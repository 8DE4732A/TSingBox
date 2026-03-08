from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from tsingbox.services.parsers.base import BaseParser, ParseError


class TrojanParser(BaseParser):
    scheme = "trojan"

    def parse(self, uri: str) -> dict:
        parsed = urlparse(uri)
        if parsed.scheme != self.scheme:
            raise ParseError("非 trojan 链接")
        if not parsed.hostname or not parsed.port or not parsed.username:
            raise ParseError("trojan 缺少主机/端口/password")

        query = parse_qs(parsed.query)
        tag = unquote(parsed.fragment) if parsed.fragment else f"trojan-{parsed.hostname}"

        outbound = {
            "type": "trojan",
            "tag": tag,
            "server": parsed.hostname,
            "server_port": parsed.port,
            "password": parsed.username,
            "tls": {
                "enabled": True,
                "server_name": query.get("sni", [parsed.hostname])[0],
            },
        }
        return outbound
