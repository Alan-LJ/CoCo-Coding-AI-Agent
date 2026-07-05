# Context Management Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。本文档以当前 `coco_code` 仓库结构为准。

## 实现完整性

### 包与目录结构

- [ ] **C1**：`src/coco_code/compact/` 子包存在，可被其他模块导入。
  - 验证：`Get-ChildItem src/coco_code/compact` 列出 `__init__.py`、`constants.py`、`manager.py`、`layer1.py`、`layer2.py`、`summary_prompt.py`、`recovery.py`、`token.py`、`state.py`。
  - 验证：`python -c "import coco_code.compact"` 退出码为 0。
  - 验证：`Get-ChildItem tests/test_compact_*.py` 能看到 compact 各模块测试文件。

- [ ] **C2**：上下文管理阈值常量集中在 `src/coco_code/compact/constants.py`，业务代码通过常量名引用。
  - 验证：`rg -n "50_000|200_000|20_000|13_000|3_000|10_000|5_000|0\\.2|3\\.5|2048" src/coco_code/compact` 的业务源码命中点集中在 `constants.py`，其他模块只出现常量名。
  - 验证：provider 默认窗口只在 `src/coco_code/config.py` 定义和导出，`effective_context_window` 可直接导入。

### 状态对象

- [ ] **C3**：会话状态构造函数返回完整实例，并自动建立落盘目录。
  - 验证：运行最小程序调用 `new_session_context(Path.cwd())`，返回的 `session_id` 形如 `<unix_ts>-<hex>`。
  - 验证：返回的 `spill_dir` 指向 `.mewcode/sessions/<session_id>/tool-results/`，且物理目录存在。
  - 验证：连续调用两次得到不同 `session_id`。

- [ ] **C4**：替换决策账本提供“已见”和“已替换”两本独立簿子。
  - 验证：单元测试用 `kept` / `replaced` / `skip` 组合检查：`kept` 后 `_seen_ids` 命中、`_replacements` 不命中；`replaced` 后两者都命中且返回值稳定；`skip` 后两者都不命中。

- [ ] **C5**：自动摘要熔断器支持读状态、记录失败、记录成功、判断跳闸。
  - 验证：单元测试连续调用 `record_failure` 三次后 `tripped()` 返回 `True`。
  - 验证：再调用一次 `record_success` 后 `tripped()` 返回 `False`。

- [ ] **C6**：文件追踪状态并发安全，对外只暴露快照拷贝。
  - 验证：`pytest tests/test_compact_recovery.py -k concurrent` 通过，覆盖 50 个并发 `record_file` + `snapshot`。
  - 验证：修改 `snapshot()` 返回列表不会影响下一次 `snapshot()` 的结果。

### 两层压缩

- [ ] **C7**：第 1 层提供单条落盘、聚合落盘、幂等、决策冻结四种行为。
  - 验证：对 60K 字符单条工具结果运行两次 `offload_and_snip`，第二次输出与第一次逐字节一致。
  - 验证：对 3 条 80K 字符的同批工具结果运行 `offload_and_snip` 后，该批剩余 payload 合计低于 200K 阈值。
  - 验证：被判定保留原文的同一 `tool_call_id` 在后续请求前仍保持原文，不再被替换。

- [ ] **C8**：第 1 层落盘失败不阻断主流程。
  - 验证：把 `spill_dir` 设为不可写路径后运行 `offload_and_snip`，工具结果保持原文。
  - 验证：该 `tool_call_id` 未被写入“已见”账本，下轮仍会重新评估。

- [ ] **C9**：工具结果预览体包含原始大小、头部预览、落盘路径、重读提示，并保留协议 id。
  - 验证：预览 payload 中能找到 `original size:`、`head preview`、落盘路径尾段、`文件读取工具`、`不要凭头部预览猜测` 等稳定标志。
  - 验证：头部预览同时不超过 20 行和 2048 UTF-8 字节。
  - 验证：预览结果保留原 `tool_call_id`、`tool_name`、成功/失败状态和耗时字段。
  - 验证：相同输入连续两次构造预览体，结果逐字节相等。

- [ ] **C10**：第 2 层摘要 prompt 要求“分析草稿 + 正式摘要”，正式摘要包含 9 个固定小节。
  - 验证：抓取摘要请求 messages，最后一条 user 内容包含禁止调用工具的明确说明、`<analysis>`、`<summary>`，以及 9 个小节标题。
  - 验证：provider 请求的工具定义为 `None` 或空集合。
  - 验证：解析摘要返回结果时，`<summary>` 之外的内容被丢弃。
  - 验证：返回工具调用、空摘要或缺失固定小节时，本次摘要被判定为失败。

