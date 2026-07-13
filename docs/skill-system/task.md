# Skill System Tasks

> Execute in order. After each implementation task, run the focused tests named in that task before moving on. Run the full suite after the TUI integration tasks.

## File List

| Action | File | Responsibility |
|---|---|---|
| New | `src/coco_code/skills/__init__.py` | Export Skill catalog, active state, executor, install helpers |
| New | `src/coco_code/skills/types.py` | Skill dataclasses and enums |
| New | `src/coco_code/skills/parser.py` | Frontmatter parsing, validation, argument substitution |
| New | `src/coco_code/skills/catalog.py` | Built-in/user/project discovery, priority override, hot reload |
| New | `src/coco_code/skills/active.py` | Runtime active Skill store |
| New | `src/coco_code/skills/render.py` | Catalog and active Skill prompt rendering |
| New | `src/coco_code/skills/executor.py` | Inline and fork execution |
| New | `src/coco_code/skills/install.py` | Remote install parsing, download, staging, safety checks |
| New | `src/coco_code/skills/builtin/*/SKILL.md` | Built-in `commit`, `review`, `test` samples |
| New | `src/coco_code/tools/load_skill.py` | `LoadSkill` system tool |
| New | `src/coco_code/tools/install_skill.py` | `InstallSkill` normal tool |
| Modify | `src/coco_code/tools/base.py` | `ToolSpec.system` field |
| Modify | `src/coco_code/tools/registry.py` | Tool names and whitelist filtering |
| Modify | `src/coco_code/prompt.py` | Skill catalog and active Skill prompt sections |
| Modify | `src/coco_code/llm/__init__.py` | Provider protocol system-prompt setter |
| Modify | `src/coco_code/llm/openai_provider.py` | Provider setter |
| Modify | `src/coco_code/llm/anthropic_provider.py` | Provider setter |
| Modify | `src/coco_code/agent/runtime.py` | `active_skills` field |
| Modify | `src/coco_code/agent/loop.py` | Dynamic system prompt and effective tool registry |
| Modify | `src/coco_code/agent/tools.py` | Mode filtering works with pre-filtered registry |
| Modify | `src/coco_code/command/registry.py` | Command removal helpers |
| Modify | `src/coco_code/command/types.py` | Command UI Skill methods |
| Modify | `src/coco_code/command/builtins.py` | Remove hard-coded public `/review`, add `/skill` path |
| Modify | `src/coco_code/command/handlers.py` | `/clear` active Skill cleanup |
| New | `src/coco_code/command/skills.py` | Skill slash command registration and `/skill` handler |
| Modify | `src/coco_code/tui/app.py` | Skill startup wiring, reload, prompt builder, fork summaries |
| New/Modify | `tests/test_*skills*.py` | Focused Skill tests |
| New | `docs/skill-system/checklist.md` | Acceptance checklist, generated after task approval |

## T1: Define Skill Types And Active Store

**Files:** `src/coco_code/skills/types.py`, `src/coco_code/skills/active.py`, `src/coco_code/skills/__init__.py`

**Dependencies:** None

**Steps:**
1. Add `SkillMode`, `SkillContext`, and `SkillSource` `StrEnum` classes.
2. Add frozen dataclasses `SkillMeta`, `Skill`, and `SkillCatalogItem`.
3. Add frozen dataclass `ActiveSkillEntry`.
4. Implement `ActiveSkills.activate`, `clear`, `snapshot`, and `allowed_tool_union`.
5. Ensure duplicate activation updates the existing entry without changing activation order.
6. Export public types from `skills/__init__.py`.

**Verify:** `pytest tests/test_skills_active.py -q`

## T2: Parse Skill Markdown And Arguments

**Files:** `src/coco_code/skills/parser.py`, `tests/test_skills_parser.py`

**Dependencies:** T1

**Steps:**
1. Define `SkillParseError` and `SKILL_NAME_RE`.
2. Implement `split_frontmatter(raw)` for `---` YAML frontmatter plus Markdown body.
3. Implement metadata validation for `name`, `description`, `allowed_tools`, `mode`, `context`, and `model`.
4. Implement `parse_skill_file(path, source, is_directory=False)`.
5. Implement `substitute_arguments(prompt_body, args)`.
6. Preserve body text exactly except for frontmatter removal and argument rendering.

**Verify:** `pytest tests/test_skills_parser.py -q`

## T3: Load Catalog From Built-In, User, And Project Roots

**Files:** `src/coco_code/skills/catalog.py`, `tests/test_skills_catalog.py`

**Dependencies:** T2

