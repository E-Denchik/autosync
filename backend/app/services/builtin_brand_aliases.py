"""Стартовый набор соответствий "кириллица/опечатка -> каноничная марка"
для BrandAlias (см. app/models/brand_alias.py, document_parser._normalize_brand_label).

Единственный источник этих данных — переиспользуется:
  - миграцией migrations/versions/b7e3a9c5d1f8_add_brand_aliases_table.py
    (засевает таблицу при `flask db upgrade` на реальной БД);
  - tests/conftest.py (тесты создают таблицы через db.create_all(), а не
    через Alembic — миграции при этом не выполняются, значит и её seed-шаг
    тоже, без этого дублирования таблица в тестах была бы пустой).

Заказчик не ограничится уже присланными файлами — список не претендует на
полноту всех марок, продающихся в РФ, только самые массовые (топ продаж
2025 — Lada лидирует, следом китайские бренды Chery/Haval/Geely быстро
растят долю рынка) плюс распространённые. Марку не из списка можно
добавить через админку/файлом (см. app/api/brand_aliases.py) или доучить
через ИИ (LLMClient.normalize_brand_labels) — без правки кода и пересборки.
"""

BUILTIN_BRAND_ALIASES = {
    # Россия/СССР/СНГ
    "ЛАДА": "LADA",
    "ВАЗ": "LADA",
    "ГАЗ": "GAZ",
    "УАЗ": "UAZ",
    "ПАЗ": "PAZ",
    "КАМАЗ": "KAMAZ",
    "ЗИЛ": "ZIL",
    "МОСКВИЧ": "MOSKVICH",
    # Китай (быстро растущая доля рынка РФ)
    "ЧЕРИ": "CHERY",
    "ДЖИЛИ": "GEELY",
    "ХАВЕЙЛ": "HAVAL",
    "ХАВАЛ": "HAVAL",
    "ГРЕЙТ ВОЛЛ": "GREAT WALL",
    "ГРЕЙТВОЛЛ": "GREAT WALL",
    "ЧАНГАН": "CHANGAN",
    "ЭКСИД": "EXEED",
    "ОМОДА": "OMODA",
    "ДЖЕЙКУ": "JAECOO",
    "ТАНК": "TANK",
    "ДЖАК": "JAC",
    "ФАВ": "FAW",
    "ДОНГФЕНГ": "DONGFENG",
    "ДУНФЭН": "DONGFENG",
    "БИД": "BYD",
    "ДЖЕТУР": "JETOUR",
    "ЛИФАН": "LIFAN",
    "ЗОТАЙ": "ZOTYE",
    "ФОТОН": "FOTON",
    "СОЛАРИС": "SOLARIS",
    "ВОЯ": "VOYAH",
    "БАИК": "BAIC",
    "ДЭУ": "DAEWOO",
    "ДЭО": "DAEWOO",
    # Япония
    "ТОЙОТА": "TOYOTA",
    "НИССАН": "NISSAN",
    "ХОНДА": "HONDA",
    "МАЗДА": "MAZDA",
    "МИЦУБИСИ": "MITSUBISHI",
    "СУБАРУ": "SUBARU",
    "СУЗУКИ": "SUZUKI",
    "ЛЕКСУС": "LEXUS",
    "ИНФИНИТИ": "INFINITI",
    "ИСУЗУ": "ISUZU",
    "ДАЙХАТСУ": "DAIHATSU",
    # Корея
    "ХЕНДАЙ": "HYUNDAI",
    "ХЕНДЭ": "HYUNDAI",
    "КИА": "KIA",
    "САНГ ЙОНГ": "SSANGYONG",
    "СANГЙОНГ": "SSANGYONG",
    "ССАНГЙОНГ": "SSANGYONG",
    "ДЖЕНЕСИС": "GENESIS",
    # Европа
    "ФОЛЬКСВАГЕН": "VOLKSWAGEN",
    "ШКОДА": "SKODA",
    "АУДИ": "AUDI",
    "БМВ": "BMW",
    "МЕРСЕДЕС": "MERCEDES-BENZ",
    "ОПЕЛЬ": "OPEL",
    "РЕНО": "RENAULT",
    "ПЕЖО": "PEUGEOT",
    "СИТРОЕН": "CITROEN",
    "ФИАТ": "FIAT",
    "ВОЛЬВО": "VOLVO",
    "ПОРШЕ": "PORSCHE",
    "ЛЕНД РОВЕР": "LAND ROVER",
    "ЛЕНДРОВЕР": "LAND ROVER",
    "РЕЙНДЖ РОВЕР": "RANGE ROVER",
    "ЯГУАР": "JAGUAR",
    "МИНИ": "MINI",
    "СЕАТ": "SEAT",
    "АЛЬФА РОМЕО": "ALFA ROMEO",
    # США
    "ФОРД": "FORD",
    "ШЕВРОЛЕ": "CHEVROLET",
    "КАДИЛЛАК": "CADILLAC",
    "ДЖИП": "JEEP",
    "КРАЙСЛЕР": "CHRYSLER",
    "ДОДЖ": "DODGE",
    "БЬЮИК": "BUICK",
    # Грузовой сегмент
    "СКАНИЯ": "SCANIA",
    "ИВЕКО": "IVECO",
}
