from __future__ import annotations

from tsingbox.data.db import Database
from tsingbox.data.models import RoutingRule


class RoutingRulesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_rules(self, rule_set_id: int) -> list[RoutingRule]:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, rule_set_id, match_type, match_value, action, sort_order, enabled
                FROM routing_rules
                WHERE rule_set_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (rule_set_id,),
            )
            rows = await cursor.fetchall()
        return [
            RoutingRule(
                id=row["id"],
                rule_set_id=row["rule_set_id"],
                match_type=row["match_type"],
                match_value=row["match_value"],
                action=row["action"],
                sort_order=row["sort_order"],
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    async def create_rule(self, rule_set_id: int, *, match_type: str, match_value: str, action: str) -> RoutingRule:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM routing_rules WHERE rule_set_id = ?",
                (rule_set_id,),
            )
            next_sort = (await cursor.fetchone())["next_sort"]
            cursor = await conn.execute(
                """
                INSERT INTO routing_rules (rule_set_id, match_type, match_value, action, sort_order, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (rule_set_id, match_type, match_value, action, next_sort),
            )
            rule_id = cursor.lastrowid
        return RoutingRule(
            id=int(rule_id),
            rule_set_id=rule_set_id,
            match_type=match_type,
            match_value=match_value,
            action=action,
            sort_order=int(next_sort),
            enabled=True,
        )

    async def delete_rule(self, rule_id: int) -> bool:
        async with self.database.connect() as conn:
            cursor = await conn.execute("DELETE FROM routing_rules WHERE id = ?", (rule_id,))
        return (cursor.rowcount or 0) > 0
