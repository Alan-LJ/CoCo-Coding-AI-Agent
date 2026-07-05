# MCP 客户端 Tasks

> 包名：`coco_code`（Python 3.12+）。源码位于 `src/coco_code/`。本阶段只写任务拆解，不开始实现；四份文档全部通过后再按本任务表编码。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 改 | `pyproject.toml` | 新增运行时依赖 `mcp>=1.12.4`、`httpx>=0.27.0` |
| 新建 | `src/coco_code/mcp/__init__.py` | MCP 子包门面：导出 `McpConfig`、`ServerConfig`、`McpManager`、`load_config` |
| 新建 | `src/coco_code/mcp/config.py` | 两层 MCP YAML、`mcp_servers` 合并、`${VAR}` 展开、字段校验、stderr 告警 |
| 新建 | `src/coco_code/mcp/tool.py` | `McpTool`、`McpCaller`、工具命名、schema/readOnly 映射、调用结果转换 |
| 新建 | `src/coco_code/mcp/manager.py` | `McpManager`、`ManagedSession`、stdio/http 连接、启动/关闭超时、工具发现 |
| 改 | `src/coco_code/tools/base.py` | `ToolSpec` 增加 `timeout_seconds` 可选字段 |
| 改 | `src/coco_code/tools/executor.py` | 工具执行外层超时优先使用 `ToolSpec.timeout_seconds` |
| 改 | `src/coco_code/cli.py` | 加载 MCP 配置并传入 `CoCoCodeApp` |
| 改 | `src/coco_code/tui/app.py` | 启动期创建/启动/关闭 `McpManager`，注册 MCP 工具 |
| 新建 | `docs/mcp-servers.example.yaml` | MCP server 配置示例，只使用 `${VAR}` 表示凭据 |
| 新建 | `tests/test_mcp_config.py` | 配置合并、变量展开、字段校验、降级与敏感值保护测试 |
| 新建 | `tests/test_mcp_tool.py` | 工具适配、命名、schema、readOnly、调用成功/错误/超时/非 text 块测试 |
| 新建 | `tests/test_mcp_manager.py` | manager 启动、失败隔离、超时、排序、关闭测试 |
| 新建 | `tests/test_tui_mcp.py` | TUI 启动注册 MCP 工具、冲突跳过、退出关闭测试 |
| 改 | `tests/test_tools_executor.py` | 覆盖 per-tool timeout 优先生效 |
| 改 | `tests/test_permission_engine.py` / `tests/test_permission_rules.py` | 覆盖 MCP 命名规则、readOnly 分类、黑名单/沙箱不误拦 |

---

## T1: 添加 MCP SDK 与 HTTP 依赖

**文件：** `pyproject.toml`、锁文件（如后续工具生成）
**依赖：** 无
**步骤：**
1. 在 `[project].dependencies` 中追加 `"mcp>=1.12.4"`。
2. 在同一列表追加 `"httpx>=0.27.0"`，因为 `streamable_http_client` 的 headers/timeout 通过显式 `httpx.AsyncClient` 配置。
3. 如使用 `uv`，运行 `uv sync` 更新环境和锁文件；若本地使用 pip，则运行 `python -m pip install -e .`。
4. 用 Python 试导入：
   ```python
   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client
   from mcp.client.streamable_http import streamable_http_client
   import httpx
   ```

**验证：** `python -c "from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; from mcp.client.streamable_http import streamable_http_client; import httpx; print('ok')"` 输出 `ok`。

## T2: 建立 MCP 子包门面

**文件：** `src/coco_code/mcp/__init__.py`
**依赖：** 无
**步骤：**
1. 新建 `src/coco_code/mcp/` 目录。
2. 新建 `__init__.py`，先导出后续会实现的公共符号。
3. 初始导出目标为：`McpConfig`、`ServerConfig`、`load_config`、`McpManager`。
4. 为避免循环导入，`McpManager` 的导出在 `manager.py` 完成后补齐。

**验证：** 在 T3 完成前允许导入失败；T3 后运行 `python -c "from coco_code.mcp import McpConfig, ServerConfig, load_config; print('ok')"`。

## T3: 实现 MCP 配置数据结构与路径

