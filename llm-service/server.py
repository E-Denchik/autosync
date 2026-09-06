"""Тонкая обёртка над локальными LLM-раннерами, отдаёт единые /models и
/generate эндпоинты.

Backend (llm_client.py) обращается сюда по HTTP, а не к Ollama/LM Studio
напрямую — раннер или модель можно заменить, не трогая backend
(см. ARCHITECTURE.md: «LLM как отдельный сервис»).

Поддержаны два локальных раннера, которые пользователь может держать на
своей машине одновременно, плюс один облачный:
  - Ollama          — HTTP API на OLLAMA_BASE_URL (по умолчанию localhost:11434)
  - LM Studio       — Local Server (OpenAI-совместимый) на LMSTUDIO_BASE_URL
                       (по умолчанию localhost:1234/v1)
  - vsegpt.ru       — облачный OpenAI-совместимый шлюз к внешним моделям
                       (GPT/Claude/Gemini и т.п.), нужен API-ключ. В отличие
                       от Ollama/LM Studio ключ не живёт на этой машине как
                       переменная окружения — администратор вводит его в UI
                       (Администрирование → Интеграции), backend хранит его в
                       БД и передаёт с каждым запросом сюда (заголовок
                       X-VseGPT-Api-Key для GET /models, поле "api_key" в теле
                       POST /generate) — сам llm-service ключ нигде не хранит.

Какую из моделей реально использовать — решает администратор в UI
(Настройки → LLM), backend хранит выбор в БД и передаёт provider+model
с каждым запросом сюда (см. app/services/llm_settings.py). Если backend
их не передал (прямой curl, обратная совместимость) — используются
переменные окружения LLM_PROVIDER/LLM_MODEL_NAME как раньше.
"""

from __future__ import annotations

import glob
import logging
import os
import threading
import time

import requests
from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

app = Flask(__name__)


