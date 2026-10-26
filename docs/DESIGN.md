# Design decisions, limitations and future enhancements

*Time & Attendance Processor - developed by Isheanesu Zvikaramba, Zvicasso Technologies (Pty) Ltd*

## 1. What the source report looks like

The input is the *Time and Attendance Summary Report* from the site's access-control system. The 21-10-2026 sample is 451 pages and has 1,953 cardholder sections. Each section lists:

- a header: Cardholder Name, Staff Card No, Card Number(s);
- one row per attendance period: entry clock, first entry, exit clock, last exit, time worked;
- a *Total Working Time* line.

Features of the report that shaped the design:

| Observation | Consequence |
|---|---|
| Long values wrap inside their column: `PDM-UG-SP.GT.U5-` / `RIN`, and `12:01:11` / `pm` | Plain text extraction loses which column a fragment belongs to. **Words are extracted with x/y coordinates and assigned to columns.** Column edges are measured from the header row on each page. |
| `Report End Date/Time` in the exit column (435 rows) | The person had not exited when the report period ended. This is **not a real exit**. Such rows are flagged as *Missing Exit* and never counted as early departures. |
| `Insuff. D.` in Time Worked (138 rows, 93 with no timestamps at all) | These rows are kept as evidence of a card with no usable events. They are not counted as attendance. |
| Sessions from 20/10 that close on 21/10 (255 rows), with Time Worked up to 25+ hours | The report pairs a first entry with the last exit up to 24 h later. Sessions belong to their **entry date**. People still on site overnight are explained in *Other Activity* or *Review Notes* rather than being misreported. |
| Sections split across pages; the column header repeats; page headers repeat | The parser is a state machine that keeps the open section across page boundaries. |
| The same cardholder appears in several sections (e.g. PENSIONER 110026 ×10) | Sections are merged by normalised name + staff number (or card numbers when there is no staff number). Identical rows are de-duplicated. |
| Generic names (`VISITOR` ×289, `TEMPORARY` ×141, `PENSIONER` ×60), misspellings (`TEMPORARAY`) | Keyword exclusion uses token-level fuzzy matching (difflib ratio ≥ 0.80, tokens of 5+ letters). `PENSIONER` is not excluded, because no rule names it, but the app warns about it. |
| The report prints its own section totals | **Built-in reconciliation:** the sum of parsed rows must equal the printed total for every section. On the sample, all 1,953 sections reconcile with zero discrepancies. |

## 2. Key decisions

**Streamlit rather than Flask.** The requirement is a single-screen upload → options → process → download tool for internal staff. Streamlit provides the upload widget, progress bar, tables and download button with about 250 lines of UI code and no HTML templates or JavaScript to maintain. Flask would need a hand-built front end and session handling for the same result. Streamlit's weaker points are covered as follows:
- No built-in authentication. An optional PBKDF2 password gate is implemented, and the docs describe an IIS/Windows-auth reverse proxy for single sign-on.
- WebSocket transport. This works on internal networks and through IIS ARR when WebSockets are enabled.

**pypdfium2 as the primary PDF engine, pdfplumber as the fallback.** On the 451-page sample, pdfplumber took about 55 s and pypdfium2 about 3 s for the same word boxes. pypdfium2 is already a dependency of pdfplumber, so no extra package is needed. The test suite runs the parser on both engines' output and they produce **identical** records. PyMuPDF was not used because of its AGPL licence.

**No OCR in v1.** A scanned report is detected (no text layer plus image objects) and rejected with instructions to export the report digitally. An OCR misread of `8:05` as `8:06` would silently create a false late arrival, and Tesseract/Poppler would add large native dependencies on Windows Server. Digital exports from the access-control system are always available.

**No database.** Each run is stateless. Inputs go to a unique temporary folder that is deleted in a `finally` block, and results stay only in the user's session. This removes data-retention and backup questions for employee data.

**Excel written cell by cell with openpyxl** (not `DataFrame.to_excel`). This gives explicit control over types:
- Staff and card numbers are stored as text, so leading zeros survive and 16-digit card numbers are not rounded by Excel.
- Timestamps are real Excel datetimes.
- Time Worked uses the `[h]:mm:ss` duration format, which shows durations over 24 h correctly.
- Every sheet gets filters, frozen panes and print setup.

**Nothing is silently discarded.**
- Every PDF row appears in Raw Data, including excluded and duplicate rows with the reason, and sections with no rows.
- Unreadable values become ERROR issues with the source text.
- Unexpected lines become WARNING issues.
- Section-total mismatches are reported.
- The Summary status says *Completed with errors / warnings* when anything needs review.

**Absence is not inferred.** Without a roster the sheet is named and worded *No Recorded Entry – absence not confirmed*. With a roster, roster employees who are missing from the PDF entirely are also listed.

## 3. Results on the supplied sample (21/10/2026, default settings)

