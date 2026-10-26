# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    page: int  # 1-based


@dataclass
class Line:
    page: int
    top: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return self.words[0].x0 if self.words else 0.0


@dataclass
class ReportMeta:
    report_type: str = ""
    site_name: str = ""
    operator: str = ""
    start: datetime | None = None
    end: datetime | None = None
    generated: str = ""
    page_count: int = 0
    declared_page_count: int | None = None
    personal_field: str = ""          # label of the ID field, e.g. "Staff No"
    source_format: str = "PDF"        # "PDF" | "Excel" | "CSV"
    extra_rows: int = 0               # spreadsheet sources: number of data rows read


@dataclass
class SessionRecord:
    """One data row of the report (a first entry / last exit pair)."""

    record_id: str
    block_id: int
    page: int
    cardholder_name: str
    staff_no: str
    card_numbers: str
    entry_clock: str = ""
    entry_dt: datetime | None = None
    exit_clock: str = ""
    exit_dt: datetime | None = None
    exit_is_report_end: bool = False   # exit shown is a placeholder (PDF 'Report End', Excel 'X_24')
    missing_exit_label: str = ""       # why there is no valid exit, in the source's own terms
    time_worked: timedelta | None = None
    time_worked_raw: str = ""
    insufficient_data: bool = False
    raw_text: str = ""
    notes: list[str] = field(default_factory=list)
    integrity_notes: list[str] = field(default_factory=list)  # signs of manual editing in the source
    # Populated later in the pipeline
    employee_key: str = ""
    excluded: bool = False
    exclusion_reason: str = ""
    duplicate_of: str = ""

    @property
    def has_valid_exit(self) -> bool:
        return self.exit_dt is not None and not self.exit_is_report_end

    @property
    def entry_date(self) -> date | None:
        return self.entry_dt.date() if self.entry_dt else None


@dataclass
class CardholderBlock:
    block_id: int
    page: int
    cardholder_name: str = ""
    staff_no: str = ""
    card_numbers: str = ""
    total_working_raw: str = ""
    total_working: timedelta | None = None
    department: str = ""                # spreadsheet sources carry a department column
    sessions: list[SessionRecord] = field(default_factory=list)
    closed: bool = False


@dataclass
class Issue:
    """A parsing / validation problem. Never silently dropped."""

    severity: str  # "ERROR" | "WARNING" | "INFO"
    category: str
    message: str
    page: int | None = None
    block_id: int | None = None
    raw_text: str = ""


@dataclass
class Employee:
    key: str
    cardholder_name: str
    staff_no: str
    card_numbers: str
    block_ids: list[int] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)
    sessions: list[SessionRecord] = field(default_factory=list)
    excluded: bool = False
    exclusion_reason: str = ""
    on_roster: bool | None = None  # None = no roster supplied
    roster_department: str = ""
    department: str = ""           # from the attendance source itself (spreadsheet exports)

    @property
    def best_department(self) -> str:
        return self.roster_department or self.department


@dataclass
class ParseResult:
    meta: ReportMeta
    blocks: list[CardholderBlock]
    issues: list[Issue]

    @property
    def sessions(self) -> list[SessionRecord]:
        return [s for b in self.blocks for s in b.sessions]
