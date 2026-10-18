"""check retrieval and temporary file cleanup without contacting aws."""

import hashlib
from pathlib import Path
from datetime import date
from decimal import Decimal
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
        client.head_object.return_value = {"Metadata": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}

    client.download_file.side_effect = download
    report = process.process_report(client, bucket="bucket", key="report.csv")
    assert report["report_date"] == date(2026, 10, 15)
    assert report["rejected"] == []
    assert report["accepted"] == [{
        "name": "Example bond", "asset_class": "Fixed Income",
        "market_value": Decimal("1000.00"), "weight_percent": Decimal("0.25"),
        "raw": {"Name": "Example bond", "Asset Class": "Fixed Income",
                                   "Market Value": "1,000.00", "Weight (%)": "0.25",
                                   "CUSIP": "000000001"}}]
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
        client.head_object.return_value = {"Metadata": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}

    client.download_file.side_effect = download
    with pytest.raises(ValueError, match="Holdings column header not found"):
        process.process_report(client, bucket="bucket", key="invalid.csv")
    assert not paths[0].parent.exists()


@pytest.mark.parametrize('metadata,message', [
    ({}, 'checksum metadata is missing'),
    ({'sha256': '0' * 64}, 'does not match'),
])
@pytest.mark.parametrize('persist', [False, True])
def test_integrity_failure_prevents_parsing_and_writes(monkeypatch, metadata, message, persist, caplog):
    client = Mock()
    db = Mock() if persist else None
    parser = Mock()
    monkeypatch.setattr(process, 'parse_holdings', parser)
    paths = []

    def download(bucket, key, filename):
        path = Path(filename)
        paths.append(path)
        path.write_bytes(b'invalid content that must not reach parsing')

    client.download_file.side_effect = download
    client.head_object.return_value = {'Metadata': metadata}
    with pytest.raises(ValueError, match=message):
        process.process_report(client, bucket='bucket', key='report.csv', database=db)
    parser.assert_not_called()
    assert not paths[0].parent.exists()
    assert 'VERIFY_CHECKSUM' in caplog.text
    if persist:
        db.holdings.bulk_write.assert_not_called()
        assert db.processing_runs.update_one.call_args.args[1]['$set']['stage'] == 'VERIFY_CHECKSUM'


@pytest.mark.parametrize('date_text,stage', [('Feb 30, 2026', 'VALIDATE'), ('missing', 'PARSE')])
def test_pre_storage_failures_are_recorded(date_text, stage):
    client = Mock()
    db = Mock()
    payload = (f'Fund Holdings as of,"{date_text}"\n'
               'Name,Asset Class,Market Value,Weight (%)\n'
               'bond,Fixed Income,1.00,0.25\n').encode()
    if stage == 'PARSE':
        payload = b'not a report'
    client.download_file.side_effect = lambda bucket, key, filename: Path(filename).write_bytes(payload)
    client.head_object.return_value = {'Metadata': {'sha256': hashlib.sha256(payload).hexdigest()}}
    with pytest.raises(ValueError):
        process.process_report(client, bucket='bucket', key='report.csv', database=db)
    assert db.processing_runs.update_one.call_args.args[1]['$set']['stage'] == stage
    db.holdings.bulk_write.assert_not_called()


def test_batch_continues_and_preserves_outcomes(monkeypatch):
    worker = Mock(side_effect=[RuntimeError('failed'),
                              {'persistence': {'status': 'COMPLETED_WITH_REJECTIONS',
                                               'inserted': 2, 'unchanged': 3}}])
    monkeypatch.setattr(process, 'process_report', worker)
    summary = {'results': [
        {'fund_id': 'SKIP', 'status': 'FAILED'},
        {'fund_id': 'BAD', 'status': 'STORED', 'source': {'bucket': 'b', 'key': 'bad'}},
        {'fund_id': 'GOOD', 'status': 'STORED', 'source': {'bucket': 'b', 'key': 'good'}},
    ]}
    outcomes = process.process_batch(Mock(), summary=summary, database=Mock())
    assert [r['status'] for r in outcomes] == ['SKIPPED', 'FAILED', 'COMPLETED_WITH_REJECTIONS']
    assert outcomes[1]['error_type'] == 'RuntimeError'
    assert outcomes[2]['inserted'] == 2
    assert worker.call_count == 2


def test_missing_source_does_not_stop_batch(monkeypatch):
    worker = Mock(return_value={'persistence': {'status': 'VALIDATION_FAILED', 'inserted': 0, 'unchanged': 0}})
    monkeypatch.setattr(process, 'process_report', worker)
    summary = {'results': [{'fund_id': 'BAD', 'status': 'STORED'},
                            {'fund_id': 'NEXT', 'status': 'STORED',
                             'source': {'bucket': 'b', 'key': 'k'}}]}
    outcomes = process.process_batch(Mock(), summary=summary, database=Mock())
    assert [r['status'] for r in outcomes] == ['FAILED', 'VALIDATION_FAILED']
    worker.assert_called_once()


@pytest.mark.parametrize('statuses,expected', [
    (['COMPLETED', 'COMPLETED_WITH_REJECTIONS'], 0),
    (['COMPLETED', 'FAILED'], 1),
    (['VALIDATION_FAILED'], 1), (['SKIPPED'], 1), ([], 1),
])
def test_batch_exit_status(statuses, expected):
    assert process.batch_exit_code([{'status': s} for s in statuses]) == expected


@pytest.mark.parametrize('arguments', [
    ['--summary', 'batch.json'],
    ['--summary', 'batch.json', '--store', '--bucket', 'b'],
    ['--bucket', 'b'],
])
def test_cli_rejects_incomplete_or_conflicting_arguments(arguments):
    with pytest.raises(SystemExit) as caught:
        process.main(['--region', 'us-east-2', *arguments])
    assert caught.value.code == 2


def test_interrupt_during_retrieval_records_interrupted_run():
    client, db = Mock(), Mock()
    client.download_file.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        process.process_report(client, bucket='bucket', key='report.csv', database=db)
    run = db.processing_runs.update_one.call_args.args[1]['$set']
    assert run['status'] == 'INTERRUPTED'
    assert run['stage'] == 'DOWNLOAD'


def test_batch_interrupt_stops_remaining_reports(monkeypatch):
    worker = Mock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(process, 'process_report', worker)
    item = {'fund_id': 'IVV', 'status': 'STORED', 'source': {'bucket': 'b', 'key': 'k'}}
    with pytest.raises(KeyboardInterrupt):
        process.process_batch(Mock(), summary={'results': [item, item]}, database=Mock())
    worker.assert_called_once()
