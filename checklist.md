# CoCo Code Agent Loop Checklist

> 每一项都必须通过运行代码、自动化测试或 TUI 观察来验证。验收时先执行验证方式，再记录实际结果。

## 实现完整性

- [ ] Agent 核心包已建立，`AgentLoop`、`AgentMode`、`AgentLimits`、`AgentEvent` 等公共类型可导入。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k plain`）
- [ ] Agent 核心通过异步事件流输出文本、工具调用、工具开始、工具结果、进度、错误和停止原因，不直接依赖 Textual/Rich。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k event`）
- [ ] 流式收集器能实时转发文本增量，同时累积完整回复和工具调用列表。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k stream`）
- [ ] 没有工具调用的普通对话仍能流式输出、写入历史、markdown 定型并恢复输入。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k plain`，并在 TUI 中发送普通聊天请求观察）
- [ ] 单工具调用请求仍能显示工具状态、执行工具、回灌结果并输出最终回复。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k single_tool`）
- [ ] 多轮工具链可在一次用户请求内完成，不再需要用户输入“继续”。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k multi_turn`）

## 多工具与会话历史

- [ ] Provider 返回多个工具调用时，系统收集全部工具调用，而不是只处理第一个。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py -k multiple`）
- [ ] OpenAI / OpenAI-compatible 流式 JSON 参数碎片能按 index 拼接成多个 `ToolCall`。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py -k openai`）
- [ ] Anthropic 多个 `tool_use` block 能按出现顺序转换成多个 `ToolCall`。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py -k anthropic`）
- [ ] 多工具调用历史能按协议可回放格式写入会话，OpenAI 和 Anthropic 历史回放均正确。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py tests/test_conversation_tools.py`）
- [ ] 并发只读工具即使完成顺序不同，也按模型请求顺序写入会话历史和展示。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k order`）
- [ ] 大文件读取、大搜索结果、大命令输出仍被截断，并在工具结果中标明截断状态。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_builtin.py -k truncated`）

## 工具安全与执行

