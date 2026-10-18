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


# bump this when parsing or validation changes the meaning of stored holdings
PROCESSING_VERSION = "1"


def new_attempt(source: dict) -> dict:
    """give even an early failure an id, time, and source reference."""
    return {"_id": str(uuid4()), "source": source,
            "processing_version": PROCESSING_VERSION,
            "started_at": datetime.now(timezone.utc), "status": "RUNNING",
            "stage": "START", "inserted": 0, "unchanged": 0}


def save_attempt(database, run: dict):
    # upsert also works when the initial run write failed or never happened
    database.processing_runs.update_one(
        {"_id": run["_id"]},
        {"$set": {key: value for key, value in run.items() if key != "_id"}},
        upsert=True,
    )


def record_failure(database, run: dict, exc: Exception):
    """record the stage without exposing credentials from driver error messages."""
    run.update(status="FAILED", error_type=type(exc).__name__,
               finished_at=datetime.now(timezone.utc))
    # always keep a local fallback, including when mongodb itself is unavailable
    logging.error(json.dumps({"run_id": run["_id"], "stage": run["stage"],
                              "status": run["status"], "error_type": run["error_type"],
                              "inserted": run["inserted"], "unchanged": run["unchanged"],
                              "source_bucket": run["source"].get("bucket"),
                              "source_key": run["source"].get("key")}))
    if database is not None:
        try:
            save_attempt(database, run)
        except Exception:
            # failure recording must not replace the error that caused the failure
            pass


def store_report(database, *, report: dict, source: dict, attempt=None) -> dict:
    """store a snapshot once; reject a different interpretation until explicitly rebuilt.

    raw-row hashes prevent exact duplicates, not conflicting security positions.
    versionless snapshots are treated as legacy and are never silently adopted.
    """
    run = attempt if attempt is not None else new_attempt(source)
    run["source"] = source
    try:
        run["stage"] = "PREPARE_DOCUMENTS"
        snapshot_id = stable_hash({"fund_id": source["fund-id"], "sha256": source["sha256"]})
        run["snapshot_id"] = snapshot_id
        documents = {}
        for holding in report["accepted"]:
            row_hash = stable_hash(holding["raw"])
            documents[row_hash] = {
                "snapshot_id": snapshot_id, "row_hash": row_hash,
                "processing_version": PROCESSING_VERSION,
                "fund_id": source["fund-id"], "report_date": report["report_date"].isoformat(),
                **holding,
                "market_value": Decimal128(holding["market_value"]),
                "weight_percent": Decimal128(holding["weight_percent"]),
                "source": source, "created_at": run["started_at"],
            }
        run.update(received=len(report["accepted"]) + len(report["rejected"]),
                   accepted=len(documents), rejected=len(report["rejected"]),
                   duplicates_skipped=len(report["accepted"]) - len(documents),
                   rejections=report["rejected"])
        run["stage"] = "ENSURE_INDEXES"
        ensure_indexes(database)
        run["stage"] = "RECORD_RUN"
        save_attempt(database, run)
        run["stage"] = "CHECK_PROCESSING_VERSION"
        existing = database.report_snapshots.find_one({"_id": snapshot_id})
        if existing is not None and existing.get("processing_version") != PROCESSING_VERSION:
            raise ValueError("Snapshot processing version differs or is missing; an explicit rebuild is required")
        run["stage"] = "WRITE_SNAPSHOT"
        database.report_snapshots.update_one(
            {"_id": snapshot_id}, {"$setOnInsert": {
                "fund_id": source["fund-id"], "file_sha256": source["sha256"],
                "processing_version": PROCESSING_VERSION,
                "report_date": report["report_date"].isoformat(), "source": source,
                "created_at": run["started_at"],
            }}, upsert=True,
        )
        run["stage"] = "WRITE_HOLDINGS"
        for row_hash, document in documents.items():
            result = database.holdings.update_one(
                {"snapshot_id": snapshot_id, "row_hash": row_hash},
                {"$setOnInsert": document}, upsert=True,
            )
            # these counts cover acknowledged writes; a lost reply can leave uncertainty
            run["inserted" if result.upserted_id is not None else "unchanged"] += 1
        run["status"] = ("VALIDATION_FAILED" if not documents else
                         "COMPLETED_WITH_REJECTIONS" if run["rejected"] else "COMPLETED")
        run["finished_at"] = datetime.now(timezone.utc)
        run["stage"] = "FINALIZE_RUN"
        save_attempt(database, run)
    except Exception as exc:
        record_failure(database, run, exc)
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
