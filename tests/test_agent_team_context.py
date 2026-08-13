from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coco_code.agents.fork import FORK_BOILERPLATE_TAG
from coco_code.agents.parser import AgentDef
from coco_code.conversation import ConversationManager
from coco_code.teams.models import BackendType
from coco_code.tools import ToolRegistry
from coco_code.tools.agent_tool import AgentTool, AgentToolParams


def _make_tool(tmp_path: Path, backend: BackendType) -> tuple[AgentTool, MagicMock, MagicMock]:
    parent = MagicMock()
    parent.agent_id = "lead-agent"
    parent.trace_id = None
    parent.max_iterations = 20
    parent.client = MagicMock(name="parent-client")
    parent.protocol = "anthropic"
    parent.work_dir = str(tmp_path)
    parent.context_window = 200_000
    parent.hook_engine = None
    parent.registry = ToolRegistry()
    parent._full_registry = None
    parent.replacement_state = MagicMock()
    parent_conv = ConversationManager()
    parent_conv.add_user_message("parent-only context")
    parent_conv.add_assistant_message("parent response")
    parent._current_conversation = parent_conv

    definition = AgentDef(
        agent_type="general-purpose",
        when_to_use="general work",
        system_prompt="worker instructions",
        disallowed_tools=[],
        model="inherit",
        max_turns=20,
        permission_mode="default",
        source="builtin",
    )
    loader = MagicMock()
    loader.get.return_value = definition
    loader.list_agents.return_value = [("general-purpose", "general work")]

    task_manager = MagicMock()
    task_manager.launch.return_value = "task-1"
    trace_manager = MagicMock()
    trace_manager.create.return_value = SimpleNamespace(agent_id="worker-agent")

    team = MagicMock()
    team.members = []
    team_manager = MagicMock()
    team_manager.get_team.return_value = team
    team_manager.detect_backend.return_value = backend
    team_manager.get_mailbox.return_value = MagicMock()

    worktree = SimpleNamespace(path=str(tmp_path / "worker-tree"))
    worktree_manager = MagicMock()
    worktree_manager.create = AsyncMock(return_value=worktree)

    tool = AgentTool(
        agent_loader=loader,
        task_manager=task_manager,
        trace_manager=trace_manager,
        parent_agent=parent,
        enable_fork=True,
        worktree_manager=worktree_manager,
        team_manager=team_manager,
    )
    return tool, task_manager, team_manager


def _agent_params(
    context_mode: str = "fresh",
) -> AgentToolParams:
    return AgentToolParams(
        prompt="implement only the assigned task",
        description="implementation",
        subagent_type="general-purpose",
        context_mode=context_mode,
        team_name="test-team",
        name="worker",
    )


@pytest.mark.asyncio
async def test_fresh_teammate_never_builds_fork_context(tmp_path: Path) -> None:
    tool, task_manager, _ = _make_tool(tmp_path, BackendType.IN_PROCESS)
    sub_agent = MagicMock()

    with (
        patch("coco_code.agent.Agent", return_value=sub_agent),
        patch(
            "coco_code.agents.tool_filter.build_teammate_tools",
            return_value=ToolRegistry(),
        ),
        patch("coco_code.agents.fork.build_forked_messages") as build_fork,
    ):
        result = await tool.execute(_agent_params())

    assert not result.is_error
    build_fork.assert_not_called()
    launch = task_manager.launch.call_args.kwargs
    assert launch["task"] == "implement only the assigned task"
    assert launch["fork_conversation"] is None


@pytest.mark.asyncio
async def test_fresh_teammate_first_business_message_is_only_task(tmp_path: Path) -> None:
    tool, task_manager, _ = _make_tool(tmp_path, BackendType.IN_PROCESS)

    with (
        patch("coco_code.agent.Agent", return_value=MagicMock()),
        patch(
            "coco_code.agents.tool_filter.build_teammate_tools",
            return_value=ToolRegistry(),
        ),
    ):
        await tool.execute(_agent_params())

    launch = task_manager.launch.call_args.kwargs
    conversation = ConversationManager()
    conversation.add_user_message(launch["task"])
    business_messages = [
        message.content
        for message in conversation.history
        if message.role == "user" and message.content
    ]
    assert business_messages == ["implement only the assigned task"]
    assert "parent-only context" not in business_messages


