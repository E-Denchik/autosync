import os

from app.extensions import db
from app.models import (
    ConfidenceLevel,
    Contract,
    ContractHourlyRate,
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
RATE_TABLE_DOCX = os.path.join(TESTDATA_DIR, "Нормочасы.docx")


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
        db.session.add(ContractHourlyRate(contract_id=contract.id, vehicle_make="HYUNDAI", hourly_rate=1170.0))
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
        assert float(labor_match.hourly_rate) == 1170.0
        assert float(labor_match.total_cost) == 28.0 * 1170.0


def test_process_upload_job_falls_back_to_norm_hours_stated_in_repair_order_when_nothing_matched(app):
    """Регрессия по реальным данным заказчика: у "Управление дорог" нет ни
    каталога работ в договоре, ни доступа к AutoData/1С — но исходный
    заказ-наряд (1С-выгрузка) уже содержит норму часов по каждой операции
    (см. document_parser.parse_repair_order_export, колонка "Норма, ч").
    Раньше эта норма отбрасывалась при парсинге в _parse_repair_order_files,
    и все восемь работ уезжали на проверку с пустой нормой ("не указана"),
    хотя цифра была прямо в исходном файле."""
    with app.app_context():
        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()
        # Каталог договора пуст — ни одной ContractLaborNorm, как у
        # заказчика (98% случаев без справочника, см. PROJECT.md).

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        lines = {l.description: l for l in LaborLine.query.filter_by(repair_order_id=repair_order_id).all()}
        assert float(lines["ДВС снятие"].norm_hours) == 28.0
        assert float(lines["Блок цилиндров расточка"].norm_hours) == 6.0
        assert float(lines["Опора ДВС правая замена"].norm_hours) == 0.8
        # Каталог всё равно не подтвердил операцию — matched_operation_name
        # остаётся пустым, это не "точное совпадение", а значение из наряда.
        assert lines["ДВС снятие"].matched_operation_name is None
        assert lines["ДВС снятие"].confidence_level == ConfidenceLevel.LLM_GUESS
        assert lines["ДВС снятие"].raw_match_data["source"] == "repair_order_stated_value"


def test_process_upload_job_prefers_contract_catalog_norm_hours_over_repair_order_stated_value(app):
    """Если каталог договора всё-таки нашёл операцию — его норма часов
    (проверенная, из тендерного прайса) важнее того, что написал мехник."""
    with app.app_context():
        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()
        db.session.add(
            ContractLaborNorm(
                contract_id=contract.id,
                operation_name="ДВС снятие",
                vehicle_make="HYUNDAI",
                vehicle_model="IX35",
                norm_hours=99.0,
            )
        )
        db.session.commit()

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        labor_match = LaborLine.query.filter_by(
            repair_order_id=repair_order_id, matched_operation_name="ДВС снятие"
        ).first()
        assert float(labor_match.norm_hours) == 99.0
        assert labor_match.confidence_level == ConfidenceLevel.EXACT


def test_process_upload_job_uses_contragent_rate_when_no_contract_rate_for_make(app):
    from app.models import Contragent

    with app.app_context():
        contragent = Contragent(name="Заказчик Б", hourly_rate=1000)
        db.session.add(contragent)

        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()
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

        repair_order = RepairOrder(
            contract_id=contract.id,
            contragent_id=contragent.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        labor_match = LaborLine.query.filter_by(
            repair_order_id=repair_order_id, matched_operation_name="ДВС снятие"
        ).first()
        assert float(labor_match.hourly_rate) == 1000.0


def test_process_upload_job_prefers_contragent_make_rate_over_flat_rate(app):
    from app.models import Contragent, ContragentHourlyRate

    with app.app_context():
        contragent = Contragent(name="Заказчик В", hourly_rate=1000)
        db.session.add(contragent)
        db.session.flush()
        db.session.add(ContragentHourlyRate(contragent_id=contragent.id, vehicle_make="HYUNDAI", hourly_rate=1350.0))

        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()
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

        repair_order = RepairOrder(
            contract_id=contract.id,
            contragent_id=contragent.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        labor_match = LaborLine.query.filter_by(
            repair_order_id=repair_order_id, matched_operation_name="ДВС снятие"
        ).first()
        # HYUNDAI-специфичная ставка контрагента (1350) должна победить его же
        # общую плоскую ставку (1000), но контрактная ставка по-прежнему в
        # приоритете, если бы она была задана (см. предыдущий тест).
        assert float(labor_match.hourly_rate) == 1350.0


def test_process_upload_job_matches_contract_rate_regardless_of_vehicle_make_letter_case(app):
    """Регрессия: заказ-наряд (1С-выгрузка) обычно кладёт марку заглавными
    ("HYUNDAI"), а ставку по марке оператор вводит вручную через UI и может
    написать как угодно ("Hyundai") — раньше сравнение было точным строковым,
    несовпадение регистра молча откатывалось на общую ставку вместо
    найденной по марке."""
    with app.app_context():
        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()
        db.session.add(ContractHourlyRate(contract_id=contract.id, vehicle_make="Hyundai", hourly_rate=1170.0))
        db.session.commit()

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,  # парсится с vehicle_make="HYUNDAI"
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        any_labor_line = LaborLine.query.filter_by(repair_order_id=repair_order_id).first()
        assert float(any_labor_line.hourly_rate) == 1170.0


def test_process_upload_job_matches_contragent_rate_regardless_of_vehicle_make_letter_case(app):
    from app.models import Contragent, ContragentHourlyRate

    with app.app_context():
        contragent = Contragent(name="Заказчик Г", hourly_rate=1000)
        db.session.add(contragent)
        db.session.flush()
        db.session.add(ContragentHourlyRate(contragent_id=contragent.id, vehicle_make="hyundai", hourly_rate=800.0))

        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.commit()

        repair_order = RepairOrder(
            contract_id=contract.id,
            contragent_id=contragent.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,  # парсится с vehicle_make="HYUNDAI"
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        any_labor_line = LaborLine.query.filter_by(repair_order_id=repair_order_id).first()
        assert float(any_labor_line.hourly_rate) == 800.0


def test_process_upload_job_matches_contract_labor_norm_regardless_of_vehicle_make_letter_case(app):
    with app.app_context():
        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()
        db.session.add(
            ContractLaborNorm(
                contract_id=contract.id,
                operation_name="ДВС снятие",
                vehicle_make="Hyundai",
                vehicle_model="IX35",
                norm_hours=28.0,
            )
        )
        db.session.commit()

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,  # парсится с vehicle_make="HYUNDAI"
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        labor_match = LaborLine.query.filter_by(
            repair_order_id=repair_order_id, matched_operation_name="ДВС снятие"
        ).first()
        assert labor_match is not None
        assert labor_match.confidence_level == ConfidenceLevel.EXACT
        assert float(labor_match.norm_hours) == 28.0


def test_process_upload_job_uses_model_specific_rate_from_real_customer_rate_table(app):
    """Сквозной регресс на реальных файлах заказчика: тендерный прайс-лист
    (Нормочасы.docx) даёт РАЗНЫЕ ставки для разных моделей Hyundai — Accent/
    Sonata по 720 ₽, Tucson/IX35/Santa Fe по 810 ₽. Реальный заказ-наряд
    (тест 1 (исходник).xlsx) — как раз про Hyundai IX35, должен взять
    именно 810, а не 720 (другая модель) и не первую попавшуюся ставку по
    марке "Hyundai" вообще."""
    from app.models import Contragent, ContragentHourlyRate
    from app.services.hourly_rate_import import import_hourly_rates

    with app.app_context():
        contragent = Contragent(name="Управление дорог", hourly_rate=1000)
        db.session.add(contragent)
        db.session.flush()
        result = import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent.id, RATE_TABLE_DOCX)
        assert result["created"] == 15

        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.commit()

        repair_order = RepairOrder(
            contract_id=contract.id,
            contragent_id=contragent.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,  # парсится с vehicle_make="HYUNDAI", vehicle_model="IX35"
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        repair_order_id = repair_order.id

        process_upload_job(contract.id, repair_order.id)

        any_labor_line = LaborLine.query.filter_by(repair_order_id=repair_order_id).first()
        assert float(any_labor_line.hourly_rate) == 810.0


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


def test_process_upload_job_marks_contract_failed_instead_of_hanging_on_unexpected_import_error(app, monkeypatch):
    with app.app_context():
        contract = Contract(
            original_filename="c.xlsx",
            storage_path="/tmp/c.xlsx",
            status=DocumentProcessingStatus.UPLOADED,
        )
        db.session.add(contract)
        db.session.flush()

        repair_order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=REPAIR_ORDER_FILE,
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(repair_order)
        db.session.commit()
        contract_id = contract.id
        repair_order_id = repair_order.id

        def _boom(*args, **kwargs):
            raise RuntimeError("неожиданная ошибка парсинга договора")

        monkeypatch.setattr("app.services.repair_order_processor.import_contract_files", _boom)

        result = process_upload_job(contract_id, repair_order_id)

        assert result["status"] == "failed"
        contract = db.session.get(Contract, contract_id)
        assert contract.status == DocumentProcessingStatus.FAILED
        repair_order = db.session.get(RepairOrder, repair_order_id)
        assert repair_order.status == RepairOrderStatus.FAILED
