from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult, ScreenStackError
from textual.containers import Container, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Tab, Tabs

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.data.models import Node, Subscription
from tsingbox.data.repositories.nodes import NodesRepository
from tsingbox.data.repositories.preferences import PreferencesRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.config_builder import ConfigBuilder
from tsingbox.services.singbox_binary_service import SingboxBinaryCheckResult, SingboxBinaryService
from tsingbox.services.singbox_controller import SingboxController
from tsingbox.services.subscription_manager import SubscriptionManager
from tsingbox.services.warp_generator import WarpGenerator
from tsingbox.ui.screens.config import ConfigScreen
from tsingbox.ui.screens.dashboard import DashboardScreen
from tsingbox.ui.screens.logs import LogsScreen
from tsingbox.ui.screens.nodes import NodesScreen
from tsingbox.ui.screens.routing import RoutingScreen
from tsingbox.ui.screens.subscriptions import SubscriptionsScreen
from tsingbox.ui.screens.warp import WarpScreen
from tsingbox.ui.widgets.status_footer import StatusFooter


@dataclass(slots=True)
class DashboardState:
    subscription_name: str
    subscription_updated_at: str
    node_name: str
    node_protocol: str
    node_port: str
    node_count: int
    singbox_status: str
    routing_mode: str
    dns_leak_protection: str
    warp_enabled: str


