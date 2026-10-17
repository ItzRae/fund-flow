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
        ["Ticker", "Name", "Market Value", "Weight (%)"],
        ["AAA", "Example, Inc.", "1,250.00", "2.50"],
        [],
        ["BBB", "Second company", "0.00", "0.00"],
        [],
    ])

    assert parse_holdings(path) == {
        "report_date": "Oct 15, 2026",
        "holdings": [
            {"Ticker": "AAA", "Name": "Example, Inc.",
             "Market Value": "1,250.00", "Weight (%)": "2.50"},
            {"Ticker": "BBB", "Name": "Second company",
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
        ["Ticker", "Name", "Market Value"],
        ["AAA", "Example", "1.00"],
    ])
    with pytest.raises(ValueError, match="Report date not found"):
        parse_holdings(path)


@pytest.mark.parametrize("holding", [
    ["AAA", "Example"],
    ["AAA", "Example", "1.00", "unexpected cell"],
])
def test_reject_mismatched_row_width(write_report, holding):
    path = write_report([
        ["Fund Holdings as of", "Oct 15, 2026"],
        ["Ticker", "Name", "Market Value"],
        holding,
    ])
    with pytest.raises(ValueError, match="CSV row 3: expected 3 cells"):
        parse_holdings(path)


def test_reject_report_without_holdings(write_report):
    path = write_report([
        ["Fund Holdings as of", "Oct 15, 2026"],
        ["Ticker", "Name", "Market Value"],
        [],
    ])
    with pytest.raises(ValueError, match="No holdings rows found"):
        parse_holdings(path)
