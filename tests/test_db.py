""" check snapshot identity and persistence decisions offline"""

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
    db.holdings.bulk_write.return_value = Mock(upserted_count=1, matched_count=0)
    case["accepted"].append(case["accepted"][0].copy())
    run = store_report(db, report=case, source=SOURCE)
    assert (run["received"], run["accepted"], run["duplicates_skipped"], run["inserted"]) == (2, 1, 1, 1)
    document = db.holdings.bulk_write.call_args.args[0][0]._doc["$setOnInsert"]
    assert document["market_value"] == Decimal128("1234.56")
    assert document["source"] == SOURCE
    assert db.holdings.create_index.call_args.kwargs["unique"] is True


def test_same_snapshot_new_attempt_and_unchanged_count(case):
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    db.holdings.bulk_write.return_value = Mock(upserted_count=0, matched_count=1)
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
    db.holdings.bulk_write.side_effect = [Mock(upserted_count=1, matched_count=0), AutoReconnect("offline")]
    with pytest.raises(AutoReconnect):
        store_report(db, report=case, source=SOURCE, batch_size=1)
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
    db.holdings.bulk_write.assert_not_called()


@pytest.mark.parametrize('version', [None, 'older-version'])
def test_refuse_legacy_or_different_processing_version(case, version):
    db = Mock()
    db.report_snapshots.find_one.return_value = {'processing_version': version}
    with pytest.raises(ValueError, match='explicit rebuild'):
        store_report(db, report=case, source=SOURCE)
    db.holdings.bulk_write.assert_not_called()
    db.report_snapshots.update_one.assert_not_called()
    failure = db.processing_runs.update_one.call_args.args[1]['$set']
    assert failure['stage'] == 'CHECK_PROCESSING_VERSION'
    assert failure['status'] == 'FAILED'


def test_same_version_can_retry_without_new_holdings(case):
    from fundflow.db import PROCESSING_VERSION
    db = Mock()
    db.report_snapshots.find_one.return_value = {'processing_version': PROCESSING_VERSION}
    db.holdings.bulk_write.return_value = Mock(upserted_count=0, matched_count=1)
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
    db.holdings.bulk_write.assert_not_called()


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


def test_bulk_chunks_save_counts_and_print_progress(case, capsys):
    from copy import deepcopy
    case['accepted'] = [{**case['accepted'][0], 'raw': {'Name': str(i)}} for i in range(5)]
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    db.holdings.bulk_write.side_effect = [Mock(upserted_count=2, matched_count=0),
                                          Mock(upserted_count=1, matched_count=1),
                                          Mock(upserted_count=0, matched_count=1)]
    saved = []
    db.processing_runs.update_one.side_effect = lambda *a, **kw: saved.append(deepcopy(a[1]['$set']))
    result = store_report(db, report=case, source=SOURCE, batch_size=2)
    assert [len(call.args[0]) for call in db.holdings.bulk_write.call_args_list] == [2, 2, 1]
    assert all(call.kwargs['ordered'] for call in db.holdings.bulk_write.call_args_list)
    assert (result['inserted'], result['unchanged']) == (3, 2)
    assert [r['processed'] for r in saved if r['stage'] == 'WRITE_HOLDINGS'] == [0, 2, 4, 5]
    assert 'SHY: 5/5 holdings' in capsys.readouterr().err


@pytest.mark.parametrize('write_concern', [False, True])
def test_bulk_error_partial_counts_and_uncertainty(case, write_concern):
    from pymongo.errors import BulkWriteError
    case['accepted'] = [{**case['accepted'][0], 'raw': {'Name': str(i)}} for i in range(3)]
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    db.holdings.bulk_write.side_effect = BulkWriteError({
        'nUpserted': 1, 'nMatched': 1,
        'writeErrors': [{'index': 2, 'code': 11000, 'errmsg': 'duplicate'}],
        'writeConcernErrors': [{'code': 64, 'errmsg': 'timeout'}] if write_concern else [],
    })
    with pytest.raises(BulkWriteError):
        store_report(db, report=case, source=SOURCE)
    failure = db.processing_runs.update_one.call_args.args[1]['$set']
    assert failure['processed'] == (0 if write_concern else 2)
    assert failure['write_outcome_uncertain'] == write_concern
    assert failure['status'] == 'FAILED'


def test_interrupt_preserves_completed_batches(case):
    db = Mock()
    db.report_snapshots.find_one.return_value = None
    case['accepted'].append({**case['accepted'][0], 'raw': {'Name': 'second'}})
    db.holdings.bulk_write.side_effect = [Mock(upserted_count=1, matched_count=0), KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        store_report(db, report=case, source=SOURCE, batch_size=1)
    failure = db.processing_runs.update_one.call_args.args[1]['$set']
    assert failure['status'] == 'INTERRUPTED'
    assert failure['inserted'] == 1
    assert failure['write_outcome_uncertain'] is True
