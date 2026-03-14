from __future__ import annotations

from unittest import mock

import httpx
import pytest

from tsingbox.services.proxy_latency_probe import ProxyLatencyProbe, ProxyProbeStatus


class SuccessClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        request = httpx.Request("GET", url)
        return httpx.Response(204, request=request)


class TimeoutClient(SuccessClient):
    async def get(self, url: str):
        raise httpx.TimeoutException("timeout")


class RequestErrorClient(SuccessClient):
    async def get(self, url: str):
        raise httpx.ProxyError("proxy failed")


class HttpErrorClient(SuccessClient):
    async def get(self, url: str):
        request = httpx.Request("GET", url)
        return httpx.Response(503, request=request)


@pytest.mark.asyncio
@mock.patch("tsingbox.services.proxy_latency_probe.perf_counter", side_effect=[1.0, 1.183])
async def test_probe_returns_latency_on_success(mock_perf_counter, monkeypatch):
    import tsingbox.services.proxy_latency_probe as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", SuccessClient)

    probe = ProxyLatencyProbe(timeout=5.0)
    result = await probe.probe(proxy_url="http://127.0.0.1:7890")

    assert result.status is ProxyProbeStatus.OK
    assert result.latency_ms == 183
    assert result.display_text == "183ms"


@pytest.mark.asyncio
async def test_probe_maps_timeout(monkeypatch):
    import tsingbox.services.proxy_latency_probe as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", TimeoutClient)

    probe = ProxyLatencyProbe(timeout=5.0)
    result = await probe.probe(proxy_url="http://127.0.0.1:7890")

    assert result.status is ProxyProbeStatus.TIMEOUT
    assert result.latency_ms is None
    assert result.display_text == "超时"


@pytest.mark.asyncio
async def test_probe_maps_request_failure(monkeypatch):
    import tsingbox.services.proxy_latency_probe as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", RequestErrorClient)

    probe = ProxyLatencyProbe(timeout=5.0)
    result = await probe.probe(proxy_url="http://127.0.0.1:7890")

    assert result.status is ProxyProbeStatus.UNAVAILABLE
    assert result.latency_ms is None
    assert result.display_text == "不可用"


@pytest.mark.asyncio
async def test_probe_maps_http_status_error(monkeypatch):
    import tsingbox.services.proxy_latency_probe as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", HttpErrorClient)

    probe = ProxyLatencyProbe(timeout=5.0)
    result = await probe.probe(proxy_url="http://127.0.0.1:7890")

    assert result.status is ProxyProbeStatus.UNAVAILABLE
    assert result.latency_ms is None
    assert result.display_text == "不可用"
