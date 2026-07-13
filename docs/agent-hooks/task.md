# Hook 生命周期挂钩系统 Tasks

> 本任务清单使用用户提供的 Tasks 版本作为主骨架，并按当前仓库实际结构适配为 `src/coco_code/...` 与扁平 `tests/test_*.py` 测试布局。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/coco_code/permission/matcher.py` | Matcher Protocol、四种 matcher、字符串与结构化 matcher 编译 |
| 修改 | `src/coco_code/permission/rule.py` | `Rule` 持有 matcher，`parse_rule` 支持 exact/regex/not/glob |
| 修改 | `src/coco_code/permission/settings.py` | `to_rule_set` 输出解析失败日志并跳过坏规则 |
| 新建 | `tests/test_permission_matcher.py` | matcher 类型与边界条件覆盖 |
| 修改 | `tests/test_permission_rules.py` | 权限规则新语法与向后兼容测试 |
| 修改 | `tests/test_permission_settings_executor.py` | 配置解析失败 stderr 与跳过逻辑测试 |
| 新建 | `src/coco_code/hook/__init__.py` | Hook 包公共导出 |
| 新建 | `src/coco_code/hook/event.py` | 11 个事件枚举、blocking event 判定、payload helper |
| 新建 | `src/coco_code/hook/rule.py` | `HookRule`、`Condition`、`Action` 数据结构 |
| 新建 | `src/coco_code/hook/matcher.py` | payload 字段路径读取与条件求值 |
| 新建 | `src/coco_code/hook/loader.py` | YAML 解析、双层合并、集中校验 |
| 新建 | `src/coco_code/hook/executor.py` | shell/prompt/http/subagent 四类动作执行 |
| 新建 | `src/coco_code/hook/engine.py` | dispatch 主流程、once、async task、拦截结果 |
| 新建 | `tests/test_hook_loader.py` | loader 字段校验、加载错误、同名合并测试 |
| 新建 | `tests/test_hook_matcher.py` | payload 字段读取与 all/any 条件测试 |
| 新建 | `tests/test_hook_executor.py` | shell exit2、HTTP block、prompt、subagent stub 测试 |
| 新建 | `tests/test_hook_engine.py` | dispatch、拦截、prompt 注入、only_once、async 测试 |
| 修改 | `src/coco_code/agent/runtime.py` | 增加 Hook reminder、once 状态、后台 task 追踪 |
| 修改 | `src/coco_code/agent/loop.py` | 接入 PreUserMessage、PreCompact、PostCompact、Stop 与 prompt 注入 |
| 修改 | `src/coco_code/agent/tools.py` | 接入 PreToolUse、PostToolUse，支持 Hook 拦截工具结果 |
| 修改 | `tests/test_agent_loop.py` | AgentLoop Hook reminder、Stop、compact 事件测试 |
| 修改 | `tests/test_agent_tools.py` | 工具 Hook 拦截与 PostToolUse 测试 |
| 修改 | `src/coco_code/prompt.py` | 增加 Hook reminder 渲染区 |
| 修改 | `tests/test_prompt.py` | Hook reminder 不进入会话历史、只渲染到 system prompt |
| 修改 | `src/coco_code/tui/app.py` | TUI 持有 HookEngine，触发 session 级事件 |
| 修改 | `src/coco_code/tui/stream.py` | 用户提交前触发 UserPromptSubmit 并处理拦截 |
| 修改 | `src/coco_code/tui/commands.py` | `/clear`、resume、退出路径触发 SessionEnd/Start/Resume |
| 修改 | `src/coco_code/command/types.py` | `CommandUI` 增加 Hook 查询接口 |
| 修改 | `src/coco_code/command/handlers.py` | 新增 `/hooks` handler |
| 修改 | `src/coco_code/command/builtins.py` | 注册 `/hooks` 内置命令 |
| 修改 | `tests/test_command_builtins.py` | `/hooks` 命令注册与输出测试 |
| 修改 | `tests/test_tui_app.py` | SessionStart/End/Resume wiring 测试 |
| 修改 | `tests/test_tui_completion.py` 或新增 TUI 提交测试 | UserPromptSubmit 拦截路径测试 |
| 修改 | `src/coco_code/cli.py` | 启动期加载 HookEngine 并注入 App |
| 检查 | `pyproject.toml` | 确认 `httpx`、`pyyaml` 已存在；无缺失则不改 |

## T1: 实现权限 Matcher 抽象

**文件：** `src/coco_code/permission/matcher.py`  
**依赖：** 无  
**步骤：**
1. 新建 `Matcher(Protocol)`，定义 `match(value: str) -> bool`。
2. 实现 `ExactMatcher(value: str)`，整串相等时命中。
3. 实现 `GlobMatcher(pattern: str, path_like: bool = False)`，复用现有命令 glob 与路径 glob 语义。
4. 实现 `RegexMatcher(src: str, compiled: Pattern[str])`，用 `compiled.search(value)` 判定。
5. 实现 `NotMatcher(inner: Matcher)`，对内部 matcher 结果取反。
6. 从 `permission.rule` 迁出或复用 `_command_glob_to_regex`、`_path_glob_to_regex`、`_normalize_pathish`。
7. 实现 `compile_matcher(pattern: str, *, path_like: bool = False) -> Matcher`：`=value` 为 exact，`~regex` 为 regex，`!inner` 为 not，无前缀为 glob。
8. 实现 `compile_structured_matcher(raw: Mapping[str, Any], *, path_like: bool = False) -> Matcher`，支持 `{type: exact|glob|regex|not, value|inner}`。
9. 空 pattern、非法 regex、非法结构化 matcher 均抛 `ValueError`，错误信息可读。

**验证：** `python -c "from coco_code.permission.matcher import compile_matcher; print(compile_matcher('=foo').match('foo'))"` 输出 `True`

## T2: matcher 单元测试

**文件：** `tests/test_permission_matcher.py`  
**依赖：** T1  
**步骤：**
1. 覆盖 exact、glob、regex、not 四种类型的命中与不命中。
2. 验证 `=git status` 命中 `git status`，不命中 `git status -s`。
3. 验证 `~^npm (install|test)$` 命中 `npm install`，不命中 `npm run dev`。
4. 验证 `!=foo` 不命中 `foo`，命中 `bar`。
5. 验证 `!~^rm` 命中 `ls -lh`，不命中 `rm -rf .`。
6. 验证 `!git *` 命中 `npm install`，不命中 `git status`。
7. 验证 `~[invalid` 与空串抛 `ValueError`。
8. 验证结构化 matcher 的 exact、glob、regex、not 与非法结构。
9. 使用 `pytest.mark.parametrize` 表驱动，并给每条用例设置清晰 `id`。

**验证：** `pytest tests/test_permission_matcher.py -v` 通过

## T3: 升级权限 Rule 与 parse_rule

**文件：** `src/coco_code/permission/rule.py`  
**依赖：** T1  
**步骤：**
1. 将 `Rule.pattern: str` 改为 `Rule.matcher: Matcher | None`，新增 `raw_pattern: str = ""`。
2. 保留 `Rule.text()` 可读输出：无 pattern 输出工具名，有 pattern 输出 `Tool(pattern)`。
3. 将 `parse_rule` 改为返回 `tuple[Rule | None, str | None]`，失败时返回错误描述。
4. 解析出 `tool` 与 `pattern` 后调用 `compile_matcher`；空 pattern 使用 `matcher=None` 表示全匹配。
5. `RuleSet.find_match` 使用 `matcher.match(target)` 判定；`matcher is None` 直接命中。
6. 保留 `match_pattern` 兼容入口，内部委托给 `compile_matcher(pattern, path_like=...)`。
7. 保留 `escape_glob` 行为，避免影响现有自动生成的精确 glob 规则。

**验证：** `pytest tests/test_permission_rules.py -v` 不出现导入错误

## T4: 权限设置坏规则日志

**文件：** `src/coco_code/permission/settings.py`  
**依赖：** T3  
**步骤：**
1. 更新 `to_rule_set`，当 `parse_rule` 返回错误时向 stderr 输出 `rule '<raw>' parse failed: <err>`。
2. 失败规则不进入 `RuleSet.allow` 或 `RuleSet.deny`，其它规则继续加载。
3. 保持 `friendly_name`、`categorize`、`extract_target` 现有语义不变。

**验证：** `python -c "from coco_code.permission.settings import to_rule_set; print('ok')"` 输出 `ok`

## T5: 权限规则测试扩展

**文件：** `tests/test_permission_rules.py`、`tests/test_permission_settings_executor.py`  
**依赖：** T3、T4  
**步骤：**
1. 增加 `Bash(=git status)` 精确匹配测试。
2. 增加 `Bash(~^npm.*)` 正则匹配测试。
3. 增加 `Bash(!~^rm)` 反向正则测试。
4. 增加 `Write(**/*.py)` glob 向后兼容测试。
5. 用 `capsys` 捕获 stderr，验证非法规则被跳过且 stderr 含 `parse failed`。
6. 保持现有权限引擎 deny 优先、allow 次之、默认模式兜底测试全部通过。

**验证：** `pytest tests/test_permission_matcher.py tests/test_permission_rules.py tests/test_permission_settings_executor.py -v` 通过

## T6: Hook 包基础数据结构

**文件：** `src/coco_code/hook/__init__.py`、`src/coco_code/hook/event.py`、`src/coco_code/hook/rule.py`  
**依赖：** 无  
**步骤：**
1. `__init__.py` 导出 `Event`、`HookEngine`、`DispatchResult`、`load_hooks`。
2. `event.py` 定义 11 个 `Event(StrEnum)` 成员，字面量与 spec 完全一致。
3. 定义 `BLOCKING_EVENTS = frozenset({Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT})`。
4. 提供 `is_blocking(event: Event) -> bool` 与 `parse_event(value: str) -> Event | None`。
5. `rule.py` 定义 `AtomCondition`、`Condition`、`HookRule`、`ShellAction`、`PromptAction`、`HttpAction`、`SubagentAction`、`HookAction`。
6. `HookRule` 字段与 plan 对齐：`name`、`event`、`action`、`condition`、`only_once`、`async_mode`、`timeout_seconds`、`source`、`index`。
7. 定义 `Payload = Mapping[str, Any]` 或等价类型别名，供 loader/engine/executor 复用。

**验证：** `python -c "from coco_code.hook import Event; print(Event.PRE_TOOL_USE.value)"` 输出 `PreToolUse`

## T7: Hook 条件字段路径求值

**文件：** `src/coco_code/hook/matcher.py`、`tests/test_hook_matcher.py`  
**依赖：** T1、T6  
**步骤：**
1. 实现 `get_by_path(payload, path) -> str`，按 `.` 分隔读取嵌套 dict 字段。
2. 字段不存在、中途遇到 `None` 或非 dict 时返回空字符串。
3. 字段值是字符串时原样返回。
4. 字段值是 dict/list 时用 `json.dumps(value, sort_keys=True)` 转成稳定字符串。
5. 字段值是 bool/int/float 时用 `str(value)` 转成字符串。
6. 实现 `eval_condition(condition, payload) -> bool`，`None` 表示无条件命中。
7. `all_of` 要求全部原子条件命中，`any_of` 要求任一原子条件命中。
8. 测试字段缺失、嵌套读取、dict/list 稳定序列化、all_of、any_of。

**验证：** `pytest tests/test_hook_matcher.py -v` 通过

## T8: Hook Loader YAML 解析

**文件：** `src/coco_code/hook/loader.py`  
**依赖：** T1、T6、T7、T10  
**步骤：**
1. 实现 `default_hook_paths(project_root: Path, home: Path | None = None) -> tuple[Path, Path]`。
2. 实现 `load_hooks(project_root: Path, *, home: Path | None = None, stderr: TextIO = sys.stderr) -> HookEngine`。
3. 加载 `<projectRoot>/.coco-code/hooks.yaml` 和 `~/.coco-code/hooks.yaml`；不存在则跳过。
4. YAML 解析失败、顶层非 mapping、`hooks` 非 list 时，该文件报错并跳过。
5. 单条 Hook 非 dict 或字段校验失败时，只跳过该条并向 stderr 写明 source 与 index。
6. 校验 `name`、`event`、`action.type` 必填且类型正确。
7. 校验 `event` 必须属于 11 个固定事件。
8. 校验 `if` 顶层只能有 `all_of` 或 `any_of` 一个。
9. 校验每个 `match` 使用 exact、glob、regex、not 之一，并复用 `compile_structured_matcher`。
10. 校验 `async: true` 不能用于 `PreToolUse` 和 `UserPromptSubmit`。
11. 解析 `timeout`：支持数字秒与 `30s`、`5m`、`1h`；非法则跳过该 Hook。
12. 项目级先加载，用户级后加载；同名 Hook 后到者跳过并写 stderr。
13. `subagent` action 只校验字段，不做真实运行。

**验证：** `python -c "from pathlib import Path; from coco_code.hook.loader import load_hooks; print(load_hooks(Path('.')).rules())"` 不抛异常

## T9: Hook Loader 测试

**文件：** `tests/test_hook_loader.py`  
**依赖：** T8  
**步骤：**
1. 用 `tmp_path` 写合法 `.coco-code/hooks.yaml`，验证加载出 2 条 rule。
2. 覆盖 name 空、event 不存在、action.type 无效，坏条目跳过且好条目保留。
3. 覆盖 `all_of` 与 `any_of` 同时存在时跳过。
4. 覆盖 `async: true` + `PreToolUse` 时跳过，stderr 含 `async not allowed for blocking events`。
5. 覆盖项目级与用户级同名冲突，项目级保留、用户级跳过。
6. 覆盖非法正则导致 matcher 编译失败并跳过该条。
7. 覆盖非法 YAML、顶层结构错误、`hooks` 类型错误。

**验证：** `pytest tests/test_hook_loader.py -v` 通过

## T10: HookEngine dispatch 主流程

**文件：** `src/coco_code/hook/engine.py`  
**依赖：** T6、T7、T11  
**步骤：**
1. 定义 `DispatchResult`，包含 `blocked`、`reason`、`blocking_hook_name`、`injected_prompts`。
2. 定义 `HookEngine`，保存 `_rules`、`_sources`、`_executor`。
3. 实现 `rules()` 与 `sources()`，返回不可变快照。
4. 实现 `dispatch(event, payload, runtime=None)`。
5. 仅选择 event 匹配的 Hook，并保持加载顺序。
6. `only_once` 优先使用 `runtime.fired_hooks` 判断；无 runtime 时使用 engine 内部 fallback set。
7. 条件不命中则跳过；无条件视为命中。
8. `async_mode` Hook 创建后台 task 立即返回；有 runtime 时加入 `runtime.hook_tasks` 并消费异常。
9. 同步 Hook 等待 executor 结果。
10. executor 失败只向 stderr 写日志，不中断主流程。
11. prompt outcome 追加到 `DispatchResult.injected_prompts`。
12. blocking event 下 outcome.blocked 设置 `DispatchResult.blocked`，记录原因和 Hook 名，并停止后续同事件规则。
13. Hook 成功执行后记录 `only_once`。

**验证：** `python -c "import asyncio; from coco_code.hook import Event, HookEngine; print(asyncio.run(HookEngine([], []).dispatch(Event.STOP, {})))"` 不抛异常

## T11: HookExecutor 四类动作

**文件：** `src/coco_code/hook/executor.py`  
**依赖：** T6  
**步骤：**
1. 定义 `ActionOutcome`，包含 `blocked`、`reason`、`prompt`、`error`。
2. 定义 `HookExecutor.run(rule, payload, *, blocking) -> ActionOutcome`，按 action type 分发。
3. shell action 使用 `asyncio.create_subprocess_shell`。
4. shell stdin 写入 `json.dumps(payload, sort_keys=True)` 的 UTF-8 bytes。
5. shell timeout 时 kill 子进程并返回 `error`，不拦截。
6. blocking shell 下 `returncode == 2` 表示拦截，reason 取 stderr 或 stdout。
7. shell `returncode == 0` 放行；其它非零码为 Hook 自身失败。
8. prompt action 直接返回 `prompt=text`。
9. http action 默认 POST；无 body 时发送 payload JSON，有 body 时使用 `str.format_map` 渲染。
10. blocking http 下，2xx 且 JSON body 为 `{"decision":"block","reason":"..."}` 才拦截。
11. HTTP 网络错误、超时、JSON 解析失败都作为 Hook 失败，不拦截主流程。
12. subagent action 仅向 stderr 写 `[hook subagent] not yet implemented, skipped: <name>` 并放行。

**验证：** `python -c "from coco_code.hook.executor import HookExecutor; print(HookExecutor)"` 输出类对象

## T12: HookExecutor 测试

**文件：** `tests/test_hook_executor.py`  
**依赖：** T11  
**步骤：**
1. shell exit 2 且 stderr 有内容时，blocking outcome 为 `blocked=True` 且 reason 来自 stderr。
2. shell exit 0 时放行且无 error。
3. shell exit 1 时 `error is not None` 且不拦截。
4. shell stdin JSON 测试验证 payload key 字典序。
5. shell timeout 测试验证子进程被终止且 outcome.error 非空。
6. prompt action 测试验证 outcome.prompt。
7. HTTP stub 返回 `{"decision":"block","reason":"x"}` 时拦截。
8. HTTP 5xx、网络错误或非法 JSON 时作为 Hook 失败但不拦截。
9. HTTP body 模板 `{event}` 渲染后服务端收到正确内容。
10. subagent action 测试 stderr 含占位文本。

**验证：** `pytest tests/test_hook_executor.py -v` 通过

## T13: HookEngine 测试

**文件：** `tests/test_hook_engine.py`  
**依赖：** T10、T11  
**步骤：**
1. 多个同事件 rule 按声明顺序执行。
2. blocking event 中首个 blocked rule 中断后续 rule。
3. 非 blocking event 即使 executor 返回 blocked，也不设置 dispatch blocked。
4. prompt action 的文本累加到 `injected_prompts`。
5. `only_once` 首次执行后记录，第二次 dispatch 跳过。
6. runtime 重置 once 状态后，该 Hook 可再次执行。
7. async Hook 不进入 blocked 判定，且后台 task 被追踪。
8. executor 失败只记录日志，后续 rule 继续执行。

**验证：** `pytest tests/test_hook_engine.py -v` 通过

## T14: 扩展 SessionRuntime

**文件：** `src/coco_code/agent/runtime.py`、`tests/test_agent_loop.py`  
**依赖：** T6、T10  
**步骤：**
1. `SessionRuntime` 增加 `pending_hook_reminders: list[str]`。
2. 增加 `fired_hooks: set[str]`。
3. 增加 `hook_tasks: set[asyncio.Task[Any]]`。
4. 实现 `append_hook_reminders(prompts: list[str]) -> None`，忽略空字符串。
5. 实现 `take_hook_reminders() -> list[str]`，返回当前列表并清空。
6. 实现 `reset_hook_state()`，清空 reminders、fired hooks，并取消未完成 hook tasks。
7. 为 hook task 增加 done callback，自动从 set 中移除并消费异常。
8. 测试 append/take、reset、task 自动移除。

**验证：** `pytest tests/test_agent_loop.py -k runtime -v` 通过

## T15: AgentLoop 注入 HookEngine

**文件：** `src/coco_code/agent/loop.py`  
**依赖：** T10、T14  
**步骤：**
1. `AgentLoop.__init__` 增加 `hook_engine: HookEngine | None = None`。
2. 保存 `self._hook_engine`。
3. 新增 `_base_hook_payload(event: Event, **extra) -> dict[str, Any]`，至少包含 `event`、`cwd`、`turn_count`。
4. 新增 `async def _dispatch_hook(event, payload) -> DispatchResult`。
5. 无 HookEngine 时返回空 `DispatchResult`。
6. 有 HookEngine 时调用 `dispatch(event, payload, self._runtime)`。
7. dispatch 返回的 `injected_prompts` 写入 `runtime.append_hook_reminders`。

**验证：** `python -c "from coco_code.agent.loop import AgentLoop; print(AgentLoop)"` 不报错

## T16: AgentLoop 接入轮次级和压缩级事件

**文件：** `src/coco_code/agent/loop.py`、`src/coco_code/prompt.py`、`tests/test_agent_loop.py`、`tests/test_prompt.py`  
**依赖：** T15  
**步骤：**
1. 每轮模型请求前触发 `PreUserMessage`，payload 包含最近用户消息和模式信息。
2. 在 `_refresh_system_prompt` 之前完成 PreUserMessage，使 prompt action 能进入本轮 system prompt。
3. `prompt.build_system_prompt` 增加 `hook_reminders: str = ""` 参数，并渲染独立 `Hook Reminders:` 区。
4. App 或 system prompt builder 从 `runtime.take_hook_reminders()` 取出一次性 reminder，并传给 prompt builder。
5. `_auto_manage_context` 在调用 `manage_context` 前触发 `PreCompact`，调用后触发 `PostCompact`。
6. emergency compact 路径同样触发 `PreCompact` / `PostCompact`，payload 标记 trigger。
7. 自然停止前触发 `Stop`；用户取消和异常路径不强制触发 Stop。
8. provider stream error 路径触发 `Notification`，payload kind 为 `stream_error`。
9. 测试 Hook reminder 出现在下一次 system prompt，且取出后不会重复注入。
10. 测试 compact 前后事件 payload 含 before/after token 信息。
11. 测试 Stop 在模型自然结束路径触发。

**验证：** `pytest tests/test_agent_loop.py tests/test_prompt.py -k hook -v` 通过

## T17: 工具执行前后 Hook 接入

**文件：** `src/coco_code/agent/tools.py`、`src/coco_code/agent/loop.py`、`tests/test_agent_tools.py`  
**依赖：** T15  
**步骤：**
1. `execute_tool_batches` 增加 `hook_engine` 与 `runtime` 可选参数，或增加统一 hook dispatcher 参数。
2. `_execute_one` 在真实工具执行前触发 `PreToolUse`。
3. PreToolUse payload 包含 `tool_name`、`tool_input`、`permission_mode`。
4. Hook 拦截时跳过 `ToolExecutor.execute`，构造 `ToolResult(ok=False, data={"hook_blocked": True, ...})`。
5. 被拦截结果的 summary/error 包含 `[hook <name>] <reason>`。
6. 拦截路径仍保留 `TOOL_STARTED` 与后续 `TOOL_RESULT` 事件，避免 UI 状态断裂。
7. 真实工具执行后触发 `PostToolUse`，payload 包含 `tool_name`、`tool_input`、`tool_result`、`is_error`。
8. `PostToolUse` 不修改工具结果；失败只记日志。
9. 确保 Hook 拦截发生在权限引擎之前。
10. 测试 PreToolUse 拦截时 executor 未被调用。
11. 测试 PostToolUse 在成功与失败工具结果后都触发。

**验证：** `pytest tests/test_agent_tools.py -k hook -v` 通过

## T18: TUI 持有 HookEngine

**文件：** `src/coco_code/tui/app.py`、`tests/test_tui_app.py`  
**依赖：** T10、T15  
**步骤：**
1. App 构造参数增加 `hook_engine: HookEngine | None = None`。
2. `CoCoCodeApp` 保存 `self.hook_engine`。
3. 构造 `AgentLoop` 时传入同一个 HookEngine。
4. 确保 App 内 system prompt builder 能访问 runtime hook reminders。
5. `on_mount` 初始化完成后触发 `SessionStart`。
6. `SessionStart` 的 prompt action 写入 runtime pending reminders。

**验证：** `pytest tests/test_tui_app.py -k hook -v` 通过

## T19: UserPromptSubmit 拦截集成

**文件：** `src/coco_code/tui/stream.py`、`tests/test_tui_completion.py` 或新增 TUI 提交测试  
**依赖：** T18  
**步骤：**
1. 找到非 slash 用户提交路径，在写入 conversation 之前触发 `UserPromptSubmit`。
2. payload 包含 `prompt`、`cwd`、`session_id`、`mode`。
3. `DispatchResult.blocked` 为 True 时，不写入 conversation，不启动 AgentLoop。
4. UI 显示 `[hook <name>] <reason>`。
5. 被拦截时保留或恢复输入框文本。
6. 未拦截时，把 `injected_prompts` 写入 runtime，并继续原提交流程。
7. slash command 不触发 UserPromptSubmit。

**验证：** `pytest tests/test_tui_completion.py -k hook -v` 通过

## T20: SessionStart / SessionEnd / SessionResume 接入

**文件：** `src/coco_code/tui/app.py`、`src/coco_code/tui/commands.py`、`src/coco_code/tui/resume.py`、`tests/test_tui_app.py`  
**依赖：** T18、T19  
**步骤：**
1. 新增 `_dispatch_session_start()`，构造基础 payload 并调用 HookEngine。
2. 新增 `_dispatch_session_end()`，用于 clear、resume、退出前。
3. 新增 `_dispatch_session_resume()`，恢复旧会话后触发。
4. `/clear` 路径先触发 SessionEnd，再 `runtime.reset_hook_state()`，最后触发 SessionStart。
5. resume 切换旧会话前触发 SessionEnd，恢复完成后触发 SessionResume。
6. App 正常退出路径触发 SessionEnd。
7. 权限确认弹窗或类似通知路径触发 `Notification(kind="approval")`。
8. 测试 clear/resume/exit 事件顺序。

**验证：** `pytest tests/test_tui_app.py -k "session and hook" -v` 通过

## T21: `/hooks` 命令

**文件：** `src/coco_code/command/types.py`、`src/coco_code/command/handlers.py`、`src/coco_code/command/builtins.py`、`tests/test_command_builtins.py`  
**依赖：** T6、T10、T18  
**步骤：**
1. `CommandUI` Protocol 增加 `hook_rules()` 与 `hook_sources()`，或单个 `hooks_snapshot()`。
2. `CoCoCodeApp` 实现对应查询方法。
3. `handlers.py` 新增 `handle_hooks(ctx, ui)`。
4. 无 Hook 时输出 `No hooks loaded.`。
5. 有 Hook 时按 event 分组，保留声明顺序。
6. 每条输出包含 name、event、action type、`[once]`、`[async]` flags。
7. 输出 loaded sources，便于诊断项目级/用户级配置。
8. `builtins.py` 注册 public slash command `/hooks`。
9. 测试命令注册、空列表输出、有规则输出。

**验证：** `pytest tests/test_command_builtins.py -k hooks -v` 通过

## T22: CLI wiring

**文件：** `src/coco_code/cli.py`、`tests/test_cli_mcp.py` 或新增 CLI 测试  
**依赖：** T8、T18  
**步骤：**
1. 在启动流程中加载权限、MCP 配置后调用 `load_hooks(root)`。
2. 将 `hook_engine` 注入 `CoCoCodeApp`。
3. Hook 加载失败不得冒泡到 CLI 顶层；loader 返回空 engine 并已写 stderr。
4. `app.run_async()` 返回后 best-effort 触发一次 `SessionEnd` 兜底。
5. 检查 `pyproject.toml` 已包含 `httpx` 与 `pyyaml`，已存在则不改。
6. 更新 CLI 相关测试或新增最小启动 wiring 测试。

**验证：** `python -m coco_code --help` 正常输出帮助

## T23: 整体静态检查与测试

**文件：** 全部相关文件  
**依赖：** T1-T22  
**步骤：**
1. 运行 `ruff check src tests`。
2. 运行 Hook 相关测试：`pytest tests/test_hook_*.py tests/test_permission_matcher.py -v`。
3. 运行权限、Agent、TUI、命令相关测试。
4. 运行全量 `pytest`。
5. 记录失败项，进入 T24。

**验证：** `ruff check src tests` 与 `pytest` 均通过，或失败项已明确记录

## T24: 修复回归

**文件：** 根据 T23 输出决定  
**依赖：** T23  
**步骤：**
1. 修复权限 matcher 改造导致的旧权限测试失败。
2. 修复 prompt builder 新参数导致的旧 prompt/TUI 测试失败。
3. 修复 `/hooks` 命令加入后影响命令排序、帮助文本或快照的测试。
4. 修复 AgentLoop hook 注入造成的事件顺序回归。
5. 重新运行失败测试对应的最小集合。
6. 最后重新运行 `ruff check src tests` 与 `pytest`。

**验证：** 全量 `pytest` 通过

## T25: 端到端实跑验收准备

**文件：** `.coco-code/hooks.yaml` 临时测试配置  
**依赖：** T23、T24  
**步骤：**
1. 在测试工作区写入临时 `.coco-code/hooks.yaml`。
2. 配置覆盖典型场景：PreToolUse 拦截、UserPromptSubmit 拦截、PreUserMessage prompt 注入、PostToolUse HTTP、Stop shell。
3. 启动 `python -m coco_code` 或安装后的 `coco-code`。
4. 触发一次会调用工具的对话，观察 Hook 拦截工具结果。
5. 输入命中 UserPromptSubmit 条件的文本，观察 UI 阻止提交并显示原因。
6. 触发普通对话，观察 Hook reminder 只影响下一轮。
7. 输入 `/hooks`，观察已加载规则和 sources。
8. 退出会话，观察 SessionEnd/Stop 相关 Hook 日志。
9. 删除临时配置，避免污染后续开发环境。

**验证：** checklist.md 中端到端场景逐项通过

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5             # permission matcher 扩展
T6 -> T7 -> T10 -> T11 -> T12 -> T13   # hook 基础、engine、executor
T8 -> T9                               # loader，可在 T10/T11 后收口
T14 -> T15 -> T16 -> T17               # agent/runtime/tool 接入
T18 -> T19 -> T20                      # TUI 生命周期与提交拦截
T21                                    # /hooks 命令
T22                                    # CLI wiring
T23 -> T24                             # 整体测试与回归修复
T25                                    # 端到端实跑准备
```

并行机会：

- T11/T12 可在 T6 完成后与 T10/T13 并行推进。
- T8/T9 在 T6/T7 完成后可与 executor 测试并行推进。
- T16 与 T17 都依赖 T15，但可以由同一轮实现分开验证。
- T21 依赖 HookEngine 与 TUI 持有 HookEngine，完成 T18 后即可推进。
