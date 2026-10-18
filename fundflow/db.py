"""load local database settings and check the mongodb connection."""

import os
import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


def stable_hash(value: dict) -> str:
    """hash field contents consistently, regardless of dictionary key order."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ensure_indexes(database):
    """let mongodb enforce the same uniqueness rules as our upsert filters """
    database.report_snapshots.create_index([("fund_id", 1), ("file_sha256", 1)], unique=True)
    database.holdings.create_index([("snapshot_id", 1), ("row_hash", 1)], unique=True)


def store_report(database, *, report: dict, source: dict) -> dict:
    """store an immutable snapshot and a separate record for each processing attempt

    exact duplicate accepted rows are skipped. row hashes identify snapshot rows,
    not securities across funds or dates. changed files create new snapshots.
    """
    # same fund and file checksum produce the same snapshot ID
    snapshot_id = stable_hash({"fund_id": source["fund-id"], "sha256": source["sha256"]})
    # each processing attempt gets a fresh random ID + timestamp
    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    documents = {}
    for holding in report["accepted"]:
        # deduplicate identical raw rows
        row_hash = stable_hash(holding["raw"])
        documents[row_hash] = {
            "snapshot_id": snapshot_id, "row_hash": row_hash,
            "fund_id": source["fund-id"], "report_date": report["report_date"].isoformat(),
            **holding,
            "market_value": Decimal128(holding["market_value"]),
            "weight_percent": Decimal128(holding["weight_percent"]),
            "source": source, "created_at": now,
        }
    run = {
        "_id": run_id, "snapshot_id": snapshot_id, "source": source,
        "started_at": now, "status": "RUNNING",
        "received": len(report["accepted"]) + len(report["rejected"]),
        "accepted": len(documents), "rejected": len(report["rejected"]),
        "duplicates_skipped": len(report["accepted"]) - len(documents),
        "inserted": 0, "unchanged": 0, "rejections": report["rejected"],
    }
    ensure_indexes(database)
    database.processing_runs.insert_one(run.copy())
    try:
        database.report_snapshots.update_one(
            # fields applied only during insertion
            {"_id": snapshot_id}, {"$setOnInsert": {
                "fund_id": source["fund-id"], "file_sha256": source["sha256"],
                "report_date": report["report_date"].isoformat(), "source": source,
                "created_at": now,
            }}, upsert=True,
        )
        for row_hash, document in documents.items():
            # for each holding
            result = database.holdings.update_one(
                {"snapshot_id": snapshot_id, "row_hash": row_hash},
                {"$setOnInsert": document}, upsert=True,
            )
            # so report safely reprocessed wo duplicate holdings 
            run["inserted" if result.upserted_id is not None else "unchanged"] += 1
        run["status"] = ("VALIDATION_FAILED" if not documents else
                         "COMPLETED_WITH_REJECTIONS" if run["rejected"] 
                         else "COMPLETED")
        run["finished_at"] = datetime.now(timezone.utc)
        # updates an existing doc's fields,
        # exclude _id bc mongodb's document ID is immutable
        database.processing_runs.update_one({"_id": run_id}, {"$set": {
            key: value for key, value in run.items() if key != "_id"
        }})
    except PyMongoError as exc:
        # acknowledged writes remain stored; the same keys make retrying safe
        failure = {"status": "DB_WRITE_FAILED", "error_type": type(exc).__name__,
                   "inserted": run["inserted"], "unchanged": run["unchanged"],
                   "finished_at": datetime.now(timezone.utc)}
        try:
            database.processing_runs.update_one({"_id": run_id}, {"$set": failure})
        except PyMongoError:
            logging.error(json.dumps({"run_id": run_id, "status": "DB_WRITE_FAILED",
                                      "inserted": run["inserted"], "unchanged": run["unchanged"]}))
        raise
    return run


def create_client() -> MongoClient:
    """read the uri without hardcoding credentials; the caller closes the client."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise ValueError("Set MONGODB_URI in the environment or project .env file")
    return MongoClient(uri, serverSelectionTimeoutMS=10000,
                       connectTimeoutMS=10000, socketTimeoutMS=10000)


def main() -> int:
    try:
        # ping checks connectivity without creating collections or writing records
        with create_client() as client:
            client.admin.command("ping")
    except (PyMongoError, ValueError) as exc:
        # avoid printing connection details that might contain credentials
        print(f"MongoDB connection failed ({type(exc).__name__}).")
        return 1
    print("MongoDB ping succeeded. No records written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
