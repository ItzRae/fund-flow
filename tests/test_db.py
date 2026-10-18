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
    second = {**case["accepted"][0], "raw": {"Name": "other bond"}}
    case["accepted"].append(second)
    db.holdings.update_one.side_effect = [Mock(upserted_id="first"), AutoReconnect("offline")]
    with pytest.raises(AutoReconnect):
        store_report(db, report=case, source=SOURCE)
    failure = db.processing_runs.update_one.call_args.args[1]["$set"]
    assert failure["status"] == "DB_WRITE_FAILED"
    assert failure["inserted"] == 1


def test_all_rejected_writes_no_holdings(case):
    db = Mock()
    case["accepted"] = []
    case["rejected"] = [{"holding_number": 1, "reason": "missing name", "raw": {}}]
    result = store_report(db, report=case, source=SOURCE)
    assert result["status"] == "VALIDATION_FAILED"
    db.holdings.update_one.assert_not_called()
