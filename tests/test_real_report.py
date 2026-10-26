# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Regression test against a real report (optional - never commit real employee data).

Set TAP_SAMPLE_PDF to the path of 'Time and Attendance 21-10-2026.pdf' to run:
    set TAP_SAMPLE_PDF=C:\\path\\Time and Attendance 21-10-2026.pdf
    python -m pytest tests\\test_real_report.py
"""

import os
from datetime import date
from pathlib import Path

import pytest

SAMPLE = os.environ.get("TAP_SAMPLE_PDF", "")

pytestmark = pytest.mark.skipif(not SAMPLE or not Path(SAMPLE).exists(),
                                reason="TAP_SAMPLE_PDF not set")


def test_bank_of_ghana_21_october_2026():
    from tap.config import Settings
    from tap.pipeline import process_pdf

    o = process_pdf(SAMPLE, Settings(), dates=[date(2026, 10, 21)])
    s = o.summary
    assert s["Pages / rows read"] == "451 pages"
    assert s["Cardholder sections in report"] == 1953
    assert s["Total records extracted"] == 2458
    assert not o.has_errors
    # every section total in the PDF reconciled with the parsed rows
    assert not [i for i in o.all_issues if i.category == "Total mismatch"]
    assert s["Late arrivals"] == 561
    assert s["Early departures"] == 201
    assert s["No recorded entry"] == 163


ROSTER = os.environ.get("TAP_SAMPLE_ROSTER", "")


@pytest.mark.skipif(not ROSTER or not Path(ROSTER).exists(), reason="TAP_SAMPLE_ROSTER not set")
def test_bank_of_ghana_with_cardholder_roster():
    from tap.config import Settings
    from tap.pipeline import process_pdf

    o = process_pdf(SAMPLE, Settings(), dates=[date(2026, 10, 21)], roster_path=ROSTER)
    assert len(o.roster) == 3536
    active = [e for e in o.employees if not e.excluded]
    assert all(e.on_roster for e in active)          # every analysed employee is a known cardholder
    assert o.summary["Excluded cardholders"] == 125  # 2 extra visitors identified by the roster


PDF2 = os.environ.get("TAP_SAMPLE_PDF2", "")    # '20 to 21 October 2026 Time and Attendance.pdf' (Staff No)
XLSX = os.environ.get("TAP_SAMPLE_XLSX", "")    # '20-10-2026 - Time & Attendance.xlsx'


@pytest.mark.skipif(not PDF2 or not Path(PDF2).exists(), reason="TAP_SAMPLE_PDF2 not set")
def test_staff_no_pdf():
    from tap.config import Settings
    from tap.pipeline import process_report

    o = process_report(PDF2, Settings(), dates=[date(2026, 10, 21)])
    assert o.meta.personal_field == "Staff No"
    assert o.summary["Cardholder sections in report"] == 2771
    assert not o.parse.issues                       # every section total reconciles


@pytest.mark.skipif(not XLSX or not Path(XLSX).exists(), reason="TAP_SAMPLE_XLSX not set")
def test_excel_export():
    from tap.config import Settings
    from tap.pipeline import process_report

    o = process_report(XLSX, Settings(), dates=[date(2026, 10, 20)])
    assert o.summary["Total records extracted"] == 1601
    integ = {r["Cardholder Name"] for r in o.analysis.exceptions if r["Exception Type"] == "Data Integrity"}
    assert "Adams, Jonas" in integ
