from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, unquote, urlparse

from tsingbox.services.parsers.base import BaseParser, ParseError


class VmessParser(BaseParser):
    scheme = "vmess"

    def parse(self, uri: str) -> dict:
        parsed = urlparse(uri)
        if parsed.scheme != self.scheme:
            raise ParseError("非 vmess 链接")

        encoded = parsed.netloc + parsed.path
        encoded = encoded.strip()
        if not encoded:
            raise ParseError("vmess 缺少配置内容")

        try:
            raw = base64.b64decode(encoded + "===", validate=False).decode("utf-8", errors="strict")
        except Exception as exc:  # noqa: BLE001
            raise ParseError("vmess 配置不是有效的 base64 文本") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return self._parse_legacy_payload(raw, parsed.query)
        return self._parse_json_payload(payload)

    def _parse_json_payload(self, payload: dict) -> dict:
        server = str(payload.get("add", "")).strip()
        port_text = str(payload.get("port", "")).strip()
        uuid = str(payload.get("id", "")).strip()
        if not server or not port_text or not uuid:
            raise ParseError("vmess 缺少主机/端口/uuid")

        try:
            server_port = int(port_text)
        except ValueError as exc:
            raise ParseError("vmess 端口无效") from exc

        tag = self._resolve_json_tag(payload, server)
        outbound = {
            "type": "vmess",
            "tag": tag,
            "server": server,
            "server_port": server_port,
            "uuid": uuid,
            "security": str(payload.get("scy", "auto") or "auto"),
            "alter_id": self._resolve_alter_id(payload.get("aid")),
        }

        transport = self._resolve_json_transport(payload)
        if transport is not None:
            outbound["transport"] = transport

        tls = self._resolve_json_tls(payload, server)
        if tls is not None:
            outbound["tls"] = tls

        return outbound

    def _parse_legacy_payload(self, raw: str, query_string: str) -> dict:
        try:
            security, rest = raw.split(":", 1)
            uuid, server_part = rest.split("@", 1)
            server, port_text = server_part.rsplit(":", 1)
        except ValueError as exc:
            raise ParseError("旧式 vmess 缺少 method/uuid/host/port") from exc

        security = security.strip()
        uuid = uuid.strip()
        server = server.strip()
        port_text = port_text.strip()
        if not security or not uuid or not server or not port_text:
            raise ParseError("旧式 vmess 缺少 method/uuid/host/port")

        try:
            server_port = int(port_text)
        except ValueError as exc:
            raise ParseError("旧式 vmess 端口无效") from exc

        query = parse_qs(query_string)
        remarks = query.get("remarks", [""])[0]
        obfs = str(query.get("obfs", ["none"])[0] or "none").strip().lower()

        outbound = {
            "type": "vmess",
            "tag": unquote(remarks) if remarks else f"vmess-{server}",
            "server": server,
            "server_port": server_port,
            "uuid": uuid,
            "security": security,
            "alter_id": 0,
        }

        tls = self._resolve_legacy_tls(query, server)
        if tls is not None:
            outbound["tls"] = tls

        transport = self._resolve_legacy_transport(query, obfs)
        if transport is not None:
            outbound["transport"] = transport

        return outbound

    def _resolve_json_tag(self, payload: dict, server: str) -> str:
        ps = str(payload.get("ps", "")).strip()
        return unquote(ps) if ps else f"vmess-{server}"

    def _resolve_alter_id(self, value: object) -> int:
        try:
            return int(str(value or 0))
        except ValueError:
            return 0

    def _resolve_json_transport(self, payload: dict) -> dict | None:
        network = str(payload.get("net", "tcp") or "tcp").lower()
        host = str(payload.get("host", "")).strip()
        path = str(payload.get("path", "")).strip()
        transport_type = str(payload.get("type", "")).strip()

        if network == "ws":
            transport: dict[str, object] = {"type": "ws"}
            if path:
                transport["path"] = path
            if host:
                transport["headers"] = {"Host": host}
            return transport
        if network == "grpc":
            transport = {"type": "grpc"}
            if path:
                transport["service_name"] = path
            return transport
        if network == "http":
            transport = {"type": "http"}
            if path:
                transport["path"] = path
            if host:
                transport["host"] = [host]
            return transport
        if network in {"tcp", "h2"}:
            if transport_type == "http" and (host or path):
                transport = {"type": "http"}
                if path:
                    transport["path"] = path
                if host:
                    transport["host"] = [host]
                return transport
            return None
        return None

    def _resolve_json_tls(self, payload: dict, server: str) -> dict | None:
        tls_value = str(payload.get("tls", "")).strip().lower()
        if tls_value not in {"tls", "1", "true"}:
            return None

        server_name = str(payload.get("sni", "")).strip() or str(payload.get("host", "")).strip() or server
        tls: dict[str, object] = {
            "enabled": True,
            "server_name": server_name,
        }

        fingerprint = str(payload.get("fp", "")).strip()
        if fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": fingerprint}

        alpn = str(payload.get("alpn", "")).strip()
        if alpn:
            tls["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]

        return tls

    def _resolve_legacy_tls(self, query: dict[str, list[str]], server: str) -> dict | None:
        tls_value = str(query.get("tls", [""])[0] or "").strip().lower()
        if tls_value not in {"tls", "1", "true"}:
            return None

        server_name = str(query.get("peer", [""])[0] or query.get("sni", [""])[0] or server).strip()
        return {
            "enabled": True,
            "server_name": server_name,
        }

    def _resolve_legacy_transport(self, query: dict[str, list[str]], obfs: str) -> dict | None:
        if obfs == "websocket":
            path = str(query.get("path", [""])[0] or "").strip()
            host = str(query.get("obfsParam", [""])[0] or query.get("host", [""])[0] or "").strip()
            transport: dict[str, object] = {"type": "ws"}
            if path:
                transport["path"] = path
            if host:
                transport["headers"] = {"Host": host}
            return transport
        if obfs in {"none", "", "plain"}:
            return None
        return None