**文件：** `src/coco_code/mcp/config.py`、`src/coco_code/mcp/__init__.py`、`tests/test_mcp_config.py`
**依赖：** T2
**步骤：**
1. 定义 `ServerType = Literal["stdio", "http"]`。
2. 定义 `@dataclass(frozen=True) class ServerConfig`，字段与 plan 保持一致：`name`、`type`、`command`、`args`、`env`、`url`、`headers`。
3. 定义 `@dataclass(frozen=True) class McpConfig`，字段 `servers: dict[str, ServerConfig]`。
4. 实现 `default_mcp_config_paths(root: Path) -> tuple[Path, Path]`，返回 `Path.home() / ".coco-code" / "mcp.yaml"` 与 `root / ".coco-code" / "mcp.yaml"`。
5. 在 `__init__.py` 导出 `McpConfig`、`ServerConfig`、`load_config`。

**验证：** `pytest tests/test_mcp_config.py -q -k "missing or paths"` 覆盖：两层文件缺失时 `McpConfig.servers == {}`；路径函数返回用户级和项目级两个路径。

## T4: 实现 MCP YAML 加载与两层合并

**文件：** `src/coco_code/mcp/config.py`、`tests/test_mcp_config.py`
**依赖：** T3
**步骤：**
1. 实现内部 `load_file(path, stderr)`：文件缺失返回 `{}`。
2. `yaml.safe_load` 失败、IO 失败、顶层非 map、`mcp_servers` 非 map 时，向 stderr 输出 `[mcp] warn: ...`，返回 `{}`。
3. 实现 `merge_servers(user, project)`：先复制用户级，再用项目级完整覆盖同名 server。
4. `load_config(root, stderr=sys.stderr)` 串起两层读取和合并，但先暂不做完整字段校验。
5. 所有告警不得打印 env/header 的实际值。

**验证：** `pytest tests/test_mcp_config.py -q -k "merge or invalid_yaml"` 覆盖：用户级独有保留、项目级独有保留、同名项目级完整覆盖；非法 YAML 只告警并跳过该层。

## T5: 实现 `${VAR}` 展开与字段校验

**文件：** `src/coco_code/mcp/config.py`、`tests/test_mcp_config.py`
**依赖：** T4
**步骤：**
1. 实现 `expand_vars(value, server_name, stderr)`，正则为 `\$\{([A-Za-z_][A-Za-z0-9_]*)\}`。
2. 仅对 `env` 和 `headers` 的值做展开；未定义变量替换为空字符串并告警。
3. 实现 `validate_server(name, raw, stderr) -> ServerConfig | None`。
4. 校验规则：`type` 必须是 `stdio` 或 `http`；`stdio.command` 必填字符串；`stdio.args` 是字符串数组；`stdio.env` 是字符串 map；`http.url` 必填字符串；`http.headers` 是字符串 map。
5. 非法 server 跳过并告警，其他 server 继续保留。
6. `command`、`args`、server 名、工具名不做环境变量展开。

**验证：** `pytest tests/test_mcp_config.py -q` 覆盖：变量已定义/未定义、只展开 env/header 值、不展开 command/args、非法 server 被跳过且不影响合法 server、告警不包含 token 实际值。

## T6: 增加 per-tool 外层超时

**文件：** `src/coco_code/tools/base.py`、`src/coco_code/tools/executor.py`、`tests/test_tools_executor.py`
**依赖：** 无
**步骤：**
1. 在 `ToolSpec` dataclass 末尾增加 `timeout_seconds: float | None = None`，保证内置工具构造不需要改。
2. 在 `ToolExecutor.execute` 中把当前 `self._context.timeout_seconds` 改为：`timeout = spec.timeout_seconds or self._context.timeout_seconds`。
3. `asyncio.wait_for(tool.run(...), timeout=timeout)` 使用新的局部变量。
4. 新增或扩展测试：构造 fake tool 的 spec 设置很短 timeout，`ToolContext.timeout_seconds` 设置更长，断言按 spec timeout 触发。
5. 保留既有内置工具默认行为测试。

**验证：** `pytest tests/test_tools_executor.py -q` 通过，并新增用例能证明 `ToolSpec.timeout_seconds` 优先。

## T7: 实现 MCP 工具命名与适配