class RunnerError(RuntimeError):
    """Раннер/шлюз ответил ошибкой (не 2xx). В отличие от голого
    RuntimeError несёт исходный HTTP-статус — по нему /generate ниже
    решает, пробрасывать ли его как есть (4xx — неверный ключ, кончился
    баланс, битый запрос: постоянная причина, backend такое НЕ ретраит,
    см. LLMClient._generate: retry только на >=500) или завернуть в общий
    502 (5xx/непонятно что — может быть, раннер просто занят/грузится,
    имеет смысл попробовать ещё раз)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _error_detail(resp: requests.Response) -> str:
    """Достаёт читаемое сообщение из тела ответа раннера, а не отдаёт сырой
    JSON как есть — и Ollama ({"error": "текст"}), и OpenAI-совместимые
    шлюзы, vsegpt.ru/LM Studio ({"error": {"message": "текст", "code": N}}).
    Если тело не JSON или не в одном из этих двух видов — возвращает текст
    ответа как есть: лучше сырой текст, чем скрыть неожиданную форму ошибки."""
    try:
        data = resp.json()
    except ValueError:
        return resp.text
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(error, str) and error:
        return error
    return resp.text


def _vsegpt_error_message(status_code: int, resp: requests.Response) -> str:
    """Понятное человеку объяснение — ПЕРЕД техническими деталями, а не
    вместо них (см. _error_detail), чтобы при обращении в поддержку было
    что показать. Распознаёт частые, ожидаемые случаи; для остального —
    только сырой (но уже без лишней вложенности JSON) текст ошибки, не
    выдумываем причину, если она не очевидна."""
    detail = _error_detail(resp)
    lowered = detail.lower()
    if status_code == 400 and ("on account" in lowered or "balance" in lowered):
        human = "Закончился баланс на аккаунте vsegpt.ru — пополните на https://vsegpt.ru/User/Money"
    elif status_code == 429:
        human = "vsegpt.ru ограничивает скорость запросов — попробуйте ещё раз через несколько секунд"
    elif status_code in (401, 403):
        human = "vsegpt.ru не принял API-ключ — проверьте его в Администрирование → LLM-модель"
    else:
        return f"vsegpt -> {status_code}: {detail}"
    return f"{human} (vsegpt -> {status_code}: {detail})"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
# Не секрет — просто адрес шлюза, сам ключ приходит с каждым запросом отдельно
# (см. докстринг модуля), а не читается из окружения этого процесса.
VSEGPT_BASE_URL = os.environ.get("VSEGPT_BASE_URL", "https://api.vsegpt.ru/v1")

DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")
DEFAULT_MODEL = os.environ.get("LLM_MODEL_NAME", "qwen2.5:14b")

# LM Studio хранит скачанные .gguf либо в новом расположении (~/.lmstudio),
# либо в старом (~/.cache/lm-studio) — на разных версиях приложения.
LMSTUDIO_MODEL_DIRS = [
    os.path.expanduser("~/.lmstudio/models"),
    os.path.expanduser("~/.cache/lm-studio/models"),
]

# vsegpt.ru жёстко ограничивает 1 запрос/сек НА КЛЮЧ (по всем эндпоинтам —
# и /models, и /chat/completions), а backend умеет параллелить несколько
# запросов сразу (см. app/services/parallel.py: до 4 одновременно — для
# локальных Ollama/LM Studio это ускоряет разбор больших заказ-нарядов, они
# нормально обслуживают параллельные запросы к уже загруженной модели). Для
# vsegpt.ru этот же параллелизм только вредит: 3 из 4 запросов сразу
# получают 429 "Rate-limit error", уходят в повтор с задержкой (см.
# LLMClient._generate) — реальная задержка суммарно оказывается БОЛЬШЕ, чем
# если бы запросы изначально шли по одному в темпе лимита. Поэтому здесь,
# в единственном месте, где реально идёт исходящий HTTP к vsegpt.ru,
# запросы сериализуются с шагом чуть больше 1с — независимо от того,
# сколько потоков backend вызвало сюда одновременно.
_VSEGPT_MIN_INTERVAL_SECONDS = 1.1
_vsegpt_rate_lock = threading.Lock()
_vsegpt_last_request_at = 0.0
_vsegpt_stats_lock = threading.Lock()
_vsegpt_stats = {"requests": 0, "successes": 0, "errors": 0}


def _throttle_vsegpt() -> None:
    global _vsegpt_last_request_at
    with _vsegpt_rate_lock:
        wait = _vsegpt_last_request_at + _VSEGPT_MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _vsegpt_last_request_at = time.monotonic()


# Без явного max_tokens шлюз/модель подставляют свой умолчательный лимит
# вывода (у части моделей за vsegpt.ru это заметно меньше, чем реально
# нужно на JSON-таблицу из ocr_table_extraction.md) — на практике это
# приводило к тому, что ответ обрывался почти на КАЖДОМ куске текста
# (см. LLMClient._recover_truncated_rows: раньше просто восстанавливали,
# что успело прийти, теперь по возможности не допускаем обрыв вовсе).
# Значение с запасом под самый крупный кусок (см. llm_client.py: узкие
# таблицы — 4000 символов исходного текста на кусок, это заведомо меньше,
# чем 8000 токенов ответа даже для многословного JSON.
_VSEGPT_MAX_TOKENS = 8000
_LOCAL_RUNNER_TIMEOUT_SECONDS = int(os.environ.get("AUTOSYNC_LLM_TIMEOUT_SECONDS", "300")) - 5


def discover_ollama() -> dict:
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        resp.raise_for_status()
    except requests.RequestException:
        return {"available": False, "models": []}

    models = []
    for m in resp.json().get("models", []):
        # "details" — реальные метаданные модели (параметры, квантование),
        # которые Ollama отдаёт в /api/tags, но не гарантированно на всех
        # версиях/форматах моделей — .get() дважды, без исключений: backend
        # (см. model_capability.py) сам умеет откатиться на оценку по имени,
        # если parameter_size здесь пуст.
        details = m.get("details") or {}
        models.append(
            {
                "name": m["name"],
                "size": m.get("size"),
                "modified_at": m.get("modified_at"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
            }
        )
    return {"available": True, "models": models}


def _scan_lmstudio_filesystem() -> list[str]:
    """Best-effort скан каталогов LM Studio на диске — находит модели, даже
    если Local Server сейчас выключен (пользователь просто не открыл
    приложение). Идентификатор модели — путь относительно каталога models
    без расширения .gguf, ровно так LM Studio называет модели в своём API."""
    found: set[str] = set()
    for root in LMSTUDIO_MODEL_DIRS:
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "*.gguf"), recursive=True):
            rel = os.path.relpath(path, root)
            found.add(rel[: -len(".gguf")] if rel.endswith(".gguf") else rel)
    return sorted(found)


def discover_lmstudio() -> dict:
    try:
        resp = requests.get(f"{LMSTUDIO_BASE_URL}/models", timeout=3)
        resp.raise_for_status()
        names = [m["id"] for m in resp.json().get("data", [])]
        return {"available": True, "server_running": True, "models": [{"name": n} for n in names]}
    except requests.RequestException:
        pass

    # Local Server выключен — покажем то, что найдено на диске, но пометим
    # как недоступное для генерации прямо сейчас (нужно включить сервер в
    # приложении LM Studio).
    names = _scan_lmstudio_filesystem()
    return {"available": bool(names), "server_running": False, "models": [{"name": n} for n in names]}


def discover_vsegpt(api_key: str | None) -> dict:
    """Список моделей, доступных на vsegpt.ru с этим ключом — в отличие от
    Ollama/LM Studio, это не "что скачано на диске", а "что открыто по
    подписке/балансу этого ключа". Без ключа даже не пробуем сходить в
    сеть — это ожидаемое "не настроено", а не сбой."""
    if not api_key:
        return {"available": False, "models": [], "configured": False}

    status = get_vsegpt_status(api_key)
    _throttle_vsegpt()
    try:
        resp = requests.get(
            f"{VSEGPT_BASE_URL}/models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=5,
        )
    except requests.RequestException as exc:
        # Нет сети до vsegpt.ru и т.п. — не роняем discovery целиком
        # (Ollama/LM Studio могли ответить нормально), просто помечаем
        # этот провайдер недоступным с причиной для UI.
        return {"available": False, "models": [], "configured": True, "error": str(exc), "status": status}

    if not resp.ok:
        # Не голое "400 Client Error: Bad Request" (это отдавал бы
        # resp.raise_for_status()) — та же читаемая причина, что и при
        # реальной генерации (см. _vsegpt_error_message): неверный ключ,
        # кончился баланс и т.п. видно сразу на странице настроек LLM, а
        # не только когда дело дойдёт до первого реального запроса.
        return {
            "available": False,
            "models": [],
            "configured": True,
            "error": _vsegpt_error_message(resp.status_code, resp),
            "status": status,
        }

    try:
        entries = resp.json().get("data", [])
        models = [{"name": m["id"]} for m in entries if "id" in m]
    except (ValueError, AttributeError, TypeError):
        return {
            "available": False,
            "models": [],
            "configured": True,
            "error": "vsegpt.ru вернул неожиданный ответ",
            "status": status,
        }

    balance = status.get("balance")
    balance_blocked = balance is None or balance <= 0
    unavailable_reason = "balance_unknown" if balance is None else "non_positive_balance"
    return {
        "available": not balance_blocked,
        "models": models,
        "configured": True,
        "temporarily_unavailable": balance_blocked,
        "reason": unavailable_reason if balance_blocked else None,
        "error": (
            "Не удалось подтвердить баланс vsegpt.ru — выбор моделей временно заблокирован"
            if balance is None
            else "Баланс vsegpt.ru равен нулю или меньше нуля — выбор моделей временно заблокирован"
            if balance_blocked
            else None
        ),
        "status": status,
    }


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_vsegpt_status(api_key: str | None) -> dict:
    """Получает баланс и статус аккаунта из официального v1/balance —
    ровно то же самое, что видно в личном кабинете на vsegpt.ru.

    Реальная форма ответа (см. https://vsegpt.ru/Docs/API/Code):
        {"status": "ok", "data": {
            "credits": "10.752448",
            "subscription_status": "ok",
            "subscription_end": "2024-05-02 00:08:02",
            "user_status": 1,
            "user_status_text": "Less than 500 credits on account."
        }}
    Раньше здесь читалось несуществующее поле "balance" (и ещё несколько
    угаданных "currency"/"spent"/"requests_made"/"requests_remaining",
    которых в реальном ответе API вообще нет) — баланс всегда приходил
    None, хотя ключ был рабочим. "credits" — приоритетное имя поля,
    "balance" оставлен как запасной вариант на случай более старой версии
    API (см. её прежнее упоминание в этом докстринге про смену формы
    ответа между версиями)."""
    if not api_key:
        return {"configured": False, "available": False}
    _throttle_vsegpt()
    try:
        resp = requests.get(
            f"{VSEGPT_BASE_URL}/balance",
            headers={"Authorization": "Bearer " + api_key},
            timeout=5,
        )
    except requests.RequestException as exc:
        return {"configured": True, "available": False, "error": str(exc)}
    if not resp.ok:
        return {
            "configured": True,
            "available": False,
            "error": _vsegpt_error_message(resp.status_code, resp),
        }
    try:
        payload = resp.json()
    except ValueError:
        return {"configured": True, "available": False, "error": "vsegpt.ru вернул неожиданный ответ"}
    if isinstance(payload, dict) and payload.get("status") == "error":
        # /v1/balance — единственный эндпоинт vsegpt.ru, где отказ (например,
        # несуществующий ключ) приходит с HTTP 200 вместо кода ошибки: то же
        # самое "User with this API key not found" на /v1/chat/completions
        # отдаётся с honest 400 и уже нормально ловится веткой `not resp.ok`
        # ниже по коду (см. _vsegpt_error_message). Без этой проверки такой
        # ответ тихо падал в balance=None и превращался в бессмысленное
        # "не удалось подтвердить баланс" без единой причины.
        reason = payload.get("reason")
        return {
            "configured": True,
            "available": False,
            "error": f"vsegpt.ru отклонил запрос: {reason}" if reason else "vsegpt.ru отклонил запрос баланса",
        }
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return {"configured": True, "available": False, "error": "vsegpt.ru вернул неожиданный ответ"}
    balance = _number(data.get("credits") if data.get("credits") is not None else data.get("balance"))
    if balance is None:
        # Ключ принят (иначе выше уже вернули бы _vsegpt_error_message на
        # non-2xx), но ни "credits", ни "balance" не удалось разобрать в
        # число — раньше это тихо превращалось в голое "available": False
        # без единой зацепки, почему (integrations.py показывал пользователю
        # только заглушку "Не удалось подтвердить баланс vsegpt.ru"). Логируем
        # сырой ответ для диагностики и, если сам vsegpt.ru прислал
        # человеко-читаемое пояснение (user_status_text — например, про
        # неактивную подписку), показываем его вместо голой заглушки.
        logger.warning("vsegpt.ru /v1/balance: не удалось получить числовой баланс, сырой ответ: %r", data)
    result = {
        "configured": True,
        "available": balance is not None,
        "balance": balance,
        "error": (
            f"Не удалось получить баланс vsegpt.ru из ответа сервера ({data.get('user_status_text')})"
            if balance is None and data.get("user_status_text")
            else "Не удалось получить баланс vsegpt.ru из ответа сервера"
            if balance is None
            else None
        ),
        # 0/1/2 — тот же светофор ("зелёный"/"жёлтый"/"красный"), что
        # показан в профиле на vsegpt.ru; user_status_text — их же
        # человеко-читаемое пояснение (например, "Less than 500 credits on
        # account."), не переводим и не переформулируем — это сообщение
        # самого vsegpt.ru, оно может обновиться на их стороне.
        "user_status": data.get("user_status"),
        "user_status_text": data.get("user_status_text"),
        "subscription_status": data.get("subscription_status"),
        "subscription_end": data.get("subscription_end"),
    }
    with _vsegpt_stats_lock:
        result["local_requests"] = _vsegpt_stats["requests"]
        result["local_successes"] = _vsegpt_stats["successes"]
        result["local_errors"] = _vsegpt_stats["errors"]
    return result


@app.get("/health")
def health():
    return jsonify(status="ok", provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL)


@app.get("/models")
def models():
    """Что доступно для использования: скачанное на этой машине (Ollama, LM
    Studio) плюс облачные модели vsegpt.ru, если backend передал ключ
    (см. X-VseGPT-Api-Key в докстринге модуля) — для UI выбора модели админом."""
    vsegpt_api_key = request.headers.get("X-VseGPT-Api-Key")
    return jsonify(
        providers={
            "ollama": discover_ollama(),
            "lmstudio": discover_lmstudio(),
            "vsegpt": discover_vsegpt(vsegpt_api_key),
        }
    )


@app.get("/vsegpt/status")
def vsegpt_status():
    return jsonify(get_vsegpt_status(request.headers.get("X-VseGPT-Api-Key")))


def _generate_ollama(model: str, prompt: str, json_response: bool) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if json_response:
        payload["format"] = "json"

    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=_LOCAL_RUNNER_TIMEOUT_SECONDS
    )
    if not resp.ok:
        raise RunnerError(f"ollama -> {resp.status_code}: {_error_detail(resp)}", status_code=resp.status_code)
    return resp.json().get("response", "")


def _generate_lmstudio(model: str, prompt: str, json_response: bool) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if json_response:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(
        f"{LMSTUDIO_BASE_URL}/chat/completions", json=payload, timeout=_LOCAL_RUNNER_TIMEOUT_SECONDS
    )
    if not resp.ok:
        raise RunnerError(f"lmstudio -> {resp.status_code}: {_error_detail(resp)}", status_code=resp.status_code)
    return resp.json()["choices"][0]["message"]["content"]


def _generate_vsegpt(model: str, prompt: str, json_response: bool, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": _VSEGPT_MAX_TOKENS,
    }
    if json_response:
        payload["response_format"] = {"type": "json_object"}

    _throttle_vsegpt()
    with _vsegpt_stats_lock:
        _vsegpt_stats["requests"] += 1
    resp = requests.post(
        f"{VSEGPT_BASE_URL}/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer " + api_key},
        timeout=180,
    )
    if not resp.ok:
        with _vsegpt_stats_lock:
            _vsegpt_stats["errors"] += 1
        raise RunnerError(_vsegpt_error_message(resp.status_code, resp), status_code=resp.status_code)
    with _vsegpt_stats_lock:
        _vsegpt_stats["successes"] += 1
    return resp.json()["choices"][0]["message"]["content"]


@app.post("/generate")
def generate():
    body = request.get_json(force=True) or {}
    prompt = body.get("prompt")
    if not prompt:
        return jsonify(error="'prompt' обязателен"), 400

    json_response = bool(body.get("json_response", False))
    provider = body.get("provider") or DEFAULT_PROVIDER
    model = body.get("model") or DEFAULT_MODEL

    try:
        if provider == "lmstudio":
            text = _generate_lmstudio(model, prompt, json_response)
        elif provider == "vsegpt":
            api_key = body.get("api_key")
            if not api_key:
                return jsonify(error="Для vsegpt.ru нужен API-ключ — добавьте его в Администрирование → Интеграции"), 400
            text = _generate_vsegpt(model, prompt, json_response, api_key)
        else:
            text = _generate_ollama(model, prompt, json_response)
    except RunnerError as exc:
        # 4xx от самого раннера/шлюза (неверный ключ, кончился баланс,
        # битый запрос) — постоянная причина: backend её всё равно не
        # ретраит на >=500 (см. LLMClient._generate), значит незачем
        # заворачивать в общий 502, который выглядел бы как временный сбой.
        # Экономит и время (не ждём 2 бесполезных повтора x 2с задержки на
        # КАЖДЫЙ кусок большого файла), и деньги — не тратим лишние попытки
        # обратиться к платному vsegpt.ru с запросом, который заведомо не
        # пройдёт. Настоящие 5xx/непонятный статус — как и раньше, 502
        # (может, раннер просто занят/грузится — тут повтор имеет смысл).
        status = exc.status_code if exc.status_code and exc.status_code < 500 else 502
        return jsonify(error=str(exc)), status
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 502
    except requests.exceptions.RequestException as exc:
        # Таймаут/обрыв соединения к Ollama/LM Studio (модель ещё грузится в
        # память на первом запросе после простоя, раннер занят другим
        # запросом и т.п.) — не RuntimeError, поэтому раньше пролетало мимо
        # except выше и падало как НЕПОЙМАННОЕ исключение: Flask отдавал
        # голую стандартную страницу 500 без единого объяснения причины, а
        # backend (llm_client.py) эту страницу видел как "llm-service -> 500:
        # The server encountered an internal error..." и ретраи для нём не
        # делал (ретраит только полную недоступность llm-service, а тут
        # llm-service отвечает нормально — это раннер внутри подвёл).
        # Теперь это понятная ошибка с 502, которую backend вдобавок
        # ретраит (см. LLMClient._generate).
        return jsonify(error=f"{provider} не ответил вовремя: {exc}"), 502
    except (ValueError, KeyError, IndexError) as exc:
        # resp.json() / ["choices"][0]["message"]["content"] — раннер
        # ответил 200, но с телом не той формы, которую мы ожидаем (другая
        # версия API, пустой ответ и т.п.). Тоже не RuntimeError — та же
        # история с голой страницей 500 без объяснения.
        return jsonify(error=f"{provider} вернул неожиданный ответ: {exc}"), 502

    return jsonify(text=text)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
