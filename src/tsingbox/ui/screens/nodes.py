from __future__ import annotations

from collections import defaultdict

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, OptionList, Static, Tab, Tabs
from textual.widgets.option_list import Option

from tsingbox.data.models import Node, Subscription


class NodesScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active_sub_id: int | None = None
        self._selected_node_id: int | None = None
        self._nodes_by_subscription: dict[int, list[Node]] = {}
        self._subscriptions_by_id: dict[int, Subscription] = {}
        self._current_node_ids: list[int] = []
        self._applying = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Tabs(id="node-sub-tabs")
            yield OptionList(id="nodes-list")
            yield Button("刷新节点", id="refresh-nodes")
            yield Static("", id="nodes-status")

    async def on_mount(self) -> None:
        await self.reload_nodes()

    def on_show(self) -> None:
        self._focus_nodes_list()

    async def refresh_screen(self) -> None:
        await self.reload_nodes()
        self._focus_nodes_list()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-nodes":
            await self.reload_nodes()

    async def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tabs.id != "node-sub-tabs":
            return
        tab_id = getattr(event.tab, "id", "") or ""
        if not tab_id.startswith("node-sub-"):
            return
        sub_id = self._sub_id_from_tab_id(tab_id)
        if sub_id is None or sub_id == self._active_sub_id:
            self._focus_nodes_list()
            return
        self._active_sub_id = sub_id
        self._render_current_subscription_status()
        self._focus_nodes_list()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "nodes-list":
            return
        await self.select_and_apply_current_node()

    async def reload_nodes(self) -> None:
        subscriptions = await self.app.subscriptions_repo.list_subscriptions()  # type: ignore[attr-defined]
        nodes = await self.app.nodes_repo.list_nodes()  # type: ignore[attr-defined]
        preferences = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]

        self._selected_node_id = preferences.selected_node_id
        self._subscriptions_by_id = {subscription.id: subscription for subscription in subscriptions}

        grouped_nodes: dict[int, list[Node]] = defaultdict(list)
        node_by_id: dict[int, Node] = {}
        for node in nodes:
            grouped_nodes[node.sub_id].append(node)
            node_by_id[node.id] = node
        self._nodes_by_subscription = dict(grouped_nodes)

        selected_node = node_by_id.get(self._selected_node_id) if self._selected_node_id is not None else None
        selected_missing = self._selected_node_id is not None and selected_node is None

        await self._update_subscription_tabs(subscriptions)
        self._active_sub_id = self._choose_active_subscription(subscriptions, selected_node)
        self._sync_tabs_active()
        self._render_current_subscription_status(
            selected_missing=selected_missing,
            selected_node=selected_node,
            total_nodes=len(nodes),
        )

    async def select_and_apply_current_node(self) -> None:
        if self._applying:
            return

        node_id = self._get_highlighted_node_id()
        if node_id is None:
            self.query_one("#nodes-status", Static).update("请先选择节点")
            return

        self._selected_node_id = node_id
        self._render_current_subscription_status(status_override="正在应用节点...")
        self.apply_node_worker(node_id)

    @work(exclusive=True)
    async def apply_node_worker(self, node_id: int) -> None:
        self._applying = True
        try:
            await self.app.preferences_repo.set_selected_node(node_id)  # type: ignore[attr-defined]
            self._selected_node_id = node_id
            _, msg = await self.app.apply_runtime_config()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            msg = f"应用失败（节点切换）: {exc}"
        self._applying = False
        self._render_current_subscription_status(status_override=msg)
        self._focus_nodes_list()

    async def _update_subscription_tabs(self, subscriptions: list[Subscription]) -> None:
        tabs = self.query_one("#node-sub-tabs", Tabs)
        await tabs.clear()
        for subscription in subscriptions:
            await tabs.add_tab(Tab(subscription.name, id=self._tab_id(subscription.id)))
        tabs.display = bool(subscriptions)

    def _choose_active_subscription(
        self,
        subscriptions: list[Subscription],
        selected_node: Node | None,
    ) -> int | None:
        if selected_node and selected_node.sub_id in self._subscriptions_by_id:
            return selected_node.sub_id
        if self._active_sub_id in self._subscriptions_by_id:
            return self._active_sub_id
        for subscription in subscriptions:
            if self._nodes_by_subscription.get(subscription.id):
                return subscription.id
        if subscriptions:
            return subscriptions[0].id
        return None

    def _render_current_subscription_status(
        self,
        *,
        selected_missing: bool = False,
        selected_node: Node | None = None,
        total_nodes: int | None = None,
        status_override: str | None = None,
    ) -> None:
        option_list = self.query_one("#nodes-list", OptionList)
        option_list.clear_options()
        self._current_node_ids = []

        if self._active_sub_id is None:
            self.query_one("#nodes-status", Static).update("暂无订阅，请先添加订阅")
            return

        current_nodes = self._nodes_by_subscription.get(self._active_sub_id, [])
        for node in current_nodes:
            option_list.add_option(Option(f"{node.tag} ({node.protocol})", id=str(node.id)))
            self._current_node_ids.append(node.id)

        self._restore_highlight_for_current_subscription(current_nodes)

        if status_override is not None:
            status = status_override
        elif not self._subscriptions_by_id:
            status = "暂无订阅，请先添加订阅"
        elif (total_nodes or 0) == 0:
            status = "暂无节点，请先刷新订阅"
        elif not current_nodes:
            status = "当前订阅暂无节点"
        else:
            subscription = self._subscriptions_by_id.get(self._active_sub_id)
            status = f"当前订阅: {subscription.name if subscription else self._active_sub_id} · 节点数: {len(current_nodes)}"
            if selected_missing:
                status = "上次选择的节点已不存在，已回退到当前可用节点"
            elif selected_node is not None and selected_node.sub_id == self._active_sub_id:
                status = f"当前订阅: {subscription.name if subscription else self._active_sub_id} · 已选节点: {selected_node.tag}"

        self.query_one("#nodes-status", Static).update(status)

    def _restore_highlight_for_current_subscription(self, current_nodes: list[Node]) -> None:
        option_list = self.query_one("#nodes-list", OptionList)
        if not current_nodes:
            option_list.highlighted = None
            return

        highlighted_index = 0
        if self._selected_node_id is not None:
            for index, node in enumerate(current_nodes):
                if node.id == self._selected_node_id:
                    highlighted_index = index
                    break
        option_list.highlighted = highlighted_index

    def _get_highlighted_node_id(self) -> int | None:
        option_list = self.query_one("#nodes-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        if highlighted < 0 or highlighted >= len(self._current_node_ids):
            return None
        return self._current_node_ids[highlighted]

    def _sync_tabs_active(self) -> None:
        tabs = self.query_one("#node-sub-tabs", Tabs)
        if self._active_sub_id is None:
            return
        active_tab_id = self._tab_id(self._active_sub_id)
        if tabs.active != active_tab_id:
            tabs.active = active_tab_id

    def _focus_nodes_list(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#nodes-list", OptionList).focus()

    def _tab_id(self, sub_id: int) -> str:
        return f"node-sub-{sub_id}"

    def _sub_id_from_tab_id(self, tab_id: str) -> int | None:
        try:
            return int(tab_id.removeprefix("node-sub-"))
        except ValueError:
            return None