- [ ] **C11**：恢复段拼装三块内容：最近读过的文件、当前可用工具、边界提示消息。
  - 验证：调用 `build_recovery_attachment(recovery, tools)` 后，输出文本包含三段标题。
  - 验证：超过 5 条文件记录时仅输出最近 5 条，较旧文件路径不出现。
  - 验证：单文件超过 5000 token 估算上限时保留头部内容，并追加 `(content truncated)`。
  - 验证：工具段渲染的工具名集合与本轮传给 provider 的工具集合一致。

- [ ] **C12**：边界提示消息文案稳定，不在两次调用之间漂移。
  - 验证：相同 snapshot 与 tools 输入下，连续两次 `build_recovery_attachment` 的边界提示段逐字节一致。
  - 验证：边界提示明确说明需要细节时重新读取文件或工具输出，不能根据摘要脑补代码。

### Token 估算

- [ ] **C13**：估算函数支持 usage 锚点和字符增量两种来源，返回 `int`。
  - 验证：`estimate_tokens(0, [], 0)` 返回 0。
  - 验证：`anchor=5000`、新增 350 字符 ASCII 内容时，返回 `5000 + ceil(350 / 3.5)`。
  - 验证：`usage_anchor` 把 `input_tokens`、`output_tokens`、`cache_read`、`cache_write` 四个字段按缺失为 0 合并为 int。

- [ ] **C13a**：估算 token 远低于自动阈值时，`manage_context` 不进入 layer2。
  - 验证：构造 `estimated_tokens = threshold - 1`，调用 `manage_context(trigger=AUTO)` 后 fake provider 的摘要请求计数为 0。
  - 验证：构造 `estimated_tokens = threshold + 1`，调用后摘要请求计数为 1。

### 手动入口与命令分发

- [ ] **C14**：TUI 输入以 `/` 开头时走命令路径，不发给 LLM。
  - 验证：注入 mock agent，输入 `/compact` 后 `stream` 调用次数为 0，手动压缩调用次数为 1。
  - 验证：输入 `/unknown` 后 `stream` 调用次数为 0，scrollback 出现未知命令提示和可用命令列表。

- [ ] **C15**：Agent 暴露手动压缩 helper 给 TUI 调用。
  - 验证：`AgentLoop` 提供 `run_force_compact` 或等价入口，返回 `ManageOutput`。
  - 验证：TUI 能使用返回的 `before_tokens` 和 `after_tokens` 拼出压缩完成消息。
  - 验证：压缩异常向 TUI 返回可展示错误，不导致 App 退出。

### 紧急压缩与哨兵异常

- [ ] **C16**：`coco_code.llm.PromptTooLongError` 哨兵异常存在，并被 provider 包装。
  - 验证：`python -c "from coco_code.llm import PromptTooLongError"` 成功。
  - 验证：OpenAI provider 模拟上下文过长 SDK 异常时，输出的 `StreamEvent.error` 是 `PromptTooLongError`，且 `__cause__` 是原异常。
  - 验证：Anthropic provider 模拟 `prompt_too_long` / `prompt is too long` 时同样包装为 `PromptTooLongError`。
  - 验证：非上下文过长错误不被误包装。

### 配置

- [ ] **C17**：`ProviderConfig` 新增 `context_window` 字段，并能从 YAML 解码。
  - 验证：构造包含 `context_window: 80000` 的 YAML，`load_config` 后对应 provider 的 `context_window == 80000`。
  - 验证：缺失字段时默认为 0，负数或非整数时报 `ConfigError`。

- [ ] **C18**：`effective_context_window(provider)` 在不同 provider 和配置下返回正确值。
  - 验证：Anthropic 未配置返回 200000。
  - 验证：OpenAI / OpenAI-compatible 未配置或配置 0 返回 128000。
  - 验证：Anthropic 配置 `context_window: 80000` 返回 80000。
  - 验证：未知 protocol 未配置时返回保守默认 200000。

## 集成

### compact 与 conversation

- [ ] **I1**：`Conversation` 提供 `replace_items` 入口，且做拷贝写入。
  - 验证：构造 2 条会话项调用 `replace_items` 后，再修改原列表，`Conversation.items()` 输出不被污染。
  - 验证：传空列表不抛异常，后续 `items()` 长度为 0。

