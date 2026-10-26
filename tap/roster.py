# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Optional employee roster for confirmed-absence identification.

Accepted sources:
* Cardholder Summary Report PDF exported from the access-control system
  (First Name / Last Name / Access Group / Staff No / Department)
* Excel (.xlsx) or CSV with a staff-number and/or name column
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .filtering import match_exclusion, normalise_name, normalise_staff_no
from .models import Employee

STAFF_COLS = ("staff card no", "staff card number", "staff no", "staff number", "staff id",
              "employee id", "employee no", "employee number", "emp no", "personnel no",
              "staff card", "id number")
NAME_COLS = ("cardholder name", "employee name", "full name", "staff name", "name")
FIRST_COLS = ("first name", "firstname", "given name", "forename")
LAST_COLS = ("last name", "lastname", "surname", "family name")
DEPT_COLS = ("department", "dept", "division", "unit", "directorate")


class RosterError(Exception):
    pass


@dataclass
class RosterEntry:
    row: int                 # spreadsheet row, or PDF page for a cardholder report
    name: str
    staff_no: str
    department: str = ""
    matched_keys: list[str] = field(default_factory=list)
    excluded: bool = False
    exclusion_reason: str = ""
    match_method: str = ""


@dataclass
class Roster:
    entries: list[RosterEntry]
    columns_used: dict[str, str]
    source_type: str = "spreadsheet"   # "spreadsheet" | "cardholder report"
    warnings: list[str] = field(default_factory=list)

    def __len__(self):
        return len(self.entries)

    @property
    def active(self) -> list[RosterEntry]:
        return [e for e in self.entries if not e.excluded]

    def ref(self, e: RosterEntry) -> str:
        return f"Roster page {e.row}" if self.source_type == "cardholder report" else f"Roster row {e.row}"


def _find(cols: dict[str, str], candidates) -> str | None:
    for c in candidates:
        if c in cols:
            return cols[c]
    for c in candidates:  # contains-match as a second pass
        for low, orig in cols.items():
            if c in low:
                return orig
    return None


def _load_pdf(path: Path) -> Roster:
    from .cardholder_report import is_cardholder_report, parse_cardholder_report
    from .pdf_extract import PdfExtractionError

    try:
        if not is_cardholder_report(path):
            raise RosterError("This roster PDF is not a Cardholder Summary Report. Use the access-control "
                              "system's Cardholder Summary Report, or an Excel/CSV roster.")
        rep = parse_cardholder_report(path)
    except PdfExtractionError as exc:
        raise RosterError(f"Roster PDF: {exc}") from exc
    except ValueError as exc:
        raise RosterError(str(exc)) from exc
    entries = [RosterEntry(row=r.page, name=r.full_name, staff_no=r.staff_no, department=r.department)
               for r in rep.records if r.full_name or r.staff_no]
    if not entries:
        raise RosterError("No cardholders were found in the roster PDF.")
    return Roster(entries, {"staff": "Staff No", "name": "First Name + Last Name", "department": "Department"},
                  source_type="cardholder report", warnings=rep.warnings)


def load_roster(path: Path | str) -> Roster:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return _load_pdf(path)
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding_errors="replace")
        elif path.suffix.lower() in (".xlsx", ".xlsm"):
            df = pd.read_excel(path, dtype=str, keep_default_na=False, engine="openpyxl")
        else:
            raise RosterError("Roster must be a Cardholder Summary Report (.pdf), .xlsx or .csv file.")
    except RosterError:
        raise
    except Exception as exc:
        raise RosterError(f"The roster file could not be read ({type(exc).__name__}).") from exc

    cols = {str(c).strip().lower(): c for c in df.columns}
    staff_c = _find(cols, STAFF_COLS)
    first_c, last_c = _find(cols, FIRST_COLS), _find(cols, LAST_COLS)
    name_c = next((cols[c] for c in NAME_COLS if c in cols), None)
    if name_c is None and not (first_c and last_c):
        rest = {k: v for k, v in cols.items() if v not in (first_c, last_c, staff_c)}
        name_c = _find(rest, NAME_COLS)
    dept_c = _find(cols, DEPT_COLS)
    if not staff_c and not name_c and not (first_c and last_c):
        raise RosterError(
            "The roster needs a 'Staff No' column and/or a 'Name' column "
            f"(found: {', '.join(map(str, df.columns))}).")

    entries = []
    for i, r in df.iterrows():
        if name_c:
            name = str(r[name_c]).strip()
        elif first_c and last_c:
            name = f"{str(r[last_c]).strip()}, {str(r[first_c]).strip()}".strip(", ")
        else:
            name = ""
        staff = str(r[staff_c]).strip() if staff_c else ""
        if not name and not staff:
            continue
        entries.append(RosterEntry(row=int(i) + 2, name=name, staff_no=staff,
                                   department=str(r[dept_c]).strip() if dept_c else ""))
    if not entries:
        raise RosterError("The roster file contains no employee rows.")
    used = {"staff": str(staff_c or ""), "name": str(name_c or (f"{last_c} + {first_c}" if first_c else "")),
            "department": str(dept_c or "")}
    return Roster(entries, used)


