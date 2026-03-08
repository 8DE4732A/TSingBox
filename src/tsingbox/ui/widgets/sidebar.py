from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static


class Sidebar(Vertical):
    LABELS = {
        "dashboard": "总览",
        "subscriptions": "订阅",
        "nodes": "节点",
        "routing": "设置",
        "warp": "WARP",
        "logs": "日志",
    }

    def compose(self) -> ComposeResult:
        yield Static("TSingBox", classes="sidebar-title")
        for item, label in self.LABELS.items():
            yield Button(label, id=f"nav-{item}")

    def set_active_screen(self, name: str) -> None:
        for item, label in self.LABELS.items():
            button = self.query_one(f"#nav-{item}", Button)
            button.variant = "primary" if item == name else "default"
            button.label = label
