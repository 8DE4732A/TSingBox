import json

import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.config_builder import BOOTSTRAP_MIXED_PORT, ConfigBuilder


async def _create_builder_with_selected_node(tmp_path, *, server: str = "example.com"):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    subs = SubscriptionsRepository(db)
    nodes = NodesRepository(db)
    prefs = PreferencesRepository(db)
    warp = WarpAccountsRepository(db)

    _, _ = await subs.upsert_and_replace_nodes(
        name="demo",
        url="https://example.com/sub",
        nodes=[
            {
                "tag": "n1",
                "protocol": "vless",
                "config": {
                    "type": "vless",
                    "tag": "n1",
                    "server": server,
                    "server_port": 443,
                    "uuid": "11111111-1111-1111-1111-111111111111",
                },
            }
        ],
    )
    all_nodes = await nodes.list_nodes()
    await prefs.set_selected_node(all_nodes[0].id)

    return ConfigBuilder(nodes_repo=nodes, preferences_repo=prefs, warp_repo=warp), prefs, warp


def _dns_server_by_tag(cfg, tag: str):
    return next(server for server in cfg.dns.servers if server.tag == tag)


@pytest.mark.asyncio
async def test_build_config_without_warp_and_dns_leak_protection_disabled(tmp_path):
    builder, prefs, _ = await _create_builder_with_selected_node(tmp_path)

    cfg = await builder.build_config()

    assert len(cfg.inbounds) == 1
    assert cfg.inbounds[0]["type"] == "mixed"
    assert cfg.inbounds[0]["tag"] == "mixed-in"
    assert cfg.inbounds[0]["listen"] == "127.0.0.1"
    assert cfg.inbounds[0]["listen_port"] == 7890
    assert cfg.route.final == "n1"

    bootstrap_dns = _dns_server_by_tag(cfg, "bootstrap-dns")
    direct_dns = _dns_server_by_tag(cfg, "direct-dns")
    remote_dns = _dns_server_by_tag(cfg, "remote-dns")
    assert bootstrap_dns.type == "udp"
    assert bootstrap_dns.server == "223.5.5.5"
    assert bootstrap_dns.server_port == 53
    assert direct_dns.type == "udp"
    assert direct_dns.server == "223.5.5.5"
    assert direct_dns.server_port == 53
    assert remote_dns.type == "https"
    assert remote_dns.server == "cloudflare-dns.com"
    assert remote_dns.path == "/dns-query"
    assert remote_dns.domain_resolver == "bootstrap-dns"
    assert remote_dns.detour == "n1"

    assert cfg.dns.rules == [{"server": "bootstrap-dns", "domain": ["example.com"]}]
    assert cfg.dns.final == "direct-dns"
    assert cfg.route.default_domain_resolver == {"server": "direct-dns"}
    assert any(outbound.get("tag") == "direct" and outbound.get("type") == "direct" for outbound in cfg.outbounds)
    assert any(outbound.get("tag") == "n1" for outbound in cfg.outbounds)
    assert cfg.route.rules == [
        {"ip_cidr": ["223.5.5.5"], "port": [53], "network": ["udp"], "outbound": "direct"}
    ]

    await prefs.update_preferences(routing_mode="rule")
    cfg_rule_mode = await builder.build_config()
    assert cfg_rule_mode.route.final == "n1"
    assert cfg_rule_mode.route.rules == [
        {"ip_cidr": ["223.5.5.5"], "port": [53], "network": ["udp"], "outbound": "direct"}
    ]


@pytest.mark.asyncio
async def test_build_config_without_warp_and_dns_leak_protection_enabled(tmp_path):
    builder, prefs, _ = await _create_builder_with_selected_node(tmp_path)
    await prefs.update_preferences(dns_leak_protection=True)

    cfg = await builder.build_config()

    remote_dns = _dns_server_by_tag(cfg, "remote-dns")
    assert cfg.dns.final == "remote-dns"
    assert cfg.route.default_domain_resolver == {"server": "remote-dns"}
    assert remote_dns.detour == "n1"
    assert cfg.route.final == "n1"


@pytest.mark.asyncio
async def test_build_config_with_warp_routes_remote_dns_through_warp(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path)
    await prefs.update_preferences(dns_leak_protection=True)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
        peer_public_key="peer-public-key",
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )
    await prefs.update_preferences(warp_enabled=True)

    cfg = await builder.build_config()

    assert cfg.route.final == "warp-endpoint"
    assert cfg.dns.final == "remote-dns"
    assert cfg.route.default_domain_resolver == {"server": "remote-dns"}
    assert _dns_server_by_tag(cfg, "remote-dns").detour == "warp-endpoint"
    assert _dns_server_by_tag(cfg, "bootstrap-dns").server == "223.5.5.5"
    assert _dns_server_by_tag(cfg, "direct-dns").server == "223.5.5.5"
    assert any(item.get("tag") == "proxy-node" for item in cfg.outbounds)
    assert any(item.get("tag") == "direct" for item in cfg.outbounds)
    assert len(cfg.endpoints) == 1
    warp_endpoint = cfg.endpoints[0]
    assert warp_endpoint.tag == "warp-endpoint"
    assert warp_endpoint.detour == "proxy-node"
    assert warp_endpoint.address == ["172.16.0.2/32", "2606:4700:110::2/128"]
    assert warp_endpoint.peers[0].address == "engage.cloudflareclient.com"
    assert warp_endpoint.peers[0].port == 2408
    assert warp_endpoint.peers[0].public_key == "peer-public-key"
    assert warp_endpoint.peers[0].allowed_ips == ["0.0.0.0/0", "::/0"]
    assert warp_endpoint.peers[0].reserved == [1, 2, 3]