- [ ] **I2**：`manage_context` 成功后，conversation 内存历史被替换为新序列。
  - 验证：fake provider 触发一次 layer2 摘要后，`conv.items()` 结构为“摘要 + 恢复段”的 user 消息，加上近期原文 tail。
  - 验证：压缩前后的 `before_tokens`、`after_tokens` 均为非负整数，且成功压缩场景下 `before_tokens > after_tokens`。

### compact 与 agent

- [ ] **I3**：Agent 本轮迭代选出的工具集合同时传给 `ManageInput.tools` 和 provider stream。
  - 验证：同一轮内 `manage_context` 拿到的 `ToolRegistry` 与 provider 请求使用的是同一对象或等价工具集合。
  - 验证：Plan Mode 使用只读工具集合，Default Mode 使用完整工具集合。
  - 验证：恢复段渲染出的工具名和 schema 与 provider 请求中的工具定义一一对应。

- [ ] **I4**：每轮主对话 stream 完成后，用最后一次 usage 更新锚点，语义是替换而不是累加。
  - 验证：fake provider 连续 3 轮返回 usage 合计 1000、1500、2200，`runtime.usage_anchor` 依次变为 1000、1500、2200。
  - 验证：`runtime.anchor_item_len` 更新为收到 usage 时的 `Conversation.items()` 长度。

- [ ] **I4-bis**：摘要请求不更新主对话 usage 锚点。
  - 验证：fake provider 让摘要请求也返回 usage，摘要成功后 `runtime.usage_anchor` 仍等于最近一次主对话 usage 合计。

- [ ] **I5**：`ReadFile` 工具成功后，Agent 用纯净文件内容写入 `RecoveryState`。
  - 验证：调用 `ReadFile` 读一个本地文件，`recovery.snapshot()` 包含该绝对路径。
  - 验证：记录内容与磁盘原文逐字节相等，不含 UI 行号、代码围栏或工具渲染前缀。

- [ ] **I6**：主对话遇到 `PromptTooLongError` 时进入紧急压缩并就地重试一次。
  - 验证：fake provider 第 1 次主 stream 返回 `PromptTooLongError`，紧急压缩后的第 2 次 stream 正常完成，整体 run 成功结束。
  - 验证：紧急压缩后的重试再次返回 `PromptTooLongError` 时，Agent 上抛或返回错误，不进入第三次主 stream。

### compact 与 TUI

- [ ] **I7**：TUI 命令分发表注册四项：`/exit`、`/plan`、`/do`、`/compact`。
  - 验证：`rg -n "/compact|/exit|/plan|/do" src/coco_code/tui/commands.py` 命中四项。
  - 验证：未知斜杠命令显示可用命令列表，不进入普通对话。
  - 验证：迁移后 `/exit` 仍退出，`/plan` 仍切 plan 模式，`/do` 仍切 default 模式并启动一轮 run。

- [ ] **I8**：`/compact` 处理完成后，TUI 输出带 token 数对比的系统消息。
  - 验证：mock agent 返回 `before_tokens=120000, after_tokens=42000`，TUI 输出包含两个数字。
  - 验证：mock agent 返回 `before_tokens=500, after_tokens=300` 也能显示，不因低于自动阈值而拦截。
  - 验证：mock agent 抛异常时，TUI 输出 `压缩失败`，App 不退出。

- [ ] **I12**：手动 `/compact` 与正在运行的 agent turn 串行执行。
  - 验证：构造慢响应 fake provider，同时触发普通 run 和 `run_force_compact`，两者按 `runtime.lock` 顺序完成，没有并发修改 conversation。

### compact 与 config / 会话目录

- [ ] **I9**：CLI / App 启动时把 `effective_context_window(provider)` 注入 `SessionRuntime`。
  - 验证：运行 `python -m coco_code`，Anthropic provider 未配置 `context_window` 时 runtime 拿到 200000。
  - 验证：配置 `context_window: 100000` 后 runtime 拿到 100000。

- [ ] **I10**：`.coco-code/config.yaml.example` 展示 `context_window` 字段用法与默认值说明。
  - 验证：打开示例文件，能看到 `context_window` 字段和“未配置时按 protocol 默认”的说明。
  - 验证：`python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.coco-code/config.yaml.example').read_text(encoding='utf-8'))"` 不报错。

