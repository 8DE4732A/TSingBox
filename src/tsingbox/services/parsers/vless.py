from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from tsingbox.services.parsers.base import BaseParser, ParseError


class VlessParser(BaseParser):
    scheme = "vless"

    def parse(self, uri: str) -> dict:
        parsed = urlparse(uri)
        if parsed.scheme != self.scheme:
            raise ParseError("非 vless 链接")
        if not parsed.hostname or not parsed.port or not parsed.username:
            raise ParseError("vless 缺少主机/端口/uuid")

        query = parse_qs(parsed.query)
        tag = unquote(parsed.fragment) if parsed.fragment else f"vless-{parsed.hostname}"
        security = query.get("security", ["none"])[0]

        outbound = {
            "type": "vless",
            "tag": tag,
            "server": parsed.hostname,
            "server_port": parsed.port,
            "uuid": parsed.username,
            "flow": query.get("flow", [""])[0] or None,
            "packet_encoding": query.get("packetEncoding", ["xudp"])[0],
        }

        if security == "reality":
            outbound["tls"] = {
                "enabled": True,
                "server_name": query.get("sni", [parsed.hostname])[0],
                "reality": {
                    "enabled": True,
                    "public_key": query.get("pbk", [""])[0],
                    "short_id": query.get("sid", [""])[0],
                },
                "utls": {"enabled": True, "fingerprint": query.get("fp", ["chrome"])[0]},
            }
        elif security == "tls":
            outbound["tls"] = {
                "enabled": True,
                "server_name": query.get("sni", [parsed.hostname])[0],
            }

        return outbound
