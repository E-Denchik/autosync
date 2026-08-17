import os

from app.extensions import db
from app.models import (
    ConfidenceLevel,
    Contract,
    ContractLaborNorm,
    ContractPart,
    DocumentProcessingStatus,
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.repair_order_processor import process_upload_job

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "testdata")
REPAIR_ORDER_FILE = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")


def test_process_upload_job_matches_against_pre_populated_contract_catalog(app):
    with app.app_context():
        contract = Contract(
            name="Контракт по HYUNDAI",
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()

        db.session.add(
            ContractPart(
                contract_id=contract.id,
                article="PN32661 [AUTOWELT]",
                name="Поршень с кольцами (авторитетное наименование)",
                price=9999.0,
            )
        )
        db.session.add(
            ContractLaborNorm(
                contract_id=contract.id,
                operation_name="ДВС снятие",
                vehicle_make="HYUNDAI",
                vehicle_model="IX35",
                norm_hours=28.0,
            )
        )
        db.session.commit()
        contract_id = contract.id

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        result = process_upload_job(contract.id, repair_order.id)

        assert result["status"] == "ok"

        repair_order = db.session.get(RepairOrder, repair_order_id)
        assert repair_order.status == RepairOrderStatus.NEEDS_REVIEW
        assert repair_order.vehicle_make == "HYUNDAI"
        assert repair_order.vehicle_model == "IX35"

        parts_count_after = ContractPart.query.filter_by(contract_id=contract_id).count()
        assert parts_count_after == 1

        exact_match = PartMatch.query.filter_by(
            repair_order_id=repair_order_id, matched_article="PN32661 [AUTOWELT]"
        ).first()
        assert exact_match is not None
        assert exact_match.confidence_level == ConfidenceLevel.EXACT
        assert float(exact_match.matched_price) == 9999.0
        assert exact_match.matched_name == "Поршень с кольцами (авторитетное наименование)"

        labor_match = LaborLine.query.filter_by(
            repair_order_id=repair_order_id, matched_operation_name="ДВС снятие"
        ).first()
        assert labor_match is not None
        assert labor_match.confidence_level == ConfidenceLevel.EXACT
        assert float(labor_match.norm_hours) == 28.0


def test_process_upload_job_fails_gracefully_on_broken_repair_order_file(app):
    with app.app_context():
        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.txt",
            storage_path="/tmp/does-not-exist.txt",
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        result = process_upload_job(contract.id, repair_order.id)

        assert result["status"] == "failed"
        repair_order = db.session.get(RepairOrder, repair_order_id)
        assert repair_order.status == RepairOrderStatus.FAILED
