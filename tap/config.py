# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Application settings loaded from config/settings.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from datetime import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = APP_ROOT / "config" / "settings.toml"


def parse_hhmm(value: str | time) -> time:
    """Parse '08:05', '8:05', '08:05:30' or '5:00 PM' into a time."""
    if isinstance(value, time):
        return value
    text = str(value).strip().upper()
    suffix = None
    for s in ("AM", "PM"):
        if text.endswith(s):
            suffix, text = s, text[: -len(s)].strip()
    parts = [int(p) for p in text.split(":")]
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"Invalid time value: {value!r}")
    h, m = parts[0], parts[1]
    s = parts[2] if len(parts) == 3 else 0
    if suffix == "PM" and h < 12:
        h += 12
    if suffix == "AM" and h == 12:
        h = 0
    return time(h, m, s)


@dataclass(frozen=True)
class Settings:
    late_threshold: time = time(8, 5)
    early_threshold: time = time(17, 0)
    max_session_hours: float = 16.0
    pdf_date_order: str = "DMY"
    exclude_keywords: tuple[str, ...] = ("Temporary", "Contractor", "Visitor")
    fuzzy_threshold: float = 0.80
    visitor_doors: tuple[str, ...] = ("VISITORS-MANAGE", "TW-BIO-VM")
    max_pdf_mb: int = 50
    max_roster_mb: int = 10
    temp_dir: str = ""
    retention_minutes: int = 60
    auth_enabled: bool = False
    password_hash: str = ""
    max_login_attempts: int = 5
    log_dir: str = "logs"
    log_level: str = "INFO"
    extra: dict = field(default_factory=dict)

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)

    @property
    def log_path(self) -> Path:
        p = Path(self.log_dir)
        return p if p.is_absolute() else APP_ROOT / p


def load_settings(path: Path | str | None = None) -> Settings:
    path = Path(path) if path else DEFAULT_SETTINGS_PATH
    if not path.exists():
        return Settings()
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    att = data.get("attendance", {})
    flt = data.get("filtering", {})
    upl = data.get("uploads", {})
    sto = data.get("storage", {})
    sec = data.get("security", {})
    log = data.get("logging", {})
    d = Settings()
    order = str(att.get("pdf_date_order", d.pdf_date_order)).upper()
    if order not in ("DMY", "MDY"):
        raise ValueError("pdf_date_order must be 'DMY' or 'MDY'")
    return Settings(
        late_threshold=parse_hhmm(att.get("late_threshold", "08:05")),
        early_threshold=parse_hhmm(att.get("early_threshold", "17:00")),
        max_session_hours=float(att.get("max_session_hours", d.max_session_hours)),
        pdf_date_order=order,
        exclude_keywords=tuple(flt.get("exclude_keywords", d.exclude_keywords)),
        fuzzy_threshold=float(flt.get("fuzzy_threshold", d.fuzzy_threshold)),
        visitor_doors=tuple(flt.get("visitor_doors", d.visitor_doors)),
        max_pdf_mb=int(upl.get("max_pdf_mb", d.max_pdf_mb)),
        max_roster_mb=int(upl.get("max_roster_mb", d.max_roster_mb)),
        temp_dir=str(sto.get("temp_dir", "")),
        retention_minutes=int(sto.get("retention_minutes", d.retention_minutes)),
        auth_enabled=bool(sec.get("auth_enabled", False)),
        password_hash=str(sec.get("password_hash", "")),
        max_login_attempts=int(sec.get("max_login_attempts", d.max_login_attempts)),
        log_dir=str(log.get("log_dir", d.log_dir)),
        log_level=str(log.get("level", d.log_level)).upper(),
    )
