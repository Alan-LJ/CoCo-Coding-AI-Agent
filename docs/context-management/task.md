# Context Management Tasks

本章把“两层压缩 + 压缩后恢复 + 手动 / 紧急入口”按 `docs/context-management/plan.md` 落到当前 `coco_code` 代码结构。任务只描述实现顺序和验证方式；在 checklist 通过前不开始编码。

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/coco_code/compact/__init__.py` | compact 包导出入口 |
| 新建 | `src/coco_code/compact/constants.py` | 上下文管理硬编码常量 |
| 新建 | `src/coco_code/compact/state.py` | `SessionContext`、替换账本、熔断器 |
| 新建 | `src/coco_code/compact/token.py` | token 估算和 usage 锚点合并 |
| 新建 | `src/coco_code/compact/layer1.py` | 工具结果落盘、预览、批次压缩 |
| 新建 | `src/coco_code/compact/summary_prompt.py` | 摘要 prompt、会话序列化、summary 提取 |
| 新建 | `src/coco_code/compact/recovery.py` | 文件追踪、恢复三段、边界提示 |
| 新建 | `src/coco_code/compact/layer2.py` | 摘要、近期尾部、PTL 重试、熔断 |
| 新建 | `src/coco_code/compact/manager.py` | `manage_context` 统一入口 |
| 新建 | `src/coco_code/agent/runtime.py` | `SessionRuntime` 会话级状态 |
| 修改 | `src/coco_code/conversation.py` | 增加整体替换历史接口 |
| 修改 | `src/coco_code/config.py` | `context_window` 与默认窗口 |
| 修改 | `src/coco_code/llm/__init__.py` | `PromptTooLongError` |
| 修改 | `src/coco_code/llm/openai_provider.py` | usage 回传与 PTL 包装 |
| 修改 | `src/coco_code/llm/anthropic_provider.py` | usage 回传与 PTL 包装 |
| 修改 | `src/coco_code/agent/types.py` | compact 事件类型 |
| 修改 | `src/coco_code/agent/stream.py` | usage 传递 |
| 修改 | `src/coco_code/agent/loop.py` | 自动压缩、紧急压缩、文件追踪、手动压缩入口 |
| 新建 | `src/coco_code/tui/commands.py` | `/exit`、`/plan`、`/do`、`/compact` 命令分发 |
| 修改 | `src/coco_code/tui/app.py` | runtime 持有、命令路由、compact notice |
| 修改/新建 | `.coco-code/config.yaml.example` | `context_window` 示例 |
| 修改 | `.gitignore` | 显式忽略 `.mewcode/sessions/` |
| 新建/修改 | `tests/test_compact_*.py` | compact 各模块单测 |
| 修改 | `tests/test_conversation.py` | `replace_items` 测试 |
| 修改 | `tests/test_config.py` | `context_window` 测试 |
| 修改 | `tests/test_llm_events.py` | PTL 和 usage 测试 |
| 修改 | `tests/test_agent_loop.py` | 自动/紧急/手动压缩集成测试 |
| 修改 | `tests/test_tui_app.py` | `/compact` 与命令回归测试 |

## T1: 建立 compact 包和常量

**文件**：`src/coco_code/compact/__init__.py`、`src/coco_code/compact/constants.py`  
**依赖**：无

**步骤**：
1. 新建 `src/coco_code/compact/` 目录和 `__init__.py`。
2. 在 `constants.py` 定义 plan 中列出的全部常量：单条 50000 字节、批次 200000 字节、摘要预留 20000 token、自动余量 13000、手动余量 3000、近期尾部 10000 token / 5 条、文件快照 5 个 / 5000 token、熔断 3 次、PTL 重试 3 次、丢弃比例 0.2、字符 token 比 3.5、预览 2048 字节 / 20 行。
3. 给每个常量写一句简短注释，说明它服务的行为。

**验证**：`python -c "from coco_code.compact import constants"` 不报错。

## T2: 实现 SessionContext 和会话目录

**文件**：`src/coco_code/compact/state.py`  
**依赖**：T1

**步骤**：
1. 新建 `state.py`，定义 `SessionContext(session_id: str, spill_dir: Path)`。
2. 实现 `new_session_context(workspace: Path) -> SessionContext`。
3. session id 使用 `<unix_ts>-<short_random>` 格式，随机部分用 `secrets.token_hex(4)`。
4. 创建 `.mewcode/sessions/<session_id>/tool-results/`，目录已存在时不报错。

**验证**：临时调用 `new_session_context(Path.cwd())`，确认返回路径存在且包含 `tool-results`。

## T3: 实现替换账本和熔断器

**文件**：`src/coco_code/compact/state.py`  
**依赖**：T2

**步骤**：
1. 定义 `ReplacementDecision(kind, result)`，`kind` 支持 `kept`、`replaced`、`skip`。
2. 定义 `ContentReplacementState`，内部维护 `_seen_ids` 和 `_replacements`。
3. 实现 `async decide_once(tool_call_id, original, decide)`，在同一把 `asyncio.Lock` 内完成查账本、调用决策、写账本。
4. 定义 `CompactCircuitBreaker`，实现 `record_success`、`record_failure`、`tripped`。

**验证**：新增 `tests/test_compact_state.py`，覆盖 replaced 复用、kept 固定、skip 不写账本、3 次失败熔断。

## T4: 实现文件追踪状态

**文件**：`src/coco_code/compact/recovery.py`  
**依赖**：T1

**步骤**：
1. 定义 `FileReadRecord(path, content, timestamp)`。
2. 定义 `RecoveryState`，内部用绝对路径作为 key。
3. 实现 `record_file(path, content)`，写入当前时间戳。
4. 实现 `snapshot()`，返回按时间倒序的拷贝列表。

**验证**：`tests/test_compact_recovery.py` 覆盖同一文件覆盖更新时间、多个文件按时间倒序。

## T5: 实现 token 估算

**文件**：`src/coco_code/compact/token.py`  
**依赖**：T1

**步骤**：
1. 实现 `conversation_bytes(items)`，按 UTF-8 字节统计 `ChatMessage`、工具调用参数、`ToolResult` payload。
2. 实现 `estimate_tokens(anchor, items, anchor_item_len)`，只估算 anchor 后的增量。
3. 实现 `usage_anchor(usage)`，合并 provider 提供的 usage 字段；缺失字段按 0 处理。

**验证**：`tests/test_compact_token.py` 覆盖无 anchor、有 anchor、anchor 长度越界、usage 字段缺失。

## T6: 实现工具结果落盘和预览构造

**文件**：`src/coco_code/compact/layer1.py`  
**依赖**：T1、T2

**步骤**：
1. 实现 `tool_result_payload_bytes(result)`，按 provider 实际 JSON payload 的 UTF-8 字节估算。
2. 实现 `spill_single(session, result)`，写入 `spill_dir / result.tool_call_id`，文件已存在则跳过。
3. 实现预览头部截断：先取 20 行，再按 2048 UTF-8 字节安全截断。
4. 实现 `build_preview_result(original, original_bytes, spill_path)`，返回保留原 id、工具名、状态和耗时的新 `ToolResult`。

**验证**：`tests/test_compact_layer1.py` 覆盖预览不超过 20 行和 2048 字节、重复落盘不改 `mtime`。

## T7: 实现第一层 offload_and_snip

**文件**：`src/coco_code/compact/layer1.py`  
**依赖**：T3、T6

**步骤**：
1. 实现 `offload_and_snip(items, state, session) -> (new_items, offloaded_count)`。
2. 按 `AssistantToolCallItem` / `AssistantToolCallsItem` 后续 `ToolResultItem` 识别同一批工具结果。
3. 每批先处理单条超过 50000 字节的结果，再处理剩余聚合超过 200000 字节的结果。
4. 对每个 tool call id 只通过 `ContentReplacementState.decide_once` 决策一次。
5. 落盘失败返回 `skip`，保持原结果，下轮继续评估。

**验证**：`tests/test_compact_layer1.py` 覆盖单条压缩、批量最小数量压缩、决策冻结、落盘失败降级、不会切换同一 id 的结果。

## T8: 实现摘要 prompt

**文件**：`src/coco_code/compact/summary_prompt.py`  
**依赖**：T1

**步骤**：
1. 定义固定摘要指令，包含 `<analysis>` 草稿和 `<summary>` 正式摘要。
2. 固定 9 个小节标题：主要请求和意图、关键技术概念、文件和代码段、错误和修复、问题解决过程、所有用户消息原文、待办任务、当前工作、可能的下一步。
3. 实现 `serialize_conversation(items)`，把用户/assistant/工具调用/工具结果序列化成可读文本。
4. 实现 `build_summary_prompt(items)`，返回单条 `ChatMessage(role="user", content=...)`。
5. 实现 `extract_summary(raw)` 和 `validate_summary(summary)`。

**验证**：`tests/test_compact_summary_prompt.py` 覆盖 prompt 禁止工具、9 小节存在、只提取 `<summary>`、缺小节判失败。

## T9: 实现恢复三段渲染

**文件**：`src/coco_code/compact/recovery.py`  
**依赖**：T4、T5

**步骤**：
1. 定义固定 `BOUNDARY_NOTICE`。
2. 实现 `render_file_block(record)`，超过 5000 token 估算上限时保留头部并追加 `(content truncated)`。
3. 实现 `render_tools_block(specs)`，渲染工具名、描述和参数 schema 摘要。
4. 实现 `build_recovery_attachment(recovery, tools)`，拼接最近文件、当前工具和边界提示三段。

**验证**：`tests/test_compact_recovery.py` 覆盖只取最近 5 个文件、超长截断、工具列表与 registry specs 一致、边界提示稳定。

## T10: 实现近期尾部选择和消息分组

**文件**：`src/coco_code/compact/layer2.py`  
**依赖**：T5

**步骤**：
1. 实现 `pick_recent_tail(items)`，从尾部累加直到同时满足 10000 token 和 5 条。
2. 截断点若落在工具调用和工具结果中间，继续向前扩展到工具调用之前。
3. 实现 `group_by_user_turn(items)`，按“用户提交 + 后续 assistant/tool 往返”分组。

**验证**：`tests/test_compact_layer2.py` 覆盖双下界、工具配对修正、分组不拆工具批次。

## T11: 实现摘要调用和 PTL 重试

**文件**：`src/coco_code/compact/layer2.py`  
**依赖**：T8、T10

**步骤**：
1. 实现 `summarize_once(provider, items)`，调用 `provider.stream(summary_prompt, tools=None)`。
2. 若 stream 返回工具调用、空摘要、缺失结构或 error，抛出 compact 错误。
3. 实现 `ptl_retry(input, items)`，摘要自身 PTL 时按分组丢弃策略重试。
4. 前 3 次每次丢最旧 1 组，之后每次丢剩余 20% 且至少 1 组。

**验证**：`tests/test_compact_layer2.py` 覆盖无工具请求、PTL 丢组重试、非 PTL 错误不重试、消息耗尽时报错。

## T12: 实现 run_summary / auto_compact / force_compact

**文件**：`src/coco_code/compact/layer2.py`  
**依赖**：T9、T10、T11

**步骤**：
1. 实现 `run_summary(input)`：生成摘要，构建恢复段，选择近期原文，拼成新历史。
2. 摘要和恢复段合并为一条 user 消息。
3. 若摘要 user 后紧接近期原文 user，插入简短 assistant 衔接消息。
4. 实现 `auto_compact(input)`：成功清零熔断，失败累加熔断。
5. 实现 `force_compact(input)`：不读写自动熔断。

**验证**：`tests/test_compact_layer2.py` 覆盖 9 部分摘要、恢复三段、近期原文、熔断成功清零和失败累加。

## T13: 实现 manage_context

**文件**：`src/coco_code/compact/manager.py`、`src/coco_code/compact/__init__.py`  
**依赖**：T7、T12

**步骤**：
1. 定义 `TriggerKind`、`ManageInput`、`ManageOutput`。
2. 实现 `AUTO`：先 layer1，写回 conversation，重新估算；达阈值且未熔断时 layer2。
3. 实现 `MANUAL`：跳过 layer1、阈值和熔断，直接 force compact。
4. 实现 `EMERGENCY`：先强制 layer1，再 force compact。
5. 在 `__init__.py` 重导出主要入口和状态类型。

**验证**：`tests/test_compact_manager.py` 覆盖三种 trigger、阈值判断、熔断跳过、before/after token。

## T14: 增加 Conversation 整体替换接口

**文件**：`src/coco_code/conversation.py`  
**依赖**：无

**步骤**：
1. 新增 `replace_items(items: Sequence[ConversationItem]) -> None`。
2. 写入时拷贝输入序列，避免外部继续修改内部列表。
3. 保持 `items()` 仍返回拷贝。

**验证**：`tests/test_conversation.py` 覆盖替换顺序、替换后外部列表修改不影响 conversation。

## T15: 增加 SessionRuntime

**文件**：`src/coco_code/agent/runtime.py`  
**依赖**：T2、T3、T4

**步骤**：
1. 定义 `SessionRuntime` dataclass。
2. 提供 `new_session_runtime(workspace, context_window)` 工厂，组装 session、replacement、recovery、circuit breaker 和 lock。
3. 默认 `context_window` 可先传 0，provider 激活后再写入有效值。

**验证**：`python -c "from coco_code.agent.runtime import new_session_runtime"` 不报错；相关 state 创建完整。

## T16: 增加 context_window 配置

**文件**：`src/coco_code/config.py`  
**依赖**：无

**步骤**：
1. `ProviderConfig` 增加 `context_window: int = 0`。
2. `_parse_provider` 读取可选 `context_window`；缺失为 0，非整数或负数报 `ConfigError`。
3. 增加 `effective_context_window(provider)`。
4. Anthropic 默认 200000；OpenAI 和 OpenAI-compatible 默认 128000。

**验证**：`tests/test_config.py` 覆盖未配置、0、正数、非法值、不同 protocol 默认值。

## T17: 增加 PromptTooLongError

**文件**：`src/coco_code/llm/__init__.py`  
**依赖**：无

**步骤**：
1. 定义 `class PromptTooLongError(RuntimeError): pass`。
2. 加入 `__all__` 导出。

**验证**：`python -c "from coco_code.llm import PromptTooLongError"` 不报错。

## T18: OpenAI provider usage 与 PTL 包装

**文件**：`src/coco_code/llm/openai_provider.py`  
**依赖**：T17

**步骤**：
1. 在 stream 请求中尽量启用 usage 回传。
2. 增加从 chunk 或最终事件提取 usage 的逻辑，并 yield `StreamEvent(usage=...)`。
3. 捕获 OpenAI SDK 上下文过长错误，包装为 `PromptTooLongError`。
4. 其他错误保持现有 `StreamEventType.ERROR` 行为。

**验证**：`tests/test_llm_events.py` 增加 OpenAI usage 和 PTL 包装用例。

## T19: Anthropic provider usage 与 PTL 包装

**文件**：`src/coco_code/llm/anthropic_provider.py`  
**依赖**：T17

**步骤**：
1. 从 Anthropic stream 事件或最终消息中提取 usage。
2. yield 统一 `StreamEvent(usage=...)`。
3. 捕获 `prompt is too long` / `prompt_too_long` 相关错误并包装为 `PromptTooLongError`。
4. 其他错误保持现有 error 事件。

**验证**：`tests/test_llm_events.py` 增加 Anthropic usage 和 PTL 包装用例。

## T20: 增加 compact 事件类型

**文件**：`src/coco_code/agent/types.py`  
**依赖**：无

**步骤**：
1. 增加 `CompactPhase` 和 `CompactEvent`。
2. `AgentEventType` 增加 `COMPACT`。
3. `AgentEvent` 增加 `compact: CompactEvent | None = None`。

**验证**：现有 `tests/test_agent_loop.py` 不需要修改即可继续导入；新增 compact event 构造测试。

## T21: 传递 usage 到 AgentLoop

**文件**：`src/coco_code/agent/stream.py`、`src/coco_code/agent/types.py`  
**依赖**：T20

**步骤**：
1. `StreamTurnResult` 增加 `usage: dict[str, int] | None = None`。
2. `collect_stream_turn` 记录最后一次非空 usage。
3. 保持原先每次 usage 事件仍通过 callback 发 `AgentEventType.USAGE`。
4. 返回 `StreamTurnResult(..., usage=last_usage)`。

**验证**：扩展 `tests/test_agent_loop.py` 或 `tests/test_llm_events.py`，确认 fake provider usage 能进入 result。

## T22: AgentLoop 接入 runtime 和自动压缩

**文件**：`src/coco_code/agent/loop.py`  
**依赖**：T13、T15、T20、T21

**步骤**：
1. `AgentLoop.__init__` 增加 `runtime: SessionRuntime | None = None`。
2. 未传 runtime 时用当前 workspace 和默认窗口创建测试 runtime。
3. `run()` 入口使用 `async with runtime.lock`。
4. 每次 provider 请求前计算估算 token，构造 `ManageInput(trigger=AUTO)`。
5. 若预计会触发自动摘要，yield `COMPACT BEFORE_AUTO`；结束后 yield `AFTER_AUTO`。
6. 调用 `manage_context` 后再进入 `_collect_turn_stream`。
7. 模型正常返回 usage 时更新 `runtime.usage_anchor` 和 `runtime.anchor_item_len`。

**验证**：`tests/test_agent_loop.py` 增加自动压缩事件、usage anchor 更新用例。

## T23: AgentLoop 记录 ReadFile 文件快照

**文件**：`src/coco_code/agent/loop.py`  
**依赖**：T4、T22

**步骤**：
1. 在工具结果写入 conversation 之前检查执行结果。
2. 当工具名为 `ReadFile` 且结果成功时，从 `result.data["path"]` 或 call 参数中取得路径。
3. 使用 workspace 解析为绝对路径。
4. 用 `asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")` 或等价方式读取纯净文件内容。
5. 调用 `runtime.recovery.record_file(abs_path, content)`。
6. 读取失败静默跳过。

