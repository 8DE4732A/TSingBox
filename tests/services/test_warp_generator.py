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
                "peers": [{"reserved": [7, 8, 9]}],
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
    loaded = await repo.get_account()
    assert loaded is not None
    assert loaded.reserved == "[7, 8, 9]"


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
