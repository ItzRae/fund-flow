# FundFlow

I'm building FundFlow to to retrieve a fund's holdings report, check its contents, and load it into a database. I'm starting with the public holdings CSV for [iShares Core S&P 500 ETF (IVV)](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf).

The plan is to use Playwright to open the fund page and download the report, save the original file in S3, then validate and store holdings in MongoDB. Each run should show what was accepted, what was rejected, and whether the report has already been processed.

The CSV can also be downloaded directly over HTTP. I'm using Playwright to learn it (having previously used Selenium) and practice automating the portal workflow.

## Setup

Use Python 3.11 or newer. From the project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

## Structure

- `fundflow/pages/fund_page.py`: the page object for opening the IVV fund page.
- `tests/conftest.py`: a fixture that provides the fund page object using pytest-playwright's browser page fixture.
- `tests/test_fund_page.py`: a live navigation test that checks the fund heading is visible.
- `portal/`: the original synthetic portal exercise. The collector will use the real fund page instead.

## Progress and testing

The page object opens IVV, and the first live navigation test has passed locally. The test uses a fixture for browser setup and cleanup, then waits for the expected fund heading to appear.

Run the live test with a visible browser:

```sh
python -m pytest -m live --headed
```

Live tests visit the external website and require internet access. They are excluded by default; running pytest without `-m live` currently deselects the only test.

## Next milestone

Download one IVV holdings CSV and inspect its report date, metadata, and columns before writing the parser. Download handling, parsing, S3 storage, and MongoDB ingestion are not implemented yet. Saved report samples will support offline parsing tests. Scheduling and CI will come after a working ingestion run.
