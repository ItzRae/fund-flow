import os
from contextlib import asynccontextmanager
from pathlib import Path

from pymongo import DESCENDING
from pymongo.errors import PyMongoError

from fastapi import FastAPI, HTTPException, Request
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
