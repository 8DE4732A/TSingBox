from __future__ import annotations

from tsingbox.data.db import Database
from tsingbox.data.models import Node


class NodesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_nodes(self) -> list[Node]:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                "SELECT id, sub_id, tag, protocol, config_json, ping_delay FROM nodes ORDER BY id ASC"
            )
            rows = await cursor.fetchall()
        return [
            Node(
                id=row["id"],
                sub_id=row["sub_id"],
                tag=row["tag"],
                protocol=row["protocol"],
                config_json=row["config_json"],
                ping_delay=row["ping_delay"],
            )
            for row in rows
        ]

    async def get_node(self, node_id: int) -> Node | None:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                "SELECT id, sub_id, tag, protocol, config_json, ping_delay FROM nodes WHERE id = ?",
                (node_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return Node(
            id=row["id"],
            sub_id=row["sub_id"],
            tag=row["tag"],
            protocol=row["protocol"],
            config_json=row["config_json"],
            ping_delay=row["ping_delay"],
        )
