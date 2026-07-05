# MCP 客户端 Plan

> 技术栈：Python 3.12+；使用官方 MCP Python SDK `mcp` 承载协议层，配合 `httpx.AsyncClient` 配置 Streamable HTTP headers/timeout。当前仓库包名为 `coco_code`，本章新增 `coco_code.mcp` 子包；provider 适配层和 permission 包源码不为 MCP 增加特殊分支。

## 架构概览

- **mcp 子包（新增）**：集中承载 MCP 客户端能力：两层配置读取与合并、`${VAR}` 展开、字段校验、stdio/Streamable HTTP 连接、initialize/list/call 会话流程、远端工具适配、连接缓存与关闭。该包依赖 `tools` 抽象、官方 MCP SDK、`httpx` 与标准库，不依赖 agent/tui/permission/llm/conversation。
- **CLI 装配（小改）**：`cli.py` 在解析普通 provider 配置、创建权限引擎后，加载 MCP 配置并把 `McpConfig` 传给 `CoCoCodeApp`。MCP 配置加载失败或 server 定义非法只产生 stderr 告警，不让 CLI 退出。
- **TUI 启动期装配（小改）**：`CoCoCodeApp` 持有 `McpManager`。在 `on_mount` 的第一阶段 `await manager.start()`，完成所有 server 的连接、握手和列工具，再把 MCP 工具注册进现有 `ToolRegistry`，最后才启用 provider 选择或输入框。这样对用户而言，进入可交互状态时工具集已经稳定。
- **tools 模块（小改）**：`Tool` 接口保持不变；`ToolSpec` 增加可选 `timeout_seconds` 字段，`ToolExecutor` 优先使用该字段作为外层执行超时。MCP 工具内部仍用 30 秒 `tools/call` 超时并返回 MCP 风格错误；外层超时只做兜底。
- **permission 包（零改实现）**：MCP 工具通过 `ToolSpec.read_only` 自然进入现有分类。未知工具名在 `friendly_name` 中原样返回，`categorize(..., read_only=True)` 归只读，非只读归执行类；`extract_target` 对未知工具返回非文件目标，黑名单与沙箱自然跳过。规则可直接写 `mcp__<server>__<tool>` 或 `mcp__<server>__*`。
- **agent / llm / provider（零改）**：Agent 仍通过 registry 获取工具，provider 仍只接收统一 Tool schema 和统一 ToolResult。MCP 来源不进入 provider 协议层。

数据流（启动）：

```text
cli.main()
  ├─ config.load()                         # 既有 provider 配置
  ├─ permission.new_engine(root)            # 既有权限引擎
  ├─ mcp.load_config(root)                  # 新：两层 mcp_servers 配置
  └─ CoCoCodeApp(..., mcp_config)
       └─ on_mount:
            ├─ create_default_registry()    # 6 个内置工具
            ├─ await McpManager.start()     # 每 server 30s，失败隔离
            ├─ registry.register(mcp_tool)  # 注册成功工具
            └─ 启用 provider/input
```

数据流（调用）：

```text
AgentLoop / ToolExecutor
  └─ registry.get("mcp__github__create_issue")
       └─ McpTool.run(params, context)
            ├─ asyncio.timeout(30s)
            ├─ session.call_tool(remote_name, arguments=params)
            ├─ 拼接 TextContent.text
            ├─ 丢弃非 text 内容块并 stderr 告警
            └─ ToolResult(ok=not result.is_error, summary=text, error=...)
```

## 核心数据结构

### McpConfig / ServerConfig

```python
from dataclasses import dataclass, field
from typing import Literal

ServerType = Literal["stdio", "http"]

@dataclass(frozen=True)
class McpConfig:
    servers: dict[str, "ServerConfig"] = field(default_factory=dict)

@dataclass(frozen=True)
class ServerConfig:
    name: str
    type: ServerType
    command: str = ""              # stdio required
    args: tuple[str, ...] = ()      # stdio optional
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                  # http required
    headers: dict[str, str] = field(default_factory=dict)
```

