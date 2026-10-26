# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    """Synthetic report + roster, regenerated for every test session."""
    from synthetic import write_fixtures

    return write_fixtures(tmp_path_factory.mktemp("fixtures"))


@pytest.fixture(scope="session")
def synthetic_pdf(fixtures):
    return fixtures[0]


@pytest.fixture(scope="session")
def roster_csv(fixtures):
    return fixtures[1]


@pytest.fixture(scope="session")
def cardholder_pdf(fixtures):
    return fixtures[2]


@pytest.fixture(scope="session")
def excel_export(fixtures):
    return fixtures[0].parent / "sample_export.xlsx"


@pytest.fixture(scope="session")
def staffno_pdf(fixtures):
    return fixtures[0].parent / "synthetic_report_staffno.pdf"


@pytest.fixture
def settings():
    from tap.config import Settings

    return Settings()
