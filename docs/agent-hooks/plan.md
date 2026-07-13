# Hook 生命周期挂钩系统 Plan

## 技术栈

- 语言：Python 3.12+
- TUI：Textual async-first + Rich
- 配置：PyYAML，通过 `yaml.safe_load` 解析
- HTTP 客户端：`httpx.AsyncClient`
- 异步进程：`asyncio.create_subprocess_shell` + `asyncio.wait_for`
- 模板：Python 标准库 `str.format_map`，只支持字段插值，不开放函数调用
- 测试：pytest；异步测试使用 `asyncio.run` 或 pytest async 能力；HTTP 行为用 fake client 或本地 async stub 覆盖

## 架构概览

本章拆成两层实现。

第一层是权限匹配器升级。当前 `coco_code.permission.rule` 只有字符串规则、工具名 glob 和目标 glob。计划新增统一 matcher 抽象，把 exact、glob、regex、not 四种匹配放到同一套实现中。权限规则继续保持 deny 优先、allow 次之、模式兜底的判定语义；只升级规则解析、匹配能力和错误可观测性。

第二层是 Hook 主体。新增 `coco_code.hook` 包，负责加载 YAML、校验规则、维护事件分派、执行四类动作和管理 `only_once` 状态。Hook 引擎作为可选依赖注入到 TUI 与 AgentLoop。TUI 负责会话级、用户提交级和通知类事件；AgentLoop 与工具执行路径负责轮次级、工具级和上下文压缩类事件。

核心模块：

- `coco_code.permission.matcher`：新增四类 matcher 和 `compile_matcher`。
- `coco_code.permission.rule`：改造 `Rule` 和 `parse_rule`，复用 matcher。
- `coco_code.hook.loader`：扫描 `<projectRoot>/.coco-code/hooks.yaml` 和 `~/.coco-code/hooks.yaml`，解析并校验规则。
- `coco_code.hook.engine`：按事件分派规则，处理条件、同步/异步执行、拦截和 prompt 注入。
- `coco_code.hook.executor`：执行 shell、prompt、http、subagent stub。
- `coco_code.hook.matcher`：按 payload 字段路径取值并求值 `all_of` / `any_of`。
- `coco_code.agent.loop` / `coco_code.agent.tools` / `coco_code.tools.executor`：接入 `PreUserMessage`、`PreToolUse`、`PostToolUse`、`Stop`、`PreCompact`、`PostCompact`。
- `coco_code.tui.app` / `coco_code.command`：接入 `SessionStart`、`SessionEnd`、`SessionResume`、`UserPromptSubmit`、`Notification` 和 `/hooks`。

## 核心数据结构

### Matcher

```python
class Matcher(Protocol):
    def match(self, value: str) -> bool: ...
```

实现类型：

- `ExactMatcher(value: str)`：整串相等。
- `GlobMatcher(pattern: str)`：复用现有 glob 语义，保留路径形态和命令形态差异。
- `RegexMatcher(src: str, compiled: Pattern[str])`：加载期编译，运行期复用。
- `NotMatcher(inner: Matcher)`：对 inner 结果取反。

工厂接口：

```python
def compile_matcher(pattern: str, *, path_like: bool = False) -> Matcher: ...
def compile_structured_matcher(raw: Mapping[str, Any], *, path_like: bool = False) -> Matcher: ...
```

`compile_matcher` 解析权限规则字符串前缀：`=`、`~`、`!`、无前缀。`compile_structured_matcher` 解析 Hook 条件中的 `{type, value}` 或 `{type: not, inner: ...}`。

### Permission Rule

```python
@dataclass(frozen=True)
class Rule:
    tool: str
    matcher: Matcher | None
    allow: bool
    raw_pattern: str = ""
```

`matcher is None` 表示只匹配工具名、不限制 target。`parse_rule` 返回规则或解析错误；`to_rule_set` 对错误写 stderr 并跳过，不影响其它规则。

### Hook Event

```python
class Event(StrEnum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"
```

`PreToolUse` 和 `UserPromptSubmit` 是 blocking events。它们不允许 async Hook，并且同步动作可以返回拦截结果。

### Hook Rule

