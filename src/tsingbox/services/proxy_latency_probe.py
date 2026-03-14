from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

import httpx

PROXY_PROBE_URL = "https://cp.cloudflare.com/generate_204"


class ProxyProbeStatus(StrEnum):
    UNTESTED = "untested"
    TESTING = "testing"
    OK = "ok"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class ProxyProbeResult:
    status: ProxyProbeStatus
    latency_ms: int | None = None

    @property
    def display_text(self) -> str:
        if self.status is ProxyProbeStatus.UNTESTED:
            return "未测试"
        if self.status is ProxyProbeStatus.TESTING:
            return "测试中"
        if self.status is ProxyProbeStatus.OK and self.latency_ms is not None:
            return f"{self.latency_ms}ms"
        if self.status is ProxyProbeStatus.TIMEOUT:
            return "超时"
        if self.status is ProxyProbeStatus.UNAVAILABLE:
            return "不可用"
        return "未测试"


class ProxyLatencyProbe:
    def __init__(self, *, timeout: float = 5.0, probe_url: str = PROXY_PROBE_URL) -> None:
        self.timeout = timeout
        self.probe_url = probe_url

    async def probe(self, *, proxy_url: str) -> ProxyProbeResult:
        transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(transport=transport, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(self.probe_url)
                response.raise_for_status()
        except httpx.TimeoutException:
            return ProxyProbeResult(status=ProxyProbeStatus.TIMEOUT)
        except httpx.RequestError:
            return ProxyProbeResult(status=ProxyProbeStatus.UNAVAILABLE)
        except httpx.HTTPStatusError:
            return ProxyProbeResult(status=ProxyProbeStatus.UNAVAILABLE)

        latency_ms = max(0, round((perf_counter() - started_at) * 1000))
        return ProxyProbeResult(status=ProxyProbeStatus.OK, latency_ms=latency_ms)
