from __future__ import annotations

import json

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from tsingbox.data.models import WarpAccount
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository

WARP_REGISTER_URL = "https://api.cloudflareclient.com/v0a4005/reg"


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
    def __init__(self, repo: WarpAccountsRepository) -> None:
        self.repo = repo

    def _normalize_prefix(self, value: str | None, fallback: str) -> str:
        text = (value or "").strip()
        if not text:
            return fallback
        if "/" in text:
            return text
        return f"{text}/32" if ":" not in text else f"{text}/128"

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

        config = data.get("config")
        interface = config.get("interface") if isinstance(config, dict) else None
        addresses = interface.get("addresses") if isinstance(interface, dict) else None
        peers = config.get("peers") if isinstance(config, dict) else None
        if not isinstance(addresses, dict):
            raise WarpResponseError("Cloudflare 响应缺少 interface.addresses")
        if not isinstance(peers, list) or not peers:
            raise WarpResponseError("Cloudflare 响应缺少 peers")

        first_peer = peers[0] if isinstance(peers[0], dict) else {}
        peer_reserved = first_peer.get("reserved", [0, 0, 0])

        try:
            return await self.repo.upsert_account(
                private_key=private_key_b64,
                local_address_v4=self._normalize_prefix(addresses.get("v4"), "172.16.0.2/32"),
                local_address_v6=self._normalize_prefix(addresses.get("v6"), "2606:4700:110:8765::2/128"),
                reserved=json.dumps(peer_reserved),
            )
        except Exception as exc:  # noqa: BLE001
            raise WarpStoreError(f"WARP 账户保存失败: {exc}") from exc

    def _b64(self, raw: bytes) -> str:
        import base64

        return base64.b64encode(raw).decode("utf-8")
