"""Генератор нагрузки: отправляет в сервис случайные события аудита.

Часть запросов намеренно некорректна (ответ 400), часть — чтение списка
событий (ответ 200), чтобы на дашборде было что-то кроме 201.
"""

import argparse
import asyncio
import random
import sys
import time
from collections import Counter

import aiohttp

APPS = {"billing": 5, "auth": 3, "orders": 2, "profile": 1}
ACTIONS = ["login", "logout", "create", "update", "delete", "export"]
ACTORS = [f"user{n}" for n in range(1, 21)] + ["system", "cron"]


def random_event() -> dict:
    app = random.choices(list(APPS), weights=list(APPS.values()))[0]
    return {
        "app": app,
        "action": random.choice(ACTIONS),
        "actor": random.choice(ACTORS),
        "payload": {"ip": f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}"},
    }


def broken_event() -> dict:
    event = random_event()
    match random.randint(0, 2):
        case 0:
            event["app"] = "Not A Valid Name!"
        case 1:
            del event["actor"]
        case _:
            event["payload"] = "not an object"
    return event


async def send_one(session: aiohttp.ClientSession, url: str, invalid_ratio: float, read_ratio: float) -> str:
    roll = random.random()
    try:
        if roll < read_ratio:
            app = random.choice(list(APPS))
            async with session.get(f"{url}/api/events", params={"app": app, "limit": "10"}) as resp:
                return str(resp.status)
        body = broken_event() if roll < read_ratio + invalid_ratio else random_event()
        async with session.post(f"{url}/api/events", json=body) as resp:
            return str(resp.status)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return type(exc).__name__


async def run(args: argparse.Namespace) -> None:
    url = args.url.rstrip("/")
    stats: Counter[str] = Counter()
    pending: set[asyncio.Task] = set()
    interval = 1 / args.rate
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    last_report = time.monotonic()

    async def task():
        stats[await send_one(session, url, args.invalid_ratio, args.read_ratio)] += 1

    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            while deadline is None or time.monotonic() < deadline:
                if len(pending) < args.concurrency:
                    job = asyncio.create_task(task())
                    pending.add(job)
                    job.add_done_callback(pending.discard)
                await asyncio.sleep(interval)
                if time.monotonic() - last_report >= 10:
                    print(f"sent {sum(stats.values())}: {dict(sorted(stats.items()))}", file=sys.stderr)
                    last_report = time.monotonic()
        finally:
            if pending:
                await asyncio.wait(pending)
    print(f"total {sum(stats.values())}: {dict(sorted(stats.items()))}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Send random audit events to audit-svc")
    parser.add_argument("--url", default="http://localhost:8080", help="base URL (default: %(default)s)")
    parser.add_argument("--rate", type=float, default=20, help="requests per second (default: %(default)s)")
    parser.add_argument("--duration", type=float, default=300, help="seconds, 0 - until Ctrl+C (default: %(default)s)")
    parser.add_argument("--invalid-ratio", type=float, default=0.05, help="share of broken events (default: %(default)s)")
    parser.add_argument("--read-ratio", type=float, default=0.1, help="share of GET requests (default: %(default)s)")
    parser.add_argument("--concurrency", type=int, default=50, help="max requests in flight (default: %(default)s)")
    args = parser.parse_args()
    if args.rate <= 0:
        parser.error("--rate must be positive")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
