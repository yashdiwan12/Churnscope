"""Generate a SYNTHETIC event log (seeded, reproducible). Not real customer behaviour.

Usage: uv run python scripts/generate_events.py --customers 2000 --seed 42 --out ../data/processed

Each customer gets a latent engagement level and a churn week; they stop being active after
that week. The funnel/retention shapes are therefore properties of this generator, not findings.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

PLANS = ["free", "pro", "team"]
FEATURES = ["report_builder", "dashboards", "exports", "alerts"]


def generate(
    n_customers: int, seed: int, start: str, days: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start, tz="UTC")
    end = t0 + pd.Timedelta(days=days)

    signups = t0 + pd.to_timedelta(rng.integers(0, days - 14, n_customers), unit="D")
    signups += pd.to_timedelta(rng.integers(0, 86_400, n_customers), unit="s")
    customers = pd.DataFrame(
        {
            "external_customer_id": [f"c{i:05d}" for i in range(n_customers)],
            "created_at": signups,
            "plan": rng.choice(PLANS, n_customers, p=[0.6, 0.3, 0.1]),
        }
    )
    engagement = rng.gamma(2.0, 0.5, n_customers)  # mean 1.0
    churn_week = rng.geometric(0.12, n_customers)  # weeks after signup when activity stops
    p_onboard = rng.random(n_customers) < 0.75
    p_report = rng.random(n_customers) < 0.55
    p_share = rng.random(n_customers) < 0.4

    rows: list[tuple] = []
    seq = 0

    def add(cid: str, name: str, ts: pd.Timestamp, props: dict | None = None) -> None:
        nonlocal seq
        if ts < end:
            seq += 1
            rows.append((f"e{seq:08d}", cid, name, ts, props or {}))

    for i, row in customers.iterrows():
        cid, s = row["external_customer_id"], row["created_at"]
        add(cid, "signup", s)
        if p_onboard[i]:
            onboarded = s + pd.Timedelta(hours=float(rng.exponential(24)))
            add(cid, "onboarding_complete", onboarded)
            if p_report[i]:  # the key action follows onboarding, so funnel order is meaningful
                reported = onboarded + pd.Timedelta(hours=float(rng.exponential(48)) + 1)
                add(cid, "report_created", reported)
                if p_share[i]:
                    shared = reported + pd.Timedelta(hours=float(rng.exponential(48)) + 1)
                    add(cid, "report_shared", shared)
        active_until = s + pd.Timedelta(weeks=int(churn_week[i]))
        for w in range(int(churn_week[i])):
            for _ in range(rng.poisson(3 * engagement[i])):
                ts = s + pd.Timedelta(days=7 * w + float(rng.uniform(0, 7)))
                if ts >= active_until:
                    continue
                if rng.random() < 0.6:
                    add(cid, "session_start", ts)
                else:
                    add(cid, "feature_used", ts, {"feature": str(rng.choice(FEATURES))})

    events = pd.DataFrame(
        rows, columns=["event_id", "customer_id", "event_name", "event_timestamp", "properties"]
    )
    return customers, events.sort_values("event_timestamp").reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--out", type=Path, default=Path("../data/processed"))
    a = ap.parse_args()

    customers, events = generate(a.customers, a.seed, a.start, a.days)
    a.out.mkdir(parents=True, exist_ok=True)
    customers.to_csv(a.out / "customers.csv", index=False)
    events.assign(properties=events["properties"].map(lambda d: json.dumps(d))).to_csv(
        a.out / "events.csv", index=False
    )
    print(f"{len(customers)} customers, {len(events)} events -> {a.out} (seed={a.seed})")


if __name__ == "__main__":
    main()
