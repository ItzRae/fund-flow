# FundFlow

I built FundFlow to automate a recurring investment operations task: retrieve a fund's holdings report, validate its contents, and make the results available for review. I wanted to work with real reports and keep the cleaned data traceable to its original source.

The pipeline collects public iShares holdings reports for **IVV, ITOT, AGG, IEFA, and SHY**, preserves the original CSV files in an **AWS S3 bucket**, and stores validated holdings in **MongoDB Atlas**. A read-only **FastAPI dashboard hosted on Vercel** lets visitors inspect holdings, review processing history, and see which attempts completed or failed.

**Technologies:** Python · Playwright · AWS S3 · MongoDB Atlas · FastAPI · pytest · Vercel

The CSV can also be downloaded directly over HTTP. I'm using Playwright to learn it, having previously used Selenium, and to practice browser-based collection with a page object and pytest fixtures.

## What it does

- Preserves each downloaded CSV with its source URL, retrieval time, run ID, and SHA-256 hash.
- Verifies the retrieved file's checksum before parsing or validation.
- Handles report metadata, column headers, dates, and formatted numbers. Tickers aren't required for every holding, and zero or negative values aren't automatically rejected.
- Records accepted and rejected rows, including rejection reasons.
- Writes holdings in batches of 250, prints progress, and records acknowledged inserted/unchanged counts.
- Avoids duplicate holdings when the same snapshot is processed again. Each processing attempt still has its own history record.

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
retrieve -> verify checksum -> parse -> validate
                                          |
                                          v
                          MongoDB snapshots, holdings, runs
                                          |
                                          v
                                     FastAPI
                                          |
                                          v
                           read-only operations dashboard
```

Collection and processing are separate. I can retry processing a saved report without downloading it from the fund website again. Viewing the dashboard only needs MongoDB access; it doesn't run collection or need AWS credentials.

## Dashboard

The dashboard shows the latest processing attempt for each fund. **View history** opens a modal with recent attempts and their counts. **View holdings** displays the latest successfully processed report below the overview, so a newer failed attempt doesn't replace the last usable report.

Holdings are paginated, with name search, an asset-class filter, and sorting by weight, market value, or name. Sorting and filtering happen before pagination. The table shows the report date, currency, and a notice if the selected report had rejected rows.

The app is deployed on Vercel. Its configuration uses Python 3.12 and the `fundflow.app:app` entrypoint. Deployment credentials belong in environment variables; the hosted dashboard should use a MongoDB user with read-only access to `fundflow`.

## Local setup

Use Python 3.12 to match deployment. For the full pipeline and tests:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

For just the dashboard, install `requirements.txt` instead; Playwright isn't needed.

Create a local `.env` file for database access:

```dotenv
MONGODB_URI=your_mongodb_connection_string
MONGODB_DATABASE=fundflow
```

The file is ignored by Git. Processing with `--store` needs a database user with write access; the dashboard only needs read access. Atlas network access must also allow the environment making the connection.

For collection and S3 retrieval, configure AWS credentials with access to your bucket. The examples below use a local profile named `fundflow` and region `us-east-2`. Omit `--profile` to use the default AWS credential chain. The AWS CLI is installed separately if you use it to manage your login.

## CLI commands

I added command-line entrypoints so I could check each stage independently, repeat a failed step, and later connect the same commands to an automation workflow.

| Command | Purpose |
| --- | --- |
| `python -m fundflow.collect` | Download configured fund reports and upload the originals to S3. |
| `python -m fundflow.parser PATH` | Inspect a local CSV's report date and row count without cloud access. |
| `python -m fundflow.process` | Retrieve, verify, and validate a saved S3 report; optionally store it in MongoDB. |
| `python -m fundflow.db` | Check MongoDB connectivity without inserting records. |
| `python -m uvicorn fundflow.app:app --reload` | Start the local dashboard and API. |

Collect reports:

```sh
python -m fundflow.collect \
  --funds IVV ITOT AGG IEFA SHY \
  --bucket YOUR_BUCKET \
  --region us-east-2 \
  --profile fundflow
```

Add `--headed` to watch the browser. Collection continues after individual fund failures and exits with a nonzero status if any fund fails. Downloads and `summary.json` are saved under the ignored `downloads/{batch_id}/` directory. `STORED` means the S3 upload succeeded, not that validation passed.

Process one report using its key from the summary:

```sh
python -m fundflow.process \
  --bucket YOUR_BUCKET \
  --key runs/RUN_ID/SHY/raw/holdings.csv \
  --region us-east-2 \
  --profile fundflow
```

This prints the report date, accepted/rejected counts, and rejection details. Add `--store` to persist the results. The temporary downloaded file is removed afterward; the S3 original stays in place.

Process a collected batch and store its results:

```sh
python -m fundflow.process \
  --summary downloads/BATCH_ID/summary.json \
  --region us-east-2 \
  --profile fundflow \
  --store
```

Batch processing requires `--store` and prints a JSON outcome summary. Failed or skipped funds produce a nonzero exit status; completed reports with rejected rows remain distinguishable in their status and counts.

Run the dashboard:

```sh
python -m uvicorn fundflow.app:app --reload
```

Open `http://127.0.0.1:8000`, or `/docs` to try the API endpoints:

- `GET /health` — app liveness, not a database connectivity check.
- `GET /api/funds` — latest processing attempt per fund.
- `GET /api/funds/{fund_id}/runs` — up to 20 recent attempts.
- `GET /api/funds/{fund_id}/holdings` — holdings with pagination, sorting, and filters.

## Testing

```sh
python -m pytest
```

Offline tests cover parsing, validation, S3 requests, batch processing, repeat-safe storage, failure handling, and holdings query construction. Cloud clients are stubbed or mocked; these tests don't prove that live credentials or network access work.

Run live browser tests separately:

```sh
python -m pytest -m live --headed
```

These visit the configured fund pages and check downloads. Live tests require internet access and are excluded by default.

## Scope and next step

The five configured funds have been collected and processed with real reports. This covers selected equity and bond reports, not every iShares format.

Deduplication uses the fund, file hash, and original row contents. It prevents exact repeats; it doesn't identify the same security across different reports or resolve conflicting business records. Changed processing versions require an explicit snapshot rebuild rather than silently mixing interpretations. Reports are still parsed in memory.

Next is a manually triggered GitHub Actions workflow to connect collection and processing and retain their summaries. Scheduling isn't implemented yet.
