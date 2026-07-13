# Context Management Plan

> 本计划以用户提供的 ch08 上下文管理 Spec 为准。参考稿中的 `coco-code` 路径在当前仓库中落到 `coco_code` 包；参考稿中的 RoleTool 批量结构在当前仓库中落到 `ConversationItem` 序列上的 `AssistantToolCallItem` / `AssistantToolCallsItem` / `ToolResultItem`。

## 架构概览

新增 `src/coco_code/compact/` 子包作为上下文管理的唯一权威入口。该子包不直接管理 TUI、权限或工具执行，只处理会话历史、token 估算、工具结果落盘、摘要压缩、恢复段构建和熔断状态。Agent Loop 在每次 provider 请求前调用它，TUI 的 `/compact` 命令也通过 Agent Loop 调用同一套能力。

上下文管理分三层：

- **第 1 层轻量预防**：遍历 `Conversation.items()`，对 `ToolResultItem` 中过大的 `ToolResult` payload 做“落盘 + 稳定预览替换”。单条超过 50000 字节即替换；同一批工具结果聚合超过 200000 字节时按体积从大到小继续替换，直到达标。替换决策进入会话级账本，保证同一个 tool call id 后续逐字节复用同一预览。
- **第 2 层重量兜底**：当估算 token 达到 `context_window - 20000 - 13000`，或由 `/compact` / `prompt_too_long` 触发时，调用 provider 做一次不带工具的摘要请求，提取 9 部分正式摘要，拼接最近文件快照、当前工具列表、边界提示和近期原文，整体替换 conversation。
- **异常和生命周期支撑**：维护 usage 锚点、最近文件读取记录、自动摘要熔断器、session 目录、摘要请求自身过长的丢消息组重试，以及 `prompt_too_long` 后的一次紧急压缩重试。

长生命周期状态不放在每轮临时变量里，而是由 TUI 会话持有一个 `SessionRuntime`。当前 `CoCoCodeApp` 会为整个进程持有同一个 `Conversation`、`ToolRegistry` 和 `ToolExecutor`；本章给它再增加一个 `SessionRuntime`。每次构造 `AgentLoop` 时注入同一份 runtime，保证替换账本、文件追踪、usage 锚点和熔断计数跨用户 turn 保留。

依赖方向：

```text
cli -> config -> ProviderConfig
cli/app -> agent.runtime -> compact.state
agent.loop -> compact -> conversation / llm / tools.registry
compact -> conversation / llm / tools.base / tools.registry
tui.app -> tui.commands -> AgentLoop.run_force_compact

compact 不 import tui / cli / config。
config 不 import compact。
provider 不 import compact。
```

## 核心数据结构

### `SessionRuntime`

位置：`src/coco_code/agent/runtime.py`

```python
@dataclass
class SessionRuntime:
    replacement: ContentReplacementState
    recovery: RecoveryState
    circuit_breaker: CompactCircuitBreaker
    session: SessionContext
    context_window: int
    usage_anchor: int = 0
    anchor_item_len: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

字段说明：

- `replacement`：工具结果替换决策账本。
- `recovery`：最近成功读取文件的快照状态。
- `circuit_breaker`：自动摘要连续失败计数。
- `session`：本进程会话 id 和 `.coco-code/sessions/<session_id>/tool-results/` 路径。
- `context_window`：当前 provider 的上下文窗口，provider 选定后写入。
- `usage_anchor`：最近一次主对话 provider 请求返回的真实 usage 合计；摘要请求不更新它。
- `anchor_item_len`：记录 usage anchor 时的 `Conversation.items()` 长度。
- `lock`：保护手动 `/compact` 与正在运行的 agent turn 不并发修改 conversation。

### `ContentReplacementState`

位置：`src/coco_code/compact/state.py`

```python
class ContentReplacementState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, ToolResult] = {}

    async def decide_once(
        self,
        tool_call_id: str,
        original: ToolResult,
        decide: Callable[[], ReplacementDecision],
    ) -> ToolResult: ...
