from __future__ import annotations

import base64

import httpx

SUBSCRIPTION_HEADERS = {
    "User-Agent": "clash-verge/2.2.3",
    "Accept": "text/plain, application/octet-stream, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.services.parsers.base import ParseError
from tsingbox.services.parsers.trojan import TrojanParser
from tsingbox.services.parsers.vless import VlessParser
from tsingbox.services.parsers.vmess import VmessParser


class SubscriptionError(RuntimeError):
    pass


class SubscriptionValidationError(SubscriptionError):
    pass


class SubscriptionHTTPError(SubscriptionError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP 状态错误: {status_code}")


class SubscriptionNetworkError(SubscriptionError):
    pass


class SubscriptionParseError(SubscriptionError):
    pass


class SubscriptionManager:
    def __init__(
        self,
        *,
        subscriptions_repo: SubscriptionsRepository,
        nodes_repo: NodesRepository,
    ) -> None:
        self.subscriptions_repo = subscriptions_repo
        self.nodes_repo = nodes_repo
        self._parsers = {
            "vless://": VlessParser(),
            "trojan://": TrojanParser(),
            "vmess://": VmessParser(),
        }

    async def refresh_subscription(self, *, name: str, url: str) -> int:
        if not name or not url:
            raise SubscriptionValidationError("参数缺失：请填写订阅名称和 URL")

        text = await self.fetch(url)
        lines = self._to_lines(text)
        parsed_nodes: list[dict] = []
        for line in lines:
            try:
                item = self.parse_line(line)
            except ParseError as exc:
                raise SubscriptionParseError(f"节点解析失败: {exc}") from exc
            if item is not None:
                parsed_nodes.append(item)

        if not parsed_nodes:
            raise SubscriptionParseError("解析后无有效节点")

        _, inserted = await self.subscriptions_repo.upsert_and_replace_nodes(
            name=name,
            url=url,
            nodes=parsed_nodes,
        )
        if inserted == 0:
            raise SubscriptionParseError("解析后无有效节点")
        return inserted

    async def fetch(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url, headers=SUBSCRIPTION_HEADERS)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                raise SubscriptionHTTPError(status_code) from exc
            except httpx.TimeoutException as exc:
                raise SubscriptionNetworkError("请求超时，请检查网络连接") from exc
            except httpx.RequestError as exc:
                raise SubscriptionNetworkError("连接失败，请检查网络或订阅地址") from exc
            return resp.text.strip()

    def _to_lines(self, content: str) -> list[str]:
        text = content.strip()
        if not text:
            return []

        if "\n" not in text and not text.startswith(("vless://", "trojan://", "vmess://")):
            try:
                decoded = base64.b64decode(text + "===", validate=False).decode("utf-8", errors="ignore")
                if any(prefix in decoded for prefix in ("vless://", "trojan://", "vmess://")):
                    text = decoded
            except Exception:
                pass

        return [line.strip() for line in text.splitlines() if line.strip()]

    def parse_line(self, line: str) -> dict | None:
        for prefix, parser in self._parsers.items():
            if line.startswith(prefix):
                config = parser.parse(line)
                return {
                    "tag": config["tag"],
                    "protocol": config["type"],
                    "config": config,
                }
        return None