- [ ] **I11**：进程启动后 `.mewcode/sessions/<id>/tool-results/` 物理目录被创建，并被 Git 忽略。
  - 验证：启动后 `Get-ChildItem .mewcode/sessions` 出现新子目录，子目录名形如 `<unix_ts>-<hex>`。
  - 验证：进程退出后该目录依然保留，下次启动会再开新子目录。
  - 验证：创建 `.mewcode/sessions/x/tool-results/y` 后，`git status --short` 不显示该路径。

### compact 状态事件

- [ ] **I13**：自动压缩触发时，Agent yield `CompactEvent(BEFORE_AUTO)` 与 `CompactEvent(AFTER_AUTO)` 一对事件；阈值未达时不 yield。
  - 验证：`test_agent_emits_auto_compact_events` 收集 run async generator 事件，compact phase 序列为 `[BEFORE_AUTO, AFTER_AUTO]`。
  - 验证：`AFTER_AUTO` 的 `before_tokens > after_tokens`，且 `error is None`。
  - 验证：估算 token 远低于阈值时，compact 事件数量为 0。

- [ ] **I14**：紧急压缩触发时，Agent yield `BEFORE_EMERGENCY` 与 `AFTER_EMERGENCY` 一对事件。
  - 验证：fake provider 返回 `PromptTooLongError` 后，事件序列中出现 `[BEFORE_EMERGENCY, AFTER_EMERGENCY]`。
  - 验证：紧急压缩失败时 `AFTER_EMERGENCY.error is not None`。

- [ ] **I15**：TUI 对 compact 事件优先走统一渲染分支。
  - 验证：自动压缩开始时 scrollback 出现 `正在压缩上下文`。
  - 验证：紧急压缩开始时 scrollback 出现 `上下文撞墙，自动压缩中`。
  - 验证：压缩完成消息由 `format_compact_notice` 统一格式化，手动、自动、紧急完成态文案结构一致。

## 编译与测试

- [ ] **B1**：项目语法检查通过。
  - 验证：`python -m compileall src/coco_code` 退出码 0。
  - 验证：`python -c "import coco_code"` 成功。

- [ ] **B2**：lint 检查通过。
  - 验证：`python -m ruff check src tests` 无错误。

- [ ] **B3**：类型检查通过。
  - 验证：`python -m mypy src` 无本章新增错误；若仓库已有类型失败，报告与本章无关的既有失败。

- [ ] **B4**：compact 纯逻辑测试通过。
  - 验证：`python -m pytest tests/test_compact_*.py` 全部通过。
  - 覆盖：状态对象、token 估算、第 1 层落盘、第 2 层摘要、摘要 prompt、恢复段、manager 三种 trigger。

- [ ] **B5**：Conversation 测试通过。
  - 验证：`python -m pytest tests/test_conversation.py` 通过，覆盖 `replace_items` 拷贝语义。

- [ ] **B6**：Config 测试通过。
  - 验证：`python -m pytest tests/test_config.py` 通过，覆盖 `context_window` 和默认窗口。

- [ ] **B7**：LLM event 测试通过。
  - 验证：`python -m pytest tests/test_llm_events.py` 通过，覆盖 usage 回传和 `PromptTooLongError` 包装。

- [ ] **B8**：Agent 集成测试通过。
  - 验证：`python -m pytest tests/test_agent_loop.py` 通过，覆盖自动压缩、usage anchor、ReadFile recovery、紧急压缩、手动压缩。

- [ ] **B9**：TUI 测试通过。
  - 验证：`python -m pytest tests/test_tui_app.py` 通过，覆盖 `/compact`、未知命令、现有命令回归和 compact notice。

- [ ] **B10**：全量测试通过。
  - 验证：`python -m pytest` 通过；若有既有失败，记录失败测试名并确认不是本章改动引入。

- [ ] **B11**：文档和实现中没有残留旧包路径、旧命令或旧测试目录。
  - 验证：用 `rg` 扫描旧包路径、旧模块名、旧测试目录、旧启动命令、旧整体替换接口名和旧工具消息类型名，`docs/context-management`、`src`、`tests` 下均无非预期命中。

## 端到端场景

### 场景 E1：长会话不撞墙

- [ ] **触发**：构造 fake provider 脚本，30 轮迭代每轮返回一个工具调用，工具结果约 30KB，并设置较小 `context_window`，例如 50000。
- [ ] **预期**：30 轮完整跑完，无未捕获异常；中途至少触发一次自动 layer2 摘要；最终 `conv.items()` 长度明显小于未压缩历史。
- [ ] **观察方式**：在测试中统计 layer2 触发次数和 compact event 数量，断言 async generator 正常结束。

