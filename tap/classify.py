# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Attendance classification for one or more reporting dates.

Rules (per employee, per selected date D, excluded cardholders skipped):

* Sessions "on D" are rows whose FIRST ENTRY date is D (event date, not page or
  report generation date).
* Late arrival      : earliest entry on D is later than the late threshold.
* Early departure   : latest valid exit of the sessions on D is earlier than the
  departure threshold on D. Exits on a later day (overnight) are not early.
  "Report End Date/Time" and "Insufficient data" are NOT valid exits.
* On time           : entry on D, not late, valid departure known and not early
  (arrivals with no valid exit are not here - see Missing Exit exceptions).
* No recorded entry : no session with an entry on D. Without a roster this is
  reported as "absence not confirmed".
* Exceptions        : missing exit, missing entry, exit before entry, overlapping
  sessions, very long sessions, overnight sessions, late + early together,
  duplicate rows, unreadable values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .models import Employee, SessionRecord


@dataclass
class AnalysisResult:
    dates: list[date]
    late: list[dict] = field(default_factory=list)
    early: list[dict] = field(default_factory=list)
    on_time: list[dict] = field(default_factory=list)
    no_entry: list[dict] = field(default_factory=list)
    exceptions: list[dict] = field(default_factory=list)
    roster_supplied: bool = False

    def count_employees(self, rows: list[dict]) -> int:
        return len({(r["Date"], r["_key"]) for r in rows})


def _base(emp: Employee, d: date | None, roster: bool) -> dict:
    # Department comes from the roster when supplied, else from the attendance source (spreadsheets)
    row = {
        "Date": d,
        "Cardholder Name": emp.cardholder_name,
        "Staff No": emp.staff_no,
        "Card Number(s)": emp.card_numbers,
    }
    row["Department"] = emp.best_department
    if roster:
        row["On Roster"] = "Yes" if emp.on_roster else "No"
    row["_key"] = emp.key
    return row


def _refs(sessions: list[SessionRecord]) -> dict:
    pages = sorted({s.page for s in sessions})
    return {
        "Source Page(s)": ", ".join(map(str, pages)),
        "Record ID(s)": ", ".join(s.record_id for s in sessions),
    }


def _hms(td: timedelta) -> str:
    t = int(td.total_seconds())
    return f"{t // 3600}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def _minutes(td: timedelta) -> float:
    return round(td.total_seconds() / 60, 1)


