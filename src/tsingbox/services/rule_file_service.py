from __future__ import annotations

from dataclasses import dataclass

from tsingbox.data.models import RuleFile
from tsingbox.data.repositories.rule_files import RuleFilesRepository


@dataclass(slots=True)
class RuleFileStatus:
    rule_file: RuleFile
    source_text: str
    status_text: str


class RuleFileService:
    def __init__(self, *, repository: RuleFilesRepository) -> None:
        self.repository = repository

    def normalize_url_proxy_prefix(self, prefix: str | None) -> str | None:
        if prefix is None:
            return None
        normalized = prefix.strip()
        if not normalized:
            return None
        if not normalized.endswith("/"):
            normalized = f"{normalized}/"
        return normalized

    def build_final_url(self, *, url: str, proxy_prefix: str | None) -> str:
        normalized_prefix = self.normalize_url_proxy_prefix(proxy_prefix)
        if normalized_prefix is None:
            return url
        return url if url.startswith(normalized_prefix) else f"{normalized_prefix}{url}"

    def build_rule_file_url(self, *, rule_file: RuleFile, proxy_prefix: str | None) -> str:
        return self.build_final_url(url=rule_file.url, proxy_prefix=proxy_prefix)

    async def list_rule_files_with_status(self) -> list[RuleFileStatus]:
        items = await self.repository.list_rule_files()
        return [self._build_status(item) for item in items]

    async def get_rule_file(self, tag: str) -> RuleFile | None:
        return await self.repository.get_rule_file(tag)

    async def ensure_rule_file(self, tag: str) -> RuleFile:
        record = await self.repository.get_rule_file(tag)
        if record is None:
            raise ValueError(f"未知 rule_set tag: {tag}")
        return record

    async def upsert_rule_file(
        self,
        *,
        tag: str,
        name: str,
        url: str,
        format: str = "binary",
        download_detour: str | None = None,
        is_builtin: bool = False,
        auto_enabled: bool = False,
        enabled: bool = True,
    ) -> RuleFileStatus:
        record = await self.repository.upsert_rule_file(
            tag=tag,
            name=name,
            url=url,
            format=format,
            download_detour=download_detour,
            is_builtin=is_builtin,
            auto_enabled=auto_enabled,
            enabled=enabled,
        )
        return self._build_status(record)

    async def delete_rule_file(self, rule_file_id: int) -> bool:
        return await self.repository.delete_rule_file(rule_file_id)

    def _build_status(self, item: RuleFile) -> RuleFileStatus:
        source_text = "内置" if item.is_builtin else "自定义"
        status_text = "可引用"
        return RuleFileStatus(rule_file=item, source_text=source_text, status_text=status_text)
