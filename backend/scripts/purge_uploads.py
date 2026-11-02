"""Delete uploaded datasets older than a number of days (customers and events cascade).

Usage: PYTHONPATH=. uv run python scripts/purge_uploads.py --older-than 30 [--dry-run]
Reads DATABASE_URL from the environment. Prints counts only: never customer ids, file names or
anything from a file. The demo dataset is never touched. This is a separate process, so it cannot
clear a running API's in-memory churn cache: restart the API if stale rows matter (see the runbook).
"""

import argparse
import sys

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db.models import Dataset
from app.db.session import get_engine


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def purge(session: Session, days: int, dry_run: bool) -> int:
    """Number of old uploads found (dry run) or deleted. Commits only on a real run."""
    cutoff = func.now() - func.make_interval(0, 0, 0, days)
    old = (Dataset.kind == "upload") & (Dataset.created_at < cutoff)
    if dry_run:
        return int(session.scalar(select(func.count()).select_from(Dataset).where(old)))
    # Same global lock as an import, so a purge never interleaves with a replace.
    from app.services import uploads

    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": uploads.IMPORT_LOCK_KEY})
    deleted = session.execute(delete(Dataset).where(old)).rowcount
    session.commit()
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete uploads older than DAYS days.")
    parser.add_argument("--older-than", type=positive_int, required=True, metavar="DAYS")
    parser.add_argument("--dry-run", action="store_true", help="count only, delete nothing")
    args = parser.parse_args(argv)
    with Session(get_engine()) as session:
        count = purge(session, args.older_than, args.dry_run)
    if args.dry_run:
        print(f"dry run: {count} upload(s) older than {args.older_than} day(s) would be deleted")
    else:
        print(f"deleted {count} upload(s) older than {args.older_than} day(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