**验证**：`tests/test_agent_loop.py` 增加 ReadFile 后 recovery snapshot 包含文件内容的用例。

## T24: AgentLoop 紧急压缩和一次重试

**文件**：`src/coco_code/agent/loop.py`  
**依赖**：T13、T17、T22

**步骤**：
1. 当 `_collect_turn_task` 得到 `PromptTooLongError` 时，不写入部分 assistant 回复。
2. 用迭代级 `emergency_retried` 防止重复紧急压缩。
3. yield `COMPACT BEFORE_EMERGENCY`。
4. 调用 `manage_context(trigger=EMERGENCY)`。
5. 成功后重置 usage anchor 和 anchor length。
6. 重新估算 token，低于 `context_window - 3000` 才重试 provider 请求一次。
7. 重试仍 PTL 时按错误结束，不再第二次压缩。

**验证**：`tests/test_agent_loop.py` 增加紧急压缩成功、第二次 PTL 不重复、压缩后仍过大不重试。

## T25: 提供手动压缩入口给 TUI

**文件**：`src/coco_code/agent/loop.py`  
**依赖**：T13、T22

**步骤**：
1. 增加 `run_force_compact(...) -> ManageOutput` 或等价 helper。
2. 方法获取 `runtime.lock`。
3. 构造 `ManageInput(trigger=MANUAL)`，调用 `manage_context`。
4. 返回 `ManageOutput`，异常交给 TUI 展示。

