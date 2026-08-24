from app.services.matcher import normalize_article, split_article_brand


def test_splits_trailing_bracket_as_brand():
    assert split_article_brand("PN32661 [AUTOWELT]") == ("PN32661", "AUTOWELT")


def test_splits_brand_with_slash():
    assert split_article_brand("2443125001 [HYUNDAI/KIA/MOBIS]") == ("2443125001", "HYUNDAI/KIA/MOBIS")


def test_no_brackets_returns_unchanged_with_no_brand():
    assert split_article_brand("ABC-123") == ("ABC-123", None)


def test_none_passthrough():
    assert split_article_brand(None) == (None, None)


def test_empty_string_passthrough():
    assert split_article_brand("") == ("", None)


def test_tolerates_extra_whitespace():
    assert split_article_brand("  PN32661   [AUTOWELT]  ") == ("PN32661", "AUTOWELT")


def test_bracket_in_the_middle_is_not_touched():
    # только СТРОГО завершающая скобка считается брендом — скобки где-то в
    # середине названия/артикула трогать не нужно, риск испортить артикул выше.
    assert split_article_brand("AB[C]-123") == ("AB[C]-123", None)


def test_normalize_article_strips_dashes():
    assert normalize_article("23410-2G000") == "234102G000"


def test_normalize_article_strips_spaces():
    assert normalize_article("ABC 123 45") == "ABC12345"


def test_normalize_article_upcases():
    assert normalize_article("pn32661") == "PN32661"


def test_normalize_article_already_clean_is_unchanged():
    assert normalize_article("234102G000") == "234102G000"


def test_normalize_article_none_passthrough():
    assert normalize_article(None) is None


def test_normalize_article_empty_string_returns_none():
    assert normalize_article("") is None
    assert normalize_article("   ") is None
    assert normalize_article("--") is None


def test_normalize_article_strips_dots_and_slashes_too():
    # Разделители не перечисляются по одному — любой небуквенно-цифровой
    # "мусор" схлопывается разом, а не только тире/пробел из одного отчёта.
    assert normalize_article("234102.G000") == "234102G000"
    assert normalize_article("234102/G000") == "234102G000"
    assert normalize_article("234102_G000") == "234102G000"
    assert normalize_article("234102\\G000") == "234102G000"
    assert normalize_article("23410 - 2 G 000") == "234102G000"


def test_normalize_article_folds_cyrillic_lookalike_letters():
    # Русская раскладка физически совпадает по клавишам с латинской для этих
    # букв — кириллица в артикуле почти всегда опечатка, а не другой код.
    assert normalize_article("РN32661") == normalize_article("PN32661")  # Cyrillic Р (U+0420)
    assert normalize_article("АВС123") == "ABC123"  # Cyrillic А, В, С
    assert normalize_article("234102Х000") == "234102X000"  # Cyrillic Х (U+0425)


def test_normalize_article_all_kinds_of_noise_together():
    assert normalize_article("  рn-32.661/ ") == "PN32661"
