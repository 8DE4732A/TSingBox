from __future__ import annotations

from contextlib import asynccontextmanager

import aiosqlite

from tsingbox.core.settings import Settings
from tsingbox.data.schema import SCHEMA_SQL

GHFAST_PREFIX = "https://ghfast.top/"

BUILTIN_RULE_SET_NAMES = {
    "cn_direct": "国内直连",
    "global_proxy": "全局代理",
}

BUILTIN_CN_DIRECT_RULES = [
    ("rule_set", "geosite-google", "proxy", 0),
    ("rule_set", "geosite-private", "direct", 1),
    ("rule_set", "geoip-cn", "direct", 2),
    ("rule_set", "geosite-cn", "direct", 3),
]

BUILTIN_REMOTE_RULE_SETS = [
    {
        "tag": "geosite-cn",
        "name": "中国大陆域名",
        "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs",
        "is_builtin": True,
        "auto_enabled": True,
    },
    {
        "tag": "geoip-cn",
        "name": "中国大陆 IP",
        "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-cn.srs",
        "is_builtin": True,
        "auto_enabled": True,
    },
    {
        "tag": "geosite-google",
        "name": "Google 域名",
        "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-google.srs",
        "is_builtin": True,
        "auto_enabled": False,
    },
    {
        "tag": "geosite-private",
        "name": "私有域名",
        "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-private.srs",
        "is_builtin": True,
        "auto_enabled": False,
    },
]


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @asynccontextmanager
    async def connect(self):
        conn = await aiosqlite.connect(self.settings.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()

    async def initialize(self) -> None:
        async with self.connect() as conn:
            await conn.executescript(SCHEMA_SQL)

            cursor = await conn.execute("PRAGMA table_info(preferences)")
            preference_columns = {row["name"] for row in await cursor.fetchall()}
            if "singbox_binary_path" not in preference_columns:
                await conn.execute("ALTER TABLE preferences ADD COLUMN singbox_binary_path TEXT")
            if "singbox_active_version" not in preference_columns:
                await conn.execute("ALTER TABLE preferences ADD COLUMN singbox_active_version TEXT")
            if "active_routing_rule_set_id" not in preference_columns:
                await conn.execute("ALTER TABLE preferences ADD COLUMN active_routing_rule_set_id INTEGER")
            if "rule_set_url_proxy_prefix" not in preference_columns:
                await conn.execute("ALTER TABLE preferences ADD COLUMN rule_set_url_proxy_prefix TEXT")

            cursor = await conn.execute("PRAGMA table_info(warp_accounts)")
            warp_columns = {row["name"] for row in await cursor.fetchall()}
            if "peer_public_key" not in warp_columns:
                await conn.execute("ALTER TABLE warp_accounts ADD COLUMN peer_public_key TEXT")
            if "peer_endpoint_host" not in warp_columns:
                await conn.execute("ALTER TABLE warp_accounts ADD COLUMN peer_endpoint_host TEXT")
            if "peer_endpoint_port" not in warp_columns:
                await conn.execute("ALTER TABLE warp_accounts ADD COLUMN peer_endpoint_port INTEGER")
            if "peer_allowed_ips" not in warp_columns:
                await conn.execute("ALTER TABLE warp_accounts ADD COLUMN peer_allowed_ips TEXT")

            await conn.execute(
                """
                INSERT OR IGNORE INTO preferences (
                    id,
                    selected_node_id,
                    routing_mode,
                    dns_leak_protection,
                    warp_enabled,
                    singbox_binary_path,
                    singbox_active_version,
                    active_routing_rule_set_id,
                    rule_set_url_proxy_prefix
                ) VALUES (1, NULL, 'global', 0, 0, NULL, NULL, NULL, NULL)
                """
            )
            await conn.execute(
                "UPDATE preferences SET routing_mode = 'global' WHERE id = 1 AND routing_mode = 'rule'"
            )

            builtin_rule_set_ids: dict[str, int] = {}
            for index, (key, name) in enumerate(BUILTIN_RULE_SET_NAMES.items()):
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO routing_rule_sets (name, is_builtin, is_default, enabled, sort_order)
                    VALUES (?, 1, ?, 1, ?)
                    """,
                    (name, 1 if key == "cn_direct" else 0, index),
                )
                cursor = await conn.execute(
                    "SELECT id FROM routing_rule_sets WHERE name = ?",
                    (name,),
                )
                row = await cursor.fetchone()
                if row:
                    builtin_rule_set_ids[key] = row["id"]

            cn_direct_rule_set_id = builtin_rule_set_ids.get("cn_direct")
            if cn_direct_rule_set_id is not None:
                await conn.execute(
                    "DELETE FROM routing_rules WHERE rule_set_id = ?",
                    (cn_direct_rule_set_id,),
                )
                for match_type, match_value, action, sort_order in BUILTIN_CN_DIRECT_RULES:
                    await conn.execute(
                        """
                        INSERT INTO routing_rules (rule_set_id, match_type, match_value, action, sort_order, enabled)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (cn_direct_rule_set_id, match_type, match_value, action, sort_order),
                    )

            if cn_direct_rule_set_id is not None:
                await conn.execute(
                    """
                    UPDATE routing_rule_sets
                    SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END
                    """,
                    (cn_direct_rule_set_id,),
                )

            cursor = await conn.execute(
                "SELECT active_routing_rule_set_id FROM preferences WHERE id = 1"
            )
            preference_row = await cursor.fetchone()
            active_rule_set_id = preference_row["active_routing_rule_set_id"] if preference_row else None
            if active_rule_set_id is None:
                cursor = await conn.execute(
                    "SELECT id FROM routing_rule_sets WHERE is_default = 1 ORDER BY sort_order ASC, id ASC LIMIT 1"
                )
                default_row = await cursor.fetchone()
                if default_row is not None:
                    await conn.execute(
                        "UPDATE preferences SET active_routing_rule_set_id = ? WHERE id = 1",
                        (default_row["id"],),
                    )

            for item in BUILTIN_REMOTE_RULE_SETS:
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO rule_files (
                        name,
                        tag,
                        format,
                        url,
                        download_detour,
                        is_builtin,
                        auto_enabled,
                        enabled,
                        updated_at
                    )
                    VALUES (?, ?, 'binary', ?, NULL, ?, ?, 0, datetime('now', 'localtime'))
                    """,
                    (
                        item["name"],
                        item["tag"],
                        item["url"],
                        1 if item["is_builtin"] else 0,
                        1 if item["auto_enabled"] else 0,
                    ),
                )

            await conn.execute(
                """
                UPDATE rule_files
                SET url = substr(url, ? + 1)
                WHERE is_builtin = 1 AND url LIKE ?
                """,
                (len(GHFAST_PREFIX), f"{GHFAST_PREFIX}%"),
            )