**验证**：`tests/test_agent_loop.py` 增加手动压缩跳过自动熔断的用例。

## T26: 新增 TUI 命令分发

**文件**：`src/coco_code/tui/commands.py`  
**依赖**：T25

**步骤**：
1. 新建 `commands.py`。
2. 实现 `dispatch_command(app, text) -> bool`。
3. 迁移现有 `/exit`、`/plan`、`/do` 行为，保持语义不变。
4. 新增 `/compact`：不写入 conversation，不发送给 LLM，调用手动压缩入口。
5. 未知斜杠命令显示可用命令提示。
6. 实现 `format_compact_notice(event_or_output)` 供自动、紧急、手动复用。

**验证**：`tests/test_tui_app.py` 覆盖 `/compact`、未知命令、已有三个命令回归。

## T27: TUI App 接入 runtime、命令和 compact notice

**文件**：`src/coco_code/tui/app.py`  
**依赖**：T15、T16、T20、T26

**步骤**：
1. `CoCoCodeApp.__init__` 创建或接收 `SessionRuntime`。
2. provider 激活后设置 `runtime.context_window = effective_context_window(provider_cfg)`。
3. `_run_agent_turn` 构造 `AgentLoop(..., runtime=self.runtime)`。
4. `prompt_submitted` 先调用 `dispatch_command`，命中则返回。
5. `handle_agent_event` 新增 compact 事件渲染。

