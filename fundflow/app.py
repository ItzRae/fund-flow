import re
from typing import Literal
import os
from contextlib import asynccontextmanager
from pathlib import Path

from pymongo import DESCENDING
from pymongo.errors import PyMongoError

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from fundflow.db import create_client


@asynccontextmanager
async def lifespan(app):
    # reuse one client, then close its connections when the server stops
    client = create_client()
    app.state.database = client[os.getenv("MONGODB_DATABASE", "fundflow")]
    try:
        yield
    finally:
        client.close()

app = FastAPI(lifespan=lifespan)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "index.html")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/funds")
def list_funds(request: Request):
    database = request.app.state.database
    try:
        results = database["processing_runs"].find().sort([
            ("started_at", DESCENDING),
            ("_id", DESCENDING)
        ])
        funds = []
        seen_funds = set()

        for run in results:
            fund_id = run.get("source", {}).get("fund-id")
            # newest comes first, so skip any older runs for the same fund
            if not fund_id or fund_id in seen_funds:
                continue
            seen_funds.add(fund_id)

            # a run can fail before its snapshot is created
            snapshot = None
            if run.get("snapshot_id"):
                snapshot = database["report_snapshots"].find_one(
                    {"_id": run["snapshot_id"]}
                )

            funds.append({
                "fund_id": fund_id,
                "report_date": snapshot.get("report_date") if snapshot else None,
                "accepted": run.get("accepted"),
                "rejected": run.get("rejected"),
                "status": run.get("status"),
            })

        return {"funds": funds}
    except PyMongoError:
        raise HTTPException(
            status_code=503, detail="Could not load fund results. Try again later."
        ) from None


@app.get("/api/funds/{fund_id}/runs")
def list_fund_runs(fund_id: str, request: Request):
    database = request.app.state.database

    try:
        # dot notation for nested dict
        results = database["processing_runs"].find({"source.fund-id": fund_id})
        results.sort([
            ("started_at", DESCENDING),
            ("_id", DESCENDING)
        ]).limit(20)
        runs = []

        for run in results:
            run_id = run.get("_id")

            if not run_id:
                continue

            runs.append({
                "run_id": run_id,
                "status": run.get("status"),
                "started_at": run.get("started_at"),
                "accepted": run.get("accepted"),
                "rejected": run.get("rejected"),
                "inserted": run.get("inserted"),
                "unchanged": run.get("unchanged")
            })

        return {"fund_id": fund_id, "runs": runs}
    except PyMongoError:
        raise HTTPException(
            status_code=503, detail="Could not load fund results. Try again later."
        ) from None


@app.get("/api/funds/{fund_id}/holdings")
def list_fund_holdings(
    fund_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    sort_by: Literal["weight_percent", "market_value", "name"] = "weight_percent",
    direction: Literal["asc", "desc"] = "desc",
    asset_class: str = Query(default="", max_length=100),
    search: str = Query(default="", max_length=100),
):
    database = request.app.state.database
    try:
        run = database["processing_runs"].find_one(
            {
                "source.fund-id": fund_id,
                "status": {"$in": ["COMPLETED", "COMPLETED_WITH_REJECTIONS"]},
            },
            sort=[("started_at", DESCENDING), ("_id", DESCENDING)],
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail="No successfully processed report found for this fund.",
            )

        snapshot_id = run["snapshot_id"]
        snapshot = database["report_snapshots"].find_one({"_id": snapshot_id})
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Report snapshot not found.")

        # count the whole report, then fetch just the requested page
        holdings_filter = {"snapshot_id": snapshot_id}
        # options come from the full snapshot so filtering does not hide choices
        asset_classes = sorted(database["holdings"].distinct("asset_class", holdings_filter))
        if asset_class:
            holdings_filter["asset_class"] = asset_class
        if search.strip():
            # treat user text literally, not as a regular expression
            holdings_filter["name"] = {"$regex": re.escape(search.strip()), "$options": "i"}
        total = database["holdings"].count_documents(holdings_filter)
        results = (
            database["holdings"].find(holdings_filter)
            .sort([(sort_by, 1 if direction == "asc" else -1), ("row_hash", 1)])
            .skip(offset)
            .limit(limit)
        )

        holdings = []
        for holding in results:
            # each dictionary here represents one holding, not the whole response
            holdings.append({
                "currency": holding.get("raw", {}).get("Currency"),
                "name": holding["name"],
                "asset_class": holding["asset_class"],
                "market_value": str(holding["market_value"].to_decimal()),
                "weight_percent": str(holding["weight_percent"].to_decimal()),
            })

        # report details and pagination belong outside the list of holdings
        return {
            "fund_id": fund_id,
            "snapshot_id": snapshot_id,
            "report_date": snapshot["report_date"],
            "total": total,
            "offset": offset,
            "limit": limit,
            "holdings": holdings,
            "asset_classes": asset_classes,
            "rejected": run.get("rejected"),
        }
    except PyMongoError:
        raise HTTPException(
            status_code=503, detail="Could not load holdings. Try again later."
        ) from None
