"""Работа с PostgreSQL: пул соединений и запросы к таблице events."""

import json
import logging

import asyncpg

from .config import DatabaseConfig

log = logging.getLogger(__name__)


class StorageUnavailable(Exception):
    pass


class Storage:
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                **self.config.dsn_params(), min_size=1, max_size=5, timeout=5
            )
        except (OSError, asyncpg.PostgresError) as exc:
            raise StorageUnavailable(str(exc)) from exc
        log.info(
            "connected to postgres://%s@%s:%s/%s",
            self.config.user,
            self.config.host,
            self.config.port,
            self.config.name,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def connected(self) -> bool:
        return self._pool is not None

    async def ping(self) -> None:
        await self._fetchval("SELECT 1")

    async def insert_event(self, app: str, action: str, actor: str, payload: dict) -> int:
        return await self._fetchval(
            "INSERT INTO events (app, action, actor, payload) VALUES ($1, $2, $3, $4::jsonb) RETURNING id",
            app,
            action,
            actor,
            json.dumps(payload),
        )

    async def list_events(self, app: str | None, limit: int) -> list[dict]:
        if self._pool is None:
            raise StorageUnavailable("not connected")
        try:
            rows = await self._pool.fetch(
                "SELECT id, received_at, app, action, actor, payload FROM events"
                " WHERE $1::text IS NULL OR app = $1"
                " ORDER BY id DESC LIMIT $2",
                app,
                limit,
            )
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            raise StorageUnavailable(str(exc)) from exc
        return [
            {
                "id": row["id"],
                "received_at": row["received_at"].isoformat(),
                "app": row["app"],
                "action": row["action"],
                "actor": row["actor"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    async def _fetchval(self, query: str, *args):
        if self._pool is None:
            raise StorageUnavailable("not connected")
        try:
            return await self._pool.fetchval(query, *args)
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            raise StorageUnavailable(str(exc)) from exc
