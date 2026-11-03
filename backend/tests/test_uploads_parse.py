"""CSV parser: pure, no database. No value from the file may reach a message or a log."""

import logging

import pandas as pd
import pytest

from app.services.uploads import (
    MAX_CUSTOMERS,
    MAX_EVENT_NAMES,
    MAX_ROWS,
    UploadRejected,
    first_week_share,
    normalise,
    parse_csv,
    suggest_mapping,
)

NOW = pd.Timestamp("2026-06-01T12:00:00Z")
HEAD = "customer_id,event_name,event_timestamp\n"
OK_TS = "2026-01-05T00:00:00Z"


def csv(*rows: str, head: str = HEAD) -> bytes:
    return (head + "".join(r + "\n" for r in rows)).encode()


def rejected(raw: bytes) -> UploadRejected:
    with pytest.raises(UploadRejected) as info:
        parse_csv(raw, NOW)
    return info.value


def test_parses_bom_crlf_quotes_and_header_case():
    raw = (
        "﻿ Customer_ID , EVENT_NAME ,Event_Timestamp\r\n"
        'u1,"Session, Start",2026-01-05T10:00:00Z\r\n'
        "u2,login,2026-01-06T10:00:00+02:00\r\n"
    ).encode()
    parsed = parse_csv(raw, NOW)
    assert parsed.total_rows == 2
    assert parsed.skipped == []
    assert list(parsed.rows["customer_id"]) == ["u1", "u2"]
    assert list(parsed.rows["source_name"]) == ["Session, Start", "login"]
    assert parsed.rows["event_timestamp"].iloc[1] == pd.Timestamp("2026-01-06T08:00:00Z")
    assert all(v is None for v in parsed.rows["event_id"])
    assert parsed.zoneless is False


def test_zoneless_timestamp_is_utc_and_flagged():
    parsed = parse_csv(csv("u1,login,2026-01-05 10:00:00", "u2,login,2026-01-05"), NOW)
    assert parsed.zoneless is True
    assert parsed.rows["event_timestamp"].iloc[0] == pd.Timestamp("2026-01-05T10:00:00Z")
    assert str(parsed.rows["event_timestamp"].dt.tz) == "UTC"


def test_latin1_is_not_utf8():
    raw = HEAD.encode() + "caf\xe9,login,2026-01-05\n".encode("latin-1")
    assert rejected(raw).code == "not_utf8"


def test_missing_column_rejected():
    err = rejected(b"customer_id,event_name\nu1,login\n")
    assert err.code == "missing_columns"
    assert err.status == 422


def test_row_skip_codes():
    parsed = parse_csv(
        csv(
            f",login,{OK_TS}",
            f"u1,,{OK_TS}",
            "u1,login,not-a-date",
            "u1,login,1999-12-31T00:00:00Z",
            f"{'x' * 101},login,{OK_TS}",
            f"u1,login,{OK_TS}",
        ),
        NOW,
    )
    assert parsed.skipped == [
        (1, "missing_customer_id"),
        (2, "missing_event_name"),
        (3, "bad_timestamp"),
        (4, "timestamp_out_of_range"),
        (5, "value_too_long"),
    ]
    assert parsed.total_rows == 6
    assert list(parsed.rows["row"]) == [6]


def test_timestamp_bounds():
    ok = (NOW + pd.Timedelta(minutes=5)).isoformat()
    late = (NOW + pd.Timedelta(minutes=5, seconds=1)).isoformat()
    parsed = parse_csv(csv(f"u1,login,{ok}", f"u1,login,{late}"), NOW)
    assert parsed.skipped == [(2, "timestamp_out_of_range")]


def test_limits():
    assert rejected(b"").code == "empty_file"
    assert rejected(HEAD.encode()).code == "empty_file"
    many = csv(*[f"u1,login,{OK_TS}"] * (MAX_ROWS + 1))
    assert rejected(many).code == "too_many_rows"
    cust = csv(*[f"u{i},login,{OK_TS}" for i in range(MAX_CUSTOMERS + 1)])
    assert rejected(cust).code == "too_many_customers"
    names = csv(*[f"u1,n{i},{OK_TS}" for i in range(MAX_EVENT_NAMES + 1)])
    assert rejected(names).code == "too_many_event_names"


