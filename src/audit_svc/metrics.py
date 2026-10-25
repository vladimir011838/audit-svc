"""Метрики Prometheus и middleware, которое считает HTTP-запросы."""

import time

from aiohttp import web
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    generate_latest,
)

# ряды *_created только мешают на дашбордах
disable_created_metrics()

EVENTS_RECEIVED = Counter(
    "audit_events_received_total",
    "Принятые и сохранённые события аудита",
    ["app"],
)
HTTP_REQUESTS = Counter(
    "audit_http_requests_total",
    "HTTP-запросы к сервису",
    ["method", "handler", "code"],
)
HTTP_DURATION = Histogram(
    "audit_http_request_duration_seconds",
    "Время обработки HTTP-запроса",
    ["method", "handler"],
)
CONFIG_RELOADS = Counter(
    "audit_config_reloads_total",
    "Перечитывания конфигурации",
    ["result"],
)
DB_UP = Gauge(
    "audit_db_up",
    "1, если сервис подключён к PostgreSQL",
)


def _handler_label(request: web.Request) -> str:
    # шаблон маршрута, а не реальный путь: иначе /api/xxx породит бесконечно много рядов
    resource = request.match_info.route.resource
    return resource.canonical if resource is not None else "unmatched"


@web.middleware
async def metrics_middleware(request: web.Request, handler):
    started = time.perf_counter()
    code = 500
    try:
        response = await handler(request)
        code = response.status
        return response
    except web.HTTPException as exc:
        code = exc.status
        raise
    finally:
        label = _handler_label(request)
        HTTP_REQUESTS.labels(request.method, label, str(code)).inc()
        HTTP_DURATION.labels(request.method, label).observe(time.perf_counter() - started)


async def metrics_handler(_: web.Request) -> web.Response:
    return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
