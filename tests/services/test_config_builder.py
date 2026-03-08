import json

import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.config_builder import ConfigBuilder


@pytest.mark.asyncio
async def test_build_config_with_and_without_warp(tmp_path):
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
                    "server": "example.com",
                    "server_port": 443,
                    "uuid": "11111111-1111-1111-1111-111111111111",
                },
            }
        ],
    )
    all_nodes = await nodes.list_nodes()
    await prefs.set_selected_node(all_nodes[0].id)

    builder = ConfigBuilder(nodes_repo=nodes, preferences_repo=prefs, warp_repo=warp)

    cfg = await builder.build_config()
    assert cfg.route.final == "n1"
    assert cfg.dns.servers[0].type == "udp"
    assert cfg.dns.servers[0].tag == "local"
    assert cfg.dns.servers[0].server == "223.5.5.5"
    assert cfg.dns.servers[0].server_port == 53

    await prefs.update_preferences(dns_leak_protection=True)
    cfg_dns_protected = await builder.build_config()
    assert cfg_dns_protected.dns.servers[0].type == "udp"
    assert cfg_dns_protected.dns.servers[0].tag == "remote"
    assert cfg_dns_protected.dns.servers[0].server == "1.1.1.1"
    assert cfg_dns_protected.dns.servers[0].server_port == 53

    await warp.upsert_account(
        private_key="pk",
        local_address_v4="172.16.0.2",
        local_address_v6="2606:4700:110::2",
        reserved=json.dumps([1, 2, 3]),
    )
    await prefs.update_preferences(warp_enabled=True)
    cfg2 = await builder.build_config()
    assert cfg2.route.final == "warp-endpoint"
    assert any(item.get("tag") == "proxy-node" for item in cfg2.outbounds)
    assert len(cfg2.endpoints) == 1
    warp_endpoint = cfg2.endpoints[0]
    assert warp_endpoint.tag == "warp-endpoint"
    assert warp_endpoint.detour == "proxy-node"
    assert warp_endpoint.address == ["172.16.0.2/32", "2606:4700:110::2/128"]
    assert warp_endpoint.peers[0].address == "162.159.193.10"
    assert warp_endpoint.peers[0].port == 2408
    assert warp_endpoint.peers[0].allowed_ips == ["0.0.0.0/0", "::/0"]