说明：`ServerConfig` 是配置加载后的归一化结果，已经完成两层合并、`${VAR}` 展开和字段校验。非法 server 不进入 `McpConfig.servers`。

### ManagedSession

```python
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

@dataclass
class ManagedSession:
    server_name: str
    session: Any              # 实际为 mcp.ClientSession；测试中可替换为 stub
    stack: AsyncExitStack     # 持有 stdio/http transport、ClientSession、httpx client 的 async context
```

说明：Python SDK 的 stdio/http transport 和 `ClientSession` 都通过 async context 管理。`AsyncExitStack` 让每个 server 的生命周期可以统一关闭；启动失败时也能关闭已经进入的上下文。

### McpManager

```python
class McpManager:
    def __init__(self, config: McpConfig, version: str, *, stderr: TextIO = sys.stderr) -> None: ...

    async def start(self) -> None: ...
    def tools(self) -> list[Tool]: ...
    async def close(self) -> None: ...
```

字段：
- `_config: McpConfig`：已校验配置。
- `_sessions: dict[str, ManagedSession]`：成功连接的 server。
- `_tools: list[McpTool]`：已适配好的远端工具。
- `_started: bool` / `_closed: bool`：防止重复启动或重复关闭。
- `_stderr: TextIO`：统一告警出口，测试可注入 `io.StringIO`。

### McpTool

```python
@dataclass
class McpTool:
    full_name: str                 # mcp__<server>__<tool>
    server_name: str
    remote_name: str               # server 原始工具名
    description: str
    parameters_schema: dict[str, Any]
    read_only: bool
    caller: McpCaller
    stderr: TextIO = sys.stderr
```

`McpTool` 实现现有 `Tool` 协议：

```python
@property
def spec(self) -> ToolSpec: ...

async def run(self, params: ToolParams, context: ToolContext) -> ToolResult: ...
```

### McpCaller

```python
class McpCaller(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...
```

说明：生产环境中 `caller` 是 SDK `ClientSession`；单元测试中注入 fake caller，避免测试依赖真实子进程或网络。

## 核心接口

### `coco_code.mcp.config`

```python
def default_mcp_config_paths(root: Path) -> tuple[Path, Path]: ...

def load_config(root: Path, *, stderr: TextIO = sys.stderr) -> McpConfig: ...

def expand_vars(value: str, *, server_name: str, stderr: TextIO) -> str: ...
```

路径决策：本仓库落地为两个独立 MCP 配置文件：

```text
~/.coco-code/mcp.yaml
<root>/.coco-code/mcp.yaml
```

两者都使用顶层 `mcp_servers` map。选择独立 `mcp.yaml` 是为了保持 MCP 的“配置非法只跳过并告警”语义，不改变现有 `config.yaml` 对 provider 配置的强校验/启动失败行为。仍然只合并用户级和项目级两层，不读取 `.coco-code/config.local.yaml` 或任何本地层。

配置示例：

```yaml
mcp_servers:
  github:
    type: http
    url: https://example.com/mcp
    headers:
      Authorization: Bearer ${GITHUB_TOKEN}
  local_math:
    type: stdio
    command: python
    args: ["-m", "examples.math_server"]
    env:
      API_KEY: ${LOCAL_MCP_API_KEY}
```

### `coco_code.mcp.manager`

```python
STARTUP_TIMEOUT_SECONDS = 30.0
CLOSE_TIMEOUT_SECONDS = 5.0

class McpManager:
    async def start(self) -> None:
        """并发启动所有 server；单 server 失败只告警并跳过。"""

    def tools(self) -> list[Tool]:
        """返回按 server 名、远端工具名稳定排序的工具。"""

    async def close(self) -> None:
        """并发关闭所有 ManagedSession，总超时 5 秒。"""
```

内部辅助接口：

```python
async def connect_server(config: ServerConfig, version: str, stderr: TextIO) -> ManagedSession: ...
async def connect_stdio(config: ServerConfig, version: str, stderr: TextIO) -> ManagedSession: ...
async def connect_http(config: ServerConfig, version: str, stderr: TextIO) -> ManagedSession: ...
def merge_env(extra: Mapping[str, str]) -> dict[str, str]: ...
```

