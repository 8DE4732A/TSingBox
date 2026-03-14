import base64

import httpx
import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.services.subscription_manager import (
    SUBSCRIPTION_HEADERS,
    SubscriptionHTTPError,
    SubscriptionManager,
    SubscriptionNetworkError,
    SubscriptionParseError,
)


class DummyResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class DummyClient:
    def __init__(self, text: str, *, timeout: float = 15.0, follow_redirects: bool = False):
        self._text = text
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.last_url: str | None = None
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None):
        self.last_url = url
        self.last_headers = headers
        return DummyResponse(self._text)


@pytest.mark.asyncio
async def test_refresh_subscription_with_base64(monkeypatch, tmp_path):
    uri = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls#node1"
    encoded = base64.b64encode((uri + "\n").encode()).decode()

    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    manager = SubscriptionManager(
        subscriptions_repo=SubscriptionsRepository(db),
        nodes_repo=NodesRepository(db),
    )

    import tsingbox.services.subscription_manager as m

    client = DummyClient(encoded, timeout=15.0, follow_redirects=True)
    monkeypatch.setattr(
        m.httpx,
        "AsyncClient",
        lambda timeout=15.0, follow_redirects=False: client,
    )
    inserted = await manager.refresh_subscription(name="demo", url="https://example.com/sub")
    assert inserted == 1

    nodes = await manager.nodes_repo.list_nodes()
    assert len(nodes) == 1
    assert nodes[0].protocol == "vless"
    assert client.follow_redirects is True
    assert client.last_url == "https://example.com/sub"
    assert client.last_headers == SUBSCRIPTION_HEADERS


def test_parse_line_trojan():
    manager = SubscriptionManager(subscriptions_repo=None, nodes_repo=None)  # type: ignore[arg-type]
    line = "trojan://pwd@example.com:443?sni=example.com#t1"
    parsed = manager.parse_line(line)
    assert parsed is not None
    assert parsed["protocol"] == "trojan"


def test_parse_line_anytls():
    manager = SubscriptionManager(subscriptions_repo=None, nodes_repo=None)  # type: ignore[arg-type]
    line = "anytls://mypassword@example.com:443?sni=example.com&alpn=h2,http/1.1&fp=chrome#anytls-node"
    parsed = manager.parse_line(line)
    assert parsed is not None
    assert parsed["protocol"] == "anytls"
    assert parsed["config"]["server"] == "example.com"
    assert parsed["config"]["server_port"] == 443
    assert parsed["config"]["password"] == "mypassword"
    assert parsed["config"]["tls"]["enabled"] is True
    assert parsed["config"]["tls"]["server_name"] == "example.com"
    assert parsed["config"]["tls"]["alpn"] == ["h2", "http/1.1"]
    assert parsed["config"]["tls"]["utls"]["fingerprint"] == "chrome"
    assert parsed["tag"] == "anytls-node"


def test_parse_line_vmess():
    manager = SubscriptionManager(subscriptions_repo=None, nodes_repo=None)  # type: ignore[arg-type]
    vmess_json = '{"v":"2","ps":"vmess-node","add":"example.com","port":"443","id":"11111111-1111-1111-1111-111111111111","aid":"0","scy":"auto","net":"ws","type":"none","host":"cdn.example.com","path":"/ws","tls":"tls","sni":"sni.example.com"}'
    line = "vmess://" + base64.b64encode(vmess_json.encode()).decode()
    parsed = manager.parse_line(line)
    assert parsed is not None
    assert parsed["protocol"] == "vmess"
    assert parsed["config"]["server"] == "example.com"
    assert parsed["config"]["server_port"] == 443
    assert parsed["config"]["transport"]["type"] == "ws"
    assert parsed["config"]["tls"]["enabled"] is True


def test_parse_line_legacy_vmess():
    manager = SubscriptionManager(subscriptions_repo=None, nodes_repo=None)  # type: ignore[arg-type]
    legacy = "chacha20-poly1305:fd8ea7f8-e1ba-39fa-932e-77784876ad6b@tunnel.suda-edu.com:5744"
    line = "vmess://" + base64.b64encode(legacy.encode()).decode() + "?remarks=IEPL%7CHK.2x&obfs=none"
    parsed = manager.parse_line(line)
    assert parsed is not None
    assert parsed["protocol"] == "vmess"
    assert parsed["config"]["server"] == "tunnel.suda-edu.com"
    assert parsed["config"]["server_port"] == 5744
    assert parsed["config"]["uuid"] == "fd8ea7f8-e1ba-39fa-932e-77784876ad6b"
    assert parsed["config"]["security"] == "chacha20-poly1305"
    assert parsed["config"]["tag"] == "IEPL|HK.2x"


