# CoCo Code Agent Loop Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/coco_code/agent/__init__.py` | 导出 Agent 核心类型和 `AgentLoop` |
| 新建 | `src/coco_code/agent/types.py` | 定义模式、停止原因、限制、事件、进度、流式回合结果、工具批次 |
| 新建 | `src/coco_code/agent/stream.py` | 消费 provider 流，实时转发文本事件并收集完整回复和多工具调用 |
| 新建 | `src/coco_code/agent/tools.py` | 工具过滤、允许性校验、分批、并发/串行执行调度 |
| 新建 | `src/coco_code/agent/loop.py` | ReAct Agent Loop 主流程、停止条件、历史写入 |
| 修改 | `src/coco_code/conversation.py` | 增加多工具调用历史项和 `add_tool_calls` |
| 修改 | `src/coco_code/llm/__init__.py` | `StreamEvent` 增加 `tool_calls`、`usage` |
| 修改 | `src/coco_code/llm/openai_provider.py` | OpenAI 多工具流式解析与多工具历史回放 |
| 修改 | `src/coco_code/llm/anthropic_provider.py` | Anthropic 多工具流式解析与多工具历史回放 |
| 修改 | `src/coco_code/tools/registry.py` | 支持基于元信息过滤出临时 registry |
| 修改 | `src/coco_code/tui/app.py` | 接入 AgentLoop、解析 `/plan` `/do`、消费 AgentEvent、移除一次工具边界 |
| 修改 | `src/coco_code/tui/view.py` | 增加模式、进度、工具批次、停止原因展示 |
| 修改 | `src/coco_code/tui/stream.py` | 保留兼容薄包装或迁移到 `agent.stream` |
| 新建 | `tests/test_agent_tools.py` | Plan Mode 过滤、多工具分批、只读并发、副作用串行测试 |
| 新建 | `tests/test_agent_loop.py` | Agent Loop 多轮、停止、取消、未知工具、纯对话测试 |
| 修改 | `tests/test_conversation_tools.py` | 多工具历史项顺序和兼容测试 |
| 修改 | `tests/test_llm_tool_events.py` | OpenAI/Anthropic 多工具解析与回放测试 |
| 修改 | `tests/test_tui_app.py` | 模式切换、事件消费、状态恢复 headless 测试 |
| 修改 | `tests/test_tui_tools.py` | 工具确认、拒绝、结果展示不退化测试 |
| 检查 | `INSTALL.md` | 本章无新增依赖时保持不变；若实现发现缺失再补充 |

## T1: 建立 Agent 包和公共类型

**文件：** `src/coco_code/agent/__init__.py`, `src/coco_code/agent/types.py`

**依赖：** 无

**步骤：**
1. 创建 `coco_code.agent` 包。
2. 在 `types.py` 定义 `AgentMode`、`AgentStopReason`、`AgentLimits`、`AgentRunRequest`。
3. 定义 `AgentProgress`、`AgentEventType`、`AgentEvent`、`StreamTurnResult`、`ToolBatch`。
4. 在 `__init__.py` 导出上述公共类型。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_config.py`，确认新增包不会破坏现有导入。

## T2: 扩展 StreamEvent 以支持多工具调用

**文件：** `src/coco_code/llm/__init__.py`

**依赖：** T1

**步骤：**
1. 给 `StreamEvent` 增加 `tool_calls: tuple[ToolCall, ...] = ()`。
2. 给 `StreamEvent` 增加 `usage: dict[str, int] | None = None`。
3. 保留 `tool_call` 字段兼容旧调用点。
4. 确保 `Provider.stream()` 的类型签名不破坏现有 provider。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_events.py tests/test_llm_tool_events.py`。

## T3: 扩展会话历史支持多工具调用

**文件：** `src/coco_code/conversation.py`, `tests/test_conversation_tools.py`

**依赖：** T1

**步骤：**
1. 新增 `AssistantToolCallsItem`，字段为 `calls: tuple[ToolCall, ...]`。
2. 把 `AssistantToolCallsItem` 纳入 `ConversationItem`。
3. 增加 `Conversation.add_tool_calls(calls)`，空列表不写入历史。
4. 保留 `AssistantToolCallItem` 和 `add_tool_call()` 兼容旧路径。
5. 补充测试：多工具调用项按顺序保存，`messages()` 仍只返回纯文本消息。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_conversation_tools.py tests/test_conversation.py`。

## T4: 让 ToolRegistry 支持基于元信息过滤

**文件：** `src/coco_code/tools/registry.py`, `tests/test_tools_registry.py`

**依赖：** 无

**步骤：**
1. 增加 `ToolRegistry.filtered(predicate)` 或等价方法，返回包含匹配工具和别名的新 registry。
2. 确保 filtered registry 的 `list_specs()`、`get()`、`to_openai_tools()`、`to_anthropic_tools()` 正常工作。
3. 不改变默认 registry 的六个工具和别名行为。
4. 补充只读工具过滤、别名保留、未知工具错误测试。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_registry.py`。