**Steps:**
1. Define default roots for built-in package resources, `~/.coco-code/skills`, and `<workspace>/.coco-code/skills`.
2. Implement scanning for directory Skills containing `SKILL.md`.
3. Implement scanning for direct single-file `*.md` Skills.
4. Merge by normalized name in built-in -> user -> project order.
5. Keep deterministic sorted iteration.
6. Log and skip invalid individual Skills without aborting the catalog load.
7. Implement `get`, `get_latest`, `list`, `reload`, and `catalog_text`.
8. Implement hot update fallback to the last cached valid Skill on parse failure.

**Verify:** `pytest tests/test_skills_catalog.py -q`

## T4: Add Built-In Sample Skills

**Files:** `src/coco_code/skills/builtin/commit/SKILL.md`, `src/coco_code/skills/builtin/review/SKILL.md`, `src/coco_code/skills/builtin/test/SKILL.md`, `tests/test_skills_catalog.py`

**Dependencies:** T3

**Steps:**
1. Add a `commit` Skill with a concise commit-message SOP and a conservative tool whitelist.
2. Add a `review` Skill that preserves current review behavior: findings first, bugs/regressions/tests/security/maintainability.
3. Add a `test` Skill that identifies project type, selects test commands, runs them, and reports evidence.
4. Ensure built-in Skills are discovered through the same catalog path as user/project Skills.
5. Add tests proving user/project Skills override built-ins.

**Verify:** `pytest tests/test_skills_catalog.py -q`

## T5: Extend Tool Metadata And Registry Filtering

**Files:** `src/coco_code/tools/base.py`, `src/coco_code/tools/registry.py`, `tests/test_tools_registry.py`, `tests/test_skills_registry.py`

**Dependencies:** T1

**Steps:**
1. Add `system: bool = False` to `ToolSpec`.
2. Add `ToolRegistry.names()`.
3. Add `ToolRegistry.system_specs()` or equivalent helper.
4. Add `ToolRegistry.filtered_by_names(allowed, include_system=True)`.
5. Ensure aliases resolve correctly when validating allowed tool names.
6. Ensure system tools pass through even when not listed.
7. Preserve current `filtered(predicate)` behavior.

**Verify:** `pytest tests/test_tools_registry.py tests/test_skills_registry.py -q`

## T6: Render Skill Prompt Blocks

**Files:** `src/coco_code/skills/render.py`, `src/coco_code/prompt.py`, `tests/test_prompt_skills.py`

**Dependencies:** T1, T2

**Steps:**
1. Implement `render_skill_body(skill, args)` with `$ARGUMENTS` replacement and `## User Request` fallback.
2. Implement `render_skills_catalog(skills)` with name and one-line description only.
3. Implement `render_active_skills_block(entries)`.
4. Extend `build_system_prompt` with `skills_catalog` and `active_skills`.
5. Place catalog and active Skills after runtime facts and before memory/custom instructions.
6. Keep output empty when no Skills are available or active.

**Verify:** `pytest tests/test_prompt.py tests/test_prompt_skills.py -q`

## T7: Add Provider System Prompt Setter

**Files:** `src/coco_code/llm/__init__.py`, `src/coco_code/llm/openai_provider.py`, `src/coco_code/llm/anthropic_provider.py`, provider tests if present

**Dependencies:** T6

**Steps:**
1. Add `set_system_prompt(text)` to the `Provider` protocol.
2. Implement the setter in OpenAI, OpenAI-compatible, and Anthropic providers by updating `_system_prompt`.
3. Keep existing provider constructors unchanged.
4. Add or update tests to assert the next request uses the updated prompt.

**Verify:** `pytest tests/test_llm_events.py tests/test_llm_tool_events.py -q`

## T8: Store Active Skills In SessionRuntime

**Files:** `src/coco_code/agent/runtime.py`, `src/coco_code/tui/app.py`, tests covering runtime/session behavior

**Dependencies:** T1

**Steps:**
1. Add `active_skills: ActiveSkills` to `SessionRuntime` with a default factory.
2. Ensure `new_session_runtime` initializes an empty active store.
3. Ensure cancellation/runtime replacement preserves active Skills for the same conversation.
4. Ensure restored sessions start with an empty active Skill store.
5. Ensure `/clear` later can clear the runtime store.

**Verify:** `pytest tests/test_agent_loop.py tests/test_tui_app.py -q`

## T9: Implement LoadSkill Tool

**Files:** `src/coco_code/tools/load_skill.py`, `tests/test_tools_load_skill.py`

**Dependencies:** T3, T5, T6, T8

