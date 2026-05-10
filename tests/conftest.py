"""Per-test isolated SQLite database.

We set STUDYSYNC_DB_URL *before* the app modules are imported for the first
time, so the engine binds to a temp file. Each test gets a clean schema.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest


@pytest.fixture
def client():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["STUDYSYNC_DB_URL"] = f"sqlite:///{tmp.name}"

    # Drop any cached app modules so the new env var takes effect on import.
    for mod in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

    os.unlink(tmp.name)