@pytest.mark.asyncio
async def test_build_config_with_old_warp_account_falls_back_to_legacy_peer_defaults(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
    )
    await prefs.update_preferences(warp_enabled=True)

    cfg = await builder.build_config()

    warp_endpoint = cfg.endpoints[0]
    assert warp_endpoint.peers[0].address == "162.159.193.10"
    assert warp_endpoint.peers[0].port == 2408
    assert warp_endpoint.peers[0].public_key == "bmXOC+F1V4JxA8S8d+QsbNf8j2RzYj6JQ5t8V9hV7iE="
    assert warp_endpoint.peers[0].allowed_ips == ["0.0.0.0/0", "::/0"]


@pytest.mark.asyncio
async def test_build_bootstrap_stages_with_warp_keeps_current_layer_on_bootstrap_dns(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path)
    await prefs.update_preferences(warp_enabled=True, dns_leak_protection=True)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
        peer_public_key="peer-public-key",
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )

    stages = await builder.build_bootstrap_stages()

    assert len(stages) == 1
    assert stages[0].resolve_hosts == ["example.com", "engage.cloudflareclient.com"]
    cfg = stages[0].config
    assert cfg.route.final == "proxy-node"
    assert cfg.dns.final == "bootstrap-dns"
    assert cfg.route.default_domain_resolver == {"server": "bootstrap-dns"}
    assert cfg.inbounds[0]["listen_port"] == BOOTSTRAP_MIXED_PORT
    assert len(cfg.endpoints) == 0
    assert [item["tag"] for item in cfg.outbounds] == ["direct", "proxy-node"]
    assert _dns_server_by_tag(cfg, "remote-dns").detour == "proxy-node"
    assert cfg.dns.rules == [
        {"server": "remote-dns", "domain": ["example.com", "engage.cloudflareclient.com"]},
        {"server": "bootstrap-dns", "domain": ["example.com"]},
    ]


@pytest.mark.asyncio
async def test_build_bootstrap_stages_skips_when_next_layer_host_is_ip(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path)
    await prefs.update_preferences(warp_enabled=True, dns_leak_protection=True)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
        peer_endpoint_host="162.159.193.10",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )

    stages = await builder.build_bootstrap_stages()

    assert len(stages) == 1
    assert stages[0].resolve_hosts == ["example.com"]
    assert stages[0].config.dns.rules == [
        {"server": "remote-dns", "domain": ["example.com"]},
        {"server": "bootstrap-dns", "domain": ["example.com"]},
    ]


@pytest.mark.asyncio
async def test_build_bootstrap_stages_skips_current_layer_bootstrap_rule_when_node_server_is_ip(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path, server="1.2.3.4")
    await prefs.update_preferences(warp_enabled=True, dns_leak_protection=True)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )

    stages = await builder.build_bootstrap_stages()

    assert len(stages) == 1
    assert stages[0].resolve_hosts == ["engage.cloudflareclient.com"]
    assert stages[0].config.dns.rules == [{"server": "remote-dns", "domain": ["engage.cloudflareclient.com"]}]


@pytest.mark.asyncio
async def test_build_config_injects_dynamic_hosts_predefined(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path)
    await prefs.update_preferences(warp_enabled=True, dns_leak_protection=True)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
        peer_public_key="peer-public-key",
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )

    cfg = await builder.build_config(
        predefined_hosts={
            "example.com": ["203.0.113.1"],
            "engage.cloudflareclient.com": ["198.51.100.10", "2606:4700:4700::1111"],
            "162.159.193.10": ["162.159.193.10"],
        }
    )

    hosts_dns = _dns_server_by_tag(cfg, "hosts-dns")
    assert hosts_dns.type == "hosts"
    assert hosts_dns.predefined == {
        "example.com": ["203.0.113.1"],
        "engage.cloudflareclient.com": ["198.51.100.10", "2606:4700:4700::1111"]
    }
    assert cfg.dns.rules[0] == {"server": "hosts-dns", "domain": ["example.com", "engage.cloudflareclient.com"]}
    assert cfg.outbounds[1]["server"] == "203.0.113.1"
    assert cfg.endpoints[0].peers[0].address == "198.51.100.10"


@pytest.mark.asyncio
async def test_build_config_keeps_warp_endpoint_host_when_predefined_hosts_missing(tmp_path):
    builder, prefs, warp = await _create_builder_with_selected_node(tmp_path)
    await prefs.update_preferences(warp_enabled=True, dns_leak_protection=True)
    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
        peer_public_key="peer-public-key",
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )

    cfg = await builder.build_config(predefined_hosts={"other.example.com": ["198.51.100.10"]})

    assert cfg.endpoints[0].peers[0].address == "engage.cloudflareclient.com"


@pytest.mark.asyncio
async def test_build_config_skips_bootstrap_domain_rule_when_node_server_is_ip(tmp_path):
    builder, _, _ = await _create_builder_with_selected_node(tmp_path, server="1.2.3.4")

    cfg = await builder.build_config()

    assert cfg.dns.rules == []
    assert _dns_server_by_tag(cfg, "remote-dns").domain_resolver == "bootstrap-dns"