**Steps:**
1. Implement `LoadSkillTool` with `ToolSpec.name == "LoadSkill"`.
2. Mark it `read_only=True`, `confirmation=NEVER`, and `system=True`.
3. Accept parameters `name` and optional `arguments`.
4. Attach catalog and runtime through constructor or setter.
5. On execution, load the latest valid Skill, render it, activate it, and return a short confirmation.
6. Return structured tool errors for unknown Skill or uninitialized dependencies.
7. Do not include the full SOP in `ToolResult.summary` or `ToolResult.data`.

**Verify:** `pytest tests/test_tools_load_skill.py -q`

## T10: Apply Active Skill Whitelists In AgentLoop

**Files:** `src/coco_code/agent/loop.py`, `src/coco_code/agent/tools.py`, `tests/test_agent_loop_skills.py`

**Dependencies:** T5, T6, T7, T8

**Steps:**
1. Add a `system_prompt_builder` callback to `AgentLoop`.
2. Before each model turn, call the builder and update the provider prompt.
3. Add helper logic to derive an active registry from `runtime.active_skills.allowed_tool_union()`.
4. Use the active registry before mode filtering.
5. Use the same effective registry for model tool definitions, validation, batching, and compaction token estimates.
6. Keep `ToolExecutor` on the full registry but execute only calls validated against the effective registry.
7. Add tests for no active whitelist, one whitelist, multiple whitelist union, and system-tool passthrough.

**Verify:** `pytest tests/test_agent_loop_skills.py tests/test_agent_tools.py -q`

## T11: Implement Skill Executor Inline And Fork Modes

**Files:** `src/coco_code/skills/executor.py`, `tests/test_skills_executor.py`

**Dependencies:** T3, T5, T6, T8, T10

**Steps:**
1. Define `SkillDependencyError`.
2. Implement inline command execution: latest Skill -> render -> activate -> send concise trigger message.
3. Implement fork conversation creation with `none`, `recent`, and `full` context policies.
4. Build fork registry from the Skill whitelist plus system tools.
5. Build fork `ToolExecutor` using the same tool context and confirmation callbacks.
6. Build fork provider from the current provider config, or a configured provider matching `model`.
7. Run child `AgentLoop` and collect final assistant text.
8. Return a clear failure summary on child errors without mutating main history mid-run.
9. Add tests using fake provider/tool objects, not real network calls.

**Verify:** `pytest tests/test_skills_executor.py -q`

## T12: Implement Remote Install Core

**Files:** `src/coco_code/skills/install.py`, `tests/test_skills_install.py`

**Dependencies:** T2, T3

**Steps:**
1. Define install limits: 1 MiB per file, 8 MiB total, 64 files, depth 4.
2. Implement URL parsing for `skills.sh`, GitHub tree URLs, and `raw.githubusercontent.com`.
3. Reject unsupported hosts before writing files.
4. Implement HTTP-based GitHub tree/content fetch without local `git`.
5. Stream or bound downloads to enforce file and total limits.
6. Stage all files in a temporary directory.
7. Reject absolute paths, `..`, symlinks, excessive depth, excessive count, and excessive size.
8. Validate exactly one package root containing `SKILL.md`.
9. Parse staged `SKILL.md` before installation.
10. Atomically move staging into `~/.coco-code/skills/<skill-name>`.
11. Fail clearly if target already exists.
12. Remove staging on failure.

**Verify:** `pytest tests/test_skills_install.py -q`

## T13: Implement InstallSkill Tool

**Files:** `src/coco_code/tools/install_skill.py`, `tests/test_tools_install_skill.py`

**Dependencies:** T5, T12

**Steps:**
1. Implement `InstallSkillTool` with `ToolSpec.name == "InstallSkill"`.
2. Mark it `read_only=False`, `confirmation=REQUIRED`, `system=False`.
3. Accept `source_url`.
4. Call `install_from_url`.
5. Invoke an injected reload callback after successful install.
6. Return installed Skill name, target path, file count, and total bytes.
7. Return structured errors without exposing sensitive headers or tokens.

**Verify:** `pytest tests/test_tools_install_skill.py -q`

## T14: Add Skill Command Registration And `/skill`

**Files:** `src/coco_code/command/registry.py`, `src/coco_code/command/types.py`, `src/coco_code/command/builtins.py`, `src/coco_code/command/handlers.py`, `src/coco_code/command/skills.py`, `tests/test_command_skills.py`

**Dependencies:** T3, T11

**Steps:**
1. Add command removal support to `CommandRegistry`.
2. Add Skill-related methods to `CommandUI`: list catalog, list active Skills, clear active Skills, reload Skills, append assistant message.
3. Remove public hard-coded `/review` from built-ins; keep the review behavior as a built-in Skill.
4. Add `/skill list`, `/skill info <name>`, and `/skill reload`.
5. Implement `register_skill_commands` and `remove_skill_commands`.
6. Reject Skills that conflict with reserved command names.
7. Ensure command closures capture each Skill name correctly.
8. Wire `/clear` to call `ui.clear_active_skills()`.

