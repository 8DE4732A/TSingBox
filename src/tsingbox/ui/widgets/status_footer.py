from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class StatusFooter(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("页面: 总览 | sing-box: stopped | 代理延迟: -- | 状态: 准备就绪", id="footer-status")

    def update_status(
        self,
        *,
        current_screen: str,
        singbox_status: str,
        proxy_latency: str,
        last_message: str,
    ) -> None:
        self.query_one("#footer-status", Static).update(
            f"页面: {current_screen} | sing-box: {singbox_status} | 代理延迟: {proxy_latency} | 状态: {last_message}"
        )
