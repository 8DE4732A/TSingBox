from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tsingbox.data.models import Preferences


class SingboxBinaryStatus(StrEnum):
    CONFIGURED_VALID = "configured_valid"
    CONFIGURED_NOT_FOUND = "configured_not_found"
    CONFIGURED_NOT_FILE = "configured_not_file"
    CONFIGURED_NOT_EXECUTABLE = "configured_not_executable"
    VERSION_MANAGED = "version_managed"
    VERSION_NOT_FOUND = "version_not_found"
    PATH_FOUND = "path_found"
    PATH_NOT_FOUND = "path_not_found"


@dataclass(slots=True)
class SingboxBinaryCheckResult:
    status: SingboxBinaryStatus
    binary_path: str | None
    configured_path: str | None

    @property
    def ok(self) -> bool:
        return self.status in {
            SingboxBinaryStatus.CONFIGURED_VALID,
            SingboxBinaryStatus.VERSION_MANAGED,
            SingboxBinaryStatus.PATH_FOUND,
        }


class SingboxBinaryService:
    def normalize_input(self, raw_value: str | None) -> str | None:
        if raw_value is None:
            return None
        value = raw_value.strip()
        if not value:
            return None
        path = Path(value).expanduser()
        if path.name == "sing-box":
            return str(path)
        return str(path / "sing-box")

    def validate_configured_path(self, raw_value: str | None) -> SingboxBinaryCheckResult:
        normalized = self.normalize_input(raw_value)
        if normalized is None:
            return SingboxBinaryCheckResult(
                status=SingboxBinaryStatus.PATH_NOT_FOUND,
                binary_path=None,
                configured_path=None,
            )

        path = Path(normalized)
        if not path.exists():
            return SingboxBinaryCheckResult(
                status=SingboxBinaryStatus.CONFIGURED_NOT_FOUND,
                binary_path=None,
                configured_path=normalized,
            )
        if not path.is_file():
            return SingboxBinaryCheckResult(
                status=SingboxBinaryStatus.CONFIGURED_NOT_FILE,
                binary_path=None,
                configured_path=normalized,
            )
        if not os.access(path, os.X_OK):
            return SingboxBinaryCheckResult(
                status=SingboxBinaryStatus.CONFIGURED_NOT_EXECUTABLE,
                binary_path=None,
                configured_path=normalized,
            )
        return SingboxBinaryCheckResult(
            status=SingboxBinaryStatus.CONFIGURED_VALID,
            binary_path=normalized,
            configured_path=normalized,
        )

    def resolve_binary(
        self,
        preferences: Preferences,
        versions_dir: Path | None = None,
    ) -> SingboxBinaryCheckResult:
        # 1. User-configured path takes highest priority
        if preferences.singbox_binary_path:
            return self.validate_configured_path(preferences.singbox_binary_path)

        # 2. Version manager installed binary
        if preferences.singbox_active_version and versions_dir is not None:
            binary = versions_dir / preferences.singbox_active_version / "sing-box"
            if binary.exists() and binary.is_file() and os.access(binary, os.X_OK):
                return SingboxBinaryCheckResult(
                    status=SingboxBinaryStatus.VERSION_MANAGED,
                    binary_path=str(binary),
                    configured_path=None,
                )
            return SingboxBinaryCheckResult(
                status=SingboxBinaryStatus.VERSION_NOT_FOUND,
                binary_path=None,
                configured_path=None,
            )

        # 3. Fallback to PATH
        binary = shutil.which("sing-box")
        if binary:
            return SingboxBinaryCheckResult(
                status=SingboxBinaryStatus.PATH_FOUND,
                binary_path=binary,
                configured_path=None,
            )
        return SingboxBinaryCheckResult(
            status=SingboxBinaryStatus.PATH_NOT_FOUND,
            binary_path=None,
            configured_path=None,
        )

    def get_missing_binary_message(self, result: SingboxBinaryCheckResult) -> str:
        if result.status == SingboxBinaryStatus.CONFIGURED_NOT_FOUND:
            return "已配置的 sing-box 路径不存在，请在设置页重新指定"
        if result.status == SingboxBinaryStatus.CONFIGURED_NOT_FILE:
            return "已配置的 sing-box 路径不是文件，请在设置页重新指定"
        if result.status == SingboxBinaryStatus.CONFIGURED_NOT_EXECUTABLE:
            return "sing-box 文件不可执行，请检查文件权限或重新指定"
        if result.status == SingboxBinaryStatus.VERSION_NOT_FOUND:
            return "已选的 sing-box 版本文件不存在，请前往内核页重新下载或选择其他版本"
        return "未检测到系统 sing-box，请前往内核页下载或在设置页指定路径"
