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