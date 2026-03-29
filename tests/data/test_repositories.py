import json
import sqlite3

import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
from tsingbox.data.repositories.rule_files import RuleFilesRepository
from tsingbox.data.repositories.routing_rules import RoutingRulesRepository
from tsingbox.data.repositories.routing_rule_sets import RoutingRuleSetsRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository


@pytest.mark.asyncio
async def test_subscription_replace_nodes_transaction(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    subs = SubscriptionsRepository(db)
    nodes = NodesRepository(db)

    await subs.upsert_and_replace_nodes(
        name="demo",
        url="https://example.com/sub",
        nodes=[
            {"tag": "a", "protocol": "vless", "config": {"type": "vless", "tag": "a"}},
            {"tag": "b", "protocol": "trojan", "config": {"type": "trojan", "tag": "b"}},
        ],
    )
    first = await nodes.list_nodes()
    assert len(first) == 2
    assert [node.tag for node in first] == ["a", "b"]

    await subs.upsert_and_replace_nodes(
        name="demo",
        url="https://example.com/sub",
        nodes=[
            {"tag": "c", "protocol": "vless", "config": {"type": "vless", "tag": "c"}},
        ],
    )
    second = await nodes.list_nodes()
    assert len(second) == 1
    assert second[0].tag == "c"


@pytest.mark.asyncio
async def test_warp_and_preferences_repo(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    warp_repo = WarpAccountsRepository(db)
    pref_repo = PreferencesRepository(db)

    account = await warp_repo.upsert_account(
        private_key="k",
        local_address_v4="172.16.0.2/32",
        local_address_v6="2606:4700:110::2/128",
        reserved=json.dumps([1, 2, 3]),
        peer_public_key="peer-pk",
        peer_endpoint_host="engage.cloudflareclient.com",
        peer_endpoint_port=2408,
        peer_allowed_ips=json.dumps(["0.0.0.0/0", "::/0"]),
    )
    loaded = await warp_repo.get_account()
    assert loaded is not None
    assert loaded.private_key == account.private_key
    assert loaded.peer_public_key == "peer-pk"
    assert loaded.peer_endpoint_host == "engage.cloudflareclient.com"
    assert loaded.peer_endpoint_port == 2408
    assert loaded.peer_allowed_ips == json.dumps(["0.0.0.0/0", "::/0"])

    pref = await pref_repo.get_preferences()
    assert pref.routing_mode == "global"
    assert pref.singbox_binary_path is None
    assert pref.rule_set_url_proxy_prefix is None

    await pref_repo.update_preferences(
        routing_mode="global",
        dns_leak_protection=True,
        warp_enabled=True,
        singbox_binary_path="/opt/homebrew/bin/sing-box",
        active_routing_rule_set_id=1,
        rule_set_url_proxy_prefix="https://ghfast.top/",
    )
    await pref_repo.set_selected_node(99)
    updated = await pref_repo.get_preferences()
    assert updated.routing_mode == "global"
    assert updated.dns_leak_protection is True
    assert updated.warp_enabled is True
    assert updated.selected_node_id == 99
    assert updated.singbox_binary_path == "/opt/homebrew/bin/sing-box"
    assert updated.active_routing_rule_set_id == 1
    assert updated.rule_set_url_proxy_prefix == "https://ghfast.top/"

    await pref_repo.update_preferences(singbox_binary_path=None, rule_set_url_proxy_prefix=None)
    cleared = await pref_repo.get_preferences()
    assert cleared.singbox_binary_path is None
    assert cleared.rule_set_url_proxy_prefix is None


@pytest.mark.asyncio
async def test_preferences_repo_falls_back_when_old_database_missing_singbox_column(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        """
        CREATE TABLE preferences (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            selected_node_id INTEGER,
            routing_mode TEXT NOT NULL DEFAULT 'global',
            dns_leak_protection INTEGER NOT NULL DEFAULT 0,
            warp_enabled INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO preferences (id, selected_node_id, routing_mode, dns_leak_protection, warp_enabled) VALUES (1, NULL, 'rule', 0, 1)"
    )
    conn.commit()
    conn.close()

    pref_repo = PreferencesRepository(Database(settings))
    pref = await pref_repo.get_preferences()

    assert pref.routing_mode == "rule"
    assert pref.warp_enabled is True
    assert pref.singbox_binary_path is None
    assert pref.rule_set_url_proxy_prefix is None


@pytest.mark.asyncio
async def test_initialize_adds_missing_warp_account_peer_columns(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        """
        CREATE TABLE warp_accounts (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            private_key TEXT NOT NULL,
            local_address_v4 TEXT NOT NULL,
            local_address_v6 TEXT NOT NULL,
            reserved TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE preferences (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            selected_node_id INTEGER,
            routing_mode TEXT NOT NULL DEFAULT 'global',
            dns_leak_protection INTEGER NOT NULL DEFAULT 0,
            warp_enabled INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(settings)
    await db.initialize()

    conn = sqlite3.connect(settings.db_path)
    cursor = conn.execute("PRAGMA table_info(warp_accounts)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    assert "peer_public_key" in columns
    assert "peer_endpoint_host" in columns
    assert "peer_endpoint_port" in columns
    assert "peer_allowed_ips" in columns


@pytest.mark.asyncio
async def test_warp_repo_get_account_falls_back_when_old_database_missing_peer_columns(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        """
        CREATE TABLE warp_accounts (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            private_key TEXT NOT NULL,
            local_address_v4 TEXT NOT NULL,
            local_address_v6 TEXT NOT NULL,
            reserved TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO warp_accounts (id, private_key, local_address_v4, local_address_v6, reserved)
        VALUES (1, 'legacy-key', '172.16.0.2/32', '2606:4700:110::2/128', '[1, 2, 3]')
        """
    )
    conn.commit()
    conn.close()

    repo = WarpAccountsRepository(Database(settings))
    account = await repo.get_account()

    assert account is not None
    assert account.private_key == "legacy-key"
    assert account.peer_public_key is None
    assert account.peer_endpoint_host is None
    assert account.peer_endpoint_port is None
    assert account.peer_allowed_ips is None


@pytest.mark.asyncio
async def test_initialize_creates_builtin_routing_rule_sets_and_preference_selection(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    rule_sets_repo = RoutingRuleSetsRepository(db)
    rules_repo = RoutingRulesRepository(db)
    pref_repo = PreferencesRepository(db)

    rule_sets = await rule_sets_repo.list_rule_sets()
    names = [item.name for item in rule_sets]
    assert "国内直连" in names
    assert "全局代理" in names

    cn_direct = next(item for item in rule_sets if item.name == "国内直连")
    pref = await pref_repo.get_preferences()
    assert pref.routing_mode == "global"
    assert pref.active_routing_rule_set_id == cn_direct.id
    assert cn_direct.is_default is True

    rules = await rules_repo.list_rules(cn_direct.id)
    assert [(rule.match_type, rule.match_value, rule.action) for rule in rules] == [
        ("rule_set", "geosite-google", "proxy"),
        ("rule_set", "geosite-private", "direct"),
        ("rule_set", "geoip-cn", "direct"),
        ("rule_set", "geosite-cn", "direct"),
    ]


@pytest.mark.asyncio
async def test_initialize_seeds_builtin_remote_rule_sets(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    repo = RuleFilesRepository(db)
    items = await repo.list_rule_files()
    tags = {item.tag for item in items}

    assert {"geosite-cn", "geoip-cn", "geosite-google", "geosite-private"}.issubset(tags)


@pytest.mark.asyncio
async def test_initialize_normalizes_builtin_rule_file_ghfast_urls_only(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "UPDATE rule_files SET url = ? WHERE tag = ?",
        ("https://ghfast.top/https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs", "geosite-cn"),
    )
    conn.execute(
        "INSERT INTO rule_files (name, tag, format, url, download_detour, is_builtin, auto_enabled, enabled, updated_at) VALUES (?, ?, 'binary', ?, NULL, 0, 0, 1, datetime('now', 'localtime'))",
        ("自定义", "custom-ghfast", "https://ghfast.top/https://example.com/custom.srs"),
    )
    conn.commit()
    conn.close()

    await db.initialize()

    repo = RuleFilesRepository(db)
    builtin = await repo.get_rule_file("geosite-cn")
    custom = await repo.get_rule_file("custom-ghfast")

    assert builtin is not None
    assert custom is not None
    assert builtin.url == "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs"
    assert custom.url == "https://ghfast.top/https://example.com/custom.srs"


@pytest.mark.asyncio
async def test_routing_rule_repositories_support_custom_rule_set_crud(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()
    db = Database(settings)
    await db.initialize()

    rule_sets_repo = RoutingRuleSetsRepository(db)
    rules_repo = RoutingRulesRepository(db)
    pref_repo = PreferencesRepository(db)

    custom = await rule_sets_repo.create_rule_set("办公规则")
    await pref_repo.update_preferences(active_routing_rule_set_id=custom.id)
    created_rule = await rules_repo.create_rule(
        custom.id,
        match_type="rule_set",
        match_value="geosite-cn",
        action="proxy",
    )

    updated_pref = await pref_repo.get_preferences()
    assert updated_pref.active_routing_rule_set_id == custom.id

    listed_rules = await rules_repo.list_rules(custom.id)
    assert [rule.id for rule in listed_rules] == [created_rule.id]
    assert listed_rules[0].match_value == "geosite-cn"
    assert listed_rules[0].action == "proxy"

    assert await rules_repo.delete_rule(created_rule.id) is True
    assert await rules_repo.list_rules(custom.id) == []
    assert await rule_sets_repo.delete_rule_set(custom.id) is True
    remaining = await rule_sets_repo.list_rule_sets()
    assert all(item.name != "办公规则" for item in remaining)
