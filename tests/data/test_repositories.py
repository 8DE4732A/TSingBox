import json
import sqlite3

import pytest

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
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
    )
    loaded = await warp_repo.get_account()
    assert loaded is not None
    assert loaded.private_key == account.private_key

    pref = await pref_repo.get_preferences()
    assert pref.routing_mode == "rule"
    assert pref.singbox_binary_path is None

    await pref_repo.update_preferences(
        routing_mode="global",
        dns_leak_protection=True,
        warp_enabled=True,
        singbox_binary_path="/opt/homebrew/bin/sing-box",
    )
    await pref_repo.set_selected_node(99)
    updated = await pref_repo.get_preferences()
    assert updated.routing_mode == "global"
    assert updated.dns_leak_protection is True
    assert updated.warp_enabled is True
    assert updated.selected_node_id == 99
    assert updated.singbox_binary_path == "/opt/homebrew/bin/sing-box"

    await pref_repo.update_preferences(singbox_binary_path=None)
    cleared = await pref_repo.get_preferences()
    assert cleared.singbox_binary_path is None


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
            routing_mode TEXT NOT NULL DEFAULT 'rule',
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
