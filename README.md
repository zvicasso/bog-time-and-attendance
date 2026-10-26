<p align="left"><img src="assets/zvicasso_logo_horizontal.png" alt="Zvicasso Technologies" width="260"></p>

# Time & Attendance Processor

*Developed by **Isheanesu Zvikaramba** · © 2026 Zvicasso Technologies (Pty) Ltd*

A browser-based tool that turns a Time and Attendance report into a classified **Excel workbook**. It accepts either source:

* **PDF:** the *Time and Attendance Summary Report* from the access-control client, for example Bank of Ghana New HQ. It works whether the report's personal data field is *Staff No* or *Staff Card No*.
* **Excel / CSV:** the simpler export with one row per person per day: *Staff No, Cardholder Name, Department, Entry Door, Entry Date/Time, Exit Door, Exit Date/Time, Exception, Time on Site*.

Both sources go through exactly the same rules and produce the same workbook:

| Sheet | Contents |
|---|---|
| **Summary** | Report details, settings used, record counts, exceptions by type, warnings |
| **Raw Data** | Every extracted row, with PDF page, section and record IDs so you can trace it back |
| **Late Arrivals** | First entry later than the late threshold (default **08:05**) |
| **Early Departures** | Last valid exit earlier than the departure threshold (default **17:00**) |
| **On Time** | Arrived by the late threshold **and** left at or after the departure threshold, with time on site |
| **No Recorded Entry** | Cardholders with no entry on the date (confirmed absences only when a roster is supplied) |
| **Attendance Exceptions** | Missing exits, missing entries, conflicting or overlapping events, very long sessions, late *and* early, duplicates |
| **Roster Not In Report** | *(when a roster is supplied)* Roster employees with no section at all in the attendance PDF |
| **Validation** | Parsing and data-quality checks (empty when everything reconciled) |

Everything runs on your own PC or server. **No employee data is sent to the internet, cloud services or AI services.**

---

## 1. Quick start (Windows 11)

1. **Install Python** 3.12 or 3.13 from <https://www.python.org/downloads/windows/>.
   In the installer, tick **"Add python.exe to PATH"**.
2. Copy the `bog-time-attendance` folder to e.g. `C:\Apps\bog-time-attendance`.
3. Double-click **`setup.bat`**. This runs once and takes 1–3 minutes. It creates a private Python environment (`.venv`) and installs the libraries.
4. Double-click **`start_app.bat`**. Your browser opens at <http://127.0.0.1:8501>.
   Keep the black window open while you use the app. Close it to stop the app.

<details>
<summary>Manual setup (same as setup.bat)</summary>

