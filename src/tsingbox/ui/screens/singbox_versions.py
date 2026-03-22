from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option


class SingboxVersionsScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._releases: list = []
        self._fetching = False
        self._downloading = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("sing-box 内核版本管理", classes="screen-title")
            yield Static("当前平台: 检测中...", id="versions-platform")
            yield Static("当前使用版本: 未选择", id="versions-active")
            with Horizontal():
                yield Button("获取版本列表", id="fetch-versions", variant="primary")
                yield Button("下载", id="download-version")
                yield Button("使用此版本", id="activate-version")
                yield Button("删除", id="delete-version", variant="error")
            yield OptionList(id="versions-list")
            yield ProgressBar(total=100, show_eta=False, id="download-progress")
            yield Static("", id="versions-status")

    async def on_mount(self) -> None:
        progress = self.query_one("#download-progress", ProgressBar)
        progress.display = False
        vm = self.app.version_manager  # type: ignore[attr-defined]
        platform_label = f"当前平台: {vm._os_name}-{vm._arch}"
        self.query_one("#versions-platform", Static).update(platform_label)
        await self._update_active_label()

    async def refresh_screen(self) -> None:
        await self._update_active_label()
        if self._releases:
            await self._refresh_list_marks()

    async def _update_active_label(self) -> None:
        pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
        active = pref.singbox_active_version
        if active:
            self.query_one("#versions-active", Static).update(f"当前使用版本: {active}")
        else:
            path = pref.singbox_binary_path
            if path:
                self.query_one("#versions-active", Static).update(f"当前使用版本: 手动指定 ({path})")
            else:
                self.query_one("#versions-active", Static).update("当前使用版本: 未选择")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fetch-versions":
            if self._fetching:
                return
            self._fetching = True
            self.query_one("#fetch-versions", Button).disabled = True
            self.query_one("#versions-status", Static).update("正在获取版本列表...")
            self._fetch_versions_worker()
            return

        if event.button.id == "download-version":
            if self._downloading:
                return
            option_list = self.query_one("#versions-list", OptionList)
            idx = option_list.highlighted
            if idx is None or idx >= len(self._releases):
                self.query_one("#versions-status", Static).update("请先选择一个版本")
                return
            release = self._releases[idx]
            if release.installed:
                self.query_one("#versions-status", Static).update(f"{release.tag} 已下载")
                return
            if not release.download_url:
                self.query_one("#versions-status", Static).update(
                    f"{release.tag} 无适用当前平台的下载资源"
                )
                return
            self._downloading = True
            self.query_one("#download-version", Button).disabled = True
            self._download_version_worker(idx)
            return

        if event.button.id == "activate-version":
            option_list = self.query_one("#versions-list", OptionList)
            idx = option_list.highlighted
            if idx is None or idx >= len(self._releases):
                self.query_one("#versions-status", Static).update("请先选择一个版本")
                return
            release = self._releases[idx]
            if not release.installed:
                self.query_one("#versions-status", Static).update(f"请先下载 {release.tag}")
                return
            await self._activate_version(release.tag)
            return

        if event.button.id == "delete-version":
            option_list = self.query_one("#versions-list", OptionList)
            idx = option_list.highlighted
            if idx is None or idx >= len(self._releases):
                self.query_one("#versions-status", Static).update("请先选择一个版本")
                return
            release = self._releases[idx]
            if not release.installed:
                self.query_one("#versions-status", Static).update(f"{release.tag} 未下载")
                return
            pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
            if pref.singbox_active_version == release.tag:
                self.query_one("#versions-status", Static).update("不能删除当前使用中的版本")
                return
            vm = self.app.version_manager  # type: ignore[attr-defined]
            vm.delete_version(release.tag)
            release.installed = False
            await self._refresh_list_marks()
            self.query_one("#versions-status", Static).update(f"已删除 {release.tag}")
            return

    @work(exclusive=True, group="fetch-versions")
    async def _fetch_versions_worker(self) -> None:
        status = self.query_one("#versions-status", Static)
        try:
            vm = self.app.version_manager  # type: ignore[attr-defined]
            self._releases = await vm.fetch_remote_versions()
            pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]

            option_list = self.query_one("#versions-list", OptionList)
            option_list.clear_options()

            for release in self._releases:
                label = self._format_release_label(release, pref.singbox_active_version)
                option_list.add_option(Option(label, id=release.tag))

            count = len(self._releases)
            available = sum(1 for r in self._releases if r.download_url)
            status.update(f"获取到 {count} 个版本，{available} 个适用当前平台")
        except Exception as exc:  # noqa: BLE001
            status.update(f"获取版本列表失败: {exc}")
            self.app.append_log(f"获取版本列表失败: {exc}")  # type: ignore[attr-defined]
        finally:
            self._fetching = False
            self.query_one("#fetch-versions", Button).disabled = False

    @work(exclusive=True, group="download-version")
    async def _download_version_worker(self, idx: int) -> None:
        release = self._releases[idx]
        status = self.query_one("#versions-status", Static)
        progress = self.query_one("#download-progress", ProgressBar)
        progress.display = True
        progress.update(progress=0, total=100)

        def on_progress(downloaded: int, total: int) -> None:
            if total > 0:
                pct = min(int(downloaded * 100 / total), 100)
                self._update_progress(pct, downloaded, total)

        try:
            vm = self.app.version_manager  # type: ignore[attr-defined]
            await vm.download_version(release, progress_callback=on_progress)
            release.installed = True
            await self._refresh_list_marks()
            status.update(f"{release.tag} 下载完成")
        except Exception as exc:  # noqa: BLE001
            status.update(f"下载失败: {exc}")
            self.app.append_log(f"下载 {release.tag} 失败: {exc}")  # type: ignore[attr-defined]
        finally:
            self._downloading = False
            self.query_one("#download-version", Button).disabled = False
            progress.display = False

    def _update_progress(self, pct: int, downloaded: int, total: int) -> None:
        progress = self.query_one("#download-progress", ProgressBar)
        progress.update(progress=pct)
        mb_done = downloaded / 1024 / 1024
        mb_total = total / 1024 / 1024
        self.query_one("#versions-status", Static).update(
            f"下载中: {mb_done:.1f} MB / {mb_total:.1f} MB ({pct}%)"
        )

    async def _activate_version(self, tag: str) -> None:
        await self.app.preferences_repo.update_preferences(  # type: ignore[attr-defined]
            singbox_active_version=tag,
            singbox_binary_path=None,
        )
        await self._update_active_label()
        await self._refresh_list_marks()
        self.query_one("#versions-status", Static).update(f"已切换到 {tag}")
        self.app.append_log(f"sing-box 版本切换到 {tag}")  # type: ignore[attr-defined]
        self.app.last_action_message = f"sing-box 版本切换到 {tag}"  # type: ignore[attr-defined]
        await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]

    async def _refresh_list_marks(self) -> None:
        pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
        option_list = self.query_one("#versions-list", OptionList)
        option_list.clear_options()
        for release in self._releases:
            label = self._format_release_label(release, pref.singbox_active_version)
            option_list.add_option(Option(label, id=release.tag))

    @staticmethod
    def _format_release_label(release, active_version: str | None) -> str:
        parts = [release.tag]
        if release.published_at:
            parts.append(f"({release.published_at})")
        if release.download_url:
            if release.asset_size:
                mb = release.asset_size / 1024 / 1024
                parts.append(f"[{mb:.1f} MB]")
        else:
            parts.append("[当前平台不可用]")
        if active_version and release.tag == active_version:
            parts.append("★ 使用中")
        elif release.installed:
            parts.append("✓ 已下载")
        return " ".join(parts)