```python
@dataclass(frozen=True)
class AtomCondition:
    field: str
    matcher: Matcher

@dataclass(frozen=True)
class Condition:
    mode: Literal["all_of", "any_of"]
    atoms: tuple[AtomCondition, ...]

@dataclass(frozen=True)
class HookRule:
    name: str
    event: Event
    action: HookAction
    condition: Condition | None = None
    only_once: bool = False
    async_mode: bool = False
    timeout_seconds: float = 30.0
    source: str = ""
    index: int = 0
```

`index` 是加载顺序，仅用于稳定排序和诊断，不暴露为用户可配置 priority。

### Actions

```python
@dataclass(frozen=True)
class ShellAction:
    command: str

@dataclass(frozen=True)
class PromptAction:
    text: str

@dataclass(frozen=True)
class HttpAction:
    url: str
    method: str = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str | None = None

@dataclass(frozen=True)
class SubagentAction:
    agent_name: str
    prompt: str

@dataclass(frozen=True)
class HookAction:
    type: Literal["shell", "prompt", "http", "subagent"]
    value: ShellAction | PromptAction | HttpAction | SubagentAction
```

### Dispatch Result

```python
@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)
```

`blocked` 只在 blocking events 下有效。`injected_prompts` 由调用方追加到 `SessionRuntime.pending_hook_reminders`，在下一次模型请求前取出。

### SessionRuntime 扩展

```python
@dataclass
class SessionRuntime:
    ...
    pending_hook_reminders: list[str] = field(default_factory=list)
    fired_hooks: set[str] = field(default_factory=set)
    hook_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
```

`pending_hook_reminders` 保存本轮待注入 reminder。`fired_hooks` 保存会话内 `only_once` 状态。`hook_tasks` 追踪 async Hook，退出或取消当前交互时可做 best-effort 清理。

## 核心接口

### Loader

```python
def default_hook_paths(project_root: Path, home: Path | None = None) -> tuple[Path, Path]: ...

def load_hooks(
    project_root: Path,
    *,
    home: Path | None = None,
    stderr: TextIO = sys.stderr,
) -> HookEngine: ...
```

加载顺序为项目级再用户级，保持参考 spec 的“后到者同名跳过”语义。每个存在的文件进入 sources；不存在不报错。顶层必须是 mapping 且 `hooks` 为 list，否则该文件报错并跳过。单条 Hook 校验失败只跳过该条。

校验规则：

- `name`、`event`、`action.type` 必填且类型正确。
- `event` 必须属于 11 个固定事件。
- `if` 顶层只能有 `all_of` 或 `any_of` 一个。
- `match` 必须是 exact、glob、regex、not 之一。
- regex 加载期编译。
- `async: true` 不能用于 `PreToolUse` 和 `UserPromptSubmit`。
- `timeout` 支持秒级字符串和数字，非法时该 Hook 跳过。
- 同名 Hook 后到者跳过并写 stderr。

### Engine

```python
class HookEngine:
    def __init__(self, rules: Sequence[HookRule], sources: Sequence[Path]) -> None: ...

    async def dispatch(
        self,
        event: Event,
        payload: Mapping[str, Any],
        runtime: SessionRuntime | None = None,
    ) -> DispatchResult: ...

    def rules(self) -> tuple[HookRule, ...]: ...
    def sources(self) -> tuple[Path, ...]: ...
```

dispatch 流程：

1. 只选择 event 匹配的 Hook。
2. 如果 `only_once` 且 name 已在 `runtime.fired_hooks` 中，跳过。
3. 求值条件；无条件视为命中。
4. async Hook 创建后台 task 并立即继续。
5. 同步 Hook 等待 action 完成。
6. action 失败写 stderr，主流程继续。
7. prompt action 的文本进入 `DispatchResult.injected_prompts`。
8. blocking event 中 shell/http 按约定返回 block 时，设置 `blocked` 并停止后续同事件规则。
9. Hook 成功执行后记录 `only_once`。

### Executor

```python
@dataclass
class ActionOutcome:
    blocked: bool = False
    reason: str = ""
    prompt: str = ""
    error: str | None = None

class HookExecutor:
    async def run(
        self,
        rule: HookRule,
        payload: Mapping[str, Any],
        *,
        blocking: bool,
    ) -> ActionOutcome: ...
```

Shell：

- 使用 `asyncio.create_subprocess_shell`。
- payload 用 `json.dumps(payload, sort_keys=True)` 序列化为单行 JSON，经 stdin 传入命令。
- timeout 后 kill 子进程，返回 Hook 失败。
- blocking 下 `returncode == 2` 表示拦截，原因取 `stderr` 或 `stdout`。
- `returncode == 0` 放行。
- 其它非零码为 Hook 失败但不拦截。

