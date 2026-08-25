from app.extensions import db
from app.models import RawImportRow
from app.services.raw_import_staging import mark_rows_moved, stage_raw_rows


def test_stage_raw_rows_preserves_arbitrary_shape(app):
    """Заказчик: "нам должно быть всё равно, как устроен файл" — строки с
    РАЗНЫМ набором полей (разное число "колонок") должны сохраняться как
    есть, без общей жёсткой схемы на все строки сразу."""
    with app.app_context():
        rows = [
            {"article": "A-1", "name": "Деталь 1", "price": 100.0},
            {"name": "Деталь 2", "extra_field": "необычная колонка", "another": 42},
        ]
        stage_raw_rows(rows, row_kind="catalog_part", contract_id=1, source_filename="test.xlsx")
        db.session.commit()

        staged = RawImportRow.query.filter_by(contract_id=1).order_by(RawImportRow.row_index).all()
        assert len(staged) == 2
        assert staged[0].raw_data == rows[0]
        assert staged[1].raw_data == rows[1]
        assert staged[0].status == "staged"
        assert staged[0].source_filename == "test.xlsx"


def test_stage_raw_rows_no_op_for_empty_list(app):
    with app.app_context():
        stage_raw_rows([], row_kind="catalog_part", contract_id=1)
        db.session.commit()
        assert RawImportRow.query.count() == 0


def test_mark_rows_moved_only_affects_matching_scope(app):
    with app.app_context():
        stage_raw_rows([{"name": "A"}], row_kind="catalog_part", contract_id=1)
        stage_raw_rows([{"name": "B"}], row_kind="catalog_part", contract_id=2)
        stage_raw_rows([{"name": "C"}], row_kind="order_part", repair_order_id=5)
        db.session.commit()

        mark_rows_moved(contract_id=1, row_kind="catalog_part")
        db.session.commit()

        rows = {r.raw_data["name"]: r.status for r in RawImportRow.query.all()}
        assert rows == {"A": "moved", "B": "staged", "C": "staged"}
