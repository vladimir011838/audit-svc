from audit_svc import create_app

from .conftest import FakeStorage

EVENT = {"app": "billing", "action": "login", "actor": "user1", "payload": {"ip": "10.0.0.1"}}


async def test_create_and_list_events(client):
    resp = await client.post("/api/events", json=EVENT)
    assert resp.status == 201
    assert await resp.json() == {"id": 1}

    resp = await client.get("/api/events", params={"app": "billing"})
    assert resp.status == 200
    assert len((await resp.json())["events"]) == 1


async def test_invalid_event(client):
    for body in ({**EVENT, "app": "Bad Name"}, {"app": "billing"}, {**EVENT, "payload": []}, [1, 2]):
        resp = await client.post("/api/events", json=body)
        assert resp.status == 400, body


async def test_metrics(client):
    await client.post("/api/events", json=EVENT)
    text = await (await client.get("/metrics")).text()
    assert 'audit_events_received_total{app="billing"}' in text
    assert 'audit_http_requests_total{code="201",handler="/api/events",method="POST"}' in text


async def test_reload_reconnects_with_new_password(client, write_config):
    resp = await client.post("/reload")
    assert (await resp.json())["changed"] is False

    write_config(password="rotated")
    resp = await client.post("/reload")
    assert resp.status == 200
    assert (await resp.json())["changed"] is True
    assert client.app["state"].storage.config.password == "rotated"


async def test_reload_keeps_old_connection_on_failure(client, write_config):
    write_config(host="down")
    resp = await client.post("/reload")
    assert resp.status == 503
    assert client.app["state"].storage.config.host == "db"

    (await client.post("/api/events", json=EVENT)).raise_for_status()


async def test_database_down(aiohttp_client, write_config):
    client = await aiohttp_client(create_app(write_config(host="down"), storage_factory=FakeStorage))
    assert (await client.get("/healthz")).status == 503
    assert (await client.post("/api/events", json=EVENT)).status == 503
