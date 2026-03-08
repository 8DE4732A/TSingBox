from __future__ import annotations

import sqlite3

from tsingbox.data.db import Database
from tsingbox.data.models import WarpAccount


class WarpAccountsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_account(self) -> WarpAccount | None:
        async with self.database.connect() as conn:
            try:
                cursor = await conn.execute(
                    """
                    SELECT
                        id,
                        private_key,
                        local_address_v4,
                        local_address_v6,
                        reserved,
                        peer_public_key,
                        peer_endpoint_host,
                        peer_endpoint_port,
                        peer_allowed_ips
                    FROM warp_accounts
                    WHERE id = 1
                    """
                )
                row = await cursor.fetchone()
            except sqlite3.OperationalError as exc:
                if "no such column: peer_public_key" not in str(exc):
                    raise
                cursor = await conn.execute(
                    """
                    SELECT id, private_key, local_address_v4, local_address_v6, reserved
                    FROM warp_accounts
                    WHERE id = 1
                    """
                )
                row = await cursor.fetchone()
        if not row:
            return None
        return WarpAccount(
            id=row["id"],
            private_key=row["private_key"],
            local_address_v4=row["local_address_v4"],
            local_address_v6=row["local_address_v6"],
            reserved=row["reserved"],
            peer_public_key=row["peer_public_key"] if "peer_public_key" in row.keys() else None,
            peer_endpoint_host=row["peer_endpoint_host"] if "peer_endpoint_host" in row.keys() else None,
            peer_endpoint_port=row["peer_endpoint_port"] if "peer_endpoint_port" in row.keys() else None,
            peer_allowed_ips=row["peer_allowed_ips"] if "peer_allowed_ips" in row.keys() else None,
        )

    async def upsert_account(
        self,
        *,
        private_key: str,
        local_address_v4: str,
        local_address_v6: str,
        reserved: str,
        peer_public_key: str | None = None,
        peer_endpoint_host: str | None = None,
        peer_endpoint_port: int | None = None,
        peer_allowed_ips: str | None = None,
    ) -> WarpAccount:
        async with self.database.connect() as conn:
            await conn.execute(
                """
                INSERT INTO warp_accounts (
                    id,
                    private_key,
                    local_address_v4,
                    local_address_v6,
                    reserved,
                    peer_public_key,
                    peer_endpoint_host,
                    peer_endpoint_port,
                    peer_allowed_ips
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    private_key = excluded.private_key,
                    local_address_v4 = excluded.local_address_v4,
                    local_address_v6 = excluded.local_address_v6,
                    reserved = excluded.reserved,
                    peer_public_key = excluded.peer_public_key,
                    peer_endpoint_host = excluded.peer_endpoint_host,
                    peer_endpoint_port = excluded.peer_endpoint_port,
                    peer_allowed_ips = excluded.peer_allowed_ips
                """,
                (
                    private_key,
                    local_address_v4,
                    local_address_v6,
                    reserved,
                    peer_public_key,
                    peer_endpoint_host,
                    peer_endpoint_port,
                    peer_allowed_ips,
                ),
            )
        return WarpAccount(
            id=1,
            private_key=private_key,
            local_address_v4=local_address_v4,
            local_address_v6=local_address_v6,
            reserved=reserved,
            peer_public_key=peer_public_key,
            peer_endpoint_host=peer_endpoint_host,
            peer_endpoint_port=peer_endpoint_port,
            peer_allowed_ips=peer_allowed_ips,
        )