def apply_roster_exclusions(roster: Roster, keywords, threshold: float) -> int:
    """Apply the same exclusion words to roster names and departments. Returns count excluded."""
    n = 0
    for e in roster.entries:
        reason = match_exclusion(e.name, keywords, threshold)
        if not reason:
            reason = match_exclusion(e.department, keywords, threshold).replace("Name contains", "Department contains", 1)
        if reason:
            e.excluded, e.exclusion_reason = True, reason
            n += 1
    return n


def _names_compatible(a: str, b: str) -> bool:
    """True when two names share a meaningful word (guards against reused staff numbers)."""
    ta = {t for t in normalise_name(a).split() if len(t) >= 3}
    tb = {t for t in normalise_name(b).split() if len(t) >= 3}
    return not ta or not tb or bool(ta & tb)


def match_roster(roster: Roster, employees: list[Employee]) -> tuple[list[RosterEntry], list[str]]:
    """Mark employees on/off roster. Returns (unmatched active roster entries, warnings).

    Matching order: staff number (only when the names agree), then exact name
    (word order and punctuation ignored, so 'Zindam, Cynthia' = 'Cynthia Zindam').
    """
    warnings: list[str] = []
    by_staff: dict[str, list[Employee]] = {}
    by_name: dict[str, list[Employee]] = {}
    for e in employees:
        e.on_roster = False
        s = normalise_staff_no(e.staff_no)
        if s:
            by_staff.setdefault(s, []).append(e)
        by_name.setdefault(normalise_name(e.cardholder_name), []).append(e)

    unmatched = []
    conflicts = 0
    for entry in roster.active:
        hits: list[Employee] = []
        s = normalise_staff_no(entry.staff_no)
        if s and s in by_staff:
            hits = [h for h in by_staff[s] if _names_compatible(h.cardholder_name, entry.name)]
            if hits:
                entry.match_method = "staff number"
            else:
                conflicts += 1
        if not hits and entry.name:
            hits = by_name.get(normalise_name(entry.name), [])
            if hits:
                entry.match_method = "name"
            if len({h.staff_no for h in hits}) > 1:
                warnings.append(f"{roster.ref(entry)}: name '{entry.name}' matches several cardholders; "
                                "all marked as on roster.")
        if hits:
            for h in hits:
                h.on_roster = True
                if entry.department:
                    h.roster_department = entry.department
            entry.matched_keys = [h.key for h in hits]
        else:
            unmatched.append(entry)
    warnings = list(dict.fromkeys(warnings))  # de-duplicate, keep order
    if conflicts:
        warnings.append(f"{conflicts} roster staff number(s) belong to a different name in the attendance "
                        "report; those were matched by name instead.")
    return unmatched, warnings


def exclude_by_roster(roster: Roster, employees: list[Employee]) -> list[Employee]:
    """Exclude attendance cardholders that the roster identifies as excluded (e.g. department 'Visitor').

    Only applies to people who did not also match an active roster entry, so an employee who
    shares a name with a visitor card is not excluded. Call after match_roster().
    """
    by_staff: dict[str, list[Employee]] = {}
    by_name: dict[str, list[Employee]] = {}
    for e in employees:
        if e.excluded or e.on_roster:
            continue
        s = normalise_staff_no(e.staff_no)
        if s:
            by_staff.setdefault(s, []).append(e)
        by_name.setdefault(normalise_name(e.cardholder_name), []).append(e)
    changed: list[Employee] = []
    for entry in roster.entries:
        if not entry.excluded:
            continue
        s = normalise_staff_no(entry.staff_no)
        hits = [h for h in by_staff.get(s, []) if _names_compatible(h.cardholder_name, entry.name)] if s else []
        if not hits and entry.name:
            hits = by_name.get(normalise_name(entry.name), [])
        for h in hits:
            if h.excluded:
                continue
            h.excluded = True
            h.exclusion_reason = f"Roster: {entry.exclusion_reason}"
            for sess in h.sessions:
                sess.excluded, sess.exclusion_reason = True, h.exclusion_reason
            changed.append(h)
    return changed
