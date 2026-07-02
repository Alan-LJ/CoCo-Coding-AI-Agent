# CoCo Code Agent Loop Plan

## 架构概览

本章采用“新增 Agent 核心层、收窄 TUI 职责”的方案。现有 `CoCoCodeApp` 里已经承担了 provider 流消费、工具执行、历史写入、确认弹窗和 UI 渲染，导致“一次工具调用后停下”的边界写死在 TUI 内。新方案会新增 `coco_code.agent` 包，把 Agent Loop、停止条件、工具分批、模式过滤、事件流和历史写入放进核心层；TUI 只负责提交用户请求、消费事件、展示文本/工具/进度/停止原因。

核心架构分为五层：

1. `llm` provider 层
   继续负责 OpenAI / Anthropic 协议差异，但流式工具调用结果从“单个 `ToolCall`”升级为“多个 `ToolCall`”。OpenAI 现有 accumulator 已按 index 收集多个工具调用碎片，只需把最终转换从取第一个改为生成完整列表；Anthropic accumulator 也升级为按 content block 收集多个 `tool_use`。provider 仍输出统一 `StreamEvent`，不关心 Agent Loop。

2. `conversation` 会话层
   继续维护当前会话历史，但需要支持“一条 assistant 响应包含多个工具调用”。计划新增复数工具调用项，保证 OpenAI/Anthropic 回放格式正确：先写 assistant tool calls，再按模型请求顺序写 tool results。这样即使只读工具并发执行，写回历史的顺序也稳定。

3. `tools` 工具层
   复用现有 `ToolRegistry`、`ToolExecutor`、`ToolSpec`、确认回调和安全元信息。新增工具过滤与分批执行能力：Plan Mode 根据 `read_only=True` 且 `destructive=False` 过滤工具；同一响应里的只读工具可并发执行，`WriteFile`、`EditFile`、`Bash` 等非只读/破坏性/需确认工具串行执行。确认弹窗仍通过现有 confirm callback 触发，不绕过。

4. `agent` 核心层
   新增 `AgentLoop` 作为本章主入口。它接收 provider、conversation、tool registry、tool executor、运行限制和本轮模式，产出异步 `AgentEvent` 流。循环逻辑是：请求模型流 → 双路收集文本和工具调用 → 没工具则停止 → 有工具则分批执行 → 结果写回历史 → 继续下一轮，直到模型完成、迭代上限、取消、未知工具上限、流错误或其他停止条件触发。

5. `tui` 展示层
   `CoCoCodeApp` 不再直接调用 `consume_provider_stream` 和 `_handle_tool_call`。它把用户输入解析成普通 Agent 模式、Plan Mode 或 Do Mode 请求，然后启动 `AgentLoop.run()`，消费事件并调用现有 `view.py` 渲染函数。`view.py` 会补充模式状态、迭代进度、工具批次、停止原因等展示；现有确认弹窗继续保留。

模式设计上，本章只扩展 `/plan` 和 `/do`，不引入完整 slash 命令体系。普通输入使用完整工具集；`/plan` 触发只读计划模式；`/do` 触发执行模式并使用完整工具集。`/plan <任务>` 和 `/do <任务>` 可直接带任务文本；单独输入 `/plan` 或 `/do` 时，Agent 基于当前会话上下文生成计划或执行最近计划。

这一架构覆盖 `F1-F20` 的主线：循环在 `agent`，多工具和协议解析在 `llm`，安全分批与确认在 `tools`，历史顺序在 `conversation`，模式和可观测状态在 `tui`。

## 核心数据结构

### AgentMode

```python
class AgentMode(StrEnum):
    AGENT = "agent"
    PLAN = "plan"
    DO = "do"
```

表示当前运行模式。普通输入走 `AGENT`；`/plan` 走 `PLAN`，只下发只读非破坏性工具；`/do` 走 `DO`，下发完整工具集。

### AgentStopReason

```python
class AgentStopReason(StrEnum):
    MODEL_DONE = "model_done"
    ITERATION_LIMIT = "iteration_limit"
    USER_CANCELLED = "user_cancelled"
    UNKNOWN_TOOL_LIMIT = "unknown_tool_limit"
    STREAM_ERROR = "stream_error"
    TOOL_ERROR = "tool_error"
    RUNTIME_ABORT = "runtime_abort"
```

