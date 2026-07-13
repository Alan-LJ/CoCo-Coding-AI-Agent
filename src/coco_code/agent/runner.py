from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from coco_code.agent.loop import AgentLoop
from coco_code.agent.runtime import SessionRuntime, new_session_runtime
from coco_code.agent.types import (
    AgentEventType,
    AgentLimits,
    AgentMode,
    AgentRunRequest,
    AgentStopReason,
)
from coco_code.config import ProviderConfig, effective_context_window
from coco_code.conversation import Conversation
from coco_code.hook import HookEngine
from coco_code.llm import Provider, new_provider
from coco_code.permission import Mode as PermissionMode
from coco_code.permission.engine import Engine
from coco_code.tools.base import ConfirmCallback, ToolContext
from coco_code.tools.executor import PermissionCallback, ToolExecutor
from coco_code.tools.registry import ToolRegistry

ProviderFactory = Callable[[ProviderConfig, str], Provider]
PromptBuilder = Callable[[ProviderConfig, SessionRuntime], str]


@dataclass
class LoopSubAgent:
    provider_cfg: ProviderConfig
    registry: ToolRegistry
    tool_context: ToolContext
    confirm_callback: ConfirmCallback
    prompt_builder: PromptBuilder
    agent_limits: AgentLimits
    permission_mode: PermissionMode
    provider_factory: ProviderFactory = new_provider
    permission_engine: Engine | None = None
    permission_callback: PermissionCallback | None = None
    hook_engine: HookEngine | None = None
    runtime: SessionRuntime | None = None

    async def run_to_completion(
        self,
        conv: Conversation,
        task: str,
        *,
        events: Any = None,
    ) -> str:
        runtime = self.runtime
        if runtime is None:
            runtime = new_session_runtime(
                self.tool_context.workspace,
                effective_context_window(self.provider_cfg),
            )
            self.runtime = runtime

        executor = ToolExecutor(
            self.registry,
            self.tool_context,
            self.confirm_callback,
            self.permission_engine,
            self.permission_callback,
            self.permission_mode,
        )
        provider = self.provider_factory(
            self.provider_cfg,
            self.prompt_builder(self.provider_cfg, runtime),
        )
        loop = AgentLoop(
            provider,
            conv,
            self.registry,
            executor,
            self.agent_limits,
            runtime=runtime,
            system_prompt_builder=lambda: self.prompt_builder(self.provider_cfg, runtime),
            hook_engine=self.hook_engine,
        )
        final_reply = ""
        stop_reason: AgentStopReason | None = None
        error_text = ""
        request = AgentRunRequest(task, AgentMode.AGENT, self.permission_mode)
        async for event in loop.run(request):
            if events is not None:
                await events.put(event)
            if event.type == AgentEventType.ASSISTANT_MESSAGE and event.text:
                final_reply = event.text
            elif event.type == AgentEventType.ERROR and event.error is not None:
                error_text = str(event.error)
            elif event.type == AgentEventType.STOPPED:
                stop_reason = event.stop_reason

        if final_reply:
            return final_reply
        if error_text:
            raise RuntimeError(error_text)
        if stop_reason is not None:
            return f"SubAgent finished with stop reason: {stop_reason.value}"
        return "SubAgent finished without a model summary."


def clone_conversation(items: Sequence[object] = ()) -> Conversation:
    return Conversation.from_items(items)  # type: ignore[arg-type]
