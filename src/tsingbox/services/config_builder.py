from __future__ import annotations

import json

from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.config_models import DNSConfig, RouteConfig, RouteRule, SingBoxConfig

WARP_PEER_PUBLIC_KEY = "bmXOC+F1V4JxA8S8d+QsbNf8j2RzYj6JQ5t8V9hV7iE="
WARP_ENDPOINT = "162.159.193.10"
WARP_PORT = 2408


class ConfigBuilder:
    def __init__(
        self,
        *,
        nodes_repo: NodesRepository,
        preferences_repo: PreferencesRepository,
        warp_repo: WarpAccountsRepository,
    ) -> None:
        self.nodes_repo = nodes_repo
        self.preferences_repo = preferences_repo
        self.warp_repo = warp_repo

    def _normalize_prefix(self, value: str) -> str:
        text = value.strip()
        if "/" in text:
            return text
        return f"{text}/32" if ":" not in text else f"{text}/128"

    async def build_config(self) -> SingBoxConfig:
        pref = await self.preferences_repo.get_preferences()
        if pref.selected_node_id is None:
            raise ValueError("尚未选择节点")

        node = await self.nodes_repo.get_node(pref.selected_node_id)
        if not node:
            raise ValueError("选中的节点不存在")

        node_outbound = json.loads(node.config_json)
        outbounds: list[dict] = []

        endpoints: list[dict] = []

        if pref.warp_enabled:
            warp = await self.warp_repo.get_account()
            if not warp:
                raise ValueError("已开启 WARP，但不存在 WARP 账户")
            node_outbound["tag"] = "proxy-node"
            outbounds.append(node_outbound)
            endpoints.append(
                {
                    "type": "wireguard",
                    "tag": "warp-endpoint",
                    "address": [
                        self._normalize_prefix(warp.local_address_v4),
                        self._normalize_prefix(warp.local_address_v6),
                    ],
                    "private_key": warp.private_key,
                    "peers": [
                        {
                            "address": WARP_ENDPOINT,
                            "port": WARP_PORT,
                            "public_key": WARP_PEER_PUBLIC_KEY,
                            "allowed_ips": ["0.0.0.0/0", "::/0"],
                            "reserved": json.loads(warp.reserved),
                        }
                    ],
                    "detour": "proxy-node",
                }
            )
            final_tag = "warp-endpoint"
        else:
            outbounds.append(node_outbound)
            final_tag = node_outbound["tag"]

        dns_servers = [{"type": "udp", "tag": "local", "server": "223.5.5.5", "server_port": 53}]
        if pref.dns_leak_protection:
            dns_servers = [{"type": "udp", "tag": "remote", "server": "1.1.1.1", "server_port": 53}]

        route = RouteConfig(final=final_tag)
        if pref.routing_mode == "rule":
            route.rules = [RouteRule(outbound=final_tag)]

        model = SingBoxConfig(
            dns=DNSConfig(servers=dns_servers),
            outbounds=outbounds,
            endpoints=endpoints,
            route=route,
        )
        return SingBoxConfig.model_validate(model.model_dump())
