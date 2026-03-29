from __future__ import annotations

import sqlite3

from tsingbox.data.db import Database
from tsingbox.data.models import Preferences


UNSET = object()


class PreferencesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_preferences(self) -> Preferences:
        async with self.database.connect() as conn:
            try:
                cursor = await conn.execute(
                    """
                    SELECT id, selected_node_id, routing_mode, dns_leak_protection,
                           warp_enabled, singbox_binary_path, singbox_active_version,
                           active_routing_rule_set_id, rule_set_url_proxy_prefix
                    FROM preferences
                    WHERE id = 1
                    """
                )
                row = await cursor.fetchone()
            except sqlite3.OperationalError as exc:
                msg = str(exc)
                if "no such column: rule_set_url_proxy_prefix" in msg:
                    cursor = await conn.execute(
                        """
                        SELECT id, selected_node_id, routing_mode, dns_leak_protection,
                               warp_enabled, singbox_binary_path, singbox_active_version,
                               active_routing_rule_set_id
                        FROM preferences
                        WHERE id = 1
                        """
                    )
                    row = await cursor.fetchone()
                elif "no such column: active_routing_rule_set_id" in msg:
                    cursor = await conn.execute(
                        """
                        SELECT id, selected_node_id, routing_mode, dns_leak_protection,
                               warp_enabled, singbox_binary_path, singbox_active_version
                        FROM preferences
                        WHERE id = 1
                        """
                    )
                    row = await cursor.fetchone()
                elif "no such column: singbox_active_version" in msg:
                    cursor = await conn.execute(
                        """
                        SELECT id, selected_node_id, routing_mode, dns_leak_protection,
                               warp_enabled, singbox_binary_path
                        FROM preferences
                        WHERE id = 1
                        """
                    )
                    row = await cursor.fetchone()
                elif "no such column: singbox_binary_path" in msg:
                    cursor = await conn.execute(
                        """
                        SELECT id, selected_node_id, routing_mode, dns_leak_protection, warp_enabled
                        FROM preferences
                        WHERE id = 1
                        """
                    )
                    row = await cursor.fetchone()
                else:
                    raise
        if not row:
            return Preferences(
                id=1,
                selected_node_id=None,
                routing_mode="global",
                dns_leak_protection=False,
                warp_enabled=False,
                singbox_binary_path=None,
                singbox_active_version=None,
                active_routing_rule_set_id=None,
                rule_set_url_proxy_prefix=None,
            )
        keys = row.keys()
        return Preferences(
            id=row["id"],
            selected_node_id=row["selected_node_id"],
            routing_mode=row["routing_mode"],
            dns_leak_protection=bool(row["dns_leak_protection"]),
            warp_enabled=bool(row["warp_enabled"]),
            singbox_binary_path=row["singbox_binary_path"] if "singbox_binary_path" in keys else None,
            singbox_active_version=row["singbox_active_version"] if "singbox_active_version" in keys else None,
            active_routing_rule_set_id=row["active_routing_rule_set_id"] if "active_routing_rule_set_id" in keys else None,
            rule_set_url_proxy_prefix=row["rule_set_url_proxy_prefix"] if "rule_set_url_proxy_prefix" in keys else None,
        )

    async def set_selected_node(self, node_id: int | None) -> None:
        async with self.database.connect() as conn:
            await conn.execute(
                "UPDATE preferences SET selected_node_id = ? WHERE id = 1",
                (node_id,),
            )

    async def update_preferences(
        self,
        *,
        routing_mode: str | None = None,
        dns_leak_protection: bool | None = None,
        warp_enabled: bool | None = None,
        singbox_binary_path: str | None | object = UNSET,
        singbox_active_version: str | None | object = UNSET,
        active_routing_rule_set_id: int | None | object = UNSET,
        rule_set_url_proxy_prefix: str | None | object = UNSET,
    ) -> None:
        sets: list[str] = []
        values: list[object] = []
        if routing_mode is not None:
            sets.append("routing_mode = ?")
            values.append(routing_mode)
        if dns_leak_protection is not None:
            sets.append("dns_leak_protection = ?")
            values.append(1 if dns_leak_protection else 0)
        if warp_enabled is not None:
            sets.append("warp_enabled = ?")
            values.append(1 if warp_enabled else 0)
        if singbox_binary_path is not UNSET:
            sets.append("singbox_binary_path = ?")
            values.append(singbox_binary_path)
        if singbox_active_version is not UNSET:
            sets.append("singbox_active_version = ?")
            values.append(singbox_active_version)
        if active_routing_rule_set_id is not UNSET:
            sets.append("active_routing_rule_set_id = ?")
            values.append(active_routing_rule_set_id)
        if rule_set_url_proxy_prefix is not UNSET:
            sets.append("rule_set_url_proxy_prefix = ?")
            values.append(rule_set_url_proxy_prefix)

        if not sets:
            return

        values.append(1)
        async with self.database.connect() as conn:
            await conn.execute(
                f"UPDATE preferences SET {', '.join(sets)} WHERE id = ?",
                tuple(values),
            )
