"""Upload limits, the CSV parser and the bounded multipart reader.

Privacy rule for this module: no message, exception text or log line ever contains a value from
the uploaded file. Problems are reported as codes and 1-based data row numbers only.
"""

import io
import logging
import re
import warnings
from dataclasses import dataclass, field

import pandas as pd
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app.schemas.events import MAX_CLOCK_SKEW, MIN_EVENT_TIME
from app.services.metrics import EVENT_NAMES

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
    if any(list(df.columns).count(c) > 1 for c in REQUIRED_COLUMNS + ("event_id",)):
        raise UploadRejected("missing_columns", "A column name appears more than once.")
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
        (too_long, "value_too_long"),
        (name == "", "missing_event_name"),
        (cid == "", "missing_customer_id"),
    ):
        code = code.mask(mask, reason)
    bad = code != ""
    skipped = [(int(i) + 1, str(code.iloc[i])) for i in range(total) if bad.iloc[i]]

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
    return ParsedFile(rows=rows, skipped=skipped, total_rows=total, zoneless=zoneless)


def first_week_share(rows: pd.DataFrame) -> float:
    """Share of customers whose first event is within CENSOR_WINDOW_DAYS of the file's start."""
    if rows.empty:
        return 0.0
    first = rows.groupby("customer_id")["event_timestamp"].min()
    cutoff = first.min() + pd.Timedelta(days=CENSOR_WINDOW_DAYS)
    return float((first < cutoff).sum() / len(first))


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
