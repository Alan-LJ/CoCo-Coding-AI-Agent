# MCP 客户端 Checklist

> 每一项通过运行代码、自动化测试或可观察行为来验证；函数和类型名只作定位提示，验收以外部行为为准。当前仓库包名为 `coco_code`，MCP 配置路径按 plan 落地为 `~/.coco-code/mcp.yaml` 与 `<root>/.coco-code/mcp.yaml`。

## 实现完整性

- [ ] MCP 运行依赖可导入：官方 SDK `mcp`、stdio transport、Streamable HTTP transport、`httpx` 都能导入。（验证：运行 `python -c "from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; from mcp.client.streamable_http import streamable_http_client; import httpx; print('ok')"`，输出 `ok`）
- [ ] `coco_code.mcp` 子包可导入，暴露配置加载、manager 和工具适配所需公共符号。（验证：运行 `python -c "from coco_code.mcp import McpConfig, ServerConfig, McpManager, load_config; print('ok')"`）
- [ ] `ToolSpec.timeout_seconds` 不影响内置工具默认行为，并能让 MCP 工具获得 30 秒内部调用超时的外层兜底窗口。（验证：运行 `pytest tests/test_tools_executor.py -q`，包含 per-tool timeout 优先级用例）
- [ ] TUI 启动时会先完成 MCP 工具发现并注册，再启用 provider 选择或输入框。（验证：运行 `pytest tests/test_tui_mcp.py -q`，断言 fake manager 启动和工具注册发生在 mount 流程中）
- [ ] CLI 会加载 MCP 配置并传给 `CoCoCodeApp`，无 MCP 配置时启动路径与当前版本一致。（验证：CLI 轻量测试或 monkeypatch `CoCoCodeApp`，断言 `mcp_config` 传入；手动运行 `python -m coco_code` 无 MCP 配置不报 MCP 错误）

## 配置加载

- [ ] 无 `mcp_servers` 配置时，MCP 配置为空且启动不失败，内置工具集合保持可用。（验证：`pytest tests/test_mcp_config.py -q -k "missing"`；手动无配置启动 `python -m coco_code`）
- [ ] 用户级与项目级 MCP 配置按 server 名合并；同名 server 由项目级完整覆盖用户级，不做字段级合并。（验证：单测构造 `~/.coco-code/mcp.yaml` 与 `<root>/.coco-code/mcp.yaml`，断言覆盖后的字段全部来自项目级）
- [ ] 任一 MCP YAML 文件缺失视为空；非法 YAML、顶层非 map、`mcp_servers` 非 map 时跳过该文件并 stderr 告警，不阻断其他层加载。（验证：`pytest tests/test_mcp_config.py -q -k "invalid_yaml or degrade"`）
- [ ] server 字段校验严格：`type` 缺失/非法、stdio 缺 `command`、http 缺 `url`、`args`/`env`/`headers` 类型错误都会跳过该 server 并告警。（验证：`pytest tests/test_mcp_config.py -q -k "validate"`）
- [ ] `${VAR}` 只在 `env` 和 `headers` 的值中展开；未定义变量展开为空字符串并告警；`command`、`args`、server 名和工具名不展开。（验证：`pytest tests/test_mcp_config.py -q -k "expand"`）
- [ ] stderr 告警、测试输出和示例配置不泄露 env/header 的实际密钥值。（验证：配置中设置假 token，运行配置测试，断言 `capsys.err` 不包含 token 值）
- [ ] `docs/mcp-servers.example.yaml` 能被配置加载器解析，且只用 `${VAR}` 表达凭据。（验证：`pytest tests/test_mcp_config.py -q -k "example"`；运行 `Select-String -Path docs/mcp-servers.example.yaml -Pattern 'sk-|ghp_|github_pat_|Bearer [A-Za-z0-9_\-]{12,}'` 无真实凭据命中）

## 连接与生命周期

- [ ] stdio server 能通过官方 SDK 完成启动、initialize 和 `tools/list`；配置 env 会覆盖同名宿主环境变量并注入子进程。（验证：`pytest tests/test_mcp_manager.py -q -k "stdio or env"`，或手动接一个本地最小 stdio server）
- [ ] Streamable HTTP server 能通过 `httpx.AsyncClient` 注入 headers 并完成 initialize 和 `tools/list`。（验证：`pytest tests/test_mcp_manager.py -q -k "http or headers"`，使用 fake transport 或 mock HTTP client 断言 headers 传入）
- [ ] 单个 server 连接、握手或列工具失败时只跳过该 server，内置工具和其他 MCP server 工具仍可用。（验证：`pytest tests/test_mcp_manager.py -q -k "failure_isolation"`）
- [ ] 单个 server 启动序列受 30 秒超时约束；测试中缩短超时后，卡住的连接会被跳过并告警。（验证：`pytest tests/test_mcp_manager.py -q -k "startup_timeout"`）
- [ ] 所有 server 尝试结束后工具集稳定，本次会话不做热加载。（验证：manager 启动测试断言 `tools()` 结果稳定；运行期修改配置不改变已注册工具）
- [ ] `McpManager.close()` 会关闭所有已建立会话；关闭卡住时受 5 秒兜底，不阻塞程序退出。（验证：`pytest tests/test_mcp_manager.py -q -k "close"`）
- [ ] 退出 TUI 时会调用 MCP manager close；如果正在 streaming，先取消当前轮再关闭 MCP 连接。（验证：`pytest tests/test_tui_mcp.py -q -k "close"`）