```bat
cd C:\Apps\bog-time-attendance
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
</details>

## 2. Using the application

1. **Drag the attendance report** into box 1. This can be the PDF, the Excel export (.xlsx) or a CSV. The app reads the report header and shows the site, page count and report period.
2. **Choose the reporting date.** It defaults to the last day of the report period. You can also choose *Every date in report period*.
3. *(Optional)* **Upload an employee roster** (`.xlsx` or `.csv`) to confirm absences. See *Roster format* below.
4. *(Optional)* In the left panel, adjust the thresholds or the exclusion words.
5. Click **Process Attendance Report**. A 450-page report takes about 5–10 seconds.
6. Review the counts and any **warnings**, and preview each category in the tabs.
7. Click **Download Excel workbook**. You can also download the **validation report** (.txt).
8. Click **Clear results** when you are done. This removes the employee data from the browser session.

### Roster format

**Recommended: the Cardholder Summary Report PDF** exported from the access-control system. It has the columns First Name, Last Name, Access Group, Staff No and Department. Upload it as-is. The app reads it directly, including names and departments that wrap over several lines.

With this roster:
* Departments are added to every sheet.
* Absences in *No Recorded Entry* become confirmed ("Absent – on roster, no entry recorded").
* Cardholders that the roster lists under an excluded name or department (e.g. department *Visitor*) are excluded from the attendance analysis too.
* Roster employees with no section in the attendance PDF go to the **Roster Not In Report** sheet. These people either had no badge activity or were not selected when the attendance report was run, for example regional branch staff. Filter that sheet by Department before treating anyone as absent.

On the Bank of Ghana sample, the cardholder report's Staff No (e.g. `6798`) uses a different numbering scheme from the attendance report's Staff Card No (e.g. `01001518`). Matching is therefore mostly **by name**: word order and punctuation are ignored. A staff-number match is accepted only when the names also agree, so a reused number can never link two different people.

**Alternative: Excel/CSV.** Use one row per expected employee. The column names are detected automatically, and their case does not matter:

| Needed | Accepted column names |
|---|---|
| ID *and/or* name | `Staff Card No`, `Staff No`, `Employee ID`, `Personnel No` … / `Name`, `Employee Name`, `Cardholder Name`, or `Surname` + `First Name` |
| Optional | `Department`, `Dept`, `Division`, `Unit` |

Matching uses the staff number first. Leading zeros are ignored, so `456` matches `000456`. If there is no staff number, matching falls back to the name. Name order and punctuation are ignored, so "Zindam, Cynthia" matches "Cynthia Zindam". See `tests/data/sample_roster.csv` for an example.

## 3. Attendance sources

| | PDF summary report | Excel/CSV export |
|---|---|---|
| Staff ID | The report's *Personal Data Field*, read from the report itself (Staff No or Staff Card No) | `Staff No` column |
| Department | From the roster | `Department` column (the roster overrides it) |
| No real exit | `Report End Date/Time` / `Insuff. D.` | `Exception = X_24` (exit shown as the next midnight) |
| Traceability | PDF page + record ID | Spreadsheet row number + record ID |
| Absentees | Selected cardholders with no rows are listed | The export lists only people who badged in, so use a roster to find absentees |

Column names in the spreadsheet are matched flexibly, e.g. *Employee ID*, *Time In* / *Time Out*, *Duration*. Every sheet that has the expected header is read.

**Data integrity checks (spreadsheet source).** In a genuine system export, every time cell is text and *Time on Site* always equals exit minus entry. The app flags any row where:

- a time cell is a typed Excel date/time among text cells, or
- *Time on Site* does not match the entry and exit times.

Those rows appear under **Attendance Exceptions → Data Integrity**. On the 20-10-2026 export, one row (Adams, Jonas) shows 07:15 to 17:31, while its own Time on Site and the access-control PDF both indicate 08:15 to 16:31. That edit would have turned a late arrival and early departure into "on time".

**Visitor badges.** Visitor cards issued at a visitor-management workstation often have no staff number or department. They are recognised by the door/reader where the badge was first used: `visitor_doors` in `config\settings.toml`, editable in the app's left panel. The defaults are `VISITORS-MANAGE` and `TW-BIO-VM`.

## 4. How attendance is classified

The rules apply to each person, for each selected date **D**. Cardholders whose names match an exclusion word are skipped.

* **The date comes from the actual entry timestamp.** It never comes from the PDF page number or the report generation date. A session that starts on D and ends on the next day belongs to D.
* **Late arrival:** the earliest entry on D is *later than* the threshold. An entry at exactly 08:05:00 is not late.
* **Early departure:** the latest **valid** exit of D's sessions is *earlier than* the threshold. An exit at exactly 17:00:00 is not early.
  `Report End Date/Time` (still inside when the report period ended) and `Insuff. D.` are **not** valid exits. Those rows appear as *Missing Exit* exceptions and are never counted as early departures.
* **On time:** the person arrived by the late threshold, has a valid exit, and left at or after the departure threshold. Anyone who arrived on time but has no valid exit is not on this sheet. They appear under *Attendance Exceptions → Missing Exit*, because the app cannot confirm when they left.
* **No recorded entry:** the person has a section in the PDF but no entry on D. The *Other Activity* column explains what the report does show, for example "Still on site from 20/10 10:20 (overnight)" or "Insufficient data".
  **Without a roster this is not a confirmed absence list.** Staff who are missing from the PDF entirely cannot be detected.
  With a roster, people on the roster are marked *Absent*, and roster employees with no section in the PDF are listed as *not found in report*.
* **Exclusions:** names containing *Temporary*, *Contractor* or *Visitor* are excluded. Matching ignores case and tolerates misspellings such as `TEMPORARAY` or `VISTOR`. Excluded rows stay in **Raw Data** with the reason shown. No other category is excluded automatically. The app warns you about generic names like `PENSIONER` so you can decide whether to exclude them.
* **Repeated sections:** sections for the same person (same name + staff number) are merged. Identical repeated rows are ignored and listed as *Duplicate Records*.
* **Validation:** for every cardholder section, the sum of the parsed *Time Worked* values is checked against the report's own *Total Working Time*. Any difference is listed on the **Validation** sheet. Nothing that fails to parse is dropped silently.

## 5. Configuration

Open `config\settings.toml` in Notepad, save your changes, then restart the app.

| Setting | Default | Meaning |
|---|---|---|
| `late_threshold` / `early_threshold` | `08:05` / `17:00` | Default thresholds (can be changed per run in the app) |
| `max_session_hours` | `16` | Sessions longer than this are flagged |
| `pdf_date_order` | `DMY` | `21/10/2026` style dates. Use `MDY` for US-format reports |
| `exclude_keywords` | Temporary, Contractor, Visitor | Exclusion words |
| `fuzzy_threshold` | `0.80` | Misspelling tolerance (`1.0` = exact words only) |
| `max_pdf_mb` / `max_roster_mb` | 50 / 10 | Upload limits |
| `temp_dir`, `retention_minutes` | system temp, 60 | Where temporary files go and how long leftovers may stay |
| `auth_enabled`, `password_hash` | off | Password protection (see §6.3) |

**Network address and port** are set in `.streamlit\config.toml` (`address`, `port`). The default is `127.0.0.1`, which means only this computer can open the app.

## 6. Windows Server 2022 deployment

Windows Server does **not** include Python. Install it first.

### 6.1 Install

1. Install **Python 3.12/3.13 (64-bit)**. Choose **Customize installation → Install for all users** and tick **Add Python to environment variables**.
   *Install for all users* is required so that the background service account can use Python.
2. Copy the application to a local folder, for example `C:\Apps\bog-time-attendance`. Do not use a user's Desktop or Documents folder.
3. Run `setup.bat` as an administrator.

**Offline server (no internet access):** on a Windows PC that has internet access and the **same Python version**, run:

```bat
py -3 -m pip download -r requirements.txt -d wheels
```

Copy the `wheels` folder into the application folder on the server. `setup.bat` then installs from it automatically.

### 6.2 Make it reachable from the internal network

1. Edit `.streamlit\config.toml` and set `address` to the server's **internal IP**, for example `address = "10.20.30.40"`.
   Avoid `0.0.0.0` unless the server has only internal network interfaces.
2. Open the firewall **only to the internal subnet that needs access**. Run this in an elevated PowerShell window:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\deploy\open_firewall.ps1 -RemoteAddress 10.20.30.0/24
   ```

   The rule applies only to the Domain and Private profiles. **Never publish this port to the internet.**