- [ ] Plan Mode 工具过滤基于 `ToolSpec.read_only`、`destructive`、`confirmation` 等元信息，而不是硬编码工具名。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k filter`）
- [ ] `ReadFile`、`Glob`、`Grep` 在 Plan Mode 中可用，`WriteFile`、`EditFile`、`Bash` 在 Plan Mode 中不可执行。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k plan`）
- [ ] 普通 Agent 模式和 Do Mode 下发完整工具集。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k do`）
- [ ] 同一响应中的多个只读、非破坏性、无需确认工具可并发执行。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k concurrent`）
- [ ] `WriteFile`、`EditFile`、`Bash` 或其他非只读/破坏性/需确认工具必须串行执行。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_tools.py -k serial`）
- [ ] `WriteFile`、`EditFile`、`Bash` 在 Agent Loop 中仍会弹出确认，批准后才执行。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_tools.py -k confirm`，并在 TUI 中触发写文件/改文件/命令执行观察弹窗）
- [ ] 用户拒绝工具后，拒绝结果作为结构化工具结果写回模型，程序不崩溃。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k reject`）
- [ ] `Bash` 元信息保持 `category=shell`、`read_only=False`、`destructive=True`。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_registry.py -k bash`）
- [ ] 路径限制、敏感环境变量隔离、命令超时、输出截断等既有工具安全行为不退化。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_builtin.py tests/test_tools_safety.py tests/test_tools_executor.py`）

## 停止条件与错误恢复

- [ ] 模型输出最终回复且没有工具调用时，Agent Loop 以 `MODEL_DONE` 停止并恢复输入。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k model_done`）
- [ ] 达到最大迭代次数时停止，不继续请求模型或执行工具，并展示“达到迭代上限”或等价停止原因。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k iteration_limit`）
- [ ] 用户取消当前轮任务时，后续 provider 请求和未开始工具执行停止，TUI 恢复可输入状态。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k cancel`，并在 TUI 中运行期间按取消/退出观察）
- [ ] 连续未知工具或当前模式不允许工具达到上限后停止，程序不崩溃。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k unknown`）
- [ ] Provider 流式响应错误时，Agent Loop 发出错误事件和 `STREAM_ERROR` 停止原因，已有文本和工具历史保留。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k stream_error`）
- [ ] 工具参数错误、路径越界、命令超时、确认超时、确认拒绝均以结构化结果呈现，TUI 恢复输入。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_executor.py tests/test_tui_tools.py`）
- [ ] 不再出现无限 `Imagining...`、无限等待确认或无限 provider 请求。（验证：运行迭代上限/确认超时/响应超时相关测试，并在 TUI 中观察停止原因）

## Plan Mode / Do Mode

- [ ] 输入 `/plan <任务>` 后进入 Plan Mode，状态栏或历史区明确显示当前模式。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py -k mode`，并在 TUI 输入 `/plan 分析项目结构` 观察）
- [ ] Plan Mode 可通过 `ReadFile`、`Glob`、`Grep` 了解项目并输出计划。（验证：在 TUI 输入 `/plan 给 spec.md 增加一行注释前先制定计划`，观察只读工具和计划文本）
- [ ] Plan Mode 不执行文件修改、命令执行、依赖安装或测试运行。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py tests/test_agent_tools.py -k plan`）
- [ ] 输入 `/do` 或 `/do <任务>` 后进入 Do Mode，使用完整工具集推进当前计划或任务。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py -k do`，并在 TUI 中观察模式切换）
- [ ] Do Mode 中每一步工具调用、确认、结果、停止原因都在历史区可追踪。（验证：在 TUI 运行一个小的计划执行任务，观察 Tool、Confirm Tool、Tool Result、Stop 面板）
- [ ] 模式切换、计划生成完成、执行开始、执行停止均有可见状态。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py -k mode`，并人工观察 TUI）

## TUI 与用户体验

- [ ] 等待模型、执行工具、等待确认、并发只读工具、串行副作用工具期间，TUI 不冻结。（验证：headless TUI 测试通过，并人工运行多步任务时确认可滚动/可见进度）
- [ ] 运行中显示当前迭代序号、最大迭代数、当前阶段、正在执行的工具或工具批次。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_tools.py -k progress`）
- [ ] 停止时显示停止原因，并清空流式区、恢复输入框、更新状态栏。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py -k stopped`）
- [ ] 助手最终回复仍以 markdown 定型展示，代码块、列表、强调等显示正常。（验证：在 TUI 提问“用 markdown 给一个 Python 示例”，观察最终展示）
- [ ] `/exit` 和 Ctrl+C 仍能安全退出，终端状态恢复正常。（验证：运行 TUI 后分别输入 `/exit` 和按 Ctrl+C，观察光标可见、输入正常）
- [ ] Provider 选择、多轮上下文、输入历史回放不退化。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py`，并人工测试多 provider 配置）

## 隐私与边界

