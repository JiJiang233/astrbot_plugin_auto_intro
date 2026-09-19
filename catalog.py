from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class CapabilityItem:
    name: str
    description: str = ""
    owner: str = ""


def normalize_names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def select_items(
    items: Iterable[CapabilityItem],
    allowlist: Any,
    blocklist: Any,
    limit: int,
) -> list[CapabilityItem]:
    allowed = normalize_names(allowlist)
    blocked = normalize_names(blocklist)
    selected: list[CapabilityItem] = []
    seen: set[str] = set()

    for item in sorted(items, key=lambda current: current.name.lower()):
        key = item.name.strip().lower()
        if not key or key in seen or key in blocked:
            continue
        if allowed and key not in allowed:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= max(1, limit):
            break
    return selected


def render_section(title: str, items: Iterable[CapabilityItem]) -> str:
    lines = []
    for item in items:
        detail = item.description.strip() or "无补充说明"
        owner = item.owner or "未标注"
        lines.append(f"名称：{item.name}；来源：{owner}；说明：{detail}")
    if not lines:
        return ""
    return f"{title}：\n" + "\n".join(lines)
