"""save the original holdings file in s3 so we can reprocess it later."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


def upload_report(client, *, path: Path, bucket: str, fund_id: str,
                  run_id: str, source_url: str, retrieved_at: datetime) -> dict:
    """upload the file as downloaded and return its storage details.

    the caller provides the download time and a unique run id.
    let upload errors reach the caller so it knows to stop processing.
    """
    # these ids become part of the object key, so don't allow extra path separators
    for label, value in (("fund_id", fund_id), ("run_id", run_id)):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError(f"Invalid {label}: use letters, digits, underscores or hyphens")
    # require a timezone so the download time isn't ambiguous
    if retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")

    # keep the original bytes, including encoding and line endings
    payload = path.read_bytes()
    if not payload:
        raise ValueError("Cannot upload an empty report")
    # the hash lets us compare file contents even if the filenames differ
    sha256 = hashlib.sha256(payload).hexdigest()
    key = f"runs/{run_id}/{fund_id}/raw/holdings.csv"
    # keep enough context with the file to trace where it came from
    metadata = {
        "fund-id": fund_id,
        "run-id": run_id,
        "source-url": source_url,
        "retrieved-at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "sha256": sha256,
    }
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload,
        ContentType="text/csv",
        Metadata=metadata,
        # don't overwrite a file already saved for this run and fund
        IfNoneMatch="*",
    )
    return {"bucket": bucket, "key": key, "sha256": sha256, **metadata}

def download_report(client, *, bucket: str, key: str, destination: Path) -> Path:
    """ retrieve a saved report from s3 for local processing """

    destination.parent.mkdir(parents=True, exist_ok=True)

    client.download_file(bucket, key, str(destination))

    return destination

if __name__ == "__main__":
    import argparse
    import json
    from uuid import uuid4

    import boto3

    from fundflow.funds import FUNDS

    # use the configured fund details rather than asking for the source url again
    funds = {fund.fund_id: fund for fund in FUNDS}
    cli = argparse.ArgumentParser(description="Upload an original holdings CSV to S3.")
    cli.add_argument("path", type=Path)
    cli.add_argument("--fund", required=True, choices=funds)
    cli.add_argument("--bucket", required=True)
    cli.add_argument("--region", required=True)
    cli.add_argument("--retrieved-at", required=True,
                     help="Actual retrieval time with timezone, e.g. 2026-10-16T18:00:00-04:00")
    args = cli.parse_args()
    # boto3 uses local aws credentials; each command invocation gets a new run id
    result = upload_report(
        boto3.client("s3", region_name=args.region),
        path=args.path, bucket=args.bucket, fund_id=args.fund,
        run_id=str(uuid4()), source_url=funds[args.fund].url,
        retrieved_at=datetime.fromisoformat(args.retrieved_at),
    )
    print(json.dumps(result, indent=2))