统一描述停止原因。TUI 只展示这个语义结果，不自己推断为什么停。

### AgentLimits

```python
@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = 8
    unknown_tool_limit: int = 2
    response_timeout_seconds: float = 300.0
    tool_timeout_seconds: float = 10.0
    confirm_timeout_seconds: float = 60.0
    read_tool_concurrency: int = 4
```

本章先提供代码层默认值，后续再接配置文件。`tool_timeout_seconds` 和 `confirm_timeout_seconds` 会同步写入 `ToolContext`，避免 TUI 和工具层各自维护一套边界。

### AgentRunRequest

```python
@dataclass(frozen=True)
class AgentRunRequest:
    text: str
    mode: AgentMode
```

TUI 把用户输入解析成这个请求后交给 Agent。`/plan xxx` 会变成 `mode=PLAN, text=xxx`；`/do xxx` 会变成 `mode=DO, text=xxx`。

### StreamTurnResult

```python
@dataclass(frozen=True)
class StreamTurnResult:
    reply: str
    tool_calls: tuple[ToolCall, ...] = ()
    error: Exception | None = None
```

替代当前 TUI 的 `StreamResult.tool_call` 单数结构。它由新的流式收集器生成：文本增量实时发事件，完整 reply 和全部 tool calls 留给 Agent Loop 判断下一步。

### AgentEventType

```python
class AgentEventType(StrEnum):
    MODE_CHANGED = "mode_changed"
    PROGRESS = "progress"
    TEXT_DELTA = "text_delta"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALLS = "tool_calls"
    TOOL_BATCH_STARTED = "tool_batch_started"
    TOOL_STARTED = "tool_started"
    TOOL_RESULT = "tool_result"
    USAGE = "usage"
    ERROR = "error"
    STOPPED = "stopped"
```

事件是 Agent 和 TUI 的边界。TUI 根据事件渲染历史区、流式区、状态栏和停止原因。

### AgentEvent

```python
@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    text: str = ""
    mode: AgentMode | None = None
    progress: AgentProgress | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    stop_reason: AgentStopReason | None = None
    error: Exception | str | None = None
    usage: dict[str, int] | None = None
```

先用一个统一事件结构，避免为每种事件建很多小类。测试可以直接断言事件序列。

### AgentProgress

```python
@dataclass(frozen=True)
class AgentProgress:
    iteration: int
    max_iterations: int
    phase: str
    tool_name: str | None = None
    batch_index: int | None = None
    batch_total: int | None = None
```

用于展示“第几轮、正在等模型、正在执行哪个工具、当前批次”等状态。

### AgentLoop

```python
class AgentLoop:
    def __init__(
        self,
        provider: Provider,
        conversation: Conversation,
        registry: ToolRegistry,
        executor: ToolExecutor,
        limits: AgentLimits,
    ) -> None: ...

    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]: ...
```

`AgentLoop.run()` 是本章主入口。它负责添加用户消息、循环请求 provider、执行工具、写回历史，并持续产出事件。

### ToolBatcher

```python
class ToolBatcher:
    def build_batches(
        self,
        calls: Sequence[ToolCall],
        registry: ToolRegistry,
        mode: AgentMode,
    ) -> list[ToolBatch]: ...
```

`ToolBatcher` 根据工具元信息分批：只读非破坏性工具可并发；非只读、破坏性或需要确认的工具单独串行批次。Plan Mode 的不允许工具会转成结构化错误结果，不执行。

### ToolBatch

```python
@dataclass(frozen=True)
class ToolBatch:
    calls: tuple[ToolCall, ...]
    concurrent: bool
```

并发批次只用于只读工具。副作用工具永远 `concurrent=False`，并按模型请求顺序执行。

### StreamEvent

Provider 层同步调整：

```python
@dataclass(frozen=True)
class StreamEvent:
    type: EventType
    text: str = ""
    tool_call: ToolCall | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    error: Exception | None = None
    usage: dict[str, int] | None = None
```

