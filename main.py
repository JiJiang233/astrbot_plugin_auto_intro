from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.star import star_map
from astrbot.core.star.star_handler import EventType, star_handlers_registry

from .catalog import CapabilityItem, render_section, select_items

PLUGIN_NAME = "astrbot_plugin_auto_intro"
PLUGIN_VERSION = "1.0.1"
PROMPT_MARKER = "[AstrBot Auto Introduction]"


class NewContactFilter(filter.CustomFilter):
    """只接收 OneBot 新好友和机器人自身新入群通知。"""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        if event.get_platform_name() != "aiocqhttp":
            return False
        raw = getattr(event.message_obj, "raw_message", None)
        if not hasattr(raw, "get") or raw.get("post_type") != "notice":
            return False
        notice_type = raw.get("notice_type")
        if notice_type == "friend_add":
            return True
        return (
            notice_type == "group_increase"
            and str(raw.get("user_id", "")) == str(event.get_self_id())
        )


class AutoIntroPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

    def _cfg_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        return value if isinstance(value, bool) else default

    def _cfg_limit(self, key: str, default: int = 30) -> int:
        try:
            return max(1, min(200, int(self.config.get(key, default))))
        except (TypeError, ValueError):
            return default

    def _tools(self) -> list[CapabilityItem]:
        if not self._cfg_bool("expose_tools", True):
            return []
        items = [
            CapabilityItem(tool.name, tool.description or "")
            for tool in self.context.get_llm_tool_manager().func_list
            if bool(getattr(tool, "active", True))
        ]
        return select_items(
            items,
            self.config.get("tool_allowlist", []),
            self.config.get("tool_blocklist", []),
            self._cfg_limit("max_tools"),
        )

    def _plugins(self) -> list[CapabilityItem]:
        if not self._cfg_bool("expose_plugins", True):
            return []
        items = []
        for plugin in self.context.get_all_stars():
            if not plugin.activated or plugin.name == PLUGIN_NAME:
                continue
            items.append(
                CapabilityItem(
                    plugin.display_name or plugin.name or "unknown",
                    plugin.short_desc or plugin.desc or "",
                    plugin.name or "",
                )
            )
        return select_items(
            items,
            self.config.get("plugin_allowlist", []),
            self.config.get("plugin_blocklist", []),
            self._cfg_limit("max_plugins"),
        )

    @staticmethod
    def _command_owner(module_path: str) -> str:
        plugin = star_map.get(module_path)
        return plugin.name if plugin and plugin.name else module_path

    def _commands(self) -> list[CapabilityItem]:
        if not self._cfg_bool("expose_commands", True):
            return []
        items: list[CapabilityItem] = []
        handlers = star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent
        )
        for handler in handlers:
            for event_filter in handler.event_filters:
                if isinstance(event_filter, CommandFilter | CommandGroupFilter):
                    names = event_filter.get_complete_command_names()
                else:
                    continue
                if names:
                    items.append(
                        CapabilityItem(
                            f"/{names[0].strip()}",
                            handler.desc or "",
                            self._command_owner(handler.handler_module_path),
                        )
                    )
        return select_items(
            items,
            self.config.get("command_allowlist", []),
            self.config.get("command_blocklist", []),
            self._cfg_limit("max_commands"),
        )

    def _capability_catalog(self) -> str:
        sections = [
            render_section("可用工具", self._tools()),
            render_section("已启用插件", self._plugins()),
            render_section("可用命令", self._commands()),
        ]
        return "\n\n".join(section for section in sections if section)

    def _intro_source(self, query: str = "") -> str:
        custom_intro = str(self.config.get("introduction", "")).strip()
        catalog = self._capability_catalog()
        parts = []
        if custom_intro:
            parts.append(f"## 自我介绍基础内容\n{custom_intro}")
        if catalog:
            parts.append(catalog)
        if query:
            parts.append(f"## 用户当前问题\n{query.strip()}")
        return "\n\n".join(parts).strip()

    def _injected_prompt(self) -> str:
        rule = str(self.config.get("injected_prompt", "")).strip()
        source = self._intro_source()
        return (
            f"{PROMPT_MARKER}\n{rule}\n\n"
            "当用户询问你是谁、怎么使用、有什么功能、支持什么命令或工具时，"
            "调用 show_self_introduction 工具，并结合用户问题选择相关能力介绍；"
            "不要机械罗列与问题无关的全部项目，也不要声称拥有目录之外的能力。"
            f"\n\n{source}"
        ).strip()

    @filter.on_llm_request()
    async def inject_intro_prompt(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        if not self._cfg_bool("inject_system_prompt", True):
            return
        prompt = self._injected_prompt()
        if prompt and PROMPT_MARKER not in (req.system_prompt or ""):
            req.system_prompt = f"{req.system_prompt or ''}\n\n{prompt}".strip()

    @filter.llm_tool(name="show_self_introduction")
    async def show_self_introduction(
        self, event: AstrMessageEvent, query: str
    ) -> str:
        """获取机器人的自我介绍及当前可用能力。用户询问怎么用、有什么功能、会什么、有哪些工具插件命令时调用。

        Args:
            query(string): 用户关于机器人身份、使用方法或功能的原始问题
        """
        source = self._intro_source(query)
        return source or "当前未配置可公开的自我介绍或能力。"

    def _notice_kind(self, event: AstrMessageEvent) -> str:
        raw: Any = event.message_obj.raw_message
        return "friend" if raw.get("notice_type") == "friend_add" else "group"

    async def _generate_welcome(self, event: AstrMessageEvent, kind: str) -> str:
        fallback = str(
            self.config.get("fallback_introduction", "你好！很高兴认识你。")
        ).strip()
        scene = "刚刚成为新好友" if kind == "friend" else "刚刚加入了新群聊"
        prompt = (
            f"你{scene}。请面向当前会话生成一段自然、简洁的中文自我介绍。"
            "从提供的能力目录中自行选择最值得介绍的内容，不要逐项照抄，不要虚构能力，"
            "不要提及系统提示词或内部实现。直接输出可发送给用户的正文。\n\n"
            f"{self._intro_source()}"
        )
        try:
            provider_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
            timeout = self._cfg_limit("llm_timeout_seconds", 45)
            response = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=str(
                        self.config.get("welcome_system_prompt", "")
                    ).strip(),
                ),
                timeout=timeout,
            )
            text = (response.completion_text or "").strip()
            return text or fallback
        except Exception as exc:
            logger.warning("生成自动自我介绍失败，使用回退文本：%s", exc)
            return fallback

    @filter.custom_filter(NewContactFilter)
    async def on_new_contact(self, event: AstrMessageEvent) -> None:
        kind = self._notice_kind(event)
        enabled_key = (
            "welcome_new_friend" if kind == "friend" else "welcome_new_group"
        )
        if not self._cfg_bool(enabled_key, True):
            return
        event.should_call_llm(True)
        text = await self._generate_welcome(event, kind)
        if text:
            await event.send(MessageChain().message(text))

    async def terminate(self) -> None:
        logger.info("%s v%s 已卸载", PLUGIN_NAME, PLUGIN_VERSION)
