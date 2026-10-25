import pytest

from audit_svc import create_app
from audit_svc.storage import StorageUnavailable

CONFIG = """\
database:
  host: {host}
  port: 5432
  name: audit
  user: audit_svc
  password: {password}
"""


class FakeStorage:
    """Хранилище в памяти вместо PostgreSQL. Хост `down` имитирует недоступную БД."""

    def __init__(self, config):
        self.config = config
        self.connected = False
        self.events = []

    async def connect(self):
        if self.config.host == "down":
            raise StorageUnavailable("connection refused")
        self.connected = True

    async def close(self):
        self.connected = False

    async def ping(self):
        pass

    async def insert_event(self, app, action, actor, payload):
        self.events.append({"app": app, "action": action, "actor": actor, "payload": payload})
        return len(self.events)

    async def list_events(self, app, limit):
        return [e for e in self.events if app in (None, e["app"])][-limit:]


@pytest.fixture
def write_config(tmp_path):
    path = tmp_path / "config.yaml"

    def write(host="db", password="secret"):
        path.write_text(CONFIG.format(host=host, password=password), encoding="utf-8")
        return str(path)

    return write


@pytest.fixture
async def client(aiohttp_client, write_config):
    return await aiohttp_client(create_app(write_config(), storage_factory=FakeStorage))