### `coco_code.mcp.tool`

```python
CALL_TIMEOUT_SECONDS = 30.0
OUTER_EXECUTOR_TIMEOUT_SECONDS = 31.0
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

def adapt_tool(server_name: str, remote_tool: Any, caller: McpCaller, *, stderr: TextIO) -> McpTool | None: ...

def tool_full_name(server_name: str, remote_name: str) -> str: ...

def normalize_input_schema(raw_schema: Any) -> dict[str, Any]: ...

def remote_read_only(remote_tool: Any) -> bool: ...
```

`adapt_tool` 同时兼容 SDK 模型字段的 snake_case / camelCase 形态，例如 `input_schema` 与 `inputSchema`、`read_only_hint` 与 `readOnlyHint`。如果 SDK 版本只暴露其中一种，代码路径仍稳定。

### `tools` 小改接口

```python
@dataclass(frozen=True)
class ToolSpec:
    ...
    timeout_seconds: float | None = None
```

`ToolExecutor.execute` 的外层等待改为：

```python
timeout = spec.timeout_seconds or context.timeout_seconds
result = await asyncio.wait_for(tool.run(...), timeout=timeout)
```

MCP 工具的 `ToolSpec.timeout_seconds` 设置为 `31.0`，使 `McpTool.run` 内部 30 秒超时先返回结构化 MCP 错误；31 秒只是兜底，避免 SDK/transport 异常卡住。

## 模块设计

### `src/coco_code/mcp/config.py`

**职责：** 读取两层 MCP YAML、合并、展开变量、校验 server 定义。

**关键实现：**
- `load_file(path)`：文件不存在返回 `{}`；YAML 解析失败、顶层非 map、`mcp_servers` 非 map 时返回空并 stderr 告警，不抛给 CLI。
- `merge_servers(user, project)`：先复制用户级，再用项目级同名 server 完整覆盖；不做字段级合并。
- `expand_vars`：正则 `\$\{([A-Za-z_][A-Za-z0-9_]*)\}`。只作用于 `env` 和 `headers` 的值；未定义变量替换为空字符串，并输出 `[mcp] warn: server <name> references undefined env var ${VAR}`，不输出任何实际值。
- `validate_server(name, raw)`：要求 `type` 为 `stdio` 或 `http`；`stdio.command` 必填字符串；`stdio.args` 必须是字符串数组；`stdio.env` 必须是字符串 map；`http.url` 必填字符串；`http.headers` 必须是字符串 map。非法时跳过该 server 并告警。
- `redact_for_log`：只输出字段名、server 名和错误原因，不输出 env/header 值。

### `src/coco_code/mcp/manager.py`

**职责：** 启动 server、建立 SDK 会话、列工具、缓存连接、关闭连接。

**关键实现：**
- `start()` 用 `asyncio.gather(..., return_exceptions=True)` 并发启动每个 server。每个 `_start_one` 外层包 `asyncio.timeout(30)`，确保连接 + initialize + `list_tools` 总时长受限。
- stdio 连接使用官方 SDK：`StdioServerParameters(command=..., args=..., env=merge_env(...))`，`stdio_client(params)`，`ClientSession(read, write)`，随后 `await session.initialize()` 和 `await session.list_tools()`。
- HTTP 连接使用官方 SDK当前推荐方式：创建 `httpx.AsyncClient(headers=server.headers, timeout=httpx.Timeout(30.0), follow_redirects=True)`，再传给 `streamable_http_client(url=server.url, http_client=http_client)`，随后进入 `ClientSession` 并 initialize/list_tools。`httpx.AsyncClient` 由 `AsyncExitStack` 托管关闭。
- `list_tools` 成功后逐个调用 `adapt_tool`。非法工具名、重复工具名只跳过对应工具并告警；同一 server 的其他工具继续注册。
- `_tools` 排序键为 `(server_name, remote_name)`，保证 provider 看到的工具列表稳定。
- `close()` 并发关闭每个 session 的 `AsyncExitStack`，外层 `asyncio.timeout(5)`；超时后告警并返回，不阻塞程序退出。

