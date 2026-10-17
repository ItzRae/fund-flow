"""Offline parser checks using small, deliberately constructed CSV examples."""

import csv

import pytest

from fundflow.parser import parse_holdings


@pytest.fixture
def write_report(tmp_path):
    """Create a temporary CSV from the rows supplied by each test."""
    def write(rows):
        path = tmp_path / "holdings.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            csv.writer(file).writerows(rows)
        return path

    return write


def test_parse_distinct_holdings_and_preserve_source_values(write_report):
    path = write_report([
        ["Example fund"],
        ["Fund Holdings as of", " Oct 15, 2026 "],
        ["Additional metadata", "can shift the header"],
        [],
        ["Ticker", "Name", "Asset Class", "Market Value", "Weight (%)"],
        ["AAA", "Example, Inc.", "Equity", "1,250.00", "2.50"],
        [],
        ["BBB", "Second company", "Equity", "0.00", "0.00"],
        [],
    ])

    assert parse_holdings(path) == {
        "report_date": "Oct 15, 2026",
        "holdings": [
            {"Ticker": "AAA", "Name": "Example, Inc.", "Asset Class": "Equity",
             "Market Value": "1,250.00", "Weight (%)": "2.50"},
            {"Ticker": "BBB", "Name": "Second company", "Asset Class": "Equity",
             "Market Value": "0.00", "Weight (%)": "0.00"},
        ],
    }


def test_missing_header(write_report):
    path = write_report([["Fund Holdings as of", "Oct 15, 2026"]])
    with pytest.raises(ValueError, match="Holdings column header not found"):
        parse_holdings(path)


@pytest.mark.parametrize("metadata", [[], [["Fund Holdings as of"]],
                                      [["Fund Holdings as of", "   "]]])
def test_missing_or_empty_date(write_report, metadata):
    path = write_report(metadata + [
        ["Name", "Asset Class", "Market Value", "Weight (%)"],
        ["Example", "Equity", "1.00", "0.10"],
    ])
    with pytest.raises(ValueError, match="Report date not found"):
        parse_holdings(path)


@pytest.mark.parametrize("holding", [
    ["AAA", "Example"],
    ["Example", "Equity", "1.00", "0.10", "unexpected cell"],
])
def test_reject_mismatched_row_width(write_report, holding):
    path = write_report([
        ["Fund Holdings as of", "Oct 15, 2026"],
        ["Name", "Asset Class", "Market Value", "Weight (%)"],
        holding,
    ])
    with pytest.raises(ValueError, match="CSV row 3: expected 4 cells"):
        parse_holdings(path)


def test_reject_report_without_holdings(write_report):
    path = write_report([
        ["Fund Holdings as of", "Oct 15, 2026"],
        ["Name", "Asset Class", "Market Value", "Weight (%)"],
        [],
    ])
    with pytest.raises(ValueError, match="No holdings rows found"):
        parse_holdings(path)


def test_parse_bonds_without_ticker_and_preserve_extra_columns(write_report):
    """bond identifiers survive parsing even when the columns are reordered."""
    headers = ["ISIN", "Weight (%)", "Name", "CUSIP", "Maturity",
               "Market Value", "Asset Class"]
    values = ["US0000000001", "0.25", "Example treasury", "000000001",
              "Oct 15, 2028", "1,000.00", "Fixed Income"]
    path = write_report([
        ["Fund Holdings as of", "Oct 15, 2026"], headers, values,
    ])
    assert parse_holdings(path)["holdings"] == [{
        "ISIN": "US0000000001", "Weight (%)": "0.25",
        "Name": "Example treasury", "CUSIP": "000000001",
        "Maturity": "Oct 15, 2028", "Market Value": "1,000.00",
        "Asset Class": "Fixed Income",
    }]


@pytest.mark.parametrize("missing", ["Name", "Asset Class", "Market Value", "Weight (%)"])
def test_require_each_shared_header(write_report, missing):
    headers = [name for name in ["Name", "Asset Class", "Market Value", "Weight (%)"]
               if name != missing]
    path = write_report([["Fund Holdings as of", "Oct 15, 2026"], headers])
    with pytest.raises(ValueError, match="Holdings column header not found"):
        parse_holdings(path)
