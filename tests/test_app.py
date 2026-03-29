from __future__ import annotations

import asyncio
from pathlib import Path
import re

from unittest import mock

import pytest

from tsingbox.app import TSingBoxApp
from tsingbox.core.settings import Settings
from tsingbox.ui.screens.config import ConfigScreen
from tsingbox.ui.screens.dashboard import DashboardScreen
from tsingbox.services.singbox_binary_service import SingboxBinaryCheckResult, SingboxBinaryStatus
from tsingbox.services.proxy_latency_probe import ProxyProbeResult, ProxyProbeStatus
from tsingbox.services.singbox_controller import ControlResult
from conftest import create_initialized_app
from textual.widgets import Button, Input, Log, OptionList, Static, Switch


class DummyConfig:
    def __init__(self, payload: str = '{"outbounds": []}', *, endpoints=None, inbounds=None) -> None:
        self.payload = payload
        self.endpoints = endpoints or []
        self.inbounds = inbounds or [{"listen_port": 7890}]

    def model_dump_json(self, **kwargs) -> str:
        return self.payload


class DummyStage:
    def __init__(self, config: DummyConfig, resolve_hosts: list[str]) -> None:
        self.config = config
        self.resolve_hosts = resolve_hosts


class FailingBuilder:
    async def build_config(self, **kwargs):
        raise ValueError("尚未选择节点")

    async def build_bootstrap_stages(self):
        return []


class SuccessBuilder:
    async def build_config(self, **kwargs):
        return DummyConfig()

    async def build_bootstrap_stages(self):
        return []


class StageBuilder:
    def __init__(self) -> None:
        self.build_config_calls: list[dict] = []
        self.stage_calls = 0

    async def build_config(self, **kwargs):
        self.build_config_calls.append(kwargs)
        predefined_hosts = kwargs.get("predefined_hosts") or {}
        payload = '{"outbounds": []}'
        if predefined_hosts:
            payload = (
                '{"dns":{"servers":[{"type":"hosts","tag":"hosts-dns","predefined":'
                '{"engage.cloudflareclient.com":["198.51.100.10"]}}]}}'
            )
        return DummyConfig(payload)

    async def build_bootstrap_stages(self):
        self.stage_calls += 1
        return [
            DummyStage(
                DummyConfig('{"outbounds": [], "inbounds":[{"listen_port":17890}]}', inbounds=[{"listen_port": 17890}]),
                ["engage.cloudflareclient.com"],
            )
        ]


class IpWarpBuilder(StageBuilder):
    async def build_bootstrap_stages(self):
        self.stage_calls += 1
        return []


class RestartFailController:
    def __init__(self) -> None:
        self.binary = "sing-box"

    async def restart(self, config_path: Path) -> ControlResult:
        return ControlResult(ok=False, error="sing-box 可执行文件不存在")


class RestartSuccessController:
    def __init__(self) -> None:
        self.binary = "sing-box"
        self.restart_calls: list[Path] = []

    async def restart(self, config_path: Path) -> ControlResult:
        self.restart_calls.append(config_path)
        return ControlResult(ok=True)


class SequenceController(RestartSuccessController):
    def __init__(self, results: list[ControlResult] | None = None) -> None:
        super().__init__()
        self.results = results or []

    async def restart(self, config_path: Path) -> ControlResult:
        self.restart_calls.append(config_path)
        if self.results:
            return self.results.pop(0)
        return ControlResult(ok=True)


class GeneratedWarpAccount:
    local_address_v4 = "172.16.0.2/32"
    local_address_v6 = "2606:4700:110::2/128"
    reserved = "[7, 8, 9]"


def test_append_log_writes_to_file(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()

    app.append_log("hello")

    content = app.settings.app_log_path.read_text(encoding="utf-8")
    assert len(app.logs) == 1
    assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] hello", app.logs[0])
    assert content.strip() == app.logs[0]


