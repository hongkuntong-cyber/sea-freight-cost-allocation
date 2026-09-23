from decimal import Decimal
from app.core.eu_number import parse_eu_number, has_mask


def test_eu_format_basic():
    assert parse_eu_number("1.295,96") == Decimal("1295.96")
    assert parse_eu_number("5.798,93") == Decimal("5798.93")


def test_eu_thousands_only():
    assert parse_eu_number("5.445,00") == Decimal("5445.00")


def test_eu_zero():
    assert parse_eu_number("0,00") == Decimal("0")


def test_eu_masked():
    assert parse_eu_number("**.***.353,93") == Decimal("353.93")
    assert parse_eu_number("**.**1.217,77") == Decimal("1217.77")
    assert parse_eu_number("**.***.**0,00") == Decimal("0")


def test_eu_negative():
    assert parse_eu_number("-1.234,56") == Decimal("-1234.56")


def test_eu_integer():
    assert parse_eu_number("610") == Decimal("610")


def test_has_mask():
    assert has_mask("**.***.353,93") is True
    assert has_mask("353,93") is False


def test_invalid():
    assert parse_eu_number("") is None
    assert parse_eu_number(None) is None
    assert parse_eu_number("abc") is None