Prompt：

- 直接返回 `ActionOutcome(prompt=text)`。
- 不参与拦截。

HTTP：

- 默认 POST。
- `body is None` 时发送 payload JSON。
- `body` 存在时使用 `str.format_map` 从 payload 字段渲染。
- blocking 下 2xx 且 JSON body 为 `{"decision":"block","reason":"..."}` 才拦截。
- 网络错误、超时、JSON 解析失败为 Hook 失败但不拦截。

Subagent：

- 校验 `agent_name` 与 `prompt`。
- 执行时只写固定 stderr：`[hook subagent] not yet implemented, skipped: <name>`。
- 不报错、不拦截。

### Condition

```python
def get_by_path(payload: Mapping[str, Any], path: str) -> str: ...
def eval_condition(condition: Condition | None, payload: Mapping[str, Any]) -> bool: ...
```

字段路径用 `.` 分隔。不存在时返回空字符串。字典、list、bool、int 等非字符串值在匹配前转为稳定字符串；dict/list 优先 JSON 序列化，保证可测试。

## 模块设计

### `src/coco_code/permission/matcher.py`

职责：承载四种 matcher 和编译入口。现有 `_command_glob_to_regex` 与 `_path_glob_to_regex` 可从 `permission.rule` 迁入或复用，避免 Hook 与权限各写一套 glob。

测试：`tests/test_permission_rules.py` 或新增 `tests/test_permission_matcher.py` 覆盖 exact、glob、regex、not、嵌套 not、空串、转义、路径形态。

### `src/coco_code/permission/rule.py`

职责：把 `Rule.pattern: str` 改为 `Rule.matcher`，保留 `Rule.text()` 的可读输出。`parse_rule` 支持 `=value`、`~regex`、`!inner`、旧 glob 语法。

兼容：旧格式继续成功；规则解析失败向调用方返回错误，不让异常逃出配置加载。

### `src/coco_code/permission/settings.py`

职责：`to_rule_set` 接收 `stderr` 或使用默认 stderr，把失败规则和原因输出后跳过。`friendly_name`、`categorize`、`extract_target` 语义不变。

### `src/coco_code/hook/*`

新增包：

- `__init__.py`：导出 `Event`、`HookEngine`、`DispatchResult`、`load_hooks`。
- `event.py`：事件枚举、blocking event 集合、payload helper。
- `rule.py`：HookRule、Condition、Action 数据结构。
- `matcher.py`：字段路径取值和条件求值。
- `loader.py`：YAML 加载、校验、合并、错误输出。
- `executor.py`：四类动作执行器。
- `engine.py`：dispatch 主流程、async task 追踪、only_once 管理。

### `src/coco_code/agent/loop.py`

职责：接入轮次级、工具级和压缩级事件。

改动点：

- `AgentLoop.__init__` 增加 `hook_engine: HookEngine | None = None`。
- `_run_locked` 在每轮模型请求前触发 `PreUserMessage`，并把返回的 prompt 加入 runtime pending reminder。
- `_refresh_system_prompt` 或新的 prompt builder 注入点读取并清空 pending reminder，将 Hook reminder 放在 plan reminder 之后、项目指令之前或专门 Hook Reminder 区。
- `_auto_manage_context` 在 `manage_context` 前后触发 `PreCompact` / `PostCompact`，payload 包含 trigger 和 token。
- 自然停止前触发 `Stop`；取消和错误路径不触发。

### `src/coco_code/agent/tools.py`

职责：工具批执行过程触发 `PreToolUse` / `PostToolUse`。

可选设计：

- 将 `execute_tool_batches` 增加 `hook_engine` 和 runtime 参数。
- 在 `_execute_one` 中先触发 `PreToolUse`。
- 被 Hook 拦截时，构造 `ToolResult(ok=False, data={"hook_blocked": True, ...})`，跳过 `ToolExecutor.execute`，同时仍发送 `TOOL_STARTED` 和 `TOOL_RESULT` 相关事件。
- 真实工具执行后触发 `PostToolUse`，但不得修改结果。

如果为了减少函数参数扩散，也可以把 Hook 拦截放入 `ToolExecutor.execute`。但 `agent.tools` 更接近批处理和事件发射，能更清楚地区分 Hook 拦截、权限拒绝和真实工具结果。

