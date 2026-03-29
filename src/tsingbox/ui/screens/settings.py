from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Select, Static, Switch


class SettingsScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rule_sets = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("基础设置", classes="screen-title")
            yield Select(
                options=[("规则模式", "rule"), ("全局代理", "global")],
                id="route-mode",
                prompt="路由模式",
            )
            yield Static("当前规则集")
            yield Select(options=[], id="active-rule-set", prompt="当前规则集")
            yield Static("DNS 防泄漏")
            yield Switch(value=False, id="dns-leak")
            yield Static("rule_set URL 前缀")
            yield Input(placeholder="留空表示关闭，示例: https://ghfast.top/", id="rule-set-url-proxy-prefix")
            yield Static("仅影响生成的 route.rule_set 下载地址，不会回写 rule file 原始 URL。", classes="help-text")
            yield Static("sing-box 路径")
            yield Input(placeholder="支持完整可执行文件路径或所在目录", id="singbox-binary-path")
            yield Static('指定 sing-box 所在目录或可执行文件路径（也可前往"内核"页下载管理）', classes="help-text")
            yield Button("保存设置", id="save-settings", variant="primary")
            yield Static("global 模式下规则集不参与路由，仅作为 rule 模式下的候选。", classes="help-text")
            yield Static("", id="settings-status")

    async def on_mount(self) -> None:
        await self.refresh_screen()

    async def refresh_screen(self) -> None:
        try:
            pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
            self.query_one("#route-mode", Select).value = pref.routing_mode
            self.query_one("#dns-leak", Switch).value = pref.dns_leak_protection
            self.query_one("#rule-set-url-proxy-prefix", Input).value = pref.rule_set_url_proxy_prefix or ""
            self.query_one("#singbox-binary-path", Input).value = pref.singbox_binary_path or ""
            self._rule_sets = await self.app.routing_rule_sets_repo.list_rule_sets()  # type: ignore[attr-defined]
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            self._rule_sets = []
            self._render_active_rule_set_select(None)
            self.query_one("#settings-status", Static).update("初始化中...")
            return

        active_rule_set_id = pref.active_routing_rule_set_id
        if active_rule_set_id is None and self._rule_sets:
            active_rule_set_id = self._rule_sets[0].id
        self._render_active_rule_set_select(active_rule_set_id)
        self.query_one("#route-mode", Select).focus()

    def _render_active_rule_set_select(self, active_rule_set_id: int | None) -> None:
        select = self.query_one("#active-rule-set", Select)
        select.set_options([(item.name, item.id) for item in self._rule_sets])
        select.value = active_rule_set_id if active_rule_set_id is not None else Select.BLANK
        self._update_active_rule_set_control()

    def _update_active_rule_set_control(self) -> None:
        route_mode = str(self.query_one("#route-mode", Select).value)
        self.query_one("#active-rule-set", Select).disabled = route_mode == "global"

    def _set_status(self, message: str) -> None:
        self.query_one("#settings-status", Static).update(message)
        self.app.last_action_message = message  # type: ignore[attr-defined]
        self.app.append_log(message)  # type: ignore[attr-defined]

    async def _save_preferences(self) -> None:
        mode = str(self.query_one("#route-mode", Select).value)
        dns_leak = self.query_one("#dns-leak", Switch).value
        binary_input = self.query_one("#singbox-binary-path", Input).value
        rule_set_url_proxy_prefix_input = self.query_one("#rule-set-url-proxy-prefix", Input).value
        active_value = self.query_one("#active-rule-set", Select).value
        active_rule_set_id = None if active_value in (Select.BLANK, Select.NULL) else int(active_value)
        normalized_path, error = self.app.validate_singbox_binary_input(binary_input)  # type: ignore[attr-defined]
        normalized_rule_set_url_proxy_prefix = self.app.rule_file_service.normalize_url_proxy_prefix(  # type: ignore[attr-defined]
            rule_set_url_proxy_prefix_input
        )
        if error:
            self._set_status(error)
            await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
            return
        await self.app.preferences_repo.update_preferences(  # type: ignore[attr-defined]
            routing_mode=mode,
            dns_leak_protection=dns_leak,
            singbox_binary_path=normalized_path,
            active_routing_rule_set_id=active_rule_set_id,
            rule_set_url_proxy_prefix=normalized_rule_set_url_proxy_prefix,
        )
        self.query_one("#rule-set-url-proxy-prefix", Input).value = normalized_rule_set_url_proxy_prefix or ""
        self.query_one("#singbox-binary-path", Input).value = normalized_path or ""
        self._update_active_rule_set_control()
        await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
        self._set_status("设置已保存")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-settings":
            await self._save_preferences()

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "route-mode":
            self._update_active_rule_set_control()

    def on_show(self) -> None:
        self.query_one("#route-mode", Select).focus()
