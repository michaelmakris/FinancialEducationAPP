import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Point at a fresh temp DB file *before* anything imports app.config/app.db,
# so the API tests never touch a developer's real investment_platform.db.
_tmp_db = tempfile.NamedTemporaryFile(prefix="test_investment_platform_", suffix=".db", delete=False)
_tmp_db.close()  # Windows can't delete a file that's still open (see teardown below)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import pytest  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from scripts.seed_demo_data import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _seeded_db():
    init_db()
    seed()
    yield
    engine.dispose()
    os.unlink(_tmp_db.name)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
