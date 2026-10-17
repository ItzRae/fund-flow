"""Offline checks for report value validation."""

from datetime import date
from decimal import Decimal

import pytest

from fundflow.validator import parse_decimal, parse_report_date, validate_report, validate_holding


def test_validate_report_continues_after_bad_holding():
    """ keep processing valid holdings after a rejected row """
    valid = {
        "Name": "Example fund holding",
        "Asset Class": "Equity",
        "Market Value": "1,250.00",
        "Weight (%)": "2.50",
    }
    invalid = {**valid, "Market Value": "not a number"}

    report = {
        "report_date": "Oct 15, 2026",
        "holdings": [valid, invalid, {**valid, "Name": "Later holding"}],
    }

    result = validate_report(report)
    assert len(result["accepted"]) == 2 and len(result["rejected"]) == 1
    assert result["accepted"][1]["name"] == "Later holding"
    assert result["rejected"][0]["holding_number"] == 2
    assert result["rejected"][0]["raw"] == invalid
    assert "Market Value: Invalid numeric value" in result["rejected"][0]["reason"]


@pytest.fixture
def holding():
    return {"Name": " Example bond ", "Asset Class": " Fixed Income ",
            "Market Value": "-1,250.00", "Weight (%)": "0.00", "CUSIP": "000000001"}


def test_clean_holding_preserves_raw_and_allows_zero_and_negative(holding):
    original = holding.copy()
    result = validate_holding(holding)
    assert result["name"] == "Example bond"
    assert result["asset_class"] == "Fixed Income"
    assert result["market_value"] == Decimal("-1250.00")
    assert result["weight_percent"] == Decimal("0.00")
    assert holding == original
    assert result["raw"] == original
    assert result["raw"] is not holding


@pytest.mark.parametrize("field", ["Name", "Asset Class", "Market Value", "Weight (%)"])
@pytest.mark.parametrize("value", [None, "", "   ", "-"])
def test_missing_required_holding_fields(holding, field, value):
    # none here means the column is absent, not a literal csv cell value
    if value is None:
        del holding[field]
    else:
        holding[field] = value
    with pytest.raises(ValueError):
        validate_holding(holding)


def test_weight_rejection_identifies_field(holding):
    holding["Weight (%)"] = "bad"
    with pytest.raises(ValueError, match=r"Weight \(%\): Invalid numeric value"):
        validate_holding(holding)


def test_invalid_date_fails_entire_report(holding):
    with pytest.raises(ValueError, match="Invalid report date"):
        validate_report({"report_date": "Feb 30, 2026", "holdings": [holding]})


def test_all_invalid_holdings_are_rejected(holding):
    holding["Name"] = ""
    result = validate_report({"report_date": "Oct 15, 2026", "holdings": [holding]})
    assert result["accepted"] == []
    assert result["rejected"] == [{"holding_number": 1, "raw": holding,
                                   "reason": "Missing holding name"}]


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
