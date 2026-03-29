from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Subscription:
    id: int
    name: str
    url: str
    last_update: datetime | None


@dataclass(slots=True)
class Node:
    id: int
    sub_id: int
    tag: str
    protocol: str
    config_json: str
    ping_delay: int | None


@dataclass(slots=True)
class WarpAccount:
    id: int
    private_key: str
    local_address_v4: str
    local_address_v6: str
    reserved: str
    peer_public_key: str | None
    peer_endpoint_host: str | None
    peer_endpoint_port: int | None
    peer_allowed_ips: str | None


@dataclass(slots=True)
class Preferences:
    id: int
    selected_node_id: int | None
    routing_mode: str
    dns_leak_protection: bool
    warp_enabled: bool
    singbox_binary_path: str | None
    singbox_active_version: str | None = None
    active_routing_rule_set_id: int | None = None
    rule_set_url_proxy_prefix: str | None = None


@dataclass(slots=True)
class RoutingRuleSet:
    id: int
    name: str
    is_builtin: bool
    is_default: bool
    enabled: bool
    sort_order: int


@dataclass(slots=True)
class RoutingRule:
    id: int
    rule_set_id: int
    match_type: str
    match_value: str
    action: str
    sort_order: int
    enabled: bool


@dataclass(slots=True)
class RuleFile:
    id: int
    name: str
    tag: str
    format: str
    url: str
    download_detour: str | None
    is_builtin: bool
    auto_enabled: bool
    enabled: bool
    local_path: str | None
    managed: bool
    updated_at: datetime
