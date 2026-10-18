from pathlib import Path
import hashlib
from tempfile import TemporaryDirectory

from fundflow.parser import parse_holdings
from fundflow.validator import validate_report
from fundflow.s3_handler import download_report

def process_report(s3_client, *, bucket: str, key: str, database=None):
    """verify the original file before interpreting it, with or without persistence."""
    from fundflow.db import new_attempt, save_attempt, record_failure, store_report

    run = new_attempt({"bucket": bucket, "key": key})
    storage_started = False
    try:
        if database is not None:
            run["stage"] = "RECORD_RUN"
            save_attempt(database, run)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "holdings.csv"
            run["stage"] = "DOWNLOAD"
            s3_file = download_report(s3_client, bucket=bucket, key=key, destination=destination)
            run["stage"] = "VERIFY_CHECKSUM"
            metadata = s3_client.head_object(Bucket=bucket, Key=key).get("Metadata", {})
            expected = metadata.get("sha256")
            if not expected:
                raise ValueError("Source checksum metadata is missing")
            digest = hashlib.sha256(s3_file.read_bytes()).hexdigest()
            if digest != expected:
                raise ValueError("Downloaded file does not match its source hash")
            source = {**metadata, "bucket": bucket, "key": key, "sha256": digest}
            run["source"] = source
            run["stage"] = "PARSE"
            parsed = parse_holdings(s3_file)
            run["stage"] = "VALIDATE"
            report = validate_report(parsed)
            if database is not None:
                # storage records its own finer-grained stage if it fails
                storage_started = True
                report["persistence"] = store_report(database, report=report, source=source, attempt=run)
            return report
    except (Exception, KeyboardInterrupt) as exc:
        if not storage_started:
            record_failure(database, run, exc)
        raise

def process_batch(s3_client, *, summary: dict, database):
    """ process each stored report and keep an outcome for every attempt """

    if database is None:
        raise ValueError("Batch processing requires a database")
    outcomes = []

    for item in summary["results"]:
        # skip reports that weren't successfully uploaded
        if item["status"] != "STORED":
            outcomes.append({
                "fund_id": item["fund_id"],
                "status": "SKIPPED",
                "reason": "collection did not store a report",
            })
            continue

        try:
            source = item["source"]

            report = process_report(
                s3_client,
                bucket=source["bucket"],
                key=source["key"],
                database=database
            )

            outcomes.append({
                "fund_id": item["fund_id"],
                "status": report["persistence"]["status"],
                "inserted": report["persistence"]["inserted"],
                "unchanged": report["persistence"]["unchanged"],
            })

        except Exception as exc:
            outcomes.append({
                "fund_id": item["fund_id"],
                "status": "FAILED",
                "error_type": type(exc).__name__
            })

    return outcomes

def main(argv=None):
    import argparse
    import json
    import boto3

    cli = argparse.ArgumentParser(description="Parse a report stored in s3.")
    cli.add_argument("--bucket")
    cli.add_argument("--key")
    cli.add_argument("--summary", type=Path, help="Saved collection summary to process")
    cli.add_argument("--region", required=True)
    cli.add_argument("--profile", default=None)
    cli.add_argument("--store", action="store_true", help="Persist the validated snapshot in MongoDB")
    args = cli.parse_args(argv)
    if args.summary:
        if args.bucket or args.key:
            cli.error("use --summary or --bucket/--key, not both")
        if not args.store:
            cli.error("batch processing requires --store")
    elif not args.bucket or not args.key:
        cli.error("provide --summary or both --bucket and --key")

    try:
        session = boto3.Session(
            profile_name=args.profile,
            region_name=args.region,
        )
        s3_client = session.client("s3")

        from contextlib import ExitStack
        import os
        with ExitStack() as stack:
            database = None
            if args.store:
                from fundflow.db import create_client
                client = stack.enter_context(create_client())
                database = client[os.environ.get("MONGODB_DATABASE", "fundflow")]
            if args.summary:
                summary = json.loads(args.summary.read_text(encoding="utf-8"))
                outcomes = process_batch(s3_client, summary=summary, database=database)
                print(json.dumps({"batch_id": summary.get("batch_id"), "results": outcomes}, indent=2))
                return batch_exit_code(outcomes)
            report = process_report(s3_client, bucket=args.bucket, key=args.key, database=database)
    except KeyboardInterrupt:
        print("Processing interrupted; completed writes are preserved. Rerun safely to finish.")
        return 130
    except Exception as exc:
        # detailed stages are logged by processing; never print a credential-bearing uri
        print(f"Processing failed ({type(exc).__name__}); see the stage in the error log.")
        return 1

    print(f"Report date: {report['report_date']}")
    print(f"Accepted: {len(report['accepted'])}")
    print(f"Rejected: {len(report['rejected'])}")
    if "persistence" in report:
        result = report["persistence"]
        print(f"Database: {result['status']}; inserted={result['inserted']}, unchanged={result['unchanged']}")

    for rejection in report["rejected"]:
        print(
            f"Holding {rejection['holding_number']}: "
            f"{rejection['reason']}"
        )

    if "persistence" in report:
        return batch_exit_code([report["persistence"]])
    return 1 if not report["accepted"] else 0


def batch_exit_code(outcomes):
    """signal incomplete processing to a terminal or future scheduler."""
    completed = {"COMPLETED", "COMPLETED_WITH_REJECTIONS"}
    return 0 if outcomes and all(item["status"] in completed for item in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