3. Users then open `http://10.20.30.40:8501`.

### 6.3 Turn on password protection (required when networked)

```bat
cd C:\Apps\bog-time-attendance
.venv\Scripts\python -m tap.security
```

Enter a password of at least 10 characters. Paste the printed `password_hash = "..."` line into `config\settings.toml`, and set `auth_enabled = true`. Users then see a sign-in screen. Failed attempts are rate-limited, and each browser session locks after 5 failures.

**HTTPS (recommended):** put certificate files on the server and uncomment `sslCertFile` / `sslKeyFile` in `.streamlit\config.toml`. You can use certificates from your internal CA.

For single sign-on with Windows accounts, see *Future enhancements* in `docs/DESIGN.md`. It works by placing IIS (with Windows Authentication and URL Rewrite/ARR) in front of the app.

### 6.4 Run persistently (starts at boot, restarts if it stops)

This uses the built-in Task Scheduler, so no extra software is needed. Run it in an elevated PowerShell window from the application folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\install_scheduled_task.ps1
```

* By default the task runs as the low-privilege built-in account **LOCAL SERVICE**. To use a dedicated service account instead, add `-User "CORP\svc-tap" -Password (Read-Host -AsSecureString)`.
* The script grants that account write access to `logs\`, starts the task, and checks the health URL.
* To manage it: **Task Scheduler → TimeAttendanceProcessor** (Run / End / History).
* To remove it: `.\deploy\uninstall_scheduled_task.ps1`.

<details>
<summary>Alternative: run as a Windows service with NSSM</summary>

If your organisation allows NSSM (<https://nssm.cc>):

```bat
nssm install TimeAttendanceProcessor "C:\Apps\bog-time-attendance\.venv\Scripts\python.exe" "-m streamlit run app.py"
nssm set TimeAttendanceProcessor AppDirectory "C:\Apps\bog-time-attendance"
nssm set TimeAttendanceProcessor ObjectName "NT AUTHORITY\LocalService"
nssm set TimeAttendanceProcessor Start SERVICE_AUTO_START
nssm start TimeAttendanceProcessor
```
</details>

### 6.5 Packaging note

The supported way to deploy is to copy the folder and run `setup.bat`, using an online or offline `wheels` install. A single `.exe` build (for example PyInstaller) is possible but fragile with Streamlit, and it makes security updates harder, so it is not provided in this release.

## 7. Security and privacy

* Uploads are checked for extension, size and real PDF/XLSX file signatures. Encrypted, damaged and scanned (image-only) PDFs are rejected with a clear message.
* Each run uses its own randomly named temporary folder, which is deleted as soon as processing finishes, even when processing fails. A retention sweep removes leftovers at startup and after each run. Uploaded filenames are sanitised, which prevents path traversal.
* Results live only in the user's browser session until **Clear results** is clicked or the tab is closed. Nothing is stored permanently on the server.
* `logs\app.log` records only technical events, timings and counts. It **never** contains names, staff numbers or card numbers.
* Streamlit usage statistics are disabled, and Python error details are hidden from users.

## 8. Command line (optional)

This is for administrators or scheduled batch jobs:

```bat
.venv\Scripts\python cli.py "Time and Attendance 21-10-2026.pdf" --date 21/10/2026 --roster roster.xlsx --out results.xlsx --report validation.txt
.venv\Scripts\python cli.py report.pdf --all-dates --late 08:00 --early 16:30
```

## 9. Tests

Double-click `run_tests.bat`, or run:

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -v
```