### `src/coco_code/tools/executor.py`

职责：如果 `PreToolUse` 放在 `ToolExecutor`，则在权限检查之前调用 Hook；否则保持现有权限执行链，只补充 Hook 拦截结果 helper。无论选择哪条路径，权限检查顺序必须满足 spec：Hook 拦截早于权限引擎。

### `src/coco_code/tui/app.py`

职责：TUI 侧接入会话级、用户提交级、通知类事件。

改动点：

- `CoCoCodeApp.__init__` 增加 `hook_engine`。
- `on_mount` 在 MCP 和 Skill 初始化后、首条用户消息前触发 `SessionStart`。
- `submit_user_text` 或 `on_prompt_submitted` 对非 slash 用户消息先触发 `UserPromptSubmit`；被拦截时不写入 conversation，UI 显示 `[hook <name>] <reason>`，输入框保留或恢复文本。
- `clear_history` 前触发 `SessionEnd`，清理 runtime Hook once 集合和 pending reminders，再新会话触发 `SessionStart`。
- resume 切换旧会话前触发 `SessionEnd`，恢复完成后触发 `SessionResume`。
- 权限确认弹窗和 provider stream error 触发 `Notification`。
- 退出时触发 `SessionEnd`，并取消/等待 Hook 后台 task 的 best-effort 收尾。

### `src/coco_code/prompt.py`

职责：增加 Hook reminder 渲染入口。

设计：

- `build_system_prompt` 增加 `hook_reminders: str = ""` 可选参数。
- Hook reminder 作为独立标题区，如 `Hook Reminders:`，不进入 conversation history。
- `CoCoCodeApp.build_current_system_prompt` 从 runtime 读取并清空 pending reminders，或由 AgentLoop 在模型请求前构造一次性 prompt。

为了保证“一轮有效”，更推荐 AgentLoop 在模型请求前取出 pending reminders，传给 system prompt builder 的 runtime 视图，而不是让 `build_system_prompt` 自己读全局状态。

### `src/coco_code/command/*`

职责：新增 `/hooks`。

改动点：

- `CommandUI` Protocol 增加 `hook_rules()` 和 `hook_sources()`，或增加单个 `hooks_snapshot()`。
- `handlers.py` 新增 `handle_hooks`。
- `builtins.py` 注册 public command `/hooks`。
- 输出按 event 分组，flags 包含 `[once]`、`[async]`；无 Hook 输出 `No hooks loaded.`。

### `src/coco_code/cli.py`

职责：启动期加载 Hook。

流程：

```text
config.load()
permission.new_engine(root)
load_mcp_config(root)
load_hooks(root)
CoCoCodeApp(..., hook_engine=hook_engine)
```

Hook 加载失败不得抛出到 CLI 顶层；loader 自己写 stderr 并返回空 engine。

## 模块交互

```text
启动:
  cli.py
    ├─ permission.new_engine()
    ├─ hook.loader.load_hooks()
    └─ CoCoCodeApp(..., hook_engine)

用户提交:
  PromptSubmitted
    ├─ slash? 是 -> command dispatch
    └─ slash? 否 -> HookEngine.dispatch(UserPromptSubmit)
          ├─ blocked -> UI 显示原因, 不写 conversation
          └─ allowed -> conversation.add_user(), AgentLoop.run()

模型请求前:
  AgentLoop._run_locked()
    ├─ HookEngine.dispatch(PreUserMessage)
    ├─ auto_manage_context() 包含 PreCompact/PostCompact
    ├─ 注入 pending Hook reminders
    └─ provider.stream()

工具执行:
  execute_tool_batches()
    ├─ emit TOOL_STARTED
    ├─ HookEngine.dispatch(PreToolUse)
    │    ├─ blocked -> ToolResult(hook_blocked=True)
    │    └─ allowed -> ToolExecutor.execute()
    ├─ HookEngine.dispatch(PostToolUse)
    └─ conversation.add_tool_result()

结束:
  AgentLoop 自然停止 -> HookEngine.dispatch(Stop)
  clear/resume/quit -> HookEngine.dispatch(SessionEnd)
```

## 文件组织

