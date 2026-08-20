from app.services.parts_supplier_client import AggregatedPartsSupplierClient, build_configured_supplier_client


class _StubClient:
    def __init__(self, refs=None, error=None):
        self._refs = refs or []
        self._error = error

    def find_cross_references(self, article, brand=None):
        if self._error:
            raise self._error
        return self._refs


def test_aggregated_client_merges_results_from_all_suppliers():
    client = AggregatedPartsSupplierClient(
        [
            _StubClient(refs=[{"article": "A-1", "brand": "KYB"}]),
            _StubClient(refs=[{"article": "A-2", "brand": "Sachs"}]),
        ]
    )
    refs = client.find_cross_references("333114")
    assert {r["article"] for r in refs} == {"A-1", "A-2"}


def test_aggregated_client_dedupes_by_article():
    client = AggregatedPartsSupplierClient(
        [
            _StubClient(refs=[{"article": "A-1", "brand": "KYB"}]),
            _StubClient(refs=[{"article": "A-1", "brand": "KYB (partner)"}]),
        ]
    )
    refs = client.find_cross_references("333114")
    assert len(refs) == 1
    assert refs[0]["brand"] == "KYB"


def test_aggregated_client_skips_a_failing_supplier_without_raising():
    client = AggregatedPartsSupplierClient(
        [
            _StubClient(error=RuntimeError("network down")),
            _StubClient(refs=[{"article": "A-2", "brand": "Sachs"}]),
        ]
    )
    refs = client.find_cross_references("333114")
    assert refs == [{"article": "A-2", "brand": "Sachs"}]


def test_build_configured_supplier_client_only_includes_configured_suppliers():
    cfg = {
        "PARTS_SUPPLIER_BASE_URL": "",
        "PARTS_SUPPLIER_API_KEY": "",
        "ROSSCO_KEY1": "k1",
        "ROSSCO_KEY2": "k2",
        "AUTOEURO_API_KEY": "",
        "MOSKVORECHYE_BASE_URL": "",
        "MOSKVORECHYE_API_KEY": "",
    }
    client = build_configured_supplier_client(cfg)
    assert len(client._clients) == 1
    assert type(client._clients[0]).__name__ == "RosscoClient"


def test_build_configured_supplier_client_with_nothing_configured_is_empty():
    cfg = {
        "PARTS_SUPPLIER_BASE_URL": "",
        "PARTS_SUPPLIER_API_KEY": "",
        "ROSSCO_KEY1": "",
        "ROSSCO_KEY2": "",
        "AUTOEURO_API_KEY": "",
        "MOSKVORECHYE_BASE_URL": "",
        "MOSKVORECHYE_API_KEY": "",
    }
    client = build_configured_supplier_client(cfg)
    assert client._clients == []
    assert client.find_cross_references("333114") == []