保留 `tool_call` 兼容旧代码，但 Agent 新逻辑只读 `tool_calls`；旧单工具 provider 可以填单元素 tuple。

## 模块设计

### `coco_code.agent.types`

**职责：** 定义 Agent Loop 的公共类型，作为核心层、TUI、测试之间的稳定契约。

**对外接口：** `AgentMode`、`AgentStopReason`、`AgentLimits`、`AgentRunRequest`、`AgentProgress`、`AgentEventType`、`AgentEvent`、`StreamTurnResult`、`ToolBatch`。

**依赖：** 只依赖标准库、`coco_code.tools.base`。不依赖 Textual/Rich。

### `coco_code.agent.stream`

**职责：** 替代当前 `coco_code.tui.stream.consume_provider_stream`，负责消费 provider 的流式事件，并完成“双路收集”。

**对外接口：**

```python
async def collect_stream_turn(
    provider: Provider,
    messages: list[ConversationItem],
    tools: ToolRegistry | None,
    on_event: Callable[[AgentEvent], Awaitable[None]],
) -> StreamTurnResult: ...
```

**行为：**
- 收到 `TEXT_DELTA` 时，立刻发出 `AgentEvent(TEXT_DELTA)`，同时累积完整 reply。
- 收到 `THINKING_DELTA` 时丢弃，不进入 UI，不进入历史。
- 收到 `TOOL_CALL` 时收集全部 `tool_calls`，不只取第一个。
- 收到 `ERROR` 时返回 `StreamTurnResult(error=...)`。
- 收到 `DONE` 时返回完整结果。

**依赖：** `Provider`、`ConversationItem`、`ToolRegistry`、`AgentEvent`。

### `coco_code.agent.tools`

**职责：** 工具过滤、未知工具处理、多工具分批和执行调度。

**对外接口：**

```python
def registry_for_mode(registry: ToolRegistry, mode: AgentMode) -> ToolRegistry: ...

def validate_tool_allowed(
    call: ToolCall,
    registry: ToolRegistry,
    mode: AgentMode,
) -> ToolResult | None: ...

class ToolBatcher:
    def build_batches(
        self,
        calls: Sequence[ToolCall],
        registry: ToolRegistry,
        mode: AgentMode,
    ) -> list[ToolBatch]: ...

async def execute_tool_batches(
    batches: Sequence[ToolBatch],
    executor: ToolExecutor,
    on_event: Callable[[AgentEvent], Awaitable[None]],
    concurrency_limit: int,
) -> list[ToolResult]: ...
```

**行为：**
- `registry_for_mode` 基于 `ToolSpec.read_only`、`ToolSpec.destructive`、`ToolSpec.category` 和 `ToolSpec.confirmation` 过滤工具。
- Plan Mode 只保留只读、非破坏性、无需确认的工具。
- 未知工具或当前模式不允许工具返回结构化 `ToolResult`，不执行真实工具。
- 多个只读工具组成并发批次，结果按原请求顺序返回。
- 副作用工具拆成单工具串行批次，保持模型请求顺序。
- `ToolExecutor.execute()` 仍负责参数校验、确认弹窗、超时和异常包装。

**依赖：** `ToolRegistry`、`ToolExecutor`、`ToolSpec`、`ToolCall`、`ToolResult`。

### `coco_code.agent.loop`

**职责：** 实现 ReAct 风格 Agent Loop 主流程。

**对外接口：**

```python
class AgentLoop:
    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]: ...
```

**行为：**
- 开始时把用户文本写入 `Conversation.add_user()`。
- 根据模式选择工具 registry，并向 provider 下发对应工具列表。
- 每次迭代发出 `PROGRESS` 事件，包含当前迭代序号、最大迭代数、阶段。
- 调用 `collect_stream_turn()` 获取本轮完整 assistant 文本和工具调用列表。
- 有 assistant 文本时写入历史并发出 `ASSISTANT_MESSAGE`。
- 没有工具调用时以 `MODEL_DONE` 停止。
- 有工具调用时写入 assistant tool calls，执行工具批次，按请求顺序写入 tool results，然后进入下一轮。
- 达到 `max_iterations` 时停止并发出 `STOPPED(iteration_limit)`。
- 连续未知工具或不允许工具达到上限时停止。
- 流式错误时停止并发出 `ERROR` 和 `STOPPED(stream_error)`。
- 捕获 `CancelledError`，发出 `STOPPED(user_cancelled)` 后向外传播或安全结束。

