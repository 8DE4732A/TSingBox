from __future__ import annotations

import json
from datetime import datetime, timezone

from tsingbox.data.db import Database
from tsingbox.data.models import Subscription


class SubscriptionsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_subscriptions(self) -> list[Subscription]:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                "SELECT id, name, url, last_update FROM subscriptions ORDER BY id DESC"
            )
            rows = await cursor.fetchall()
        return [
            Subscription(
                id=row["id"],
                name=row["name"],
                url=row["url"],
                last_update=datetime.fromisoformat(row["last_update"]) if row["last_update"] else None,
            )
            for row in rows
        ]

    async def upsert_and_replace_nodes(
        self,
        *,
        name: str,
        url: str,
        nodes: list[dict],
    ) -> tuple[int, int]:
        now = datetime.now(timezone.utc).isoformat()
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                "SELECT id FROM subscriptions WHERE url = ?",
                (url,),
            )
            row = await cursor.fetchone()

            if row:
                sub_id = row["id"]
                await conn.execute(
                    "UPDATE subscriptions SET name = ?, last_update = ? WHERE id = ?",
                    (name, now, sub_id),
                )
            else:
                cursor = await conn.execute(
                    "INSERT INTO subscriptions (name, url, last_update) VALUES (?, ?, ?)",
                    (name, url, now),
                )
                sub_id = int(cursor.lastrowid)

            await conn.execute("DELETE FROM nodes WHERE sub_id = ?", (sub_id,))
            for node in nodes:
                await conn.execute(
                    """
                    INSERT INTO nodes (sub_id, tag, protocol, config_json, ping_delay)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        sub_id,
                        node["tag"],
                        node["protocol"],
                        json.dumps(node["config"], ensure_ascii=False),
                        None,
                    ),
                )

        return sub_id, len(nodes)
