"""prepare(): mapping, duplicates, the 5% rule, derived signup and capabilities. No database."""

import hashlib

import pandas as pd
import pytest

from app.db.models import Dataset
from app.services.metrics import FUNNEL_STEPS
from app.services.uploads import (
    UploadRejected,
    capabilities,
    derive_event_id,
    parse_csv,
    prepare,
)

NOW = pd.Timestamp("2026-06-01T12:00:00Z")
HEAD = "customer_id,event_name,event_timestamp\n"
HEAD_ID = "customer_id,event_name,event_timestamp,event_id\n"
MAP = {"login": "session_start", "join": "signup", "noise": None}


def parsed(*rows: str, head: str = HEAD):
    return parse_csv((head + "".join(r + "\n" for r in rows)).encode(), NOW)


def ts(day: int, sec: int = 0) -> str:
    return f"2026-03-{day:02d}T00:00:{sec:02d}Z"


def fit(p) -> dict:
    """MAP restricted to the names in the file (a mapping may only name those)."""
    present = set(p.rows["source_name"])
    return {k: v for k, v in MAP.items() if k in present}


def run(p, derive: bool = False, ack: bool = False):
    return prepare(p, fit(p), derive_signup=derive, acknowledged=ack)


def rejected(*args, **kw) -> str:
    with pytest.raises(UploadRejected) as info:
        prepare(*args, **kw)
    return info.value.code


def run_rejected(p, derive: bool = False, ack: bool = False) -> str:
    return rejected(p, fit(p), derive_signup=derive, acknowledged=ack)


def test_identical_rows_are_duplicates():
    p = run(parsed(f"u1,login,{ts(5)}", f"u1,login,{ts(5)}", f"u1,join,{ts(4)}"))
    assert len(p.events) == 2
    assert p.duplicate_rows == 1
    assert p.mapped_counts == {"session_start": 1, "signup": 1}


def test_derived_event_id_is_stable():
    t = pd.Timestamp("2026-03-05T00:00:00Z")
    a = derive_event_id("u1", "session_start", t)
    assert a == derive_event_id("u1", "session_start", t)
    assert a == hashlib.sha256(f"u1|session_start|{t.isoformat()}".encode()).hexdigest()[:32]
    assert a != derive_event_id("u1", "session_start", t + pd.Timedelta(seconds=1))
    assert len(a) == 32


def test_supplied_event_id_duplicates_keep_first():
    p = run(
        parsed(
            f"u1,login,{ts(5)},e1",
            f"u2,login,{ts(6)},e1",
            f"u1,join,{ts(4)},e2",
            head=HEAD_ID,
        )
    )
    assert p.duplicate_rows == 1
    kept = p.events.set_index("event_id").loc["e1"]
    assert kept["customer_id"] == "u1"


def five_percent_file(invalid: int, counted: int, ignored: int, dups: int) -> list[str]:
    """`counted` rows enter the 5% rule (valid unique mapped rows plus `invalid` bad rows)."""
    rows = [f"u{i},login,{ts(5)}" for i in range(counted - invalid)]
    rows += [f"u{i},login,garbage" for i in range(invalid)]
    rows += [f"n{i},noise,{ts(6)}" for i in range(ignored)]
    rows += [rows[0]] * dups
    return rows


def test_invalid_share_excludes_ignored_and_duplicates():
    # 4 invalid of the 100 rows that count; 30 ignored and 10 duplicate rows are left out.
    ok = run(parsed(*five_percent_file(4, 100, 30, 10)))
    assert (ok.invalid_rows, ok.ignored_rows, ok.duplicate_rows) == (4, 30, 10)
    assert [c for _, c in ok.skipped] == ["bad_timestamp"] * 4
    # 6 of 100 counted is over 5%, although 6 of all 140 rows would not be.
    assert run_rejected(parsed(*five_percent_file(6, 100, 30, 10))) == "too_many_invalid"
    assert run_rejected(parsed(*five_percent_file(7, 100, 0, 0))) == "too_many_invalid"
    # Bad rows of an ignored event name are not counted as invalid.
    noisy = five_percent_file(0, 100, 5, 0) + [f"n{i},noise,garbage" for i in range(20)]
    p = run(parsed(*noisy))
    assert (p.invalid_rows, p.ignored_rows, p.skipped) == (0, 25, [])
    # A name seen only on bad rows is not one the user could ignore: those rows count.
    only_bad = five_percent_file(0, 100, 0, 0) + [f"z{i},mystery,garbage" for i in range(6)]
    assert run_rejected(parsed(*only_bad)) == "too_many_invalid"