## 工具发现与注册

- [ ] 远端工具注册名统一为 `mcp__<server>__<tool>`。（验证：`pytest tests/test_mcp_tool.py -q -k "name"`）
- [ ] 拼接后含非法工具名字符（非 `[A-Za-z0-9_-]`）的 MCP 工具被跳过并 stderr 告警；同一 server 的其他合法工具仍注册。（验证：`pytest tests/test_mcp_tool.py -q -k "illegal"`）
- [ ] 同名远端工具来自不同 server 时不会互相覆盖；与 6 个内置工具不重名。（验证：registry 集成测试断言工具名集合无重复，且内置工具仍在）
- [ ] 同一 full name 重复注册时后者跳过并告警，不覆盖已注册工具。（验证：`pytest tests/test_tui_mcp.py -q -k "conflict"` 或 registry 集成测试）
- [ ] 远端 description 为空时使用包含 server/tool 来源的兜底描述；非空时保留远端描述。（验证：`pytest tests/test_mcp_tool.py -q -k "description"`）
- [ ] 远端 `inputSchema`/`input_schema` 作为 JSON Schema dict 透传；缺失或非法时兜底为 object schema，provider 不会收到空 schema。（验证：`pytest tests/test_mcp_tool.py -q -k "schema"`）
- [ ] 只有 `annotations.readOnlyHint == true` 或 `read_only_hint == True` 映射为只读；缺失、false、非法均按非只读处理。（验证：`pytest tests/test_mcp_tool.py -q -k "read_only"`）
- [ ] 只读 MCP 工具的 confirmation 为 `never`，非只读 MCP 工具的 confirmation 为 `required`，无 permission engine 时仍有安全确认兜底。（验证：`pytest tests/test_mcp_tool.py -q -k "confirmation"`）

## 工具调用

- [ ] MCP 工具调用会把 params 原样作为 `tools/call` arguments 传给远端工具，空 dict 可按设计转为 `None` 或空参数。（验证：`pytest tests/test_mcp_tool.py -q -k "arguments"`）
- [ ] 远端多个 text content block 按顺序拼接成成功 ToolResult，并进入会话历史。（验证：`pytest tests/test_mcp_tool.py -q -k "text_content"`；Agent 集成测试断言 ToolResultItem 写入历史）
- [ ] 远端 `is_error`/`isError` 为 True 时，MCP 工具返回失败 ToolResult，错误文本来自远端 text 或兜底文案。（验证：`pytest tests/test_mcp_tool.py -q -k "remote_error"`）
- [ ] 非 text 内容块（image/audio/resource_link/embedded_resource 等）不回灌给模型，并对每个工具最多告警一次。（验证：`pytest tests/test_mcp_tool.py -q -k "non_text"`）
- [ ] SDK 异常、协议错误、连接断开都会转成失败 ToolResult，不抛出普通异常打断 Agent Loop。（验证：`pytest tests/test_mcp_tool.py -q -k "exception"`）
- [ ] `tools/call` 内部 30 秒超时会转成失败 ToolResult；Agent Loop 可以继续下一轮。（验证：`pytest tests/test_mcp_tool.py -q -k "timeout"`，测试中 monkeypatch 缩短超时）
- [ ] 外层 `ToolExecutor` 的 per-tool timeout 只是兜底；正常超时时优先看到 MCP 工具自己的结构化错误。（验证：`pytest tests/test_tools_executor.py tests/test_mcp_tool.py -q -k "timeout"`）

## 权限集成

- [ ] `mcp__<server>__<tool>` 精确规则能 allow 或 deny 对应 MCP 工具。（验证：`pytest tests/test_permission_rules.py tests/test_permission_engine.py -q -k "mcp"`）
- [ ] `mcp__<server>__*` glob 规则能匹配该 server 的全部 MCP 工具。（验证：权限规则测试断言 glob 命中）
- [ ] `readOnlyHint == true` 的 MCP 工具在 default 模式下按只读类放行，并可参与只读并发批次。（验证：权限引擎测试 + agent/tool batcher 测试）
- [ ] 非只读 MCP 工具在 default 与 acceptEdits 模式下按执行类触发人在回路；bypass 模式下放行。（验证：权限引擎测试断言裁决）
- [ ] 黑名单只作用于内置 Bash 命令；MCP 工具名或参数中出现危险字符串不会被黑名单层误拦。（验证：权限引擎测试构造 MCP 工具参数含 `rm -rf /`，断言不因黑名单直接 Deny）
- [ ] 路径沙箱只作用于内置文件类工具；MCP 工具参数中出现路径字符串不会进入沙箱层误拦。（验证：权限引擎测试构造 MCP 工具参数含项目外路径，断言不因沙箱直接 Deny）
- [ ] provider 适配层无 MCP 特殊逻辑；Anthropic/OpenAI 只看到统一 Tool schema 与 ToolResult。（验证：检查 `src/coco_code/llm/anthropic_provider.py`、`src/coco_code/llm/openai_provider.py` diff 无 MCP 分支；现有 provider tests 通过）