```

`_seen_ids` 记录已经完成决策的 tool call id，无论保留原文还是替换预览。`_replacements` 只保存被替换后的 `ToolResult` 对象。`decide_once` 在同一把锁内完成“查账本、执行决策、写账本”，避免出现已 seen 但 replacement 尚未写入的中间态。若落盘失败，决策返回 `skip`，不写入 `_seen_ids`，下次请求前重新评估。

### `ReplacementDecision`

位置：`src/coco_code/compact/state.py`

```python
@dataclass(frozen=True)
class ReplacementDecision:
    kind: Literal["kept", "replaced", "skip"]
    result: ToolResult | None = None
```

`kept` 表示本会话内固定保留原文；`replaced` 表示固定替换为 `result`；`skip` 表示本次因 I/O 等失败未完成决策。

### `SessionContext`

位置：`src/coco_code/compact/state.py`

```python
@dataclass(frozen=True)
class SessionContext:
    session_id: str
    spill_dir: Path

def new_session_context(workspace: Path) -> SessionContext: ...
```

`new_session_context` 生成 `<unix_ts>-<short_random>`，创建 `.coco-code/sessions/<session_id>/tool-results/`。进程退出不自动清理该目录。

### `FileReadRecord` / `RecoveryState`

位置：`src/coco_code/compact/recovery.py`

```python
@dataclass(frozen=True)
class FileReadRecord:
    path: str
    content: str
    timestamp: datetime

class RecoveryState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._files: dict[str, FileReadRecord] = {}

    async def record_file(self, path: str, content: str) -> None: ...
    async def snapshot(self) -> list[FileReadRecord]: ...
```

key 使用解析后的绝对路径，避免同一文件用不同相对路径重复记录。`snapshot` 返回按 `timestamp` 倒序排序的拷贝。

### `CompactCircuitBreaker`

位置：`src/coco_code/compact/state.py`

```python
class CompactCircuitBreaker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0

    async def record_success(self) -> None: ...
    async def record_failure(self) -> None: ...
    async def tripped(self) -> bool: ...
