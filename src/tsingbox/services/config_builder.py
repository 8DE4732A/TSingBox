from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass

from tsingbox.data.models import Preferences, RuleFile, RoutingRule, RoutingRuleSet, WarpAccount
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
from tsingbox.data.repositories.routing_rules import RoutingRulesRepository
from tsingbox.data.repositories.routing_rule_sets import RoutingRuleSetsRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.config_models import DNSConfig, RouteConfig, RuleSetConfigEntry, SingBoxConfig
from tsingbox.services.rule_file_service import RuleFileService

WARP_PEER_PUBLIC_KEY = "bmXOC+F1V4JxA8S8d+QsbNf8j2RzYj6JQ5t8V9hV7iE="
WARP_ENDPOINT = "162.159.193.10"
WARP_PORT = 2408
WARP_ALLOWED_IPS = ["0.0.0.0/0", "::/0"]
DEFAULT_MIXED_LISTEN = "127.0.0.1"
DEFAULT_MIXED_PORT = 7890
BOOTSTRAP_MIXED_PORT = 17890
BOOTSTRAP_DNS = "223.5.5.5"
BOOTSTRAP_DNS_TAG = "bootstrap-dns"
REMOTE_DNS_TAG = "remote-dns"
DIRECT_DNS_TAG = "direct-dns"
HOSTS_DNS_TAG = "hosts-dns"
REMOTE_DNS_SERVER = "cloudflare-dns.com"
REMOTE_DNS_PATH = "/dns-query"
DIRECT_OUTBOUND_TAG = "direct"
PROXY_NODE_TAG = "proxy-node"
WARP_ENDPOINT_TAG = "warp-endpoint"


@dataclass(slots=True)
class BuildContext:
    preferences: Preferences
    node_outbound: dict
    node_server: str
    warp_account: WarpAccount | None


@dataclass(slots=True)
class BootstrapStage:
    config: SingBoxConfig
    resolve_hosts: list[str]