- [ ] API key 不出现在 Agent 事件、工具定义、工具结果、计划文本、错误信息、状态栏或测试输出中。（验证：运行全量测试后搜索输出日志；人工观察 TUI 状态栏和错误面板）
- [ ] `Bash` 工具仍使用受限环境，不默认继承完整进程环境。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_builtin.py -k env`）
- [ ] 本章未实现完整权限系统、上下文压缩、长期记忆、MCP、插件系统、交互式 shell、自动回滚、复杂任务图调度或跨会话计划管理。（验证：代码 review 对照 `spec.md` 的“不做的事”，确认无相关新增入口）
- [ ] 本章没有新增第三方依赖；如实际实现新增依赖，`INSTALL.md` 已同步更新。（验证：检查 `pyproject.toml` 和 `INSTALL.md`）

## 编译与测试

- [ ] Agent 核心测试通过。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_agent_loop.py tests/test_agent_tools.py`）
- [ ] Provider 多工具解析和历史回放测试通过。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_llm_tool_events.py tests/test_conversation_tools.py`）
- [ ] 工具系统回归测试通过。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tools_builtin.py tests/test_tools_executor.py tests/test_tools_registry.py tests/test_tools_safety.py`）
- [ ] TUI headless 测试通过。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest tests/test_tui_app.py tests/test_tui_tools.py`）
- [ ] 全量 pytest 通过。（验证：运行 `./.codeagent/Scripts/python.exe -m pytest`）
- [ ] ruff 检查通过。（验证：运行 `./.codeagent/Scripts/python.exe -m ruff check .`）
- [ ] mypy 检查通过。（验证：运行 `./.codeagent/Scripts/python.exe -m mypy src`）

## 端到端场景

- [ ] 纯对话：启动 CoCo Code，输入“请用三句话介绍你能做什么”，模型不调用工具，流式回复并恢复输入。（验证：人工 TUI 观察）
- [ ] 多步只读任务：输入“输出项目根目录结构，并说明核心目录用途”，模型可连续使用 `Glob`/`ReadFile`/`Grep`，无需用户继续催促。（验证：人工 TUI 观察工具链和最终回复）
- [ ] Plan Mode：输入 `/plan 给 spec.md 第一行增加作者注释`，模型只使用只读工具并输出计划，不修改文件。（验证：人工观察工具列表和文件内容未变）
- [ ] Do Mode：在计划后输入 `/do`，模型进入执行模式，请求 `EditFile` 或 `WriteFile` 时弹出确认，批准后完成修改并给出最终说明。（验证：人工观察确认弹窗、工具结果和文件内容）
- [ ] 写文件确认：输入“在项目根目录创建 agent-loop-test.txt，内容为 hello agent loop”，确认 `WriteFile` 弹窗，批准后文件出现。（验证：人工 TUI 观察 + 检查文件）
- [ ] Bash 确认：输入“运行一个命令查看 Python 版本”，确认 `Bash` 弹窗，批准后展示退出码和输出。（验证：人工 TUI 观察）
- [ ] 确认拒绝：触发一个 `WriteFile` 或 `Bash` 请求并点击拒绝，模型收到拒绝结果后解释未执行，TUI 恢复输入。（验证：人工 TUI 观察）
- [ ] 迭代上限：使用 fake provider 或测试配置让模型持续请求工具，达到上限后停止并显示原因。（验证：自动测试或人工测试配置）
- [ ] 取消恢复：Agent Loop 运行中取消当前轮或退出，TUI 不残留锁定输入框、隐藏光标、未关闭弹窗或后台悬挂任务。（验证：人工 TUI 观察）
- [ ] Windows 兼容：在当前 Windows PowerShell 环境中完成纯对话、多步工具、Plan Mode、Do Mode、确认弹窗和 `Bash` 一次性命令场景。（验证：人工 TUI 观察）

## AC 覆盖索引

- AC1：实现完整性“多轮工具链”、端到端“多步只读任务/Do Mode”。
- AC2：停止条件“MODEL_DONE”、TUI “markdown 定型”。
- AC3：停止条件“迭代上限”。
- AC4：停止条件“用户取消”、端到端“取消恢复”。
- AC5：停止条件“连续未知工具”。
- AC6：停止条件“流式错误”。
- AC7：实现完整性“异步事件流”。
- AC8：实现完整性“流式双路收集”。
- AC9：多工具“收集全部工具调用”。
- AC10：工具安全“只读并发”。
- AC11：工具安全“副作用串行”。
- AC12：工具安全“高风险确认”。
- AC13-AC14：Plan Mode 条目。
- AC15-AC16：Do Mode 与模式状态条目。
- AC17：工具过滤基于元信息。
- AC18-AC19：TUI 进度和用量/兼容事件条目。
- AC20-AC21：纯对话和单工具兼容条目。
- AC22-AC23：会话历史顺序和输出截断条目。
- AC24：隐私与密钥条目。
- AC25-AC26：退出整洁和 Windows 兼容端到端条目。
- AC27-AC29：编译与测试条目。
- AC30：端到端场景条目。