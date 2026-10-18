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
    except Exception as exc:
        if not storage_started:
            record_failure(database, run, exc)
        raise


if __name__ == "__main__":
    import argparse
    import boto3

    cli = argparse.ArgumentParser(description="Parse a report stored in s3.")
    cli.add_argument("--bucket", required=True)
    cli.add_argument("--key", required=True)
    cli.add_argument("--region", required=True)
    cli.add_argument("--profile", default=None)
    cli.add_argument("--store", action="store_true", help="Persist the validated snapshot in MongoDB")
    args = cli.parse_args()

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
            report = process_report(s3_client, bucket=args.bucket, key=args.key, database=database)
    except Exception as exc:
        # detailed stages are logged by processing; never print a credential-bearing uri
        print(f"Processing failed ({type(exc).__name__}); see the stage in the error log.")
        raise SystemExit(1)

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
