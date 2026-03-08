from __future__ import annotations

from textual import work
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from tsingbox.services.subscription_manager import (
    SubscriptionHTTPError,
    SubscriptionNetworkError,
    SubscriptionParseError,
    SubscriptionValidationError,
)


class SubscriptionsScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fetching = False
        self._show_add_form = False

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal():
                yield Button("增加订阅", id="show-add-sub", variant="primary")
                yield Button("刷新订阅", id="refresh-subs")
            yield OptionList(id="subscriptions-list")
            with Vertical(id="add-sub-form"):
                yield Input(placeholder="订阅名称", id="sub-name")
                yield Input(placeholder="订阅 URL", id="sub-url")
                yield Button("添加并拉取订阅", id="fetch-sub")
            yield Static("", id="sub-status")

    async def on_mount(self) -> None:
        self.set_add_form_visible(False)
        await self.reload_subscriptions()

    def on_show(self) -> None:
        self._focus_current_target()

    async def refresh_screen(self) -> None:
        await self.reload_subscriptions()
        self._focus_current_target()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "show-add-sub":
            self.set_add_form_visible(True)
            return
        if event.button.id == "refresh-subs":
            if self._fetching:
                return
            self._fetching = True
            event.button.disabled = True
            self.query_one("#sub-status", Static).update("刷新中...")
            self.refresh_all_subscriptions_worker()
            return
        if event.button.id != "fetch-sub":
            return
        if self._fetching:
            return

        name = self.query_one("#sub-name", Input).value.strip()
        url = self.query_one("#sub-url", Input).value.strip()
        if not name or not url:
            self.query_one("#sub-status", Static).update("参数缺失：请填写名称和 URL")
            self.set_add_form_visible(True)
            return

        self._fetching = True
        event.button.disabled = True
        self.query_one("#sub-status", Static).update("拉取中...")
        self.fetch_subscription_worker(name, url)

    async def reload_subscriptions(self) -> None:
        option_list = self.query_one("#subscriptions-list", OptionList)
        option_list.clear_options()
        subscriptions = await self.app.subscriptions_repo.list_subscriptions()  # type: ignore[attr-defined]
        for subscription in subscriptions:
            option_list.add_option(
                Option(
                    f"{subscription.name} · {self._format_subscription_time(subscription.last_update)}",
                    id=str(subscription.id),
                )
            )
        if subscriptions:
            option_list.highlighted = 0
            if not self._fetching:
                self.query_one("#sub-status", Static).update(f"订阅数: {len(subscriptions)}")
        elif not self._fetching:
            self.query_one("#sub-status", Static).update("暂无订阅，请点击增加订阅")

    def set_add_form_visible(self, visible: bool) -> None:
        self._show_add_form = visible
        form = self.query_one("#add-sub-form", Vertical)
        form.display = visible
        if self.is_mounted:
            self._focus_current_target()

    def _focus_current_target(self) -> None:
        if self._show_add_form:
            self.query_one("#sub-name", Input).focus()
            return
        self.query_one("#show-add-sub", Button).focus()

    def _format_subscription_time(self, updated_at: datetime | None) -> str:
        if updated_at is None:
            return "未更新"
        return updated_at.strftime("%Y-%m-%d %H:%M:%S")

    @work(exclusive=True)
    async def fetch_subscription_worker(self, name: str, url: str) -> None:
        manager = self.app.subscription_manager  # type: ignore[attr-defined]
        success = False
        try:
            inserted = await manager.refresh_subscription(name=name, url=url)
            msg = f"拉取完成，节点数: {inserted}"
            self.app.last_action_message = msg  # type: ignore[attr-defined]
            await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
            await self.reload_subscriptions()
            self.query_one("#sub-name", Input).value = ""
            self.query_one("#sub-url", Input).value = ""
            self.set_add_form_visible(False)
            success = True
        except SubscriptionValidationError as exc:
            msg = str(exc)
        except SubscriptionHTTPError as exc:
            msg = f"拉取失败（HTTP 错误）: {exc.status_code}"
        except SubscriptionNetworkError as exc:
            msg = f"拉取失败（网络）: {exc}"
        except SubscriptionParseError as exc:
            msg = f"拉取失败（解析）: {exc}"
        except Exception as exc:  # noqa: BLE001
            msg = f"拉取失败（未知）: {exc}"

        if not success:
            self.set_add_form_visible(True)
        self.query_one("#sub-status", Static).update(msg)
        self.app.last_action_message = msg  # type: ignore[attr-defined]
        self.app.append_log(msg)  # type: ignore[attr-defined]
        self.query_one("#fetch-sub", Button).disabled = False
        self._fetching = False

    @work(exclusive=True)
    async def refresh_all_subscriptions_worker(self) -> None:
        manager = self.app.subscription_manager  # type: ignore[attr-defined]
        try:
            subscriptions = await self.app.subscriptions_repo.list_subscriptions()  # type: ignore[attr-defined]
            if not subscriptions:
                msg = "暂无订阅可刷新"
            else:
                refreshed = 0
                total_nodes = 0
                for subscription in subscriptions:
                    inserted = await manager.refresh_subscription(name=subscription.name, url=subscription.url)
                    refreshed += 1
                    total_nodes += inserted
                await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
                await self.reload_subscriptions()
                msg = f"已刷新 {refreshed} 个订阅，节点总数: {total_nodes}"
        except SubscriptionValidationError as exc:
            msg = str(exc)
        except SubscriptionHTTPError as exc:
            msg = f"刷新失败（HTTP 错误）: {exc.status_code}"
        except SubscriptionNetworkError as exc:
            msg = f"刷新失败（网络）: {exc}"
        except SubscriptionParseError as exc:
            msg = f"刷新失败（解析）: {exc}"
        except Exception as exc:  # noqa: BLE001
            msg = f"刷新失败（未知）: {exc}"

        self.query_one("#sub-status", Static).update(msg)
        self.app.last_action_message = msg  # type: ignore[attr-defined]
        self.app.append_log(msg)  # type: ignore[attr-defined]
        self.query_one("#refresh-subs", Button).disabled = False
        self._fetching = False
