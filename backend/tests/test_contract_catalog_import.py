import os

from app.extensions import db
from app.models import Contract, ContractLaborNorm, ContractPart, DocumentProcessingStatus
from app.services.contract_catalog_import import import_contract_files

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "testdata")


def _make_contract(app) -> int:
    contract = Contract(
        original_filename="c.xlsx",
        storage_path="/tmp/c.xlsx",
        status=DocumentProcessingStatus.UPLOADED,
    )
    db.session.add(contract)
    db.session.commit()
    return contract.id


def test_import_from_repair_order_shaped_file_extracts_parts_and_labor_norms(app):
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        result = import_contract_files(contract_id, [path], None, llm_client=None)

        assert result["parts_created"] > 0
        assert result["labor_norms_created"] > 0

        parts = ContractPart.query.filter_by(contract_id=contract_id).all()
        assert any(p.name and "поршень" in p.name.lower() for p in parts)

        norms = ContractLaborNorm.query.filter_by(contract_id=contract_id).all()
        assert any(n.operation_name == "ДВС снятие" for n in norms)
        assert all(n.vehicle_make == "HYUNDAI" for n in norms)
        assert all(n.vehicle_model == "IX35" for n in norms)


def test_import_from_brand_catalog_file_scoped_to_requested_brand(app):
    path = os.path.join(TESTDATA_DIR, "Приложение со списком запчастей.xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        result = import_contract_files(contract_id, [path], "Chevrolet", llm_client=None)

        assert result["parts_created"] > 0
        assert result["labor_norms_created"] == 0

        count = ContractPart.query.filter_by(contract_id=contract_id).count()
        assert count == result["parts_created"]

        vw_only_article = ContractPart.query.filter_by(contract_id=contract_id, article="04E129620A").first()
        assert vw_only_article is None


def test_import_accumulates_across_multiple_files(app):
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        import_contract_files(contract_id, [path], None, llm_client=None)
        first_count = ContractPart.query.filter_by(contract_id=contract_id).count()

        import_contract_files(contract_id, [path], None, llm_client=None)
        second_count = ContractPart.query.filter_by(contract_id=contract_id).count()

        assert second_count == first_count * 2