```text
src/coco_code/
├── permission/
│   ├── matcher.py            # 新增: exact/glob/regex/not matcher
│   ├── rule.py               # 改造: parse_rule 与 Rule matcher
│   └── settings.py           # 改造: 规则解析错误 stderr 输出
├── hook/
│   ├── __init__.py           # 新增: 公共导出
│   ├── event.py              # 新增: 11 个事件和 payload helper
│   ├── rule.py               # 新增: HookRule/Condition/Action
│   ├── matcher.py            # 新增: 条件字段读取和求值
│   ├── loader.py             # 新增: hooks.yaml 加载与校验
│   ├── executor.py           # 新增: shell/prompt/http/subagent 动作
│   └── engine.py             # 新增: dispatch/only_once/async task
├── agent/
│   ├── runtime.py            # 改造: pending_hook_reminders/fired_hooks/hook_tasks
│   ├── loop.py               # 改造: 轮次/压缩/停止事件和 prompt 注入
│   └── tools.py              # 改造: PreToolUse/PostToolUse
├── command/
│   ├── builtins.py           # 改造: 注册 /hooks
│   ├── handlers.py           # 改造: handle_hooks
│   └── types.py              # 改造: CommandUI 增加 hook snapshot
├── tui/
│   └── app.py                # 改造: Hook engine wiring 和 TUI 事件
├── prompt.py                 # 改造: Hook reminder 区
└── cli.py                    # 改造: load_hooks 并注入 App

tests/
├── test_permission_rules.py  # 扩展: exact/regex/not/glob
├── test_hook_loader.py       # 新增
├── test_hook_matcher.py      # 新增
├── test_hook_executor.py     # 新增
├── test_hook_engine.py       # 新增
├── test_agent_hooks.py       # 新增或扩展 agent loop tests
├── test_tui_hooks.py         # 新增或扩展 TUI submit tests
└── test_command_builtins.py  # 扩展 /hooks
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 匹配语法 | `=` exact、`~` regex、`!` not、无前缀 glob | 向后兼容旧权限规则，新增能力直观 |
| 结构化 match | Hook 条件使用 `{type, value}` | YAML 可读性好，便于加载期校验 |
| Hook 配置路径 | 按 spec 使用 `.coco-code/hooks.yaml` | 与本章用户扩展路径保持一致，不混入 provider 配置 |
| 两层合并 | 项目级与用户级叠加，同名后到者跳过 | 不需要覆盖语义，避免 `only_once` key 冲突 |
| 事件枚举 | `StrEnum` | 与 YAML 字符串直接互转，日志可读 |
| Payload | `dict[str, Any]` | 11 个事件字段差异大，dict 更适合字段路径读取 |
| shell 输入 | payload JSON 走 stdin | 避免把复杂参数塞进环境变量或命令行，脚本端易解析 |
| shell 拦截 | blocking event 中 `exit code 2` | 明确区分“拒绝”和“Hook 自身失败” |
| HTTP 拦截 | 2xx + `decision=block` | 外部策略服务语义清晰，失败默认放行 |
| prompt 注入 | runtime pending reminder | 不污染会话历史，符合“一轮有效” |
| async Hook | 后台 task + stderr 失败日志 | 不阻塞主流程，失败隔离 |
| `only_once` | SessionRuntime 内存 set | 与会话生命周期一致，不做持久化 |
| subagent | 只校验和固定日志 | 满足本章占位要求，后续章节可替换 |
| `/hooks` | 普通 public slash command | 与现有命令系统一致，便于测试 |
| 失败处理 | stderr + 跳过或放行 | Hook 不能破坏主 Agent 流程 |

## Spec 覆盖

| Spec | Plan 归属 |
|---|---|
| F1-F5 权限匹配扩展 | `permission.matcher`、`permission.rule`、`permission.settings` |
| F6-F8 Hook 配置文件 | `hook.loader` |
| F9-F10 生命周期事件和 payload | `hook.event`、TUI/Agent 接入 |
| F11-F15 条件表达式 | `hook.matcher` + `permission.matcher` |
| F16-F26 四类动作 | `hook.executor` |
| F27 only_once | `SessionRuntime.fired_hooks` + `HookEngine` |
| F28 async 控制 | `hook.loader` 校验 + `HookEngine` 后台 task |
| F29 失败日志 | `HookEngine` / `HookExecutor` |
| F30-F33 集成点 | `cli.py`、`tui.app`、`agent.loop`、`agent.tools`、`prompt.py` |
| F34-F35 `/hooks` | `command.handlers`、`command.builtins`、`CommandUI` |
