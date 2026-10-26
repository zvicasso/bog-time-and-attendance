# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Spreadsheet (Excel/CSV) attendance source and the 'Staff No' PDF variant."""

import io
from datetime import date, datetime

import openpyxl
import pandas as pd
import pytest

from tap.excel_source import ExcelSourceError, parse_spreadsheet
from tap.pipeline import process_report

D20 = date(2026, 10, 20)


def names(rows):
    return sorted(r["Cardholder Name"] for r in rows)


@pytest.fixture(scope="module")
def out_x(excel_export):
    from tap.config import Settings
    return process_report(excel_export, Settings(), dates=[D20])


def test_spreadsheet_is_parsed(excel_export):
    r = parse_spreadsheet(excel_export)
    assert r.meta.source_format == "Excel" and r.meta.personal_field == "Staff No"
    assert len(r.sessions) == 10
    mensah = r.blocks[0].sessions[0]
    assert mensah.staff_no == "6123" and mensah.entry_dt == datetime(2026, 10, 20, 7, 45)
    assert r.blocks[0].department == "Finance"


def test_x24_is_missing_exit(out_x):
    kinds = {(r["Cardholder Name"], r["Exception Type"]) for r in out_x.analysis.exceptions}
    assert ("Darko, Kwame", "Missing Exit") in kinds
    assert "Darko, Kwame" not in names(out_x.analysis.early)
    darko = next(r for r in out_x.analysis.exceptions if r["Cardholder Name"] == "Darko, Kwame")
    assert "X_24" in darko["Detail"]


def test_same_rules_as_pdf(out_x):
    assert names(out_x.analysis.late) == ["Asante, Efua", "Owusu, Ama"]
    assert names(out_x.analysis.early) == ["Adams, Jonas", "Asante, Efua", "Boateng, Yaw"] or \
        names(out_x.analysis.early) == ["Asante, Efua", "Boateng, Yaw"]
    assert "Adomako, Akua" in names(out_x.analysis.on_time)      # exactly 08:05:00 and 17:00:00


def test_department_column_and_visitor_department_exclusion(out_x):
    excl = {e.cardholder_name: e.exclusion_reason for e in out_x.employees if e.excluded}
    assert "McConaghy, Peter" in excl and "Department" in excl["McConaghy, Peter"]
    assert "019, Temporary" in excl
    late = out_x.analysis.late[0]
    assert late["Department"] in ("Finance", "ICT")


def test_hand_edited_row_is_flagged(out_x):
    integ = [r for r in out_x.analysis.exceptions if r["Exception Type"] == "Data Integrity"]
    assert [r["Cardholder Name"] for r in integ] == ["Adams, Jonas"]
    assert "typed date/time" in integ[0]["Detail"] and "does not match" in integ[0]["Detail"]
    assert any("Data integrity" in w for w in out_x.warnings)


def test_workbook_from_spreadsheet(out_x):
    wb = openpyxl.load_workbook(io.BytesIO(out_x.workbook))
    h = [c.value for c in wb["Late Arrivals"][1]]
    assert "Staff No" in h and "Department" in h
    raw = wb["Raw Data"]
    assert [c.value for c in raw[1]][2] == "Source Page/Row"


def test_csv_and_flexible_headers(tmp_path):
    p = tmp_path / "export.csv"
    pd.DataFrame([{"Employee ID": "0042", "Name": "Tetteh, Ama", "Time In": "20/10/2026 8:30:00 am",
                   "Time Out": "20/10/2026 5:15:00 pm", "Duration": "08:45:00"}]).to_csv(p, index=False)
    r = parse_spreadsheet(p)
    s = r.sessions[0]
    assert r.meta.source_format == "CSV" and s.staff_no == "0042"
    assert s.exit_dt == datetime(2026, 10, 20, 17, 15) and not s.integrity_notes


def test_spreadsheet_without_required_columns(tmp_path):
    p = tmp_path / "bad.xlsx"
    pd.DataFrame([{"Colour": "red"}]).to_excel(p, index=False)
    with pytest.raises(ExcelSourceError):
        parse_spreadsheet(p)


def test_pdf_with_staff_no_label(staffno_pdf, synthetic_pdf):
    """Reports configured with 'Staff No' instead of 'Staff Card No' give identical results."""
    from tap.config import Settings
    a = process_report(staffno_pdf, Settings(), dates=[date(2026, 10, 21)])
    b = process_report(synthetic_pdf, Settings(), dates=[date(2026, 10, 21)])
    assert a.meta.personal_field == "Staff No" and b.meta.personal_field == "Staff Card No"
    assert a.parse.blocks[0].staff_no == "000123"
    assert names(a.analysis.late) == names(b.analysis.late)
    assert not a.parse.issues


def test_visitor_workstation_badge_is_excluded(out_x):
    teye = next(e for e in out_x.employees if e.cardholder_name == "TEYE, ABRAHAM")
    assert teye.excluded and "VISITORS-MANAGE" in teye.exclusion_reason
