import os

import pytest

from app.extensions import db
from app.models import (
    BrandAlias,
    Contract,
    ContractHourlyRate,
    ContractLaborNorm,
    ContractPart,
    DocumentProcessingStatus,
    RawImportRow,
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

        # Заказчик: сырые строки каталога — в БД ДО того, как они стали
        # ContractPart (см. raw_import_staging.py), помечены перенесёнными
        # после того, как реально там оказались.
        staged = RawImportRow.query.filter_by(contract_id=contract_id, row_kind="catalog_part").all()
        assert len(staged) == len(parts)
        assert all(r.status == "moved" for r in staged)
        assert all(r.source_filename == "тест 1 (исходник).xlsx" for r in staged)


def test_import_from_single_sheet_section_catalog_real_customer_file(app):
    """Реальный файл заказчика (см. document_parser.
    parse_price_catalog_single_sheet_sections) — один лист вместо листа на
    марку, шапка колонок не в первой строке. import_contract_files должен
    дойти до этого парсера через цепочку фоллбэков (сначала
    parse_price_catalog_by_brand — не подходит формату, вернёт None) и
    корректно затегать позиции маркой из раздела."""
    path = os.path.join(TESTDATA_DIR, "Приложение №1 ИП Даянова З.Р..xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        result = import_contract_files(contract_id, [path], "CHEVROLET", llm_client=None)

        assert result["parts_created"] > 20000

        chevrolet_part = ContractPart.query.filter_by(contract_id=contract_id, vehicle_make="CHEVROLET").first()
        assert chevrolet_part is not None
        assert chevrolet_part.price is not None

        lada_count = ContractPart.query.filter_by(contract_id=contract_id, vehicle_make="LADA").count()
        assert lada_count > 10000


def test_import_from_brand_catalog_file_imports_all_brands_and_tags_each_row(app):
    """Регрессия: передача конкретной марки раньше ОГРАНИЧИВАЛА импорт только
    её листом — договор помечался PARSED и повторно уже не разбирался (см.
    repair_order_processor.process_upload_job: contract.status == PARSED
    пропускает import_contract_files), поэтому заказ-наряд другой марки,
    использующий тот же самый (многобрендовый!) договор, оставался вообще
    без единой запчасти для сопоставления, хотя её лист физически лежал в
    файле — реальный кейс заказчика с Lada Niva. Теперь разбираются ВСЕ
    листы сразу при любом переданном vehicle_make, и каждая строка помечена
    СВОЕЙ маркой (см. document_parser.parse_price_catalog_by_brand) — это и
    даёт matcher._contract_candidate_pool возможность не путать вкладку
    одной марки с другой при подборе по названию."""
    path = os.path.join(TESTDATA_DIR, "Приложение со списком запчастей.xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        result = import_contract_files(contract_id, [path], "Chevrolet", llm_client=None)

        assert result["parts_created"] > 0

        # Лист другой марки (Volkswagen) тоже импортирован, а не отброшен.
        vw_article = ContractPart.query.filter_by(contract_id=contract_id, article="04E129620A").first()
        assert vw_article is not None
        assert vw_article.vehicle_make == "VOLKSWAGEN"

        chevrolet_parts = ContractPart.query.filter_by(contract_id=contract_id, vehicle_make="CHEVROLET").all()
        assert len(chevrolet_parts) > 0


def test_import_from_brand_catalog_file_without_brand_imports_all_brands(app):
    """Регрессия: файл со списком запчастей по нескольким маркам одним
    файлом (разные листы Volkswagen/FORD/KIA/...) раньше разбирался
    ТОЛЬКО если явно указать марку — без неё parse_price_catalog_by_brand
    вообще не вызывалась, и разбор уходил в общий однотабличный парсер,
    который падал с "не удалось найти колонку с наименованием" (реальный
    файл заказчика так и падал). У ContractPart нет колонки "марка" —
    запчасти различаются по артикулу, поэтому без указанной марки правильно
    и безопасно взять все найденные листы сразу, а не требовать от
    пользователя по одному разу на каждую марку."""
    path = os.path.join(TESTDATA_DIR, "Приложение со списком запчастей.xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        result = import_contract_files(contract_id, [path], None, llm_client=None)

        assert result["parts_created"] > 0

        vw_article = ContractPart.query.filter_by(contract_id=contract_id, article="04E129620A").first()
        assert vw_article is not None  # Volkswagen-лист учтён
        assert vw_article.vehicle_make == "VOLKSWAGEN"

        kia_article = ContractPart.query.filter_by(contract_id=contract_id, article="AA100101A0").first()
        assert kia_article is not None  # KIA-лист тоже учтён
        assert kia_article.vehicle_make == "KIA"


def test_import_normalizes_unresolved_brand_via_llm_and_caches_to_brand_alias(app):
    """Заказчик: сохранённые данные должна проверить и адаптировать под наш
    стандарт выбранная им ИИ, а уже ПОТОМ идти сопоставление. "МАРКА XYZ" —
    заведомо нет в справочнике BrandAlias (см. builtin_brand_aliases.py) —
    после импорта ИИ должна была её нормализовать: и в ContractPart, и в
    самом справочнике (source="llm"), чтобы при следующем импорте (у ЛЮБОГО
    заказчика) это уже не требовало нового обращения к ИИ."""
    from unittest.mock import MagicMock

    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractPart(contract_id=contract_id, article="X-1", name="Деталь", price=100.0, vehicle_make="МАРКА XYZ")
        )
        db.session.commit()

        llm_client = MagicMock()
        llm_client.normalize_brand_labels.return_value = {"МАРКА XYZ": "SOME BRAND"}

        from app.services.contract_catalog_import import _normalize_unresolved_brands

        normalized = _normalize_unresolved_brands(contract_id, llm_client)
        db.session.commit()

        assert normalized == 1
        llm_client.normalize_brand_labels.assert_called_once_with(["МАРКА XYZ"])

        part = ContractPart.query.filter_by(contract_id=contract_id, article="X-1").first()
        assert part.vehicle_make == "SOME BRAND"

        alias = BrandAlias.query.filter_by(alias="МАРКА XYZ").first()
        assert alias is not None
        assert alias.canonical_make == "SOME BRAND"
        assert alias.source == "llm"


def test_import_skips_llm_normalization_when_no_client_or_nothing_unresolved(app):
    """Нет LLM под рукой (или всё и так распознано builtin-справочником) —
    не должно падать и не должно звать LLM зря."""
    from unittest.mock import MagicMock

    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractPart(contract_id=contract_id, article="X-1", name="Деталь", price=100.0, vehicle_make="TOYOTA")
        )
        db.session.commit()

        from app.services.contract_catalog_import import _normalize_unresolved_brands

        assert _normalize_unresolved_brands(contract_id, llm_client=None) == 0

        llm_client = MagicMock()
        assert _normalize_unresolved_brands(contract_id, llm_client) == 0
        llm_client.normalize_brand_labels.assert_not_called()  # TOYOTA уже известна


def test_import_llm_normalization_failure_does_not_raise(app):
    """ИИ недоступна/вернула ошибку — та же деградация, что и везде в этом
    проекте (см. matcher.py/labor_matcher.py): марка остаётся как есть,
    импорт не падает."""
    from unittest.mock import MagicMock

    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractPart(contract_id=contract_id, article="X-1", name="Деталь", price=100.0, vehicle_make="МАРКА XYZ")
        )
        db.session.commit()

        llm_client = MagicMock()
        llm_client.normalize_brand_labels.side_effect = RuntimeError("llm-service недоступен")

        from app.services.contract_catalog_import import _normalize_unresolved_brands

        assert _normalize_unresolved_brands(contract_id, llm_client) == 0

        part = ContractPart.query.filter_by(contract_id=contract_id, article="X-1").first()
        assert part.vehicle_make == "МАРКА XYZ"  # не тронуто


def test_import_supplier_price_list_xlsx(app):
    """Простой прайс-лист поставщика (Артикул/Наименование/Цена, без разбивки
    по маркам) — testdata/Тест 1 (договор - прайс-лист поставщика).xlsx,
    раньше без выделенного теста."""
    path = os.path.join(TESTDATA_DIR, "Тест 1 (договор - прайс-лист поставщика).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        result = import_contract_files(contract_id, [path], None, llm_client=None)

        assert result["parts_created"] == 47
        part = ContractPart.query.filter_by(contract_id=contract_id, article="0RF0323802B").first()
        assert part is not None
        assert part.name == "МАСЛЯНЫЙ ФИЛЬТР ДВИГАТЕЛЯ"
        assert float(part.price) == 479.9


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


def test_reimporting_the_same_file_updates_labor_norms_in_place_instead_of_duplicating(app):
    """Регрессия: в отличие от ContractPart, ContractLaborNorm при повторной
    загрузке файла норм (например, через «Добавить ещё файлы» —
    app/api/contracts.py::import_more_files) всегда только вставлялся заново,
    без проверки на уже существующую норму — список норм удваивался бы при
    каждой повторной загрузке того же файла."""
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        first_result = import_contract_files(contract_id, [path], None, llm_client=None)
        first_count = ContractLaborNorm.query.filter_by(contract_id=contract_id).count()
        assert first_result["labor_norms_created"] > 0
        assert first_result["labor_norms_updated"] == 0

        second_result = import_contract_files(contract_id, [path], None, llm_client=None)
        second_count = ContractLaborNorm.query.filter_by(contract_id=contract_id).count()

        assert second_count == first_count
        assert second_result["labor_norms_created"] == 0
        assert second_result["labor_norms_updated"] == first_count


def test_reimport_updates_labor_norm_hours_when_changed_upstream(app):
    path = os.path.join(TESTDATA_DIR, "тест 1 (исходник).xlsx")
    with app.app_context():
        contract_id = _make_contract(app)
        import_contract_files(contract_id, [path], None, llm_client=None)

        norm = ContractLaborNorm.query.filter_by(contract_id=contract_id).first()
        original_hours = norm.norm_hours
        norm.norm_hours = (original_hours or 0) + 999
        db.session.commit()

        import_contract_files(contract_id, [path], None, llm_client=None)

        db.session.refresh(norm)
        assert norm.norm_hours == original_hours


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
