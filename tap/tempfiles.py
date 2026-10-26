# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Per-job temporary folders with guaranteed cleanup and a retention sweep."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)
PREFIX = "tap_job_"


def base_dir(configured: str = "") -> Path:
    base = Path(configured) if configured else Path(tempfile.gettempdir()) / "tap_processing"
    base.mkdir(parents=True, exist_ok=True)
    return base


@contextmanager
def job_dir(configured: str = "") -> Iterator[Path]:
    """Create a unique folder for one processing job and always delete it afterwards."""
    path = Path(tempfile.mkdtemp(prefix=PREFIX, dir=base_dir(configured)))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():  # e.g. file still locked by antivirus on Windows
            log.warning("temporary folder could not be removed yet: %s", path.name)


def purge_old(configured: str = "", retention_minutes: int = 60) -> int:
    """Delete leftover job folders older than the retention period. Returns count removed."""
    base = base_dir(configured)
    cutoff = time.time() - retention_minutes * 60
    removed = 0
    for p in base.glob(PREFIX + "*"):
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        log.info("retention sweep removed %d old temporary folder(s)", removed)
    return removed