def test_invalid_share_at_the_limit_is_accepted():
    p = run(parsed(*five_percent_file(5, 100, 0, 0)))
    assert p.invalid_rows == 5


@pytest.mark.parametrize(
    "mapping",
    [
        {"login": "logged_in"},  # target not one of our names
        {"login": "session_start", "absent_name": "signup"},  # key not in the file
        {"login": 3},
    ],
)
def test_mapping_must_target_known_names(mapping):
    assert rejected(parsed(f"u1,login,{ts(5)}"), mapping, False, False) == "bad_mapping"


def test_needs_an_activity_event():
    rows = parsed(f"u1,join,{ts(5)}", f"u1,login,{ts(6)}")
    assert rejected(rows, {"join": "signup"}, False, False) == "no_activity_event"


def test_derive_only_when_nothing_maps_to_signup():
    rows = parsed(f"u1,join,{ts(5)}", f"u1,login,{ts(6)}")
    assert run_rejected(rows, derive=True, ack=True) == "derive_not_allowed"


def test_derived_signup_per_customer_at_first_event():
    rows = parsed(
        f"u1,login,{ts(9)}",
        f"u1,login,{ts(7)}",
        f"u1,noise,{ts(1)}",  # ignored: not a mapped event, so not the first one
        f"u2,login,{ts(20)}",
        *[f"x{i},login,{ts(25)}" for i in range(8)],  # keeps the first-week share low
    )
    p = prepare(rows, {"login": "session_start"}, derive_signup=True, acknowledged=False)
    assert p.signup_rule == "derived_from_first_event"
    assert p.derived_signups == 10
    signups = p.events[p.events["event_name"] == "signup"].set_index("customer_id")
    assert signups.loc["u1", "event_timestamp"] == pd.Timestamp(ts(7))
    assert signups.loc["u2", "event_timestamp"] == pd.Timestamp(ts(20))
    assert all(prop == {"derived": True} for prop in signups["properties"])
    assert p.mapped_counts["signup"] == 10
    created = p.customers.set_index("customer_id")["created_at"]
    assert created.loc["u1"] == pd.Timestamp(ts(7))


def test_acknowledgement_required_when_censored():
    rows = parsed(f"u1,login,{ts(1)}", f"u2,login,{ts(2)}", f"u3,login,{ts(20)}")
    m = {"login": "session_start"}
    assert rejected(rows, m, derive_signup=True, acknowledged=False) == "acknowledgement_required"
    assert prepare(rows, m, derive_signup=True, acknowledged=True).derived_signups == 3
    assert prepare(rows, m, derive_signup=False, acknowledged=False).derived_signups == 0


def upload(mapped_counts: dict, signup_rule: str = "event") -> Dataset:
    return Dataset(kind="upload", mapped_counts=mapped_counts, signup_rule=signup_rule)


def test_capabilities_shapes():
    none = capabilities(upload({"session_start": 5}))
    assert none["overview"] and none["engagement"]
    assert none["retention"] is False and none["funnel"] is False and none["churn"] is False
    assert none["funnel_missing"] == list(FUNNEL_STEPS)

    derived = capabilities(upload({"session_start": 5, "signup": 2}, "derived_from_first_event"))
    assert derived["retention"] is True
    assert derived["funnel_missing"] == [s for s in FUNNEL_STEPS if s != "signup"]

    full = capabilities(upload({s: 1 for s in FUNNEL_STEPS} | {"session_start": 1}))
    assert full["funnel"] is True and full["funnel_missing"] == [] and full["churn"] is False

    demo = capabilities(Dataset(kind="demo", mapped_counts={}, signup_rule="event"))
    assert all(demo[k] for k in ("overview", "engagement", "retention", "funnel", "churn"))
    assert demo["funnel_missing"] == []
