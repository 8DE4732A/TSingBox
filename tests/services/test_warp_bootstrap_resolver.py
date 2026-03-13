from __future__ import annotations

import json
from unittest import mock

import httpx
import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.warp_bootstrap_resolver import WarpBootstrapResolveError, WarpBootstrapResolver


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class SuccessClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        name = params["name"]
        query_type = params["type"]
        payloads = {
            ("engage.cloudflareclient.com", "A"): {
                "Status": 0,
                "Answer": [{"data": "198.51.100.10"}],
            },
            ("engage.cloudflareclient.com", "AAAA"): {
                "Status": 0,
                "Answer": [{"data": "2606:4700:4700::1111"}],
            },
            ("next.example.com", "A"): {
                "Status": 0,
                "Answer": [{"data": "203.0.113.20"}],
            },
            ("next.example.com", "AAAA"): {
                "Status": 0,
                "Answer": [],
            },
        }
        return DummyResponse(payloads[(name, query_type)])


class EmptyAnswerClient(SuccessClient):
    async def get(self, url: str, *, params=None, headers=None):
        return DummyResponse({"Status": 0, "Answer": []})


class InvalidJSONClient(SuccessClient):
    async def get(self, url: str, *, params=None, headers=None):
        return DummyResponse(ValueError("invalid json"))


class DnsFailureClient(SuccessClient):
    async def get(self, url: str, *, params=None, headers=None):
        return DummyResponse({"Status": 2})


class TimeoutClient(SuccessClient):
    async def get(self, url: str, *, params=None, headers=None):
        raise httpx.TimeoutException("boom")


class RequestErrorClient(SuccessClient):
    async def get(self, url: str, *, params=None, headers=None):
        raise httpx.ProxyError("proxy boom")


async def _create_repo(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()
    repo = WarpAccountsRepository(db)
    await repo.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2/32",
        local_address_v6="2606:4700:110::2/128",
        reserved=json.dumps([1, 2, 3]),
        peer_public_key="peer-public-key",
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )
    return repo


@pytest.mark.asyncio
async def test_resolver_returns_predefined_hosts_via_proxy_doh(monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)
    logs: list[str] = []

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", SuccessClient)

    resolver = WarpBootstrapResolver(repo, log_callback=logs.append)
    result = await resolver.resolve_predefined_hosts(proxy_url="http://127.0.0.1:17890")

    assert result == {
        "engage.cloudflareclient.com": ["198.51.100.10", "2606:4700:4700::1111"]
    }
    assert any("WARP 域名解析结果" in line for line in logs)


@pytest.mark.asyncio
async def test_resolver_resolves_multiple_hosts_via_proxy_doh(monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", SuccessClient)

    resolver = WarpBootstrapResolver(repo)
    result = await resolver.resolve_hosts(
        proxy_url="http://127.0.0.1:17890",
        hosts=["engage.cloudflareclient.com", "next.example.com", "162.159.193.10"],
    )

    assert result == {
        "engage.cloudflareclient.com": ["198.51.100.10", "2606:4700:4700::1111"],
        "next.example.com": ["203.0.113.20"],
    }


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
async def test_resolver_raises_clear_error_when_doh_answer_empty(mock_sleep, monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", EmptyAnswerClient)

    resolver = WarpBootstrapResolver(repo)
    with pytest.raises(WarpBootstrapResolveError, match="解析目标域名失败"):
        await resolver.resolve_predefined_hosts(proxy_url="http://127.0.0.1:17890")
    assert mock_sleep.call_count == 4


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
async def test_resolver_raises_clear_error_on_invalid_doh_json(mock_sleep, monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", InvalidJSONClient)

    resolver = WarpBootstrapResolver(repo)
    with pytest.raises(WarpBootstrapResolveError, match="DoH 响应不是合法 JSON"):
        await resolver.resolve_hosts(proxy_url="http://127.0.0.1:17890", hosts=["engage.cloudflareclient.com"])
    assert mock_sleep.call_count == 4


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
async def test_resolver_raises_clear_error_on_doh_failure_status(mock_sleep, monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", DnsFailureClient)

    resolver = WarpBootstrapResolver(repo)
    with pytest.raises(WarpBootstrapResolveError, match="DoH 查询失败"):
        await resolver.resolve_hosts(proxy_url="http://127.0.0.1:17890", hosts=["engage.cloudflareclient.com"])
    assert mock_sleep.call_count == 4


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
async def test_resolver_raises_clear_error_on_timeout(mock_sleep, monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", TimeoutClient)

    resolver = WarpBootstrapResolver(repo)
    with pytest.raises(WarpBootstrapResolveError, match="超时"):
        await resolver.resolve_hosts(proxy_url="http://127.0.0.1:17890", hosts=["engage.cloudflareclient.com"])
    assert mock_sleep.call_count == 4


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
async def test_resolver_raises_clear_error_on_proxy_error(mock_sleep, monkeypatch, tmp_path):
    repo = await _create_repo(tmp_path)

    import tsingbox.services.warp_bootstrap_resolver as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", RequestErrorClient)

    resolver = WarpBootstrapResolver(repo)
    with pytest.raises(WarpBootstrapResolveError, match="失败"):
        await resolver.resolve_hosts(proxy_url="http://127.0.0.1:17890", hosts=["engage.cloudflareclient.com"])
    assert mock_sleep.call_count == 4
