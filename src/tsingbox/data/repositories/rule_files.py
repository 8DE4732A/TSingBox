from __future__ import annotations

from datetime import datetime

from tsingbox.data.db import Database
from tsingbox.data.models import RuleFile


class RuleFilesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_rule_files(self) -> list[RuleFile]:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, tag, format, url, download_detour, is_builtin, auto_enabled, enabled, updated_at
                FROM rule_files
                ORDER BY is_builtin DESC, tag ASC, id ASC
                """
            )
            rows = await cursor.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def get_rule_file(self, tag: str) -> RuleFile | None:
        async with self.database.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT id, name, tag, format, url, download_detour, is_builtin, auto_enabled, enabled, updated_at
                FROM rule_files
                WHERE tag = ?
                LIMIT 1
                """,
                (tag,),
            )
            row = await cursor.fetchone()
        return self._row_to_model(row) if row else None

    async def upsert_rule_file(
        self,
        *,
        name: str,
        tag: str,
        format: str = "binary",
        url: str,
        download_detour: str | None = None,
        is_builtin: bool = False,
        auto_enabled: bool = False,
        enabled: bool = True,
    ) -> RuleFile:
        updated_at = datetime.now().isoformat(timespec="seconds")
        async with self.database.connect() as conn:
            cursor = await conn.execute("SELECT id FROM rule_files WHERE tag = ?", (tag,))
            existing = await cursor.fetchone()
            if existing is None:
                cursor = await conn.execute(
                    """
                    INSERT INTO rule_files (
                        name, tag, format, url, download_detour, is_builtin, auto_enabled, enabled, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        tag,
                        format,
                        url,
                        download_detour,
                        1 if is_builtin else 0,
                        1 if auto_enabled else 0,
                        1 if enabled else 0,
                        updated_at,
                    ),
                )
                rule_file_id = int(cursor.lastrowid)
            else:
                rule_file_id = int(existing["id"])
                await conn.execute(
                    """
                    UPDATE rule_files
                    SET name = ?, format = ?, url = ?, download_detour = ?, is_builtin = ?, auto_enabled = ?, enabled = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        format,
                        url,
                        download_detour,
                        1 if is_builtin else 0,
                        1 if auto_enabled else 0,
                        1 if enabled else 0,
                        updated_at,
                        rule_file_id,
                    ),
                )
            cursor = await conn.execute(
                """
                SELECT id, name, tag, format, url, download_detour, is_builtin, auto_enabled, enabled, updated_at
                FROM rule_files
                WHERE id = ?
                """,
                (rule_file_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("远程 rule_set 保存失败")
        return self._row_to_model(row)

    async def set_enabled(self, tag: str, enabled: bool) -> RuleFile | None:
        async with self.database.connect() as conn:
            await conn.execute(
                "UPDATE rule_files SET enabled = ?, updated_at = datetime('now', 'localtime') WHERE tag = ?",
                (1 if enabled else 0, tag),
            )
            cursor = await conn.execute(
                """
                SELECT id, name, tag, format, url, download_detour, is_builtin, auto_enabled, enabled, updated_at
                FROM rule_files
                WHERE tag = ?
                LIMIT 1
                """,
                (tag,),
            )
            row = await cursor.fetchone()
        return self._row_to_model(row) if row else None

    async def delete_rule_file(self, rule_file_id: int) -> bool:
        async with self.database.connect() as conn:
            cursor = await conn.execute("DELETE FROM rule_files WHERE id = ?", (rule_file_id,))
        return (cursor.rowcount or 0) > 0

    async def delete_rule_file_by_tag(self, tag: str) -> bool:
        async with self.database.connect() as conn:
            cursor = await conn.execute("DELETE FROM rule_files WHERE tag = ?", (tag,))
        return (cursor.rowcount or 0) > 0

    @staticmethod
    def _row_to_model(row) -> RuleFile:
        return RuleFile(
            id=row["id"],
            name=row["name"],
            tag=row["tag"],
            format=row["format"],
            url=row["url"],
            download_detour=row["download_detour"],
            is_builtin=bool(row["is_builtin"]),
            auto_enabled=bool(row["auto_enabled"]),
            enabled=bool(row["enabled"]),
            local_path=None,
            managed=False,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