```

只影响自动摘要。手动 `/compact` 和紧急压缩绕过熔断器，它们的失败也不计入自动熔断。

### `ManageInput` / `ManageOutput`

位置：`src/coco_code/compact/manager.py`

```python
class TriggerKind(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"

@dataclass
class ManageInput:
    conversation: Conversation
    provider: Provider
    tools: ToolRegistry
    runtime: SessionRuntime
    trigger: TriggerKind
    estimated_tokens: int

@dataclass(frozen=True)
class ManageOutput:
    before_tokens: int
    after_tokens: int
    offloaded_results: int = 0
    compacted: bool = False
```

`tools` 是本轮将传给 provider 的同一个 `ToolRegistry`，恢复段直接从它渲染工具列表，provider 请求也使用同一个 registry。

### `CompactEvent`

位置：`src/coco_code/agent/types.py`

```python
class CompactPhase(StrEnum):
    BEFORE_AUTO = "before_auto"
    AFTER_AUTO = "after_auto"
    BEFORE_EMERGENCY = "before_emergency"
    AFTER_EMERGENCY = "after_emergency"
    MANUAL_DONE = "manual_done"

@dataclass(frozen=True)
class CompactEvent:
    phase: CompactPhase
    before_tokens: int = 0
    after_tokens: int = 0
    error: Exception | str | None = None
```

`AgentEvent` 追加 `compact: CompactEvent | None = None`。TUI 用它展示自动和紧急压缩状态；手动压缩可以直接复用同一格式化函数展示完成态。

### `ProviderConfig.context_window`

位置：`src/coco_code/config.py`

```python
@dataclass(frozen=True)
class ProviderConfig:
    name: str
    protocol: ProtocolName
    model: str
    base_url: str | None = None
    api_key: str | None = None
    thinking: bool = False
    context_window: int = 0

def effective_context_window(provider: ProviderConfig) -> int: ...
```

默认值：Anthropic `200000`，OpenAI / OpenAI-compatible `128000`。配置值大于 0 时覆盖默认。

### `PromptTooLongError`

位置：`src/coco_code/llm/__init__.py`

```python
class PromptTooLongError(RuntimeError):
    pass
```

OpenAI / Anthropic provider 把各自 SDK 的上下文过长错误包装成该异常，并通过 `StreamEvent(type=ERROR, error=wrapped)` 进入 Agent Loop。

## 模块设计

### `src/coco_code/compact/constants.py`

集中保存硬编码常量：

```python
SINGLE_RESULT_LIMIT_BYTES = 50_000
BATCH_RESULT_LIMIT_BYTES = 200_000
SUMMARY_RESERVE_TOKENS = 20_000
AUTO_SAFETY_MARGIN_TOKENS = 13_000
MANUAL_SAFETY_MARGIN_TOKENS = 3_000
RECENT_KEEP_TOKENS = 10_000
RECENT_KEEP_ITEMS = 5
RECOVERY_FILE_LIMIT = 5
RECOVERY_TOKENS_PER_FILE = 5_000
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3
PTL_RETRY_LIMIT = 3
PTL_DROP_PERCENTAGE = 0.2
ESTIMATE_CHARS_PER_TOKEN = 3.5
PREVIEW_HEAD_BYTES = 2048
PREVIEW_HEAD_LINES = 20
```

### `src/coco_code/compact/token.py`

职责：近似 token 估算和 usage 合并。

```python
def estimate_tokens(
    anchor: int,
    items: list[ConversationItem],
    anchor_item_len: int,
) -> int: ...

def usage_anchor(usage: dict[str, int] | None) -> int: ...

def conversation_bytes(items: list[ConversationItem]) -> int: ...
```

`conversation_bytes` 必须按 provider 实际可见内容估算：`ChatMessage.content`、工具调用参数 JSON、`ToolResult` payload JSON 都计入 UTF-8 字节。`estimate_tokens` 使用 `items[anchor_item_len:]` 作为增量；anchor 为 0 时估算完整列表。

### `src/coco_code/compact/layer1.py`

职责：工具结果落盘、预览体构造、批次聚合判断。

```python
async def offload_and_snip(
    items: list[ConversationItem],
    state: ContentReplacementState,
    session: SessionContext,
) -> tuple[list[ConversationItem], int]: ...

def tool_result_payload_bytes(result: ToolResult) -> int: ...

def build_preview_result(
    original: ToolResult,
    original_bytes: int,
    spill_path: Path,
) -> ToolResult: ...

async def spill_single(session: SessionContext, result: ToolResult) -> Path: ...
```

当前 `Conversation` 不使用 RoleTool 消息，而是把每个工具结果作为独立 `ToolResultItem` 插入列表。因此 layer1 的批次识别规则是：

1. 遇到 `AssistantToolCallItem` 或 `AssistantToolCallsItem`，记录本轮 expected tool call id 集合。
2. 紧随其后的 `ToolResultItem` 按 tool call id 归入当前批次。
3. 遇到下一条 `ChatMessage` 或下一条 assistant tool call，当前批次结束。
4. 对每个批次先处理单条阈值，再处理剩余聚合阈值。

`build_preview_result` 返回新的 `ToolResult`，保持原 `tool_call_id`、`tool_name`、`ok`、`elapsed_ms`，把完整内容替换为稳定预览：

- `summary` 说明结果已落盘并给出路径。
- `data` 包含 `offloaded: true`、`path`、`original_bytes`、`preview`、`original_truncated`。
- `error` 保留原错误语义；若原结果失败，也需要把失败详情落盘并在预览中说明。
- `truncated` 置为 `True`。

完整落盘内容使用 JSON，包含原 `ToolResult` 的全部字段和工具结果 provider payload。文件名为原 `tool_call_id`。文件已存在时不重写。

### `src/coco_code/compact/summary_prompt.py`

职责：摘要 prompt 和正式摘要提取。

```python
def build_summary_prompt(items: list[ConversationItem]) -> list[ConversationItem]: ...
def serialize_conversation(items: list[ConversationItem]) -> str: ...
def extract_summary(raw: str) -> str: ...
def validate_summary(summary: str) -> bool: ...
```

`build_summary_prompt` 返回一条 `ChatMessage(role="user", content=...)`，prompt 明确：

- 不允许调用任何工具。
- 先写 `<analysis>...</analysis>` 草稿。
- 再写 `<summary>...</summary>` 正式摘要。
- `<summary>` 内必须包含 9 个固定小节。

`extract_summary` 只保留 `<summary>` 内的正文；若缺失 `<summary>` 或固定小节，调用方把摘要视为失败。

### `src/coco_code/compact/recovery.py`

职责：构建三段恢复内容。

```python
async def build_recovery_attachment(
    recovery: RecoveryState,
    tools: ToolRegistry,
) -> str: ...

def render_file_block(record: FileReadRecord) -> str: ...
def render_tools_block(specs: list[ToolSpec]) -> str: ...

BOUNDARY_NOTICE = "..."
```

恢复内容包含：

1. 最近成功读取的最多 5 个文件，按时间倒序。每个文件最多约 5000 token，超过时按 `5000 * 3.5` 字符估算截断并追加 `(content truncated)`。
2. 当前可用工具列表，由与 provider 请求相同的 `ToolRegistry` 渲染。渲染内容包含工具名、描述和参数 schema 摘要。
3. 固定边界提示，要求模型需要原文或工具输出细节时重新读取，不得根据摘要脑补。

恢复段和摘要合并为一条 user 消息，避免 Anthropic 出现连续 user 消息。

### `src/coco_code/compact/layer2.py`

职责：自动摘要、强制摘要、摘要请求过长重试、近期尾部选择。

```python
async def auto_compact(input: ManageInput) -> tuple[list[ConversationItem], int, int]: ...
async def force_compact(input: ManageInput) -> tuple[list[ConversationItem], int, int]: ...
async def run_summary(input: ManageInput) -> list[ConversationItem]: ...
async def summarize_once(provider: Provider, items: list[ConversationItem]) -> str: ...
async def ptl_retry(input: ManageInput, items: list[ConversationItem]) -> str: ...
def pick_recent_tail(items: list[ConversationItem]) -> list[ConversationItem]: ...
def group_by_user_turn(items: list[ConversationItem]) -> list[list[ConversationItem]]: ...
```

`auto_compact` 成功后清零熔断失败计数；失败后计数加一。`force_compact` 用于手动和紧急路径，不读也不写自动熔断计数。

`run_summary` 输出的新历史结构：

```text
ChatMessage(role="user", content="<9 部分摘要>\n\n<恢复三段>")
<近期原文 tail...>
```

若摘要 user 消息之后的近期原文第一条也是 user 消息，插入一条简短 assistant 衔接消息，避免 provider 对连续 user 消息不兼容。`pick_recent_tail` 在选择 tail 时必须保证不会切开 assistant tool call 和 tool result。

`ptl_retry` 对摘要请求自身 `PromptTooLongError` 采用分组丢弃策略：前 3 次每次丢最旧 1 组；之后每次丢弃剩余组数的 20%（至少 1 组）；消息组耗尽仍失败则抛出。

### `src/coco_code/compact/manager.py`

职责：上下文管理统一入口。

```python
async def manage_context(input: ManageInput) -> ManageOutput: ...
```

流程：

1. `MANUAL`：跳过轻量预防、跳过阈值检查、跳过熔断器，直接 `force_compact`。如果摘要请求自身估算过大，由 layer2 进入 PTL 重试策略。
2. `EMERGENCY`：先强制 `offload_and_snip`，再 `force_compact`。成功后调用方重置 usage 锚点并重试一次 provider 请求。
3. `AUTO`：先执行 `offload_and_snip` 并写回 conversation；用 layer1 后的新历史重新估算 token；未达阈值或熔断器已触发则返回；达到阈值时执行 `auto_compact`，成功后写回 conversation。

`before_tokens` 使用入口估算值；`after_tokens` 在写回后重新估算。

### `src/coco_code/conversation.py`

新增整体替换接口：

```python
def replace_items(self, items: Sequence[ConversationItem]) -> None: ...
```

实现使用拷贝写入，避免调用方持有内部列表引用。现有 `items()` 仍返回拷贝。因当前 TUI 和 Agent Loop 都在同一事件循环线程内运行，Conversation 不新增复杂锁；并发互斥由 `SessionRuntime.lock` 保证。

### `src/coco_code/agent/loop.py`

Agent Loop 接入点：

- `AgentLoop.__init__` 增加 `runtime: SessionRuntime | None = None`，测试未传时创建默认 runtime。
- `run()` 入口 `async with runtime.lock`，保证一次 agent turn 与手动 `/compact` 互斥。
- 每次 provider 请求前构造 `ManageInput(trigger=AUTO)` 并调用 `manage_context`。
- 自动摘要达到阈值前先 yield `AgentEvent(COMPACT, BEFORE_AUTO)`；完成后 yield `AFTER_AUTO`。
- `_collect_turn_task` 捕获 `PromptTooLongError` 并返回到主循环，主循环触发 `EMERGENCY`，成功后重试本次 provider 请求一次。
- provider 请求正常完成并收到 usage 事件后，更新 `runtime.usage_anchor` 和 `runtime.anchor_item_len`。
- 工具结果写回 conversation 前，若 `ReadFile` 成功，重新读取对应文件纯文本并写入 `runtime.recovery`；读取失败时静默跳过，不影响工具结果回灌。
- 新增 `run_force_compact(request_tools: ToolRegistry) -> ManageOutput` 或等价方法，供 TUI `/compact` 调用。

### `src/coco_code/agent/stream.py`

当前 `collect_stream_turn` 已经把 provider `ERROR` 事件放到 `StreamTurnResult.error`。保留该模式，补充 usage 捕获：

- 对任意带 `event.usage` 的事件，继续向 Agent Loop 发 `AgentEventType.USAGE`。
- `StreamTurnResult` 增加 `usage: dict[str, int] | None` 或 Agent Loop 从 event 流累计最后一次 usage。

### `src/coco_code/llm/openai_provider.py`

改动：

- 请求流式输出时尽量启用 usage 回传。
- 识别 OpenAI SDK 的上下文过长错误，例如 `context_length_exceeded` 或错误消息中的上下文过长信息。
- 包装为 `PromptTooLongError` 并 yield `StreamEvent(type=ERROR, error=wrapped)`。
- 其他错误保持现有 ERROR 事件。

### `src/coco_code/llm/anthropic_provider.py`

改动：

- 从 Anthropic stream 事件或最终消息中提取 usage，映射到统一 `StreamEvent.usage`。
- 识别 `prompt is too long` / `prompt_too_long` 一类错误，包装为 `PromptTooLongError`。
- 摘要请求仍走同一个 `provider.stream`，但 tools 参数为 `None`。

### `src/coco_code/tui/commands.py`

新增统一命令分发：

```python
async def dispatch_command(app: CoCoCodeApp, text: str) -> bool: ...
async def handle_exit(app: CoCoCodeApp) -> None: ...
async def handle_plan(app: CoCoCodeApp, text: str) -> None: ...
async def handle_do(app: CoCoCodeApp, text: str) -> None: ...
async def handle_compact(app: CoCoCodeApp) -> None: ...
```

`dispatch_command` 返回是否已处理。以 `/` 开头但未注册的命令显示友好提示，不进入 conversation，不发送给 LLM。`/plan` 和 `/do` 保持现有语义；`/compact` 在空闲状态下调用 Agent Loop 的强制压缩入口，完成后显示 token 变化。

### `src/coco_code/tui/app.py`

改动：

- `CoCoCodeApp.__init__` 创建并持有 `self.runtime`。
- provider 激活后设置 `self.runtime.context_window = effective_context_window(provider_cfg)`。
- `_run_agent_turn` 构造 `AgentLoop(..., runtime=self.runtime)`。
- `prompt_submitted` 先走 `dispatch_command`，已处理则返回。
- `handle_agent_event` 增加 compact 事件展示。
- `format_compact_notice` 统一自动、紧急、手动压缩文案。

### `src/coco_code/config.py`

改动：

- `ProviderConfig` 增加 `context_window: int = 0`。
- `_parse_provider` 读取可选整数 `context_window`，非整数或负数报 `ConfigError`。
- 新增 `effective_context_window(provider)`。
- 配置示例 `.coco-code/config.yaml.example` 增加字段注释。

### `.gitignore`

追加 `.coco-code/sessions/`。当前 `.mew*/` 已覆盖该目录，但显式追加能让行为更清楚。

## 模块交互

### 自动路径

```text
TUI submit user text
  -> AgentLoop.run
     -> conversation.add_user
     -> active_registry = registry_for_mode(...)
     -> estimate_tokens(runtime.usage_anchor, conversation.items(), runtime.anchor_item_len)
     -> manage_context(trigger=AUTO, tools=active_registry)
        -> layer1.offload_and_snip
        -> conversation.replace_items(layer1_items)
        -> re-estimate tokens
        -> if threshold reached and not tripped:
             -> emit BEFORE_AUTO
             -> layer2.auto_compact
             -> conversation.replace_items(summary + recovery + recent_tail)
             -> emit AFTER_AUTO
     -> provider.stream(conversation.items(), tools=active_registry)
     -> usage event updates runtime usage anchor
     -> tool calls execute
     -> ReadFile success updates recovery before add_tool_result
     -> conversation.add_tool_result
```

### 手动路径

```text
TUI input "/compact"
  -> dispatch_command handles it
  -> no conversation.add_user
  -> AgentLoop.run_force_compact or app-level helper acquires runtime.lock
  -> manage_context(trigger=MANUAL)
     -> layer2.force_compact
     -> conversation.replace_items(summary + recovery + recent_tail)
  -> TUI shows "已压缩，token 从 X 降至 Y"
```

### 紧急路径

```text
provider.stream returns PromptTooLongError
  -> current partial reply is not written to conversation
  -> if emergency_retried is false:
       -> emit BEFORE_EMERGENCY
       -> manage_context(trigger=EMERGENCY)
          -> layer1.offload_and_snip
          -> layer2.force_compact
          -> conversation.replace_items(...)
       -> reset usage_anchor and anchor_item_len
       -> re-estimate tokens
       -> if under context_window - 3000:
            retry provider.stream once
          else:
            surface unrecoverable context error
     else:
       surface original error
```

### 摘要请求自身过长

```text
summarize_once -> PromptTooLongError
  -> group_by_user_turn(items)
  -> retry 3 times, dropping oldest 1 group each time
  -> then retry by dropping ceil(remaining_groups * 0.2), at least 1
  -> success returns summary
  -> exhausted groups raises CompactError
```

## 文件组织

```text
src/coco_code/
├── compact/
│   ├── __init__.py          # 重导出 manage_context、TriggerKind、runtime state 类型
│   ├── constants.py         # 硬编码阈值常量
│   ├── manager.py           # manage_context、ManageInput、ManageOutput、TriggerKind
│   ├── layer1.py            # offload_and_snip、spill_single、build_preview_result
│   ├── layer2.py            # auto_compact、force_compact、run_summary、ptl_retry、pick_recent_tail
│   ├── recovery.py          # RecoveryState、FileReadRecord、恢复三段渲染
│   ├── state.py             # ContentReplacementState、CompactCircuitBreaker、SessionContext
│   ├── summary_prompt.py    # 摘要 prompt、会话序列化、summary 提取
│   └── token.py             # token 估算、usage 合并
├── agent/
│   ├── runtime.py           # SessionRuntime
│   ├── loop.py              # 接入 manage_context、紧急压缩、文件追踪、usage anchor
│   └── types.py             # CompactEvent / CompactPhase / AgentEventType.COMPACT
├── llm/
│   ├── __init__.py          # PromptTooLongError
│   ├── openai_provider.py   # usage + PTL 包装
│   └── anthropic_provider.py# usage + PTL 包装
├── tui/
│   ├── commands.py          # /exit /plan /do /compact 命令注册与分发
│   └── app.py               # runtime 持有、命令分发、compact notice 渲染
├── conversation.py          # replace_items
└── config.py                # context_window + effective_context_window

tests/
├── test_compact_layer1.py
├── test_compact_layer2.py
├── test_compact_manager.py
├── test_compact_recovery.py
├── test_compact_state.py
├── test_compact_summary_prompt.py
├── test_compact_token.py
├── test_agent_loop.py       # 扩展自动/紧急压缩、usage anchor、ReadFile recovery
├── test_conversation.py     # replace_items
├── test_config.py           # context_window
├── test_llm_events.py       # PTL 包装与 usage 映射
└── test_tui_app.py          # /compact、未知命令、现有命令回归
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 子包命名 | `coco_code.compact` | 与当前仓库包名一致，保留参考 plan 的职责边界。 |
| 会话目录 | `.coco-code/sessions/<session_id>/tool-results/` | 按用户提供的 spec 执行；当前 `.gitignore` 的 `.mew*/` 已覆盖，仍显式追加更清楚。 |
| 工具结果替换粒度 | 替换 `ToolResultItem.result` 为新的 `ToolResult` | 当前 conversation 结构没有 RoleTool；保持 tool_call_id 和顺序即可满足 provider 协议。 |
| 批次识别 | 根据 `AssistantToolCallItem(s)` 后续的 `ToolResultItem` 分组 | 与当前 AgentLoop 写入顺序一致，不需要改 conversation schema。 |
| 替换账本 | 保存 `tool_call_id -> ToolResult` | 预览必须逐字节稳定；保存对象比每轮重新生成字符串更可靠。 |
| 落盘格式 | JSON 保存完整 `ToolResult` 字段和 provider payload | 方便人工调试，也方便未来工具读取时还原。 |
| 锁策略 | runtime 级 turn 锁 + state 内部 asyncio.Lock | TUI 命令、Agent turn、紧急路径都在 asyncio 内运行，锁能保持账本、熔断和文件追踪一致。 |
| 摘要调用 | 复用当前 `Provider.stream(..., tools=None)` | 不引入第二套 provider API；明确不传工具。 |
| 摘要和恢复消息 | 合并为一条 user 消息 | 避免 Anthropic 连续 user 消息问题，也让边界提示更集中。 |
| 当前工具列表 | 从本轮 `ToolRegistry` 渲染，provider 请求也使用同一 registry | 当前 provider 接口接受 registry；复用同一对象即可保证工具集合一致。 |
| 近期原文切分 | 从尾部累计，并向前扩展避免孤立工具调用/结果 | 满足 spec 的“同时满足 10000 token 和 5 条”以及 provider 协议合法性。 |
| Usage 锚点 | 只由主对话路径更新，摘要请求不更新 | 摘要请求是内部维护动作，不代表用户任务上下文的常规请求。 |
| PTL 识别 | Provider 包装为统一 `PromptTooLongError` | Agent Loop 不依赖各 SDK 异常细节。 |
| 紧急压缩 | 同一 provider 请求最多重试一次 | 防止无限循环；若一次压缩后仍过长，应向用户暴露不可恢复错误。 |
| `/compact` 语义 | 命令路径，不写入 conversation，无条件摘要 | 按用户 spec；跳过自动阈值和熔断器。 |
| `context_window` | 只暴露这个配置项，其他阈值硬编码 | provider 窗口是用户必须能调整的变量；其他阈值作为产品策略常量控制测试矩阵。 |

## Spec 覆盖

| Spec 区域 | Plan 归属 |
|---|---|
| 第 1 层单条 / 聚合落盘、预览、账本冻结 | `compact/layer1.py` + `compact/state.py` |
| `.coco-code/sessions` 会话目录 | `SessionContext` + `.gitignore` |
| 近似 token 估算和 usage 锚点 | `compact/token.py` + Agent Loop usage 更新 |
| 自动摘要阈值和熔断 | `compact/manager.py` + `compact/layer2.py` + `CompactCircuitBreaker` |
| 摘要 prompt、禁工具、9 部分结构 | `compact/summary_prompt.py` |
| 近期原文和工具配对修正 | `compact/layer2.py::pick_recent_tail` |
| 恢复三段 | `compact/recovery.py` |
| `/compact` 和斜杠命令路由 | `tui/commands.py` + `tui/app.py` |
| `prompt_too_long` 紧急压缩 | `llm` provider 包装 + `agent/loop.py` |
| `context_window` 配置 | `config.py` + config example |
| 可观测事件和 TUI 状态提示 | `AgentEvent` compact 字段 + `tui/app.py` |