### `src/coco_code/mcp/tool.py`

**职责：** 把 MCP 远端工具包装成现有 `Tool`。

**关键实现：**
- `tool_full_name("github", "create_issue")` 生成 `mcp__github__create_issue`。
- 拼接后的名称必须匹配 `^[A-Za-z0-9_-]+$`；否则 `adapt_tool` 返回 `None` 并告警。
- `description` 优先用远端描述；为空时兜底为 `MCP tool <tool> from server <server>`。
- `parameters_schema` 透传远端 `inputSchema/input_schema`；无法转成 dict 时兜底为 `{"type": "object", "properties": {}}`。
- `read_only` 只在远端 `annotations.readOnlyHint == true` 或 `annotations.read_only_hint == true` 时为 True；其他情况一律 False。
- `ToolSpec.confirmation`：只读 MCP 工具为 `ConfirmationPolicy.NEVER`；非只读 MCP 工具为 `ConfirmationPolicy.REQUIRED`，作为无 permission engine 时的安全兜底。有 permission engine 时仍由规则/模式/人在回路决定。
- `ToolSpec.category` 使用 `ToolCategory.GENERAL`；权限分类依赖 `read_only` 和未知工具默认执行类，不依赖 category。
- `run()` 内部用 `asyncio.timeout(30)` 包裹 `caller.call_tool(remote_name, params or None)`。
- 成功结果：遍历 `result.content`，只收集 `TextContent.text` 或等价 `type == "text"` 且有 `text` 字段的块；文本按顺序用换行拼接。
- 非 text 块：计数并通过包级 `set`/`Lock` 对每个 `full_name` 只告警一次，避免刷屏。
- `result.is_error` 为 True 时返回 `ToolResult(ok=False, error=text or "MCP tool returned an error.")`；否则 `ok=True`。
- SDK 异常、连接断开、协议错误、超时都转换为 `ToolResult(ok=False, summary="MCP tool call failed: ...", error=...)`，不抛出到 Agent Loop。

### `src/coco_code/tools/base.py` / `executor.py`

**职责：** 支持 per-tool 外层超时。

**关键实现：**
- `ToolSpec` 增加 `timeout_seconds: float | None = None`，默认不改变内置工具行为。
- `ToolExecutor.execute` 使用 `spec.timeout_seconds or context.timeout_seconds`。
- 现有内置工具不设置该字段，仍使用 `ToolContext.timeout_seconds` 默认 10 秒。
- MCP 工具设置 31 秒，确保内部 30 秒超时能按 spec 回灌 MCP 错误。

### `src/coco_code/cli.py`

**职责：** 加载 MCP 配置并传入 App。

**关键实现：**
- `root = Path.cwd().resolve()` 之后调用 `mcp_config = load_mcp_config(root)`。
- `CoCoCodeApp(..., mcp_config=mcp_config)`。
- MCP 配置加载函数不抛 `ConfigError`，因此不会改变 provider 配置失败时退出、MCP 配置失败时降级的边界。

### `src/coco_code/tui/app.py`

**职责：** 在 Textual 事件循环内启动和关闭 MCP Manager，并注册工具。

**关键实现：**
- `CoCoCodeApp.__init__` 新增 `mcp_config: McpConfig | None = None`、`mcp_manager: McpManager | None = None` 参数，测试可注入已构造 manager 或空配置。
- `on_mount` 改为 async：先 `await self.start_mcp()`，再按现有逻辑激活单 provider 或启用 provider 选择。
- `start_mcp()`：若配置为空直接返回；否则构造 `McpManager(mcp_config, __version__)` 并 `await start()`；把 `manager.tools()` 逐个 `registry.register`。注册异常只告警并跳过，不影响其他工具。
- 启动期间输入框保持 disabled，history 可写入简短 Notice，如 `Loading MCP tools...` 和失败摘要。
- `request_quit` / `action_quit` / 退出清理路径确保调用 `await mcp_manager.close()`；若正在 streaming，先取消当前任务，再关闭 MCP。

### `pyproject.toml`

**职责：** 声明运行时依赖。