The tests generate a synthetic report with fictional people. It reproduces the real report's tricky cases: wrapped clock names, wrapped am/pm, `Insuff. D.` rows, `Report End Date/Time` exits, sections split across pages, repeated sections, overnight shifts and exact-threshold times.

To also run the regression test against the real report, run `set TAP_SAMPLE_PDF=C:\path\Time and Attendance 21-10-2026.pdf` before running pytest.

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `setup.bat`: *Python was not found* | Install Python with "Add to PATH" ticked, then open a **new** window. On a server, choose "Install for all users". |
| `pip install` fails behind a proxy | `set HTTPS_PROXY=http://proxy:port`, then rerun `setup.bat`, or use the offline `wheels` method (§6.1). |
| Browser says *can't reach this page* | Make sure the start window is still open. Check `address` and `port` in `.streamlit\config.toml`. From other PCs, check the firewall rule (§6.2). |
| *Port 8501 is already in use* | Another copy is running. Close it, or change `port` in `.streamlit\config.toml`. |
| *This PDF appears to be a scanned image* | Export the report directly from the access-control system (Print/Save to PDF), not by scanning paper. |
| *password-protected* | Re-export the report without a password. |
| *No 'Cardholder Name:' sections were found* | The file is not a Time and Attendance Summary Report, or its layout is different. Send a sample to the maintainer. |
| *Total mismatch* warnings | Open the PDF at the listed page and compare it with **Raw Data**. Report the case so the parser can be extended. |
| Dates look swapped (e.g. 10/21) | Set `pdf_date_order = "MDY"` in `config\settings.toml`. |
| Scheduled task runs but the page doesn't load | Check Task Scheduler → History and `logs\app.log`. Make sure Python was installed for all users and the task account can read the folder. |

## 11. Credits and branding

Designed and developed by **Isheanesu Zvikaramba**, Zvicasso Technologies (Pty) Ltd.
Logos are in `assets/` and are used in the app (sidebar, sign-in page, browser tab icon) and on the workbook's Summary sheet. Brand colours are navy `#06364A`, teal `#63CDC5` and mint `#DAFFFB`. They are defined in `tap/branding.py` and `.streamlit/config.toml`.

## 12. Project structure

```
bog-time-attendance/
├─ app.py                     Browser interface (Streamlit)
├─ cli.py                     Command-line processing
├─ tap/                       Processing package
│  ├─ pdf_extract.py          PDF words + positions (pypdfium2, pdfplumber fallback), scan/encryption detection
│  ├─ parser.py               Column-aware parsing of cardholder sections and rows, total reconciliation
│  ├─ filtering.py            Exclusion rules (fuzzy), merging repeated sections, duplicate detection
│  ├─ roster.py               Roster loading (PDF/Excel/CSV), safe matching, roster-based exclusions
│  ├─ cardholder_report.py    Cardholder Summary Report PDF parser (roster)
│  ├─ excel_source.py         Excel/CSV attendance export reader + data-integrity checks
│  ├─ branding.py             Author, company, colours, logo paths
│  ├─ classify.py             Late / early / no-entry / exception rules
│  ├─ excel_report.py         Workbook formatting (openpyxl)
│  ├─ pipeline.py             Orchestration + summary + validation report
│  ├─ security.py             Upload validation, safe filenames, password hashing
│  ├─ tempfiles.py            Per-job temp folders and retention sweep
│  ├─ config.py / logging_setup.py / urlinfo.py
├─ assets/                    Zvicasso Technologies logos and icon
├─ config/settings.toml       Business and security settings
├─ .streamlit/config.toml     Web server settings (address, port, HTTPS)
├─ deploy/                    Windows Server scripts (scheduled task, firewall)
├─ tests/                     pytest suite + synthetic report generator + sample roster
├─ sample_output/             Example workbooks
├─ docs/DESIGN.md             Design decisions, limitations, future enhancements
├─ setup.bat  start_app.bat  run_server.bat  run_tests.bat
└─ requirements.txt  requirements-dev.txt
```
