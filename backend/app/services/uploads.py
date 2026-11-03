"""Upload limits, the CSV parser and the bounded multipart reader.

Privacy rule for this module: no message, exception text or log line ever contains a value from
the uploaded file. Problems are reported as codes and 1-based data row numbers only.
"""

import csv
import hashlib
import io
import json
import logging
import re
import warnings
from dataclasses import dataclass, field

import pandas as pd
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app.db.models import Dataset
from app.schemas.events import MAX_CLOCK_SKEW, MIN_EVENT_TIME
from app.services.metrics import EVENT_NAMES, FUNNEL_STEPS, QUALIFYING_EVENTS
from app.services.upload_scoring import SCOREABLE

logger = logging.getLogger("churnscope.uploads")

MAX_REQUEST_BYTES = 5_767_168  # 5.5 MiB, whole multipart body
MAX_FILE_BYTES = 5_242_880  # 5 MiB, the file part
MAX_ROWS = 50_000
MAX_CUSTOMERS = 10_000
MAX_EVENT_NAMES = 50
MAX_VALUE_CHARS = 100
MAX_INVALID_SHARE = 0.05
MAX_REASONS = 20
GLOBAL_UPLOADED_EVENTS_CAP = 300_000
CENSOR_WARN_SHARE = 0.25
CENSOR_WINDOW_DAYS = 7
IMPORT_LOCK_KEY = 6_202_611
INSERT_BATCH = 5_000

REQUIRED_COLUMNS = ("customer_id", "event_name", "event_timestamp")
MAX_FORM_FIELDS = 5
MAX_FIELD_BYTES = 8_192  # non-file form fields (mapping JSON, flags)
_CHUNK = 64 * 1024
_TZ_SUFFIX = re.compile(r"[Tt ]\d.*(?:[Zz]|[+-]\d{2}(?::?\d{2})?)$")


class UploadRejected(Exception):
    """The whole upload is refused. `message` is fixed text, never file content."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class ParsedFile:
    rows: pd.DataFrame  # row, customer_id, source_name, event_timestamp (UTC), event_id
    skipped: list[tuple[int, str]]  # (1-based data row, code), all of them
    total_rows: int
    zoneless: bool
    # Trimmed event name of each skipped row, parallel to `skipped`. Held in memory only, so a
    # bad row of an event name mapped to "ignore" can be left out of the 5% rule (spec D8).
    skipped_names: list[str] = field(default_factory=list)


def normalise(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def suggest_mapping(names: list[str]) -> dict[str, str | None]:
    return {n: (normalise(n) if normalise(n) in EVENT_NAMES else None) for n in names}


def _timestamps(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse ISO-8601 to UTC (NaT when unparseable). Also return which values had a zone."""
    has_zone = raw.str.contains(_TZ_SUFFIX)
    parsed = pd.to_datetime(raw, format="ISO8601", errors="coerce", utc=True)
    return parsed, has_zone