**文件：** `src/coco_code/mcp/tool.py`、`tests/test_mcp_tool.py`
**依赖：** T6
**步骤：**
1. 定义 `CALL_TIMEOUT_SECONDS = 30.0`、`OUTER_EXECUTOR_TIMEOUT_SECONDS = 31.0`、`TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")`。
2. 定义 `McpCaller(Protocol)`，包含 `async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any`。
3. 实现 `tool_full_name(server_name, remote_name)`，返回 `mcp__<server>__<tool>`。
4. 实现 `normalize_input_schema(raw_schema)`：dict 透传浅拷贝；不可用时兜底 `{"type": "object", "properties": {}}`。
5. 实现 `remote_read_only(remote_tool)`，兼容 `annotations.readOnlyHint` 与 `annotations.read_only_hint`，只有显式 True 才返回 True。
6. 实现 `adapt_tool(server_name, remote_tool, caller, stderr)`：生成 full name、校验合法字符、描述兜底、schema 透传、readOnly 映射，非法名称返回 `None` 并告警。
7. `McpTool.spec` 返回 `ToolSpec`：name 为 full name；confirmation 只读为 `NEVER`，非只读为 `REQUIRED`；category 为 `GENERAL`；read_only/destructive/timeout_seconds 按 plan 设置。

**验证：** `pytest tests/test_mcp_tool.py -q -k "adapt or schema or read_only or name"` 覆盖：合法命名、非法字符跳过、描述兜底、schema 兜底/透传、readOnly 缺失默认 False、readOnlyHint True 映射 True。

## T8: 实现 MCP 工具调用结果转换

**文件：** `src/coco_code/mcp/tool.py`、`tests/test_mcp_tool.py`
**依赖：** T7
**步骤：**
1. 实现 `McpTool.run(params, context)`。
2. 内部使用 `asyncio.timeout(CALL_TIMEOUT_SECONDS)` 包裹 `caller.call_tool(self.remote_name, params or None)`。
3. 遍历 `result.content`，只收集 `TextContent.text` 或 `type == "text"` 且有 `text` 的块。
4. 非 text 块丢弃，并用包级 set 或 lock 对同一 `full_name` 只告警一次。
5. `result.is_error` 为 True 时返回 `ToolResult(ok=False, error=文本或兜底错误)`。
6. 成功时返回 `ToolResult(ok=True, summary=文本摘要, data={"content": text}, error=None, elapsed_ms=...)`。
7. SDK 异常、连接断开、协议错误、超时都返回 `ToolResult(ok=False, summary="MCP tool call failed: ...", error=...)`，不向外抛普通异常。

**验证：** `pytest tests/test_mcp_tool.py -q` 覆盖：多 text 块按顺序拼接、远端 `is_error` 映射、异常转失败结果、超时转失败结果、非 text 块跳过且只告警一次。

## T9: 实现 Manager 基础生命周期

**文件：** `src/coco_code/mcp/manager.py`、`src/coco_code/mcp/__init__.py`、`tests/test_mcp_manager.py`
**依赖：** T5、T8
**步骤：**
1. 定义 `STARTUP_TIMEOUT_SECONDS = 30.0`、`CLOSE_TIMEOUT_SECONDS = 5.0`。
2. 定义 `@dataclass class ManagedSession`，字段 `server_name`、`session`、`stack`。
3. 定义 `class McpManager`，构造参数 `config: McpConfig`、`version: str`、`stderr`。
4. 实现 `start()`：空配置立即返回；非空时为每个 server 创建启动 task，`asyncio.gather(..., return_exceptions=True)` 等全部完成。
5. 每个 server 启动外层用 `asyncio.timeout(STARTUP_TIMEOUT_SECONDS)`；失败或超时只告警并跳过。
6. 实现 `tools()` 返回 `_tools` 副本。
7. 实现 `close()`：并发关闭所有 `ManagedSession.stack`，总超时 5 秒，超时告警后返回。
8. 在 `__init__.py` 导出 `McpManager`。

**验证：** `pytest tests/test_mcp_manager.py -q -k "empty or timeout or close"` 覆盖：空配置、启动超时、失败隔离、关闭 5 秒兜底。

## T10: 实现 stdio 与 HTTP 连接

**文件：** `src/coco_code/mcp/manager.py`、`tests/test_mcp_manager.py`
**依赖：** T9
**步骤：**
1. 实现 `merge_env(extra)`：复制 `os.environ`，再用 server env 覆盖同名变量，返回 dict。
2. 实现 `connect_stdio(config, version, stderr)`：使用 `StdioServerParameters(command=config.command, args=list(config.args), env=merge_env(config.env))`。
3. 使用 `stdio_client(params)` 进入 transport async context，拿到 read/write。
4. 使用 `ClientSession(read, write)` 进入会话 async context，执行 `await session.initialize()` 和 `await session.list_tools()`。
5. 实现 `connect_http(config, version, stderr)`：创建 `httpx.AsyncClient(headers=config.headers, timeout=httpx.Timeout(30.0), follow_redirects=True)`，传给 `streamable_http_client(url=config.url, http_client=http_client)`。
6. 用 `AsyncExitStack` 托管 httpx client、transport、ClientSession。
7. `list_tools` 成功后调用 `adapt_tool`；非法工具跳过，合法工具进入 `_tools`。
8. `_tools` 按 `(server_name, remote_name)` 稳定排序。
9. 启动或列工具失败时，关闭该 server 已进入的 stack，避免连接泄漏。

