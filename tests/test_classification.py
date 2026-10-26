# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
from datetime import date, time

import pytest

from tap.filtering import match_exclusion, normalise_name, normalise_staff_no
from tap.pipeline import process_pdf

D21, D20 = date(2026, 10, 21), date(2026, 10, 20)


def names(rows):
    return sorted(r["Cardholder Name"] for r in rows)


@pytest.fixture(scope="module")
def out21(synthetic_pdf):
    from tap.config import Settings
    return process_pdf(synthetic_pdf, Settings(), dates=[D21])


def test_exclusions(out21):
    excl = sorted(e.cardholder_name for e in out21.employees if e.excluded)
    assert excl == ["Contractor", "TEMPORARAY STAFF", "Temporary, Bank Square", "VISITOR"]
    assert out21.summary["Employees analysed"] == 14


def test_late_arrivals_respect_threshold(out21):
    # Adomako arrives at exactly 08:05:00 -> not late
    assert names(out21.analysis.late) == ["Asante, Efua", "Long, Section", "Nkrumah, Afua", "Owusu, Ama"]
    owusu = next(r for r in out21.analysis.late if r["Cardholder Name"] == "Owusu, Ama")
    assert owusu["Minutes Late"] == 15.2


def test_early_departures(out21):
    # Darko has no valid exit (Report End) -> not early; Adomako leaves at exactly 17:00 -> not early
    assert names(out21.analysis.early) == ["Asante, Efua", "Boateng, Yaw"]


def test_no_recorded_entry_without_roster(out21):
    assert names(out21.analysis.no_entry) == ["Appiah, Abena", "Quaye, Nii"]
    assert all("absence not confirmed" in r["Status"] for r in out21.analysis.no_entry)


def test_exceptions(out21):
    kinds = sorted((r["Cardholder Name"], r["Exception Type"]) for r in out21.analysis.exceptions)
    assert kinds == [
        ("Agyeman, Yaa", "Long Session"),
        ("Asante, Efua", "Late Arrival and Early Departure"),
        ("Darko, Kwame", "Missing Exit"),
        ("Ofori, Esi", "Duplicate Records"),
    ]


def test_repeated_sections_are_merged_and_deduplicated(out21):
    ofori = [e for e in out21.employees if e.cardholder_name == "Ofori, Esi"]
    assert len(ofori) == 1 and len(ofori[0].block_ids) == 2
    assert out21.summary["Duplicate records ignored"] == 1


def test_event_date_not_report_date(synthetic_pdf, settings):
    o = process_pdf(synthetic_pdf, settings, dates=[D20])
    assert names(o.analysis.late) == ["Lartey, Kojo"]            # 18:00 entry on the 20th
    kinds = {(r["Cardholder Name"], r["Exception Type"]) for r in o.analysis.exceptions}
    assert ("Lartey, Kojo", "Overnight Session") in kinds       # exit on the 21st
    assert "Lartey, Kojo" not in names(o.analysis.early)


def test_overnight_worker_gets_review_note(out21):
    # Lartey was on site overnight; his 21st session is normal, but no false overlap is raised
    kinds = {(r["Cardholder Name"], r["Exception Type"]) for r in out21.analysis.exceptions}
    assert ("Lartey, Kojo", "Overlapping Sessions") not in kinds


def test_all_dates(synthetic_pdf, settings):
    o = process_pdf(synthetic_pdf, settings, all_dates=True)
    assert o.dates == [D20, D21]
    assert {r["Date"] for r in o.analysis.late} == {D20, D21}


def test_custom_thresholds(synthetic_pdf, settings):
    o = process_pdf(synthetic_pdf, settings.with_overrides(late_threshold=time(8, 30), early_threshold=time(16, 0)),
                    dates=[D21])
    assert names(o.analysis.late) == ["Asante, Efua", "Nkrumah, Afua"]
    assert names(o.analysis.early) == ["Asante, Efua"]


def test_roster_confirms_absences(synthetic_pdf, roster_csv, settings):
    o = process_pdf(synthetic_pdf, settings, dates=[D21], roster_path=roster_csv)
    status = {r["Cardholder Name"]: r["Status"] for r in o.analysis.no_entry}
    assert status["Appiah, Abena"] == "Absent - on roster, no entry recorded"
    assert "Ghost Employee" not in status                       # listed separately, not per date
    assert [e.name for e in o.roster_unmatched] == ["Ghost Employee"]
    owusu = next(e for e in o.employees if e.cardholder_name == "Owusu, Ama")
    assert owusu.on_roster and owusu.roster_department == "Finance"     # '456' matched '000456'
    sarpong = next(e for e in o.employees if e.cardholder_name == "Sarpong, Kwabena")
    assert sarpong.on_roster                                               # matched by name


