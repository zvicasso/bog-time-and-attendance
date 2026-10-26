# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Generate synthetic Time and Attendance Summary Report PDFs for testing.

The layout mirrors the Bank of Ghana New HQ report (Gallagher-style summary):
column positions, wrapped clock names, wrapped am/pm, 'Insuff. D.' rows,
'Report End Date/Time' exits, repeated headers and sections split across pages.
All names and numbers are fictional.

Run directly to (re)create tests/data/synthetic_report.pdf and sample_roster.csv:
    python tests/synthetic.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = letter  # 612 x 792, same as the real report
X_LABEL, X_VALUE = 72.0, 180.2
X_COLS = (72.1, 177.4, 282.5, 387.7)
X_RIGHT = 536.4
LINE = 10.6
TOP, BOTTOM = 72.0, 700.0
CLOCKS = ["PDM-UG-SP.GT.U5-RIN", "PDM-UG-SP.GT.T3-ROUT", "PDM-UG-SP.GT.U1-ROUT", "PDM-UG-SP.GT.T5-RIN"]


@dataclass
class Row:
    entry: datetime | None = None
    exit: datetime | None = None
    entry_clock: str = "PDM-UG-SP.GT.U5-RIN"
    exit_clock: str = "PDM-UG-SP.GT.U1-ROUT"
    report_end: bool = False
    insufficient: bool = False
    worked: str | None = None  # override 'Time Worked' text


@dataclass
class Section:
    name: str
    staff_no: str = ""
    cards: str = "1234567890"
    rows: list[Row] = field(default_factory=list)


def _fmt_dt(dt: datetime) -> tuple[str, str]:
    """Return (line1, wrapped line2) like the real report: two-digit hours push am/pm down."""
    h12 = dt.hour % 12 or 12
    ap = "am" if dt.hour < 12 else "pm"
    base = f"{dt:%d/%m/%Y} {h12}:{dt:%M:%S}"
    return (base, ap) if h12 >= 10 else (f"{base} {ap}", "")


def _split_clock(name: str) -> tuple[str, str]:
    if "-" in name and name.rsplit("-", 1)[1] in ("RIN", "ROUT"):
        a, b = name.rsplit("-", 1)
        return a + "-", b
    return name, ""


def _dur(td_s: int) -> str:
    return f"{td_s // 3600}:{(td_s % 3600) // 60:02d}:{td_s % 60:02d}"


