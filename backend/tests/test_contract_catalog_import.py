import os

import pytest

from app.extensions import db
from app.models import (
    Contract,
    ContractHourlyRate,
    ContractLaborNorm,
    ContractPart,
    DocumentProcessingStatus,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.contract_catalog_import import (
    ContractMergeError,
    import_contract_files,
    import_contract_job,
    merge_contracts,
)

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


def test_bulk_insert_parts_populates_article_normalized(app):
    """_bulk_insert_parts идёt в обход ORM (bulk_insert_mappings) — валидатор
    ContractPart._sync_article_normalized при этом не срабатывает, поэтому
    article_normalized должен выставляться явно в самой функции импорта."""
    from app.services.contract_catalog_import import _bulk_insert_parts

    with app.app_context():
        contract_id = _make_contract(app)
        _bulk_insert_parts(contract_id, [{"article": "23410-2G000", "name": "Поршень", "qty": 1, "price": 100}])
        db.session.commit()

        part = ContractPart.query.filter_by(contract_id=contract_id).first()
        assert part.article == "23410-2G000"
        assert part.article_normalized == "234102G000"


def test_reimporting_the_same_file_updates_in_place_instead_of_duplicating(app):
    """Регрессия: раньше повторная загрузка того же файла в уже
    существующий договор удваивала ContractPart на каждый повторный импорт
    (заказчик сообщил, что при повторной загрузке договора позиции
    дублируются) — теперь позиция с уже известным артикулом обновляется,
    а не создаётся заново."""
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        first_result = import_contract_files(contract_id, [path], None, llm_client=None)
        first_count = ContractPart.query.filter_by(contract_id=contract_id).count()
        assert first_result["parts_updated"] == 0

        second_result = import_contract_files(contract_id, [path], None, llm_client=None)
        second_count = ContractPart.query.filter_by(contract_id=contract_id).count()

        assert second_count == first_count
        # Строки без артикула (расходники и т.п.) не имеют естественного
        # ключа — им и дальше некуда деться, кроме как создаться заново.
        parts_without_article = ContractPart.query.filter_by(contract_id=contract_id, article=None).count()
        assert second_result["parts_created"] == parts_without_article
        assert second_result["parts_updated"] == first_result["parts_created"] - parts_without_article


def test_reimport_updates_price_when_it_changed_upstream(app):
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        import_contract_files(contract_id, [path], None, llm_client=None)

        part = ContractPart.query.filter_by(contract_id=contract_id).filter(ContractPart.article.isnot(None)).first()
        original_price = part.price
        part.price = (original_price or 0) + 999999
        db.session.commit()

        import_contract_files(contract_id, [path], None, llm_client=None)

        db.session.refresh(part)
        assert part.price == original_price


def test_merge_moves_repair_orders_and_unique_parts(app):
    with app.app_context():
        source_id = _make_contract(app)
        target_id = _make_contract(app)

        db.session.add(ContractPart(contract_id=source_id, article="A-1", name="Общая деталь", price=100))
        db.session.add(ContractPart(contract_id=source_id, article="A-2", name="Только в source", price=200))
        db.session.add(ContractPart(contract_id=target_id, article="A-1", name="Общая деталь (target)", price=999))
        db.session.add(
            RepairOrder(
                contract_id=source_id, original_filename="o.xlsx", storage_path="/tmp/o.xlsx",
                status=RepairOrderStatus.UPLOADED,
            )
        )
        db.session.commit()

        result = merge_contracts(source_id, target_id)

        assert result["repair_orders_moved"] == 1
        assert result["parts_moved"] == 1  # только A-2 — A-1 уже был в target

        assert db.session.get(Contract, source_id) is None
        assert RepairOrder.query.filter_by(contract_id=target_id).count() == 1

        target_articles = {p.article: p for p in ContractPart.query.filter_by(contract_id=target_id).all()}
        assert set(target_articles) == {"A-1", "A-2"}
        # Приоритет — у данных target, не у перенесённых.
        assert target_articles["A-1"].price == 999
        assert target_articles["A-2"].name == "Только в source"


def test_merge_moves_unique_labor_norms_and_hourly_rates(app):
    with app.app_context():
        source_id = _make_contract(app)
        target_id = _make_contract(app)

        db.session.add(ContractLaborNorm(contract_id=source_id, operation_name="Замена масла", norm_hours=1))
        db.session.add(ContractLaborNorm(contract_id=target_id, operation_name="Замена масла", norm_hours=2))
        db.session.add(ContractLaborNorm(contract_id=source_id, operation_name="Развал-схождение", norm_hours=1.5))
        db.session.add(ContractHourlyRate(contract_id=source_id, vehicle_make="KIA", hourly_rate=1000))
        db.session.add(ContractHourlyRate(contract_id=target_id, vehicle_make="KIA", hourly_rate=1500))
        db.session.add(ContractHourlyRate(contract_id=source_id, vehicle_make="HYUNDAI", hourly_rate=1100))
        db.session.commit()

        result = merge_contracts(source_id, target_id)

        assert result["labor_norms_moved"] == 1  # только "Развал-схождение"
        assert result["hourly_rates_moved"] == 1  # только HYUNDAI

        norms = {n.operation_name: n.norm_hours for n in ContractLaborNorm.query.filter_by(contract_id=target_id).all()}
        assert float(norms["Замена масла"]) == 2  # приоритет у target
        assert "Развал-схождение" in norms

        rates = {r.vehicle_make: r.hourly_rate for r in ContractHourlyRate.query.filter_by(contract_id=target_id).all()}
        assert float(rates["KIA"]) == 1500  # приоритет у target
        assert "HYUNDAI" in rates


def test_merge_rejects_same_contract():
    with pytest.raises(ContractMergeError, match="сам с собой"):
        merge_contracts(1, 1)


def test_merge_rejects_unknown_contract(app):
    with app.app_context():
        target_id = _make_contract(app)
        with pytest.raises(ContractMergeError, match="не найден"):
            merge_contracts(999999, target_id)


def test_merge_removes_source_files_from_disk(app, tmp_path):
    with app.app_context():
        source_path = tmp_path / "source.xlsx"
        source_path.write_text("dummy")
        source = Contract(original_filename="s.xlsx", storage_path=str(source_path), status=DocumentProcessingStatus.PARSED)
        target = Contract(original_filename="t.xlsx", storage_path="/tmp/t.xlsx", status=DocumentProcessingStatus.PARSED)
        db.session.add_all([source, target])
        db.session.commit()

        merge_contracts(source.id, target.id)

        assert not source_path.exists()


def test_import_contract_job_marks_failed_on_unexpected_error_instead_of_hanging(app, monkeypatch):
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)

        def _boom(*args, **kwargs):
            raise RuntimeError("неожиданная ошибка парсинга")

        monkeypatch.setattr("app.services.contract_catalog_import._bulk_insert_parts", _boom)

        result = import_contract_job(contract_id, [path], None)

        assert result["status"] == "failed"
        contract = db.session.get(Contract, contract_id)
        assert contract.status == DocumentProcessingStatus.FAILED
        assert contract.error_message is not None
