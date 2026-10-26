# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Upload validation, safe filenames and optional password protection.

Run `python -m tap.security` to generate a password hash for settings.toml.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import re
import unicodedata

PBKDF2_ITERATIONS = 310_000


class UploadError(Exception):
    """Raised with a message that is safe to show to the user."""


def safe_filename(name: str, default: str = "upload") -> str:
    """Strip directories and unsafe characters (prevents path traversal)."""
    name = unicodedata.normalize("NFKC", str(name or ""))
    name = re.split(r"[\\/]", name)[-1]  # drop any directory part, Windows or POSIX
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    name = re.sub(r"\.{2,}", ".", name)
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if not name or name.split(".")[0].upper() in reserved:
        name = default
    return name[:120]


def validate_pdf_upload(data: bytes, filename: str, max_mb: int) -> None:
    if not filename.lower().endswith(".pdf"):
        raise UploadError("Please upload a PDF file (.pdf).")
    if len(data) == 0:
        raise UploadError("The uploaded file is empty.")
    if len(data) > max_mb * 1024 * 1024:
        raise UploadError(f"The PDF is larger than the {max_mb} MB limit.")
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise UploadError("The file has a .pdf name but is not a valid PDF document.")


def validate_report_upload(data: bytes, filename: str, max_mb: int) -> None:
    """Attendance source: Time and Attendance Summary Report PDF, or an Excel/CSV export."""
    low = filename.lower()
    if low.endswith(".pdf"):
        return validate_pdf_upload(data, filename, max_mb)
    if not low.endswith((".xlsx", ".xlsm", ".csv")):
        raise UploadError("Upload the Time and Attendance report as a PDF, Excel (.xlsx) or CSV file.")
    if len(data) == 0:
        raise UploadError("The uploaded file is empty.")
    if len(data) > max_mb * 1024 * 1024:
        raise UploadError(f"The file is larger than the {max_mb} MB limit.")
    if low.endswith((".xlsx", ".xlsm")) and not data.startswith(b"PK"):
        raise UploadError("The file has an Excel name but is not a valid .xlsx workbook.")


def validate_roster_upload(data: bytes, filename: str, max_mb: int) -> None:
    low = filename.lower()
    if not low.endswith((".csv", ".xlsx", ".xlsm", ".pdf")):
        raise UploadError("The roster must be a Cardholder Summary Report (.pdf), Excel (.xlsx) or CSV (.csv) file.")
    if len(data) == 0:
        raise UploadError("The roster file is empty.")
    if len(data) > max_mb * 1024 * 1024:
        raise UploadError(f"The roster is larger than the {max_mb} MB limit.")
    if low.endswith(".pdf") and not data[:1024].lstrip().startswith(b"%PDF-"):
        raise UploadError("The roster has a .pdf name but is not a valid PDF document.")
    if low.endswith((".xlsx", ".xlsm")) and not data.startswith(b"PK"):
        raise UploadError("The roster has an Excel name but is not a valid .xlsx file.")


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def _cli() -> None:
    print("Generate a password hash for config\\settings.toml")
    p1 = getpass.getpass("New password: ")
    p2 = getpass.getpass("Repeat password: ")
    if p1 != p2:
        raise SystemExit("Passwords do not match.")
    if len(p1) < 10:
        raise SystemExit("Use at least 10 characters.")
    print("\nCopy this line into the [security] section of config\\settings.toml:\n")
    print(f'password_hash = "{hash_password(p1)}"')
    print("auth_enabled = true")


if __name__ == "__main__":
    _cli()
