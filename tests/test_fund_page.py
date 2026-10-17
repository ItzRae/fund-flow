import csv
import pytest 
from playwright.sync_api import expect


@pytest.mark.live
def test_open_fund_page(fund_page):
    fund_page.open()

    expect(
        fund_page.page.get_by_role(
            "heading",
            name="iShares Core S&P 500 ETF",
            exact=True,
        )
    ).to_be_visible()


@pytest.mark.live
def test_download_holdings(fund_page, tmp_path):
    fund_page.open()

    destination = tmp_path / "holdings.csv"
    fund_page.download_holdings(destination)

    assert destination.is_file()
    # broken server sometimes returns a 0 byte file, 
    # so check that the file is not empty
    assert destination.stat().st_size > 0

    with destination.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))

    assert rows[0] == ["iShares Core S&P 500 ETF"]
    assert any(
        row and row[0] == "Fund Holdings as of"
        for row in rows
    )

    required_columns = {"Ticker", "Name", "Market Value", "Weight (%)"}
    assert any(required_columns.issubset(row) for row in rows)