class ConfigBuilder:
    def __init__(
        self,
        *,
        nodes_repo: NodesRepository,
        preferences_repo: PreferencesRepository,
        routing_rule_sets_repo: RoutingRuleSetsRepository,
        routing_rules_repo: RoutingRulesRepository,
        warp_repo: WarpAccountsRepository,
        rule_file_service: RuleFileService,
    ) -> None:
        self.nodes_repo = nodes_repo
        self.preferences_repo = preferences_repo
        self.routing_rule_sets_repo = routing_rule_sets_repo
        self.routing_rules_repo = routing_rules_repo
        self.warp_repo = warp_repo
        self.rule_file_service = rule_file_service

    def _normalize_prefix(self, value: str) -> str:
        text = value.strip()
        if "/" in text:
            return text
        return f"{text}/32" if ":" not in text else f"{text}/128"

    def _is_ip_address(self, value: str) -> bool:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return False
        return True

    async def _build_context(self) -> BuildContext:
        pref = await self.preferences_repo.get_preferences()
        if pref.selected_node_id is None:
            raise ValueError("尚未选择节点")

        node = await self.nodes_repo.get_node(pref.selected_node_id)
        if not node:
            raise ValueError("选中的节点不存在")

        node_outbound = json.loads(node.config_json)
        node_server = node_outbound.get("server")
        if not isinstance(node_server, str) or not node_server.strip():
            raise ValueError("选中的节点缺少 server")

        warp_account: WarpAccount | None = None
        if pref.warp_enabled:
            warp_account = await self.warp_repo.get_account()
            if not warp_account:
                raise ValueError("已开启 WARP，但不存在 WARP 账户")

        return BuildContext(
            preferences=pref,
            node_outbound=node_outbound,
            node_server=node_server.strip(),
            warp_account=warp_account,
        )

    def _build_inbound(self, *, port: int) -> list[dict]:
        return [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": DEFAULT_MIXED_LISTEN,
                "listen_port": port,
            }
        ]

    def _build_current_layer_dns_rules(self, hosts: list[str]) -> list[dict]:
        return [
            {"server": BOOTSTRAP_DNS_TAG, "domain": [host]}
            for host in hosts
            if isinstance(host, str) and host.strip() and not self._is_ip_address(host.strip())
        ]

    def _build_next_layer_dns_rules(self, hosts: list[str]) -> list[dict]:
        domains = [host.strip() for host in hosts if isinstance(host, str) and host.strip() and not self._is_ip_address(host.strip())]
        if not domains:
            return []
        return [{"server": REMOTE_DNS_TAG, "domain": domains}]

    def _build_base_dns_rules(self, node_server: str) -> list[dict]:
        return self._build_current_layer_dns_rules([node_server])

    def _build_base_dns_servers(self) -> list[dict]:
        return [
            {
                "type": "udp",
                "tag": BOOTSTRAP_DNS_TAG,
                "server": BOOTSTRAP_DNS,
                "server_port": 53,
            },
            {
                "type": "udp",
                "tag": DIRECT_DNS_TAG,
                "server": BOOTSTRAP_DNS,
                "server_port": 53,
            },
        ]

    def _build_base_route_rules(self) -> list[dict]:
        return [
            {
                "ip_cidr": [BOOTSTRAP_DNS],
                "port": [53],
                "network": ["udp"],
                "outbound": DIRECT_OUTBOUND_TAG,
            }
        ]

    def _normalize_ip_cidr(self, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("IP/CIDR 规则不能为空")
        if "/" in text:
            ipaddress.ip_network(text, strict=False)
            return text
        return self._normalize_prefix(text)

    def _map_route_action_to_outbound(self, *, action: str, final_tag: str) -> str:
        if action == "direct":
            return DIRECT_OUTBOUND_TAG
        if action == "proxy":
            return final_tag
        raise ValueError(f"不支持的路由动作: {action}")

    def _map_rule_to_singbox_route(self, *, rule: RoutingRule, final_tag: str) -> dict:
        outbound = self._map_route_action_to_outbound(action=rule.action, final_tag=final_tag)
        match_value = rule.match_value.strip()
        if rule.match_type == "domain_suffix":
            return {"domain_suffix": [match_value.lstrip(".")], "outbound": outbound}
        if rule.match_type == "domain_keyword":
            return {"domain_keyword": [match_value], "outbound": outbound}
        if rule.match_type == "ip_cidr":
            return {"ip_cidr": [self._normalize_ip_cidr(match_value)], "outbound": outbound}
        if rule.match_type == "rule_set":
            return {"rule_set": [match_value], "outbound": outbound}
        raise ValueError(f"不支持的路由匹配类型: {rule.match_type}")

    async def _resolve_active_rule_set(self, preferences: Preferences) -> RoutingRuleSet | None:
        if preferences.active_routing_rule_set_id is not None:
            rule_set = await self.routing_rule_sets_repo.get_rule_set(preferences.active_routing_rule_set_id)
            if rule_set is not None and rule_set.enabled:
                return rule_set
        return await self.routing_rule_sets_repo.get_fallback_rule_set()

    async def _collect_required_rule_files(self, rules: list[RoutingRule]) -> list[RuleFile]:
        tags: list[str] = []
        for rule in rules:
            if not rule.enabled or rule.match_type != "rule_set":
                continue
            tag = rule.match_value.strip()
            if tag and tag not in tags:
                tags.append(tag)
        return [await self.rule_file_service.ensure_rule_file(tag) for tag in tags]

    def _build_route_rule_set_entries(
        self,
        *,
        rule_files: list[RuleFile],
        proxy_prefix: str | None,
        final_tag: str,
    ) -> list[RuleSetConfigEntry]:
        return [
            RuleSetConfigEntry(
                tag=rule_file.tag,
                format=rule_file.format,
                url=self.rule_file_service.build_rule_file_url(
                    rule_file=rule_file,
                    proxy_prefix=proxy_prefix,
                ),
                download_detour=final_tag,
            )
            for rule_file in rule_files
        ]

    async def _build_rule_file_rules(self, *, final_tag: str) -> list[dict]:
        _ = final_tag
        return []

    async def _build_user_route_rules(self, *, preferences: Preferences, final_tag: str) -> tuple[list[dict], list[RuleSetConfigEntry]]:
        if preferences.routing_mode != "rule":
            return [], []
        rule_set = await self._resolve_active_rule_set(preferences)
        if rule_set is None:
            return [], []
        rules = await self.routing_rules_repo.list_rules(rule_set.id)
        enabled_rules = [rule for rule in rules if rule.enabled]
        mapped_rules = [
            self._map_rule_to_singbox_route(rule=rule, final_tag=final_tag)
            for rule in enabled_rules
        ]
        required_rule_files = await self._collect_required_rule_files(enabled_rules)
        rule_set_entries = self._build_route_rule_set_entries(
            rule_files=required_rule_files,
            proxy_prefix=preferences.rule_set_url_proxy_prefix,
            final_tag=final_tag,
        )
        return [*mapped_rules, *(await self._build_rule_file_rules(final_tag=final_tag))], rule_set_entries

    def _replace_host_with_predefined_ip(self, host: str, predefined_hosts: dict[str, list[str]] | None = None) -> str:
        normalized_host = host.strip()
        if not normalized_host or self._is_ip_address(normalized_host):
            return normalized_host
        resolved_addresses = (predefined_hosts or {}).get(normalized_host, [])
        if resolved_addresses:
            return resolved_addresses[0]
        return normalized_host

    def _build_warp_endpoint(self, warp: WarpAccount, predefined_hosts: dict[str, list[str]] | None = None) -> dict:
        peer_public_key = warp.peer_public_key or WARP_PEER_PUBLIC_KEY
        peer_endpoint_host = warp.peer_endpoint_host or WARP_ENDPOINT
        peer_endpoint_port = warp.peer_endpoint_port or WARP_PORT
        peer_allowed_ips = json.loads(warp.peer_allowed_ips) if warp.peer_allowed_ips else WARP_ALLOWED_IPS
        peer_address = self._replace_host_with_predefined_ip(peer_endpoint_host, predefined_hosts)

        return {
            "type": "wireguard",
            "tag": WARP_ENDPOINT_TAG,
            "address": [
                self._normalize_prefix(warp.local_address_v4),
                self._normalize_prefix(warp.local_address_v6),
            ],
            "private_key": warp.private_key,
            "peers": [
                {
                    "address": peer_address,
                    "port": peer_endpoint_port,
                    "public_key": peer_public_key,
                    "allowed_ips": peer_allowed_ips,
                    "reserved": json.loads(warp.reserved),
                }
            ],
            "detour": PROXY_NODE_TAG,
        }

    def _normalize_hosts_mapping(self, hosts: dict[str, list[str]] | None) -> dict[str, list[str]]:
        if not hosts:
            return {}
        normalized: dict[str, list[str]] = {}
        for domain, addresses in hosts.items():
            if not isinstance(domain, str) or not domain.strip() or self._is_ip_address(domain.strip()):
                continue
            if not isinstance(addresses, list):
                continue
            cleaned: list[str] = []
            for address in addresses:
                if not isinstance(address, str) or not address.strip():
                    continue
                try:
                    normalized_address = str(ipaddress.ip_address(address.strip()))
                except ValueError:
                    continue
                if normalized_address not in cleaned:
                    cleaned.append(normalized_address)
            if cleaned:
                normalized[domain.strip()] = cleaned
        return normalized

    def _build_remote_dns_server(self, *, detour: str) -> dict:
        return {
            "type": "https",
            "tag": REMOTE_DNS_TAG,
            "server": REMOTE_DNS_SERVER,
            "path": REMOTE_DNS_PATH,
            "domain_resolver": BOOTSTRAP_DNS_TAG,
            "detour": detour,
        }

    def _collect_next_layer_hosts(self, context: BuildContext) -> list[str]:
        if not context.preferences.warp_enabled or context.warp_account is None:
            return []

        hosts: list[str] = []
        node_server = context.node_server.strip()
        if node_server and not self._is_ip_address(node_server):
            hosts.append(node_server)

        peer_endpoint_host = (context.warp_account.peer_endpoint_host or WARP_ENDPOINT).strip()
        if peer_endpoint_host and not self._is_ip_address(peer_endpoint_host) and peer_endpoint_host not in hosts:
            hosts.append(peer_endpoint_host)

        return hosts

    def _build_bootstrap_stage_model(self, *, context: BuildContext, resolve_hosts: list[str]) -> SingBoxConfig:
        node_outbound = dict(context.node_outbound)
        node_outbound["tag"] = PROXY_NODE_TAG
        dns_servers = self._build_base_dns_servers()
        dns_servers.append(self._build_remote_dns_server(detour=PROXY_NODE_TAG))
        dns_rules = [
            *self._build_next_layer_dns_rules(resolve_hosts),
            *self._build_current_layer_dns_rules([context.node_server]),
        ]

        model = SingBoxConfig(
            dns=DNSConfig(
                servers=dns_servers,
                rules=dns_rules,
                final=BOOTSTRAP_DNS_TAG,
            ),
            inbounds=self._build_inbound(port=BOOTSTRAP_MIXED_PORT),
            outbounds=[
                {"type": "direct", "tag": DIRECT_OUTBOUND_TAG},
                node_outbound,
            ],
            route=RouteConfig(
                final=PROXY_NODE_TAG,
                rules=self._build_base_route_rules(),
                default_domain_resolver={"server": BOOTSTRAP_DNS_TAG},
            ),
        )
        return SingBoxConfig.model_validate(model.model_dump())

    async def build_bootstrap_stages(self) -> list[BootstrapStage]:
        context = await self._build_context()
        resolve_hosts = self._collect_next_layer_hosts(context)
        if not resolve_hosts:
            return []
        return [
            BootstrapStage(
                config=self._build_bootstrap_stage_model(context=context, resolve_hosts=resolve_hosts),
                resolve_hosts=resolve_hosts,
            )
        ]

    async def build_bootstrap_config(self) -> SingBoxConfig:
        stages = await self.build_bootstrap_stages()
        if not stages:
            raise ValueError("当前场景不需要 WARP bootstrap 配置")
        return stages[0].config

    async def build_config(self, *, predefined_hosts: dict[str, list[str]] | None = None) -> SingBoxConfig:
        context = await self._build_context()
        inbounds = self._build_inbound(port=DEFAULT_MIXED_PORT)
        outbounds: list[dict] = [{"type": "direct", "tag": DIRECT_OUTBOUND_TAG}]
        endpoints: list[dict] = []
        dns_rules = self._build_base_dns_rules(context.node_server)
        dns_servers = self._build_base_dns_servers()
        route_rules = self._build_base_route_rules()
        normalized_hosts = self._normalize_hosts_mapping(predefined_hosts)

        if context.preferences.warp_enabled and context.warp_account is not None:
            node_outbound = dict(context.node_outbound)
            node_outbound["tag"] = PROXY_NODE_TAG
            node_outbound["server"] = self._replace_host_with_predefined_ip(context.node_server, normalized_hosts)
            outbounds.append(node_outbound)
            endpoints.append(self._build_warp_endpoint(context.warp_account, normalized_hosts))
            final_tag = WARP_ENDPOINT_TAG
            remote_dns_detour = WARP_ENDPOINT_TAG
        else:
            outbounds.append(dict(context.node_outbound))
            final_tag = context.node_outbound["tag"]
            remote_dns_detour = final_tag

        if normalized_hosts:
            dns_servers.append(
                {
                    "type": "hosts",
                    "tag": HOSTS_DNS_TAG,
                    "predefined": normalized_hosts,
                }
            )
            dns_rules = [
                {"server": HOSTS_DNS_TAG, "domain": list(normalized_hosts.keys())},
                *dns_rules,
            ]

        user_route_rules, route_rule_set_entries = await self._build_user_route_rules(
            preferences=context.preferences,
            final_tag=remote_dns_detour,
        )
        dns_final = REMOTE_DNS_TAG if context.preferences.dns_leak_protection else DIRECT_DNS_TAG
        dns_servers.append(self._build_remote_dns_server(detour=remote_dns_detour))

        model = SingBoxConfig(
            dns=DNSConfig(servers=dns_servers, rules=dns_rules, final=dns_final),
            inbounds=inbounds,
            outbounds=outbounds,
            endpoints=endpoints,
            route=RouteConfig(
                final=final_tag,
                rules=[*route_rules, *user_route_rules],
                rule_set=route_rule_set_entries,
                default_domain_resolver={"server": dns_final},
            ),
        )
        return SingBoxConfig.model_validate(model.model_dump())
