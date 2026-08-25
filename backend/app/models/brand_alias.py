from datetime import datetime

from app.extensions import db


class BrandAlias(db.Model):
    """Справочник "как марка называется в файлах поставщика -> как она
    называется в заказ-наряде/у нас" (см. document_parser._normalize_brand_label,
    matcher._contract_candidate_pool). Каталоги пишут марку то латиницей, то
    кириллицей ("Шевроле"), то с опечаткой/слитно ("ChevrolNiva") — без этого
    справочника такие строки никогда не совпали бы с vehicle_make заказ-наряда.

    Заказчик работает не только с уже присланными файлами — переносить
    список марок в код и требовать пересборку под каждую новую было бы
    неправильно, поэтому это таблица в БД, которую можно пополнять файлом
    или через админку, а нераспознанное — доучивать через выбранную ИИ
    (см. services/contract_catalog_import.py, LLMClient.normalize_brand_labels).
    """

    __tablename__ = "brand_aliases"

    id = db.Column(db.Integer, primary_key=True)
    # Написание "как есть" из файла поставщика — "Шевроле", "ChevrolNiva",
    # "GM (Шевроле, Опель)". Сравнение везде регистронезависимое.
    alias = db.Column(db.String(256), nullable=False, unique=True, index=True)
    # Каноничное написание марки — то, в каком виде она обычно приходит из
    # заказ-наряда (латиница). NULL — alias загружен (файлом/вручную), но
    # каноничная марка ещё не определена (ждёт ИИ-нормализации).
    canonical_make = db.Column(db.String(128), index=True)
    # builtin (засеяно миграцией) / manual (вручную в админке) / upload
    # (файлом) / llm (проставлено ИИ-нормализацией).
    source = db.Column(db.String(32), default="manual", nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BrandAlias {self.alias!r} -> {self.canonical_make!r}>"
