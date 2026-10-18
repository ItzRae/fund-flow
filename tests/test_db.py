"""check snapshot identity and persistence decisions offline."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from bson.decimal128 import Decimal128
from pymongo.errors import AutoReconnect

from fundflow.db import stable_hash, store_report


@pytest.fixture
def case():
    holding = {"name": "bond", "asset_class": "Fixed Income",
               "market_value": Decimal("1234.56"), "weight_percent": Decimal("0.25"),
               "raw": {"Name": "bond", "Market Value": "1,234.56"}}
    return {"report_date": date(2026, 10, 15), "accepted": [holding], "rejected": []}


SOURCE = {"fund-id": "SHY", "sha256": "a" * 64, "bucket": "test", "key": "report.csv"}


def test_hash_ignores_column_order_but_not_values():
    assert stable_hash({"a": "1", "b": "2"}) == stable_hash({"b": "2", "a": "1"})
    assert stable_hash({"a": "1"}) != stable_hash({"a": "2"})


def test_duplicates_skipped_and_decimal128_preserved(case):
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    db.holdings.update_one.return_value.upserted_id = "new"
    case["accepted"].append(case["accepted"][0].copy())
    run = store_report(db, report=case, source=SOURCE)
    assert (run["received"], run["accepted"], run["duplicates_skipped"], run["inserted"]) == (2, 1, 1, 1)
    document = db.holdings.update_one.call_args.args[1]["$setOnInsert"]
    assert document["market_value"] == Decimal128("1234.56")
    assert document["source"] == SOURCE
    assert db.holdings.create_index.call_args.kwargs["unique"] is True


def test_same_snapshot_new_attempt_and_unchanged_count(case):
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    db.holdings.update_one.return_value.upserted_id = None
    first = store_report(db, report=case, source=SOURCE)
    second = store_report(db, report=case, source=SOURCE)
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["_id"] != second["_id"]
    assert second["unchanged"] == 1
    changed = store_report(db, report=case, source={**SOURCE, "sha256": "b" * 64})
    assert changed["snapshot_id"] != first["snapshot_id"]


def test_partial_failure_records_acknowledged_progress(case):
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    second = {**case["accepted"][0], "raw": {"Name": "other bond"}}
    case["accepted"].append(second)
    db.holdings.update_one.side_effect = [Mock(upserted_id="first"), AutoReconnect("offline")]
    with pytest.raises(AutoReconnect):
        store_report(db, report=case, source=SOURCE)
    failure = db.processing_runs.update_one.call_args.args[1]["$set"]
    assert failure["status"] == "FAILED"
    assert failure["stage"] == "WRITE_HOLDINGS"
    assert failure["inserted"] == 1


def test_all_rejected_writes_no_holdings(case):
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    case["accepted"] = []
    case["rejected"] = [{"holding_number": 1, "reason": "missing name", "raw": {}}]
    result = store_report(db, report=case, source=SOURCE)
    assert result["status"] == "VALIDATION_FAILED"
    db.holdings.update_one.assert_not_called()


@pytest.mark.parametrize('version', [None, 'older-version'])
def test_refuse_legacy_or_different_processing_version(case, version):
    db = Mock()
    db.report_snapshots.find_one.return_value = {'processing_version': version}
    with pytest.raises(ValueError, match='explicit rebuild'):
        store_report(db, report=case, source=SOURCE)
    db.holdings.update_one.assert_not_called()
    db.report_snapshots.update_one.assert_not_called()
    failure = db.processing_runs.update_one.call_args.args[1]['$set']
    assert failure['stage'] == 'CHECK_PROCESSING_VERSION'
    assert failure['status'] == 'FAILED'


def test_same_version_can_retry_without_new_holdings(case):
    from fundflow.db import PROCESSING_VERSION
    db = Mock()
    db.report_snapshots.find_one.return_value = {'processing_version': PROCESSING_VERSION}
    db.holdings.update_one.return_value.upserted_id = None
    result = store_report(db, report=case, source=SOURCE)
    assert result['unchanged'] == 1
    assert result['processing_version'] == PROCESSING_VERSION


@pytest.mark.parametrize('stage', ['PREPARE_DOCUMENTS', 'ENSURE_INDEXES', 'RECORD_RUN'])
def test_early_failures_record_stage(case, stage, caplog):
    db = Mock()
    if stage == 'PREPARE_DOCUMENTS':
        # valid python decimal, but too precise to encode as decimal128 without rounding
        case['accepted'][0]['market_value'] = Decimal('1.12345678901234567890123456789012345')
    elif stage == 'ENSURE_INDEXES':
        db.holdings.create_index.side_effect = AutoReconnect('offline')
    else:
        db.processing_runs.update_one.side_effect = [AutoReconnect('offline'), Mock()]
    with pytest.raises(Exception):
        store_report(db, report=case, source=SOURCE)
    failure = db.processing_runs.update_one.call_args.args[1]['$set']
    assert failure['stage'] == stage
    assert failure['status'] == 'FAILED'
    assert stage in caplog.text
    db.holdings.update_one.assert_not_called()


def test_original_error_survives_failed_error_recording(case, caplog):
    db = Mock()
    original = AutoReconnect('private connection details')
    db.holdings.create_index.side_effect = original
    db.processing_runs.update_one.side_effect = AutoReconnect('also offline')
    with pytest.raises(AutoReconnect) as caught:
        store_report(db, report=case, source=SOURCE)
    assert caught.value is original
    assert 'ENSURE_INDEXES' in caplog.text
    assert 'private connection details' not in caplog.text