**新增依赖：**
- `mcp>=1.12.4`：官方 MCP Python SDK。
- `httpx>=0.27.0`：显式使用 `httpx.AsyncClient` 配置 Streamable HTTP headers/timeout；即使 SDK 间接依赖，也作为直接依赖声明。

## 模块交互

```text
配置阶段
  cli.py
    ├─ config.load()                         # 现有 provider 配置，强校验
    ├─ permission.new_engine(root)            # 现有权限配置
    ├─ mcp.config.load_config(root)           # 新 MCP 配置，降级告警
    └─ CoCoCodeApp(config, permission_engine, mcp_config)

TUI 启动阶段
  CoCoCodeApp.on_mount()
    ├─ await start_mcp()
    │    ├─ McpManager.start()
    │    ├─ connect stdio/http server
    │    ├─ initialize + list_tools
    │    └─ adapt_tool -> McpTool
    ├─ registry.register(McpTool...)
    └─ activate_provider / enable input

工具调用阶段
  AgentLoop -> ToolExecutor.execute(call, permission_mode)
    ├─ registry.get(call.name).spec
    ├─ permission_engine.check(mode, call, spec)
    │    ├─ MCP read_only=True  -> Category.READ -> default allow
    │    └─ MCP read_only=False -> Category.EXEC -> default/acceptEdits ask
    ├─ confirm_permission_call if Ask
    └─ McpTool.run(params, context)
         └─ ClientSession.call_tool(remote_name, params)

退出阶段
  CoCoCodeApp.action_quit()
    ├─ cancel current stream task if any
    ├─ await McpManager.close() with 5s cap
    └─ exit Textual app
```

依赖方向：

```text
cli -> mcp.config
app -> mcp.manager -> mcp.tool -> tools.base
mcp.manager -> official mcp SDK + httpx
ToolExecutor -> ToolSpec.timeout_seconds
permission / llm / provider / conversation 不依赖 mcp
```

## 文件组织

