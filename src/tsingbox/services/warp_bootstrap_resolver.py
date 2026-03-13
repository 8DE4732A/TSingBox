from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable

import httpx

from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository

DOH_URL = "https://cloudflare-dns.com/dns-query"
DOH_HEADERS = {"accept": "application/dns-json"}
DOH_QUERY_TYPES = ("A", "AAAA")


class WarpBootstrapResolveError(RuntimeError):
    pass


class WarpBootstrapResolver:
    def __init__(
        self,
        warp_repo: WarpAccountsRepository,
        *,
        log_callback: Callable[[str], None] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.warp_repo = warp_repo
        self.log_callback = log_callback or (lambda _: None)
        self.timeout = timeout

    async def resolve_hosts(self, *, proxy_url: str, hosts: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for host in hosts:
            normalized_host = host.strip()
            if not normalized_host:
                continue
            if self._is_ip_address(normalized_host):
                continue

            addresses = None
            last_exc = None
            for attempt in range(5):
                try:
                    addresses = await self._resolve_host_via_doh(normalized_host, proxy_url=proxy_url)
                    break
                except WarpBootstrapResolveError as exc:
                    last_exc = exc
                    if attempt < 4:
                        await asyncio.sleep(1.0)

            if not addresses:
                if last_exc:
                    raise last_exc
                raise WarpBootstrapResolveError(f"通过临时代理解析目标域名失败: {normalized_host}")
            result[normalized_host] = addresses
        self.log_callback(f"阶段域名解析结果: {result}")
        return result

    async def resolve_predefined_hosts(self, *, proxy_url: str) -> dict[str, list[str]]:
        account = await self.warp_repo.get_account()
        if account is None:
            raise WarpBootstrapResolveError("WARP 账户不存在，无法执行预解析")

        host = (account.peer_endpoint_host or "").strip()
        if not host:
            raise WarpBootstrapResolveError("WARP peer endpoint host 缺失，无法执行预解析")

        if self._is_ip_address(host):
            self.log_callback(f"WARP endpoint 已是 IP，跳过预解析: {host}")
            return {}

        result = await self.resolve_hosts(proxy_url=proxy_url, hosts=[host])
        self.log_callback(f"WARP 域名解析结果: {result}")
        return result

    async def _resolve_host_via_doh(self, host: str, *, proxy_url: str) -> list[str]:
        transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
        results: list[str] = []
        try:
            async with httpx.AsyncClient(transport=transport, timeout=self.timeout) as client:
                for record_type in DOH_QUERY_TYPES:
                    response = await client.get(
                        DOH_URL,
                        params={"name": host, "type": record_type},
                        headers=DOH_HEADERS,
                    )
                    addresses = self._extract_addresses_from_doh_response(host, record_type, response)
                    for address in addresses:
                        if address not in results:
                            results.append(address)
        except httpx.TimeoutException as exc:
            raise WarpBootstrapResolveError(f"通过临时代理解析目标域名超时: {host}") from exc
        except httpx.RequestError as exc:
            raise WarpBootstrapResolveError(f"通过临时代理解析目标域名失败: {host}: {exc}") from exc

        if not results:
            raise WarpBootstrapResolveError(f"通过临时代理解析目标域名失败: {host}")
        return results

    def _extract_addresses_from_doh_response(self, host: str, record_type: str, response: httpx.Response) -> list[str]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WarpBootstrapResolveError(f"DoH 响应不是合法 JSON: {host} ({record_type})") from exc

        if not isinstance(payload, dict):
            raise WarpBootstrapResolveError(f"DoH 响应格式无效: {host} ({record_type})")

        status = payload.get("Status")
        if status not in (0, "0", None):
            raise WarpBootstrapResolveError(f"DoH 查询失败: {host} ({record_type}), status={status}")

        answers = payload.get("Answer")
        if answers is None:
            return []
        if not isinstance(answers, list):
            raise WarpBootstrapResolveError(f"DoH Answer 格式无效: {host} ({record_type})")

        results: list[str] = []
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            data = answer.get("data")
            if not isinstance(data, str) or not data.strip():
                continue
            try:
                address = str(ipaddress.ip_address(data.strip()))
            except ValueError:
                continue
            if address not in results:
                results.append(address)
        return results

    def _is_ip_address(self, value: str) -> bool:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return False
        return True

    async def resolve_via_socket(self, host: str, *, port: int) -> list[str]:
        infos = await socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        result: list[str] = []
        for family, _, _, _, sockaddr in infos:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            address = sockaddr[0]
            if address not in result:
                result.append(address)
        return result