## T5: 更新 OpenAI 多工具解析

**文件：** `src/coco_code/llm/openai_provider.py`, `tests/test_llm_tool_events.py`

**依赖：** T2, T3

**步骤：**
1. 把 `_openai_tool_event()` 改为返回全部工具调用的事件，例如 `_openai_tool_calls_event()`。
2. 按 accumulator 的 index 顺序生成 `ToolCall` 列表。
3. 事件同时填充 `tool_calls`，并为兼容填充第一个 `tool_call`。
4. JSON 参数解析失败时返回 `ERROR`。
5. `openai_message_from_item()` 支持 `AssistantToolCallsItem`，生成单条 assistant 消息里的多个 `tool_calls`。
6. 补充一次响应两个工具调用、碎片拼接、历史回放测试。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py`。

## T6: 更新 Anthropic 多工具解析

**文件：** `src/coco_code/llm/anthropic_provider.py`, `tests/test_llm_tool_events.py`

**依赖：** T2, T3

**步骤：**
1. 将 `AnthropicToolAccumulator` 改为按 content block 维护多个工具调用状态。
2. 在每个 `tool_use` block stop 后保存该工具调用，而不是立刻结束整个响应。
3. 在响应停止或工具调用完成边界处生成包含全部 `tool_calls` 的事件。
4. 保留 thinking delta 丢弃逻辑。
5. `anthropic_message_from_item()` 支持 `AssistantToolCallsItem`，生成包含多个 `tool_use` block 的 assistant 消息。
6. 补充两个 `tool_use`、input_json 片段、历史回放测试。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py`。

## T7: 实现 Agent 流式收集器

**文件：** `src/coco_code/agent/stream.py`, `tests/test_agent_loop.py`

**依赖：** T1, T2

**步骤：**
1. 实现 `collect_stream_turn(provider, messages, tools, on_event)`。
2. 对 `TEXT_DELTA` 立即发出 `AgentEvent(TEXT_DELTA)` 并累积 reply。
3. 对 `THINKING_DELTA` 直接忽略。
4. 对 `TOOL_CALL` 收集 `event.tool_calls`；若仅有旧 `event.tool_call`，转成单元素 tuple。
5. 对 `ERROR` 返回带 error 的 `StreamTurnResult`。
6. 对 `DONE` 返回完整 reply 和已收集工具调用。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k stream`。

## T8: 实现模式工具过滤和允许性校验

**文件：** `src/coco_code/agent/tools.py`, `tests/test_agent_tools.py`

**依赖：** T1, T4

**步骤：**
1. 实现 `registry_for_mode(registry, mode)`。
2. `AGENT` 和 `DO` 返回完整工具集。
3. `PLAN` 只保留 `read_only=True`、`destructive=False`、`confirmation=NEVER` 的工具。
4. 实现 `validate_tool_allowed(call, registry, mode)`，未知工具和模式不允许工具返回结构化 `ToolResult`。
5. 测试 `ReadFile`、`Glob`、`Grep` 进入 Plan Mode，`WriteFile`、`EditFile`、`Bash` 被拒绝。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k "filter or allowed"`。

## T9: 实现工具分批策略

**文件：** `src/coco_code/agent/tools.py`, `tests/test_agent_tools.py`

**依赖：** T8

**步骤：**
1. 实现 `ToolBatcher.build_batches()`。
2. 连续只读、非破坏性、无需确认工具合并为并发批次。
3. 非只读、破坏性或需要确认工具拆成单工具串行批次。
4. 保持模型请求顺序。
5. 测试 `[Glob, Grep, EditFile, Bash]` 被分为并发只读批次和两个串行批次。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k batch`。

## T10: 实现工具批次执行调度

**文件：** `src/coco_code/agent/tools.py`, `tests/test_agent_tools.py`

**依赖：** T9

**步骤：**
1. 实现 `execute_tool_batches()`。
2. 并发批次使用 `asyncio.Semaphore` 限制并发数。
3. 串行批次逐个调用 `ToolExecutor.execute()`。
4. 为每个批次和工具发出 `TOOL_BATCH_STARTED`、`TOOL_STARTED`、`TOOL_RESULT` 事件。
5. 并发执行完成后按原 calls 顺序返回结果。
6. 测试只读工具可并发、副作用工具串行、结果顺序稳定。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py`。

## T11: 实现 AgentLoop 纯对话闭环

**文件：** `src/coco_code/agent/loop.py`, `tests/test_agent_loop.py`

**依赖：** T7, T8

