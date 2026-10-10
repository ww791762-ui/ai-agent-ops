"""用法：uv run python -m opsagent.storage.init_db"""
import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from opsagent.config import Settings

from .db import make_engine
from .models import Base


async def init_db(settings: Settings) -> None:
    engine = make_engine(settings.db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_db_url) as saver:
        await saver.setup()


if __name__ == "__main__":
    asyncio.run(init_db(Settings()))
    print("数据库初始化完成")