**依赖：** `Provider`、`Conversation`、`ToolRegistry`、`ToolExecutor`、`agent.stream`、`agent.tools`。

### `coco_code.conversation`

**职责：** 保存协议可回放的会话历史。

**调整：**
- 新增 `AssistantToolCallsItem`，可承载一组 `ToolCall`。
- 保留 `AssistantToolCallItem` 兼容旧测试和旧调用点。
- 新增 `Conversation.add_tool_calls(calls: Sequence[ToolCall])`。
- `items()` 返回包括多工具调用项在内的完整历史。
- `messages()` 仍只返回用户/助手纯文本消息，保持旧兼容。

**依赖：** `ToolCall`、`ToolResult`。

### `coco_code.llm`

**职责：** 继续提供协议无关 provider 接口和流事件。

**调整：**
- `StreamEvent` 新增 `tool_calls: tuple[ToolCall, ...]` 和可选 `usage`。
- `StreamEvent.tool_call` 保留兼容，但新逻辑优先读 `tool_calls`。
- OpenAI provider 的 `_openai_tool_event()` 改为 `_openai_tool_calls_event()`，从 accumulator 中按 index 生成全部 `ToolCall`。
- Anthropic provider 的 accumulator 改为支持多个 `tool_use` block，按 block 顺序生成全部 `ToolCall`。
- OpenAI/Anthropic 的历史回放函数支持 `AssistantToolCallsItem`。

**依赖：** `ConversationItem`、`ToolRegistry`、`ToolCall`。

### `coco_code.tui.app`

**职责：** 处理用户输入、provider 选择、确认弹窗、渲染 AgentEvent。

**调整：**
- 移除 `_handle_tool_call()` 和 `_stream_final_reply()` 里的“一次工具调用”边界。
- `submit_user_text()` 解析 `/plan`、`/do`、普通输入，生成 `AgentRunRequest`。
- 启动 `AgentLoop.run()`，消费事件并调用 `view.py` 渲染。
- 维护当前 mode、当前 progress、当前 streaming reply。
- 取消任务时调用当前 Agent task 的 cancel，恢复输入框和状态栏。
- 保留 `confirm_tool_call()`，由 `ToolExecutor` 通过 callback 调用。

**依赖：** `AgentLoop`、`AgentEvent`、`ToolExecutor`、Textual widgets、`view.py`。

### `coco_code.tui.view`

**职责：** 继续提供 Rich/Textual 展示块。

**调整：**
- 新增 `agent_progress_text(progress, elapsed)`。
- 新增 `agent_stop_block(reason, detail)`。
- 新增 `mode_status_text(provider, mode, message_count, progress)`。
- 新增 `tool_batch_block(batch_index, batch_total, calls, concurrent)`。
- `second_tool_block()` 保留但不再作为正常流程使用，只用于兼容旧测试或异常边界。

### `tests`

**职责：** 用 fake provider / fake tool / fake confirm 覆盖 Agent 核心，无需真实 API。

**新增/调整：**
- 新增 `tests/test_agent_loop.py`：多轮工具调用、停止条件、取消、未知工具。
- 新增 `tests/test_agent_tools.py`：模式过滤、分批、只读并发、副作用串行。
- 调整 `tests/test_llm_tool_events.py`：多工具解析和历史回放。
- 调整 `tests/test_tui_app.py` / `tests/test_tui_tools.py`：TUI 消费事件、模式状态、确认弹窗不退化。
- 继续使用 `.codeagent` 虚拟环境运行 `pytest`、`ruff check`、`mypy`。

## 模块交互

### 普通 Agent 模式数据流