### 场景 E2：单条大工具结果

- [ ] **触发**：fake provider 一轮返回一个工具调用，工具回填 80KB 字符串。
- [ ] **预期**：下一轮 stream 请求中，该工具结果 content 已被替换为预览体；`.mewcode/sessions/<id>/tool-results/<tool_call_id>` 文件存在，大小可还原完整 payload。
- [ ] **观察方式**：捕获第 N+1 次 stream 请求体检查预览字段；用 `Path(...).stat().st_size` 检查落盘文件。

### 场景 E3：单轮聚合超标

- [ ] **触发**：同一轮 assistant 工具调用对应 3 条 `ToolResultItem`，每条约 80KB。
- [ ] **预期**：按体积从大到小至少替换部分结果，直到该批结果请求可见 payload 合计低于 200K；未替换结果保持原文。
- [ ] **观察方式**：捕获下一轮 stream 请求，按同批 `tool_call_id` 汇总 payload 字节；检查 `spill_dir` 至少出现对应落盘文件。

### 场景 E4：决策冻结

- [ ] **触发**：同一个 `tool_call_id` 在第 N 轮被决定保留原文，继续跑到第 N+5 轮。
- [ ] **预期**：第 N+1 到 N+5 轮请求体中该工具结果始终保持原文。
- [ ] **触发**：另一个 `tool_call_id` 在第 M 轮被替换。
- [ ] **预期**：第 M+1 到 M+5 轮请求体中该工具结果使用与第 M 轮逐字节相同的预览体。
- [ ] **观察方式**：捕获多轮请求体，对同一 `tool_call_id` 的 content 做 `==` 比较。

### 场景 E5：手动 `/compact`

- [ ] **触发**：在 TUI 输入 `/compact`，此时估算 token 远低于自动阈值。
- [ ] **预期**：fake provider 收到一次不带工具的摘要请求，证明手动路径无视自动阈值；普通主对话 stream 未被调用。
- [ ] **预期**：conversation 被替换为“摘要 + 恢复段 + 近期原文”；TUI 输出 `已压缩，token 从 X 降至 Y`，X 和 Y 都是非负整数。
- [ ] **观察方式**：mock agent 统计 `run_force_compact` / `run` 调用次数；fake provider 捕获摘要请求体；TUI scrollback 断言。

### 场景 E6：紧急压缩

- [ ] **触发**：fake provider 在第 K 次主 stream 返回 `PromptTooLongError`。
- [ ] **预期**：Agent 先发 `BEFORE_EMERGENCY`，执行强制 layer1 + layer2，压缩成功后重置 usage anchor，再重试一次第 K 次请求。
- [ ] **预期**：重试成功则整体流程继续；重试再次 `PromptTooLongError` 时上抛或返回错误，不进入第三次主 stream。
- [ ] **观察方式**：fake provider 维护 `stream_calls` / `summarize_calls` 计数器，测试结束时断言调用次数。

### 场景 E7：熔断

- [ ] **触发 A**：让 fake provider 对自动摘要请求连续 3 次返回非 PTL 异常。
- [ ] **预期 A**：第 3 次失败后熔断器跳闸；第 4 次自动阈值命中时不再触发 layer2，轻量预防仍执行。
- [ ] **触发 B**：fake provider 摘要响应序列为 `[err, err, ok, err, err, err]`。
- [ ] **预期 B**：失败计数序列为 `[1, 2, 0, 1, 2, 3]`，证明成功会清零。
- [ ] **触发 C**：手动 `/compact` 在自动熔断后执行。
- [ ] **预期 C**：手动压缩仍走 force compact 路径，不被自动熔断器拦截。

### 场景 E8：压缩后恢复

- [ ] **触发**：压缩前先后读过 7 个不同文件，然后触发一次摘要。
- [ ] **预期**：压缩后下一轮请求首条 user 消息同时包含 9 部分摘要、最近 5 个文件块、当前工具列表和固定边界提示。
- [ ] **预期**：最近文件按时间倒序展示，较旧两个文件路径不出现；工具列表与 provider 请求工具集合一致。
- [ ] **观察方式**：捕获摘要后第一次 stream 请求 messages，按标题、路径、工具名和 schema 做断言。

### 场景 E9：多 provider context window

