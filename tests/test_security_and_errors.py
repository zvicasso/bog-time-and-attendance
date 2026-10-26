# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
import io
import os
import time
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from tap.parser import parse_lines
from tap.pdf_extract import EncryptedPdfError, ImageBasedPdfError, PdfExtractionError, extract_lines
from tap.roster import RosterError, load_roster
from tap.security import (UploadError, hash_password, safe_filename, validate_pdf_upload,
                          validate_roster_upload, verify_password)
from tap.tempfiles import PREFIX, job_dir, purge_old


@pytest.mark.parametrize("raw,expected", [
    ("..\\..\\Windows\\system32\\evil.pdf", "evil.pdf"),
    ("../../etc/passwd", "passwd"),
    ("report<>:|?.pdf", "report_____.pdf"),
    ("CON.pdf", "upload"),
    ("", "upload"),
])
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_pdf_upload_validation():
    validate_pdf_upload(b"%PDF-1.7 ...", "a.pdf", 1)
    with pytest.raises(UploadError):
        validate_pdf_upload(b"MZ\x90\x00", "a.pdf", 1)          # executable renamed to .pdf
    with pytest.raises(UploadError):
        validate_pdf_upload(b"%PDF-1.7", "a.exe", 1)
    with pytest.raises(UploadError):
        validate_pdf_upload(b"%PDF-" + b"0" * (2 * 1024 * 1024), "a.pdf", 1)
    with pytest.raises(UploadError):
        validate_pdf_upload(b"", "a.pdf", 1)


def test_roster_upload_validation():
    validate_roster_upload(b"Name\nA", "r.csv", 1)
    with pytest.raises(UploadError):
        validate_roster_upload(b"not a zip", "r.xlsx", 1)
    with pytest.raises(UploadError):
        validate_roster_upload(b"x", "r.txt", 1)
    validate_roster_upload(b"%PDF-1.7", "cardholders.pdf", 1)
    with pytest.raises(UploadError):
        validate_roster_upload(b"PK fake", "cardholders.pdf", 1)


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "garbage")


def test_image_only_pdf_is_detected(tmp_path):
    from PIL import Image

    img = tmp_path / "scan.png"
    Image.new("RGB", (200, 200), "white").save(img)
    pdf = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    for _ in range(2):
        c.drawImage(str(img), 50, 50, 500, 700)
        c.showPage()
    c.save()
    with pytest.raises(ImageBasedPdfError):
        list(extract_lines(pdf))


def test_encrypted_pdf(tmp_path):
    pdf = tmp_path / "locked.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter, encrypt="secret")
    c.drawString(72, 700, "Cardholder Name: X")
    c.save()
    with pytest.raises(EncryptedPdfError):
        list(extract_lines(pdf))


def test_corrupt_pdf(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    with pytest.raises(PdfExtractionError):
        list(extract_lines(p))


def test_wrong_kind_of_pdf_reports_error(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.drawString(72, 700, "Invoice number 123")
    c.save()
    r = parse_lines(extract_lines(pdf))
    assert any(i.severity == "ERROR" and i.category == "Format" for i in r.issues)


def test_bytes_source(synthetic_pdf):
    lines = list(extract_lines(Path(synthetic_pdf).read_bytes(), max_pages=3))
    assert any(l.text.startswith("Cardholder Name:") for l in lines)


def test_job_dir_is_removed(tmp_path):
    with job_dir(str(tmp_path)) as d:
        (d / "x.pdf").write_bytes(b"data")
        assert d.exists()
    assert not d.exists()


def test_job_dir_removed_on_error(tmp_path):
    with pytest.raises(RuntimeError):
        with job_dir(str(tmp_path)) as d:
            raise RuntimeError("boom")
    assert not d.exists()


def test_retention_purge(tmp_path):
    old = tmp_path / f"{PREFIX}old"
    old.mkdir()
    past = time.time() - 3 * 3600
    os.utime(old, (past, past))
    fresh = tmp_path / f"{PREFIX}new"
    fresh.mkdir()
    assert purge_old(str(tmp_path), 60) == 1
    assert not old.exists() and fresh.exists()


def test_roster_errors(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("Colour,Size\nred,1\n")
    with pytest.raises(RosterError):
        load_roster(p)


def test_roster_xlsx(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Surname", "First Name", "Staff No"])
    ws.append(["Mensah", "Kofi", "000123"])
    p = tmp_path / "r.xlsx"
    wb.save(p)
    r = load_roster(p)
    assert r.entries[0].name == "Mensah, Kofi" and r.entries[0].staff_no == "000123"


def test_cardholder_report_parser(cardholder_pdf):
    from tap.cardholder_report import parse_cardholder_report

    rep = parse_cardholder_report(cardholder_pdf)
    assert rep.site_name == "Test Site HQ" and rep.warnings == []
    assert len(rep.records) == 59
    first = rep.records[0]
    assert (first.first_name, first.last_name, first.staff_no, first.department) == ("Kofi", "Mensah", "6123", "Finance")
    yaw = next(r for r in rep.records if r.first_name == "Yaw")
    assert yaw.department == "Information and Communication Technology"   # wrapped department
    assert {r.page for r in rep.records} >= {1, 2, 3}


def test_attendance_pdf_rejected_as_roster(synthetic_pdf, tmp_path):
    import shutil
    p = tmp_path / "roster.pdf"
    shutil.copy(synthetic_pdf, p)
    with pytest.raises(RosterError):
        load_roster(p)