```text
用户输入
  → TUI 解析为 AgentRunRequest(mode=AGENT)
  → AgentLoop.run()
  → Conversation.add_user()
  → registry_for_mode(AGENT) 返回完整工具集
  → collect_stream_turn(provider, conversation.items(), tools)
      → TEXT_DELTA 立即转成 AgentEvent.TEXT_DELTA 给 TUI
      → DONE / TOOL_CALL / ERROR 被收集成 StreamTurnResult
  → 如果无工具调用：
      → Conversation.add_assistant(reply)
      → AgentEvent.ASSISTANT_MESSAGE
      → AgentEvent.STOPPED(MODEL_DONE)
  → 如果有工具调用：
      → Conversation.add_tool_calls(calls)
      → AgentEvent.TOOL_CALLS
      → ToolBatcher.build_batches()
      → execute_tool_batches()
      → Conversation.add_tool_result(result) 按原始顺序写入
      → 进入下一次迭代
```

这一条链路解决当前“一次工具后就停”的问题：工具结果写回历史后，AgentLoop 会继续请求 provider，而不是强制进入最终回复模式。

### Plan Mode 数据流

```text
用户输入 /plan 修复某问题
  → TUI 解析为 AgentRunRequest(mode=PLAN, text="修复某问题")
  → AgentEvent.MODE_CHANGED(PLAN)
  → registry_for_mode(PLAN)
      只保留 read_only=True 且 destructive=False 且 confirmation=NEVER 的工具
  → 模型只能看到 ReadFile / Glob / Grep 等只读工具
  → AgentLoop 正常循环读取/搜索
  → 模型输出计划文本
  → AgentEvent.STOPPED(MODEL_DONE)
```

如果模型在 Plan Mode 请求 `WriteFile`、`EditFile`、`Bash` 或其他不允许工具，`validate_tool_allowed()` 返回结构化错误结果，写回历史；连续达到上限后以 `UNKNOWN_TOOL_LIMIT` 停止。

### Do Mode 数据流

```text
用户输入 /do
  → TUI 解析为 AgentRunRequest(mode=DO)
  → AgentEvent.MODE_CHANGED(DO)
  → registry_for_mode(DO) 返回完整工具集
  → 模型基于最近计划和会话上下文继续执行
  → 写文件、改文件、Bash 调用仍进入 ToolExecutor.confirm
  → TUI 弹出确认
  → 批准后执行，拒绝则写回拒绝结果
  → AgentLoop 根据结果继续下一轮或停止
```

`/do` 不保存跨会话计划，也不引入新的计划数据库。它只利用当前会话历史，所以实现范围保持克制。

### 多工具调用执行流

```text
一次模型响应返回 calls = [Glob, Grep, EditFile, Bash]
  → AgentLoop 收集全部 calls
  → Conversation.add_tool_calls(calls)
  → ToolBatcher 生成批次：
      Batch 1: [Glob, Grep], concurrent=True
      Batch 2: [EditFile], concurrent=False
      Batch 3: [Bash], concurrent=False
  → Batch 1 并发执行，但结果按 [Glob, Grep] 顺序返回和写入
  → Batch 2 弹确认，批准后执行
  → Batch 3 弹确认，批准后执行
  → 全部结果按原始请求顺序写入 Conversation
  → 下一次 AgentLoop 迭代
```

并发只影响执行速度，不影响历史顺序。副作用工具不会并发。

### 停止条件流

```text
每轮迭代开始
  → 检查 iteration <= max_iterations
  → 请求 provider
  → provider 出错：ERROR + STOPPED(STREAM_ERROR)
  → provider 完成且无工具：STOPPED(MODEL_DONE)
  → provider 请求工具：
      → 未知/不允许工具计数增加
      → 达到 unknown_tool_limit：STOPPED(UNKNOWN_TOOL_LIMIT)
      → 否则执行工具并继续
  → 用户取消：
      → cancel 当前 Agent task
      → STOPPED(USER_CANCELLED)
      → TUI 恢复输入
  → 达到 max_iterations：
      → STOPPED(ITERATION_LIMIT)
```

这样所有停止都有事件和可见原因，避免再次出现无限 `Imagining...`。

### TUI 渲染流

