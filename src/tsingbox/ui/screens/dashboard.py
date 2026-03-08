from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

if False:  # pragma: no cover
    from tsingbox.app import DashboardState


class DashboardScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._applying = False
        self._status_message = "准备就绪"

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal():
                with Vertical():
                    yield Static("当前订阅", classes="section-title")
                    yield Static("未选择", id="dashboard-subscription")
                    yield Static("更新时间: 未更新", id="dashboard-subscription-updated")
                with Vertical():
                    yield Static("当前节点", classes="section-title")
                    yield Static("未选择", id="dashboard-node")
                    yield Static("协议: 未提供", id="dashboard-node-protocol")
                    yield Static("端口: 未提供", id="dashboard-node-port")
                    yield Static("本地代理端口: 未提供", id="dashboard-inbound-port")
                with Vertical():
                    yield Static("运行状态", classes="section-title")
                    yield Static("stopped", id="dashboard-singbox-status")
                    yield Static("节点总数: 0", id="dashboard-node-count")
            with Horizontal():
                yield Static("路由模式: rule", id="dashboard-routing-mode")
                yield Static("DNS 防泄漏: 关闭", id="dashboard-dns")
                yield Static("WARP: 关闭", id="dashboard-warp")
            with Horizontal():
                yield Button("重启", id="apply-config", variant="primary")
                yield Button("刷新", id="refresh-dashboard")
            yield Static("准备就绪", id="apply-status")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-config":
            if self._applying:
                return
            self._set_applying(True, status_message="正在应用配置...")
            self.apply_config_worker()
            return

        if event.button.id == "refresh-dashboard":
            await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
            return

    @work(exclusive=True)
    async def apply_config_worker(self) -> None:
        try:
            _, msg = await self.app.request_apply(reason="user")  # type: ignore[attr-defined]
        finally:
            self._sync_apply_state_from_app()
        self.query_one("#apply-status", Static).update(msg)

    def _set_applying(self, applying: bool, status_message: str | None = None) -> None:
        self._applying = applying
        if status_message is not None:
            self._status_message = status_message
            self.query_one("#apply-status", Static).update(status_message)
        self.query_one("#apply-config", Button).disabled = applying

    def _sync_apply_state_from_app(self, status_message: str | None = None) -> None:
        app_applying = bool(getattr(self.app, "apply_in_progress", False))  # type: ignore[attr-defined]
        effective_applying = self._applying or app_applying
        if status_message is not None:
            self._status_message = status_message
        elif effective_applying:
            self._status_message = "正在应用配置..."
        else:
            self._status_message = getattr(self.app, "last_action_message", self._status_message)  # type: ignore[attr-defined]
        self._set_applying(effective_applying, status_message=self._status_message)

    def update_state(self, state: "DashboardState", status_message: str) -> None:
        self.query_one("#dashboard-subscription", Static).update(state.subscription_name)
        self.query_one("#dashboard-subscription-updated", Static).update(
            f"更新时间: {state.subscription_updated_at}"
        )
        self.query_one("#dashboard-node", Static).update(state.node_name)
        self.query_one("#dashboard-node-protocol", Static).update(f"协议: {state.node_protocol}")
        self.query_one("#dashboard-node-port", Static).update(f"端口: {state.node_port}")
        self.query_one("#dashboard-inbound-port", Static).update(f"本地代理端口: {state.inbound_port}")
        self.query_one("#dashboard-singbox-status", Static).update(state.singbox_status)
        self.query_one("#dashboard-node-count", Static).update(f"节点总数: {state.node_count}")
        self.query_one("#dashboard-routing-mode", Static).update(f"路由模式: {state.routing_mode}")
        self.query_one("#dashboard-dns", Static).update(f"DNS 防泄漏: {state.dns_leak_protection}")
        self.query_one("#dashboard-warp", Static).update(f"WARP: {state.warp_enabled}")
        self._sync_apply_state_from_app(status_message)

    def focus_primary_action(self) -> None:
        self.query_one("#apply-config", Button).focus()
