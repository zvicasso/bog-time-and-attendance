# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Read a simple Time & Attendance export in Excel (.xlsx) or CSV form.

Expected layout (one row per person per day), column names matched flexibly:

    Staff No | Cardholder Name | Department | Entry Door | Entry Date/Time |
    Exit Door | Exit Date/Time | Exception | Time on Site

`Exception = X_24` (no exit within 24 hours, exit time shown as the next
midnight) is treated like "Report End Date/Time" in the PDF: not a real exit.

The rows are converted into the same cardholder sections / session records the
PDF parser produces, so every downstream rule is identical for both sources.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .filtering import normalise_name, normalise_staff_no
from .models import CardholderBlock, Issue, ParseResult, ReportMeta, SessionRecord
from .parser import parse_datetime, parse_duration

COLUMN_ALIASES = {
    "staff_no": ("staff no", "staff number", "staff id", "employee id", "employee no", "personnel no",
                 "staff card no", "id number"),
    "name": ("cardholder name", "employee name", "full name", "name"),
    "department": ("department", "dept", "division", "unit"),
    "entry_door": ("entry door", "entry clock name", "entry clock", "entry reader", "in door"),
    "entry_dt": ("entry date/time", "first entry date/time", "first entry", "entry time", "time in", "in time"),
    "exit_door": ("exit door", "exit clock name", "exit clock", "exit reader", "out door"),
    "exit_dt": ("exit date/time", "last exit date/time", "last exit", "exit time", "time out", "out time"),
    "exception": ("exception", "exceptions", "status", "remark"),
    "worked": ("time on site", "time worked", "hours worked", "duration"),
    "cards": ("card number(s)", "card number", "card no", "card numbers"),
}
REQUIRED = ("name", "entry_dt")
NO_EXIT_CODES = {"X_24": "X_24 - no exit within 24 hours"}


class ExcelSourceError(Exception):
    """Raised with a message that is safe to show to the user."""


def _map_columns(columns) -> dict[str, str]:
    low = {str(c).strip().lower(): c for c in columns}
    found: dict[str, str] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in low and low[a] not in found.values():
                found[key] = low[a]
                break
    return found


def _to_datetime(v, date_order: str) -> datetime | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, time())
    text = str(v).strip()
    dt = parse_datetime(text, date_order)
    if dt:
        return dt
    try:  # ISO, e.g. '2026-10-20 07:31:02'
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_duration(v) -> tuple[timedelta | None, str]:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None, ""
    if isinstance(v, timedelta):
        return v, str(v)
    if isinstance(v, time):
        return timedelta(hours=v.hour, minutes=v.minute, seconds=v.second), v.strftime("%H:%M:%S")
    text = str(v).strip()
    return parse_duration(text), text