**验证：** `pytest tests/test_mcp_manager.py -q` 覆盖：通过 monkeypatch fake `connect_stdio/connect_http` 验证成功工具注册、失败 server 不影响成功 server、排序稳定、env 覆盖宿主变量、HTTP headers 进入 `httpx.AsyncClient` 构造参数。

## T11: TUI 启动注册 MCP 工具

**文件：** `src/coco_code/tui/app.py`、`tests/test_tui_mcp.py`
**依赖：** T9、T10
**步骤：**
1. `CoCoCodeApp.__init__` 增加 `mcp_config: McpConfig | None = None`、`mcp_manager: McpManager | None = None` 参数。
2. 保存 `self.mcp_config`、`self.mcp_manager`。
3. 把 `on_mount` 改为 async，并在现有 provider 激活/选择逻辑前调用 `await self.start_mcp()`。
4. 实现 `start_mcp()`：空配置直接返回；否则构造 `McpManager(self.mcp_config, __version__)` 并 `await start()`。
5. 遍历 `manager.tools()` 并注册到 `self.tool_registry`；`ToolRegistryError` 时 stderr 告警并跳过，不影响其他工具。
6. 启动阶段保持输入框 disabled；可向 history 写一行 `Loading MCP tools...` 或只写失败摘要。
7. 更新退出路径：`action_quit` / `request_quit` 确保在退出前关闭 `mcp_manager`。如果退出函数无法 await，则创建内部 async helper 或在 Textual action 中完成 close 后再 exit。

**验证：** `pytest tests/test_tui_mcp.py -q` 覆盖：on_mount 调用 fake manager.start、注册 fake MCP tool、注册冲突跳过且内置工具仍存在、退出时 fake manager.close 被调用。

## T12: CLI 加载 MCP 配置

**文件：** `src/coco_code/cli.py`、`tests/test_tui_mcp.py` 或新增 CLI 轻量测试
**依赖：** T5、T11
**步骤：**
1. import `load_config as load_mcp_config`。
2. 在 `root = Path.cwd().resolve()` 之后调用 `mcp_config = load_mcp_config(root)`。
3. 构造 `CoCoCodeApp(config, cwd=root, permission_engine=engine, mcp_config=mcp_config)`。
4. 保持 provider 配置失败仍退出；MCP 配置错误不抛 `ConfigError`，只走 stderr 告警。
5. 如果 CLI 单测已有 monkeypatch `CoCoCodeApp`，更新断言包含 `mcp_config`。

**验证：** `python -m coco_code` 在无 MCP 配置时正常进入现有启动流程；自动测试可 monkeypatch `load_mcp_config` 与 `CoCoCodeApp`，断言传参正确。

## T13: 补充 MCP 权限规则测试

**文件：** `tests/test_permission_engine.py`、`tests/test_permission_rules.py`
**依赖：** T7、现有 permission 模块
**步骤：**
1. 增加规则匹配用例：`mcp__github__create_issue` 精确规则能命中完整工具名。
2. 增加 glob 用例：`mcp__github__*` 能匹配该 server 的全部 MCP 工具。
3. 构造 `ToolSpec(read_only=True)` 的 MCP 工具调用，断言默认模式下 `engine.check` 返回 Allow。
4. 构造 `ToolSpec(read_only=False)` 的 MCP 工具调用，断言 default 与 acceptEdits 下返回 Ask，bypass 下 Allow。
5. 断言 MCP 工具名不会触发内置 Bash 黑名单；MCP 参数里带路径字符串也不会走文件沙箱。
6. 断言 deny 规则可以拒绝 MCP 只读工具。

**验证：** `pytest tests/test_permission_engine.py tests/test_permission_rules.py -q` 通过。

## T14: 添加 MCP 配置示例文档

