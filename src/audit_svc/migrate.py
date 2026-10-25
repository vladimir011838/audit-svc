"""Подготовка схемы БД: применяет SQL-файлы из пакета audit_svc.migrations.

Применённые миграции записываются в таблицу schema_migrations, поэтому
повторный запуск ничего не делает. Параметры подключения берутся из того же
конфига, что и у сервиса (AUDIT_SVC_CONFIG или --config).
"""

import argparse
import asyncio
import logging
import sys
from importlib import resources

import asyncpg

from .config import ConfigError, config_path, load_config

log = logging.getLogger("audit_svc.migrate")

# произвольное число: не даёт двум одновременным запускам применять миграции параллельно
ADVISORY_LOCK_ID = 74_301


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("audit_svc") / "migrations"
    files = sorted(item for item in folder.iterdir() if item.name.endswith(".sql"))
    return [(item.name.removesuffix(".sql"), item.read_text(encoding="utf-8")) for item in files]


async def migrate(path: str) -> int:
    config = load_config(path)
    conn = await asyncpg.connect(**config.database.dsn_params(), timeout=10)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", ADVISORY_LOCK_ID)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")}
        count = 0
        for version, sql in migration_files():
            if version in applied:
                continue
            log.info("applying %s", version)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            count += 1
        log.info("done: %d applied, %d already in place", count, len(applied))
        return count
    finally:
        await conn.close()


def main():
    logging.basicConfig(format="[%(levelname)s] %(message)s", level="INFO", stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Apply audit-svc database migrations")
    parser.add_argument("--config", default=config_path(), help="path to config.yaml (default: %(default)s)")
    args = parser.parse_args()
    try:
        asyncio.run(migrate(args.config))
    except ConfigError as exc:
        log.critical("%s", exc)
        sys.exit(1)
    except (OSError, asyncpg.PostgresError) as exc:
        log.critical("migration failed: %s", exc)
        sys.exit(1)
