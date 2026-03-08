from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Log


class LogsScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rendered_logs: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Log(id="logs-content", auto_scroll=True, highlight=False)

    async def refresh_screen(self) -> None:
        self.update_logs(self.app.logs)  # type: ignore[attr-defined]

    def update_logs(self, logs: list[str]) -> None:
        visible_logs = logs[-50:]
        widget = self.query_one("#logs-content", Log)
        widget.clear()
        self._rendered_logs = visible_logs.copy()
        if not visible_logs:
            widget.write_line("暂无日志")
            return
        for line in visible_logs:
            widget.write_line(line)

    def append_log_line(self, line: str) -> None:
        widget = self.query_one("#logs-content", Log)
        if not self._rendered_logs:
            widget.clear()
        next_logs = [*self._rendered_logs, line]
        if len(next_logs) > 50:
            self.update_logs(next_logs[-50:])
            return
        self._rendered_logs = next_logs
        widget.write_line(line)
