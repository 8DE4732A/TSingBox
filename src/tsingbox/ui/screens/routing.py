from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Select, Static, Switch


class RoutingScreen(Vertical):
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Select(options=[("global", "global"), ("rule", "rule")], id="route-mode", prompt="路由模式")
            yield Static("DNS 防泄漏")
            yield Switch(value=False, id="dns-leak")
            yield Static("sing-box 路径")
            yield Input(placeholder="支持完整可执行文件路径或所在目录", id="singbox-binary-path")
            yield Static("指定 sing-box 所在目录或可执行文件路径", classes="help-text")
            yield Button("保存设置", id="save-routing", variant="primary")
            yield Static("", id="routing-status")

    async def on_mount(self) -> None:
        await self.refresh_screen()

    async def refresh_screen(self) -> None:
        pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
        self.query_one("#route-mode", Select).value = pref.routing_mode
        self.query_one("#dns-leak", Switch).value = pref.dns_leak_protection
        self.query_one("#singbox-binary-path", Input).value = pref.singbox_binary_path or ""
        self.query_one("#route-mode", Select).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save-routing":
            return
        mode = str(self.query_one("#route-mode", Select).value)
        dns_leak = self.query_one("#dns-leak", Switch).value
        binary_input = self.query_one("#singbox-binary-path", Input).value
        normalized_path, error = self.app.validate_singbox_binary_input(binary_input)  # type: ignore[attr-defined]
        if error:
            self.app.last_action_message = error  # type: ignore[attr-defined]
            await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
            self.query_one("#routing-status", Static).update(error)
            self.app.append_log(error)  # type: ignore[attr-defined]
            return
        await self.app.preferences_repo.update_preferences(  # type: ignore[attr-defined]
            routing_mode=mode,
            dns_leak_protection=dns_leak,
            singbox_binary_path=normalized_path,
        )
        msg = "设置已保存"
        self.app.last_action_message = msg  # type: ignore[attr-defined]
        await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
        self.query_one("#routing-status", Static).update(msg)
        self.query_one("#singbox-binary-path", Input).value = normalized_path or ""
        self.app.append_log(msg)  # type: ignore[attr-defined]