- [ ] **触发 1**：Anthropic provider 不配置 `context_window`。
- [ ] **预期 1**：runtime 拿到 200000，自动阈值为 `200000 - 20000 - 13000 = 167000`。
- [ ] **触发 2**：OpenAI provider 不配置 `context_window`。
- [ ] **预期 2**：runtime 拿到 128000，自动阈值为 `128000 - 20000 - 13000 = 95000`。
- [ ] **触发 3**：Anthropic provider 配置 `context_window: 100000`。
- [ ] **预期 3**：runtime 拿到 100000，自动阈值为 67000，手动/紧急阈值为 77000。

### 场景 E10：不切断 tool call / tool result

- [ ] **触发**：构造对话尾部形如 `[..., user, assistant(tool_calls=[A]), tool(result A), assistant(tool_calls=[B]), tool(result B)]`，让 `pick_recent_tail` 的自然截断点落在 `tool(result A)` 附近。
- [ ] **预期**：tail 第一条不可为孤立工具结果；若第一条 assistant 含 tool call，则 tail 内必须包含对应工具结果。
- [ ] **预期**：tail 同时满足至少 5 条和约 10000 token 的下界，且不会超过原始 items 长度。
- [ ] **观察方式**：单元测试直接调用 `pick_recent_tail` 并按上述条件断言。

### 场景 E11：摘要请求自身 PTL

- [ ] **触发 A**：fake provider 对前 3 次摘要请求返回 `PromptTooLongError`，第 4 次返回正常摘要。
- [ ] **预期 A**：前 3 次每次丢最旧 1 组后重试，第 4 次成功；失败计数清零。
- [ ] **触发 B**：fake provider 对前 4 次摘要请求都返回 PTL。
- [ ] **预期 B**：第 4 次之后切到按剩余组数 20% 丢弃，且每次至少丢 1 组。
- [ ] **触发 C**：fake provider 持续返回 PTL 直到消息组耗尽。
- [ ] **预期 C**：抛最后一次异常，不发送空 messages 摘要请求；自动路径失败计数 +1，手动/紧急路径不写自动熔断计数。

### 场景 E12：真实运行冒烟

- [ ] **触发**：安装依赖后启动 `python -m coco_code`，使用一个可工作的 provider 配置。
- [ ] **预期**：让 Agent 读取一个超过 50KB 的本地文件后，`.mewcode/sessions/<id>/tool-results/` 下出现对应落盘文件。
- [ ] **预期**：把 `context_window` 临时改成 80000，连续几轮对话后能看到自动压缩状态提示。
- [ ] **预期**：输入 `/compact` 看到 token 对比消息；输入 `/unknown` 看到友好提示，未发 LLM；输入 `/exit`、`/plan`、`/do` 行为与迁移前一致。
- [ ] **观察方式**：TUI 目测；用 `Get-ChildItem .mewcode/sessions` 和 `git status --short` 抽查落盘目录未进入 Git。

### 场景 E13：自动压缩 UX 状态提示

- [ ] **触发**：fake provider 脚本让某轮主对话开始前估算 token 跨越 `context_window - 20000 - 13000` 阈值，并让摘要请求延迟返回。
- [ ] **预期**：摘要请求开始前 TUI 已打印 `正在压缩上下文`。
- [ ] **预期**：摘要完成后 TUI 打印 `已压缩，token 从 <before> 降至 <after>`，其中 before 和 after 为非负整数，且 before > after。
- [ ] **观察方式**：收集 Agent events 和 TUI scrollback，断言 `BEFORE_AUTO` 在主对话 stream 启动前出现，`AFTER_AUTO` 在摘要完成后出现。

### 场景 E14：紧急压缩 UX 状态提示

- [ ] **触发**：fake provider 在主对话 stream 返回 `PromptTooLongError`，随后准备一次摘要响应和一次重试主对话响应。
- [ ] **预期**：PTL 发生后、紧急 `manage_context` 启动前，TUI 出现 `上下文撞墙，自动压缩中`。
- [ ] **预期**：紧急压缩成功后出现 `已压缩，token 从 X 降至 Y`，随后重试主对话继续渲染 Text / Tool 事件。
- [ ] **触发失败分支**：紧急摘要持续 PTL 到消息组耗尽，或重试主对话再次 PTL。
- [ ] **预期失败分支**：TUI 显示 `压缩失败`；`AFTER_EMERGENCY.error is not None`；不会发起第三次主 stream。