```text
src/coco_code/
├── mcp/
│   ├── __init__.py        — 新：导出 McpConfig、ServerConfig、McpManager、load_config
│   ├── config.py          — 新：两层 YAML、mcp_servers 合并、${VAR} 展开、字段校验、stderr 告警
│   ├── manager.py         — 新：McpManager、ManagedSession、stdio/http 连接、startup/close timeout
│   └── tool.py            — 新：McpTool、McpCaller、adapt_tool、schema/readOnly/content 映射
├── tools/
│   ├── base.py            — 改：ToolSpec 增加 timeout_seconds
│   └── executor.py        — 改：外层执行超时优先使用 spec.timeout_seconds
├── tui/
│   └── app.py             — 改：持有 mcp_config/manager；on_mount 启动 MCP；退出关闭 MCP
├── cli.py                 — 改：加载 MCP 配置并传入 CoCoCodeApp
└── ...                    — permission / llm / provider / agent 不做 MCP 特殊改动

tests/
├── test_mcp_config.py     — 新：两层合并、变量展开、字段校验、非法 YAML 降级、敏感值不输出
├── test_mcp_tool.py       — 新：命名、schema、readOnly、成功/远端错误/异常/超时/非 text 块
├── test_mcp_manager.py    — 新：启动成功、单 server 失败隔离、30s 超时、稳定排序、5s close
├── test_tui_mcp.py        — 新/改：on_mount 注册 MCP 工具、注册冲突跳过、退出 close
├── test_tools_executor.py — 改：覆盖 ToolSpec.timeout_seconds 优先生效
└── test_permission_engine.py / test_permission_rules.py
    — 补：mcp__server__tool 精确与 glob 规则、readOnly 分类、黑名单/沙箱不误拦

docs/
└── mcp-servers.example.yaml — 新：用户级/项目级 MCP 配置示例，密钥只用 ${VAR}

pyproject.toml             — 改：新增 mcp、httpx 依赖
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| SDK | 官方 MCP Python SDK `mcp` | 对齐当前 Python 仓库；SDK 负责 stdio/http transport、ClientSession、initialize/list/call |
| HTTP headers | `httpx.AsyncClient(headers=..., timeout=...)` 传给 `streamable_http_client` | 当前 SDK 文档推荐方式；新版不直接在 `streamable_http_client` 上传 headers/timeout |
| MCP 配置文件 | `~/.coco-code/mcp.yaml` + `<root>/.coco-code/mcp.yaml` | 保持两层配置；独立文件允许 MCP YAML 非法时降级告警，不改变 provider config 的强校验 |
| 配置键 | 顶层 `mcp_servers` map | 对齐 spec 与附件；每个 key 是 server 名 |
| 合并语义 | 项目级同名 server 完整覆盖用户级 | 避免字段级半合并产生畸形 server |
| 类型判断 | 显式 `type: stdio` / `type: http` | 不靠字段嗅探，错误更清晰，后续扩展更稳 |
| 变量展开 | 仅 `env` / `headers` 的值展开 `${VAR}` | 凭据可来自宿主环境；command/args/name 不受环境隐式影响 |
| 未定义变量 | 展开为空字符串 + stderr 告警 | 不替 server 判断凭据是否必需；避免启动硬失败 |
| 启动位置 | TUI `on_mount` 中、用户可交互前完成 | SDK 会话必须在 Textual 事件循环内创建和使用；同时保证 Agent 开始前工具集稳定 |
| 启动并发 | 每 server 一个 task，单 server 30s | 失败隔离；多个 server 不串行拖慢总启动 |
| 工具集热加载 | 不做 | spec 明确本章工具集启动后稳定 |
| 工具命名 | `mcp__<server>__<tool>` + `[A-Za-z0-9_-]` 校验 | 避免冲突；权限规则和 UI 可追溯来源；满足 provider 工具名限制 |
| 重复工具名 | 同一 full_name 后者跳过并告警 | 保留已注册工具，降低意外覆盖风险 |
| readOnly 映射 | 只信 `annotations.readOnlyHint == true` | 安全默认：缺失或非法都按有副作用处理 |
| 非只读确认策略 | `ConfirmationPolicy.REQUIRED` | 有 permission engine 时由权限系统处理；无 permission engine 时仍有 legacy confirm 兜底 |
| MCP 调用超时 | 内部 30s，ToolSpec 外层 31s | 内部先生成 MCP 专属错误结果；外层防 SDK 卡死 |
| 非 text 内容 | 丢弃 + 每工具一次 stderr 告警 | 当前模型回灌只支持文本；不伪造不可表达内容 |
| 错误处理 | SDK/协议/连接/超时异常转 ToolResult(ok=False) | 复用 Agent Loop 不中断契约，让模型后续轮次调整 |
| 关闭 | 每 session 的 AsyncExitStack 并发关闭，总 5s | stdio 子进程、HTTP client、ClientSession 统一释放；单 server 卡住不拖死退出 |
| 权限接入 | permission 包零改，补测试 | 现有 unknown-friendly-name 和 read_only 分类已经足够承载 MCP |
| provider 接入 | 零改动 | provider 只关心 Tool schema 与 ToolResult payload；MCP 来源透明 |
| 测试策略 | config/tool 用纯单元测试，manager 用 fake connector + 少量 SDK fake server | 大部分行为不依赖网络；避免测试不稳定，必要处覆盖 SDK 接入边界 |

## Spec 覆盖

| Spec | Plan 归属 |
|---|---|
| F1-F3 配置、类型校验、变量展开 | `mcp/config.py` |
| F4 stdio 传输 | `mcp/manager.py::connect_stdio` |
| F5 Streamable HTTP | `mcp/manager.py::connect_http` + `httpx.AsyncClient` |
| F6 会话与 JSON-RPC | 官方 SDK `ClientSession.initialize/list_tools/call_tool`，Manager 负责错误转换 |
| F7-F9 工具发现、命名、调用适配 | `mcp/tool.py` + Manager 注册 |
| F10-F12 启动/调用/关闭超时与生命周期 | `McpManager.start`、`McpTool.run`、`McpManager.close` |
| F13 权限复用 | 现有 permission 行为 + 补充测试 |