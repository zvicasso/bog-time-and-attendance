# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Turn positioned text lines into cardholder blocks and session records.

Report layout (one block per cardholder, may span pages):

    Cardholder Name: Zindam, Cynthia
    Staff No: 2218          (the report's Personal Data Field; label varies)
    Card Number(s): 4075077760, 4604837773
    Entry Clock Name | First Entry Date/Time | Exit Clock Name | Last Exit Date/Time | Time Worked
    PDM-UG-SP.GT.T5-   20/10/2026 7:54:36 am  PDM-UG-SP.GT.T3-  20/10/2026 12:01:11   4:06:35
    RIN                                       ROUT              pm
    Total Working Time (Excluding Insufficient Data) : 14:25:59

Values wrap within their column, so every word is assigned to a column by its
x position (column edges are measured from the header row on each page).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from .models import CardholderBlock, Issue, Line, ParseResult, ReportMeta, SessionRecord

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
DT_RE = re.compile(
    r"(?P<d>\d{1,2}/\d{1,2}/\d{4})\s+(?P<t>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ap>[AaPp][Mm])?"
)
DUR_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})$")
ID_LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 ./#()'-]{0,40}?):")
FOOTER_RE = re.compile(r"^Generated\b.*\bPage\s+(\d+)\s+of\s+(\d+)\s*$")
LONG_DT_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*[AaPp][Mm])")

PREAMBLE_PREFIXES = (
    "Report Type:", "Operator:", "Site Name:", "Report Resolution:", "Cardholders:",
    "Personal Data Field:", "Report sorted on:", "Clock Configuration:", "Time Clocks:",
    "Report Start Date/Time:", "Report End Date/Time:", "Grace Time:", "Assume exit within:",
)
# Lines that may repeat at the top of any page
PAGE_HEADER_PREFIXES = ("Report Type:", "Operator:", "Site Name:")

DEFAULT_EDGES = (175.0, 280.0, 385.0, 478.0)
COLS = ("entry_clock", "entry_dt", "exit_clock", "exit_dt", "worked")


def parse_duration(text: str) -> timedelta | None:
    m = DUR_RE.match(text.strip())
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    return timedelta(hours=h, minutes=mi, seconds=s)


def format_duration(td: timedelta | None) -> str:
    if td is None:
        return ""
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def parse_datetime(text: str, date_order: str = "DMY") -> datetime | None:
    m = DT_RE.search(text)
    if not m:
        return None
    d_parts = [int(x) for x in m.group("d").split("/")]
    if date_order == "MDY":
        month, day, year = d_parts
    else:
        day, month, year = d_parts
    t_parts = [int(x) for x in m.group("t").split(":")]
    h, mi = t_parts[0], t_parts[1]
    s = t_parts[2] if len(t_parts) > 2 else 0
    ap = (m.group("ap") or "").lower()
    if ap:
        if not 1 <= h <= 12:
            return None
        if ap == "pm" and h != 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
    try:
        return datetime(year, month, day, h, mi, s)
    except ValueError:
        return None


def join_wrapped(parts: list[str]) -> str:
    """Join wrapped fragments: 'PDM-UG-SP.GT.U5-' + 'RIN' -> 'PDM-UG-SP.GT.U5-RIN'."""
    out = ""
    for p in parts:
        if not out:
            out = p
        elif out.endswith("-") and not out.endswith(" -"):
            out += p
        else:
            out += " " + p
    return out


def _parse_long_dt(text: str) -> datetime | None:
    m = LONG_DT_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(re.sub(r"\s+", " ", m.group(1)).upper(), "%d %B %Y %I:%M:%S %p")
    except ValueError:
        return None


class _Row:
    def __init__(self, page: int):
        self.page = page
        self.cols: dict[str, list[str]] = {c: [] for c in COLS}
        self.raw: list[str] = []

    def text(self, col: str) -> str:
        return join_wrapped(self.cols[col])