## 编译与测试

- [ ] MCP 配置测试通过。（验证：`pytest tests/test_mcp_config.py -q`）
- [ ] MCP 工具适配测试通过。（验证：`pytest tests/test_mcp_tool.py -q`）
- [ ] MCP manager 生命周期测试通过，无悬挂 task 或 coroutine warning。（验证：`pytest tests/test_mcp_manager.py -q`）
- [ ] TUI MCP 接线测试通过。（验证：`pytest tests/test_tui_mcp.py -q`）
- [ ] 权限与 MCP 命名空间测试通过。（验证：`pytest tests/test_permission_engine.py tests/test_permission_rules.py -q`）
- [ ] 全量测试通过，既有 config/conversation/tool/agent/prompt/permission/tui 行为不退化。（验证：`pytest`）
- [ ] 格式检查通过。（验证：`ruff format --check .`）
- [ ] lint 检查通过。（验证：`ruff check .`）
- [ ] 可选类型检查通过，或记录未运行原因。（验证：`mypy src`，如果环境未配置则在验收报告说明）
- [ ] 没有真实 token、API key 或密钥明文落盘。（验证：`git grep -E "(Bearer|sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}"` 无真实凭据命中）

## 端到端场景

- [ ] 场景 1：无 MCP 配置时启动 `python -m coco_code`，应用正常进入现有流程，内置工具可用，stderr 无 MCP 错误。（验证：手动启动观察或 TUI smoke 测试）
- [ ] 场景 2：配置一个可用 stdio MCP server，启动后工具列表包含 `mcp__demo__...`，模型能调用其中一个工具并收到 ToolResult 回灌。（验证：本地最小 stdio server 或已安装示例 server；不依赖临时网络下载）
- [ ] 场景 3：配置一个不存在 command 的 server 和一个可用 server，启动 stderr 有失败 server 的告警，可用 server 工具仍能注册和调用。（验证：手动或 manager 集成测试）
- [ ] 场景 4：配置 HTTP MCP server 或 mock server，headers 中的 `Authorization: Bearer ${TOKEN}` 被展开并发送，server 端能观察到 header。（验证：本地 mock HTTP server 或 `httpx.MockTransport`）
- [ ] 场景 5：未定义 `${TOKEN}` 时启动会出现 undefined 变量告警，但配置加载和启动流程不崩溃；定义后不再出现 undefined 告警。（验证：手动设置/取消环境变量后启动）
- [ ] 场景 6：非只读 MCP 工具在 default 模式下触发权限确认；选择允许本次后执行并回灌结果，选择拒绝后回灌拒绝结果且 Loop 不崩溃。（验证：TUI 手动场景或 fake provider 集成测试）
- [ ] 场景 7：`mcp__demo__*` allow 规则写入后，同一 server 的 MCP 工具不再弹窗；deny 规则优先时拒绝执行。（验证：编辑权限配置并重启，观察权限行为）
- [ ] 场景 8：退出应用后 stdio MCP server 子进程被清理；关闭卡住不会让应用无限等待。（验证：退出后用系统进程查看工具确认 server 进程无残留；自动 close 测试覆盖卡住情况）

## 范围边界

- [ ] 未实现 MCP resources、prompts、sampling、roots。（验证：检查 `src/coco_code/mcp` 只处理 tools/list 与 tools/call）
- [ ] 未实现 tools/list 变更通知、进度通知、独立 SSE 订阅或运行时热加载。（验证：检查 manager 没有后台 watcher/订阅逻辑）
- [ ] 未实现健康检查、自动重连、退避重试。（验证：检查 manager 失败后只跳过 server）
- [ ] 未新增本地级 MCP 配置层，未读取 `.coco-code/config.local.yaml` 作为 MCP server 来源。（验证：配置路径测试只返回用户级和项目级 `mcp.yaml`）
- [ ] 未对 `command`、`args`、server 名、工具名做 `${VAR}` 展开。（验证：配置测试保留字面量）
- [ ] 未实现 OAuth 完整流程，仅支持静态 headers。（验证：HTTP 配置和代码中无 OAuth 流程）
- [ ] 未把 MCP 工具纳入危险命令黑名单或路径沙箱扩展。（验证：权限测试和 diff 范围）
- [ ] 未实现资源配额、速率限制、审计日志或 MCP Server 端。（验证：检查新增模块范围）