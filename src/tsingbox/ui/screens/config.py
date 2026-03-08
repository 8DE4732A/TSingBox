from __future__ import annotations

import json
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Log, Static


class ConfigScreen(Vertical):
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("正在读取 runtime 配置", id="config-status")
            yield Log(id="config-content", auto_scroll=False, highlight=False)

    async def refresh_screen(self) -> None:
        status_widget = self.query_one("#config-status", Static)
        content_widget = self.query_one("#config-content", Log)
        config_path = self.app.settings.runtime_config_path  # type: ignore[attr-defined]

        status, content = self._load_config_content(config_path)
        status_widget.update(status)
        self.update_content(content_widget, content)

    def update_content(self, widget: Log, content: str) -> None:
        widget.clear()
        for line in content.splitlines() or [""]:
            widget.write_line(line)

    @staticmethod
    def _load_config_content(config_path: Path) -> tuple[str, str]:
        try:
            raw_content = config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "runtime 配置文件不存在，可能尚未应用配置", "暂无配置内容"

        if not raw_content.strip():
            return "runtime 配置文件为空", "暂无配置内容"

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return "runtime 配置文件不是合法 JSON，以下展示原始内容", raw_content

        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        return "已加载 runtime 配置", formatted
