from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from tsingbox.services.parsers.base import BaseParser, ParseError


class AnytlsParser(BaseParser):
    scheme = "anytls"

    def parse(self, uri: str) -> dict:
        parsed = urlparse(uri)
        if parsed.scheme != self.scheme:
            raise ParseError("非 anytls 链接")
        if not parsed.hostname or not parsed.port or not parsed.username:
            raise ParseError("anytls 缺少主机/端口/密码")

        query = parse_qs(parsed.query)
        tag = unquote(parsed.fragment) if parsed.fragment else f"anytls-{parsed.hostname}"

        outbound = {
            "type": "anytls",
            "tag": tag,
            "server": parsed.hostname,
            "server_port": parsed.port,
            "password": unquote(parsed.username),
        }

        sni = query.get("sni", [parsed.hostname])[0]
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
        }

        alpn = query.get("alpn", [])
        if alpn:
            alpn_list = []
            for a in alpn:
                alpn_list.extend(a.split(","))
            outbound["tls"]["alpn"] = alpn_list

        fp = query.get("fp", [])
        if fp:
            outbound["tls"]["utls"] = {"enabled": True, "fingerprint": fp[0]}

        return outbound
