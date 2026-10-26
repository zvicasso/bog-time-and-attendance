# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Command-line processing (for administrators, scheduled jobs and troubleshooting).

Examples:
    python cli.py "Time and Attendance 21-10-2026.pdf"
    python cli.py report.pdf --date 21/10/2026 --roster roster.xlsx --out results.xlsx
    python cli.py report.pdf --all-dates --late 08:00 --early 16:30
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from tap.config import load_settings, parse_hhmm
from tap.logging_setup import setup_logging
from tap.pdf_extract import PdfExtractionError
from tap.excel_source import ExcelSourceError
from tap.pipeline import process_report
from tap.roster import RosterError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Process a Time and Attendance report (PDF, Excel or CSV).")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--date", help="Reporting date DD/MM/YYYY (default: report end date)")
    ap.add_argument("--all-dates", action="store_true", help="Analyse every date in the report period")
    ap.add_argument("--roster", type=Path, help="Optional employee roster (.xlsx or .csv)")
    ap.add_argument("--late", help="Late threshold HH:MM (default from settings)")
    ap.add_argument("--early", help="Early departure threshold HH:MM (default from settings)")
    ap.add_argument("--out", type=Path, help="Output .xlsx path (default next to the PDF)")
    ap.add_argument("--report", type=Path, help="Also write the validation report (.txt)")
    ap.add_argument("--settings", type=Path, help="Alternative settings.toml")
    a = ap.parse_args(argv)

    s = load_settings(a.settings)
    setup_logging(s.log_path, s.log_level)
    over = {}
    if a.late:
        over["late_threshold"] = parse_hhmm(a.late)
    if a.early:
        over["early_threshold"] = parse_hhmm(a.early)
    s = s.with_overrides(**over)
    dates = [datetime.strptime(a.date, "%d/%m/%Y").date()] if a.date else None

    try:
        o = process_report(a.pdf, s, dates=dates, all_dates=a.all_dates, roster_path=a.roster,
                        progress=lambda f, m: print(f"\r{int(f * 100):3d}%  {m:<40}", end="", flush=True))
    except (PdfExtractionError, RosterError, ExcelSourceError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    print()
    stamp = o.dates[0].strftime("%Y-%m-%d") if len(o.dates) == 1 else "all-dates"
    out = a.out or a.pdf.with_name(f"Attendance_Analysis_{stamp}.xlsx")
    out.write_bytes(o.workbook)
    for k, v in o.summary.items():
        print(f"  {k:<32} {v}")
    if a.report:
        a.report.write_text(o.validation_report(), encoding="utf-8")
    print(f"\nWorkbook written to: {out}")
    return 1 if o.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
