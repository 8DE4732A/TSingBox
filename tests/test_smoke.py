import pytest
from textual.widgets import Button, Input, Log, OptionList, Static, Tabs

from tsingbox.ui.screens.warp import WarpScreen

from tsingbox.core.settings import Settings
from tsingbox.data.db import Database
from tsingbox.services.subscription_manager import SubscriptionParseError
from tsingbox.ui.screens.subscriptions import SubscriptionsScreen
from conftest import create_initialized_app


@pytest.mark.asyncio
async def test_initialize_database(tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.ensure_dirs()

    db = Database(settings)
    await db.initialize()

    assert settings.db_path.exists()
    assert settings.runtime_dir.exists()
    assert settings.logs_dir.exists()


@pytest.mark.asyncio
async def test_tabs_default_to_dashboard(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        tabs = app.query_one("#tabs", Tabs)
        assert app.current_screen_name == "dashboard"
        assert tabs.active == "tab-dashboard"


@pytest.mark.asyncio
async def test_click_tab_switches_screen(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.click("#tab-subscriptions")
        await pilot.pause()

        tabs = app.query_one("#tabs", Tabs)
        assert app.current_screen_name == "subscriptions"
        assert tabs.active == "tab-subscriptions"


@pytest.mark.asyncio
async def test_tabs_order_places_config_before_logs(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        tabs = app.query_one("#tabs", Tabs)
        assert [tab.label.plain for tab in tabs.query("Tab").results()] == [
            "总览",
            "订阅",
            "节点",
            "设置",
            "WARP",
            "配置",
            "日志",
        ]


@pytest.mark.asyncio
async def test_number_key_switches_screen_and_tab(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()

        tabs = app.query_one("#tabs", Tabs)
        assert app.current_screen_name == "config"
        assert tabs.active == "tab-config"

        await pilot.press("7")
        await pilot.pause()

        assert app.current_screen_name == "logs"
        assert tabs.active == "tab-logs"

        await pilot.press("escape")
        await pilot.pause()

        assert app.current_screen_name == "dashboard"
        assert tabs.active == "tab-dashboard"


@pytest.mark.asyncio
async def test_subscriptions_screen_defaults_to_list_view(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.click("#tab-subscriptions")
        await pilot.pause()

        screen = app.query_one("#subscriptions", SubscriptionsScreen)
        add_button = app.query_one("#show-add-sub", Button)
        refresh_button = app.query_one("#refresh-subs", Button)
        form = screen.query_one("#add-sub-form")
        option_list = app.query_one("#subscriptions-list", OptionList)
        status = app.query_one("#sub-status", Static)

        assert add_button.display is True
        assert refresh_button.display is True
        assert form.display is False
        assert option_list.highlighted is None
        assert str(status.render()) == "暂无订阅，请点击增加订阅"


@pytest.mark.asyncio
async def test_subscriptions_screen_shows_form_after_click(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.click("#tab-subscriptions")
        await pilot.pause()
        await pilot.click("#show-add-sub")
        await pilot.pause()

        screen = app.query_one("#subscriptions", SubscriptionsScreen)
        form = screen.query_one("#add-sub-form")

        assert form.display is True


@pytest.mark.asyncio
async def test_subscriptions_success_refreshes_list_and_hides_form(monkeypatch, tmp_path):
    app = await create_initialized_app(tmp_path)

    async def fake_refresh_subscription(*, name: str, url: str) -> int:
        await app.subscriptions_repo.upsert_and_replace_nodes(
            name=name,
            url=url,
            nodes=[
                {
                    "tag": "node-1",
                    "protocol": "vless",
                    "config": {"tag": "node-1", "type": "vless"},
                }
            ],
        )
        return 1

    monkeypatch.setattr(app.subscription_manager, "refresh_subscription", fake_refresh_subscription)

    async with app.run_test() as pilot:
        await pilot.click("#tab-subscriptions")
        await pilot.pause()
        await pilot.click("#show-add-sub")
        await pilot.pause()

        app.query_one("#sub-name", Input).value = "Demo"
        app.query_one("#sub-url", Input).value = "https://example.com/sub"
        await pilot.click("#fetch-sub")
        await pilot.pause()
        await pilot.pause()

        screen = app.query_one("#subscriptions", SubscriptionsScreen)
        form = screen.query_one("#add-sub-form")
        option_list = app.query_one("#subscriptions-list", OptionList)
        status = app.query_one("#sub-status", Static)
        name_input = app.query_one("#sub-name", Input)
        url_input = app.query_one("#sub-url", Input)
        option = option_list.get_option_at_index(0)

        assert form.display is False
        assert option_list.highlighted == 0
        assert "Demo" in option.prompt
        assert str(status.render()) == "拉取完成，节点数: 1"
        assert name_input.value == ""
        assert url_input.value == ""


@pytest.mark.asyncio
async def test_subscriptions_failure_keeps_form_visible(monkeypatch, tmp_path):
    app = await create_initialized_app(tmp_path)

    async def fake_refresh_subscription(*, name: str, url: str) -> int:
        raise SubscriptionParseError("解析后无有效节点")

    monkeypatch.setattr(app.subscription_manager, "refresh_subscription", fake_refresh_subscription)

    async with app.run_test() as pilot:
        await pilot.click("#tab-subscriptions")
        await pilot.pause()
        await pilot.click("#show-add-sub")
        await pilot.pause()

        app.query_one("#sub-name", Input).value = "Bad"
        app.query_one("#sub-url", Input).value = "https://example.com/bad"
        await pilot.click("#fetch-sub")
        await pilot.pause()
        await pilot.pause()

        screen = app.query_one("#subscriptions", SubscriptionsScreen)
        form = screen.query_one("#add-sub-form")
        status = app.query_one("#sub-status", Static)

        assert form.display is True
        assert str(status.render()) == "拉取失败（解析）: 解析后无有效节点"


@pytest.mark.asyncio
async def test_refresh_subscriptions_button_updates_all(monkeypatch, tmp_path):
    app = await create_initialized_app(tmp_path)
    await app.subscriptions_repo.upsert_and_replace_nodes(
        name="Sub A",
        url="https://example.com/a",
        nodes=[{"tag": "old-a", "protocol": "vless", "config": {"tag": "old-a", "type": "vless"}}],
    )
    await app.subscriptions_repo.upsert_and_replace_nodes(
        name="Sub B",
        url="https://example.com/b",
        nodes=[{"tag": "old-b", "protocol": "vless", "config": {"tag": "old-b", "type": "vless"}}],
    )

    calls: list[tuple[str, str]] = []

    async def fake_refresh_subscription(*, name: str, url: str) -> int:
        calls.append((name, url))
        await app.subscriptions_repo.upsert_and_replace_nodes(
            name=name,
            url=url,
            nodes=[{"tag": f"{name}-node", "protocol": "vless", "config": {"tag": f"{name}-node", "type": "vless"}}],
        )
        return 1

    monkeypatch.setattr(app.subscription_manager, "refresh_subscription", fake_refresh_subscription)

    async with app.run_test() as pilot:
        await pilot.click("#tab-subscriptions")
        await pilot.pause()
        await pilot.click("#refresh-subs")
        await pilot.pause()
        await pilot.pause()

        option_list = app.query_one("#subscriptions-list", OptionList)
        status = app.query_one("#sub-status", Static)

        assert calls == [("Sub B", "https://example.com/b"), ("Sub A", "https://example.com/a")]
        assert option_list.highlighted == 0
        assert str(status.render()) == "已刷新 2 个订阅，节点总数: 2"


@pytest.mark.asyncio
async def test_warp_screen_structure_uses_account_panel_and_no_save_button(tmp_path):
    app = await create_initialized_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()

        screen = app.query_one("#warp", WarpScreen)
        assert list(screen.query("#warp-account").results())
        assert list(screen.query("#gen-warp").results())
        assert list(screen.query("#save-warp").results()) == []
