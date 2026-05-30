import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

log = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


# New columns added after the initial schema. create_all() does not ALTER
# existing tables, so add any missing ones in place (SQLite only).
_MIGRATIONS = {
    "accounts": {
        "auth_mode": "VARCHAR(16) NOT NULL DEFAULT 'password'",
        "session_token": "TEXT NOT NULL DEFAULT ''",
    },
}


async def _migrate():
    if engine.dialect.name != "sqlite":
        return
    for table, columns in _MIGRATIONS.items():
        async with engine.begin() as conn:
            result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
            existing = {row[1] for row in result}
        if not existing:
            continue  # table will be created fresh by create_all
        for name, ddl in columns.items():
            if name in existing:
                continue
            # Each ALTER in its own transaction so a concurrent worker that
            # already added the column ("duplicate column") doesn't abort the rest.
            try:
                async with engine.begin() as conn:
                    await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            except Exception as e:
                log.warning("migrate %s.%s skipped: %s", table, name, e)


async def init_db():
    # create_all / ALTER are not atomic across processes; with multiple uvicorn
    # workers all running this, tolerate the loser of the race.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        log.warning("create_all skipped: %s", e)
    await _migrate()