def test_append_log_file_error_does_not_break_memory(monkeypatch, tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()

    def fake_open(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", fake_open)

    app.append_log("still-in-memory")

    assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] still-in-memory", app.logs[-1])


@pytest.mark.asyncio
async def test_get_dashboard_state_without_selected_node(tmp_path):
    app = await create_initialized_app(tmp_path)

    state = await app.get_dashboard_state()

    assert state.subscription_name == "未选择"
    assert state.subscription_updated_at == "未更新"
    assert state.node_name == "未选择"
    assert state.node_port == "未提供"
    assert state.inbound_port == "未提供"
    assert state.node_count == 0
    assert state.singbox_status == "stopped"
    assert state.proxy_latency == "--"
    assert state.routing_mode == "global"
    assert state.dns_leak_protection == "关闭"
    assert state.warp_enabled == "关闭"


@pytest.mark.asyncio
async def test_get_dashboard_state_with_selected_node_and_subscription(tmp_path):
    app = await create_initialized_app(tmp_path)
    sub_id, inserted = await app.subscriptions_repo.upsert_and_replace_nodes(
        name="校园订阅",
        url="https://example.com/sub",
        nodes=[
            {
                "tag": "节点 A",
                "protocol": "vless",
                "config": {"tag": "node-a", "server": "example.com", "server_port": 443},
            }
        ],
    )
    assert inserted == 1

    nodes = await app.nodes_repo.list_nodes()
    await app.preferences_repo.set_selected_node(nodes[0].id)

    app.settings.runtime_config_path.write_text('{"inbounds":[{"listen_port":7890}]}', encoding="utf-8")

    state = await app.get_dashboard_state()

    assert nodes[0].sub_id == sub_id
    assert state.subscription_name == "校园订阅"
    assert state.subscription_updated_at != "未更新"
    assert state.node_name == "节点 A"
    assert state.node_protocol == "vless"
    assert state.node_port == "443"
    assert state.inbound_port == "7890"
    assert state.node_count == 1


@pytest.mark.asyncio
async def test_get_dashboard_state_uses_running_status_and_missing_port_fallback(monkeypatch, tmp_path):
    app = await create_initialized_app(tmp_path)
    await app.subscriptions_repo.upsert_and_replace_nodes(
        name="无端口订阅",
        url="https://example.com/no-port",
        nodes=[
            {
                "tag": "节点 B",
                "protocol": "trojan",
                "config": {"tag": "node-b", "server": "example.com"},
            }
        ],
    )
    node = (await app.nodes_repo.list_nodes())[0]
    await app.preferences_repo.set_selected_node(node.id)
    await app.preferences_repo.update_preferences(
        routing_mode="global",
        dns_leak_protection=True,
        warp_enabled=True,
    )
    monkeypatch.setattr(app.controller, "status", lambda: "running")

    state = await app.get_dashboard_state()

    assert state.singbox_status == "running"
    assert state.proxy_latency == "未测试"
    assert state.node_port == "未提供"
    assert state.inbound_port == "未提供"
    assert state.routing_mode == "global"
    assert state.dns_leak_protection == "开启"
    assert state.warp_enabled == "开启"


@pytest.mark.asyncio
async def test_apply_runtime_config_validation_error(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    app.config_builder = FailingBuilder()
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert not ok
    assert "业务校验" in msg
    assert "尚未选择节点" in msg
    assert app.last_action_message == msg


@pytest.mark.asyncio
async def test_apply_runtime_config_restart_error(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    app.config_builder = SuccessBuilder()
    app.controller = RestartFailController()
    app.ensure_singbox_binary_ready = fake_ready_check  # type: ignore[method-assign]
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert not ok
    assert "sing-box 重启" in msg
    assert "不存在" in msg
    assert app.last_action_message == msg


class SuccessResolver:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def resolve_hosts(self, *, proxy_url: str, hosts: list[str]):
        self.calls.append({"proxy_url": proxy_url, "hosts": hosts})
        return {"engage.cloudflareclient.com": ["198.51.100.10"]}


class FailingResolver:
    async def resolve_hosts(self, *, proxy_url: str, hosts: list[str]):
        raise RuntimeError("resolver boom")


async def fake_ready_check():
    return True, "/custom/bin/sing-box", SingboxBinaryCheckResult(
        status=SingboxBinaryStatus.CONFIGURED_VALID,
        binary_path="/custom/bin/sing-box",
        configured_path="/custom/bin/sing-box",
    )


@pytest.mark.asyncio
async def test_apply_runtime_config_fails_before_restart_when_binary_missing(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    app.config_builder = SuccessBuilder()
    controller = RestartSuccessController()
    app.controller = controller
    await app.database.initialize()

    async def fake_missing_check():
        return False, None, SingboxBinaryCheckResult(
            status=SingboxBinaryStatus.PATH_NOT_FOUND,
            binary_path=None,
            configured_path=None,
        )

    app.ensure_singbox_binary_ready = fake_missing_check  # type: ignore[method-assign]

    ok, msg = await app.apply_runtime_config()

    assert not ok
    assert "sing-box 检测" in msg
    assert "未检测到系统 sing-box" in msg
    assert controller.restart_calls == []


@pytest.mark.asyncio
async def test_apply_runtime_config_uses_resolved_binary(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    app.config_builder = SuccessBuilder()
    controller = RestartSuccessController()
    app.controller = controller
    app.ensure_singbox_binary_ready = fake_ready_check  # type: ignore[method-assign]
    app._schedule_delayed_proxy_latency_refresh = mock.MagicMock()  # type: ignore[method-assign]
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert ok
    assert controller.binary == "/custom/bin/sing-box"
    assert controller.restart_calls == [app.settings.runtime_config_path]
    assert msg == "配置已应用并重启 sing-box"
    app._schedule_delayed_proxy_latency_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_delayed_proxy_latency_refresh_cancels_previous_task():
    app = TSingBoxApp()

    first_task = mock.MagicMock()
    app._delayed_proxy_probe_task = first_task

    created_tasks: list[object] = []
    original_create_task = asyncio.create_task

    def fake_create_task(coro):
        task = mock.MagicMock()
        created_tasks.append(task)
        coro.close()
        return task

    with mock.patch("asyncio.create_task", side_effect=fake_create_task):
        app._schedule_delayed_proxy_latency_refresh()

    first_task.cancel.assert_called_once()
    assert len(created_tasks) == 1
    assert app._delayed_proxy_probe_task is created_tasks[0]


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
@mock.patch("asyncio.open_connection")
async def test_apply_runtime_config_runs_stage_flow_for_warp_domain(mock_open_conn, mock_sleep, tmp_path):
    # Mock open_connection to simulate a ready proxy port
    mock_writer = mock.MagicMock()
    mock_writer.wait_closed = mock.AsyncMock()
    mock_open_conn.return_value = (mock.AsyncMock(), mock_writer)

    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    builder = StageBuilder()
    controller = SequenceController()
    resolver = SuccessResolver()
    app.config_builder = builder
    app.controller = controller
    app.warp_bootstrap_resolver = resolver
    app.ensure_singbox_binary_ready = fake_ready_check  # type: ignore[method-assign]
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert ok
    assert msg == "配置已应用并重启 sing-box"
    assert builder.stage_calls == 1
    assert builder.build_config_calls == [
        {"predefined_hosts": {}},
        {"predefined_hosts": {"engage.cloudflareclient.com": ["198.51.100.10"]}},
    ]
    assert resolver.calls == [{"proxy_url": "http://127.0.0.1:17890", "hosts": ["engage.cloudflareclient.com"]}]
    assert controller.restart_calls == [
        app.settings.runtime_bootstrap_config_path,
        app.settings.runtime_config_path,
    ]
    assert "hosts-dns" in app.settings.runtime_config_path.read_text(encoding="utf-8")
    assert any("启动第 1 层临时代理用于预解析" in line for line in app.logs)
    assert any("第 1 层解析结果" in line for line in app.logs)
    assert any("切换到正式链式配置" in line for line in app.logs)


@pytest.mark.asyncio
@mock.patch("asyncio.sleep")
@mock.patch("asyncio.open_connection")
async def test_apply_runtime_config_keeps_old_runtime_when_stage_resolution_fails(mock_open_conn, mock_sleep, tmp_path):
    # Mock open_connection to simulate a ready proxy port
    mock_writer = mock.MagicMock()
    mock_writer.wait_closed = mock.AsyncMock()
    mock_open_conn.return_value = (mock.AsyncMock(), mock_writer)

    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    app.settings.runtime_config_path.write_text('{"existing": true}', encoding="utf-8")
    app.config_builder = StageBuilder()
    app.controller = SequenceController()
    app.warp_bootstrap_resolver = FailingResolver()
    app.ensure_singbox_binary_ready = fake_ready_check  # type: ignore[method-assign]
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert not ok
    assert "阶段预解析" in msg
    assert app.settings.runtime_config_path.read_text(encoding="utf-8") == '{"existing": true}'
    assert app.controller.restart_calls == [app.settings.runtime_bootstrap_config_path]


@pytest.mark.asyncio
async def test_apply_runtime_config_skips_stage_flow_when_no_bootstrap_stage(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.database.settings = app.settings
    app.settings.ensure_dirs()
    builder = IpWarpBuilder()
    controller = SequenceController()
    resolver = SuccessResolver()
    app.config_builder = builder
    app.controller = controller
    app.warp_bootstrap_resolver = resolver
    app.ensure_singbox_binary_ready = fake_ready_check  # type: ignore[method-assign]
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert ok
    assert msg == "配置已应用并重启 sing-box"
    assert builder.stage_calls == 1
    assert builder.build_config_calls == [{"predefined_hosts": {}}, {"predefined_hosts": {}}]
    assert resolver.calls == []
    assert controller.restart_calls == [app.settings.runtime_config_path]


@pytest.mark.asyncio
async def test_startup_check_sets_message_when_system_binary_missing(tmp_path):
    app = await create_initialized_app(tmp_path)

    app.singbox_binary_service.resolve_binary = lambda preferences, **kwargs: SingboxBinaryCheckResult(  # type: ignore[method-assign]
        status=SingboxBinaryStatus.PATH_NOT_FOUND,
        binary_path=None,
        configured_path=None,
    )

    should_auto_apply = await app._check_singbox_binary_on_startup()

    assert should_auto_apply is False
    assert "未检测到系统 sing-box" in app.last_action_message


def test_config_screen_missing_file(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)

    status, content = ConfigScreen._load_config_content(app.settings.runtime_config_path)

    assert status == "runtime 配置文件不存在，可能尚未应用配置"
    assert content == "暂无配置内容"


def test_config_screen_empty_file(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.settings.ensure_dirs()
    app.settings.runtime_config_path.write_text("", encoding="utf-8")

    status, content = ConfigScreen._load_config_content(app.settings.runtime_config_path)

    assert status == "runtime 配置文件为空"
    assert content == "暂无配置内容"


def test_config_screen_invalid_json_shows_raw_content(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.settings.ensure_dirs()
    app.settings.runtime_config_path.write_text("{invalid json", encoding="utf-8")

    status, content = ConfigScreen._load_config_content(app.settings.runtime_config_path)

    assert status == "runtime 配置文件不是合法 JSON，以下展示原始内容"
    assert content == "{invalid json"


def test_config_screen_formats_valid_json(tmp_path):
    app = TSingBoxApp()
    app.settings = Settings(base_dir=tmp_path)
    app.settings.ensure_dirs()
    app.settings.runtime_config_path.write_text('{"b":2,"a":{"c":1}}', encoding="utf-8")

    status, content = ConfigScreen._load_config_content(app.settings.runtime_config_path)

    assert status == "已加载 runtime 配置"
    assert content == '{\n  "b": 2,\n  "a": {\n    "c": 1\n  }\n}'


@pytest.mark.asyncio
async def test_config_screen_refresh_reads_latest_runtime_config(tmp_path):
    app = await create_initialized_app(tmp_path)
    app.settings.runtime_config_path.write_text('{"first":1}', encoding="utf-8")

    async with app.run_test() as pilot:
        await pilot.press("7")
        await pilot.pause()

        status = app.query_one("#config-status", Static)
        content = app.query_one("#config-content", Log)
        assert str(status.render()) == "已加载 runtime 配置"
        assert content.lines == ['{', '  "first": 1', '}']

        app.settings.runtime_config_path.write_text('{"second":2}', encoding="utf-8")
        await pilot.press("r")
        await pilot.pause()

        assert str(status.render()) == "已加载 runtime 配置"
        assert content.lines == ['{', '  "second": 2', '}']


@pytest.mark.asyncio
async def test_dashboard_screen_shows_inbound_port_from_runtime_config(tmp_path):
    app = await create_initialized_app(tmp_path)
    app.settings.runtime_config_path.write_text('{"inbounds":[{"listen_port":7890}]}', encoding="utf-8")

    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()

        inbound = app.query_one("#dashboard-inbound-port", Static)
        assert str(inbound.render()) == "本地代理端口: 7890"


@pytest.mark.asyncio
async def test_footer_shows_proxy_latency_when_probe_succeeds(tmp_path):
    app = await create_initialized_app(tmp_path)
    app._start_proxy_probe_worker = lambda: None  # type: ignore[method-assign]
    app._schedule_startup_tasks = lambda: None  # type: ignore[method-assign]
    app.trigger_proxy_latency_refresh = mock.AsyncMock()  # type: ignore[method-assign]
    app.settings.runtime_config_path.write_text('{"inbounds":[{"listen_port":7890}]}', encoding="utf-8")
    app._proxy_probe_result = ProxyProbeResult(status=ProxyProbeStatus.OK, latency_ms=183)
    app.controller.status = lambda: "running"  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one("#footer-status", Static)
        rendered = str(footer.render())
        assert "sing-box: running" in rendered
        assert "代理延迟: 183ms" in rendered


@pytest.mark.asyncio
async def test_footer_shows_proxy_unavailable_when_probe_fails(tmp_path):
    app = await create_initialized_app(tmp_path)
    app._start_proxy_probe_worker = lambda: None  # type: ignore[method-assign]
    app._schedule_startup_tasks = lambda: None  # type: ignore[method-assign]
    app.trigger_proxy_latency_refresh = mock.AsyncMock()  # type: ignore[method-assign]
    app.settings.runtime_config_path.write_text('{"inbounds":[{"listen_port":7890}]}', encoding="utf-8")
    app._proxy_probe_result = ProxyProbeResult(status=ProxyProbeStatus.UNAVAILABLE)
    app.controller.status = lambda: "running"  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one("#footer-status", Static)
        assert "代理延迟: 不可用" in str(footer.render())


@pytest.mark.asyncio
async def test_dashboard_refresh_triggers_proxy_probe_and_updates_footer(tmp_path):
    app = await create_initialized_app(tmp_path)
    app._start_proxy_probe_worker = lambda: None  # type: ignore[method-assign]
    app._schedule_startup_tasks = lambda: None  # type: ignore[method-assign]
    app.settings.runtime_config_path.write_text('{"inbounds":[{"listen_port":7890}]}', encoding="utf-8")
    app.controller.status = lambda: "running"  # type: ignore[method-assign]

    calls: list[str] = []

    async def fake_probe(*, proxy_url: str):
        calls.append(proxy_url)
        return ProxyProbeResult(status=ProxyProbeStatus.OK, latency_ms=188)

    app.proxy_latency_probe.probe = fake_probe  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        calls.clear()

        await pilot.click("#refresh-dashboard")
        await pilot.pause()
        await pilot.pause()

        footer = app.query_one("#footer-status", Static)
        rendered = str(footer.render())
        assert calls == ["http://127.0.0.1:7890"]
        assert "代理延迟: 188ms" in rendered


@pytest.mark.asyncio
async def test_logs_screen_appends_new_log_line_without_full_refresh(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("8")
        await pilot.pause()

        content = app.query_one("#logs-content", Log)
        initial_count = len(content.lines)

        app.append_log("hello")
        await pilot.pause()

        assert len(content.lines) == initial_count + 1
        assert content.lines[-1].endswith(" hello")


@pytest.mark.asyncio
async def test_startup_check_sets_message_when_configured_binary_invalid(tmp_path):
    app = await create_initialized_app(tmp_path)

    app.singbox_binary_service.resolve_binary = lambda preferences, **kwargs: SingboxBinaryCheckResult(  # type: ignore[method-assign]
        status=SingboxBinaryStatus.CONFIGURED_NOT_FOUND,
        binary_path=None,
        configured_path="/missing/sing-box",
    )

    should_auto_apply = await app._check_singbox_binary_on_startup()

    assert should_auto_apply is False
    assert "路径不存在" in app.last_action_message


@pytest.mark.asyncio
async def test_startup_tasks_run_in_background_without_blocking_initial_render(tmp_path):
    app = await create_initialized_app(tmp_path)
    startup_started = asyncio.Event()
    startup_released = asyncio.Event()
    startup_finished = asyncio.Event()

    async def fake_check_startup():
        app.startup_status_message = "启动中：正在检查 sing-box 可执行文件"
        app.last_action_message = app.startup_status_message
        app.append_log("startup check")
        await app.refresh_dashboard_state()
        return True

    async def fake_auto_apply_startup():
        startup_started.set()
        app.startup_status_message = "启动中：正在后台应用已选节点"
        app.last_action_message = app.startup_status_message
        app.apply_in_progress = True
        app.apply_owner = "startup"
        app.apply_status_message = app.startup_status_message
        app.append_log("startup auto apply begin")
        await app.refresh_dashboard_state()
        await startup_released.wait()
        app.apply_in_progress = False
        app.apply_owner = None
        app.apply_status_message = None
        app.last_action_message = "启动自动应用完成"
        app.append_log("startup auto apply done")
        await app.refresh_dashboard_state()
        startup_finished.set()
        return True, "启动自动应用完成"

    app._check_singbox_binary_on_startup = fake_check_startup  # type: ignore[method-assign]
    app._auto_apply_selected_node_on_startup = fake_auto_apply_startup  # type: ignore[method-assign]

    pilot_cm = app.run_test()
    pilot = await asyncio.wait_for(pilot_cm.__aenter__(), timeout=1)
    try:
        await pilot.pause()
        await asyncio.wait_for(startup_started.wait(), timeout=1)
        await pilot.pause()

        dashboard = app.query_one("#dashboard", DashboardScreen)
        apply_status = app.query_one("#apply-status", Static)
        footer = app.query_one("#footer-status", Static)

        assert dashboard.display is True
        assert not startup_finished.is_set()
        assert app.startup_in_progress is True
        assert str(apply_status.render()) == "启动中：正在后台应用已选节点"
        assert "状态: 启动中：正在后台应用已选节点" in str(footer.render())

        await pilot.press("8")
        await pilot.pause()

        logs = app.query_one("#logs-content", Log)
        assert any("startup check" in line for line in logs.lines)
        assert any("startup auto apply begin" in line for line in logs.lines)

        startup_released.set()
        await asyncio.wait_for(startup_finished.wait(), timeout=1)
        await pilot.press("1")
        await pilot.pause()

        assert app.startup_in_progress is False
        assert str(app.query_one("#apply-status", Static).render()) == "启动自动应用完成"
    finally:
        await pilot_cm.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_startup_auto_apply_excludes_manual_apply_action(tmp_path):
    app = await create_initialized_app(tmp_path)
    startup_apply_started = asyncio.Event()
    startup_apply_released = asyncio.Event()
    apply_calls: list[str] = []

    async def fake_check_startup():
        return True

    async def fake_apply_runtime_config():
        apply_calls.append("apply")
        if len(apply_calls) == 1:
            startup_apply_started.set()
            await startup_apply_released.wait()
        return True, "配置已应用并重启 sing-box"

    async def fake_auto_apply_startup():
        return await app.request_apply(reason="startup")

    app._check_singbox_binary_on_startup = fake_check_startup  # type: ignore[method-assign]
    app._auto_apply_selected_node_on_startup = fake_auto_apply_startup  # type: ignore[method-assign]
    app.apply_runtime_config = fake_apply_runtime_config  # type: ignore[method-assign]

    pilot_cm = app.run_test()
    pilot = await asyncio.wait_for(pilot_cm.__aenter__(), timeout=1)
    try:
        await pilot.pause()
        await asyncio.wait_for(startup_apply_started.wait(), timeout=1)
        await pilot.pause()

        apply_button = app.query_one("#apply-config", Button)
        apply_status = app.query_one("#apply-status", Static)
        assert apply_button.disabled is True
        assert str(apply_status.render()) == "启动中：正在后台应用已选节点"

        await pilot.press("a")
        await pilot.pause()

        assert apply_calls == ["apply"]
        assert app.last_action_message == "已有应用任务进行中（来源: 启动自动应用）"
        assert str(app.query_one("#apply-status", Static).render()) == "启动中：正在后台应用已选节点"

        startup_apply_released.set()
        await pilot.pause()
        await pilot.pause()

        assert apply_calls == ["apply"]
        assert app.apply_in_progress is False
    finally:
        await pilot_cm.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_auto_apply_selected_node_on_startup_runs_when_selected_node_exists(tmp_path):
    app = await create_initialized_app(tmp_path)
    await app.subscriptions_repo.upsert_and_replace_nodes(
        name="校园订阅",
        url="https://example.com/sub",
        nodes=[
            {
                "tag": "节点 A",
                "protocol": "vless",
                "config": {"tag": "node-a", "server": "example.com", "server_port": 443},
            }
        ],
    )
    node = (await app.nodes_repo.list_nodes())[0]
    await app.preferences_repo.set_selected_node(node.id)

    calls: list[str] = []

    async def fake_request_apply_runtime_config(*, source: str = "user"):
        calls.append(source)
        return True, "配置已应用并重启 sing-box"

    app.request_apply_runtime_config = fake_request_apply_runtime_config  # type: ignore[method-assign]

    result = await app._auto_apply_selected_node_on_startup()

    assert result == (True, "配置已应用并重启 sing-box")
    assert calls == ["startup"]


@pytest.mark.asyncio
async def test_auto_apply_selected_node_on_startup_skips_when_no_selected_node(tmp_path):
    app = await create_initialized_app(tmp_path)

    calls: list[str] = []

    async def fake_request_apply_runtime_config(*, source: str = "user"):
        calls.append(source)
        return True, "配置已应用并重启 sing-box"

    app.request_apply_runtime_config = fake_request_apply_runtime_config  # type: ignore[method-assign]

    result = await app._auto_apply_selected_node_on_startup()

    assert result is None
    assert calls == []


@pytest.mark.asyncio
async def test_settings_screen_saves_rule_set_url_proxy_prefix(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()

        rule_set_url_proxy_prefix = app.query_one("#rule-set-url-proxy-prefix", Input)
        rule_set_url_proxy_prefix.value = "https://ghfast.top"
        await pilot.click("#save-settings")
        await pilot.pause()

        saved_preferences = await app.preferences_repo.get_preferences()
        assert saved_preferences.rule_set_url_proxy_prefix == "https://ghfast.top/"
        assert rule_set_url_proxy_prefix.value == "https://ghfast.top/"


@pytest.mark.asyncio
async def test_settings_screen_defaults_to_global_and_rules_screen_can_create_rule_set_rule(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()

        route_mode = app.query_one("#route-mode")
        active_rule_set = app.query_one("#active-rule-set")
        rule_set_url_proxy_prefix = app.query_one("#rule-set-url-proxy-prefix", Input)
        assert route_mode.value == "global"
        assert active_rule_set.disabled is True
        assert rule_set_url_proxy_prefix.value == ""

        await pilot.press("5")
        await pilot.pause()

        rule_sets = app.query_one("#rule-sets-list", OptionList)
        assert len(rule_sets.options) >= 2
        assert any("国内直连" in option.prompt for option in rule_sets.options)
        assert any("全局代理" in option.prompt for option in rule_sets.options)

        new_rule_set_name = app.query_one("#new-rule-set-name", Input)
        new_rule_set_name.value = "办公规则"
        create_rule_set_button = app.query_one("#create-rule-set", Button)
        await app.query_one("#rules").on_button_pressed(Button.Pressed(create_rule_set_button))
        await pilot.pause()

        match_type = app.query_one("#rule-match-type")
        match_type.value = "rule_set"
        match_value = app.query_one("#rule-match-value", Input)
        match_value.value = "geosite-cn"
        action = app.query_one("#rule-action")
        action.value = "direct"
        create_rule_button = app.query_one("#create-rule", Button)
        await app.query_one("#rules").on_button_pressed(Button.Pressed(create_rule_button))
        await pilot.pause()

        rules = app.query_one("#rules-list", OptionList)
        assert any("geosite-cn" in option.prompt for option in rules.options)

        rule_files = app.query_one("#rule-files-list", OptionList)
        assert any("geosite-cn" in option.prompt for option in rule_files.options)


@pytest.mark.asyncio
async def test_rules_screen_shows_remote_rule_set_as_reference_catalog(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()

        rule_files = app.query_one("#rule-files-list", OptionList)
        assert any("geosite-cn [可引用/内置]" in option.prompt for option in rule_files.options)
        assert list(app.query("#enable-rule-file").results()) == []
        assert list(app.query("#disable-rule-file").results()) == []


@pytest.mark.asyncio
async def test_warp_screen_shows_empty_state_and_removes_save_button(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()

        account = app.query_one("#warp-account", Static)
        assert str(account.render()) == "暂无 WARP 账户，请先生成"
        assert list(app.query("#save-warp").results()) == []


@pytest.mark.asyncio
async def test_warp_screen_shows_existing_account_details(tmp_path):
    app = await create_initialized_app(tmp_path)
    await app.warp_repo.upsert_account(
        private_key="private-key",
        local_address_v4="172.16.0.2/32",
        local_address_v6="2606:4700:110::2/128",
        reserved="[7, 8, 9]",
    )

    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()

        account = app.query_one("#warp-account", Static)
        rendered = str(account.render())
        assert "IPv4: 172.16.0.2/32" in rendered
        assert "IPv6: 2606:4700:110::2/128" in rendered
        assert "Reserved: [7, 8, 9]" in rendered
        assert "private-key" not in rendered


@pytest.mark.asyncio
async def test_warp_switch_auto_saves_and_warns_without_account(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()

        switch = app.query_one("#warp-enabled", Switch)
        switch.toggle()
        await pilot.pause()

        preferences = await app.preferences_repo.get_preferences()
        status = app.query_one("#warp-status", Static)
        rendered = str(status.render())
        assert preferences.warp_enabled is True
        assert "WARP 已开启并自动保存" in rendered
        assert "请先生成账户后再应用配置" in rendered
        assert app.last_action_message == rendered


@pytest.mark.asyncio
async def test_warp_refresh_does_not_trigger_auto_save(tmp_path):
    app = await create_initialized_app(tmp_path)

    calls: list[bool] = []
    original = app.preferences_repo.update_preferences

    async def tracked_update_preferences(**kwargs):
        calls.append(True)
        await original(**kwargs)

    app.preferences_repo.update_preferences = tracked_update_preferences  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

        assert calls == []


@pytest.mark.asyncio
async def test_generate_warp_refreshes_account_panel(monkeypatch, tmp_path):
    app = await create_initialized_app(tmp_path)

    async def fake_generate_and_store():
        return await app.warp_repo.upsert_account(
            private_key="private-key",
            local_address_v4=GeneratedWarpAccount.local_address_v4,
            local_address_v6=GeneratedWarpAccount.local_address_v6,
            reserved=GeneratedWarpAccount.reserved,
        )

    monkeypatch.setattr(app.warp_generator, "generate_and_store", fake_generate_and_store)

    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()
        await pilot.click("#gen-warp")
        await pilot.pause()
        await pilot.pause()

        account = app.query_one("#warp-account", Static)
        status = app.query_one("#warp-status", Static)
        rendered = str(account.render())
        assert GeneratedWarpAccount.local_address_v4 in rendered
        assert GeneratedWarpAccount.local_address_v6 in rendered
        assert GeneratedWarpAccount.reserved in rendered
        assert str(status.render()) == f"WARP 账户已生成: {GeneratedWarpAccount.local_address_v4}"
