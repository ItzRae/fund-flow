"""Offline checks for report value validation."""

from datetime import date
from decimal import Decimal

import pytest

from fundflow.validator import parse_decimal, parse_report_date


@pytest.mark.parametrize(("raw_date", "expected"), [
    ("Oct 15, 2026", date(2026, 10, 15)),
    ("  Jan 1, 2020  ", date(2020, 1, 1)),
    ("Feb 29, 2024", date(2024, 2, 29)),
])
def test_parse_report_date(raw_date, expected):
    result = parse_report_date(raw_date)
    assert result == expected
    assert type(result) is date


@pytest.mark.parametrize("raw_date", [
    "Feb 30, 2026",
    "Feb 29, 2025",
    "Oct 32, 2026",
    "2026-10-15",
    "not a date",
    "",
    "   ",
])
def test_reject_invalid_report_date(raw_date):
    with pytest.raises(ValueError, match="Invalid report date"):
        parse_report_date(raw_date)


@pytest.mark.parametrize(("raw_value", "expected"), [
    ("1,250,000.00", "1250000.00"),
    ("1234.56", "1234.56"),
    ("0", "0"),
    ("0.00", "0.00"),
    ("-1,250.50", "-1250.50"),
    (" +12.30 ", "12.30"),
    ("2.50", "2.50"),
    ("0.12345678901234567890123456789", "0.12345678901234567890123456789"),
])
def test_parse_decimal_preserves_exact_value(raw_value, expected):
    result = parse_decimal(raw_value)
    assert isinstance(result, Decimal)
    assert str(result) == expected


@pytest.mark.parametrize("raw_value", ["", "   ", "-", " - "])
def test_reject_missing_numeric_value(raw_value):
    """Missing values must not silently become zero."""
    with pytest.raises(ValueError, match="Missing numeric value"):
        parse_decimal(raw_value)


@pytest.mark.parametrize("raw_value", [
    "12,34.56", "1,23,456", "1,,000", "1234,567", "1,000,",
    "$1,000.00", "2.50%", "(100.00)", "1e3", "NaN", "Infinity",
    "-Infinity", "1.2.3", "1 000", "--1", "1.", ".5", "abc",
])
def test_reject_unsupported_numeric_syntax(raw_value):
    """Validate grouping before stripping commas to avoid accepting bad data."""
    with pytest.raises(ValueError, match="Invalid numeric value"):
        parse_decimal(raw_value)
