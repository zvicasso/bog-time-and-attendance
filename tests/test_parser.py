# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
from datetime import datetime, timedelta

from tap.parser import join_wrapped, parse_datetime, parse_duration, parse_lines
from tap.pdf_extract import extract_lines


def _parse(pdf):
    return parse_lines(extract_lines(pdf))


def test_metadata(synthetic_pdf):
    r = _parse(synthetic_pdf)
    assert r.meta.site_name == "Test Site HQ"
    assert r.meta.start == datetime(2026, 10, 20, 0, 0)
    assert r.meta.end == datetime(2026, 10, 21, 23, 59, 59)
    assert r.meta.page_count == r.meta.declared_page_count


def test_all_sections_and_rows_extracted_without_issues(synthetic_pdf):
    r = _parse(synthetic_pdf)
    assert len(r.blocks) == 19
    assert len(r.sessions) == 36
    assert r.issues == []
    assert all(b.closed for b in r.blocks)


def test_wrapped_clock_names_and_am_pm(synthetic_pdf):
    r = _parse(synthetic_pdf)
    nk = next(b for b in r.blocks if b.cardholder_name == "Nkrumah, Afua").sessions[0]
    assert nk.entry_clock == "PDM-UG-SP.GT.U5-RIN"          # wrapped 'PDM-UG-SP.GT.U5-' + 'RIN'
    assert nk.exit_clock == "PDM-UG-SP.GT.U1-ROUT"
    assert nk.entry_dt == datetime(2026, 10, 21, 12, 15)    # '12:15:00' + wrapped 'pm'
    assert nk.time_worked == timedelta(hours=5, minutes=45)


def test_report_end_and_insufficient_data(synthetic_pdf):
    r = _parse(synthetic_pdf)
    darko = next(b for b in r.blocks if b.cardholder_name == "Darko, Kwame").sessions[0]
    assert darko.exit_is_report_end and not darko.has_valid_exit
    assert darko.exit_clock == ""
    quaye = next(b for b in r.blocks if b.cardholder_name == "Quaye, Nii").sessions[0]
    assert quaye.insufficient_data and quaye.entry_dt is None and quaye.exit_dt is None


def test_section_spanning_pages_is_kept_together(synthetic_pdf):
    r = _parse(synthetic_pdf)
    long = next(b for b in r.blocks if b.cardholder_name == "Long, Section")
    assert len(long.sessions) == 17
    assert len({s.page for s in long.sessions}) == 2
    assert long.total_working == timedelta(hours=177)


def test_section_without_rows(synthetic_pdf):
    r = _parse(synthetic_pdf)
    c = next(b for b in r.blocks if b.cardholder_name == "Contractor")
    assert c.sessions == [] and c.total_working_raw == "0:00:00"


def test_blank_staff_number_and_multiple_cards(synthetic_pdf):
    r = _parse(synthetic_pdf)
    s = next(b for b in r.blocks if b.cardholder_name == "Sarpong, Kwabena")
    assert s.staff_no == ""
    assert s.card_numbers == "4001001012, 4001001013"


def test_leading_zeros_preserved(synthetic_pdf):
    r = _parse(synthetic_pdf)
    assert r.blocks[0].staff_no == "000123"


def test_helpers():
    assert parse_datetime("21/10/2026 12:01:11 pm") == datetime(2026, 10, 21, 12, 1, 11)
    assert parse_datetime("21/10/2026 12:01:11 am") == datetime(2026, 10, 21, 0, 1, 11)
    assert parse_datetime("21/10/2026 17:01:11") == datetime(2026, 10, 21, 17, 1, 11)
    assert parse_datetime("10/21/2026 5:01:11 pm", "MDY") == datetime(2026, 10, 21, 17, 1, 11)
    assert parse_datetime("32/10/2026 5:00:00 pm") is None
    assert parse_duration("25:53:55") == timedelta(hours=25, minutes=53, seconds=55)
    assert parse_duration("Insuff. D.") is None
    assert join_wrapped(["PDM-UG-SP.GT.U5-", "RIN"]) == "PDM-UG-SP.GT.U5-RIN"
    assert join_wrapped(["Report", "End"]) == "Report End"


def test_pdfium_and_pdfplumber_engines_agree(synthetic_pdf):
    """The fast engine (pypdfium2) must produce exactly what pdfplumber produces."""
    from tap.pdf_extract import _group_lines, _pdfplumber_page_words, page_count

    def plumber_lines():
        for i in range(page_count(synthetic_pdf)):
            yield from _group_lines(_pdfplumber_page_words(synthetic_pdf, i), i + 1)

    def sig(r):
        return [(s.cardholder_name, s.staff_no, s.entry_clock, s.entry_dt, s.exit_clock,
                 s.exit_dt, s.exit_is_report_end, s.time_worked_raw) for s in r.sessions]

    assert sig(_parse(synthetic_pdf)) == sig(parse_lines(plumber_lines()))