```text
AgentEvent.TEXT_DELTA
  → 更新 #stream，显示当前流式文本 + Imagining 秒数

AgentEvent.ASSISTANT_MESSAGE
  → 写入 history，使用 markdown 定型展示

AgentEvent.TOOL_CALLS
  → 对每个工具调用写入 Tool 面板

AgentEvent.TOOL_BATCH_STARTED / TOOL_STARTED
  → 更新进度区和历史区摘要

AgentEvent.TOOL_RESULT
  → 写入 Tool Result 面板

AgentEvent.ERROR
  → 写入 Error 面板

AgentEvent.STOPPED
  → 写入停止原因，清空 stream，恢复输入框，更新状态栏
```

TUI 不再判断“下一步该不该继续调用模型”，只忠实消费事件。Agent 核心因此可以用 headless 单元测试覆盖，TUI 只测渲染和交互。

## 文件组织

```text
src/
└── coco_code/
    ├── agent/
    │   ├── __init__.py
    │   │   — 导出 AgentLoop、AgentMode、AgentLimits、AgentEvent 等核心类型
    │   ├── types.py
    │   │   — AgentMode、AgentStopReason、AgentLimits、AgentRunRequest、
    │   │     AgentProgress、AgentEvent、StreamTurnResult、ToolBatch
    │   ├── stream.py
    │   │   — collect_stream_turn；消费 provider 流，实时转发文本事件，
    │   │     同时收集完整 reply 和多个 tool calls
    │   ├── tools.py
    │   │   — registry_for_mode、validate_tool_allowed、ToolBatcher、
    │   │     execute_tool_batches；负责工具过滤、分批、调度
    │   └── loop.py
    │       — AgentLoop 主循环；停止条件、历史写入、事件产出
    │
    ├── conversation.py
    │   — 增加 AssistantToolCallsItem 和 add_tool_calls；
    │     保持旧 AssistantToolCallItem 兼容
    │
    ├── llm/
    │   ├── __init__.py
    │   │   — StreamEvent 增加 tool_calls、usage；Provider 协议保持统一
    │   ├── openai_provider.py
    │   │   — OpenAI 多 tool_calls 解析；多工具历史回放
    │   └── anthropic_provider.py
    │       — Anthropic 多 tool_use 收集；多工具历史回放
    │
    ├── tools/
    │   ├── base.py
    │   │   — 保持 ToolSpec 元信息；必要时补充 helper，不改变现有语义
    │   ├── registry.py
    │   │   — 增加从 specs 过滤生成 registry 的能力，或提供 filtered clone
    │   └── executor.py
    │       — 继续负责确认、超时、参数校验、结构化错误
    │
    └── tui/
        ├── app.py
        │   — 接入 AgentLoop；解析 /plan、/do；消费 AgentEvent；
        │     删除一次工具调用边界
        ├── stream.py
        │   — 迁移到 agent.stream 后保留兼容薄包装，或在测试迁移后删除
        └── view.py
            — 增加模式、进度、工具批次、停止原因展示函数
```

测试文件组织：

```text
tests/
├── test_agent_loop.py
│   — 多轮循环、迭代上限、取消、未知工具、流式错误、纯对话兼容
├── test_agent_tools.py
│   — Plan Mode 工具过滤、多工具分批、只读并发、副作用串行
├── test_llm_tool_events.py
│   — OpenAI / Anthropic 多工具流式解析和历史回放
├── test_conversation_tools.py
│   — 多工具调用项顺序、messages() 兼容
├── test_tui_app.py
│   — TUI 模式切换、状态恢复、provider 选择不退化
└── test_tui_tools.py
    — 工具确认、工具结果展示、拒绝/超时等 UI 行为不退化
```

文档文件：

```text
spec.md       — 已批准的 Agent Loop 需求
plan.md       — 本技术方案
task.md       — 后续按本方案拆成可执行任务
checklist.md  — 后续验收清单
INSTALL.md    — 若本章新增依赖，再补充安装说明；本方案预计不新增依赖
```

