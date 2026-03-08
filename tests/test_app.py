from __future__ import annotations

from pathlib import Path
import re

import pytest

from tsingbox.app import TSingBoxApp
from tsingbox.core.settings import Settings
from tsingbox.ui.screens.config import ConfigScreen
from tsingbox.services.singbox_binary_service import SingboxBinaryCheckResult, SingboxBinaryStatus
from tsingbox.services.singbox_controller import ControlResult
from conftest import create_initialized_app
from textual.widgets import Log, Static, Switch


class DummyConfig:
    def model_dump_json(self, **kwargs) -> str:
        return '{"outbounds": []}'


class FailingBuilder:
    async def build_config(self):
        raise ValueError("尚未选择节点")


class SuccessBuilder:
    async def build_config(self):
        return DummyConfig()


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
    assert state.node_count == 0
    assert state.singbox_status == "stopped"
    assert state.routing_mode == "rule"
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

    state = await app.get_dashboard_state()

    assert nodes[0].sub_id == sub_id
    assert state.subscription_name == "校园订阅"
    assert state.subscription_updated_at != "未更新"
    assert state.node_name == "节点 A"
    assert state.node_protocol == "vless"
    assert state.node_port == "443"
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
    assert state.node_port == "未提供"
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
    await app.database.initialize()

    ok, msg = await app.apply_runtime_config()

    assert ok
    assert controller.binary == "/custom/bin/sing-box"
    assert controller.restart_calls == [app.settings.runtime_config_path]
    assert msg == "配置已应用并重启 sing-box"


@pytest.mark.asyncio
async def test_startup_check_sets_message_when_system_binary_missing(tmp_path):
    app = await create_initialized_app(tmp_path)

    app.singbox_binary_service.resolve_binary = lambda preferences: SingboxBinaryCheckResult(  # type: ignore[method-assign]
        status=SingboxBinaryStatus.PATH_NOT_FOUND,
        binary_path=None,
        configured_path=None,
    )

    await app._check_singbox_binary_on_startup()

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
        await pilot.press("6")
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
async def test_logs_screen_appends_new_log_line_without_full_refresh(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("7")
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

    app.singbox_binary_service.resolve_binary = lambda preferences: SingboxBinaryCheckResult(  # type: ignore[method-assign]
        status=SingboxBinaryStatus.CONFIGURED_NOT_FOUND,
        binary_path=None,
        configured_path="/missing/sing-box",
    )

    await app._check_singbox_binary_on_startup()

    assert "路径不存在" in app.last_action_message


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

    calls: list[bool] = []

    async def fake_apply_runtime_config():
        calls.append(True)
        return True, "配置已应用并重启 sing-box"

    app.apply_runtime_config = fake_apply_runtime_config  # type: ignore[method-assign]

    await app._auto_apply_selected_node_on_startup()

    assert calls == [True]


@pytest.mark.asyncio
async def test_auto_apply_selected_node_on_startup_skips_when_no_selected_node(tmp_path):
    app = await create_initialized_app(tmp_path)

    calls: list[bool] = []

    async def fake_apply_runtime_config():
        calls.append(True)
        return True, "配置已应用并重启 sing-box"

    app.apply_runtime_config = fake_apply_runtime_config  # type: ignore[method-assign]

    await app._auto_apply_selected_node_on_startup()

    assert calls == []


@pytest.mark.asyncio
async def test_warp_screen_shows_empty_state_and_removes_save_button(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("5")
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
        await pilot.press("5")
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
        await pilot.press("5")
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
        await pilot.press("5")
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
        await pilot.press("5")
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