def parse_csv(raw: bytes, now: pd.Timestamp) -> ParsedFile:
    if not raw.strip():
        raise UploadRejected("empty_file", "The file is empty.")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRejected("not_utf8", "The file must be UTF-8 text.") from None
    # Checked on the raw header: pandas renames an exact repeat ("a", "a.1") before we see it.
    try:
        header = next(csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))), [])
    except csv.Error:  # its message can quote the header, so none is passed on
        raise UploadRejected(
            "missing_columns", "The file is not a well-formed CSV with a header row."
        ) from None
    names = [h.strip().lower() for h in header]
    if any(names.count(c) > 1 for c in REQUIRED_COLUMNS + ("event_id",)):
        raise UploadRejected("missing_columns", "A column name appears more than once.")
    try:
        with warnings.catch_warnings():
            # A row longer than the header is a ParserWarning with index_col=False; refuse it
            # instead of silently dropping or shifting fields.
            warnings.simplefilter("error", pd.errors.ParserWarning)
            df = pd.read_csv(
                io.BytesIO(raw),
                dtype=str,
                keep_default_na=False,
                encoding="utf-8-sig",
                skip_blank_lines=False,
                index_col=False,
            )
    except pd.errors.EmptyDataError:
        raise UploadRejected("empty_file", "The file is empty.") from None
    except (
        pd.errors.ParserError,
        pd.errors.ParserWarning,
        ValueError,
        OverflowError,
    ):  # pandas messages can quote file content, so none is passed on
        raise UploadRejected(
            "missing_columns", "The file is not a well-formed CSV with a header row."
        ) from None
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise UploadRejected(
            "missing_columns", "Required columns are missing: " + ", ".join(missing) + "."
        )
    total = len(df)
    if total == 0:
        raise UploadRejected("empty_file", "The file has a header but no rows.")
    if total > MAX_ROWS:
        raise UploadRejected("too_many_rows", f"The file has more than {MAX_ROWS} rows.")

    df = df.fillna("")
    cid = df["customer_id"].str.strip()
    name = df["event_name"].str.strip()
    stamp_raw = df["event_timestamp"].str.strip()
    eid = df["event_id"].str.strip() if "event_id" in df.columns else pd.Series("", index=df.index)
    ts, has_zone = _timestamps(stamp_raw)
    has_nul = (
        cid.str.contains("\x00", regex=False)
        | name.str.contains("\x00", regex=False)
        | eid.str.contains("\x00", regex=False)
        | stamp_raw.str.contains("\x00", regex=False)
    )
    too_long = (
        (cid.str.len() > MAX_VALUE_CHARS)
        | (name.str.len() > MAX_VALUE_CHARS)
        | (eid.str.len() > MAX_VALUE_CHARS)
    )
    out_of_range = ts.notna() & ((ts < MIN_EVENT_TIME) | (ts > now + MAX_CLOCK_SKEW))
    # Later entries overwrite earlier ones, so the priority is the reverse of this list.
    code = pd.Series("", index=df.index, dtype=object)
    for mask, reason in (
        (out_of_range, "timestamp_out_of_range"),
        (ts.isna(), "bad_timestamp"),
        (has_nul, "invalid_character"),
        (too_long, "value_too_long"),
        (name == "", "missing_event_name"),
        (cid == "", "missing_customer_id"),
    ):
        code = code.mask(mask, reason)
    bad = code != ""
    skipped = [(int(i) + 1, str(code.iloc[i])) for i in range(total) if bad.iloc[i]]
    skipped_names = [str(n) for n in name[bad]]

    good = ~bad
    rows = pd.DataFrame(
        {
            "row": (df.index[good] + 1).astype(int),
            "customer_id": cid[good].to_numpy(),
            "source_name": name[good].to_numpy(),
            "event_timestamp": ts[good].to_numpy(),
            "event_id": [e or None for e in eid[good]],
        }
    ).reset_index(drop=True)
    rows["event_timestamp"] = pd.to_datetime(rows["event_timestamp"], utc=True)
    rows["event_id"] = rows["event_id"].astype(object)
    if rows["customer_id"].nunique() > MAX_CUSTOMERS:
        raise UploadRejected(
            "too_many_customers", f"The file has more than {MAX_CUSTOMERS} customers."
        )
    if rows["source_name"].nunique() > MAX_EVENT_NAMES:
        raise UploadRejected(
            "too_many_event_names", f"The file has more than {MAX_EVENT_NAMES} event names."
        )
    zoneless = bool((~has_zone[good]).any())
    logger.info("parsed upload: %d rows, %d skipped", total, len(skipped))
    return ParsedFile(
        rows=rows,
        skipped=skipped,
        total_rows=total,
        zoneless=zoneless,
        skipped_names=skipped_names,
    )


def first_week_share(rows: pd.DataFrame) -> float:
    """Share of customers whose first event is within CENSOR_WINDOW_DAYS of the file's start."""
    if rows.empty:
        return 0.0
    first = rows.groupby("customer_id")["event_timestamp"].min()
    cutoff = first.min() + pd.Timedelta(days=CENSOR_WINDOW_DAYS)
    return float((first < cutoff).sum() / len(first))


@dataclass
class Prepared:
    """What an import stores. Customer ids here are the file's (external) ids."""

    events: pd.DataFrame  # customer_id, event_name, event_timestamp, event_id, properties
    customers: pd.DataFrame  # customer_id, created_at (the customer's first stored event)
    mapping: dict  # every event name in the file -> our name, or None for ignored
    signup_rule: str  # "event" or "derived_from_first_event"
    mapped_counts: dict[str, int]  # stored events per our event name, derived signups included
    invalid_rows: int
    ignored_rows: int
    duplicate_rows: int
    derived_signups: int
    skipped: list[tuple[int, str]]  # the invalid rows that count, all of them


