from __future__ import annotations

import re

from coco_code.compact.token import item_visible_text
from coco_code.conversation import ChatMessage, ConversationItem

SUMMARY_SECTIONS = (
    "1. 主要请求和意图",
    "2. 关键技术概念",
    "3. 文件和代码段",
    "4. 错误和修复",
    "5. 问题解决过程",
    "6. 所有用户消息原文",
    "7. 待办任务",
    "8. 当前工作",
    "9. 可能的下一步",
)


def build_summary_prompt(items: list[ConversationItem]) -> list[ConversationItem]:
    sections = "\n".join(f"- {section}" for section in SUMMARY_SECTIONS)
    content = (
        "你正在为一个长时间运行的代码 agent 压缩较早的对话历史。\n"
        "禁止调用任何工具；本次请求不需要、也不能访问文件或外部资源。\n"
        "先写 <analysis>...</analysis> 作为临时分析草稿，然后写 "
        "<summary>...</summary> 作为正式摘要。系统只会保留 <summary> 内的内容。\n"
        "正式摘要必须包含以下 9 个固定小节，标题逐字保留：\n"
        f"{sections}\n\n"
        "要求：区分用户原话、assistant 推断和工具观察；用户消息原文必须放入第 6 部分。"
        "\n\n<conversation>\n"
        f"{serialize_conversation(items)}\n"
        "</conversation>"
    )
    return [ChatMessage(role="user", content=content)]


def serialize_conversation(items: list[ConversationItem]) -> str:
    return "\n\n".join(
        f"--- item {index} ---\n{item_visible_text(item)}" for index, item in enumerate(items, 1)
    )


def extract_summary(raw: str) -> str:
    match = re.search(r"<summary>(.*?)</summary>", raw, flags=re.DOTALL | re.IGNORECASE)
    if match is None:
        return raw.strip()
    return match.group(1).strip()


def validate_summary(summary: str) -> bool:
    if not summary.strip():
        return False
    return all(section in summary for section in SUMMARY_SECTIONS)
