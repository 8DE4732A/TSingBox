from __future__ import annotations

import asyncio

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static, Switch

from tsingbox.data.models import WarpAccount

from tsingbox.services.warp_generator import (
    WarpHTTPError,
    WarpNetworkError,
    WarpResponseError,
    WarpStoreError,
)


class WarpScreen(Vertical):
    MISSING_ACCOUNT_NOTICE = "WARP 已开启，但当前没有 WARP 账户，请先生成账户后再应用配置"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._generating = False
        self._suppress_switch_event = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("通过 WARP 落地")
            yield Switch(value=False, id="warp-enabled")
            yield Static("暂无 WARP 账户，请先生成", id="warp-account")
            yield Button("生成 WARP 账户", id="gen-warp", variant="primary")
            yield Static("", id="warp-status")

    async def on_mount(self) -> None:
        await self.refresh_screen()

    async def refresh_screen(self) -> None:
        pref, account = await asyncio.gather(
            self.app.preferences_repo.get_preferences(),  # type: ignore[attr-defined]
            self.app.warp_repo.get_account(),  # type: ignore[attr-defined]
        )
        switch = self.query_one("#warp-enabled", Switch)
        self._suppress_switch_event = True
        try:
            switch.value = pref.warp_enabled
        finally:
            self._suppress_switch_event = False
        self.query_one("#warp-account", Static).update(self._build_account_text(account))
        self.query_one("#warp-status", Static).update(self._build_status_text(pref.warp_enabled, account))
        switch.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "gen-warp":
            return
        if self._generating:
            return
        self._set_generating(True)
        self.query_one("#warp-status", Static).update("WARP 生成中...")
        self.generate_warp_worker()

    async def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "warp-enabled" or self._suppress_switch_event:
            return
        enabled = event.value
        await self.app.preferences_repo.update_preferences(warp_enabled=enabled)  # type: ignore[attr-defined]
        account = await self.app.warp_repo.get_account()  # type: ignore[attr-defined]
        base_msg = "WARP 已开启并自动保存" if enabled else "WARP 已关闭并自动保存"
        msg = self._append_missing_account_notice(base_msg, enabled, account)
        self.query_one("#warp-account", Static).update(self._build_account_text(account))
        self.query_one("#warp-status", Static).update(msg)
        self.app.last_action_message = msg  # type: ignore[attr-defined]
        await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
        self.app.append_log(msg)  # type: ignore[attr-defined]

    @work(exclusive=True)
    async def generate_warp_worker(self) -> None:
        try:
            account = await self.app.warp_generator.generate_and_store()  # type: ignore[attr-defined]
            pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
            msg = self._append_missing_account_notice(f"WARP 账户已生成: {account.local_address_v4}", pref.warp_enabled, account)
            self.query_one("#warp-account", Static).update(self._build_account_text(account))
            await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
        except WarpHTTPError as exc:
            msg = f"WARP 生成失败（HTTP 错误）: {exc.status_code}"
        except WarpNetworkError as exc:
            msg = f"WARP 生成失败（网络）: {exc}"
        except WarpResponseError as exc:
            msg = f"WARP 生成失败（响应结构）: {exc}"
        except WarpStoreError as exc:
            msg = f"WARP 生成失败（落库）: {exc}"
        except Exception as exc:  # noqa: BLE001
            msg = f"WARP 生成失败（未知）: {exc}"

        self.query_one("#warp-status", Static).update(msg)
        self.app.last_action_message = msg  # type: ignore[attr-defined]
        self.app.append_log(msg)  # type: ignore[attr-defined]
        self._set_generating(False)

    def _set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.query_one("#gen-warp", Button).disabled = generating

    @staticmethod
    def _build_account_text(account: WarpAccount | None) -> str:
        if account is None:
            return "暂无 WARP 账户，请先生成"
        return (
            "当前 WARP 账户\n"
            f"IPv4: {account.local_address_v4}\n"
            f"IPv6: {account.local_address_v6}\n"
            f"Reserved: {account.reserved}"
        )

    def _build_status_text(self, warp_enabled: bool, account: WarpAccount | None) -> str:
        if self._should_warn_missing_account(warp_enabled, account):
            return self.MISSING_ACCOUNT_NOTICE
        return ""

    def _append_missing_account_notice(self, message: str, warp_enabled: bool, account: WarpAccount | None) -> str:
        if self._should_warn_missing_account(warp_enabled, account):
            return f"{message}\n{self.MISSING_ACCOUNT_NOTICE}"
        return message

    @staticmethod
    def _should_warn_missing_account(warp_enabled: bool, account: WarpAccount | None) -> bool:
        return warp_enabled and account is None
