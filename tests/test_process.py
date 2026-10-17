"""check retrieval and temporary file cleanup without contacting aws."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from fundflow import process
from fundflow.s3_handler import download_report


def test_download_creates_parent_and_preserves_bytes(tmp_path):
    client = Mock()
    destination = tmp_path / "nested" / "holdings.csv"
    payload = b'\xef\xbb\xbfexample\r\n'

    def download(bucket, key, filename):
        assert (bucket, key) == ("bucket", "reports/original.csv")
        Path(filename).write_bytes(payload)

    client.download_file.side_effect = download
    result = download_report(client, bucket="bucket", key="reports/original.csv",
                             destination=destination)
    assert result == destination
    assert destination.read_bytes() == payload


def test_process_parses_before_removing_temporary_file():
    client = Mock()
    paths = []

    def download(bucket, key, filename):
        assert (bucket, key) == ("bucket", "report.csv")
        path = Path(filename)
        paths.append(path)
        path.write_text('Fund Holdings as of,"Oct 15, 2026"\n'
                        'Name,Asset Class,Market Value,Weight (%),CUSIP\n'
                        'Example bond,Fixed Income,"1,000.00",0.25,000000001\n')

    client.download_file.side_effect = download
    report = process.process_report(client, bucket="bucket", key="report.csv")
    assert report["report_date"] == "Oct 15, 2026"
    assert report["holdings"] == [{"Name": "Example bond", "Asset Class": "Fixed Income",
                                   "Market Value": "1,000.00", "Weight (%)": "0.25",
                                   "CUSIP": "000000001"}]
    assert not paths[0].parent.exists()


def test_failed_retrieval_prevents_parsing_and_cleans_up(monkeypatch):
    client = Mock()
    paths = []
    parser = Mock()
    monkeypatch.setattr(process, "parse_holdings", parser)
    error = ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")

    def download(bucket, key, filename):
        path = Path(filename)
        paths.append(path)
        path.write_bytes(b"partial download")
        raise error

    client.download_file.side_effect = download
    with pytest.raises(ClientError) as caught:
        process.process_report(client, bucket="bucket", key="missing.csv")
    assert caught.value is error
    parser.assert_not_called()
    assert not paths[0].parent.exists()


def test_parse_failure_still_removes_temporary_file():
    client = Mock()
    paths = []

    def download(bucket, key, filename):
        path = Path(filename)
        paths.append(path)
        path.write_text("not a holdings report\n")

    client.download_file.side_effect = download
    with pytest.raises(ValueError, match="Holdings column header not found"):
        process.process_report(client, bucket="bucket", key="invalid.csv")
    assert not paths[0].parent.exists()