def test_no_dates_with_activity_warns(synthetic_pdf, settings):
    o = process_pdf(synthetic_pdf, settings, dates=[date(2026, 11, 5)])
    assert any("outside the report period" in w for w in o.warnings)


@pytest.mark.parametrize("name,excluded", [
    ("TEMPORARY", True), ("Temporary, Bank Square", True), ("TEMPORARAY STAFF", True),
    ("visitor", True), ("VISTOR 12", True), ("Visitors Pass", True), ("CONTRACTOR", True),
    ("Contracter, ABC", True), ("Victor Mensah", False), ("Asante, Efua", False), ("PENSIONER", False),
])
def test_exclusion_matching(name, excluded):
    assert bool(match_exclusion(name, ("Temporary", "Contractor", "Visitor"), 0.8)) is excluded


def test_exclusion_exact_only():
    assert match_exclusion("TEMPORARAY", ("Temporary",), 1.0) == ""


def test_normalisation():
    assert normalise_name("Zindam, Cynthia") == normalise_name("CYNTHIA  ZINDAM")
    assert normalise_staff_no("002218") == normalise_staff_no("2218.0") == "2218"


def test_on_time(out21):
    # arrived by 08:05 and left at/after 17:00 (Adomako hits both thresholds exactly);
    # Darko arrived on time but has no valid exit -> not on time (Missing Exit instead)
    assert names(out21.analysis.on_time) == ["Adomako, Akua", "Agyeman, Yaa", "Lartey, Kojo",
                                             "Mensah, Kofi", "Ofori, Esi", "Sarpong, Kwabena"]
    every = {r["Cardholder Name"] for rows in (out21.analysis.on_time, out21.analysis.late,
             out21.analysis.early, out21.analysis.no_entry) for r in rows}
    missing_exit = {r["Cardholder Name"] for r in out21.analysis.exceptions if r["Exception Type"] == "Missing Exit"}
    assert len(every | missing_exit) == out21.summary["Employees analysed"]


# ----------------------------------------------------------- cardholder report roster
@pytest.fixture(scope="module")
def out_cards(synthetic_pdf, cardholder_pdf):
    from tap.config import Settings
    return process_pdf(synthetic_pdf, Settings(), dates=[D21], roster_path=cardholder_pdf)


def test_cardholder_roster_matches_by_name_despite_different_staff_numbers(out_cards):
    active = [e for e in out_cards.employees if not e.excluded]
    assert all(e.on_roster for e in active)
    mensah = next(e for e in active if e.cardholder_name == "Mensah, Kofi")
    assert mensah.roster_department == "Finance"   # roster staff no 6123 vs report 000123


def test_reused_staff_number_does_not_cross_match(out_cards):
    # roster 'Ekow Yankey' has staff no 123 = Mensah's 000123, but the names differ
    assert "Ekow Yankey" in [e.name for e in out_cards.roster_unmatched]


def test_roster_visitor_department_excludes_cardholder(out_cards):
    quaye = next(e for e in out_cards.employees if e.cardholder_name == "Quaye, Nii")
    assert quaye.excluded and "Visitor" in quaye.exclusion_reason
    assert "Quaye, Nii" not in names(out_cards.analysis.no_entry)


def test_roster_keyword_exclusions_and_unmatched(out_cards):
    excluded = {e.name for e in out_cards.roster.entries if e.excluded}
    assert {"Nii Quaye", "Bank Square - Temporary"} <= excluded
    unmatched = {e.name for e in out_cards.roster_unmatched}
    assert "Agyabeng Dankwah Kwasi Dompreh-Mensah-Owusu" in unmatched   # wrapped names re-joined
    assert len(out_cards.roster_unmatched) == 2 + 2 + 40           # Ekow, wrapped name, 2 test cards, branch staff
    assert out_cards.analysis.no_entry and all(
        r["Status"] == "Absent - on roster, no entry recorded" for r in out_cards.analysis.no_entry)
