import pytest

from app.services.xlsx_safety import sanitize_cell_value


@pytest.mark.parametrize("dangerous", ["=1+1", "+1+1", "-1+1", "@SUM(1)", "\tCMD", "\rCMD"])
def test_sanitize_prefixes_dangerous_leading_characters(dangerous):
    result = sanitize_cell_value(dangerous)
    assert result == "'" + dangerous
    assert result[0] == "'"


@pytest.mark.parametrize("safe", ["Тормозной диск", "23410-2G000", "", "A-1 [BOSCH]"])
def test_sanitize_leaves_ordinary_strings_untouched(safe):
    assert sanitize_cell_value(safe) == safe


def test_sanitize_leaves_non_strings_untouched():
    assert sanitize_cell_value(None) is None
    assert sanitize_cell_value(1500.0) == 1500.0
    assert sanitize_cell_value(0) == 0