def test_extra_columns_ignored():
    raw = b"plan,customer_id,event_name,event_timestamp,event_id\nfree,u1,login,2026-01-05,e1\n"
    parsed = parse_csv(raw, NOW)
    assert list(parsed.rows.columns) == [
        "row",
        "customer_id",
        "source_name",
        "event_timestamp",
        "event_id",
    ]
    assert parsed.rows["event_id"].iloc[0] == "e1"


def test_suggest_mapping_normalises():
    got = suggest_mapping(["Session Start", "login", "report-created"])
    assert got == {
        "Session Start": "session_start",
        "login": None,
        "report-created": "report_created",
    }
    assert normalise("  Feature Used-X ") == "feature_used_x"


def test_first_week_share():
    ts = pd.to_datetime(
        ["2026-01-01", "2026-01-03", "2026-01-07", "2026-01-20", "2026-01-30"], utc=True
    )
    rows = pd.DataFrame({"customer_id": ["a", "b", "c", "c", "d"], "event_timestamp": ts})
    # a, b, c start within 7 days of 2026-01-01; d does not (c's later event is irrelevant)
    assert first_week_share(rows) == 0.75
    assert first_week_share(rows.iloc[0:0]) == 0.0


def test_no_file_value_in_any_message(caplog):
    caplog.set_level(logging.DEBUG)
    s = "SECRET-123"
    bad = [
        f"{s},,{OK_TS}",
        f",{s},{OK_TS}",
        f"u1,{s},{s}",
        f"u1,{s},1999-01-01",
        f"{s * 20},login,{OK_TS}",
    ]
    parsed = parse_csv(csv(*bad), NOW)
    assert len(parsed.skipped) == 5
    assert s not in repr(parsed.skipped)
    errors = [
        rejected(csv(f"{s},{s}") + f"{s},a,b,c,d,e\n".encode()),  # ragged rows
        rejected(f"{s},x\n1,2\n".encode()),  # missing columns
        rejected(f"{s},".encode() + b"\xff\xfe\n"),  # not utf-8
        rejected(csv(*[f"{s}{i},{s},2026-01-05" for i in range(MAX_CUSTOMERS + 1)])),
    ]
    for err in errors:
        assert s not in err.message
        assert s not in str(err)
    assert s not in caplog.text
    assert all(s not in r.getMessage() for r in caplog.records)


def test_row_with_one_extra_field_is_rejected_not_shifted():
    err = rejected(HEAD.encode() + f"SECRET-123,u1,login,{OK_TS}\n".encode())
    assert err.code == "missing_columns"
    assert "SECRET-123" not in err.message


def test_duplicate_required_header_is_rejected():
    err = rejected(f"customer_id, Customer_ID,event_name,event_timestamp\nu,v,x,{OK_TS}\n".encode())
    assert err.code == "missing_columns"
    assert err.status == 422


def test_exact_duplicate_header_is_rejected():
    err = rejected(
        b"customer_id,customer_id,event_name,event_timestamp\nu,v,login,2026-01-01T00:00:00Z\n"
    )
    assert err.code == "missing_columns"
    assert err.message == "A column name appears more than once."


NUL = chr(0)


def test_nul_in_any_used_field_skips_the_row_without_echo(caplog):
    caplog.set_level(logging.DEBUG)
    parsed = parse_csv(
        csv(
            f"u{NUL}1,login,{OK_TS}",
            f"u2,log{NUL}in,{OK_TS}",
            f"u3,login,2026-01-05{NUL}",
            "u4,login," + OK_TS,
        ),
        NOW,
    )
    assert [c for _, c in parsed.skipped if c == "invalid_character"]
    assert list(parsed.rows["customer_id"]) == ["u4"]
    assert all(NUL not in str(v) for v in parsed.rows.to_numpy().ravel())
    assert NUL not in caplog.text
