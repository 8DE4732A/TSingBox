from __future__ import annotations

import json
import pprint
from collections.abc import Callable

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from tsingbox.data.models import WarpAccount
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository

WARP_REGISTER_URL = "https://api.cloudflareclient.com/v0a4005/reg"
DEFAULT_PEER_ALLOWED_IPS = ["0.0.0.0/0", "::/0"]


class WarpError(RuntimeError):
    pass


class WarpNetworkError(WarpError):
    pass


class WarpHTTPError(WarpError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"WARP 注册 HTTP 错误: {status_code}")


class WarpResponseError(WarpError):
    pass


class WarpStoreError(WarpError):
    pass


class WarpGenerator:
    def __init__(
        self,
        repo: WarpAccountsRepository,
        *,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.repo = repo
        self.log_callback = log_callback

    def _summarize_peer(self, peer: object) -> str:
        if not isinstance(peer, dict):
            return repr(peer)
        return pprint.pformat(
            {
                "keys": sorted(peer.keys()),
                "endpoint": peer.get("endpoint"),
                "host": peer.get("host"),
                "address": peer.get("address"),
                "ip": peer.get("ip"),
                "port": peer.get("port"),
                "public_key": peer.get("public_key"),
                "allowed_ips": peer.get("allowed_ips"),
                "reserved": peer.get("reserved"),
            },
            compact=True,
            width=120,
        )

    def _normalize_prefix(self, value: str | None, fallback: str) -> str:
        text = (value or "").strip()
        if not text:
            return fallback
        if "/" in text:
            return text
        return f"{text}/32" if ":" not in text else f"{text}/128"

    def _parse_host_port(self, host: object, port: object) -> tuple[str, int] | None:
        if not isinstance(host, str) or not host.strip():
            return None
        if isinstance(port, int):
            return host.strip(), port
        if isinstance(port, str) and port.strip().isdigit():
            return host.strip(), int(port.strip())
        return None

    def _parse_endpoint_string(self, endpoint: str) -> tuple[str, int]:
        text = endpoint.strip()
        if not text:
            raise WarpResponseError("Cloudflare 响应缺少 peer endpoint")
        if text.startswith("["):
            host, separator, port_text = text.rpartition("]:")
            if not separator:
                raise WarpResponseError("Cloudflare peer endpoint 格式无效")
            host = host[1:]
        else:
            host, separator, port_text = text.rpartition(":")
            if not separator:
                raise WarpResponseError("Cloudflare peer endpoint 格式无效")
        if not host.strip() or not port_text.strip().isdigit():
            raise WarpResponseError("Cloudflare peer endpoint 格式无效")
        return host.strip(), int(port_text.strip())

    def _parse_peer_endpoint(self, peer: dict) -> tuple[str, int]:
        endpoint = peer.get("endpoint")
        if isinstance(endpoint, str):
            return self._parse_endpoint_string(endpoint)

        if isinstance(endpoint, dict):
            for key in ("host", "address", "ip"):
                value = endpoint.get(key)
                if isinstance(value, str) and value.strip():
                    try:
                        return self._parse_endpoint_string(value)
                    except WarpResponseError:
                        direct = self._parse_host_port(value, endpoint.get("port"))
                        if direct is not None:
                            return direct
            for key in ("v4", "v6"):
                nested = endpoint.get(key)
                if isinstance(nested, str):
                    return self._parse_endpoint_string(nested)
                if isinstance(nested, dict):
                    for nested_key in ("host", "address", "ip"):
                        nested_value = nested.get(nested_key)
                        if isinstance(nested_value, str) and nested_value.strip():
                            try:
                                return self._parse_endpoint_string(nested_value)
                            except WarpResponseError:
                                parsed = self._parse_host_port(nested_value, nested.get("port"))
                                if parsed is not None:
                                    return parsed

        direct_peer_fields = self._parse_host_port(
            peer.get("host") or peer.get("address") or peer.get("ip"),
            peer.get("port"),
        )
        if direct_peer_fields is not None:
            return direct_peer_fields

        raise WarpResponseError(
            f"Cloudflare 响应缺少有效的 peer endpoint，peer={self._summarize_peer(peer)}"
        )

    def _parse_allowed_ips(self, allowed_ips: object) -> str:
        if allowed_ips is None:
            return json.dumps(DEFAULT_PEER_ALLOWED_IPS)
        if not isinstance(allowed_ips, list) or not allowed_ips:
            raise WarpResponseError(f"Cloudflare peer allowed_ips 格式无效: {allowed_ips!r}")
        normalized = [item.strip() for item in allowed_ips if isinstance(item, str) and item.strip()]
        if not normalized:
            raise WarpResponseError(f"Cloudflare peer allowed_ips 格式无效: {allowed_ips!r}")
        return json.dumps(normalized)

    async def generate_and_store(self) -> WarpAccount:
        private_key = X25519PrivateKey.generate()
        private_key_raw = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_key_b64 = self._b64(private_key_raw)

        payload = {
            "install_id": "",
            "fcm_token": "",
            "tos": "2023-10-10T00:00:00.000Z",
            "type": "Android",
            "locale": "en_US",
            "warp_enabled": True,
            "key": self._b64(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ),
        }
        headers = {
            "User-Agent": "okhttp/3.12.1",
            "Content-Type": "application/json; charset=UTF-8",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(WARP_REGISTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                raise WarpHTTPError(status_code) from exc
            except httpx.TimeoutException as exc:
                raise WarpNetworkError("WARP 注册超时") from exc
            except httpx.RequestError as exc:
                raise WarpNetworkError("WARP 注册网络失败") from exc

            data = resp.json()

        if self.log_callback is not None:
            self.log_callback(
                "WARP API 响应: " + json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            )

        config = data.get("config")
        interface = config.get("interface") if isinstance(config, dict) else None
        addresses = interface.get("addresses") if isinstance(interface, dict) else None
        peers = config.get("peers") if isinstance(config, dict) else None
        if not isinstance(addresses, dict):
            raise WarpResponseError("Cloudflare 响应缺少 interface.addresses")
        if not isinstance(peers, list) or not peers:
            raise WarpResponseError("Cloudflare 响应缺少 peers")

        first_peer = peers[0] if isinstance(peers[0], dict) else {}
        peer_public_key = first_peer.get("public_key")
        if not isinstance(peer_public_key, str) or not peer_public_key.strip():
            raise WarpResponseError("Cloudflare 响应缺少 peer public_key")

        peer_reserved = first_peer.get("reserved", [0, 0, 0])
        if not isinstance(peer_reserved, list):
            raise WarpResponseError("Cloudflare 响应缺少有效的 peer reserved")

        peer_endpoint_host, peer_endpoint_port = self._parse_peer_endpoint(first_peer)
        peer_allowed_ips = self._parse_allowed_ips(first_peer.get("allowed_ips"))

        try:
            return await self.repo.upsert_account(
                private_key=private_key_b64,
                local_address_v4=self._normalize_prefix(addresses.get("v4"), "172.16.0.2/32"),
                local_address_v6=self._normalize_prefix(addresses.get("v6"), "2606:4700:110:8765::2/128"),
                reserved=json.dumps(peer_reserved),
                peer_public_key=peer_public_key.strip(),
                peer_endpoint_host=peer_endpoint_host,
                peer_endpoint_port=peer_endpoint_port,
                peer_allowed_ips=peer_allowed_ips,
            )
        except Exception as exc:  # noqa: BLE001
            raise WarpStoreError(f"WARP 账户保存失败: {exc}") from exc

    def _b64(self, raw: bytes) -> str:
        import base64

        return base64.b64encode(raw).decode("utf-8")