class ReportParser:
    def __init__(self, date_order: str = "DMY"):
        self.date_order = date_order
        self.meta = ReportMeta()
        self.blocks: list[CardholderBlock] = []
        self.issues: list[Issue] = []
        self._block: CardholderBlock | None = None
        self._row: _Row | None = None
        self._edges = DEFAULT_EDGES
        self._edges_page = 0
        self._in_table = False
        self._in_preamble = True
        self._last_label: str | None = None
        self._pages_seen: set[int] = set()

    # ------------------------------------------------------------------ public
    def feed(self, lines: Iterable[Line]) -> ParseResult:
        for line in lines:
            self._pages_seen.add(line.page)
            self._handle(line)
        self._close_block(final=True)
        self.meta.page_count = max(self._pages_seen) if self._pages_seen else 0
        if self.meta.declared_page_count and self.meta.declared_page_count != self.meta.page_count:
            self.issues.append(Issue("WARNING", "Page count",
                f"Footer says {self.meta.declared_page_count} pages but {self.meta.page_count} were read."))
        if not self.blocks:
            self.issues.append(Issue("ERROR", "Format",
                "No 'Cardholder Name:' sections were found. This does not look like a "
                "Time and Attendance Summary Report."))
        return ParseResult(self.meta, self.blocks, self.issues)

    # ----------------------------------------------------------------- helpers
    def _issue(self, sev, cat, msg, line: Line | None = None, raw=""):
        self.issues.append(Issue(sev, cat, msg,
                                 page=line.page if line else None,
                                 block_id=self._block.block_id if self._block else None,
                                 raw_text=raw or (line.text if line else "")))

    def _value_after_label(self, line: Line, label: str) -> str:
        text = line.text
        return text[len(label):].strip() if text.startswith(label) else text

    def _set_edges(self, line: Line):
        ws = line.words
        try:
            texts = [w.text for w in ws]
            i_first = texts.index("First")
            i_exit = texts.index("Exit", i_first)
            i_last = texts.index("Last", i_exit)
            dts = [w for w in ws if w.text == "Date/Time"]
            self._edges = (
                ws[i_first].x0 - 3,
                ws[i_exit].x0 - 3,
                ws[i_last].x0 - 3,
                dts[-1].x1 + 8,
            )
            self._edges_page = line.page
        except (ValueError, IndexError):
            if self._edges_page == 0:
                self._issue("WARNING", "Layout",
                            "Could not measure column positions from header; using defaults.", line)

    def _split_cols(self, line: Line) -> dict[str, list[str]]:
        e1, e2, e3, e4 = self._edges
        out: dict[str, list[str]] = {c: [] for c in COLS}
        for w in line.words:
            x = w.x0
            col = ("entry_clock" if x < e1 else "entry_dt" if x < e2 else
                   "exit_clock" if x < e3 else "exit_dt" if x < e4 else "worked")
            out[col].append(w.text)
        return out

    # -------------------------------------------------------------- main logic
    def _handle(self, line: Line):
        text = line.text.strip()
        if not text:
            return
        m = FOOTER_RE.match(text)
        if m:
            self.meta.declared_page_count = int(m.group(2))
            if not self.meta.generated:
                self.meta.generated = text.split(" Page ")[0].replace("Generated", "").strip()
            return
        if text.startswith("End of Time and Attendance"):
            self._close_block()
            return
        if text.startswith(PAGE_HEADER_PREFIXES) and not self._in_preamble:
            return  # repeated page header
        if self._in_preamble and not text.startswith("Cardholder Name:"):
            self._preamble(text)
            return

        if text.startswith("Cardholder Name:"):
            self._in_preamble = False
            self._close_block()
            self._block = CardholderBlock(block_id=len(self.blocks) + 1, page=line.page,
                                          cardholder_name=self._value_after_label(line, "Cardholder Name:"))
            self.blocks.append(self._block)
            self._in_table = False
            self._last_label = "name"
            return
        if self._block is None:
            self._issue("WARNING", "Unassigned text", "Text outside any cardholder section.", line)
            return
        m = ID_LABEL_RE.match(text)
        if m and self._last_label == "name" and not text.startswith("Card Number"):
            # The report's "Personal Data Field" (e.g. 'Staff No:' or 'Staff Card No:')
            label = m.group(1).strip()
            if not self.meta.personal_field:
                self.meta.personal_field = label
            self._block.staff_no = text[m.end():].strip()
            self._last_label = "staff"
            return
        if text.startswith("Card Number(s):"):
            self._block.card_numbers = self._value_after_label(line, "Card Number(s):")
            self._last_label = "cards"
            return
        if text.startswith("Entry Clock Name"):
            self._set_edges(line)
            self._flush_row()
            self._in_table = True
            self._last_label = None
            return
        if text == "Worked":
            return
        if text.startswith("Total Working Time"):
            self._flush_row()
            raw = text.split(":", 1)[1].strip() if ":" in text else ""
            self._block.total_working_raw = raw
            self._block.total_working = parse_duration(raw)
            self._block.closed = True
            self._in_table = False
            return
        if not self._in_table:
            # A wrapped label value (e.g. long card number list or name)
            if self._last_label and line.x0 > 150:
                if self._last_label == "name":
                    self._block.cardholder_name += " " + text
                elif self._last_label == "cards":
                    self._block.card_numbers += " " + text
                elif self._last_label == "staff":
                    self._block.staff_no += " " + text
                return
            self._issue("WARNING", "Unrecognised line",
                        "Unexpected text in cardholder header area (kept for review).", line)
            return
        self._data_line(line)

    def _preamble(self, text: str):
        if text.startswith("Report Type:"):
            self.meta.report_type = text.split(":", 1)[1].strip()
        elif text.startswith("Site Name:"):
            self.meta.site_name = text.split(":", 1)[1].strip()
        elif text.startswith("Operator:"):
            self.meta.operator = text.split(":", 1)[1].strip()
        elif text.startswith("Report Start Date/Time:"):
            self.meta.start = _parse_long_dt(text)
        elif text.startswith("Report End Date/Time:"):
            self.meta.end = _parse_long_dt(text)
        elif text.startswith("Personal Data Field:"):
            self.meta.personal_field = text.split(":", 1)[1].strip()

    def _data_line(self, line: Line):
        cols = self._split_cols(line)
        has_date = any(DATE_RE.match(t) for t in cols["entry_dt"] + cols["exit_dt"])
        row = self._row
        new_row = False
        if has_date or row is None:
            new_row = True
        elif cols["worked"] and row.cols["worked"]:
            new_row = True  # e.g. a standalone 'Insuff. D.' row after a complete row
        elif cols["exit_clock"] and cols["exit_clock"][0] == "Report" and row.cols["exit_clock"]:
            new_row = True
        if new_row:
            only_wrap = not has_date and all(
                t.lower() in ("am", "pm", "rin", "rout") for c in COLS for t in cols[c])
            if row is None and only_wrap:
                self._issue("WARNING", "Orphan fragment",
                            "Wrapped text found without a preceding data row.", line)
            self._flush_row()
            self._row = row = _Row(line.page)
        for c in COLS:
            row.cols[c].extend(cols[c])
        row.raw.append(line.text)

    def _flush_row(self):
        row, self._row = self._row, None
        if row is None or self._block is None:
            return
        b = self._block
        rec = SessionRecord(
            record_id=f"B{b.block_id:05d}-R{len(b.sessions) + 1:02d}",
            block_id=b.block_id, page=row.page,
            cardholder_name=b.cardholder_name, staff_no=b.staff_no,
            card_numbers=b.card_numbers, raw_text=" / ".join(row.raw),
        )
        rec.entry_clock = row.text("entry_clock")
        entry_txt = " ".join(row.cols["entry_dt"])
        exit_clock = row.text("exit_clock")
        exit_txt = " ".join(row.cols["exit_dt"])
        worked = " ".join(row.cols["worked"])

        if entry_txt:
            rec.entry_dt = parse_datetime(entry_txt, self.date_order)
            if rec.entry_dt is None:
                rec.notes.append(f"Unreadable entry time '{entry_txt}'")
        if exit_clock.startswith("Report End"):
            rec.exit_is_report_end = True
            rec.missing_exit_label = "still on site at report end ('Report End Date/Time')"
            rec.exit_clock = ""
            rec.notes.append("No exit before report end")
        else:
            rec.exit_clock = exit_clock
        if exit_txt:
            rec.exit_dt = parse_datetime(exit_txt, self.date_order)
            if rec.exit_dt is None:
                rec.notes.append(f"Unreadable exit time '{exit_txt}'")
        rec.time_worked_raw = worked
        if worked.startswith("Insuff"):
            rec.insufficient_data = True
            rec.notes.append("Insufficient data")
        elif worked:
            rec.time_worked = parse_duration(worked)
            if rec.time_worked is None:
                rec.notes.append(f"Unreadable time worked '{worked}'")
        if rec.entry_clock and not entry_txt:
            rec.notes.append("Entry clock without entry time")
        if exit_clock and not exit_txt:
            rec.notes.append("Exit clock without exit time")
        if rec.entry_dt and rec.exit_dt and rec.exit_dt < rec.entry_dt:
            rec.notes.append("Exit earlier than entry")

        bad = [n for n in rec.notes if n.startswith(("Unreadable", "Entry clock without", "Exit clock without"))]
        for n in bad:
            self.issues.append(Issue("ERROR", "Unparsed value", n, page=row.page,
                                     block_id=b.block_id, raw_text=rec.raw_text))
        b.sessions.append(rec)

    def _close_block(self, final: bool = False):
        self._flush_row()
        b = self._block
        if b is None:
            return
        if not b.closed:
            self.issues.append(Issue("WARNING", "Incomplete section",
                "Cardholder section ended without a 'Total Working Time' line.",
                page=b.page, block_id=b.block_id, raw_text=b.cardholder_name))
        elif b.total_working is not None:
            parsed = sum((s.time_worked for s in b.sessions
                          if s.time_worked is not None and not s.insufficient_data), timedelta())
            if abs((parsed - b.total_working).total_seconds()) > 1:
                self.issues.append(Issue("WARNING", "Total mismatch",
                    f"Sum of rows ({format_duration(parsed)}) differs from report total "
                    f"({b.total_working_raw}). Check this section manually.",
                    page=b.page, block_id=b.block_id, raw_text=b.cardholder_name))
        self._block = None
        self._in_table = False


def parse_lines(lines: Iterable[Line], date_order: str = "DMY") -> ParseResult:
    return ReportParser(date_order).feed(lines)