**文件：** `docs/mcp-servers.example.yaml`、`tests/test_mcp_config.py`
**依赖：** T5
**步骤：**
1. 新建示例文件，说明用户级路径 `~/.coco-code/mcp.yaml`、项目级路径 `<root>/.coco-code/mcp.yaml`。
2. 注释说明同名 server 项目级完整覆盖用户级。
3. 提供一个 stdio server 示例，使用 `command`、`args`、`env`。
4. 提供一个 HTTP server 示例，使用 `url`、`headers`。
5. 所有凭据只写 `${VAR}`，不写真实 token。
6. 在 `tests/test_mcp_config.py` 增加读取示例文件的测试，设置对应环境变量，断言示例可以解析出 stdio 和 http server。

**验证：** `pytest tests/test_mcp_config.py -q -k example` 通过；`Select-String -Path docs/mcp-servers.example.yaml -Pattern 'Bearer [A-Za-z0-9_\-]{12,}|sk-|ghp_|github_pat_'` 无命中。

## T15: MCP 单元测试全量运行

**文件：** `tests/test_mcp_config.py`、`tests/test_mcp_tool.py`、`tests/test_mcp_manager.py`、`tests/test_tui_mcp.py`
**依赖：** T1-T14
**步骤：**
1. 运行 `pytest tests/test_mcp_config.py -q`。
2. 运行 `pytest tests/test_mcp_tool.py -q`。
3. 运行 `pytest tests/test_mcp_manager.py -q`。
4. 运行 `pytest tests/test_tui_mcp.py -q`。
5. 若某项因真实 SDK API 字段名差异失败，优先调整适配层的字段读取兼容逻辑，而不是改测试放宽行为目标。

**验证：** 四组测试全部通过，无悬挂 task、无 `RuntimeWarning: coroutine ... was never awaited`。

## T16: 项目级质量检查

**文件：** —
**依赖：** T15
**步骤：**
1. 运行 `ruff format --check .`。
2. 运行 `ruff check .`。
3. 运行 `pytest`。
4. 如果本地环境已配置 mypy，运行 `mypy src`。
5. 搜索凭据明文：`git grep -E "(Bearer|sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}"`，预期无真实凭据命中。
6. 检查无临时 MCP 配置残留在项目根，尤其是 `.coco-code/mcp.yaml` 若仅为测试临时文件则删除。

**验证：** 上述命令全部通过；若 mypy 未作为必跑项，则记录未运行原因。

## T17: 可选端到端手动冒烟

**文件：** —
**依赖：** T16
**步骤：**
1. 准备一个真实 stdio MCP server。优先使用本地可用的官方示例或最小 Python MCP server；不要依赖需要网络下载的 server，除非已经提前安装。
2. 在项目根临时创建 `.coco-code/mcp.yaml`，配置一个 `demo` stdio server。
3. 启动 `python -m coco_code`。
4. 观察启动不被 MCP 阻塞；若 server 成功，模型工具列表包含 `mcp__demo__...`；若 server 失败，stderr 有可定位告警且内置工具仍可用。
5. 让模型调用一个 MCP 工具，确认结果以 ToolResult 形式回灌；非只读工具按权限模式触发确认。
6. 退出程序后确认 stdio server 子进程已关闭。
7. 删除临时 `.coco-code/mcp.yaml`。

**验证：** 手动记录观察结果；若无法准备真实 server，则说明原因，并以 T15/T16 自动化结果作为本轮证据。

## 执行顺序

```text
T1(依赖)
  ├─ T2(包门面) ─→ T3(配置结构) ─→ T4(YAML合并) ─→ T5(展开校验) ─┐
  │                                                              │
  ├─ T6(per-tool timeout) ─→ T7(工具适配) ─→ T8(调用转换) ────────┤
  │                                                              │
  └───────────────────────────────────────────────→ T9(manager) ─→ T10(stdio/http)
                                                                    │
T10 ─→ T11(TUI接入) ─→ T12(CLI接入) ─┬─→ T15(MCP测试) ─→ T16(全量检查) ─→ T17(可选冒烟)
                                     │
T7 + permission现状 ────────────────→ T13(权限测试) ─┘
T5 ─→ T14(配置示例) ─────────────────┘
```

依赖摘要：T3 依赖 T2；T4 依赖 T3；T5 依赖 T4；T7 依赖 T6；T8 依赖 T7；T9 依赖 T5/T8；T10 依赖 T9；T11 依赖 T10；T12 依赖 T5/T11；T13 依赖 T7 和现有 permission；T14 依赖 T5；T15 依赖 T1-T14；T16 依赖 T15；T17 依赖 T16。