@pytest.mark.asyncio
async def test_refresh_subscription_with_base64_vmess(monkeypatch, tmp_path):
    vmess_json = '{"v":"2","ps":"vmess-node","add":"example.com","port":"443","id":"11111111-1111-1111-1111-111111111111","aid":"0","net":"tcp","type":"none","host":"","path":"","tls":""}'
    encoded_line = "vmess://" + base64.b64encode(vmess_json.encode()).decode()
    encoded = base64.b64encode((encoded_line + "\n").encode()).decode()

    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    manager = SubscriptionManager(
        subscriptions_repo=SubscriptionsRepository(db),
        nodes_repo=NodesRepository(db),
    )

    import tsingbox.services.subscription_manager as m

    client = DummyClient(encoded, timeout=15.0, follow_redirects=True)
    monkeypatch.setattr(
        m.httpx,
        "AsyncClient",
        lambda timeout=15.0, follow_redirects=False: client,
    )

    inserted = await manager.refresh_subscription(name="vmess-demo", url="https://example.com/vmess-sub")
    assert inserted == 1

    nodes = await manager.nodes_repo.list_nodes()
    assert len(nodes) == 1
    assert nodes[0].protocol == "vmess"


@pytest.mark.asyncio
async def test_refresh_subscription_with_legacy_vmess_lines(monkeypatch, tmp_path):
    legacy_1 = "vmess://" + base64.b64encode(
        "chacha20-poly1305:fd8ea7f8-e1ba-39fa-932e-77784876ad6b@tunnel.suda-edu.com:5744".encode()
    ).decode() + "?remarks=IEPL%7CHK.2x&obfs=none"
    legacy_2 = "vmess://" + base64.b64encode(
        "chacha20-poly1305:fd8ea7f8-e1ba-39fa-932e-77784876ad6b@tunnel.suda-edu.com:5722".encode()
    ).decode() + "?remarks=IEPL%7CHKBN.2x&obfs=none"
    content = "STATUS=剩余流量：32.75GB.♥.过期时间：2026-03-16\nREMARKS=苏打\n" + legacy_1 + "\n" + legacy_2

    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    manager = SubscriptionManager(
        subscriptions_repo=SubscriptionsRepository(db),
        nodes_repo=NodesRepository(db),
    )

    import tsingbox.services.subscription_manager as m

    client = DummyClient(content, timeout=15.0, follow_redirects=True)
    monkeypatch.setattr(
        m.httpx,
        "AsyncClient",
        lambda timeout=15.0, follow_redirects=False: client,
    )

    inserted = await manager.refresh_subscription(name="legacy-vmess", url="https://example.com/legacy-vmess")
    assert inserted == 2

    nodes = await manager.nodes_repo.list_nodes()
    assert len(nodes) == 2
    assert {node.protocol for node in nodes} == {"vmess"}


class HTTPErrorResponse:
    text = ""

    def raise_for_status(self):
        req = httpx.Request("GET", "https://example.com/sub")
        resp = httpx.Response(status_code=403, request=req)
        raise httpx.HTTPStatusError("forbidden", request=req, response=resp)


class HTTPErrorClient:
    def __init__(self, *, timeout: float = 15.0, follow_redirects: bool = False):
        self.timeout = timeout
        self.follow_redirects = follow_redirects

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None):
        return HTTPErrorResponse()


class TimeoutClient:
    def __init__(self, *, timeout: float = 15.0, follow_redirects: bool = False):
        self.timeout = timeout
        self.follow_redirects = follow_redirects

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None):
        req = httpx.Request("GET", url)
        raise httpx.ReadTimeout("timeout", request=req)


@pytest.mark.asyncio
async def test_refresh_subscription_http_error(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    manager = SubscriptionManager(
        subscriptions_repo=SubscriptionsRepository(db),
        nodes_repo=NodesRepository(db),
    )

    import tsingbox.services.subscription_manager as m

    monkeypatch.setattr(
        m.httpx,
        "AsyncClient",
        lambda timeout=15.0, follow_redirects=False: HTTPErrorClient(
            timeout=timeout,
            follow_redirects=follow_redirects,
        ),
    )

    with pytest.raises(SubscriptionHTTPError) as exc_info:
        await manager.refresh_subscription(name="demo", url="https://example.com/sub")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_refresh_subscription_timeout(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    manager = SubscriptionManager(
        subscriptions_repo=SubscriptionsRepository(db),
        nodes_repo=NodesRepository(db),
    )

    import tsingbox.services.subscription_manager as m

    monkeypatch.setattr(
        m.httpx,
        "AsyncClient",
        lambda timeout=15.0, follow_redirects=False: TimeoutClient(
            timeout=timeout,
            follow_redirects=follow_redirects,
        ),
    )

    with pytest.raises(SubscriptionNetworkError):
        await manager.refresh_subscription(name="demo", url="https://example.com/sub")


@pytest.mark.asyncio
async def test_refresh_subscription_no_valid_nodes(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    manager = SubscriptionManager(
        subscriptions_repo=SubscriptionsRepository(db),
        nodes_repo=NodesRepository(db),
    )

    import tsingbox.services.subscription_manager as m

    monkeypatch.setattr(
        m.httpx,
        "AsyncClient",
        lambda timeout=15.0, follow_redirects=False: DummyClient(
            "invalid-line",
            timeout=timeout,
            follow_redirects=follow_redirects,
        ),
    )

    with pytest.raises(SubscriptionParseError):
        await manager.refresh_subscription(name="demo", url="https://example.com/sub")