| Metric | Value |
|---|---|
| Pages / sections / rows | 451 / 1,953 / 2,458 |
| Unique cardholders / excluded / analysed | 1,428 / 123 / 1,305 |
| On time (arrived ≤ 08:05 and left ≥ 17:00) | 324 |
| Late arrivals (> 08:05) | 561 |
| Early departures (< 17:00) | 201 |
| No recorded entry | 163 |
| Exceptions | 413 Missing Exit, 116 Late + Early |
| Arrived on time but no valid exit (Missing Exit only) | 172 |
| Reconciliation | 324 + 646 late/early + 163 no entry + 172 = 1,305 analysed |
| Parsing errors / total mismatches | 0 / 0 |
| Processing time | ~5 s |

These figures were cross-checked with a separately written classification script and with the pdfplumber engine. Both agree exactly.

### With the Cardholder Summary Report as roster (26-10-2026_Gen_1.pdf, 391 pages)

| Metric | Value |
|---|---|
| Cardholders read | 3,536 (314 excluded by keyword: Temporary / Visitor / Contractor, by name or department) |
| Analysed attendance employees found on the roster | 1,303 of 1,303 (100%) |
| Extra exclusions identified by the roster | 2 cardholders whose roster department is *Visitor* |
| Results for 21/10/2026 | 324 on time, 559 late, 200 early, 163 absent (confirmed on roster), 527 exceptions |
| Roster employees with no section in the attendance PDF | 1,891 (largest groups: Kumasi, Currency Management, Takoradi, Estate & Projects) |

The roster's Staff No and the attendance Staff Card No use different numbering schemes, so matching is by name (order and punctuation-insensitive). A staff-number match is only accepted when the names also agree: on this data, 7 numbers would otherwise have linked different people.

## 3b. Second report format and the Excel export (26-10-2026)

* **PDF configured with Staff No:** "20 to 21 October 2026 Time and Attendance.pdf" has 613 pages and 2,771 sections, and uses *Personal Data Field: Staff No* with the label `Staff No:`. The parser now reads whatever ID label the report uses, so no configuration is needed. All 2,771 section totals reconcile. With Staff No, 1,335 roster matches are now made by staff number (66 by name).
* **Excel export:** "20-10-2026 - Time & Attendance.xlsx" has 1,601 rows for 20/10/2026. `X_24` (no exit within 24 hours) is treated as a missing exit. Departments come from the file.
* **Why the PDF and the Excel export differ for the same day:** the PDF summary report only counts the configured *Time Clocks* (turnstile/RIN/ROUT readers). The Excel export reports the first and last badge at any door, so first entries can be earlier and last exits later. Each source is classified faithfully. They are not expected to agree exactly.
* **Integrity checks:** 4 rows in the export contain typed date cells. One of them (Adams, Jonas) also has a Time on Site that doesn't match its entry and exit. The PDF confirms that the real times were 08:15 to 16:31.
* **Visitor workstations:** in the export, 55 visitors were badged at *FT Workstation on VISITORS-MANAGE* and 114 at *FT Workstation on TW-BIO-VM*, all with no staff number or department and not in the cardholder report. Both doors are excluded by default and can be changed in `visitor_doors`. **Please confirm that TW-BIO-VM is the biometric visitor-management station.**

## 4. Limitations

1. **The summary report only shows the first entry and last exit of each period.** Lunch breaks, re-entries and time off-site in the middle of a period are not visible. *Missing Exit* often means the person left through a non-time-clock door, tailgated, or used a reader that is not a time clock. It is not necessarily an error.
2. **24-hour pairing by the source system.** If someone does not badge out, the system may pair their entry with an exit the next day. The tool reports this as a Long or Overnight Session and does not try to re-pair events.
3. **Shift workers.** The thresholds are global. Security staff and night-shift workers appear as late or early arrivals, with a *Review Notes* hint. Per-group schedules are a future enhancement.
4. **Layout dependency.** The parser targets this report format (labels and column headers). A different report type or a heavily customised layout will be rejected with a clear *Format* error rather than mis-parsed.
5. **Same name, different IDs.** Such cardholders are kept as separate people and flagged on the Validation sheet. They are not merged, because two people can share a name.
6. **Roster matching** uses the staff number (only when the names agree), then the normalised name. The roster's 1,891 cardholders who are absent from the attendance PDF cannot be classified, because the attendance report covered "Selected Cardholders" only. To get confirmed absences for everyone, run the attendance report for all HQ cardholders. Nicknames or spelling differences between HR and access-control records will not match.
7. **Scanned PDFs** are not supported (see §2).
8. **Concurrency.** Streamlit handles several simultaneous users comfortably for this workload of about 5 s per run. It is not designed for hundreds of concurrent users.

## 5. Future enhancements

- **Shift / roster schedules:** per-employee or per-department start and end times, weekends, public holidays, and approved leave imported from HR.
- **Direct data source:** read events from the access-control system's database or REST API instead of PDFs. This gives every badge event, so breaks can be detected and re-entries are handled exactly.
- **Single sign-on:** IIS reverse proxy with Windows Authentication, and an audit log of who processed which report (still without employee data in logs).
- **Trend reporting:** multi-day and monthly aggregation per employee (late count, average arrival time), with charts.
- **Configurable exception rules** in the UI (e.g. ignore Missing Exit for selected readers).
- **Optional OCR** pipeline with mandatory human verification of every OCR-derived time.
- **Signed installer** (MSI) bundling an embedded Python for zero-touch deployment.
