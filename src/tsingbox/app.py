from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from contextlib import suppress

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
from tsingbox.data.repositories.rule_files import RuleFilesRepository
from tsingbox.data.repositories.routing_rules import RoutingRulesRepository
from tsingbox.data.repositories.routing_rule_sets import RoutingRuleSetsRepository
from tsingbox.data.repositories.subscriptions import SubscriptionsRepository
from tsingbox.data.repositories.warp_accounts import WarpAccountsRepository
from tsingbox.services.config_builder import ConfigBuilder
from tsingbox.services.proxy_latency_probe import ProxyLatencyProbe, ProxyProbeResult, ProxyProbeStatus
from tsingbox.services.rule_file_service import RuleFileService
from tsingbox.services.singbox_binary_service import SingboxBinaryCheckResult, SingboxBinaryService
from tsingbox.services.singbox_controller import SingboxController
from tsingbox.services.singbox_version_manager import SingboxVersionManager
from tsingbox.services.subscription_manager import SubscriptionManager
from tsingbox.services.warp_bootstrap_resolver import WarpBootstrapResolver
from tsingbox.services.warp_generator import WarpGenerator
from tsingbox.ui.screens.config import ConfigScreen
from tsingbox.ui.screens.dashboard import DashboardScreen
from tsingbox.ui.screens.logs import LogsScreen
from tsingbox.ui.screens.nodes import NodesScreen
from tsingbox.ui.screens.rules import RulesScreen
from tsingbox.ui.screens.settings import SettingsScreen
from tsingbox.ui.screens.singbox_versions import SingboxVersionsScreen
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
    inbound_port: str
    node_count: int
    singbox_status: str
    proxy_latency: str
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
        ("4", "go('settings')", "设置"),
        ("5", "go('rules')", "规则"),
        ("6", "go('warp')", "WARP"),
        ("7", "go('singbox_versions')", "内核"),
        ("8", "go('config')", "配置"),
        ("9", "go('logs')", "日志"),
        ("a", "apply", "应用"),
        ("r", "refresh", "刷新"),
        ("escape", "dashboard", "返回总览"),
    ]

    SCREEN_LABELS = {
        "dashboard": "总览",
        "subscriptions": "订阅",
        "nodes": "节点",
        "settings": "设置",
        "rules": "规则",
        "warp": "WARP",
        "singbox_versions": "内核",
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
        self.rule_files_repo = RuleFilesRepository(self.database)
        self.routing_rule_sets_repo = RoutingRuleSetsRepository(self.database)
        self.routing_rules_repo = RoutingRulesRepository(self.database)

        self.subscription_manager = SubscriptionManager(
            subscriptions_repo=self.subscriptions_repo,
            nodes_repo=self.nodes_repo,
        )
        self.rule_file_service = RuleFileService(repository=self.rule_files_repo)
        self.config_builder = ConfigBuilder(
            nodes_repo=self.nodes_repo,
            preferences_repo=self.preferences_repo,
            routing_rule_sets_repo=self.routing_rule_sets_repo,
            routing_rules_repo=self.routing_rules_repo,
            warp_repo=self.warp_repo,
            rule_file_service=self.rule_file_service,
        )
        self.controller = SingboxController(log_callback=self.append_log)
        self.singbox_binary_service = SingboxBinaryService()
        self.version_manager = SingboxVersionManager(
            versions_dir=self.settings.versions_dir,
            log_callback=self.append_log,
        )
        self.warp_generator = WarpGenerator(self.warp_repo, log_callback=self.append_log)
        self.warp_bootstrap_resolver = WarpBootstrapResolver(self.warp_repo, log_callback=self.append_log)
        self.proxy_latency_probe = ProxyLatencyProbe()

        self.logs: list[str] = []
        self._screen_map: dict[str, Screen] = {}
        self.current_screen_name = "dashboard"
        self.last_action_message = "准备就绪"
        self.startup_in_progress = False
        self.startup_status_message: str | None = None
        self.apply_in_progress = False
        self.apply_owner: str | None = None
        self.apply_status_message: str | None = None
        self._startup_worker_scheduled = False
        self._apply_lock = asyncio.Lock()
        self._proxy_probe_lock = asyncio.Lock()
        self._proxy_probe_task: asyncio.Task[None] | None = None
        self._delayed_proxy_probe_task: asyncio.Task[None] | None = None
        self._proxy_probe_stop = asyncio.Event()
        self._proxy_probe_interval = 30.0
        self._proxy_probe_delay_after_restart = 3.0
        self._proxy_probe_result = ProxyProbeResult(status=ProxyProbeStatus.UNTESTED)
        self.dashboard_state = DashboardState(
            subscription_name="未选择",
            subscription_updated_at="未更新",
            node_name="未选择",
            node_protocol="未提供",
            node_port="未提供",
            inbound_port="未提供",
            node_count=0,
            singbox_status="stopped",
            proxy_latency="--",
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
                yield SettingsScreen(id="settings")
                yield RulesScreen(id="rules")
                yield WarpScreen(id="warp")
                yield SingboxVersionsScreen(id="singbox_versions")
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
            "settings": self.query_one("#settings", SettingsScreen),
            "rules": self.query_one("#rules", RulesScreen),
            "warp": self.query_one("#warp", WarpScreen),
            "singbox_versions": self.query_one("#singbox_versions", SingboxVersionsScreen),
            "config": self.query_one("#config", ConfigScreen),
            "logs": self.query_one("#logs", LogsScreen),
        }
        self.show_screen("dashboard")
        await self.refresh_dashboard_state()
        self._start_proxy_probe_worker()
        self._schedule_startup_tasks()

    async def on_unmount(self) -> None:
        self._proxy_probe_stop.set()
        if self._proxy_probe_task is not None:
            self._proxy_probe_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._proxy_probe_task
        if self._delayed_proxy_probe_task is not None:
            self._delayed_proxy_probe_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._delayed_proxy_probe_task
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
        await self.request_apply(reason="action")

    async def action_refresh(self) -> None:
        if self.current_screen_name != "dashboard":
            await self.trigger_proxy_latency_refresh()
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
            await self.trigger_proxy_latency_refresh()
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
        status_message = self._current_status_message()
        if self._can_query_ui():
            dashboard = self.query_one("#dashboard", DashboardScreen)
            dashboard.update_state(self.dashboard_state, status_message)
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

        singbox_status = self._get_singbox_status()
        return DashboardState(
            subscription_name=selected_subscription.name if selected_subscription else "未选择",
            subscription_updated_at=self._format_subscription_update(selected_subscription),
            node_name=selected_node.tag if selected_node else "未选择",
            node_protocol=selected_node.protocol if selected_node else "未提供",
            node_port=self._extract_node_port(selected_node),
            inbound_port=self._extract_inbound_port(),
            node_count=len(all_nodes),
            singbox_status=singbox_status,
            proxy_latency=self._format_proxy_latency(singbox_status),
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

    def _extract_inbound_port(self) -> str:
        try:
            raw_content = self.settings.runtime_config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "未提供"
        except OSError:
            return "未提供"

        try:
            config = json.loads(raw_content)
        except json.JSONDecodeError:
            return "未提供"

        inbounds = config.get("inbounds")
        if not isinstance(inbounds, list):
            return "未提供"

        for inbound in inbounds:
            if not isinstance(inbound, dict):
                continue
            value = inbound.get("listen_port")
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

    def _format_proxy_latency(self, singbox_status: str) -> str:
        if singbox_status != "running":
            return "--"
        return self._proxy_probe_result.display_text

    async def trigger_proxy_latency_refresh(self) -> None:
        if self._proxy_probe_lock.locked():
            return
        await self._refresh_proxy_latency()

    def _start_proxy_probe_worker(self) -> None:
        if self._proxy_probe_task is not None:
            return
        self._proxy_probe_stop.clear()
        self._proxy_probe_task = asyncio.create_task(self._proxy_probe_loop())

    def _schedule_delayed_proxy_latency_refresh(self) -> None:
        if self._delayed_proxy_probe_task is not None:
            self._delayed_proxy_probe_task.cancel()
        self._delayed_proxy_probe_task = asyncio.create_task(self._run_delayed_proxy_latency_refresh())

    async def _run_delayed_proxy_latency_refresh(self) -> None:
        try:
            await asyncio.sleep(self._proxy_probe_delay_after_restart)
            if self._proxy_probe_stop.is_set():
                return
            await self.trigger_proxy_latency_refresh()
        except asyncio.CancelledError:
            raise
        finally:
            current = asyncio.current_task()
            if self._delayed_proxy_probe_task is current:
                self._delayed_proxy_probe_task = None

    async def _proxy_probe_loop(self) -> None:
        while not self._proxy_probe_stop.is_set():
            await self._refresh_proxy_latency()
            try:
                await asyncio.wait_for(self._proxy_probe_stop.wait(), timeout=self._proxy_probe_interval)
            except asyncio.TimeoutError:
                continue

    async def _refresh_proxy_latency(self) -> None:
        async with self._proxy_probe_lock:
            singbox_status = self._get_singbox_status()
            if singbox_status != "running":
                self._proxy_probe_result = ProxyProbeResult(status=ProxyProbeStatus.UNTESTED)
                await self.refresh_dashboard_state()
                return

            inbound_port = self._extract_inbound_port()
            if not inbound_port.isdigit():
                self._proxy_probe_result = ProxyProbeResult(status=ProxyProbeStatus.UNTESTED)
                await self.refresh_dashboard_state()
                return

            self._proxy_probe_result = ProxyProbeResult(status=ProxyProbeStatus.TESTING)
            await self.refresh_dashboard_state()
            proxy_url = f"http://127.0.0.1:{inbound_port}"
            self._proxy_probe_result = await self.proxy_latency_probe.probe(proxy_url=proxy_url)
            await self.refresh_dashboard_state()

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
            proxy_latency=self.dashboard_state.proxy_latency,
            last_message=self._current_status_message(),
        )

    def _schedule_startup_tasks(self) -> None:
        if self._startup_worker_scheduled:
            return
        self._startup_worker_scheduled = True
        self.run_worker(
            self._run_startup_sequence(),
            group="startup",
            exclusive=True,
        )

    async def _run_startup_sequence(self) -> None:
        self.startup_in_progress = True
        self.startup_status_message = "启动中：正在检查 sing-box 可执行文件"
        self.last_action_message = self.startup_status_message
        self.append_log("开始后台启动检查")
        await self.refresh_dashboard_state()
        try:
            should_auto_apply = await self._check_singbox_binary_on_startup()
            if should_auto_apply:
                self.startup_status_message = "启动中：正在后台应用已选节点"
                self.last_action_message = self.startup_status_message
                self.append_log("检测到已选节点，开始后台自动应用")
                await self.refresh_dashboard_state()
                await self._auto_apply_selected_node_on_startup()
            else:
                self.append_log("启动阶段未触发自动应用")
        except Exception as exc:  # noqa: BLE001
            message = f"启动流程失败: {exc}"
            self.last_action_message = message
            self.append_log(message)
            await self.refresh_dashboard_state()
        finally:
            self.startup_in_progress = False
            self.startup_status_message = None
            self.append_log("启动流程完成")
            await self.refresh_dashboard_state()

    async def _check_singbox_binary_on_startup(self) -> bool:
        binary_ready, _, binary_result = await self.ensure_singbox_binary_ready()
        if not binary_ready:
            msg = self.singbox_binary_service.get_missing_binary_message(binary_result)
            self.last_action_message = msg
            self.append_log(f"sing-box 检查失败: {msg}")
            await self.refresh_dashboard_state()
            return False
        self.append_log("sing-box 检查通过")
        preferences = await self.preferences_repo.get_preferences()
        selected_node = await self._get_selected_node(preferences.selected_node_id)
        return selected_node is not None

    async def _auto_apply_selected_node_on_startup(self) -> tuple[bool, str] | None:
        preferences = await self.preferences_repo.get_preferences()
        selected_node = await self._get_selected_node(preferences.selected_node_id)
        if selected_node is None:
            self.append_log("启动阶段未找到已选节点，跳过自动应用")
            return None
        return await self.request_apply_runtime_config(source="startup")

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
        result = self.singbox_binary_service.resolve_binary(
            preferences, versions_dir=self.settings.versions_dir
        )
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

    def _current_status_message(self) -> str:
        if self.startup_in_progress and self.startup_status_message:
            return self.startup_status_message
        if self.apply_in_progress and self.apply_status_message:
            return self.apply_status_message
        return self.last_action_message

    async def _set_apply_state(
        self,
        applying: bool,
        *,
        owner: str | None = None,
        message: str | None = None,
    ) -> None:
        self.apply_in_progress = applying
        self.apply_owner = owner if applying else None
        self.apply_status_message = message if applying else None
        await self.refresh_dashboard_state()

    async def request_apply_runtime_config(self, *, source: str = "user") -> tuple[bool, str]:
        source_labels = {
            "startup": "启动自动应用",
            "user": "用户手动应用",
            "node_select": "节点切换应用",
            "action": "快捷键应用",
            "manual": "手动应用",
        }
        if self._apply_lock.locked():
            active_owner = source_labels.get(self.apply_owner or "", self.apply_owner or "未知来源")
            msg = f"已有应用任务进行中（来源: {active_owner}）"
            if source == "startup":
                self.append_log(f"启动自动应用跳过：{msg}")
                return False, msg
            self.last_action_message = msg
            self.append_log(msg)
            await self.refresh_dashboard_state()
            return False, msg

        apply_message = {
            "startup": "启动中：正在后台应用已选节点",
            "node_select": "正在应用节点...",
            "user": "正在应用配置...",
            "action": "正在应用配置...",
            "manual": "正在应用配置...",
        }.get(source, "正在应用配置...")

        async with self._apply_lock:
            await self._set_apply_state(True, owner=source, message=apply_message)
            try:
                return await self.apply_runtime_config()
            finally:
                await self._set_apply_state(False)

    async def request_apply(self, *, reason: str = "manual") -> tuple[bool, str]:
        return await self.request_apply_runtime_config(source=reason)

    async def _finalize_runtime_apply(self, ok: bool, msg: str) -> tuple[bool, str]:
        self.last_action_message = msg
        self.append_log(msg)
        await self.refresh_dashboard_state()
        return ok, msg

    async def apply_runtime_config(self) -> tuple[bool, str]:
        try:
            bootstrap_stages = await self.config_builder.build_bootstrap_stages()
            await self.config_builder.build_config(predefined_hosts={})
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

        self.controller.binary = binary_path or self.controller.binary

        try:
            predefined_hosts = await self._resolve_runtime_stage_hosts(bootstrap_stages)
        except RuntimeError as exc:
            return await self._finalize_runtime_apply(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            return await self._finalize_runtime_apply(False, f"应用失败（阶段预解析）: {exc}")

        try:
            final_config = await self.config_builder.build_config(predefined_hosts=predefined_hosts)
        except ValueError as exc:
            return await self._finalize_runtime_apply(False, f"应用失败（业务校验）: {exc}")
        except Exception as exc:  # noqa: BLE001
            return await self._finalize_runtime_apply(False, f"应用失败（配置生成）: {exc}")

        self.append_log("切换到正式链式配置")
        return await self._write_and_restart_final_config(final_config)

    async def _resolve_runtime_stage_hosts(self, stages) -> dict[str, list[str]]:
        predefined_hosts: dict[str, list[str]] = {}
        if not stages:
            return predefined_hosts

        for index, stage in enumerate(stages, start=1):
            self.append_log(f"启动第 {index} 层临时代理用于预解析")
            try:
                await self._write_bootstrap_config(stage.config)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"应用失败（bootstrap 配置写入）: {exc}") from exc
            bootstrap_result = await self.controller.restart(self.settings.runtime_bootstrap_config_path)
            if not bootstrap_result.ok:
                raise RuntimeError(f"应用失败（bootstrap sing-box 重启）: {bootstrap_result.error or 'unknown error'}")

            bootstrap_port = stage.config.inbounds[0]["listen_port"]

            # Wait for proxy port to be ready
            port_ready = False
            for _ in range(50):
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", bootstrap_port)
                    writer.close()
                    await writer.wait_closed()
                    port_ready = True
                    break
                except OSError:
                    await asyncio.sleep(0.1)

            if not port_ready:
                raise RuntimeError(f"应用失败（预解析代理端口 {bootstrap_port} 未就绪）")

            proxy_url = f"http://127.0.0.1:{bootstrap_port}"
            try:
                resolved_hosts = await self.warp_bootstrap_resolver.resolve_hosts(
                    proxy_url=proxy_url,
                    hosts=stage.resolve_hosts,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"应用失败（阶段预解析）: {exc}") from exc
            predefined_hosts.update(resolved_hosts)
            self.append_log(f"第 {index} 层解析结果: {resolved_hosts}")
            if index < len(stages):
                self.append_log(f"切换到第 {index + 1} 阶段配置")
        return predefined_hosts

    async def _write_bootstrap_config(self, bootstrap_config) -> None:
        bootstrap_json = bootstrap_config.model_dump_json(indent=2, exclude_none=True)
        self.settings.runtime_bootstrap_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.runtime_bootstrap_config_path.write_text(bootstrap_json, encoding="utf-8")

    async def _write_and_restart_final_config(self, config) -> tuple[bool, str]:
        config_json = config.model_dump_json(indent=2, exclude_none=True)
        try:
            self.settings.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings.runtime_config_path.write_text(config_json, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return await self._finalize_runtime_apply(False, f"应用失败（配置写入）: {exc}")

        result = await self.controller.restart(self.settings.runtime_config_path)
        if result.ok:
            self._schedule_delayed_proxy_latency_refresh()
            return await self._finalize_runtime_apply(True, "配置已应用并重启 sing-box")
        return await self._finalize_runtime_apply(
            False,
            f"应用失败（sing-box 重启）: {result.error or 'unknown error'}",
        )


def run() -> None:
    app = TSingBoxApp()
    app.run()