@pytest.mark.asyncio
async def test_fork_is_explicit_and_copies_parent_history(tmp_path: Path) -> None:
    tool, task_manager, _ = _make_tool(tmp_path, BackendType.IN_PROCESS)

    with (
        patch("coco_code.agent.Agent", return_value=MagicMock()),
        patch(
            "coco_code.agents.tool_filter.build_teammate_tools",
            return_value=ToolRegistry(),
        ),
        patch(
            "coco_code.agents.fork.build_forked_messages",
            wraps=__import__(
                "coco_code.agents.fork", fromlist=["build_forked_messages"]
            ).build_forked_messages,
        ) as build_fork,
    ):
        await tool.execute(_agent_params("fork"))

    build_fork.assert_called_once()
    launch = task_manager.launch.call_args.kwargs
    assert launch["task"] == ""
    forked = launch["fork_conversation"]
    assert forked is not None
    assert [message.content for message in forked.history[:2]] == [
        "parent-only context",
        "parent response",
    ]
    assert FORK_BOILERPLATE_TAG in forked.history[-1].content
    assert "implement only the assigned task" in forked.history[-1].content


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", [BackendType.TMUX, BackendType.ITERM2])
@pytest.mark.parametrize("context_mode", ["fresh", "fork"])
async def test_pane_backends_preserve_context_mode(
    tmp_path: Path,
    backend: BackendType,
    context_mode: str,
) -> None:
    tool, task_manager, team_manager = _make_tool(tmp_path, backend)
    tmux_info = SimpleNamespace(pane_id="tmux-pane")
    iterm_info = SimpleNamespace(session_id="iterm-session")

    with (
        patch("coco_code.agent.Agent", return_value=MagicMock()),
        patch(
            "coco_code.agents.tool_filter.build_teammate_tools",
            return_value=ToolRegistry(),
        ),
        patch("coco_code.teams.transcript.save_transcript") as save_transcript,
        patch(
            "coco_code.teams.spawn_tmux.spawn_tmux_teammate",
            return_value=tmux_info,
        ) as spawn_tmux,
        patch(
            "coco_code.teams.spawn_iterm2.spawn_iterm2_teammate",
            return_value=iterm_info,
        ) as spawn_iterm,
    ):
        result = await tool.execute(_agent_params(context_mode))

    assert not result.is_error
    task_manager.launch.assert_not_called()
    spawn = spawn_tmux if backend == BackendType.TMUX else spawn_iterm
    other_spawn = spawn_iterm if backend == BackendType.TMUX else spawn_tmux
    spawn.assert_called_once()
    other_spawn.assert_not_called()
    cli_command = spawn.call_args.kwargs["cli_command"]
    assert f"--context-mode {context_mode}" in cli_command

    mailbox = team_manager.get_mailbox.return_value
    if context_mode == "fresh":
        save_transcript.assert_not_called()
        mailbox.write.assert_called_once()
        message = mailbox.write.call_args.args[1]
        assert message.content == "implement only the assigned task"
        assert "parent-only context" not in message.content
    else:
        mailbox.write.assert_not_called()
        save_transcript.assert_called_once()
        saved = save_transcript.call_args.args[2]
        assert [message.content for message in saved.history[:2]] == [
            "parent-only context",
            "parent response",
        ]
        assert FORK_BOILERPLATE_TAG in saved.history[-1].content


def test_teammate_cli_and_parser_carry_context_mode(tmp_path: Path) -> None:
    from coco_code.__main__ import _parse_teammate_flags
    from coco_code.teams.spawn import build_teammate_cli

    command = build_teammate_cli(
        "test-team",
        "worker",
        str(tmp_path),
        context_mode="fork",
    )
    assert "--context-mode fork" in command
    assert _parse_teammate_flags(
        [
            "--teammate",
            "--team-name",
            "test-team",
            "--agent-name",
            "worker",
            "--context-mode",
            "fork",
        ]
    ) == ("test-team", "worker", "fork")