def classify(employees: list[Employee], dates: list[date], late_threshold: time,
             early_threshold: time, max_session_hours: float = 16,
             roster_supplied: bool = False) -> AnalysisResult:
    res = AnalysisResult(dates=list(dates), roster_supplied=roster_supplied)
    active = [e for e in employees if not e.excluded]
    max_session = timedelta(hours=max_session_hours)

    # Values that could not be read are not tied to a date -> report them once.
    for emp in active:
        bad = [s for s in emp.sessions if any(n.startswith("Unreadable") for n in s.notes)]
        if bad:
            res.exceptions.append({**_base(emp, None, roster_supplied),
                                   "Exception Type": "Unreadable Values",
                                   "Detail": "; ".join(n for s in bad for n in s.notes if n.startswith("Unreadable")),
                                   "First Entry": None, "Last Exit": None, **_refs(bad)})

    for d in dates:
        late_dt = datetime.combine(d, late_threshold)
        early_dt = datetime.combine(d, early_threshold)
        for emp in active:
            live = [s for s in emp.sessions if not s.duplicate_of]
            dups = [s for s in emp.sessions if s.duplicate_of and s.entry_date == d]
            on_d = sorted([s for s in live if s.entry_date == d], key=lambda s: s.entry_dt)
            exit_only = [s for s in live if s.entry_dt is None and s.exit_dt and s.exit_dt.date() == d]
            overnight_in = [s for s in live if s.entry_dt and s.entry_dt.date() < d
                            and s.exit_dt and s.exit_dt.date() >= d]

            def exc(kind: str, detail: str, recs: list[SessionRecord], first=None, last=None):
                res.exceptions.append({**_base(emp, d, roster_supplied), "Exception Type": kind,
                                       "Detail": detail, "First Entry": first, "Last Exit": last,
                                       **_refs(recs)})

            if exit_only:
                exc("Missing Entry", "Exit recorded with no matching entry time.", exit_only,
                    last=max(s.exit_dt for s in exit_only))
            if dups:
                exc("Duplicate Records", f"{len(dups)} repeated row(s) ignored in calculations.", dups)

            if not on_d:
                other = []
                if overnight_in:
                    s = overnight_in[-1]
                    other.append(f"Still on site from {s.entry_dt:%d/%m/%Y %H:%M} (overnight)")
                if exit_only:
                    other.append("Exit without entry recorded")
                undated_insuff = [s for s in live if s.insufficient_data and s.entry_dt is None and s.exit_dt is None]
                if undated_insuff:
                    other.append("Report shows 'Insufficient data' with no timestamps")
                if not emp.sessions:
                    other.append("No attendance rows in report")
                if roster_supplied:
                    status = ("Absent - on roster, no entry recorded" if emp.on_roster
                              else "No entry recorded - not on roster")
                else:
                    status = "No entry recorded - absence not confirmed (no roster)"
                res.no_entry.append({**_base(emp, d, roster_supplied), "Status": status,
                                     "Other Activity": "; ".join(other) or "None in report",
                                     "Source Page(s)": ", ".join(map(str, sorted(emp.pages))),
                                     "Record ID(s)": ", ".join(s.record_id for s in emp.sessions)})
                continue

            first = on_d[0]
            first_entry = first.entry_dt
            valid_exits = [s for s in on_d if s.has_valid_exit]
            last_exit_rec = max(valid_exits, key=lambda s: s.exit_dt) if valid_exits else None
            last_exit = last_exit_rec.exit_dt if last_exit_rec else None
            missing_exit = [s for s in on_d if not s.has_valid_exit]
            is_late = first_entry > late_dt
            # The latest session must have a valid exit to judge departure
            latest_session = on_d[-1]
            departure_known = latest_session.has_valid_exit or (
                last_exit is not None and last_exit >= latest_session.entry_dt)
            is_early = bool(departure_known and last_exit and last_exit < early_dt)

            review = []
            if overnight_in:
                o_ = overnight_in[-1]
                review.append(f"On site overnight {o_.entry_dt:%d/%m %H:%M} - "
                              f"{o_.exit_dt:%d/%m %H:%M} (possible shift worker)")
            if len(on_d) > 1:
                review.append(f"{len(on_d)} sessions on this date")
            if missing_exit:
                review.append("Has a session without a valid exit")
            common = {"First Entry": first_entry, "Entry Clock": first.entry_clock,
                      "Last Exit": last_exit, "Exit Clock": last_exit_rec.exit_clock if last_exit_rec else "",
                      "Review Notes": "; ".join(review)}
            if is_late:
                res.late.append({**_base(emp, d, roster_supplied), **common,
                                 "Late Threshold": late_threshold,
                                 "Minutes Late": _minutes(first_entry - late_dt),
                                 "Also Early Departure": "Yes" if is_early else "No",
                                 **_refs(on_d)})
            if is_early:
                res.early.append({**_base(emp, d, roster_supplied), **common,
                                  "Departure Threshold": early_threshold,
                                  "Minutes Early": _minutes(early_dt - last_exit),
                                  "Also Late Arrival": "Yes" if is_late else "No",
                                  **_refs(on_d)})

            if not is_late and not is_early and departure_known and last_exit:
                res.on_time.append({**_base(emp, d, roster_supplied), **common,
                                    "Time on Site": last_exit - first_entry,
                                    **_refs(on_d)})

            for s in on_d:
                if s.integrity_notes:
                    exc("Data Integrity", "; ".join(s.integrity_notes), [s], s.entry_dt, s.exit_dt)

            for s in missing_exit:
                why = (s.missing_exit_label or
                       ("insufficient data" if s.insufficient_data else "no exit time"))
                detail = f"Entry {s.entry_dt:%H:%M:%S} has no valid exit - {why}."
                if s is latest_session and not departure_known:
                    detail += " Early-departure check not possible."
                exc("Missing Exit", detail, [s], first=s.entry_dt)
            for s in on_d:
                if s.exit_dt and s.exit_dt < s.entry_dt:
                    exc("Exit Before Entry", "Exit time is earlier than entry time (conflicting events).",
                        [s], s.entry_dt, s.exit_dt)
                elif s.has_valid_exit and s.exit_dt - s.entry_dt > max_session:
                    nxt = f", ends {s.exit_dt:%d/%m/%Y}" if s.exit_dt.date() > d else ""
                    exc("Long Session",
                        f"Session of {_hms(s.exit_dt - s.entry_dt)}{nxt} exceeds {max_session_hours:g} hours "
                        "(possible missed exit swipe).", [s], s.entry_dt, s.exit_dt)
                elif s.has_valid_exit and s.exit_dt.date() > d:
                    exc("Overnight Session", f"Exit recorded on {s.exit_dt:%d/%m/%Y}.", [s], s.entry_dt, s.exit_dt)
            for a, b in zip(on_d, on_d[1:]):
                if a.has_valid_exit and b.entry_dt < a.exit_dt:
                    exc("Overlapping Sessions", "A new entry starts before the previous exit.",
                        [a, b], a.entry_dt, b.exit_dt)
            still_open = [s for s in overnight_in if s.exit_dt > first_entry]
            if still_open:
                exc("Overlapping Sessions",
                    "Entry recorded on this date while a session from a previous day was still open.",
                    still_open + on_d[:1], first_entry, last_exit)
            if is_late and is_early:
                exc("Late Arrival and Early Departure",
                    f"Arrived {_minutes(first_entry - late_dt):g} min late and left "
                    f"{_minutes(early_dt - last_exit):g} min early.", on_d, first_entry, last_exit)

    return res