**步骤：**
1. 创建 `AgentLoop` 构造函数，注入 provider、conversation、registry、executor、limits。
2. `run()` 开始时写入用户消息并发出模式/进度事件。
3. 调用 `collect_stream_turn()`。
4. 无工具调用时写入 assistant 文本，发出 `ASSISTANT_MESSAGE` 和 `STOPPED(MODEL_DONE)`。
5. 测试普通纯对话能流式输出、写入历史、正常停止。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k plain`。

## T12: 实现多轮工具循环

**文件：** `src/coco_code/agent/loop.py`, `tests/test_agent_loop.py`

**依赖：** T10, T11

**步骤：**
1. 当 `StreamTurnResult.tool_calls` 非空时，写入 `Conversation.add_tool_calls()`。
2. 发出 `TOOL_CALLS` 事件。
3. 使用 `ToolBatcher` 和 `execute_tool_batches()` 执行工具。
4. 按工具调用顺序写入 `Conversation.add_tool_result()`。
5. 工具结果写回后进入下一次 provider 请求。
6. 测试 `Glob → ReadFile → EditFile → final reply` 能在一次用户请求内完成。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k multi_turn`。

## T13: 实现 AgentLoop 停止条件

**文件：** `src/coco_code/agent/loop.py`, `tests/test_agent_loop.py`

**依赖：** T12

**步骤：**
1. 实现 `max_iterations` 检查，达到后发出 `STOPPED(ITERATION_LIMIT)`。
2. 实现连续未知/不允许工具计数，达到上限后发出 `STOPPED(UNKNOWN_TOOL_LIMIT)`。
3. 流式错误时发出 `ERROR` 和 `STOPPED(STREAM_ERROR)`。
4. 捕获 `asyncio.CancelledError`，发出 `STOPPED(USER_CANCELLED)`，并保证调用方可恢复状态。
5. 工具确认拒绝结果写回历史，让模型有机会继续；若循环后达到停止条件再停止。
6. 补齐对应 fake provider 测试。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k "limit or unknown or error or cancel"`。

## T14: 调整 TUI 输入解析和模式状态

**文件：** `src/coco_code/tui/app.py`, `tests/test_tui_app.py`

**依赖：** T1, T11

**步骤：**
1. 给 `CoCoCodeApp` 增加当前 `AgentMode` 状态。
2. 在 `prompt_submitted()` 或辅助函数中解析 `/plan`、`/do`、普通输入。
3. `/exit` 继续走退出逻辑。
4. `/plan xxx` 生成 `AgentRunRequest(mode=PLAN, text=xxx)`。
5. `/do xxx` 生成 `AgentRunRequest(mode=DO, text=xxx)`。
6. 单独 `/plan` 或 `/do` 使用命令本身的默认提示文本或当前上下文。
7. 增加 headless 测试验证模式切换和输入框状态。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py -k mode`。

## T15: TUI 接入 AgentEvent 消费

**文件：** `src/coco_code/tui/app.py`, `tests/test_tui_app.py`, `tests/test_tui_tools.py`

**依赖：** T13, T14

**步骤：**
1. 将 `submit_user_text()` 改为创建并运行 `AgentLoop.run()`。
2. 新增 `_run_agent_turn()` 消费 `AgentEvent`。
3. 删除正常流程中的 `_handle_tool_call()` 和 `_stream_final_reply()` 调用。
4. 处理 `TEXT_DELTA` 更新当前流式文本。
5. 处理 `ASSISTANT_MESSAGE`、`TOOL_CALLS`、`TOOL_RESULT`、`ERROR`、`STOPPED`。
6. `STOPPED` 后恢复输入框、暂停 timer、更新状态栏。
7. 保留现有 `confirm_tool_call()` 回调。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py tests/test_tui_tools.py`。

## T16: 增强 TUI 展示函数

**文件：** `src/coco_code/tui/view.py`, `tests/test_tui_tools.py`

**依赖：** T1

**步骤：**
1. 增加 `agent_progress_text(progress, elapsed)`。
2. 增加 `agent_stop_block(reason, detail)`。
3. 增加 `mode_status_text(provider, mode, message_count, progress)`。
4. 增加 `tool_batch_block(batch_index, batch_total, calls, concurrent)`。
5. 保持 `tool_call_block()`、`tool_confirm_block()`、`tool_result_block()` 兼容。
6. 测试输出中能看到模式、迭代、工具名、停止原因。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_tools.py`。

## T17: 处理 `tui.stream` 兼容层

**文件：** `src/coco_code/tui/stream.py`, `tests/test_tui_tools.py`

**依赖：** T7, T15

