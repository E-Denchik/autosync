"""Поиск позиций у поставщиков запчастей (Rossco/АвтоЕвро/Москворечье) по
артикулу/бренду для ручного подбора оператором — отдельная задача от
app/services/parts_supplier_client.py (тот копит кросс-номера для
автоматического сопоставления заказ-наряда, этот — отдаёт результат и
ошибку по каждому поставщику отдельно, чтобы UI мог показать, где именно
не получилось подключиться и что нужно сделать, см.
app/api/parts_suppliers.py).
"""

from __future__ import annotations

from app.services.autoeuro_client import AutoEuroClient, AutoEuroError
from app.services.moskvorechye_client import MoskvorechyeClient, MoskvorechyeError
from app.services.rossco_client import RosscoClient, RosscoError

SUPPLIERS = [
    {"id": "rossco", "name": "Rossco"},
    {"id": "autoeuro", "name": "АвтоЕвро"},
    {"id": "moskvorechye", "name": "Москворечье"},
]


def _rossco_status(cfg) -> tuple[RosscoClient | None, str | None]:
    if not (cfg["ROSSCO_KEY1"] and cfg["ROSSCO_KEY2"]):
        return None, "Не заданы ключи Key1/Key2 — задайте их в Администрирование → Интеграции → Rossco."
    return RosscoClient(cfg["ROSSCO_KEY1"], cfg["ROSSCO_KEY2"]), None


def _autoeuro_status(cfg) -> tuple[AutoEuroClient | None, str | None]:
    if not cfg["AUTOEURO_API_KEY"]:
        return None, "Не задан API-ключ — задайте его в Администрирование → Интеграции → АвтоЕвро."
    return AutoEuroClient(cfg["AUTOEURO_API_KEY"]), None


def _moskvorechye_status(cfg) -> tuple[MoskvorechyeClient | None, str | None]:
    if not cfg["MOSKVORECHYE_BASE_URL"]:
        return None, (
            "Не задан базовый URL веб-службы — узнайте его у менеджера Москворечье "
            "(обычно вида https://<reseller>.abcp2b.ru) и задайте в "
            "Администрирование → Интеграции → Москворечье."
        )
    if not cfg["MOSKVORECHYE_API_KEY"]:
        return None, "Не задан ключ доступа — задайте его в Администрирование → Интеграции → Москворечье."
    return MoskvorechyeClient(cfg["MOSKVORECHYE_BASE_URL"], cfg["MOSKVORECHYE_API_KEY"]), None


_BUILDERS = {
    "rossco": _rossco_status,
    "autoeuro": _autoeuro_status,
    "moskvorechye": _moskvorechye_status,
}

_ERRORS = (RosscoError, AutoEuroError, MoskvorechyeError)


def search_all_suppliers(cfg, article: str, brand: str | None = None) -> dict:
    """Опрашивает все три поставщика по очереди (не параллельно — три
    независимых внешних API, не стоит усложнять пулом потоков ради формы
    поиска, которая и так ждёт человека). Каждый поставщик — либо строка в
    results, либо в errors с понятной причиной и что делать, либо в
    not_configured, если ключей вообще нет."""
    results: list[dict] = []
    errors: list[dict] = []
    not_configured: list[dict] = []

    for supplier in SUPPLIERS:
        supplier_id = supplier["id"]
        client, hint = _BUILDERS[supplier_id](cfg)
        if client is None:
            not_configured.append({"supplier": supplier_id, "supplier_name": supplier["name"], "hint": hint})
            continue
        try:
            items = client.search_all(article, brand=brand)
        except _ERRORS as exc:
            errors.append({"supplier": supplier_id, "supplier_name": supplier["name"], "message": str(exc)})
            continue
        except Exception as exc:  # сеть/таймаут/что угодно неожиданное — тоже не 500, а понятная строка
            errors.append(
                {"supplier": supplier_id, "supplier_name": supplier["name"], "message": f"Не удалось подключиться: {exc}"}
            )
            continue
        for item in items:
            item.setdefault("supplier", supplier_id)
            item["supplier_name"] = supplier["name"]
        results.extend(items)

    return {"results": results, "errors": errors, "not_configured": not_configured}
