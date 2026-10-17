# FundFlow

I'm building FundFlow to retrieve a fund's holdings report, check its contents, and load it into a database. It currently collects public iShares holdings reports for IVV, ITOT, AGG, IEFA, and SHY.

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

## Architecture

```text
configured iShares funds
         |
         v
Playwright page object
         |
         v
original CSV + source metadata in S3
         |
         v
retrieve to a temporary file
         |
         v
CSV parser -> report date + holdings dictionaries
         |
         v
row validation and rejection details [planned]
         |
         v
MongoDB [planned] -> interface [planned]
```

Collection and processing are separate commands. Reports can be read back from S3 without visiting the fund website again. Date and Decimal validation helpers exist, but aren't connected to processing yet.

## Collect reports

Use an existing S3 bucket and an AWS profile with access to it. For the browser-based login used during development:

```sh
aws login --profile fundflow
python -m fundflow.collect \
  --funds IVV ITOT AGG IEFA SHY \
  --bucket YOUR_BUCKET \
  --region us-east-2 \
  --profile fundflow
```

The AWS CLI must be installed separately. Add `--headed` to see the browser. Collection runs sequentially, records failures per fund, and continues to the next fund. The command exits with a nonzero status if any fund fails.

Original files are stored at `runs/{run_id}/{fund_id}/raw/holdings.csv`, with the source URL, retrieval time, fund ID, run ID, and SHA-256 hash in object metadata. Each collection attempt gets a new run ID. This preserves separate attempts; it doesn't yet prevent duplicate business records.

Local downloads and a batch summary are saved under `downloads/{batch_id}/`. The directory is ignored by Git. `STORED` means the upload succeeded, not that the holdings passed validation.

## Process a saved report

Copy a bucket and object key from the batch summary:

```sh
python -m fundflow.process \
  --bucket YOUR_BUCKET \
  --key runs/RUN_ID/SHY/raw/holdings.csv \
  --region us-east-2 \
  --profile fundflow
```

This retrieves the file, parses it, and prints its report date and holdings count. The temporary local file is removed afterward; the original S3 object stays in place.

The parser finds the header using shared columns, so a ticker isn't required for bond reports. It preserves additional fields and keeps dates and amounts as strings. Missing headers or dates, inconsistent row lengths, and reports with no holdings raise an error. Blank CSV rows are skipped; unexpected footer text is not silently discarded.

To parse a file already on disk:

```sh
python -m fundflow.parser downloads/holdings.csv
```

## Testing and current progress

Run offline tests:

```sh
python -m pytest
```

These cover parsing, date and Decimal conversion, S3 request construction, batch failure handling, and temporary-file cleanup. S3 tests use stubbed responses or test doubles; they don't verify real AWS access.

Run live browser tests separately:

```sh
python -m pytest -m live --headed
```

The live tests check navigation and download contents for each configured fund. They require internet access and are excluded by default.

A five-fund batch has been uploaded to S3 and read back to verify its bytes, hashes, and metadata. The processing command has also been checked against a stored SHY report. This is coverage of selected sources, not a claim that every iShares format is supported.

## Still to build

Apply validation to each holding, collect rejection reasons, and store accepted records in MongoDB with safe repeat processing. Then add an interface for run results and holdings. Scheduling and CI can follow the working pipeline.
