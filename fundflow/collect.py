from datetime import datetime, timezone
from pathlib import Path

from fundflow.pages.fund_page import FundPage
from fundflow.s3_handler import upload_report

def collect_fund(page, s3_client, fund, bucket, run_id, download_dir):
    destination = Path(download_dir) / f"{fund.fund_id}-{run_id}.csv"

    fund_page = FundPage(page, fund)
    fund_page.open()
    fund_page.download_holdings(destination)

    retrieved_at = datetime.now(timezone.utc)
    s3_ref = upload_report(
        s3_client, 
        path=destination, 
        bucket=bucket, 
        fund_id=fund.fund_id, 
        run_id=run_id, 
        source_url=fund.url, 
        retrieved_at=retrieved_at
    )

    return s3_ref

def collect_batch(browser, s3_client, funds, bucket, download_dir):
    """collect funds one at a time and keep a result for each attempt."""
    from uuid import uuid4

    batch_id = str(uuid4())
    download_dir = Path(download_dir) / batch_id
    download_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for fund in funds:
        run_id = str(uuid4())
        context = None
        result = {"fund_id": fund.fund_id, "run_id": run_id}
        try:
            # a separate context keeps cookies and page state isolated for each fund
            context = browser.new_context()
            reference = collect_fund(
                context.new_page(), s3_client, fund, bucket, run_id, download_dir
            )
            result.update(status="STORED", source=reference)
        except Exception as exc:
            # catch errors at the fund boundary so the next fund still gets a turn
            result.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception as exc:
                    # cleanup shouldn't hide a successful upload or the original failure
                    result["cleanup_error"] = str(exc)
        results.append(result)

    summary = {"batch_id": batch_id, "results": results}
    # keep the summary locally even before we have a database for run records
    import json
    (download_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    """set up the clients, run collection, and print the batch result."""
    import argparse
    import json

    import boto3
    from playwright.sync_api import sync_playwright

    from fundflow.funds import FUNDS

    sources = {fund.fund_id: fund for fund in FUNDS}
    cli = argparse.ArgumentParser(description="Download configured fund reports into S3.")
    cli.add_argument("--funds", nargs="+", choices=sources, default=list(sources))
    cli.add_argument("--bucket", required=True)
    cli.add_argument("--region", required=True)
    cli.add_argument("--profile", default=None, help="AWS profile, or use the default credential chain")
    cli.add_argument("--download-dir", type=Path, default=Path("downloads"))
    cli.add_argument("--headed", action="store_true")
    args = cli.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("s3")
    # repeated fund arguments should not trigger duplicate downloads in one batch
    funds = [sources[fund_id] for fund_id in dict.fromkeys(args.funds)]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        try:
            summary = collect_batch(browser, client, funds, args.bucket, args.download_dir)
        finally:
            browser.close()
    print(json.dumps(summary, indent=2))
    # a nonzero exit code lets a future scheduler detect incomplete batches
    return 1 if any(result["status"] == "FAILED" for result in summary["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
