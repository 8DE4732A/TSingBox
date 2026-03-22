from __future__ import annotations

import os
import platform
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable

import httpx


GITHUB_RELEASES_URL = "https://api.github.com/repos/SagerNet/sing-box/releases"


@dataclass(slots=True)
class SingboxRelease:
    tag: str
    version: str
    published_at: str
    download_url: str | None
    asset_name: str | None
    asset_size: int | None
    installed: bool = False
    active: bool = False


def _detect_platform() -> tuple[str, str]:
    """Return (os_name, arch) matching sing-box release naming."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_map = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    os_name = os_map.get(system, system)

    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armv7",
        "i386": "386",
        "i686": "386",
    }
    arch = arch_map.get(machine, machine)
    return os_name, arch


class SingboxVersionManager:
    def __init__(
        self,
        versions_dir: Path,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.versions_dir = versions_dir
        self.log_callback = log_callback or (lambda _: None)
        self._os_name, self._arch = _detect_platform()

    def _log(self, msg: str) -> None:
        self.log_callback(msg)

    def _match_asset_name(self, version: str) -> str:
        """Build expected asset filename for the current platform."""
        if self._os_name == "windows":
            return f"sing-box-{version}-windows-{self._arch}.zip"
        return f"sing-box-{version}-{self._os_name}-{self._arch}.tar.gz"

    async def fetch_remote_versions(self, count: int = 20) -> list[SingboxRelease]:
        """Fetch recent releases from GitHub and return matching ones."""
        installed = self.list_installed_versions()
        installed_set = set(installed)
        releases: list[SingboxRelease] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                params={"per_page": count},
                headers={"Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            data = resp.json()

        for item in data:
            tag = item.get("tag_name", "")
            version = tag.lstrip("v")
            published = item.get("published_at", "")
            asset_name = self._match_asset_name(version)

            download_url: str | None = None
            asset_size: int | None = None
            for asset in item.get("assets", []):
                if asset.get("name") == asset_name:
                    download_url = asset.get("browser_download_url")
                    asset_size = asset.get("size")
                    break

            releases.append(
                SingboxRelease(
                    tag=tag,
                    version=version,
                    published_at=published[:10] if published else "",
                    download_url=download_url,
                    asset_name=asset_name,
                    asset_size=asset_size,
                    installed=tag in installed_set,
                )
            )

        return releases

    def list_installed_versions(self) -> list[str]:
        """Return sorted list of installed version tags (directories)."""
        if not self.versions_dir.exists():
            return []
        versions = []
        for child in self.versions_dir.iterdir():
            if child.is_dir() and (child / "sing-box").exists():
                versions.append(child.name)
        versions.sort(key=lambda v: v.lstrip("v"), reverse=True)
        return versions

    def get_binary_path(self, tag: str) -> Path | None:
        """Return path to the sing-box binary for a given version tag."""
        binary = self.versions_dir / tag / "sing-box"
        if binary.exists() and binary.is_file():
            return binary
        return None

    async def download_version(
        self,
        release: SingboxRelease,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download and extract a specific sing-box release. Returns binary path."""
        if not release.download_url:
            raise ValueError(f"版本 {release.tag} 没有适用于当前平台 ({self._os_name}-{self._arch}) 的下载资源")

        version_dir = self.versions_dir / release.tag
        version_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"开始下载 sing-box {release.tag} ({release.asset_name})")

        total_size = release.asset_size or 0
        downloaded = 0
        buffer = BytesIO()

        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            async with client.stream("GET", release.download_url) as resp:
                resp.raise_for_status()
                if total_size == 0:
                    content_length = resp.headers.get("content-length")
                    if content_length:
                        total_size = int(content_length)
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    buffer.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        self._log(f"下载完成，正在解压 {release.asset_name}")
        buffer.seek(0)

        binary_path = self._extract_binary(buffer, release, version_dir)

        # Ensure executable permission
        binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        self._log(f"sing-box {release.tag} 安装完成: {binary_path}")
        return binary_path

    def _extract_binary(self, buffer: BytesIO, release: SingboxRelease, version_dir: Path) -> Path:
        """Extract the sing-box binary from the downloaded archive."""
        asset_name = release.asset_name or ""
        version = release.version

        if asset_name.endswith(".tar.gz"):
            with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
                # The binary is inside a subdirectory like sing-box-{ver}-{os}-{arch}/sing-box
                binary_member = None
                for member in tar.getmembers():
                    if member.name.endswith("/sing-box") and member.isfile():
                        binary_member = member
                        break
                if binary_member is None:
                    raise ValueError(f"在压缩包中未找到 sing-box 可执行文件")
                extracted = tar.extractfile(binary_member)
                if extracted is None:
                    raise ValueError(f"无法提取 sing-box 可执行文件")
                dest = version_dir / "sing-box"
                dest.write_bytes(extracted.read())
                return dest

        elif asset_name.endswith(".zip"):
            with zipfile.ZipFile(buffer) as zf:
                binary_member = None
                for name in zf.namelist():
                    if name.endswith("/sing-box.exe") or name.endswith("\\sing-box.exe"):
                        binary_member = name
                        break
                    if name.endswith("/sing-box") or name == "sing-box":
                        binary_member = name
                        break
                if binary_member is None:
                    raise ValueError(f"在压缩包中未找到 sing-box 可执行文件")
                data = zf.read(binary_member)
                dest_name = "sing-box.exe" if self._os_name == "windows" else "sing-box"
                dest = version_dir / dest_name
                dest.write_bytes(data)
                return dest

        raise ValueError(f"不支持的压缩格式: {asset_name}")

    def delete_version(self, tag: str) -> bool:
        """Delete a downloaded version. Returns True if deleted."""
        version_dir = self.versions_dir / tag
        if version_dir.exists() and version_dir.is_dir():
            shutil.rmtree(version_dir)
            self._log(f"已删除 sing-box {tag}")
            return True
        return False
