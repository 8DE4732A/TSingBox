from __future__ import annotations

import ipaddress
import re
import sqlite3

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, OptionList, Select, Static
from textual.widgets.option_list import Option


class RulesScreen(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rule_sets = []
        self._rules = []
        self._rule_files = []
        self._selected_rule_set_id: int | None = None
        self._selected_rule_id: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("规则集", classes="screen-title")
            with Horizontal():
                yield Button("新增规则集", id="create-rule-set")
                yield Button("删除规则集", id="delete-rule-set")
            yield Input(placeholder="新规则集名称", id="new-rule-set-name")
            yield OptionList(id="rule-sets-list")

            yield Static("规则项", classes="screen-title")
            yield OptionList(id="rules-list")
            yield Select(
                options=[
                    ("域名后缀", "domain_suffix"),
                    ("域名关键字", "domain_keyword"),
                    ("IP/CIDR", "ip_cidr"),
                    ("远程 rule_set", "rule_set"),
                ],
                id="rule-match-type",
                prompt="匹配类型",
            )
            yield Input(placeholder="匹配值，如 example.com / 1.1.1.1 / geosite-cn", id="rule-match-value")
            yield Select(options=[("直连", "direct"), ("代理", "proxy")], id="rule-action", prompt="动作")
            with Horizontal():
                yield Button("新增规则", id="create-rule")
                yield Button("删除规则", id="delete-rule")

            yield Static("远程 rule_set", classes="screen-title")
            yield OptionList(id="rule-files-list")
            yield Static("仅当规则引用对应 tag 时，才会自动纳入最终配置。", classes="help-text")
            yield Static("", id="rules-status")

    async def on_mount(self) -> None:
        await self.refresh_screen()

    async def refresh_screen(self) -> None:
        try:
            pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
            self._rule_sets = await self.app.routing_rule_sets_repo.list_rule_sets()  # type: ignore[attr-defined]
            self._rule_files = await self.app.rule_file_service.list_rule_files_with_status()  # type: ignore[attr-defined]
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            self._rule_sets = []
            self._rules = []
            self._rule_files = []
            self._selected_rule_set_id = None
            self._selected_rule_id = None
            self._render_rule_sets_list(None)
            self._render_rules_list()
            self._render_rule_files_list()
            self._update_controls()
            self.query_one("#rules-status", Static).update("初始化中...")
            return

        active_rule_set_id = self._selected_rule_set_id or pref.active_routing_rule_set_id
        if active_rule_set_id is None:
            fallback = await self.app.routing_rule_sets_repo.get_fallback_rule_set()  # type: ignore[attr-defined]
            active_rule_set_id = fallback.id if fallback is not None else None
        self._selected_rule_set_id = active_rule_set_id

        self._render_rule_sets_list(active_rule_set_id)
        await self._reload_rules()
        self._render_rule_files_list()
        self._update_controls()

    def _render_rule_sets_list(self, active_rule_set_id: int | None) -> None:
        option_list = self.query_one("#rule-sets-list", OptionList)
        option_list.clear_options()
        highlighted = 0
        for index, rule_set in enumerate(self._rule_sets):
            current_marker = "（当前使用）" if rule_set.id == active_rule_set_id else ""
            builtin_marker = "（内置）" if rule_set.is_builtin else ""
            option_list.add_option(Option(f"{rule_set.name}{builtin_marker}{current_marker}", id=str(rule_set.id)))
            if rule_set.id == self._selected_rule_set_id:
                highlighted = index
        option_list.highlighted = highlighted if self._rule_sets else None

    async def _reload_rules(self) -> None:
        if self._selected_rule_set_id is None:
            self._rules = []
            self._selected_rule_id = None
            self._render_rules_list()
            return
        self._rules = await self.app.routing_rules_repo.list_rules(self._selected_rule_set_id)  # type: ignore[attr-defined]
        self._selected_rule_id = self._rules[0].id if self._rules else None
        self._render_rules_list()

    def _render_rules_list(self) -> None:
        option_list = self.query_one("#rules-list", OptionList)
        option_list.clear_options()
        for index, rule in enumerate(self._rules, start=1):
            option_list.add_option(Option(f"{index}. {rule.match_type}: {rule.match_value} -> {rule.action}", id=str(rule.id)))
        option_list.highlighted = 0 if self._rules else None

    def _render_rule_files_list(self) -> None:
        option_list = self.query_one("#rule-files-list", OptionList)
        option_list.clear_options()
        for item in self._rule_files:
            url_text = item.rule_file.url.replace("https://", "")
            label = (
                f"{item.rule_file.tag} [{item.status_text}/{item.source_text}] "
                f"{item.rule_file.name} - {url_text}"
            )
            option_list.add_option(Option(label, id=str(item.rule_file.id)))
        option_list.highlighted = 0 if self._rule_files else None

    def _current_rule_set(self):
        for rule_set in self._rule_sets:
            if rule_set.id == self._selected_rule_set_id:
                return rule_set
        return None

    def _update_controls(self) -> None:
        current = self._current_rule_set()
        has_rule_set = current is not None
        is_builtin = bool(current and current.is_builtin)
        has_rules = bool(self._rules)
        self.query_one("#delete-rule-set", Button).disabled = not has_rule_set or is_builtin
        self.query_one("#create-rule", Button).disabled = not has_rule_set or is_builtin
        self.query_one("#delete-rule", Button).disabled = not has_rule_set or is_builtin or not has_rules
        self.query_one("#rule-match-type", Select).disabled = not has_rule_set or is_builtin
        self.query_one("#rule-match-value", Input).disabled = not has_rule_set or is_builtin
        self.query_one("#rule-action", Select).disabled = not has_rule_set or is_builtin

    def _set_status(self, message: str) -> None:
        self.query_one("#rules-status", Static).update(message)
        self.app.last_action_message = message  # type: ignore[attr-defined]
        self.app.append_log(message)  # type: ignore[attr-defined]

    def _normalize_rule_value(self, match_type: str, raw_value: str) -> str:
        value = raw_value.strip()
        if not value:
            raise ValueError("规则值不能为空")
        if match_type == "domain_suffix":
            return value.lstrip(".")
        if match_type == "domain_keyword":
            return value
        if match_type == "ip_cidr":
            if "/" in value:
                ipaddress.ip_network(value, strict=False)
                return value
            ip = ipaddress.ip_address(value)
            return f"{value}/32" if ip.version == 4 else f"{value}/128"
        if match_type == "rule_set":
            normalized = value.lower()
            if not re.fullmatch(r"[a-z0-9._-]+", normalized):
                raise ValueError("rule_set tag 仅支持小写字母、数字、点、下划线和中划线")
            return normalized
        raise ValueError("不支持的规则类型")

    async def _create_rule_set(self) -> None:
        name = self.query_one("#new-rule-set-name", Input).value.strip()
        if not name:
            self._set_status("请先输入规则集名称")
            return
        try:
            created = await self.app.routing_rule_sets_repo.create_rule_set(name)  # type: ignore[attr-defined]
        except sqlite3.IntegrityError:
            self._set_status("规则集名称已存在")
            return
        self.query_one("#new-rule-set-name", Input).value = ""
        self._selected_rule_set_id = created.id
        await self.refresh_screen()
        self._set_status(f"已创建规则集: {created.name}")

    async def _delete_rule_set(self) -> None:
        current = self._current_rule_set()
        if current is None:
            self._set_status("请先选择规则集")
            return
        if current.is_builtin:
            self._set_status("内置规则集不允许删除")
            return
        deleted = await self.app.routing_rule_sets_repo.delete_rule_set(current.id)  # type: ignore[attr-defined]
        if not deleted:
            self._set_status("删除规则集失败")
            return
        pref = await self.app.preferences_repo.get_preferences()  # type: ignore[attr-defined]
        if pref.active_routing_rule_set_id == current.id:
            fallback = await self.app.routing_rule_sets_repo.get_fallback_rule_set()  # type: ignore[attr-defined]
            fallback_id = fallback.id if fallback is not None and fallback.id != current.id else None
            await self.app.preferences_repo.update_preferences(active_routing_rule_set_id=fallback_id)  # type: ignore[attr-defined]
        self._selected_rule_set_id = None
        await self.refresh_screen()
        await self.app.refresh_dashboard_state()  # type: ignore[attr-defined]
        self._set_status("规则集已删除")

    async def _create_rule(self) -> None:
        current = self._current_rule_set()
        if current is None:
            self._set_status("请先选择规则集")
            return
        if current.is_builtin:
            self._set_status("内置规则集不允许修改")
            return
        match_type = str(self.query_one("#rule-match-type", Select).value)
        action = str(self.query_one("#rule-action", Select).value)
        raw_value = self.query_one("#rule-match-value", Input).value
        if match_type == str(Select.BLANK) or action == str(Select.BLANK):
            self._set_status("请先选择规则类型和动作")
            return
        try:
            match_value = self._normalize_rule_value(match_type, raw_value)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        if match_type == "rule_set":
            try:
                await self.app.rule_file_service.ensure_rule_file(match_value)  # type: ignore[attr-defined]
            except ValueError as exc:
                self._set_status(str(exc))
                return
        await self.app.routing_rules_repo.create_rule(  # type: ignore[attr-defined]
            current.id,
            match_type=match_type,
            match_value=match_value,
            action=action,
        )
        self.query_one("#rule-match-value", Input).value = ""
        await self._reload_rules()
        self._update_controls()
        self._set_status("规则已新增")

    async def _delete_rule(self) -> None:
        current = self._current_rule_set()
        if current is None:
            self._set_status("请先选择规则集")
            return
        if current.is_builtin:
            self._set_status("内置规则集不允许修改")
            return
        highlighted = self.query_one("#rules-list", OptionList).highlighted
        if highlighted is None or highlighted < 0 or highlighted >= len(self._rules):
            self._set_status("请先选择规则")
            return
        selected_rule_id = self._rules[highlighted].id
        deleted = await self.app.routing_rules_repo.delete_rule(selected_rule_id)  # type: ignore[attr-defined]
        if not deleted:
            self._set_status("删除规则失败")
            return
        await self._reload_rules()
        self._update_controls()
        self._set_status("规则已删除")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "create-rule-set":
            await self._create_rule_set()
        elif button_id == "delete-rule-set":
            await self._delete_rule_set()
        elif button_id == "create-rule":
            await self._create_rule()
        elif button_id == "delete-rule":
            await self._delete_rule()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "rule-sets-list":
            highlighted = event.option_list.highlighted
            if highlighted is None or highlighted < 0 or highlighted >= len(self._rule_sets):
                return
            self._selected_rule_set_id = self._rule_sets[highlighted].id
            self._render_rule_sets_list(self._selected_rule_set_id)
            await self._reload_rules()
            self._update_controls()
        elif event.option_list.id == "rules-list":
            highlighted = event.option_list.highlighted
            if highlighted is None or highlighted < 0 or highlighted >= len(self._rules):
                self._selected_rule_id = None
                return
            self._selected_rule_id = self._rules[highlighted].id

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "new-rule-set-name":
            await self._create_rule_set()
        elif event.input.id == "rule-match-value":
            await self._create_rule()
