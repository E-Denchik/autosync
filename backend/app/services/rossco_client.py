"""Клиент API поставщика запчастей Rossco (SOAP, api.rossko.ru) — цены,
наличие и кросс-номера по артикулу.

Протокол подтверждён по официальной документации (https://api.rossko.ru/,
раздел /GetSearch) и живым тестовым запросом с реальными ключами заказчика:
SOAP/WSDL, авторизация KEY1+KEY2 (пара md5-подобных строк из личного
кабинета), поиск — GetSearch(KEY1, KEY2, text, delivery_id, address_id).
delivery_id обязателен — берём "000000001" (самовывоз) по умолчанию, чтобы
не требовать address_id (тот обязателен только для доставки не самовывозом,
см. GetCheckoutDetails).
"""

from __future__ import annotations

DEFAULT_BASE_URL = "https://api.rossko.ru/service/v2.1"
PICKUP_DELIVERY_ID = "000000001"


class RosscoError(RuntimeError):
    pass


class RosscoClient:
    def __init__(self, key1: str, key2: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 15):
        self.key1 = key1
        self.key2 = key2
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _client(self, method: str):
        from zeep import Client
        from zeep.transports import Transport

        try:
            return Client(f"{self.base_url}/{method}?wsdl", transport=Transport(timeout=self.timeout))
        except Exception as exc:
            raise RosscoError(f"Rossco недоступен: {exc}") from exc

    @staticmethod
    def _serialize(result) -> dict:
        # zeep возвращает типизированные объекты (zeep.objects.*), не dict —
        # .get()/[...] на них не работают так, как на обычном ответе API.
        from zeep.helpers import serialize_object

        return serialize_object(result, target_cls=dict)

    def get_checkout_details(self) -> dict:
        if not (self.key1 and self.key2):
            raise RosscoError("ROSSCO_KEY1/ROSSCO_KEY2 не заданы")
        client = self._client("GetCheckoutDetails")
        try:
            result = self._serialize(client.service.GetCheckoutDetails(KEY1=self.key1, KEY2=self.key2))
        except RosscoError:
            raise
        except Exception as exc:
            raise RosscoError(f"Rossco GetCheckoutDetails недоступен: {exc}") from exc
        if not result.get("success"):
            raise RosscoError(result.get("message") or "Rossco: неизвестная ошибка GetCheckoutDetails")
        return result

    def search(self, text: str, delivery_id: str = PICKUP_DELIVERY_ID, address_id: int | None = None) -> dict:
        if not (self.key1 and self.key2):
            raise RosscoError("ROSSCO_KEY1/ROSSCO_KEY2 не заданы")
        client = self._client("GetSearch")
        params = {"KEY1": self.key1, "KEY2": self.key2, "text": text, "delivery_id": delivery_id}
        if address_id is not None:
            params["address_id"] = address_id
        try:
            result = self._serialize(client.service.GetSearch(**params))
        except Exception as exc:
            raise RosscoError(f"Rossco GetSearch недоступен: {exc}") from exc
        if not result.get("success"):
            raise RosscoError(result.get("message") or f"Rossco: ничего не найдено по {text!r}")
        return result

    def find_cross_references(self, article: str) -> list[dict]:
        """Кросс-номера (аналоги) для артикула — по контракту, которого ждёт
        matcher.py: список {"article": ..., "name": ..., "brand": ..., "price": ...}."""
        try:
            result = self.search(article)
        except RosscoError:
            return []
        parts = (result.get("PartsList") or {}).get("Part") or []
        if isinstance(parts, dict):
            parts = [parts]
        refs = []
        for part in parts:
            crosses = (part.get("crosses") or {}).get("Part") or []
            if isinstance(crosses, dict):
                crosses = [crosses]
            for cross in crosses:
                stocks = (cross.get("stocks") or {}).get("stock") or []
                if isinstance(stocks, dict):
                    stocks = [stocks]
                price = float(stocks[0]["price"]) if stocks else None
                refs.append(
                    {
                        "article": cross.get("partnumber"),
                        "brand": cross.get("brand"),
                        "name": cross.get("name"),
                        "price": price,
                    }
                )
        return refs

    def test_connection(self) -> str:
        details = self.get_checkout_details()
        companies = (details.get("CompanyList") or {}).get("company") or []
        if isinstance(companies, dict):
            companies = [companies]
        company_name = companies[0]["name"] if companies else "?"
        return f"Подключение работает, клиент: {company_name}"
