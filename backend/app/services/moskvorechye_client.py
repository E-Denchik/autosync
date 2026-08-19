"""Клиент API поставщика запчастей Москворечье — по формату ключа
("login:password", см. Администрирование → Интеграции) и упоминанию
поддержки на abcp@moskvorechie.ru это протокол ABCP (стандарт, которым
пользуется много региональных поставщиков через portal.moskvorechie.ru,
см. https://www.abcp.ru/wiki/API:Docs) — GET/POST, userlogin/userpsw
(md5-хэш) в параметрах, JSON-ответ.

ВАЖНО: в отличие от Rossco/АвтоЕвро, здесь НЕ подтверждён живым запросом —
официальная документация ABCP прямо говорит, что адрес хоста веб-службы
(например, https://type-a.abcp2b.ru или похожий, у каждого реселлера свой)
уточняется у менеджера поставщика, из публичного домена moskvorechie.ru не
выводится. Нужно узнать этот адрес у Москворечье и задать его в
Администрирование → Интеграции (поле "Базовый URL") — до этого клиент
явно и понятно отказывает, не отправляя запросы наугад.
"""

from __future__ import annotations

import requests


class MoskvorechyeError(RuntimeError):
    pass


class MoskvorechyeClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/") if base_url else ""
        # Ключ в формате "login:password" (см. app/api/integrations.py) —
        # не разбираем при сохранении (чтобы не испортить формат), только при использовании.
        if api_key and ":" in api_key:
            self.userlogin, self.userpsw = api_key.split(":", 1)
        else:
            self.userlogin, self.userpsw = "", ""
        self.timeout = timeout

    def _get(self, path: str, **params) -> list | dict:
        if not self.base_url:
            raise MoskvorechyeError(
                "MOSKVORECHYE_BASE_URL не задан — узнайте адрес веб-службы (host) у менеджера "
                "Москворечье (формат обычно https://<reseller>.abcp2b.ru) и укажите его в Интеграциях."
            )
        if not (self.userlogin and self.userpsw):
            raise MoskvorechyeError("MOSKVORECHYE_API_KEY не задан или не в формате login:password")
        try:
            resp = requests.get(
                f"{self.base_url}/{path}/",
                params={"userlogin": self.userlogin, "userpsw": self.userpsw, **params},
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise MoskvorechyeError(f"Москворечье недоступно: {exc}") from exc
        if not resp.ok:
            raise MoskvorechyeError(f"Москворечье -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def search_articles(self, number: str, brand: str | None = None) -> list[dict]:
        result = self._get("search/articles", number=number, brand=brand)
        return result if isinstance(result, list) else []

    def find_cross_references(self, article: str) -> list[dict]:
        """Кандидаты по артикулу (без фильтра по бренду ABCP обычно возвращает
        совпадения по нескольким брендам сразу — этим и пользуемся как
        источником кросс-номеров), по контракту, которого ждёт matcher.py."""
        try:
            items = self.search_articles(article)
        except MoskvorechyeError:
            return []
        return [
            {
                "article": item.get("articleCodeFix") or item.get("articleCode"),
                "brand": item.get("brand"),
                "name": item.get("description"),
                "price": item.get("price"),
            }
            for item in items
        ]

    def test_connection(self) -> str:
        items = self.search_articles("test-connection-check")
        return f"Подключение работает (тестовый запрос выполнен, найдено позиций: {len(items)})"
