"""check our s3 requests offline; real bucket access needs a separate live check."""

import hashlib
from datetime import datetime, timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from fundflow.s3_handler import upload_report


@pytest.fixture
def upload_case(tmp_path):
    # include a byte-order mark and windows line endings to check they stay intact
    payload = b'\xef\xbb\xbfFund\r\n"Market Value"\r\n"1,250.00"\r\n'
    path = tmp_path / "holdings.csv"
    path.write_bytes(payload)
    # fake credentials avoid looking up our real aws login; stubber intercepts requests
    client = boto3.client("s3", region_name="us-east-1",
                          aws_access_key_id="testing", aws_secret_access_key="testing")
    args = dict(path=path, bucket="test-fundflow", fund_id="IVV", run_id="run-1",
                source_url="https://example.com/fund",
                retrieved_at=datetime(2026, 10, 16, 18, tzinfo=timezone.utc))
    return client, args, payload


def test_preserve_bytes_and_source_metadata(upload_case):
    client, args, payload = upload_case
    # digest is the file's sha256 fingerprint, written as a hex string
    # it depends on the bytes, not the filename; it isn't encryption or s3's etag
    digest = hashlib.sha256(payload).hexdigest()
    key = "runs/run-1/IVV/raw/holdings.csv" 
    # body holds the original bytes; metadata holds the source details alongside them
    expected = dict(
        Bucket="test-fundflow", Key=key, Body=payload, ContentType="text/csv",
        Metadata={"fund-id": "IVV", "run-id": "run-1",
                  "source-url": args["source_url"],
                  "retrieved-at": "2026-10-16T18:00:00+00:00", "sha256": digest},
        # ask s3 to reject the write if this key already exists
        IfNoneMatch="*",
    )
    # checks requests and supplies queued responses without contacting aws
    with Stubber(client) as stub:
        # {} is a minimal successful response
        stub.add_response("put_object", {}, expected)
        result = upload_report(client, **args)
        # fail if the uploader never made the request we queued a response for
        stub.assert_no_pending_responses()
    # check the reference returned to the caller for later lookup and processing
    assert result["key"] == key
    assert result["bucket"] == args["bucket"]
    assert result["sha256"] == digest


@pytest.mark.parametrize("error_code,status", [("AccessDenied", 403),
                                               ("PreconditionFailed", 412)])
def test_upload_errors_propagate(upload_case, error_code, status):
    """a failed upload or existing key must not be reported as successful."""
    client, args, _ = upload_case
    with Stubber(client) as stub:
        # simulate a permission denial or an existing key rejected by the write condition
        stub.add_client_error("put_object", service_error_code=error_code,
                              http_status_code=status)
        # the caller needs this error so it won't continue as though the file was saved
        with pytest.raises(ClientError):
            upload_report(client, **args)


def test_reject_empty_file_before_s3(upload_case):
    client, args, _ = upload_case
    args["path"].write_bytes(b"")
    # no response is queued, so any attempted s3 request would fail this test
    with Stubber(client), pytest.raises(ValueError, match="empty report"):
        upload_report(client, **args)


def test_require_timezone(upload_case):
    client, args, _ = upload_case
    # without a timezone, we can't reliably convert the retrieval time to utc
    args["retrieved_at"] = datetime(2026, 10, 16)
    with Stubber(client), pytest.raises(ValueError, match="timezone"):
        upload_report(client, **args)