**步骤：**
1. 若仍有旧测试或旧调用点依赖 `consume_provider_stream()`，改成调用 `agent.stream.collect_stream_turn()` 的薄包装。
2. `StreamResult` 保留兼容字段，但从多工具结果取第一个 `tool_call`。
3. 若没有调用点，保留模块但标明仅兼容旧路径。
4. 确认正常 TUI 已不依赖“一次工具调用”边界。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_tools.py tests/test_llm_tool_events.py`。

## T18: 更新 Provider 历史回放集成测试

**文件：** `tests/test_llm_tool_events.py`, `src/coco_code/llm/openai_provider.py`, `src/coco_code/llm/anthropic_provider.py`

**依赖：** T5, T6

**步骤：**
1. 测试 OpenAI 对 `AssistantToolCallsItem` 输出单条 assistant 消息和多个 `tool_calls`。
2. 测试 Anthropic 对 `AssistantToolCallsItem` 输出多个 `tool_use` block。
3. 测试 tool result 仍按工具调用 id 回放。
4. 确认旧 `AssistantToolCallItem` 回放仍通过。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py tests/test_conversation_tools.py`。

## T19: 覆盖 Plan Mode 与 Do Mode 的 Agent 集成测试

**文件：** `tests/test_agent_loop.py`, `tests/test_agent_tools.py`

**依赖：** T12, T13

**步骤：**
1. 用 fake provider 验证 Plan Mode 只下发只读工具。
2. 模型请求 `WriteFile` 时返回不允许工具结果，不执行工具。
3. 连续不允许工具达到上限后停止。
4. 用 fake provider 验证 Do Mode 下发完整工具集。
5. Do Mode 中需要确认的 fake tool 仍通过 confirm callback。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py tests/test_agent_tools.py -k "plan or do"`。

## T20: 回归现有工具安全和执行测试

**文件：** `tests/test_tools_builtin.py`, `tests/test_tools_executor.py`, `tests/test_tools_safety.py`, `tests/test_tools_registry.py`

**依赖：** T4, T10

**步骤：**
1. 跑现有工具测试，确认路径限制、输出截断、命令环境、确认拒绝、确认超时都不退化。
2. 若 registry 过滤影响默认注册顺序或别名，修正测试或实现。
3. 确认 `Bash` 仍标记为 `category=shell`、`read_only=False`、`destructive=True`。

**验证：** 运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_builtin.py tests/test_tools_executor.py tests/test_tools_safety.py tests/test_tools_registry.py`。

## T21: 全量质量检查

**文件：** 全项目

**依赖：** T1-T20

**步骤：**
1. 运行全量测试。
2. 运行 ruff。
3. 运行 mypy。
4. 若失败，先修复再重新运行对应命令。
5. 确认本章没有新增第三方依赖；如发现依赖变更，更新 `INSTALL.md`。

**验证：**
1. `./.codeagent/Scripts/python.exe -m pytest`
2. `./.codeagent/Scripts/python.exe -m ruff check .`
3. `./.codeagent/Scripts/python.exe -m mypy src`

## T22: 端到端人工验收准备

**文件：** `checklist.md` 后续生成时引用；当前不改实现代码以外文件

**依赖：** T21

**步骤：**
1. 准备纯对话场景：提问一个不需要工具的问题。
2. 准备多步只读场景：让 CoCo Code 输出项目根目录结构或查找某个函数定义。
3. 准备 `/plan` 场景：要求先分析一个小改动计划。
4. 准备 `/do` 场景：基于计划执行一个小的安全修改。
5. 准备确认场景：触发 `WriteFile`、`EditFile`、`Bash` 并分别批准/拒绝。
6. 准备停止场景：fake provider 或测试配置触发迭代上限和取消恢复。

**验证：** 本任务在 `checklist.md` 中转化为可观测验收条目；开发阶段不单独执行。

## 执行顺序

```text
T1
 ├─→ T2 ─→ T5 ─┐
 ├─→ T3 ───────┼─→ T7 ─→ T11 ─→ T12 ─→ T13 ─┐
 └─→ T4 ─→ T8 ─→ T9 ─→ T10 ─────────────────┘

T5 + T6 + T18 负责 provider 多工具解析
T11-T13 完成 Agent 核心循环
T14-T17 接入 TUI
T19-T20 补齐模式与工具回归
T21 全量质量检查
T22 准备 checklist 端到端场景
```

## 自检

- plan 覆盖：`agent.types`、`agent.stream`、`agent.tools`、`agent.loop`、`conversation`、`llm`、`tui`、`tests` 均有对应任务。
- 依赖链：先类型和兼容结构，再 provider/工具，再 AgentLoop，最后 TUI 和全量测试。
- 验证完整：每个任务都有可运行命令或明确验收转化方式。
- 范围控制：没有引入完整权限系统、上下文压缩、MCP、插件系统或跨会话计划管理。