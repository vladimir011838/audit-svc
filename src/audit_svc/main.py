import asyncio
import logging
import os
import re
import sys
from dataclasses import dataclass, field

from aiohttp import web
from aiohttp.web import Application, Request, Response, get, json_response, post

from .config import Config, ConfigError, load_config
from .metrics import CONFIG_RELOADS, DB_UP, EVENTS_RECEIVED, metrics_handler, metrics_middleware
from .storage import Storage, StorageUnavailable

log = logging.getLogger(__name__)

APP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_FIELD_LENGTH = 128
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500


@dataclass
class State:
    config_path: str | None
    storage_factory: type = Storage
    config: Config | None = None
    storage: Storage | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def create_app(config_path: str | None = None, storage_factory: type = Storage) -> Application:
    app = Application(middlewares=[metrics_middleware])
    app["state"] = State(config_path=config_path, storage_factory=storage_factory)
    app.add_routes(
        [
            post("/api/events", create_event),
            get("/api/events", list_events),
            get("/healthz", healthz),
            get("/metrics", metrics_handler),
            post("/reload", reload_config),
        ]
    )
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


async def on_startup(app: Application) -> None:
    state: State = app["state"]
    # без конфига работать нельзя: падаем сразу, чтобы ошибку было видно в docker logs
    state.config = load_config(state.config_path)
    state.storage = state.storage_factory(state.config.database)
    try:
        await state.storage.connect()
    except StorageUnavailable as exc:
        log.warning("database is unavailable, will retry on next request: %s", exc)
    DB_UP.set(1 if state.storage.connected else 0)


async def on_cleanup(app: Application) -> None:
    state: State = app["state"]
    if state.storage is not None:
        await state.storage.close()


async def get_storage(state: State) -> Storage:
    async with state.lock:
        if not state.storage.connected:
            try:
                await state.storage.connect()
            finally:
                DB_UP.set(1 if state.storage.connected else 0)
        return state.storage


def unavailable(exc: Exception) -> Response:
    log.error("database error: %s", exc)
    return json_response(status=503, data={"error": "database is unavailable"})


def bad_request(message: str) -> Response:
    return json_response(status=400, data={"error": message})


def validate_event(body) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, "body must be a JSON object"
    app = body.get("app")
    if not isinstance(app, str) or not APP_NAME_RE.match(app):
        return None, "field 'app' must match ^[a-z0-9][a-z0-9_-]{0,63}$"
    for key in ("action", "actor"):
        value = body.get(key)
        if not isinstance(value, str) or not 0 < len(value) <= MAX_FIELD_LENGTH:
            return None, f"field '{key}' must be a non-empty string up to {MAX_FIELD_LENGTH} chars"
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        return None, "field 'payload' must be a JSON object"
    return {"app": app, "action": body["action"], "actor": body["actor"], "payload": payload}, None


async def create_event(request: Request) -> Response:
    try:
        body = await request.json()
    except ValueError:
        return bad_request("body must be valid JSON")
    event, error = validate_event(body)
    if error:
        return bad_request(error)

    state: State = request.app["state"]
    try:
        storage = await get_storage(state)
        event_id = await storage.insert_event(**event)
    except StorageUnavailable as exc:
        return unavailable(exc)

    EVENTS_RECEIVED.labels(event["app"]).inc()
    return json_response(status=201, data={"id": event_id})


async def list_events(request: Request) -> Response:
    app = request.query.get("app")
    try:
        limit = int(request.query.get("limit", DEFAULT_LIST_LIMIT))
    except ValueError:
        return bad_request("limit must be a number")
    if not 0 < limit <= MAX_LIST_LIMIT:
        return bad_request(f"limit must be between 1 and {MAX_LIST_LIMIT}")

    state: State = request.app["state"]
    try:
        storage = await get_storage(state)
        events = await storage.list_events(app, limit)
    except StorageUnavailable as exc:
        return unavailable(exc)
    return json_response(status=200, data={"events": events})


async def healthz(request: Request) -> Response:
    state: State = request.app["state"]
    try:
        storage = await get_storage(state)
        await storage.ping()
    except StorageUnavailable as exc:
        return unavailable(exc)
    return json_response(status=200, data={"status": "ok"})


async def reload_config(request: Request) -> Response:
    state: State = request.app["state"]
    try:
        config = load_config(state.config_path)
    except ConfigError as exc:
        CONFIG_RELOADS.labels("failure").inc()
        log.error("config reload failed, keeping previous config: %s", exc)
        return json_response(status=500, data={"error": str(exc)})

    async with state.lock:
        if config.database == state.config.database and state.storage.connected:
            CONFIG_RELOADS.labels("success").inc()
            log.info("config reloaded, database settings are unchanged")
            return json_response(status=200, data={"status": "reloaded", "changed": False})

        storage = state.storage_factory(config.database)
        try:
            await storage.connect()
        except StorageUnavailable as exc:
            CONFIG_RELOADS.labels("failure").inc()
            log.error("config reload failed, keeping previous connection: %s", exc)
            return json_response(status=503, data={"error": f"cannot connect with new settings: {exc}"})

        old_storage, state.storage, state.config = state.storage, storage, config
        await old_storage.close()
        DB_UP.set(1)

    CONFIG_RELOADS.labels("success").inc()
    log.info("config reloaded, reconnected to the database")
    return json_response(status=200, data={"status": "reloaded", "changed": True})


def main():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
        stream=sys.stderr,
    )
    host = str(os.getenv("HOST", "0.0.0.0"))
    port = int(os.getenv("PORT", "8080"))
    try:
        web.run_app(create_app(), host=host, port=port, access_log=None)
    except ConfigError as exc:
        log.critical("%s", exc)
        sys.exit(1)
