from pathlib import Path
from tempfile import TemporaryDirectory

from fundflow.parser import parse_holdings
from fundflow.s3_handler import download_report

def process_report(s3_client, *, bucket: str, key: str):
    """retrieve a stored report and parse it locally."""
    with TemporaryDirectory() as directory:
        destination = Path(directory) / "holdings.csv"

        s3_file = download_report(s3_client, bucket=bucket, key=key, destination=destination)
        s3_parsed = parse_holdings(s3_file)

        return s3_parsed


if __name__ == "__main__":
    import argparse
    import boto3

    cli = argparse.ArgumentParser(description="Parse a report stored in s3.")
    cli.add_argument("--bucket", required=True)
    cli.add_argument("--key", required=True)
    cli.add_argument("--region", required=True)
    cli.add_argument("--profile", default=None)
    args = cli.parse_args()

    session = boto3.Session(
        profile_name=args.profile,
        region_name=args.region,
    )
    s3_client = session.client("s3")

    report = process_report(
        s3_client,
        bucket=args.bucket,
        key=args.key,
    )

    print(f"Report date: {report['report_date']}")
    print(f"Holdings: {len(report['holdings'])}")