def derive_event_id(customer_id: str, event_name: str, ts: pd.Timestamp) -> str:
    """Stable id for a row without one. No occurrence number: identical rows are duplicates."""
    key = f"{customer_id}|{event_name}|{ts.isoformat()}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _full_mapping(mapping: object, present: set[str]) -> dict[str, str | None]:
    """Validate the mapping; a name in the file but absent from the mapping is ignored."""
    if not isinstance(mapping, dict):
        raise UploadRejected("bad_mapping", "The mapping must be an object of event names.")
    for source, target in mapping.items():
        if not isinstance(source, str) or source not in present:
            raise UploadRejected(
                "bad_mapping", "The mapping names an event that is not in the file."
            )
        if target is not None and (not isinstance(target, str) or target not in EVENT_NAMES):
            raise UploadRejected("bad_mapping", "The mapping targets an unknown event name.")
    return {name: mapping.get(name) for name in sorted(present)}


def prepare(
    parsed: ParsedFile,
    mapping: dict[str, str | None],
    derive_signup: bool,
    acknowledged: bool,
) -> Prepared:
    """Apply the mapping, drop duplicates, enforce the 5% rule, derive signups (D6, D6a, D8)."""
    rows = parsed.rows
    full = _full_mapping(mapping, set(rows["source_name"].unique()))
    targets = {t for t in full.values() if t is not None}
    if derive_signup and "signup" in targets:
        raise UploadRejected(
            "derive_not_allowed",
            "Signup can only be derived when no event is mapped to signup.",
        )
    if not targets & set(QUALIFYING_EVENTS):
        raise UploadRejected(
            "no_activity_event",
            "Map at least one event to " + ", ".join(QUALIFYING_EVENTS) + ".",
        )

    target = rows["source_name"].map(full)
    keep = target.notna()
    events = rows.loc[keep, ["customer_id", "event_timestamp", "event_id"]].copy()
    events["event_name"] = target[keep]
    no_id = events["event_id"].isna()
    events.loc[no_id, "event_id"] = [
        derive_event_id(c, n, t)
        for c, n, t in zip(
            events.loc[no_id, "customer_id"],
            events.loc[no_id, "event_name"],
            events.loc[no_id, "event_timestamp"],
            strict=True,
        )
    ]
    dup = events["event_id"].duplicated(keep="first")
    duplicate_rows = int(dup.sum())
    events = events[~dup]

    # The 5% rule: rows of an ignored event name and duplicate rows are out of both the invalid
    # count and the denominator. A bad row counts as ignored only when its name is one the file
    # shows among its valid rows (so one the user saw and chose to ignore).
    ignored_names = {n for n, t in full.items() if t is None}
    names = parsed.skipped_names
    if len(names) != len(parsed.skipped):
        names = [""] * len(parsed.skipped)
    counted = [s for s, n in zip(parsed.skipped, names, strict=True) if n not in ignored_names]
    ignored_rows = int((~keep).sum()) + len(parsed.skipped) - len(counted)
    denominator = parsed.total_rows - ignored_rows - duplicate_rows
    if denominator > 0 and len(counted) / denominator > MAX_INVALID_SHARE:
        raise UploadRejected(
            "too_many_invalid", f"More than {MAX_INVALID_SHARE:.0%} of the rows are invalid."
        )
    # Same rows as the check step's warning, so the gate matches what the user was shown.
    if derive_signup and not acknowledged and first_week_share(rows) >= CENSOR_WARN_SHARE:
        raise UploadRejected(
            "acknowledgement_required",
            "Confirm that derived signup dates are approximate before importing.",
        )

    events["properties"] = [{} for _ in range(len(events))]
    derived = 0
    if derive_signup:
        first = (
            events.sort_values("event_timestamp", kind="stable")
            .groupby("customer_id", sort=False)
            .head(1)
        )
        signups = pd.DataFrame(
            {
                "customer_id": first["customer_id"].to_numpy(),
                "event_timestamp": first["event_timestamp"].to_numpy(),
                "event_id": [
                    derive_event_id(c, "signup", t)
                    for c, t in zip(first["customer_id"], first["event_timestamp"], strict=True)
                ],
                "event_name": "signup",
                "properties": [{"derived": True} for _ in range(len(first))],
            }
        )
        signups["event_timestamp"] = pd.to_datetime(signups["event_timestamp"], utc=True)
        signups = signups[~signups["event_id"].isin(set(events["event_id"]))]
        derived = len(signups)
        events = pd.concat([events, signups], ignore_index=True)
    events = events[
        ["customer_id", "event_name", "event_timestamp", "event_id", "properties"]
    ].reset_index(drop=True)

    customers = (
        events.groupby("customer_id", sort=False)["event_timestamp"]
        .min()
        .rename("created_at")
        .reset_index()
    )
    if len(customers) > MAX_CUSTOMERS:
        raise UploadRejected(
            "too_many_customers", f"The file has more than {MAX_CUSTOMERS} customers."
        )
    counts = events["event_name"].value_counts()
    return Prepared(
        events=events,
        customers=customers,
        mapping=full,
        signup_rule="derived_from_first_event" if derive_signup else "event",
        mapped_counts={str(k): int(v) for k, v in counts.items()},
        invalid_rows=len(counted),
        ignored_rows=ignored_rows,
        duplicate_rows=duplicate_rows,
        derived_signups=derived,
        skipped=counted,
    )


