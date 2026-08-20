from app.services.matcher import split_article_brand


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
