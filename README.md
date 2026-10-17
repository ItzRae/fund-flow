# FundFlow

I'm building FundFlow to retrieve a fund's holdings report, check its contents, and load it into a database. I'm starting with the public holdings CSV for [iShares Core S&P 500 ETF (IVV)](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf).

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

- `fundflow/pages/fund_page.py`: the page object for opening IVV and downloading its holdings CSV.
- `tests/conftest.py`: a fixture that provides the fund page object using pytest-playwright's browser page fixture.
- `tests/test_fund_page.py`: live tests for navigation and downloading the report.

## Progress and testing

The page object opens IVV and saves its holdings CSV. Both live tests have passed locally. Fixtures handle browser setup and cleanup and provide a temporary download directory. The tests check the fund heading, a nonempty downloaded file, the fund name, a holdings-date label, and required column names. They don't yet validate the date value or individual holdings.

Run the live tests with a visible browser:

```sh
python -m pytest -m live --headed
```

Live tests visit the external website and require internet access. They are excluded by default; running pytest without `-m live` currently deselects both tests.

## Next milestone

Write a parser that separates the introductory metadata from the holdings table, using a saved CSV sample for offline tests. The downloaded file has metadata and a blank line before its column header, so the parser will locate the header rather than assume it is the first line. Row validation, S3 storage, and MongoDB ingestion are still to come. Scheduling and CI will come after a working ingestion run.
