import os

import pytest

from opsagent.storage.db import make_engine, make_sessionmaker
from opsagent.storage.models import Base

TEST_DB_URL = os.environ.get(
    "OPSAGENT_TEST_DB_URL", "postgresql+psycopg://opsagent:opsagent@localhost:5432/opsagent_test")


@pytest.fixture
async def db_sm():
    engine = make_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield make_sessionmaker(engine)
    await engine.dispose()