本章预计不新增第三方库。并发、取消、超时使用 Python 标准库 `asyncio`；事件类型使用 `dataclasses` 和 `StrEnum`；现有依赖 `textual`、`rich`、`openai`、`anthropic`、`pyyaml` 保持不变。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Agent Loop 放在哪里 | 新增 `coco_code.agent` 包 | 避免继续膨胀 `tui.app`，让核心循环可用 fake provider/headless 测试验证。 |
| TUI 与 Agent 如何通信 | 异步 `AgentEvent` 流 | 满足 spec 的事件流解耦要求；TUI 只渲染事件，不参与循环判断。 |
| 流式处理方式 | 双路收集：实时发文本事件，同时累积完整结果 | 保持逐字流式体验，同时让 Agent 能判断是否继续调用工具。 |
| 多工具表示 | `StreamEvent.tool_calls: tuple[ToolCall, ...]` | 直接表达“一次响应多个工具调用”，避免继续被单数 `tool_call` 限制。 |
| 兼容旧接口 | 暂时保留 `StreamEvent.tool_call` 和旧 `AssistantToolCallItem` | 降低改动风险，旧测试和旧调用点可以逐步迁移。 |
| 工具过滤依据 | 基于 `ToolSpec` 的 `read_only`、`destructive`、`confirmation`、`category` | 满足用户强调的“元信息是后续权限系统基础”，不靠硬编码工具名。 |
| Plan Mode 工具集 | 只读、非破坏性、无需确认工具 | 保证 `/plan` 不会改文件、跑命令或安装依赖。 |
| Do Mode 工具集 | 完整工具集 + 现有确认机制 | 执行计划需要文件修改和命令能力，但不能绕过确认。 |
| 多工具执行策略 | 只读工具并发，副作用/确认/破坏性工具串行 | 提高只读观察效率，同时保证写文件、编辑和 shell 命令顺序可预测。 |
| 并发结果顺序 | 执行可并发，历史写入按模型请求顺序 | 防止模型观察到乱序结果，保持协议可回放。 |
| 未知/不允许工具 | 生成结构化 `ToolResult` 回灌模型，连续达到上限才停止 | 给模型一次自我修正机会，同时防止无限循环。 |
| 迭代上限 | 默认 `max_iterations=8` | 足够覆盖“找文件 → 读 → 改 → 测 → 修”这类小任务，又能避免失控。 |
| 只读并发上限 | 默认 `read_tool_concurrency=4` | 保守控制文件读取和搜索压力，避免 TUI 卡顿。 |
| 响应超时 | 默认沿用 `300s` | 保持现有体验，同时避免无限 `Imagining...`。 |
| 工具确认超时 | 默认沿用 `60s` | 避免确认弹窗无人处理时永久挂住。 |
| 工具执行超时 | 默认沿用 `10s`，工具参数仍不能超过上下文上限 | 继续约束 `Bash` 和文件/搜索工具，避免长时间阻塞。 |
| 取消实现 | cancel 当前 Agent task，并让 `ToolExecutor` / provider 保持 `CancelledError` 传播 | 符合 asyncio 语义，避免吞掉取消导致界面恢复不了。 |
| Provider 协议差异 | 在 OpenAI/Anthropic adapter 内部处理 | Agent Loop 只看统一 `StreamEvent`，保证跨协议一致。 |
| 测试策略 | 核心用 fake provider/fake tool/fake confirm，TUI 用 headless Textual 测试 | 不依赖真实 API，能稳定覆盖循环、分批、停止和模式行为。 |
| 依赖选择 | 不新增第三方依赖 | 当前 `asyncio`、Textual、Rich 已足够实现本章，降低安装和兼容风险。 |

## Spec 覆盖自检

- `F1-F5`：由 `AgentLoop`、`AgentLimits`、停止原因、取消流程覆盖。
- `F6-F7`：由 `AgentEvent` 和 `collect_stream_turn` 覆盖。
- `F8-F10`：由 provider 多工具解析、`ToolBatcher`、`ToolExecutor` 确认机制覆盖。
- `F11-F14`：由 `AgentMode`、`registry_for_mode`、TUI `/plan` `/do` 解析覆盖。
- `F15-F17`：由未知工具计数、流式错误事件、进度/用量事件覆盖。
- `F18-F20`：由兼容路径、会话历史顺序和 `AgentLimits` 默认值覆盖。