**验证**：`tests/test_tui_app.py` 确认命令路径不进入 conversation，compact notice 能写入 history。

## T28: CLI 创建 runtime

**文件**：`src/coco_code/cli.py`  
**依赖**：T15、T16

**步骤**：
1. 启动时调用 `new_session_runtime(root, context_window=0)`。
2. 把 runtime 传给 `CoCoCodeApp`。
3. 单 provider 时可提前设置 context window；多 provider 时由 app 激活 provider 后设置。

**验证**：启动 app 后 `.mewcode/sessions/<id>/tool-results/` 目录存在。

## T29: 更新配置示例和 gitignore

**文件**：`.coco-code/config.yaml.example`、`.gitignore`  
**依赖**：T16

**步骤**：
1. 如果 `.coco-code/config.yaml.example` 不存在，按 README 中的配置示例创建。
2. 在 provider 示例中加入 `context_window` 注释。
3. `.gitignore` 显式追加 `.mewcode/sessions/`。

**验证**：`python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.coco-code/config.yaml.example').read_text(encoding='utf-8'))"` 不报错；创建 `.mewcode/sessions/x/tool-results/y` 后 `git status --short` 不显示该路径。

## T30: compact 单元测试补齐

**文件**：`tests/test_compact_state.py`、`tests/test_compact_token.py`、`tests/test_compact_layer1.py`、`tests/test_compact_summary_prompt.py`、`tests/test_compact_recovery.py`、`tests/test_compact_layer2.py`、`tests/test_compact_manager.py`  
**依赖**：T1-T13

