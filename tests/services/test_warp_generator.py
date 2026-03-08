import httpx
import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.warp_generator import WarpGenerator, WarpHTTPError, WarpResponseError


class DummyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "config": {
                "interface": {"addresses": {"v4": "172.16.0.2/32", "v6": "2606:4700:110::2/128"}},
                "peers": [
                    {
                        "public_key": "peer-public-key",
                        "endpoint": "engage.cloudflareclient.com:2408",
                        "allowed_ips": ["0.0.0.0/0", "::/0"],
                        "reserved": [7, 8, 9],
                    }
                ],
            }
        }


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return DummyResponse()


@pytest.mark.asyncio
async def test_generate_and_store_logs_full_api_response(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    logs: list[str] = []
    gen = WarpGenerator(repo, log_callback=logs.append)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: DummyClient())
    await gen.generate_and_store()

    assert len(logs) == 1
    assert logs[0].startswith("WARP API 响应: ")
    assert '"config"' in logs[0]
    assert '"public_key":"peer-public-key"' in logs[0]


@pytest.mark.asyncio
async def test_generate_and_store(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: DummyClient())
    account = await gen.generate_and_store()

    assert account.local_address_v4 == "172.16.0.2/32"
    assert account.peer_public_key == "peer-public-key"
    assert account.peer_endpoint_host == "engage.cloudflareclient.com"
    assert account.peer_endpoint_port == 2408
    assert account.peer_allowed_ips == '["0.0.0.0/0", "::/0"]'
    loaded = await repo.get_account()
    assert loaded is not None
    assert loaded.reserved == "[7, 8, 9]"
    assert loaded.peer_public_key == "peer-public-key"
    assert loaded.peer_endpoint_host == "engage.cloudflareclient.com"
    assert loaded.peer_endpoint_port == 2408
    assert loaded.peer_allowed_ips == '["0.0.0.0/0", "::/0"]'


class WarpHTTPErrorResponse:
    def raise_for_status(self):
        req = httpx.Request("POST", "https://api.cloudflareclient.com/v0a4005/reg")
        resp = httpx.Response(status_code=429, request=req)
        raise httpx.HTTPStatusError("too many requests", request=req, response=resp)

    def json(self):
        return {}


class WarpHTTPErrorClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return WarpHTTPErrorResponse()


class NestedEndpointResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "config": {
                "interface": {"addresses": {"v4": "172.16.0.2/32", "v6": "2606:4700:110::2/128"}},
                "peers": [
                    {
                        "public_key": "peer-public-key",
                        "endpoint": {
                            "host": "engage.cloudflareclient.com",
                            "port": 2408,
                        },
                        "allowed_ips": ["0.0.0.0/0", "::/0"],
                        "reserved": [7, 8, 9],
                    }
                ],
            }
        }


class WgcfStyleEndpointResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "config": {
                "interface": {"addresses": {"v4": "172.16.0.2", "v6": "2606:4700:110::2"}},
                "peers": [
                    {
                        "public_key": "peer-public-key",
                        "endpoint": {
                            "host": "engage.cloudflareclient.com:2408",
                            "ports": [2408, 500, 1701, 4500],
                            "v4": "162.159.192.10:0",
                            "v6": "[2606:4700:d0::a29f:c00a]:0",
                        },
                        "reserved": [7, 8, 9],
                    }
                ],
            }
        }


class NestedEndpointClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return NestedEndpointResponse()


class WgcfStyleEndpointClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return WgcfStyleEndpointResponse()


class MissingAllowedIpsResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "config": {
                "interface": {"addresses": {"v4": "172.16.0.2/32", "v6": "2606:4700:110::2/128"}},
                "peers": [
                    {
                        "public_key": "peer-public-key",
                        "endpoint": "engage.cloudflareclient.com:2408",
                        "reserved": [7, 8, 9],
                    }
                ],
            }
        }


class MissingAllowedIpsClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return MissingAllowedIpsResponse()


class InvalidEndpointResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "config": {
                "interface": {"addresses": {"v4": "172.16.0.2/32", "v6": "2606:4700:110::2/128"}},
                "peers": [
                    {
                        "public_key": "peer-public-key",
                        "endpoint": {"unexpected": True},
                        "allowed_ips": ["0.0.0.0/0", "::/0"],
                        "reserved": [7, 8, 9],
                    }
                ],
            }
        }


class InvalidEndpointClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return InvalidEndpointResponse()


class MissingFieldResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"config": {"interface": {}, "peers": []}}


class MissingFieldClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return MissingFieldResponse()


@pytest.mark.asyncio
async def test_generate_and_store_accepts_nested_endpoint(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: NestedEndpointClient())
    account = await gen.generate_and_store()

    assert account.peer_endpoint_host == "engage.cloudflareclient.com"
    assert account.peer_endpoint_port == 2408


@pytest.mark.asyncio
async def test_generate_and_store_prefers_wgcf_style_endpoint_host(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: WgcfStyleEndpointClient())
    account = await gen.generate_and_store()

    assert account.peer_endpoint_host == "engage.cloudflareclient.com"
    assert account.peer_endpoint_port == 2408
    assert account.peer_allowed_ips == '["0.0.0.0/0", "::/0"]'


@pytest.mark.asyncio
async def test_generate_and_store_defaults_missing_allowed_ips(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: MissingAllowedIpsClient())
    account = await gen.generate_and_store()

    assert account.peer_allowed_ips == '["0.0.0.0/0", "::/0"]'


@pytest.mark.asyncio
async def test_generate_and_store_http_error(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: WarpHTTPErrorClient())

    with pytest.raises(WarpHTTPError) as exc_info:
        await gen.generate_and_store()
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_generate_and_store_invalid_endpoint_includes_peer_summary(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: InvalidEndpointClient())

    with pytest.raises(WarpResponseError) as exc_info:
        await gen.generate_and_store()

    assert "缺少有效的 peer endpoint" in str(exc_info.value)
    assert "endpoint" in str(exc_info.value)
    assert "unexpected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_and_store_missing_fields(monkeypatch, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = WarpAccountsRepository(db)
    gen = WarpGenerator(repo)

    import tsingbox.services.warp_generator as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout=20.0: MissingFieldClient())

    with pytest.raises(WarpResponseError):
        await gen.generate_and_store()