def _hms(td: timedelta) -> str:
    t = int(td.total_seconds())
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{t // 3600}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def _read(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding_errors="replace")
        sheets = pd.read_excel(path, sheet_name=None, dtype=object, engine="openpyxl")
    except Exception as exc:
        raise ExcelSourceError(f"The spreadsheet could not be read ({type(exc).__name__}).") from exc
    # Use every sheet that has the expected header (exports sometimes split into 'Page 1', 'Page 2', ...)
    frames = []
    for name, df in sheets.items():
        if all(k in _map_columns(df.columns) for k in REQUIRED):
            df = df.copy()
            df["__sheet__"] = name
            frames.append(df)
    if not frames:
        raise ExcelSourceError(
            "No sheet with the expected columns was found. The spreadsheet needs at least "
            "'Cardholder Name' and 'Entry Date/Time' columns (plus ideally 'Staff No', 'Department', "
            "'Exit Date/Time', 'Exception' and 'Time on Site').")
    return pd.concat(frames, ignore_index=True)


def parse_spreadsheet(path: Path | str, date_order: str = "DMY") -> ParseResult:
    path = Path(path)
    df = _read(path)
    cols = _map_columns(df.columns)
    missing = [k for k in REQUIRED if k not in cols]
    if missing:
        raise ExcelSourceError("The spreadsheet is missing the column(s): " + ", ".join(missing))

    meta = ReportMeta(report_type="Time & Attendance export", personal_field="Staff No",
                      source_format="CSV" if path.suffix.lower() == ".csv" else "Excel")
    issues: list[Issue] = []
    blocks: "OrderedDict[str, CardholderBlock]" = OrderedDict()

    def cell(row, key):
        c = cols.get(key)
        if c is None:
            return ""
        v = row[c]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return v

    multi_sheet = df["__sheet__"].nunique() > 1 if "__sheet__" in df else False

    # Integrity check 1: in system exports every time cell has the same type (usually text).
    # A lone typed date/time cell among text cells suggests the value was edited by hand.
    def majority_is_text(key):
        c = cols.get(key)
        if c is None:
            return None
        vals = [v for v in df[c] if not (v is None or (isinstance(v, float) and pd.isna(v)) or v == "")]
        if not vals:
            return None
        n_text = sum(isinstance(v, str) for v in vals)
        return n_text / len(vals) >= 0.8
    text_major = {k: majority_is_text(k) for k in ("entry_dt", "exit_dt")}
    for i, row in df.iterrows():
        excel_row = int(i) + 2
        name = str(cell(row, "name")).strip()
        staff = str(cell(row, "staff_no")).strip()
        if staff.endswith(".0") and staff[:-2].isdigit():
            staff = staff[:-2]
        if not name and not staff:
            continue
        key = f"{normalise_name(name)}|{normalise_staff_no(staff)}"
        b = blocks.get(key)
        if b is None:
            b = CardholderBlock(block_id=len(blocks) + 1, page=excel_row, cardholder_name=name,
                                staff_no=staff, card_numbers=str(cell(row, "cards")).strip(), closed=True)
            b.department = str(cell(row, "department")).strip()
            blocks[key] = b
        ref = f"{row['__sheet__']}!" if multi_sheet else ""
        raw = " | ".join(str(row[c]) for c in cols.values() if str(row[c]) not in ("", "nan", "NaT"))
        rec = SessionRecord(record_id=f"R{excel_row:05d}", block_id=b.block_id, page=excel_row,
                            cardholder_name=name, staff_no=staff, card_numbers=b.card_numbers,
                            raw_text=f"{ref}row {excel_row}: {raw}")
        rec.entry_clock = str(cell(row, "entry_door")).strip()
        rec.exit_clock = str(cell(row, "exit_door")).strip()
        entry_raw, exit_raw = cell(row, "entry_dt"), cell(row, "exit_dt")
        rec.entry_dt = _to_datetime(entry_raw, date_order)
        rec.exit_dt = _to_datetime(exit_raw, date_order)
        if entry_raw != "" and rec.entry_dt is None:
            rec.notes.append(f"Unreadable entry time '{entry_raw}'")
        if exit_raw != "" and rec.exit_dt is None:
            rec.notes.append(f"Unreadable exit time '{exit_raw}'")
        code = str(cell(row, "exception")).strip()
        rec.time_worked, rec.time_worked_raw = _to_duration(cell(row, "worked"))
        if code:
            rec.notes.append(f"Exception code {NO_EXIT_CODES.get(code.upper(), code)}")
        if code.upper() in NO_EXIT_CODES or (rec.exit_dt is not None and not rec.exit_clock and code):
            rec.exit_is_report_end = True     # placeholder exit, not a real badge event
            rec.missing_exit_label = NO_EXIT_CODES.get(code.upper(), f"exception {code}")
        elif rec.exit_dt is None and rec.entry_dt is not None:
            rec.missing_exit_label = "no exit time in export"
        if rec.entry_dt and rec.exit_dt and rec.exit_dt < rec.entry_dt:
            rec.notes.append("Exit earlier than entry")
        for key, label, raw_v in (("entry_dt", "Entry", entry_raw), ("exit_dt", "Exit", exit_raw)):
            if text_major.get(key) and raw_v != "" and not isinstance(raw_v, str):
                rec.integrity_notes.append(f"{label} time cell is a typed date/time while the rest of the "
                                           "export is text - possibly edited by hand")
        # Integrity check 2: 'Time on Site' must equal exit - entry
        if rec.time_worked is not None and rec.entry_dt and rec.exit_dt and not rec.exit_is_report_end:
            diff = (rec.exit_dt - rec.entry_dt) - rec.time_worked
            if abs(diff.total_seconds()) > 60:
                rec.integrity_notes.append(
                    f"Time on Site {rec.time_worked_raw} does not match exit - entry "
                    f"({_hms(rec.exit_dt - rec.entry_dt)}) - times may have been altered")
        rec.notes.extend(rec.integrity_notes)
        for n in rec.notes:
            if n.startswith("Unreadable"):
                issues.append(Issue("ERROR", "Unparsed value", n, page=excel_row, block_id=b.block_id,
                                    raw_text=rec.raw_text))
        b.sessions.append(rec)

    if not blocks:
        issues.append(Issue("ERROR", "Format", "The spreadsheet contains no attendance rows."))
    entries = [s.entry_dt for b in blocks.values() for s in b.sessions if s.entry_dt]
    if entries:
        meta.start = datetime.combine(min(entries).date(), time())
        meta.end = datetime.combine(max(entries).date(), time(23, 59, 59))
    meta.page_count = 0
    if "department" not in cols:
        issues.append(Issue("INFO", "Columns", "No Department column found in the spreadsheet."))
    if "exit_dt" not in cols:
        issues.append(Issue("WARNING", "Columns", "No exit time column found - early departures cannot be judged."))
    meta.extra_rows = len(df)
    flagged = sum(1 for b in blocks.values() for s_ in b.sessions if s_.integrity_notes)
    if flagged:
        issues.append(Issue("WARNING", "Data integrity",
            f"{flagged} row(s) show signs of manual editing (typed date cells or Time on Site not matching "
            "entry/exit). They are listed under Attendance Exceptions as 'Data Integrity'. Verify them "
            "against the access-control system."))
    return ParseResult(meta, list(blocks.values()), issues)


def is_spreadsheet(path: Path | str) -> bool:
    return Path(path).suffix.lower() in (".xlsx", ".xlsm", ".csv")