**步骤**：
1. 为每个 compact 模块建立对应测试文件。
2. 覆盖 spec AC1-AC11、AC18-AC20、AC22-AC23 的纯逻辑部分。
3. fake provider 必须不访问网络。

**验证**：`pytest tests/test_compact_*.py` 通过。

## T31: Conversation / Config / LLM 测试补齐

**文件**：`tests/test_conversation.py`、`tests/test_config.py`、`tests/test_llm_events.py`  
**依赖**：T14、T16、T18、T19

**步骤**：
1. `test_conversation.py` 增加 `replace_items` 用例。
2. `test_config.py` 增加 `context_window` 和默认窗口用例。
3. `test_llm_events.py` 增加 OpenAI / Anthropic usage 和 PTL 包装用例。

**验证**：`pytest tests/test_conversation.py tests/test_config.py tests/test_llm_events.py` 通过。

## T32: Agent / TUI 集成测试补齐

**文件**：`tests/test_agent_loop.py`、`tests/test_tui_app.py`  
**依赖**：T22-T27

**步骤**：
1. Agent fake provider 支持按调用次数返回 text、tool call、usage、PTL error。
2. 覆盖自动压缩、usage anchor、ReadFile recovery、紧急压缩成功、紧急重试失败、手动压缩绕过熔断。
3. TUI 覆盖 `/compact` 不发普通 LLM、未知命令提示、`/exit`、`/plan`、`/do` 回归。
4. TUI 覆盖自动/紧急 compact notice 文案。

