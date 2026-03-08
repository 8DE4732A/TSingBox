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
