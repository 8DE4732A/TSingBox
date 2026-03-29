from __future__ import annotations

from tsingbox.data.db import BUILTIN_RULE_SET_NAMES, Database
from tsingbox.data.models import RoutingRuleSet

DEFAULT_RULE_SET_NAME = BUILTIN_RULE_SET_NAMES["cn_direct"]


class RoutingRuleSetsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_rule_sets(self) -> list[RoutingRuleSet]:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, is_builtin, is_default, enabled, sort_order
                FROM routing_rule_sets
                ORDER BY sort_order ASC, id ASC
                """
            )
            rows = await cursor.fetchall()
        return [
            RoutingRuleSet(
                id=row["id"],
                name=row["name"],
                is_builtin=bool(row["is_builtin"]),
                is_default=bool(row["is_default"]),
                enabled=bool(row["enabled"]),
                sort_order=row["sort_order"],
            )
            for row in rows
        ]

    async def get_rule_set(self, rule_set_id: int) -> RoutingRuleSet | None:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, is_builtin, is_default, enabled, sort_order
                FROM routing_rule_sets
                WHERE id = ?
                """,
                (rule_set_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return RoutingRuleSet(
            id=row["id"],
            name=row["name"],
            is_builtin=bool(row["is_builtin"]),
            is_default=bool(row["is_default"]),
            enabled=bool(row["enabled"]),
            sort_order=row["sort_order"],
        )

    async def create_rule_set(self, name: str) -> RoutingRuleSet:
        async with self.database.connect() as conn:
            cursor = await conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM routing_rule_sets")
            next_sort = (await cursor.fetchone())["next_sort"]
            cursor = await conn.execute(
                """
                INSERT INTO routing_rule_sets (name, is_builtin, is_default, enabled, sort_order)
                VALUES (?, 0, 0, 1, ?)
                """,
                (name, next_sort),
            )
            rule_set_id = cursor.lastrowid
        return RoutingRuleSet(
            id=int(rule_set_id),
            name=name,
            is_builtin=False,
            is_default=False,
            enabled=True,
            sort_order=int(next_sort),
        )

    async def delete_rule_set(self, rule_set_id: int) -> bool:
        rule_set = await self.get_rule_set(rule_set_id)
        if rule_set is None or rule_set.is_builtin:
            return False
        async with self.database.connect() as conn:
            await conn.execute("DELETE FROM routing_rule_sets WHERE id = ?", (rule_set_id,))
        return True

    async def get_default_rule_set(self) -> RoutingRuleSet | None:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, is_builtin, is_default, enabled, sort_order
                FROM routing_rule_sets
                WHERE is_default = 1
                ORDER BY sort_order ASC, id ASC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return RoutingRuleSet(
            id=row["id"],
            name=row["name"],
            is_builtin=bool(row["is_builtin"]),
            is_default=bool(row["is_default"]),
            enabled=bool(row["enabled"]),
            sort_order=row["sort_order"],
        )

    async def get_fallback_rule_set(self) -> RoutingRuleSet | None:
        default_rule_set = await self.get_default_rule_set()
        if default_rule_set is not None and default_rule_set.enabled:
            return default_rule_set
        rule_sets = await self.list_rule_sets()
        for rule_set in rule_sets:
            if rule_set.enabled:
                return rule_set
        return None

    async def set_default_rule_set(self, rule_set_id: int) -> None:
        async with self.database.connect() as conn:
            await conn.execute("UPDATE routing_rule_sets SET is_default = 0")
            await conn.execute("UPDATE routing_rule_sets SET is_default = 1 WHERE id = ?", (rule_set_id,))
