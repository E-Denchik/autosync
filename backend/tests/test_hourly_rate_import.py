import os

from app.extensions import db
from app.models import Contragent, ContragentHourlyRate
from app.services.hourly_rate_import import import_hourly_rates

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "testdata")
RATE_TABLE_DOCX = os.path.join(TESTDATA_DIR, "Нормочасы.docx")


def _make_contragent(app) -> int:
    contragent = Contragent(name="Управление дорог", hourly_rate=1000)
    db.session.add(contragent)
    db.session.commit()
    return contragent.id


def test_import_creates_one_row_per_make_model_pair_from_real_file(app):
    with app.app_context():
        contragent_id = _make_contragent(app)
        result = import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent_id, RATE_TABLE_DOCX)

        assert result == {"created": 15, "updated": 0, "total": 15}
        rows = ContragentHourlyRate.query.filter_by(contragent_id=contragent_id).all()
        assert len(rows) == 15
        hyundai_rows = {(r.vehicle_model, float(r.hourly_rate)) for r in rows if r.vehicle_make == "Hyundai"}
        assert hyundai_rows == {("Accent", 720.0), ("Sonata", 720.0), ("Tucson", 810.0), ("IX35", 810.0), ("Santa Fe", 810.0)}


def test_reimporting_the_same_file_updates_in_place_instead_of_duplicating(app):
    with app.app_context():
        contragent_id = _make_contragent(app)
        import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent_id, RATE_TABLE_DOCX)

        result = import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent_id, RATE_TABLE_DOCX)

        assert result == {"created": 0, "updated": 15, "total": 15}
        assert ContragentHourlyRate.query.filter_by(contragent_id=contragent_id).count() == 15


def test_different_models_of_the_same_make_stay_separate_rows(app):
    with app.app_context():
        contragent_id = _make_contragent(app)
        db.session.add(
            ContragentHourlyRate(contragent_id=contragent_id, vehicle_make="Hyundai", vehicle_model="Accent", hourly_rate=700)
        )
        db.session.commit()

        import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent_id, RATE_TABLE_DOCX)

        accent = ContragentHourlyRate.query.filter_by(
            contragent_id=contragent_id, vehicle_make="Hyundai", vehicle_model="Accent"
        ).first()
        tucson = ContragentHourlyRate.query.filter_by(
            contragent_id=contragent_id, vehicle_make="Hyundai", vehicle_model="Tucson"
        ).first()
        assert float(accent.hourly_rate) == 720.0  # обновлена импортом, не задвоена
        assert float(tucson.hourly_rate) == 810.0  # отдельная модель — отдельная новая строка


def test_make_only_rate_does_not_collide_with_model_specific_rate(app):
    """Ставка "на всю марку" (vehicle_model=None) и ставка по конкретной
    модели той же марки — разные записи, импорт не должен их путать."""
    with app.app_context():
        contragent_id = _make_contragent(app)
        db.session.add(ContragentHourlyRate(contragent_id=contragent_id, vehicle_make="Hyundai", hourly_rate=999))
        db.session.commit()

        result = import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent_id, RATE_TABLE_DOCX)

        assert result["created"] == 15  # ни одна модельная строка не совпала с маркой-без-модели
        make_only = ContragentHourlyRate.query.filter_by(
            contragent_id=contragent_id, vehicle_make="Hyundai", vehicle_model=None
        ).first()
        assert float(make_only.hourly_rate) == 999.0  # не тронута
