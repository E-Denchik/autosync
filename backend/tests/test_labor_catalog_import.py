import os

from app.extensions import db
from app.models import LaborCatalogEntry
from app.services.labor_catalog_import import import_labor_catalog

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "testdata")
LABOR_CATALOG_FILE = os.path.join(TESTDATA_DIR, "Нормо-часы (справочник).xlsx")


def test_import_creates_one_row_per_make_model_operation_from_real_file(app):
    with app.app_context():
        result = import_labor_catalog(LABOR_CATALOG_FILE)

        assert result == {"created": 6, "updated": 0, "total": 6}
        rows = LaborCatalogEntry.query.all()
        assert len(rows) == 6
        assert all(r.source == "import" for r in rows)

        ix35_hours = {(r.operation_name, float(r.norm_hours)) for r in rows if r.vehicle_model == "IX35"}
        assert ix35_hours == {
            ("ДВС снятие", 28.0),
            ("Блок цилиндров расточка", 6.0),
            ("ДВС разборка дефектовка", 12.0),
        }

        toyota_row = LaborCatalogEntry.query.filter_by(vehicle_make="TOYOTA").first()
        assert toyota_row.vehicle_model is None  # марка без модели — "на все модели"


def test_reimporting_the_same_file_updates_in_place_instead_of_duplicating(app):
    with app.app_context():
        import_labor_catalog(LABOR_CATALOG_FILE)

        result = import_labor_catalog(LABOR_CATALOG_FILE)

        assert result == {"created": 0, "updated": 6, "total": 6}
        assert LaborCatalogEntry.query.count() == 6


def test_different_operations_for_the_same_make_model_stay_separate_rows(app):
    """Ключ дедупликации — марка+модель+ОПЕРАЦИЯ, а не просто марка+модель
    (в отличие от ставок, где на пару марка+модель приходится одна ставка) —
    у одной машины много разных операций с разными нормами."""
    with app.app_context():
        db.session.add(
            LaborCatalogEntry(
                vehicle_make="HYUNDAI", vehicle_model="IX35", operation_name="ДВС снятие", norm_hours=1, source="manual"
            )
        )
        db.session.commit()

        import_labor_catalog(LABOR_CATALOG_FILE)

        engine_removal = LaborCatalogEntry.query.filter_by(
            vehicle_make="HYUNDAI", vehicle_model="IX35", operation_name="ДВС снятие"
        ).first()
        assert float(engine_removal.norm_hours) == 28.0  # обновлена импортом, не задвоена
        assert engine_removal.source == "import"

        other_ops = LaborCatalogEntry.query.filter_by(vehicle_make="HYUNDAI", vehicle_model="IX35").count()
        assert other_ops == 3  # остальные две операции по IX35 добавлены отдельными строками


def test_make_only_entry_does_not_collide_with_model_specific_entry_for_same_operation(app):
    with app.app_context():
        db.session.add(
            LaborCatalogEntry(
                vehicle_make="TOYOTA",
                vehicle_model="Camry",
                operation_name="Диагностика ходовой части",
                norm_hours=2,
                source="manual",
            )
        )
        db.session.commit()

        import_labor_catalog(LABOR_CATALOG_FILE)

        camry_specific = LaborCatalogEntry.query.filter_by(
            vehicle_make="TOYOTA", vehicle_model="Camry", operation_name="Диагностика ходовой части"
        ).first()
        assert float(camry_specific.norm_hours) == 2.0  # не тронута — другая запись

        make_only = LaborCatalogEntry.query.filter_by(
            vehicle_make="TOYOTA", vehicle_model=None, operation_name="Диагностика ходовой части"
        ).first()
        assert float(make_only.norm_hours) == 1.0  # своя новая запись "на все модели"
