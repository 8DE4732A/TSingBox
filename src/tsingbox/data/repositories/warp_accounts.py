from __future__ import annotations

from tsingbox.data.db import Database
from tsingbox.data.models import WarpAccount


class WarpAccountsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_account(self) -> WarpAccount | None:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                "SELECT id, private_key, local_address_v4, local_address_v6, reserved FROM warp_accounts WHERE id = 1"
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
        )

    async def upsert_account(
        self,
        *,
        private_key: str,
        local_address_v4: str,
        local_address_v6: str,
        reserved: str,
    ) -> WarpAccount:
        async with self.database.connect() as conn:
            await conn.execute(
                """
                INSERT INTO warp_accounts (id, private_key, local_address_v4, local_address_v6, reserved)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    private_key = excluded.private_key,
                    local_address_v4 = excluded.local_address_v4,
                    local_address_v6 = excluded.local_address_v6,
                    reserved = excluded.reserved
                """,
                (private_key, local_address_v4, local_address_v6, reserved),
            )
        return WarpAccount(
            id=1,
            private_key=private_key,
            local_address_v4=local_address_v4,
            local_address_v6=local_address_v6,
            reserved=reserved,
        )