class _Writer:
    def __init__(self, path, start: datetime, end: datetime, generated="Monday, 26 October 2026 9:00:00 am"):
        self.c = canvas.Canvas(str(path), pagesize=letter)
        self.generated = generated
        self.page = 1
        self.y = TOP
        self.pages_text: list[tuple] = []
        self.start, self.end = start, end
        self.total_pages_placeholder = "{N}"

    def text(self, x, top, s, size=10, right=False):
        self.c.setFont("Helvetica", size)
        y = PAGE_H - top - size * 0.8
        (self.c.drawRightString if right else self.c.drawString)(x, y, s)

    def footer(self):
        self.text(72, 745, f"Generated {self.generated}", 9)
        self.text(X_RIGHT, 745, f"Page {self.page} of {self.total_pages_placeholder}", 9, right=True)

    def new_page(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = TOP

    def ensure(self, lines: int):
        if self.y + lines * LINE > BOTTOM:
            self.new_page()
            return True
        return False


def build_report(path: Path | str, sections: list[Section], start: datetime, end: datetime,
                 site="Test Site HQ", page_header_every_page=False, id_label="Staff Card No") -> Path:
    path = Path(path)
    # Two passes so the footer can say "Page X of N"
    n_pages = _render(path, sections, start, end, site, "?", page_header_every_page, id_label)
    _render(path, sections, start, end, site, str(n_pages), page_header_every_page, id_label)
    return path


def _render(path, sections, start, end, site, total, hdr_every, id_label="Staff Card No") -> int:
    w = _Writer(path, start, end)
    w.total_pages_placeholder = total
    # --- page 1: report parameters
    for label, value in [("Report Type:", "Time and Attendance Summary Report"),
                         ("Operator:", "System Operator on TEST-SVR"), ("Site Name:", site),
                         ("Report Resolution:", ""), ("Cardholders:", "Selected Cardholders"),
                         ("Personal Data Field:", id_label), ("Report sorted on:", "Cardholder Name"),
                         ("Clock Configuration:", "Combined entry and exit time clocks"),
                         ("Time Clocks:", CLOCKS[0])]:
        w.text(X_LABEL, w.y, label)
        w.text(X_VALUE, w.y, value)
        w.y += 12
    for ck in CLOCKS[1:]:
        w.text(X_VALUE, w.y, ck)
        w.y += 12
    w.new_page()
    w.text(X_LABEL, w.y, f"Report Start Date/Time:{start:%A, %d %B %Y} {start.hour % 12 or 12}:{start:%M:%S} "
                         f"{'am' if start.hour < 12 else 'pm'}")
    w.y += 12
    w.text(X_LABEL, w.y, f"Report End Date/Time:{end:%A, %d %B %Y} {end.hour % 12 or 12}:{end:%M:%S} "
                         f"{'am' if end.hour < 12 else 'pm'}")
    w.y += 12
    w.text(X_LABEL, w.y, "Grace Time: 120 seconds")
    w.y += 12
    w.text(X_LABEL, w.y, "Assume exit within: 24 hours")
    w.new_page()

    def page_header():
        if hdr_every:
            for label, value in [("Report Type:", "Time and Attendance Summary Report"),
                                 ("Operator:", "System Operator on TEST-SVR"), ("Site Name:", site)]:
                w.text(X_LABEL, w.y, label)
                w.text(X_VALUE, w.y, value)
                w.y += 12
            w.y += 24

    def table_header():
        w.text(X_COLS[0], w.y, "Entry Clock Name", 9.5)
        w.text(X_COLS[1], w.y, "First Entry Date/Time", 9.5)
        w.text(X_COLS[2], w.y, "Exit Clock Name", 9.5)
        w.text(X_COLS[3], w.y, "Last Exit Date/Time", 9.5)
        w.text(X_RIGHT, w.y, "Time", 9.5, right=True)
        w.y += LINE
        w.text(X_RIGHT, w.y, "Worked", 9.5, right=True)
        w.y += LINE * 1.0

    page_header()
    for sec in sections:
        w.ensure(7)
        if w.y == TOP:
            page_header()
        for label, value in [("Cardholder Name:", sec.name), (f"{id_label}:", sec.staff_no),
                             ("Card Number(s):", sec.cards)]:
            w.text(X_LABEL, w.y, label)
            if value:
                w.text(X_VALUE, w.y, value)
            w.y += 11
        w.y += 12
        table_header()
        total = 0
        for r in sec.rows:
            if w.ensure(2):
                page_header()
                table_header()  # header repeats when a section continues on a new page
            l2 = {}
            if r.entry:
                a, b = _split_clock(r.entry_clock)
                w.text(X_COLS[0], w.y, a, 9.5)
                l2[0] = b
                a, b = _fmt_dt(r.entry)
                w.text(X_COLS[1], w.y, a, 9.5)
                l2[1] = b
            if r.report_end:
                w.text(X_COLS[2], w.y, "Report End Date/Time", 9.5)
                a, b = _fmt_dt(r.exit)
                w.text(X_COLS[3], w.y, a, 9.5)
                l2[3] = b
            elif r.exit:
                a, b = _split_clock(r.exit_clock)
                w.text(X_COLS[2], w.y, a, 9.5)
                l2[2] = b
                a, b = _fmt_dt(r.exit)
                w.text(X_COLS[3], w.y, a, 9.5)
                l2[3] = b
            if r.insufficient:
                worked = "Insuff. D."
            elif r.worked:
                worked = r.worked
            else:
                secs = int((r.exit - r.entry).total_seconds()) if r.entry and r.exit else 0
                worked = _dur(secs)
            if not r.insufficient:
                from tap.parser import parse_duration
                total += int(parse_duration(worked).total_seconds())
            w.text(X_RIGHT, w.y, worked, 9.5, right=True)
            w.y += LINE
            if any(l2.values()):
                for i, t in l2.items():
                    if t:
                        w.text(X_COLS[i], w.y, t, 9.5)
                w.y += LINE
        w.ensure(2)
        w.y += 8
        w.text(275.2, w.y, f"Total Working Time (Excluding Insufficient Data) : {_dur(total)}", 9.5)
        w.y += 26
    w.ensure(2)
    w.text(X_LABEL, w.y, "End of Time and Attendance Summary Report")
    w.footer()
    w.c.save()
    return w.page


# ---------------------------------------------------------------------------
# Canonical synthetic data set used by the tests
D20, D21 = datetime(2026, 10, 20), datetime(2026, 10, 21)


def t(day: datetime, hh: int, mm: int, ss: int = 0) -> datetime:
    return day.replace(hour=hh, minute=mm, second=ss)


def standard_sections() -> list[Section]:
    S = Section
    R = Row
    secs = [
        S("Mensah, Kofi", "000123", "4001001001", [R(t(D20, 7, 40), t(D20, 17, 20)), R(t(D21, 7, 45), t(D21, 17, 30))]),
        S("Owusu, Ama", "000456", "4001001002", [R(t(D21, 8, 20, 15), t(D21, 17, 5))]),
        S("Boateng, Yaw", "001789", "4001001003", [R(t(D21, 7, 55), t(D21, 16, 10))]),
        S("Asante, Efua", "002001", "4001001004", [R(t(D21, 9, 0), t(D21, 15, 0))]),
        S("Darko, Kwame", "002002", "4001001005", [R(t(D21, 7, 50), t(D21, 23, 59, 59), report_end=True, worked="4:10:00")]),
        S("Temporary, Bank Square", "240001", "1100000000000001", [R(t(D21, 9, 30), t(D21, 12, 0))]),
        S("TEMPORARAY STAFF", "240002", "1100000000000002", [R(t(D21, 10, 0), t(D21, 11, 0))]),
        S("VISITOR", "240003", "1100000000000003", [R(insufficient=True)]),
        S("Contractor", "700021", "1171793560670864", []),
        S("Appiah, Abena", "003003", "4001001006", [R(t(D20, 7, 30), t(D20, 17, 15))]),
        S("Quaye, Nii", "003004", "4001001007", [R(insufficient=True)]),
        S("Ofori, Esi", "003005", "4001001008", [R(t(D21, 7, 58), t(D21, 17, 2))]),
        S("Lartey, Kojo", "003006", "4001001009", [R(t(D20, 18, 0), t(D21, 6, 30)), R(t(D21, 7, 50), t(D21, 17, 10))]),
        S("Nkrumah, Afua", "003007", "4001001010", [R(t(D21, 12, 15), t(D21, 18, 0))]),
        S("Adomako, Akua", "003008", "4001001011", [R(t(D21, 8, 5, 0), t(D21, 17, 0, 0))]),
        S("Sarpong, Kwabena", "", "4001001012, 4001001013", [R(t(D21, 7, 0), t(D21, 17, 45))]),
        S("Agyeman, Yaa", "003010", "4001001014", [R(t(D21, 6, 0), t(D21, 23, 30))]),
        S("Ofori, Esi", "003005", "4001001008", [R(t(D21, 7, 58), t(D21, 17, 2))]),  # repeated section
    ]
    # A long section that is forced across a page break
    many = [R(t(D20.replace(day=d), 7, 0), t(D20.replace(day=d), 17, 30)) for d in range(5, 21)]
    secs.insert(12, S("Long, Section", "003099", "4001001099", many + [R(t(D21, 8, 30), t(D21, 17, 30))]))
    return secs


def write_fixtures(out_dir: Path) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = build_report(out_dir / "synthetic_report.pdf", standard_sections(), D20, t(D21, 23, 59, 59),
                       page_header_every_page=True)
    roster = out_dir / "sample_roster.csv"
    roster.write_text(
        "Staff Card No,Employee Name,Department\n"
        "000123,Kofi Mensah,Finance\n"
        "456,Ama Owusu,Finance\n"          # leading zeros lost (as Excel often does)
        "001789,Yaw Boateng,IT\n"
        "002001,Efua Asante,IT\n"
        "002002,Kwame Darko,Security\n"
        "003003,Abena Appiah,HR\n"
        "003004,Nii Quaye,HR\n"
        "003005,Esi Ofori,Legal\n"
        "003006,Kojo Lartey,Security\n"
        "003007,Afua Nkrumah,Legal\n"
        "003008,Akua Adomako,Finance\n"
        ",Kwabena Sarpong,Facilities\n"
        "003010,Yaa Agyeman,Facilities\n"
        "003099,Section Long,Facilities\n"
        "009999,Ghost Employee,Audit\n",   # on roster, not in report
        encoding="utf-8")
    cards = build_cardholder_report(out_dir / "sample_cardholders.pdf", standard_cardholders())
    build_excel_export(out_dir / "sample_export.xlsx")
    build_report(out_dir / "synthetic_report_staffno.pdf", standard_sections(), D20, t(D21, 23, 59, 59),
                 id_label="Staff No")
    return pdf, roster, cards


# ---------------------------------------------------------------------------
# Cardholder Summary Report (roster) - same layout as the access-control export
CH_X = (72.1, 165.8, 259.4, 353.0, 445.7)
CH_W = (84.0, 88.0, 88.0, 86.0, 95.0)   # wrap widths per column


def _wrap(text: str, width: float, size: float = 9.5) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and stringWidth(trial, "Helvetica", size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def build_cardholder_report(path: Path | str, people: list[tuple[str, str, str, str, list[str]]],
                            site="Test Site HQ") -> Path:
    """people: (first name, last name, staff no, department, [access groups])."""
    path = Path(path)
    c = canvas.Canvas(str(path), pagesize=letter)
    page, y = 1, TOP

    def text(x, top, s, size=9.5):
        c.setFont("Helvetica", size)
        c.drawString(x, PAGE_H - top - size * 0.8, s)

    def footer():
        text(72, 745, "Generated Monday, 26 October 2026 9:00:00 am", 9)
        text(470, 745, f"Page {page}", 9)

    for label, value in [("Report Type:", "Cardholder Summary Report"),
                         ("Operator:", "System Operator on TEST-SVR"), ("Site Name:", site)]:
        text(72, y, label, 10)
        text(187, y, value, 10)
        y += 12
    text(72, y, "Operator's Comment:", 10)
    y += 35
    for x, h in zip(CH_X, ["First Name", "Last Name", "Access Group", "Staff No", "Department"]):
        text(x, y, h)
    y += 11
    for first, last, staff, dept, groups in people:
        cols = [_wrap(first, CH_W[0]), _wrap(last, CH_W[1]),
                [ln for g in ["Suprema Access Group"] + groups for ln in _wrap(g, CH_W[2])],
                _wrap(staff, CH_W[3]), _wrap(dept, CH_W[4])]
        n = max(len(col) for col in cols)
        if y + n * 11 > BOTTOM:
            footer()
            c.showPage()
            page, y = page + 1, TOP
        for i in range(n):
            for x, col in zip(CH_X, cols):
                if i < len(col) and col[i]:
                    text(x, y + i * 11, col[i])
        y += n * 11
    text(72, y + 4, "End of Cardholder Report", 10)
    footer()
    c.save()
    return path


def standard_cardholders():
    g = ["GEN-1", "TW-3F: ICT - GEN"]
    return [
        ("Kofi", "Mensah", "6123", "Finance", g), ("Ama", "Owusu", "6456", "Finance", g),
        ("Yaw", "Boateng", "6789", "Information and Communication Technology", g),
        ("Efua", "Asante", "7001", "Information and Communication Technology", g),
        ("Kwame", "Darko", "7002", "Security", ["GEN-1", "SEC-A"]),
        ("Abena", "Appiah", "7003", "Human Resource", g),
        ("Nii", "Quaye", "", "Visitor 12", ["GEN-1"]),                 # visitor card -> excluded
        ("Esi", "Ofori", "7005", "Legal", g), ("Kojo", "Lartey", "7006", "Security", g),
        ("Afua", "Nkrumah", "7007", "Legal", g), ("Akua", "Adomako", "7008", "Finance", g),
        ("Kwabena", "Sarpong", "7009", "Estate & Projects", g),
        ("Yaa", "Agyeman", "7010", "Estate & Projects", g),
        ("Section", "Long", "7099", "Estate & Projects", g),
        ("Agyabeng Dankwah Kwasi", "Dompreh-Mensah-Owusu", "7111", "Kumasi", g),  # wrapped names
        ("Ekow", "Yankey", "123", "Takoradi", g),                       # reuses Mensah's staff no
        ("Bank Square -", "Temporary", "000019", "Temporary", ["GEN-1"]),
        ("Cardholder", "1", "", "", []), ("Cardholder", "2", "", "", []),
    ] + [(f"Branch{i}", f"Staff{i}", str(8000 + i), "Kumasi", g) for i in range(40)]  # forces page breaks



# ---------------------------------------------------------------------------
# Simple Excel export (one row per person per day)
def build_excel_export(path: Path | str, typed_cell_row: bool = True) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Page 1"
    ws.append(["Staff No", "Cardholder Name", "Department", "Entry Door", "Entry Date/Time",
               "Exit Door", "Exit Date/Time", "Exception", "Time on Site"])

    def txt(dt):
        h12 = dt.hour % 12 or 12
        return f"{dt:%d/%m/%Y} {h12}:{dt:%M:%S} {'am' if dt.hour < 12 else 'pm'}"

    def dur(a, b):
        t = int((b - a).total_seconds())
        return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"

    rows = [
        ("6123", "Mensah, Kofi", "Finance", t(D20, 7, 45), t(D20, 17, 30), ""),
        ("6456", "Owusu, Ama", "Finance", t(D20, 8, 20, 15), t(D20, 17, 5), ""),
        ("6789", "Boateng, Yaw", "ICT", t(D20, 7, 55), t(D20, 16, 10), ""),
        ("7001", "Asante, Efua", "ICT", t(D20, 9, 0), t(D20, 15, 0), ""),
        ("7002", "Darko, Kwame", "Security", t(D20, 7, 50), None, "X_24"),
        ("", "019, Temporary", "", t(D20, 7, 0), t(D20, 15, 0), ""),
        ("", "McConaghy, Peter", "Visitor", t(D20, 9, 0), t(D20, 11, 0), ""),
        ("7008", "Adomako, Akua", "Finance", t(D20, 8, 5, 0), t(D20, 17, 0, 0), ""),
    ]
    for staff, name, dept, a, b, exc in rows:
        if exc == "X_24":
            ws.append([staff, name, dept, "EXT-SEN-STF.ENTRY", txt(a), None, txt(t(D21, 0, 0)), "X_24", None])
        else:
            ws.append([staff, name, dept, "PDM-UG-SP.GT.T 3 & 4", txt(a), "EXT-SEN-TURNSTILE", txt(b), None, dur(a, b)])
    # A visitor badge issued at the visitor-management workstation (no staff no, no department)
    ws.append(["", "TEYE, ABRAHAM", "", "FT Workstation on VISITORS-MANAGE", txt(t(D20, 8, 35)), None,
               txt(t(D21, 0, 0)), "X_24", None])
    if typed_cell_row:
        # A hand-edited row: typed datetimes (not text) and Time on Site that no longer matches
        ws.append(["6055", "Adams, Jonas", "Legal", "PDM-UG-SP.GT.U 5 & 6", t(D20, 7, 15, 20),
                   "PDM-UG-SP.GT.U 3 & 4", t(D20, 17, 31, 17), None, "09:15:57"])
    wb.save(path)
    return Path(path)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    print("wrote", *write_fixtures(Path(__file__).resolve().parent / "data"))
