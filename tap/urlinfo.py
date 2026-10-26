# Time & Attendance Processor
# Author: Isheanesu Zvikaramba
# Copyright (c) 2026 Zvicasso Technologies (Pty) Ltd. All rights reserved.
"""Print the URL the app listens on (used by start_app.bat to open the browser)."""

import tomllib

from .config import APP_ROOT

if __name__ == "__main__":
    try:
        with open(APP_ROOT / ".streamlit" / "config.toml", "rb") as fh:
            srv = tomllib.load(fh).get("server", {})
    except OSError:
        srv = {}
    addr = srv.get("address", "127.0.0.1")
    if addr in ("0.0.0.0", "", "::"):
        addr = "localhost"
    scheme = "https" if srv.get("sslCertFile") else "http"
    print(f"{scheme}://{addr}:{srv.get('port', 8501)}")