**验证**：`pytest tests/test_agent_loop.py tests/test_tui_app.py` 通过。

## T33: 全量静态检查和测试

**文件**：全项目  
**依赖**：T30-T32

**步骤**：
1. 运行格式和 lint。
2. 运行类型检查。
3. 运行全量测试。
4. 若出现与本章无关的既有失败，记录失败并确认未被本章改动扩大。

**验证**：
```powershell
python -m ruff check src tests
python -m mypy src
python -m pytest
```

## T34: 手动冒烟

**文件**：无  
**依赖**：T33

**步骤**：
1. 使用临时配置把 `context_window` 设为较小但大于 33000 的值。
2. 启动 `python -m coco_code`。
3. 读取一个超过 50000 字节的文件，确认 `.mewcode/sessions/<id>/tool-results/<tool_call_id>` 写入。
4. 下一轮确认工具结果以预览形式回放。
5. 输入 `/compact`，确认显示 token 变化。
6. 输入 `/unknown`，确认不发送给 LLM。
7. 人工触发或 mock `prompt_too_long`，确认紧急压缩只重试一次。

**验证**：完成以上步骤，TUI 不崩溃，`git status --short` 不显示 `.mewcode/sessions/`。

## 执行顺序

```text
T1
  -> T2 -> T3 -> T7 -> T13
  -> T4 -> T9 -> T12 -> T13
  -> T5 -> T10 -> T11 -> T12
  -> T6 -> T7

T14 -> T22
T15 -> T22 -> T23 -> T24 -> T25
T16 -> T27 -> T28
T17 -> T18/T19 -> T24
T20/T21 -> T22
T25 -> T26 -> T27

T1-T13 -> T30
T14/T16/T18/T19 -> T31
T22-T27 -> T32
T30-T32 -> T33 -> T34
```

可并行：

- T5、T8、T14、T16、T17 可以并行启动。
- T18 和 T19 可以并行。
- T30 内各 `test_compact_*` 可以按模块并行编写。
- T31 与 T32 可在对应实现任务完成后并行补测试。
