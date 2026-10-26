# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Time & Attendance Processor - browser interface (Streamlit).

Start with start_app.bat (Windows) or:  python -m streamlit run app.py
"""

from __future__ import annotations

import logging
import time as _time
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from tap import __version__, branding
from tap.config import load_settings
from tap.logging_setup import setup_logging
from tap.pdf_extract import PdfExtractionError
from tap.excel_source import ExcelSourceError
from tap.pipeline import peek_report, process_report
from tap.roster import RosterError
from tap.security import (UploadError, safe_filename, validate_report_upload,
                          validate_roster_upload, verify_password)
from tap.tempfiles import job_dir, purge_old

st.set_page_config(page_title=f"{branding.PRODUCT} | {branding.COMPANY_SHORT}",
                   page_icon=str(branding.ICON) if branding.ICON.exists() else "🕘", layout="wide",
                   menu_items={"About": f"{branding.PRODUCT} v{__version__}  \n"
                                        f"Developed by {branding.AUTHOR}  \n{branding.COPYRIGHT}"})

SETTINGS = load_settings()
setup_logging(SETTINGS.log_path, SETTINGS.log_level)
log = logging.getLogger("tap.app")

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1280px;}
  .tap-sub {color: #4d6470; margin-top: -0.6rem; margin-bottom: 1.2rem;}
  .tap-step {font-weight: 600; color: #06364A; margin: 0.6rem 0 0.2rem 0;
             border-left: 4px solid #63CDC5; padding-left: 0.5rem;}
  h1 {color: #06364A;}
  div[data-testid="stMetricValue"] {font-size: 1.7rem; color: #06364A;}
  .tap-footer {margin-top: 2.5rem; padding-top: 0.8rem; border-top: 1px solid #DAFFFB;
               color: #6b7f88; font-size: 0.8rem; display: flex; justify-content: space-between;}
  .tap-footer b {color: #06364A;}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- auth
def require_login() -> None:
    if not SETTINGS.auth_enabled:
        return
    if st.session_state.get("authenticated"):
        return
    if not SETTINGS.password_hash:
        st.error("Sign-in is enabled but no password hash is configured. "
                 "Ask the administrator to set password_hash in config\\settings.toml.")
        st.stop()
    attempts = st.session_state.get("login_attempts", 0)
    if branding.LOGO_HORIZONTAL.exists():
        st.image(str(branding.LOGO_HORIZONTAL), width=240)
    st.title(branding.PRODUCT)
    if attempts >= SETTINGS.max_login_attempts:
        st.error("Too many failed attempts. Close the browser tab and try again later.")
        st.stop()
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in", type="primary")
    if ok:
        if verify_password(pw, SETTINGS.password_hash):
            st.session_state.authenticated = True
            log.info("sign-in succeeded")
            st.rerun()
        else:
            st.session_state.login_attempts = attempts + 1
            log.warning("sign-in failed (attempt %d)", attempts + 1)
            _time.sleep(1.5)
            st.error("Incorrect password.")
    st.stop()


require_login()

if "startup_purge" not in st.session_state:
    purge_old(SETTINGS.temp_dir, SETTINGS.retention_minutes)
    st.session_state.startup_purge = True


# ----------------------------------------------------------------------- sidebar
with st.sidebar:
    if branding.LOGO_HORIZONTAL.exists():
        st.image(str(branding.LOGO_HORIZONTAL), width=210)
    st.header("Processing options")
    late_t = st.time_input("Late if first entry is after", SETTINGS.late_threshold, step=60)
    early_t = st.time_input("Early if last exit is before", SETTINGS.early_threshold, step=60)
    kw_text = st.text_area("Exclude cardholder names containing (one per line)",
                           "\n".join(SETTINGS.exclude_keywords), height=110,
                           help="Case-insensitive. Minor misspellings (e.g. TEMPORARAY) are also matched.")
    fuzzy = st.toggle("Match minor misspellings", value=SETTINGS.fuzzy_threshold < 1.0)
    doors_text = st.text_area("Treat badges used at these doors as visitors (one per line)",
                              "\n".join(SETTINGS.visitor_doors), height=80,
                              help="Visitor-management workstations, e.g. 'VISITORS-MANAGE'. Matched anywhere "
                                   "in the door/reader name, case-insensitive.")
    max_hours = st.number_input("Flag sessions longer than (hours)", 4.0, 48.0,
                                float(SETTINGS.max_session_hours), step=1.0)
    st.divider()
    st.caption(f"Version {__version__}. Files are processed on this server only and "
               f"temporary copies are deleted after processing.")
    st.caption(f"Developed by **{branding.AUTHOR}**  \n{branding.COPYRIGHT}")
    if SETTINGS.auth_enabled and st.button("Sign out"):
        st.session_state.clear()
        st.rerun()

keywords = tuple(k.strip() for k in kw_text.splitlines() if k.strip())
run_settings = SETTINGS.with_overrides(
    late_threshold=late_t, early_threshold=early_t, exclude_keywords=keywords,
    fuzzy_threshold=(SETTINGS.fuzzy_threshold if SETTINGS.fuzzy_threshold < 1.0 else 0.8) if fuzzy else 1.0,
    max_session_hours=max_hours,
    visitor_doors=tuple(d.strip() for d in doors_text.splitlines() if d.strip()))


# -------------------------------------------------------------------------- main
st.title("Time & Attendance Processor")
st.markdown('<div class="tap-sub">Upload a Time and Attendance report - the access-control system\'s '
            'PDF summary report or the Excel/CSV export - and download a classified Excel workbook.</div>',
            unsafe_allow_html=True)

col_a, col_b = st.columns([3, 2], gap="large")
with col_a:
    st.markdown('<div class="tap-step">1. Attendance report (PDF, Excel or CSV)</div>', unsafe_allow_html=True)
    pdf_file = st.file_uploader("Time and Attendance report", type=["pdf", "xlsx", "csv"],
                                label_visibility="collapsed", max_upload_size=SETTINGS.max_pdf_mb,
                                help="PDF: Time and Attendance Summary Report from the access-control client. "
                                     "Excel/CSV: export with Staff No, Cardholder Name, Department, Entry/Exit "
                                     "Door, Entry/Exit Date/Time, Exception and Time on Site columns.")
    meta = None
    if pdf_file is not None:
        data = pdf_file.getvalue()
        try:
            validate_report_upload(data, pdf_file.name, SETTINGS.max_pdf_mb)
            cache_key = (pdf_file.name, len(data))
            if st.session_state.get("peek_key") != cache_key:
                st.session_state.peek = peek_report(data, run_settings, filename=pdf_file.name)
                st.session_state.peek_key = cache_key
            meta, total_units = st.session_state.peek
            period = (f"{meta.start:%d/%m/%Y} – {meta.end:%d/%m/%Y}" if meta.start and meta.end
                      else "not stated in report")
            unit = "pages" if meta.source_format == "PDF" else "rows"
            st.success(f"**{meta.site_name or meta.source_format + ' export'}** · {total_units:,} {unit} · "
                       f"period {period} · ID field: {meta.personal_field or 'n/a'}")
        except (UploadError, PdfExtractionError, ExcelSourceError) as exc:
            st.error(str(exc))
            pdf_file = None

with col_b:
    st.markdown('<div class="tap-step">2. Reporting date</div>', unsafe_allow_html=True)
    default_d = meta.end.date() if meta and meta.end else date.today()
    mode = st.radio("Dates", ["Single date", "Every date in report period"], horizontal=True,
                    label_visibility="collapsed")
    target = None
    if mode == "Single date":
        target = st.date_input("Target date", default_d, format="DD/MM/YYYY",
                               label_visibility="collapsed")
        if meta and meta.start and meta.end and not (meta.start.date() <= target <= meta.end.date()):
            st.warning("This date is outside the report period.")

    st.markdown('<div class="tap-step">3. Employee roster (optional)</div>', unsafe_allow_html=True)
    roster_file = st.file_uploader("Roster", type=["pdf", "xlsx", "csv"], label_visibility="collapsed",
                                   help="The access-control system's Cardholder Summary Report (PDF), "
                                        "or an Excel/CSV list with 'Staff No' and/or 'Name' columns. "
                                        "Needed to confirm absences and to add departments.",
                                   max_upload_size=SETTINGS.max_roster_mb)
    if roster_file is None:
        st.caption("Without a roster, staff missing from the PDF cannot be identified as absent.")

st.write("")
go = st.button("Process Attendance Report", type="primary", disabled=pdf_file is None,
               width="stretch")

if go and pdf_file is not None:
    job = uuid.uuid4().hex[:8]
    log.info("job %s: start (pdf %.1f MB, roster=%s)", job, pdf_file.size / 1e6, roster_file is not None)
    bar = st.progress(0.0, text="Starting...")
    try:
        with job_dir(SETTINGS.temp_dir) as work:
            pdf_path = work / safe_filename(pdf_file.name, "report" + Path(pdf_file.name).suffix.lower())
            pdf_path.write_bytes(pdf_file.getvalue())
            roster_path = None
            if roster_file is not None:
                rdata = roster_file.getvalue()
                validate_roster_upload(rdata, roster_file.name, SETTINGS.max_roster_mb)
                roster_path = work / safe_filename(roster_file.name, "roster.xlsx")
                roster_path.write_bytes(rdata)
            outcome = process_report(
                pdf_path, run_settings, source_name=safe_filename(pdf_file.name, "report.pdf"),
                dates=[target] if target else None, all_dates=target is None,
                roster_path=roster_path,
                progress=lambda f, m: bar.progress(min(f, 1.0), text=m))
        bar.empty()
        st.session_state.outcome = outcome
        log.info("job %s: completed in %.1fs", job, outcome.elapsed_s)
    except (UploadError, PdfExtractionError, RosterError, ExcelSourceError) as exc:
        bar.empty()
        st.session_state.pop("outcome", None)
        log.warning("job %s: rejected (%s)", job, type(exc).__name__)
        st.error(str(exc))
    except Exception:
        bar.empty()
        st.session_state.pop("outcome", None)
        log.exception("job %s: unexpected failure", job)
        st.error("Processing failed because of an unexpected error. The technical details have been "
                 "written to the application log (logs\\app.log). No partial results were produced.")
    finally:
        purge_old(SETTINGS.temp_dir, SETTINGS.retention_minutes)


# ----------------------------------------------------------------------- results
o = st.session_state.get("outcome")
if o is not None:
    st.divider()
    s = o.summary
    head_l, head_r = st.columns([3, 1])
    with head_l:
        st.subheader("Results")
        st.caption(f"{s['Source file']} · reporting date(s) {s['Reporting date(s)']} · "
                   f"processed in {o.elapsed_s:g} s")
    with head_r:
        if st.button("Clear results", width="stretch",
                     help="Removes the results and employee data from this browser session."):
            st.session_state.pop("outcome", None)
            st.rerun()

    if o.has_errors:
        st.error(f"**{s['Processing status']}**")
    elif o.warnings:
        st.warning(f"**{s['Processing status']}**")
    else:
        st.success(f"**{s['Processing status']}**")

    m = st.columns(4)
    m[0].metric("Records extracted", f"{s['Total records extracted']:,}")
    m[1].metric("Unique cardholders", f"{s['Unique cardholders']:,}")
    m[2].metric("Excluded cardholders", f"{s['Excluded cardholders']:,}",
                help=f"{s['Excluded records']} records excluded by name keywords")
    m[3].metric("Employees analysed", f"{s['Employees analysed']:,}")
    m = st.columns(5)
    m[0].metric("On time", f"{s['On time (arrived and left on time)']:,}",
                help="Arrived by the late threshold and left at or after the departure threshold.")
    m[1].metric("Late arrivals", f"{s['Late arrivals']:,}")
    m[2].metric("Early departures", f"{s['Early departures']:,}")
    m[3].metric("No recorded entry", f"{s['No recorded entry']:,}",
                help="Not a confirmed absence list unless a roster was supplied.")
    m[4].metric("Attendance exceptions", f"{s['Attendance exceptions (rows)']:,}")

    d1, d2, _ = st.columns([2, 2, 3])
    stamp = o.dates[0].strftime("%Y-%m-%d") if len(o.dates) == 1 else "all-dates"
    d1.download_button("⬇ Download Excel workbook", o.workbook, file_name=f"Attendance_Analysis_{stamp}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary", width="stretch", on_click="ignore")
    d2.download_button("Download validation report", o.validation_report().encode("utf-8"),
                       file_name=f"Validation_Report_{stamp}.txt", mime="text/plain", on_click="ignore",
                       width="stretch")

    if o.warnings:
        with st.expander(f"Warnings requiring review ({len(o.warnings)})", expanded=True):
            for w in o.warnings[:100]:
                st.markdown(f"- {w}")
            if len(o.warnings) > 100:
                st.caption("More in the Validation sheet / validation report.")
    if o.exception_counts:
        with st.expander("Exceptions by type"):
            st.dataframe(pd.DataFrame(list(o.exception_counts.items()), columns=["Exception type", "Count"]),
                         hide_index=True)

    def _fmt(v, pattern):
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return ""
        return v.strftime(pattern) if hasattr(v, "strftime") else str(v)

    def frame(rows):
        df = pd.DataFrame(rows).drop(columns=["_key"], errors="ignore")
        if "Card Number(s)" in df and not df["Card Number(s)"].astype(str).str.strip().any():
            df = df.drop(columns=["Card Number(s)"])   # spreadsheet sources have no card numbers
        for col, pattern in (("Date", "%d/%m/%Y"), ("First Entry", "%d/%m/%Y %H:%M:%S"),
                             ("Last Exit", "%d/%m/%Y %H:%M:%S"), ("Late Threshold", "%H:%M"),
                             ("Departure Threshold", "%H:%M")):
            if col in df:
                df[col] = df[col].map(lambda v, p=pattern: _fmt(v, p))
        if "Time on Site" in df:
            df["Time on Site"] = df["Time on Site"].map(
                lambda td: "" if pd.isna(td) else f"{int(td.total_seconds()) // 3600}:"
                f"{int(td.total_seconds()) % 3600 // 60:02d}")
        return df

    names = ["On Time", "Late Arrivals", "Early Departures", "No Recorded Entry", "Attendance Exceptions"]
    datasets = [o.analysis.on_time, o.analysis.late, o.analysis.early, o.analysis.no_entry,
                o.analysis.exceptions]
    empties = ["No employees arrived and left on time.", "No late arrivals.", "No early departures.",
               "No cardholders without an entry.", "No exceptions."]
    if o.roster is not None:
        names.append(f"Roster Not In Report ({len(o.roster_unmatched):,})")
        datasets.append([{"Name (roster)": e.name, "Staff No": e.staff_no, "Department": e.department,
                          "Roster Reference": o.roster.ref(e)} for e in o.roster_unmatched])
        empties.append("Every roster employee appears in the attendance report.")
    tabs = st.tabs(names)
    for tab, rows, empty in zip(tabs, datasets, empties):
        with tab:
            if rows:
                st.dataframe(frame(rows), hide_index=True, width="stretch", height=380)
            else:
                st.info(empty)
    for note in o.interpretation_notes:
        st.caption("• " + note)

st.markdown(f'''<div class="tap-footer"><span>{branding.PRODUCT} v{__version__}</span>
<span>Developed by <b>{branding.AUTHOR}</b> · {branding.COPYRIGHT}</span></div>''', unsafe_allow_html=True)