**Verify:** `pytest tests/test_command_builtins.py tests/test_command_registry.py tests/test_command_skills.py -q`

## T15: Wire Skills Into TUI Startup And Runtime

**Files:** `src/coco_code/tui/app.py`, `tests/test_tui_skills.py`, `tests/test_tui_app.py`

**Dependencies:** T3, T9, T10, T11, T13, T14

**Steps:**
1. Add Skill catalog, executor, load tool, install tool, and catalog text fields to `CoCoCodeApp`.
2. Register `LoadSkillTool` and `InstallSkillTool` before provider activation.
3. Load catalog in `__init__` without full tool validation.
4. After MCP startup, validate Skill `allowed_tools` against the complete registry.
5. Register `/skill` and Skill slash commands.
6. Attach reload callbacks to `InstallSkillTool` and `/skill reload`.
7. Implement `build_current_system_prompt`.
8. Use the builder in `activate_provider`, `submit_user_text`, and manual compact paths.
9. Implement UI Skill methods required by `CommandUI`.
10. Ensure `clear_history` clears active Skills and visible history.
11. Ensure fork summaries append to both conversation and visible history.

**Verify:** `pytest tests/test_tui_skills.py tests/test_tui_app.py -q`

## T16: CLI And Session Integration

**Files:** `src/coco_code/cli.py`, `src/coco_code/session/*` if needed, `tests/test_session_persistence.py`

**Dependencies:** T15

**Steps:**
1. Keep CLI entrypoint signature stable.
2. Ensure no user/project Skills still starts with built-ins.
3. Ensure session writer records slash-triggered inline messages and fork summaries.
4. Ensure active Skills are not accidentally persisted across restored sessions.
5. Update docs or examples for user/project Skill paths if needed.

**Verify:** `pytest tests/test_session_persistence.py tests/test_tui_app.py -q`

## T17: End-To-End Tests

**Files:** `tests/test_context_management_integration.py` or new `tests/test_skill_system_integration.py`

**Dependencies:** T1-T16

**Steps:**
1. Add an integration test with a temporary project Skill and fake provider.
2. Assert startup catalog includes only name and description.
3. Assert `LoadSkill` activates the full SOP and the next model turn receives it.
4. Assert `/commit` from built-in Skills is registered.
5. Assert project Skill overrides built-in Skill.
6. Assert `/clear` clears active Skills.
7. Assert install callback reloads catalog and command registry using a mocked HTTP source.
8. Assert fork mode appends only final summary to main conversation.

**Verify:** `pytest tests/test_skill_system_integration.py -q`

## T18: Full Validation And Documentation Pass

**Files:** `README.md`, `docs/skill-system/spec.md`, `docs/skill-system/plan.md`, `docs/skill-system/task.md`

**Dependencies:** T1-T17

**Steps:**
1. Document Skill file format and storage paths.
2. Document `LoadSkill`, `InstallSkill`, and `/skill` commands.
3. Document remote install limits and supported URL forms.
4. Run `ruff check src tests`.
5. Run the full pytest suite.
6. Fix regressions until validation is clean.

**Verify:** `ruff check src tests` and `pytest`

## Execution Order

```text
T1 -> T2 -> T3 -> T4
           -> T5 -> T6 -> T7 -> T8 -> T9 -> T10
                                      -> T11
           -> T12 -> T13
T14 -> T15 -> T16 -> T17 -> T18
```

T12 can start after parser/catalog work is stable, but T13 must wait for registry metadata. T15 is the main integration point and should not start until parser, catalog, tools, executor, command registration, and AgentLoop filtering are in place.

## Progress

- [x] T1: Define Skill types and active store
- [x] T2: Parse Skill Markdown and arguments
- [x] T3: Load catalog from built-in, user, and project roots
- [x] T4: Add built-in sample Skills
- [x] T5: Extend tool metadata and registry filtering
- [x] T6: Render Skill prompt blocks
- [x] T7: Add provider system prompt setter
- [x] T8: Store active Skills in SessionRuntime
- [x] T9: Implement LoadSkill tool
- [x] T10: Apply active Skill whitelists in AgentLoop
- [x] T11: Implement Skill executor inline and fork modes
- [x] T12: Implement remote install core
- [x] T13: Implement InstallSkill tool
- [x] T14: Add Skill command registration and `/skill`
- [x] T15: Wire Skills into TUI startup and runtime
- [x] T16: CLI and session integration
- [x] T17: End-to-end tests
- [x] T18: Full validation and documentation pass

