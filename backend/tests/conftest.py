import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="fundtrace-test-")
os.environ.update({
    "DATABASE_URL": "sqlite://",
    "LOCAL_UPLOAD_DIR": os.path.join(_tmp, "uploads"),
    "SEED_ON_START": "false",
    "LLM_ENABLED": "false",
    "JWT_SECRET": "test-secret",
    "ENVIRONMENT": "test",
})


@pytest.fixture(scope="session")
def seeded():
    """One in-memory database seeded with the synthetic world, shared by integration tests."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.db import create_all, init_engine, session_scope
    from app.seed.loader import seed

    init_engine("sqlite://")
    create_all()
    with session_scope() as db:
        info = seed(db)
    return info


@pytest.fixture()
def db(seeded):
    from app.db import session_factory

    s = session_factory()()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