class TSingBoxApp(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #main {
      layout: vertical;
      width: 1fr;
      height: 1fr;
    }
    #tabs {
      height: 3;
      border-bottom: solid $surface;
      padding: 0 1;
    }
    #content {
      layout: vertical;
      height: 1fr;
      border: round $surface;
      padding: 0 1;
    }
    #content > * {
      width: 1fr;
      height: 1fr;
    }
    StatusFooter {
      dock: bottom;
      height: auto;
      border-top: solid $surface;
      padding: 0 1;
    }
    .screen-title {
      text-style: bold;
      margin-bottom: 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("1", "go('dashboard')", "总览"),
        ("2", "go('subscriptions')", "订阅"),
        ("3", "go('nodes')", "节点"),
        ("4", "go('routing')", "设置"),
        ("5", "go('warp')", "WARP"),
        ("6", "go('config')", "配置"),
        ("7", "go('logs')", "日志"),
        ("a", "apply", "应用"),
        ("r", "refresh", "刷新"),
        ("escape", "dashboard", "返回总览"),
    ]

    SCREEN_LABELS = {
        "dashboard": "总览",
        "subscriptions": "订阅",
        "nodes": "节点",
        "routing": "设置",
        "warp": "WARP",
        "config": "配置",
        "logs": "日志",
    }

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings()
        self.database = Database(self.settings)
        self.subscriptions_repo = SubscriptionsRepository(self.database)
        self.nodes_repo = NodesRepository(self.database)
        self.warp_repo = WarpAccountsRepository(self.database)
        self.preferences_repo = PreferencesRepository(self.database)

        self.subscription_manager = SubscriptionManager(
            subscriptions_repo=self.subscriptions_repo,
            nodes_repo=self.nodes_repo,
        )
        self.config_builder = ConfigBuilder(
            nodes_repo=self.nodes_repo,
            preferences_repo=self.preferences_repo,
            warp_repo=self.warp_repo,
        )
        self.controller = SingboxController(log_callback=self.append_log)
        self.singbox_binary_service = SingboxBinaryService()
        self.warp_generator = WarpGenerator(self.warp_repo)

        self.logs: list[str] = []
        self._screen_map: dict[str, Screen] = {}
        self.current_screen_name = "dashboard"
        self.last_action_message = "准备就绪"
        self.dashboard_state = DashboardState(
            subscription_name="未选择",
            subscription_updated_at="未更新",
            node_name="未选择",
            node_protocol="未提供",
            node_port="未提供",
            node_count=0,
            singbox_status="stopped",
            routing_mode="rule",
            dns_leak_protection="关闭",
            warp_enabled="关闭",
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield Tabs(
                *(Tab(label, id=f"tab-{name}") for name, label in self.SCREEN_LABELS.items()),
                id="tabs",
            )
            with Container(id="content"):
                yield DashboardScreen(id="dashboard")
                yield SubscriptionsScreen(id="subscriptions")
                yield NodesScreen(id="nodes")
                yield RoutingScreen(id="routing")
                yield WarpScreen(id="warp")
                yield ConfigScreen(id="config")
                yield LogsScreen(id="logs")
        yield StatusFooter()

    async def on_mount(self) -> None:
        self.settings.ensure_dirs()
        await self.database.initialize()
        self._screen_map = {
            "dashboard": self.query_one("#dashboard", DashboardScreen),
            "subscriptions": self.query_one("#subscriptions", SubscriptionsScreen),
            "nodes": self.query_one("#nodes", NodesScreen),
            "routing": self.query_one("#routing", RoutingScreen),
            "warp": self.query_one("#warp", WarpScreen),
            "config": self.query_one("#config", ConfigScreen),
            "logs": self.query_one("#logs", LogsScreen),
        }
        self.show_screen("dashboard")
        await self._check_singbox_binary_on_startup()
        await self._auto_apply_selected_node_on_startup()
        await self.refresh_dashboard_state()

    async def on_unmount(self) -> None:
        await self.controller.stop()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = getattr(event.tab, "id", "") or ""
        if not tab_id.startswith("tab-"):
            return
        screen_name = tab_id.removeprefix("tab-")
        if screen_name != self.current_screen_name:
            self.show_screen(screen_name)

    def action_go(self, name: str) -> None:
        self.show_screen(name)

    def action_dashboard(self) -> None:
        self.show_screen("dashboard")

    async def action_apply(self) -> None:
        await self.apply_runtime_config()

    async def action_refresh(self) -> None:
        await self.refresh_current_screen()

    def show_screen(self, name: str) -> None:
        if name not in self._screen_map:
            return
        self.current_screen_name = name
        for screen_name, widget in self._screen_map.items():
            widget.display = screen_name == name
        self._update_navigation_widgets()
        if self.is_mounted:
            self.run_worker(self.refresh_current_screen(), group="screen-refresh", exclusive=True)

    async def refresh_current_screen(self) -> None:
        if self.current_screen_name == "dashboard":
            await self.refresh_dashboard_state()
            dashboard = self.query_one("#dashboard", DashboardScreen)
            dashboard.focus_primary_action()
            return

        screen = self._screen_map[self.current_screen_name]
        refresh_method = getattr(screen, "refresh_screen", None)
        if refresh_method is not None:
            result = refresh_method()
            if hasattr(result, "__await__"):
                await result
        self._update_footer()

    async def refresh_dashboard_state(self) -> DashboardState:
        self.dashboard_state = await self.get_dashboard_state()
        if self._can_query_ui():
            dashboard = self.query_one("#dashboard", DashboardScreen)
            dashboard.update_state(self.dashboard_state, self.last_action_message)
        self._update_footer()
        return self.dashboard_state

    async def get_dashboard_state(self) -> DashboardState:
        preferences = await self.preferences_repo.get_preferences()
        selected_node, subscriptions, all_nodes = await asyncio.gather(
            self._get_selected_node(preferences.selected_node_id),
            self.subscriptions_repo.list_subscriptions(),
            self.nodes_repo.list_nodes(),
        )
        selected_subscription = self._find_subscription(subscriptions, selected_node)

        return DashboardState(
            subscription_name=selected_subscription.name if selected_subscription else "未选择",
            subscription_updated_at=self._format_subscription_update(selected_subscription),
            node_name=selected_node.tag if selected_node else "未选择",
            node_protocol=selected_node.protocol if selected_node else "未提供",
            node_port=self._extract_node_port(selected_node),
            node_count=len(all_nodes),
            singbox_status=self._get_singbox_status(),
            routing_mode=preferences.routing_mode,
            dns_leak_protection="开启" if preferences.dns_leak_protection else "关闭",
            warp_enabled="开启" if preferences.warp_enabled else "关闭",
        )

    async def _get_selected_node(self, node_id: int | None) -> Node | None:
        if node_id is None:
            return None
        return await self.nodes_repo.get_node(node_id)

    def _find_subscription(self, subscriptions: list[Subscription], node: Node | None) -> Subscription | None:
        if node is None:
            return None
        for subscription in subscriptions:
            if subscription.id == node.sub_id:
                return subscription
        return None

    def _format_subscription_update(self, subscription: Subscription | None) -> str:
        if subscription is None or subscription.last_update is None:
            return "未更新"
        return subscription.last_update.strftime("%Y-%m-%d %H:%M:%S")

    def _extract_node_port(self, node: Node | None) -> str:
        if node is None:
            return "未提供"
        try:
            config = json.loads(node.config_json)
        except json.JSONDecodeError:
            return "未提供"

        for key in ("server_port", "port"):
            value = config.get(key)
            if isinstance(value, int):
                return str(value)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "未提供"

    def _get_singbox_status(self) -> str:
        status_method = getattr(self.controller, "status", None)
        if callable(status_method):
            return str(status_method())
        return "stopped"

    def _can_query_ui(self) -> bool:
        if not self.is_mounted:
            return False
        try:
            self.query_one("#tabs", Tabs)
        except (NoMatches, ScreenStackError):
            return False
        return True

    def _update_navigation_widgets(self) -> None:
        if not self._can_query_ui():
            return
        tabs = self.query_one("#tabs", Tabs)
        active_tab_id = f"tab-{self.current_screen_name}"
        if tabs.active != active_tab_id:
            tabs.active = active_tab_id
        self._update_footer()

    def _update_footer(self) -> None:
        if not self._can_query_ui():
            return
        footer = self.query_one(StatusFooter)
        footer.update_status(
            current_screen=self.SCREEN_LABELS.get(self.current_screen_name, self.current_screen_name),
            singbox_status=self.dashboard_state.singbox_status,
            last_message=self.last_action_message,
        )

    async def _check_singbox_binary_on_startup(self) -> None:
        preferences = await self.preferences_repo.get_preferences()
        result = self.singbox_binary_service.resolve_binary(preferences)
        if result.ok:
            return
        msg = self.singbox_binary_service.get_missing_binary_message(result)
        self.last_action_message = msg
        self.append_log(msg)
        await self.refresh_dashboard_state()

    async def _auto_apply_selected_node_on_startup(self) -> None:
        preferences = await self.preferences_repo.get_preferences()
        selected_node = await self._get_selected_node(preferences.selected_node_id)
        if selected_node is None:
            return
        await self.apply_runtime_config()

    def validate_singbox_binary_input(self, raw_value: str | None) -> tuple[str | None, str | None]:
        normalized = self.singbox_binary_service.normalize_input(raw_value)
        if normalized is None:
            return None, None
        result = self.singbox_binary_service.validate_configured_path(raw_value)
        if result.ok:
            return result.binary_path, None
        return None, self.singbox_binary_service.get_missing_binary_message(result)

    async def ensure_singbox_binary_ready(self) -> tuple[bool, str | None, SingboxBinaryCheckResult]:
        preferences = await self.preferences_repo.get_preferences()
        result = self.singbox_binary_service.resolve_binary(preferences)
        if result.ok:
            return True, result.binary_path, result
        return False, None, result

    def append_log(self, line: str) -> None:
        normalized = line.rstrip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {normalized}"
        self.logs.append(formatted)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

        try:
            self.settings.app_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings.app_log_path.open("a", encoding="utf-8") as f:
                f.write(f"{formatted}\n")
        except OSError:
            pass

        if self.is_mounted and self.current_screen_name == "logs":
            try:
                logs_screen = self.query_one("#logs", LogsScreen)
                logs_screen.append_log_line(formatted)
            except (NoMatches, ScreenStackError):
                pass

    async def _finalize_runtime_apply(self, ok: bool, msg: str) -> tuple[bool, str]:
        self.last_action_message = msg
        self.append_log(msg)
        await self.refresh_dashboard_state()
        return ok, msg

    async def apply_runtime_config(self) -> tuple[bool, str]:
        try:
            config = await self.config_builder.build_config()
        except ValueError as exc:
            return await self._finalize_runtime_apply(False, f"应用失败（业务校验）: {exc}")
        except Exception as exc:  # noqa: BLE001
            return await self._finalize_runtime_apply(False, f"应用失败（配置生成）: {exc}")

        binary_ready, binary_path, binary_result = await self.ensure_singbox_binary_ready()
        if not binary_ready:
            return await self._finalize_runtime_apply(
                False,
                f"应用失败（sing-box 检测）: {self.singbox_binary_service.get_missing_binary_message(binary_result)}",
            )

        config_json = config.model_dump_json(indent=2, exclude_none=True)
        try:
            self.settings.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings.runtime_config_path.write_text(config_json, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return await self._finalize_runtime_apply(False, f"应用失败（配置写入）: {exc}")

        self.controller.binary = binary_path or self.controller.binary
        result = await self.controller.restart(self.settings.runtime_config_path)
        if result.ok:
            return await self._finalize_runtime_apply(True, "配置已应用并重启 sing-box")
        return await self._finalize_runtime_apply(
            False,
            f"应用失败（sing-box 重启）: {result.error or 'unknown error'}",
        )


def run() -> None:
    app = TSingBoxApp()
    app.run()
