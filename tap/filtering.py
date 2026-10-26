# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Employee grouping, duplicate detection and keyword-based exclusion."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import Employee, SessionRecord

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def normalise_name(name: str) -> str:
    """Upper-case, punctuation-free, order-independent name key.

    'Zindam, Cynthia' and 'CYNTHIA ZINDAM' both become 'CYNTHIA ZINDAM'.
    """
    return " ".join(sorted(t.upper() for t in _TOKEN_RE.findall(name or "")))


def normalise_staff_no(value: str) -> str:
    v = re.sub(r"\s+", "", str(value or ""))
    if v.endswith(".0") and v[:-2].isdigit():  # Excel numeric artefact
        v = v[:-2]
    return v.lstrip("0") or ("0" if v else "")


def match_exclusion(name: str, keywords: tuple[str, ...] | list[str], threshold: float = 0.8) -> str:
    """Return a human-readable reason if the name matches an exclusion keyword, else ''."""
    tokens = [t.upper() for t in _TOKEN_RE.findall(name or "")]
    for kw in keywords:
        k = kw.strip().upper()
        if not k:
            continue
        for tok in tokens:
            if k in tok:
                return f"Name contains '{tok}' (rule: {kw})"
            if threshold < 1.0 and len(tok) >= 5 and len(k) >= 5:
                if SequenceMatcher(None, tok, k).ratio() >= threshold:
                    return f"Name contains '{tok}' (similar to rule: {kw})"
    return ""


def employee_key(rec: SessionRecord | Employee) -> str:
    ident = normalise_staff_no(rec.staff_no) or re.sub(r"\s+", "", rec.card_numbers or "")
    return f"{normalise_name(rec.cardholder_name)}|{ident}"


def group_employees(blocks, keywords, threshold, visitor_doors: tuple[str, ...] | list[str] = ()) -> list[Employee]:
    """Merge repeated cardholder sections for the same person and flag exclusions."""
    employees: dict[str, Employee] = {}
    for b in blocks:
        key = employee_key(b)
        emp = employees.get(key)
        if emp is None:
            reason = match_exclusion(b.cardholder_name, keywords, threshold)
            if not reason and b.department:
                reason = match_exclusion(b.department, keywords, threshold).replace(
                    "Name contains", "Department contains", 1)
            emp = Employee(key=key, cardholder_name=b.cardholder_name,
                           staff_no=b.staff_no, card_numbers=b.card_numbers,
                           excluded=bool(reason), exclusion_reason=reason, department=b.department)
            employees[key] = emp
        emp.block_ids.append(b.block_id)
        if b.page not in emp.pages:
            emp.pages.append(b.page)
        for s in b.sessions:
            s.employee_key = key
            s.excluded, s.exclusion_reason = emp.excluded, emp.exclusion_reason
            if s.page not in emp.pages:
                emp.pages.append(s.page)
            emp.sessions.append(s)
    for emp in employees.values():
        _mark_duplicates(emp.sessions)
        if not emp.excluded and visitor_doors:
            # Visitor badges are first used at a visitor-management workstation
            # (e.g. 'FT Workstation on VISITORS-MANAGE'); the clue is the door, not the name.
            for sess in emp.sessions:
                door = sess.entry_clock.upper()
                hit = next((d for d in visitor_doors if d.strip() and d.strip().upper() in door), None)
                if hit:
                    emp.excluded = True
                    emp.exclusion_reason = f"Entry door '{sess.entry_clock}' (visitor door rule: {hit})"
                    break
        if emp.excluded:
            for sess in emp.sessions:
                sess.excluded, sess.exclusion_reason = True, emp.exclusion_reason
    return list(employees.values())


def _mark_duplicates(sessions: list[SessionRecord]) -> None:
    seen: dict[tuple, str] = {}
    for s in sessions:
        if s.entry_dt is None and s.exit_dt is None:
            continue  # empty 'insufficient data' rows carry no event to duplicate
        sig = (s.entry_dt, s.exit_dt, s.entry_clock, s.exit_clock, s.time_worked_raw)
        if sig in seen:
            s.duplicate_of = seen[sig]
            s.notes.append(f"Duplicate of {seen[sig]}")
        else:
            seen[sig] = s.record_id
