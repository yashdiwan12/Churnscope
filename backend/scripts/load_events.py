"""Ingest a generated events.csv through the validated, idempotent ingestion service.

Usage: PYTHONPATH=. uv run python scripts/load_events.py ../data/processed/events.csv
Safe to re-run: duplicates are skipped by the database UNIQUE(event_id) constraint.
"""

import json
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.services.ingestion import MAX_BATCH, ingest_events


def main(path: Path) -> None:
    df = pd.read_csv(path)
    df["properties"] = df["properties"].map(json.loads)
    records = df.to_dict("records")
    totals = {"received": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
    with Session(get_engine()) as session:
        for i in range(0, len(records), MAX_BATCH):
            r = ingest_events(session, records[i : i + MAX_BATCH])
            totals["received"] += r.received
            totals["inserted"] += r.inserted
            totals["duplicates"] += r.duplicates
            totals["rejected"] += len(r.rejected)
    print(totals)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