def capabilities(dataset: Dataset) -> dict:
    """Which pages work for a dataset. The demo has everything. An upload's churn needs a usable
    scoring method (spec 5a) and a signup (mapped or derived)."""
    if dataset.kind == "demo":
        return {
            "overview": True,
            "engagement": True,
            "retention": True,
            "funnel": True,
            "churn": True,
            "funnel_missing": [],
        }
    counts = dataset.mapped_counts or {}

    def has(name: str) -> bool:
        return int(counts.get(name, 0)) > 0

    missing = [step for step in FUNNEL_STEPS if not has(step)]
    signup = has("signup") or dataset.signup_rule == "derived_from_first_event"
    method = (dataset.scoring or {}).get("method")
    return {
        "overview": True,
        "engagement": True,
        "retention": signup,
        "funnel": not missing,
        "churn": signup and method in SCOREABLE,
        "funnel_missing": missing,
    }


def _flag(fields: dict[str, str], name: str) -> bool:
    value = fields.get(name, "false")
    if value not in ("true", "false"):
        raise UploadRejected("bad_form", "Form flags must be true or false.")
    return value == "true"


def import_options(fields: dict[str, str]) -> tuple[dict, bool, bool]:
    """(mapping, derive_signup, acknowledge_approximate_signup) from the import form fields.

    Only the JSON shape is checked here; `prepare` checks the mapping against the file.
    """
    raw = fields.get("mapping")
    if raw is None:
        raise UploadRejected("bad_mapping", "A mapping is required.")
    try:
        mapping = json.loads(raw)
    except (ValueError, RecursionError):  # the decoder's message can quote the field
        raise UploadRejected("bad_mapping", "The mapping must be JSON.") from None
    if not isinstance(mapping, dict):
        raise UploadRejected("bad_mapping", "The mapping must be an object of event names.")
    return mapping, _flag(fields, "derive_signup"), _flag(fields, "acknowledge_approximate_signup")


@dataclass
class UploadForm:
    filename: str | None
    data: bytes
    fields: dict[str, str] = field(default_factory=dict)  # non-file parts, e.g. mapping JSON


def check_content_length(request: Request) -> int:
    """411 when missing or malformed, 413 when over the request limit. Reads no body."""
    try:
        length = int(request.headers["content-length"])
        if length < 0:
            raise ValueError
    except (KeyError, ValueError):
        raise UploadRejected("length_required", "Content-Length required.", 411) from None
    if length > MAX_REQUEST_BYTES:
        raise UploadRejected("file_too_large", "The upload is too large.", 413)
    return length


async def read_form(request: Request) -> UploadForm:
    """Bounded multipart read: Content-Length is checked before the body is touched, the file
    part is read in chunks and stops at MAX_FILE_BYTES + 1. Other parts come back as `fields`."""
    check_content_length(request)
    try:
        form = await request.form(
            max_files=1, max_fields=MAX_FORM_FIELDS, max_part_size=MAX_FIELD_BYTES
        )
    except (
        MultiPartException,
        StarletteHTTPException,
    ):  # parser errors may quote the body; none of it is passed on
        raise UploadRejected("bad_form", "The upload could not be read.", 422) from None
    try:
        upload = form.get("file")
        if upload is None or isinstance(upload, str) or not hasattr(upload, "read"):
            raise UploadRejected("missing_file", "A file part named 'file' is required.")
        chunks: list[bytes] = []
        size = 0
        while chunk := await upload.read(_CHUNK):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise UploadRejected("file_too_large", "The file is too large.", 413)
            chunks.append(chunk)
        fields = {k: v for k, v in form.items() if k != "file" and isinstance(v, str)}
        return UploadForm(filename=upload.filename, data=b"".join(chunks), fields=fields)
    finally:
        await form.close()


async def read_upload(request: Request) -> tuple[str | None, bytes]:
    """Client filename and file bytes. Use `read_form` when the other form fields are needed."""
    form = await read_form(request)
    return form.filename, form.data
