"""Fund sources for collection; inclusion does not imply parser compatibility."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FundConfig:
    """Source identity and expected download columns for one fund."""

    fund_id: str
    name: str
    url: str
    required_columns: tuple[str, ...]


_COMMON_COLUMNS = ("Name", "Asset Class", "Market Value", "Weight (%)")

FUNDS = (
    FundConfig(
        fund_id="IVV",
        name="iShares Core S&P 500 ETF",
        url="https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf",
        required_columns=(*_COMMON_COLUMNS, "Ticker"),
    ),
    FundConfig(
        fund_id="ITOT",
        name="iShares Core S&P Total U.S. Stock Market ETF",
        url="https://www.ishares.com/us/products/239724/ishares-core-sp-total-us-stock-market-etf",
        required_columns=(*_COMMON_COLUMNS, "Ticker"),
    ),
    FundConfig(
        fund_id="AGG",
        name="iShares Core U.S. Aggregate Bond ETF",
        url="https://www.ishares.com/us/products/239458/ishares-core-total-us-bond-market-etf",
        required_columns=(*_COMMON_COLUMNS, "CUSIP", "ISIN"),
    ),
    FundConfig(
        fund_id="IEFA",
        name="iShares Core MSCI EAFE ETF",
        url="https://www.ishares.com/us/products/244049/ishares-core-msci-eafe-etf",
        required_columns=(*_COMMON_COLUMNS, "Ticker"),
    ),
    FundConfig(
        fund_id="SHY",
        name="iShares 1-3 Year Treasury Bond ETF",
        url="https://www.ishares.com/us/products/239452/ishares-13-year-treasury-bond-etf",
        required_columns=(*_COMMON_COLUMNS, "CUSIP", "ISIN"),
    ),
)
