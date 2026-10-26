# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""End-to-end processing: PDF -> records -> classification -> Excel bytes.

Used by both the web interface (app.py) and the command line (cli.py).
"""

from __future__ import annotations

import logging
import time as _time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .classify import AnalysisResult, classify
from .config import Settings
from .excel_report import build_workbook
from .filtering import group_employees, normalise_name
from .models import Employee, Issue, ParseResult, ReportMeta
from .excel_source import is_spreadsheet, parse_spreadsheet
from .parser import ReportParser, parse_lines
from .pdf_extract import extract_lines
from .roster import (Roster, RosterEntry, apply_roster_exclusions, exclude_by_roster, load_roster,
                     match_roster)

log = logging.getLogger(__name__)
ProgressFn = Callable[[float, str], None]


@dataclass
class ProcessingOutcome:
    source_name: str
    meta: ReportMeta
    parse: ParseResult
    employees: list[Employee]
    analysis: AnalysisResult
    dates: list[date]
    summary: dict = field(default_factory=dict)
    exception_counts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    all_issues: list[Issue] = field(default_factory=list)
    interpretation_notes: list[str] = field(default_factory=list)
    exclusions: dict = field(default_factory=dict)
    roster: Roster | None = None
    roster_unmatched: list[RosterEntry] = field(default_factory=list)
    workbook: bytes = b""
    elapsed_s: float = 0.0

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.all_issues)

    def validation_report(self) -> str:
        lines = ["TIME AND ATTENDANCE PROCESSING - VALIDATION REPORT", "=" * 52, ""]
        for k, v in self.summary.items():
            lines.append(f"{k:<34}: {v}")
        lines += ["", "EXCEPTIONS BY TYPE", "-" * 18]
        lines += [f"{k:<34}: {v}" for k, v in self.exception_counts.items()] or ["None"]
        lines += ["", "ISSUES", "-" * 6]
        if not self.all_issues:
            lines.append("No parsing or validation problems were found.")
        for i in self.all_issues:
            where = f"page {i.page}" if i.page else ""
            if i.block_id:
                where += f", section {i.block_id}"
            lines.append(f"[{i.severity}] {i.category} ({where.strip(', ')}): {i.message}")
            if i.raw_text:
                lines.append(f"        source: {i.raw_text}")
        return "\n".join(lines) + "\n"


def peek_report(source: Path | bytes, settings: Settings, filename: str = "") -> tuple[ReportMeta, int]:
    """Read the report header (site, period). Returns (meta, total pages or data rows).

    PDFs: only the first pages are read. Spreadsheets: the file is read (it is small).
    """
    from .pdf_extract import page_count

    if filename and is_spreadsheet(filename):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="tap_peek_") as d:
            p = Path(d) / ("peek" + Path(filename).suffix.lower())
            p.write_bytes(source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes())
            res = parse_spreadsheet(p, settings.pdf_date_order)
        return res.meta, res.meta.extra_rows
    total = page_count(source)
    res = ReportParser(settings.pdf_date_order).feed(extract_lines(source, max_pages=3))
    return res.meta, total


def report_dates(parse: ParseResult) -> list[date]:
    """Every calendar date in the report period (or with entry events)."""
    m = parse.meta
    if m.start and m.end and m.end >= m.start and (m.end - m.start).days <= 62:
        n = (m.end.date() - m.start.date()).days
        return [date.fromordinal(m.start.date().toordinal() + i) for i in range(n + 1)]
    return sorted({s.entry_date for s in parse.sessions if s.entry_date})


def default_date(parse: ParseResult) -> date | None:
    if parse.meta.end:
        return parse.meta.end.date()
    ds = report_dates(parse)
    return ds[-1] if ds else None


def _data_quality_issues(employees: list[Employee]) -> list[Issue]:
    issues = []
    by_name = defaultdict(set)
    name_counts = Counter()
    for e in employees:
        if not e.excluded:
            by_name[normalise_name(e.cardholder_name)].add(e.staff_no or "(blank)")
            name_counts[e.cardholder_name.strip().upper()] += len(e.block_ids)
    for n, staff in by_name.items():
        if len(staff) > 1:
            issues.append(Issue("INFO", "Same name, different IDs",
                f"A cardholder name appears with {len(staff)} different staff numbers "
                f"({', '.join(sorted(staff))}); treated as separate people. Verify manually.",
                raw_text=n.title()))
    for n, c in name_counts.items():
        if c >= 5 and len(n.split()) == 1 and "," not in n:
            issues.append(Issue("WARNING", "Generic cardholder name",
                f"{c} cardholder sections are named '{n}'. They are INCLUDED in the analysis. "
                f"Add '{n.title()}' to the exclusion keywords if they should be excluded."))
    return issues


def process_report(pdf_path: Path | str, settings: Settings, *, source_name: str = "",
                dates: list[date] | None = None, all_dates: bool = False,
                roster_path: Path | str | None = None,
                progress: ProgressFn | None = None) -> ProcessingOutcome:
    t0 = _time.time()
    pdf_path = Path(pdf_path)
    source_name = source_name or pdf_path.name
    say = progress or (lambda f, m: None)

    if is_spreadsheet(pdf_path):
        say(0.10, "Reading spreadsheet...")
        parse = parse_spreadsheet(pdf_path, settings.pdf_date_order)
    else:
        say(0.02, "Reading PDF...")
        lines = extract_lines(pdf_path, progress=lambda i, n: say(0.02 + 0.78 * i / n, f"Reading page {i} of {n}"))
        parse = parse_lines(lines, settings.pdf_date_order)
    log.info("parsed: pages=%d sections=%d rows=%d issues=%d", parse.meta.page_count,
             len(parse.blocks), len(parse.sessions), len(parse.issues))

    say(0.82, "Grouping cardholders and applying exclusions...")
    employees = group_employees(parse.blocks, settings.exclude_keywords, settings.fuzzy_threshold,
                                settings.visitor_doors)
    exclusions = {}
    for e in employees:
        for b in e.block_ids:
            exclusions[b] = e.exclusion_reason

    issues: list[Issue] = list(parse.issues)
    roster_warnings: list[str] = []
    unmatched: list[RosterEntry] = []
    roster = None
    roster_desc = "Not supplied - absences cannot be confirmed"
    if roster_path:
        say(0.85, "Reading and matching employee roster...")
        roster = load_roster(roster_path)
        n_ex = apply_roster_exclusions(roster, settings.exclude_keywords, settings.fuzzy_threshold)
        unmatched, roster_warnings = match_roster(roster, employees)
        newly_excluded = exclude_by_roster(roster, employees)
        if newly_excluded:
            roster_warnings.append(f"{len(newly_excluded)} attendance cardholder(s) excluded because the roster lists "
                                   "them under an excluded name/department (e.g. Visitor).")
            for e in newly_excluded:
                for b in e.block_ids:
                    exclusions[b] = e.exclusion_reason
        active_emps = [e for e in employees if not e.excluded]
        on = sum(1 for e in active_emps if e.on_roster)
        roster_desc = (f"{roster.source_type.title()}: {len(roster)} cardholders, {n_ex} excluded by keyword, "
                       f"{len(roster.active) - len(unmatched)} matched, {len(unmatched)} not in attendance report. "
                       f"{on} of {len(active_emps)} analysed employees are on the roster.")
        for w in roster.warnings:
            issues.append(Issue("WARNING", "Roster", w))
        for w in roster_warnings:
            issues.append(Issue("INFO", "Roster matching", w))
        off = [e for e in active_emps if not e.on_roster]
        if off:
            issues.append(Issue("INFO", "Not on roster",
                f"{len(off)} analysed employee(s) in the attendance report were not found on the roster "
                "(see the 'On Roster' column)."))

    if not dates:
        if all_dates:
            dates = report_dates(parse)
        else:
            d = default_date(parse)
            dates = [d] if d else []
    if not dates:
        issues.append(Issue("ERROR", "Date", "No reporting date could be determined."))
    available = set(report_dates(parse))
    for d in dates:
        if available and d not in available:
            issues.append(Issue("WARNING", "Date",
                f"{d:%d/%m/%Y} is outside the report period; no attendance can be found for it."))
        elif not any(s.entry_date == d for s in parse.sessions):
            issues.append(Issue("WARNING", "Date", f"The report contains no entry events on {d:%d/%m/%Y}."))

    say(0.88, "Classifying attendance...")
    analysis = classify(employees, dates, settings.late_threshold, settings.early_threshold,
                        settings.max_session_hours,
                        roster_supplied=bool(roster_path))
    issues += _data_quality_issues(employees)

    sessions = parse.sessions
    excl_emps = [e for e in employees if e.excluded]
    active = [e for e in employees if not e.excluded]
    exc_counts = Counter(r["Exception Type"] for r in analysis.exceptions)
    n_err = sum(1 for i in issues if i.severity == "ERROR")
    n_warn = sum(1 for i in issues if i.severity == "WARNING")
    m = parse.meta
    status = ("Completed with errors - review the Validation sheet" if n_err else
              "Completed with warnings" if n_warn else "Completed successfully")
    summary = {
        "Source file": source_name,
        "Source format": (f"{m.source_format} ({m.report_type})" if m.report_type else m.source_format),
        "Staff ID field": m.personal_field or "(not stated)",
        "Site": m.site_name,
        "Report period": (f"{m.start:%d/%m/%Y %H:%M} to {m.end:%d/%m/%Y %H:%M}" if m.start and m.end else "Unknown"),
        "Report generated": m.generated,
        "Pages / rows read": (f"{m.page_count} pages" if m.source_format == "PDF" else f"{m.extra_rows} rows"),
        "Reporting date(s)": ", ".join(d.strftime("%d/%m/%Y") for d in dates),
        "Late arrival threshold": f"Entry later than {settings.late_threshold:%H:%M}",
        "Early departure threshold": f"Exit earlier than {settings.early_threshold:%H:%M}",
        "Exclusion keywords": ", ".join(settings.exclude_keywords) or "(none)",
        "Visitor doors": ", ".join(settings.visitor_doors) or "(none)",
        "Employee roster": roster_desc,
        "Processed at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "Processing status": status,
        "Cardholder sections in report": len(parse.blocks),
        "Total records extracted": len(sessions),
        "Unique cardholders": len(employees),
        "Excluded cardholders": len(excl_emps),
        "Excluded records": sum(1 for s in sessions if s.excluded),
        "Employees analysed": len(active),
        "Duplicate records ignored": sum(1 for s in sessions if s.duplicate_of),
        "On time (arrived and left on time)": analysis.count_employees(analysis.on_time),
        "Late arrivals": analysis.count_employees(analysis.late),
        "Early departures": analysis.count_employees(analysis.early),
        "No recorded entry": analysis.count_employees(analysis.no_entry),
        "Attendance exceptions (rows)": len(analysis.exceptions),
        "Employees with exceptions": len({(r["Date"], r["_key"]) for r in analysis.exceptions}),
        "Roster employees not in attendance report": len(unmatched) if roster_path else "n/a",
        "Validation warnings / errors": f"{n_warn} / {n_err}",
    }
    notes = [
        "Late Arrivals: earliest entry on the date is later than the threshold. "
        "Early Departures: latest valid exit on the date is earlier than the threshold. "
        "On Time: arrived by the late threshold AND left at or after the departure threshold.",
        "Dates come from the actual entry timestamps, not from the PDF page or generation date. "
        "A session that starts on one day and ends the next belongs to the start day.",
        "'Report End Date/Time' and 'Insuff. D.' are not real exits; such rows appear under "
        "Attendance Exceptions as Missing Exit and are not counted as early departures.",
        ("No Recorded Entry lists cardholders in the PDF with no entry on the date. No roster was "
         "supplied, so this is NOT a confirmed absence list; staff missing from the PDF entirely "
         "cannot be detected.") if not roster_path else
        ("A roster was supplied: cardholders on the roster with no entry are marked 'Absent'. Roster "
         "employees with no section at all in the attendance PDF are listed on the 'Roster Not In Report' "
         "sheet: they had no badge activity OR were not selected when the report was run (e.g. regional "
         "branch staff) - filter that sheet by Department before treating anyone as absent."),
        ("Every row links back to the PDF via Source Page(s) and Record ID(s) (see Raw Data)."
         if m.source_format == "PDF" else
         "Every row links back to the spreadsheet row number via Source Page(s)/Row and Record ID(s). "
         "Spreadsheet exports list only people who badged in, so 'No Recorded Entry' needs a roster "
         "(or a multi-day export) to show absentees."),
    ]
    warnings = [f"[{i.severity}] {i.category}: {i.message}"
                + (f" (page {i.page})" if i.page else "") + (f" - {i.raw_text}" if i.raw_text and i.severity != "INFO" else "")
                for i in issues if i.severity in ("ERROR", "WARNING")]
    outcome = ProcessingOutcome(source_name=source_name, meta=m, parse=parse, employees=employees,
                                analysis=analysis, dates=dates, summary=summary,
                                exception_counts=dict(exc_counts.most_common()), warnings=warnings,
                                all_issues=issues, interpretation_notes=notes, exclusions=exclusions,
                                roster=roster, roster_unmatched=unmatched)
    say(0.92, "Building Excel workbook...")
    outcome.workbook = build_workbook(outcome)
    outcome.elapsed_s = round(_time.time() - t0, 1)
    log.info("done in %.1fs: employees=%d excluded=%d late=%d early=%d noentry=%d exceptions=%d",
             outcome.elapsed_s, len(employees), len(excl_emps), summary["Late arrivals"],
             summary["Early departures"], summary["No recorded entry"], len(analysis.exceptions))
    say(1.0, "Done")
    return outcome


# Backwards-compatible name
process_pdf = process_report
