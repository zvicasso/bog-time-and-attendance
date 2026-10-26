# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Parse a *Cardholder Summary Report* PDF into roster entries.

Layout (one cardholder per row, values wrap inside their column):

    First Name | Last Name | Access Group          | Staff No | Department
    Aaron      | Agyare    | Suprema Access Group  | 6798     | Other Financial Institutions Supervision
                           | GEN-1                 |          |
                           | UB-2F: OFISD / ...    |          |

A row starts on a line with text in a name column. Long names wrap onto the
next line; that is detected by measuring whether the fragment would have fitted
on the first line of the column (word positions are known).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import Line, Word
from .pdf_extract import extract_lines
from .parser import join_wrapped

SKIP_PREFIXES = ("Generated ", "Report Type:", "Operator:", "Site Name:", "Operator's Comment",
                 "End of Cardholder")
COLS = ("first", "last", "access", "staff", "dept")
DEFAULT_EDGES = (162.0, 255.0, 349.0, 442.0)  # right edge of first/last/access/staff columns
WRAP_MARGIN = 9.0  # text wraps this many points before the next column starts


@dataclass
class CardholderRecord:
    first_name: str
    last_name: str
    staff_no: str
    department: str
    access_groups: str
    page: int

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)


@dataclass
class CardholderReport:
    site_name: str = ""
    records: list[CardholderRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _Rec:
    def __init__(self, page: int):
        self.page = page
        self.cols: dict[str, list[Word]] = {c: [] for c in COLS}
        self.first_line: dict[str, list[Word]] = {}
        self.lines = 0
        self.name_only_lines = 0

    def text(self, col: str) -> str:
        return join_wrapped([w.text for w in self.cols[col]])


def _approx_width(w: Word) -> float:
    return max(w.x1 - w.x0, 1.0)


def is_cardholder_report(source) -> bool:
    for i, ln in enumerate(extract_lines(source, max_pages=1)):
        if ln.text.startswith("Report Type:"):
            return "Cardholder" in ln.text
        if i > 10:
            break
    return False


def parse_cardholder_report(source: Path | str | bytes) -> CardholderReport:
    rep = CardholderReport()
    edges = DEFAULT_EDGES
    started = False
    cur: _Rec | None = None
    recs: list[_Rec] = []

    def split(line: Line) -> dict[str, list[Word]]:
        out: dict[str, list[Word]] = {c: [] for c in COLS}
        for w in line.words:
            x = w.x0
            c = ("first" if x < edges[0] else "last" if x < edges[1] else
                 "access" if x < edges[2] else "staff" if x < edges[3] else "dept")
            out[c].append(w)
        return out

    def is_name_wrap(cols) -> bool:
        if cur is None or cur.lines != cur.name_only_lines + 1 or cols["staff"]:
            return False
        if cols["access"] and cols["access"][0].text == "Suprema":
            return False  # access group text starting afresh -> a new cardholder row
        for i, c in enumerate(("first", "last")):
            if not cols[c]:
                continue
            prev = cur.first_line.get(c) or []
            if not prev:
                return False  # the word would have fitted on the first line
            if prev[-1].x1 + 3 + _approx_width(cols[c][0]) <= edges[i] - WRAP_MARGIN:
                return False  # it would have fitted -> this is a new cardholder
        return True

    for line in extract_lines(source):
        t = line.text.strip()
        if t.startswith("Site Name:") and not rep.site_name:
            rep.site_name = t.split(":", 1)[1].strip()
        if not t or t.startswith(SKIP_PREFIXES):
            continue
        if not started and t.startswith("First Name") and "Staff" in t:
            ws = {w.text: w.x0 for w in line.words}
            try:
                edges = (ws["Last"] - 3, ws["Access"] - 3, ws["Staff"] - 3, ws["Department"] - 3)
            except KeyError:
                rep.warnings.append("Roster column header not recognised; default column positions used.")
            started = True
            continue
        if not started:
            continue
        cols = split(line)
        has_name = bool(cols["first"] or cols["last"])
        if has_name and not is_name_wrap(cols):
            cur = _Rec(line.page)
            cur.first_line = {c: list(v) for c, v in cols.items()}
            recs.append(cur)
        elif cur is None:
            rep.warnings.append(f"Page {line.page}: text before the first cardholder ignored.")
            continue
        elif has_name:
            cur.name_only_lines += 1
        for c in COLS:
            cur.cols[c].extend(cols[c])
        cur.lines += 1

    if not started:
        raise ValueError("This PDF is not a Cardholder Summary Report (no 'First Name ... Staff No' header).")
    for r in recs:
        rep.records.append(CardholderRecord(
            first_name=r.text("first"), last_name=r.text("last"),
            staff_no=" ".join(w.text for w in r.cols["staff"]),
            department=" ".join(w.text for w in r.cols["dept"]),
            access_groups=" ".join(w.text for w in r.cols["access"]), page=r.page))
    return rep
