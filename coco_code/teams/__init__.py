# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com


from coco_code.teams.mailbox import Mailbox, MailboxMessage, create_message
from coco_code.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from coco_code.teams.progress import TeammateProgress, ToolActivity
from coco_code.teams.registry import AgentNameRegistry
from coco_code.teams.shared_task import SharedTask, SharedTaskStore


__all__ = [
    "AgentTeam",
    "AgentNameRegistry",
    "BackendType",
    "Mailbox",
    "MailboxMessage",
    "SharedTask",
    "SharedTaskStore",
    "TeammateInfo",
    "TeammateProgress",
    "ToolActivity",
    "create_message",
    "resolve_team_dir",
    "unique_team_name",
]

