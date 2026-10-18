from pathlib import Path
import hashlib
from tempfile import TemporaryDirectory

from fundflow.parser import parse_holdings
from fundflow.validator import validate_report
from fundflow.s3_handler import download_report

def process_report(s3_client, *, bucket: str, key: str, database=None):
    """retrieve a stored report and parse it locally."""
    with TemporaryDirectory() as directory:
        destination = Path(directory) / "holdings.csv"

        s3_file = download_report(s3_client, bucket=bucket, key=key, destination=destination)
        s3_parsed = parse_holdings(s3_file)

        report = validate_report(s3_parsed)
        if database is not None:
            from fundflow.db import store_report
            metadata = s3_client.head_object(Bucket=bucket, Key=key)["Metadata"]
            # calcs downloaded file’s SHA-256 fingerprint
            digest = hashlib.sha256(s3_file.read_bytes()).hexdigest()
            if digest != metadata.get("sha256"):
                raise ValueError("Downloaded file does not match its source hash")
            source = {**metadata, "bucket": bucket, "key": key, "sha256": digest}
            report["persistence"] = store_report(database, report=report, source=source)
        return report


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
