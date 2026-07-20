"""Force cost-attribution aggregation immediately, without waiting for the scheduler.

Cost Overview and Compression ROI in the dashboard read from the
`cost_attribution` table, not raw spans directly. That table is normally
populated by an hourly APScheduler job (`materialize_hourly`, see
`workers/scheduler.py`) that only aggregates already-*completed* hours —
so freshly-seeded demo data can sit invisible for up to ~1-2 hours until
the scheduler catches up to it.

This script calls the same aggregation function directly against the last
N hours (including the current, still-in-progress one), so seeded data
shows up in the dashboard immediately. Safe to re-run: the underlying
upsert is idempotent.

Usage:
    DATABASE_URL=postgresql+asyncpg://user:pass@host/db \\
        python backend/scripts/materialize_attribution.py --hours-back 3
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from traject_backend.core.database import AsyncSessionLocal
from traject_backend.services.cost_attribution import materialize_hourly


async def run(hours_back: int) -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        for i in range(hours_back + 1):
            hour = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
            rows = await materialize_hourly(db, hour)
            print(f"Hour {hour.isoformat()}: {rows} row(s) materialized")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours-back",
        type=int,
        default=3,
        help="How many hours before the current one to also (re-)materialize",
    )
    args = parser.parse_args()
    asyncio.run(run(args.hours_back))


if __name__ == "__main__":
    main()
