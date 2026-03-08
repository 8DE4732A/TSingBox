from __future__ import annotations

from contextlib import asynccontextmanager

import aiosqlite

from tsingbox.core.settings import Settings
from tsingbox.data.schema import SCHEMA_SQL


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
                    id, selected_node_id, routing_mode, dns_leak_protection, warp_enabled, singbox_binary_path
                ) VALUES (1, NULL, 'rule', 0, 0, NULL)
                """
            )
