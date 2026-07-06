# Skill System Checklist

> Every item must be checkable and observable. Run commands from the repository root `.`.

## Implementation Completeness

### Skill Parsing And Catalog

- [x] `src/coco_code/skills/types.py` defines `SkillMode`, `SkillContext`, `SkillSource`, `SkillMeta`, `Skill`, and `SkillCatalogItem` (verify: `rg "class SkillMode|class SkillContext|class SkillSource|class SkillMeta|class Skill\\(|class SkillCatalogItem" src/coco_code/skills/types.py` finds all names).
- [x] `src/coco_code/skills/parser.py` defines `SkillParseError`, `SKILL_NAME_RE`, `split_frontmatter`, `parse_skill_file`, and `substitute_arguments` (verify: `rg "SkillParseError|SKILL_NAME_RE|def split_frontmatter|def parse_skill_file|def substitute_arguments" src/coco_code/skills/parser.py` finds all names).
- [x] Parser rejects invalid `name`, missing `description`, invalid `allowed_tools`, invalid `mode`, invalid `context`, and invalid `model` (verify: `pytest tests/test_skills_parser.py -q` passes).
- [x] `$ARGUMENTS` replacement and `## User Request` fallback both work (verify: `pytest tests/test_skills_parser.py -q` includes argument-rendering cases).
- [x] `src/coco_code/skills/catalog.py` loads built-in, user, and project roots (verify: `rg "builtin|\\.coco-code/skills|SkillCatalog" src/coco_code/skills/catalog.py` finds the root handling).
- [x] Catalog priority is project > user > built-in for duplicate Skill names (verify: `pytest tests/test_skills_catalog.py -q` passes an override test).
- [x] A broken Skill file is skipped without blocking valid Skills (verify: `pytest tests/test_skills_catalog.py -q` passes an invalid-file isolation test).
- [x] `get_latest` re-reads the Skill entry file and falls back to the cached valid Skill on parse failure (verify: `pytest tests/test_skills_catalog.py -q` passes hot reload success and failure tests).
- [x] Built-in `commit`, `review`, and `test` Skills exist under `src/coco_code/skills/builtin/` (verify: `rg "^name: (commit|review|test)$" src/coco_code/skills/builtin` finds all three).

### Active Skills And Prompt Injection

- [x] `src/coco_code/skills/active.py` implements `ActiveSkills.activate`, `clear`, `snapshot`, and `allowed_tool_union` (verify: `rg "def activate|def clear|def snapshot|def allowed_tool_union" src/coco_code/skills/active.py` finds all methods).
- [x] Duplicate activation updates the active Skill body without changing activation order (verify: `pytest tests/test_skills_active.py -q` passes).
- [x] `SessionRuntime` has an `active_skills` field with a default empty `ActiveSkills` store (verify: `rg "active_skills" src/coco_code/agent/runtime.py` finds the field).
- [x] `build_system_prompt` accepts and renders `skills_catalog` and `active_skills` sections (verify: `rg "skills_catalog|active_skills|Active Skills|Available Skills" src/coco_code/prompt.py` finds the prompt wiring).
- [x] Startup catalog rendering includes only Skill names and descriptions, not full SOP bodies (verify: `pytest tests/test_prompt_skills.py -q` passes).
- [x] Active Skill rendering includes full SOP bodies in deterministic activation order (verify: `pytest tests/test_prompt_skills.py -q` passes).

### Tool Metadata And Whitelisting

- [x] `ToolSpec` includes `system: bool = False` (verify: `rg "system: bool = False" src/coco_code/tools/base.py` finds the field).
- [x] `ToolRegistry` implements `names`, `system_specs`, and `filtered_by_names` or equivalent helpers (verify: `rg "def names|def system_specs|def filtered_by_names" src/coco_code/tools/registry.py` finds the helpers).
- [x] Whitelist filtering preserves system tools even when not listed (verify: `pytest tests/test_skills_registry.py -q` passes).
- [x] Missing `allowed_tools` entries produce fail-fast validation issues during startup or reload (verify: `pytest tests/test_skills_catalog.py tests/test_skills_registry.py -q` passes).
- [x] Tool whitelisting does not bypass permission checks (verify: `pytest tests/test_permission_engine.py tests/test_tools_executor.py -q` passes).

### LoadSkill Tool

- [x] `src/coco_code/tools/load_skill.py` defines `LoadSkillTool` with `ToolSpec.name == "LoadSkill"` (verify: `rg "class LoadSkillTool|name=\"LoadSkill\"|name = \"LoadSkill\"" src/coco_code/tools/load_skill.py` finds both class and name).
- [x] `LoadSkill` is read-only, confirmation-free, and system-level (verify: `pytest tests/test_tools_load_skill.py -q` passes spec assertions).
- [x] `LoadSkill` activates the latest valid Skill into `runtime.active_skills` (verify: `pytest tests/test_tools_load_skill.py -q` passes activation test).
- [x] `LoadSkill` returns only a short confirmation and does not return the full SOP body (verify: `pytest tests/test_tools_load_skill.py -q` passes no-SOP-output test).
- [x] Unknown Skill names return a structured tool error with catalog guidance (verify: `pytest tests/test_tools_load_skill.py -q` passes unknown-Skill test).

### AgentLoop Integration

- [x] Provider protocol and concrete providers implement `set_system_prompt` (verify: `rg "set_system_prompt" src/coco_code/llm` finds protocol and provider implementations).
- [x] `AgentLoop` accepts a system prompt builder callback (verify: `rg "system_prompt_builder" src/coco_code/agent/loop.py` finds constructor and usage).
- [x] `AgentLoop` updates provider system prompt before each model collection attempt (verify: `pytest tests/test_agent_loop_skills.py -q` passes dynamic-prompt test).
- [x] `AgentLoop` derives the model-visible registry from active Skill whitelists before mode filtering (verify: `pytest tests/test_agent_loop_skills.py -q` passes active-whitelist tests).
- [x] The effective registry is used for model tool definitions, tool validation, batching, and compaction estimates (verify: `pytest tests/test_agent_loop_skills.py tests/test_agent_tools.py -q` passes).

### Skill Executor

- [x] `src/coco_code/skills/executor.py` defines `SkillExecutor` and `SkillDependencyError` (verify: `rg "class SkillExecutor|class SkillDependencyError" src/coco_code/skills/executor.py` finds both).
- [x] Inline execution renders the latest Skill, activates it, and sends a concise trigger into the main conversation (verify: `pytest tests/test_skills_executor.py -q` passes inline test).
- [x] Fork execution creates a separate `Conversation` and `SessionRuntime` (verify: `pytest tests/test_skills_executor.py -q` passes fork isolation test).
- [x] Fork `context: none`, `recent`, and `full` all build the expected child history (verify: `pytest tests/test_skills_executor.py -q` passes all three context tests).
- [x] Fork execution uses the Skill whitelist plus system tools for the child registry (verify: `pytest tests/test_skills_executor.py -q` passes fork tool filtering test).
- [x] Fork execution appends only the final summary to the main conversation (verify: `pytest tests/test_skills_executor.py tests/test_skill_system_integration.py -q` passes).

### Remote Installation

- [x] `src/coco_code/skills/install.py` defines install limits for per-file size, total size, file count, and depth (verify: `rg "MAX_FILE|MAX_TOTAL|MAX_FILES|MAX_DEPTH" src/coco_code/skills/install.py` finds all constants).
- [x] `parse_skill_url` supports `skills.sh`, GitHub tree URLs, and `raw.githubusercontent.com` URLs (verify: `pytest tests/test_skills_install.py -q` passes URL parsing tests).
- [x] Unsupported hosts are rejected before writing files (verify: `pytest tests/test_skills_install.py -q` passes unsupported-host test).
- [x] GitHub installs use HTTP APIs and do not require local `git` (verify: `rg "api.github.com|contents|trees" src/coco_code/skills/install.py` finds HTTP API usage and `rg "git clone|subprocess" src/coco_code/skills/install.py` finds no local git path).
- [x] Installer rejects absolute paths, `..`, symlinks, excessive depth, excessive file count, excessive total bytes, and files over 1 MiB (verify: `pytest tests/test_skills_install.py -q` passes safety tests).
- [x] Installer requires a package root containing valid `SKILL.md` (verify: `pytest tests/test_skills_install.py -q` passes missing/invalid `SKILL.md` tests).
- [x] Installer atomically moves validated staging into `~/.coco-code/skills/<skill-name>` and leaves no partial target on failure (verify: `pytest tests/test_skills_install.py -q` passes atomicity tests).
- [x] Existing target Skill directories fail clearly without overwrite (verify: `pytest tests/test_skills_install.py -q` passes existing-target test).

### InstallSkill Tool

- [x] `src/coco_code/tools/install_skill.py` defines `InstallSkillTool` with `ToolSpec.name == "InstallSkill"` (verify: `rg "class InstallSkillTool|name=\"InstallSkill\"|name = \"InstallSkill\"" src/coco_code/tools/install_skill.py` finds both class and name).
- [x] `InstallSkill` is non-read-only, confirmation-required, and not system-level (verify: `pytest tests/test_tools_install_skill.py -q` passes spec assertions).
- [x] Successful install invokes the injected reload callback (verify: `pytest tests/test_tools_install_skill.py -q` passes callback test).
- [x] Tool results report installed name, target path, file count, and total bytes without leaking tokens or headers (verify: `pytest tests/test_tools_install_skill.py -q` passes result-shape test).

### Commands And TUI Wiring

- [x] `CommandRegistry` supports removing Skill commands during reload (verify: `rg "remove_where|remove_skill" src/coco_code/command/registry.py src/coco_code/command/skills.py` finds removal logic).
- [x] `src/coco_code/command/skills.py` registers `/<skill-name>` slash commands and `/skill` management commands (verify: `rg "register_skill_commands|skill list|skill info|skill reload" src/coco_code/command/skills.py` finds all handlers).
- [x] Skill command descriptions include `[skill]` or an equivalent visible marker in `/help` (verify: `pytest tests/test_command_skills.py -q` passes help/visible command test).
- [x] Reserved command conflicts are rejected clearly (verify: `pytest tests/test_command_skills.py -q` passes conflict test).
- [x] The old hard-coded public `/review` is removed and the built-in `review` Skill provides `/review` (verify: `pytest tests/test_command_builtins.py tests/test_command_skills.py -q` passes).
- [x] `/skill list`, `/skill info <name>`, and `/skill reload` work through the command dispatcher (verify: `pytest tests/test_command_skills.py -q` passes).
- [x] `/clear` clears `runtime.active_skills` as well as visible history (verify: `pytest tests/test_command_builtins.py tests/test_tui_skills.py -q` passes).
- [x] `CoCoCodeApp` registers `LoadSkillTool` and `InstallSkillTool` before provider activation (verify: `pytest tests/test_tui_skills.py -q` passes startup wiring test).
- [x] `CoCoCodeApp` validates Skill `allowed_tools` after MCP tools are registered (verify: `pytest tests/test_tui_skills.py -q` passes MCP-aware validation test).
- [x] `CoCoCodeApp.build_current_system_prompt` includes catalog and active Skill blocks (verify: `pytest tests/test_tui_skills.py -q` passes prompt builder test).
- [x] Fork summaries append to both the main `Conversation` and visible history (verify: `pytest tests/test_tui_skills.py -q` passes fork summary test).

## Integration Completeness

- [x] `rg "SkillCatalog" src/coco_code/tui/app.py src/coco_code/skills` finds catalog construction and use.
- [x] `rg "LoadSkillTool" src/coco_code` finds tool definition, TUI registration, and at least one test.
- [x] `rg "InstallSkillTool" src/coco_code` finds tool definition, TUI registration, and at least one test.
- [x] `rg "active_skills" src/coco_code` finds runtime field, prompt rendering, loop filtering, clear handling, and tests.
- [x] `rg "register_skill_commands" src/coco_code` finds command registration and TUI reload wiring.
- [x] `rg "set_system_prompt" src/coco_code` finds provider protocol, provider implementations, and AgentLoop usage.
- [x] `rg "filtered_by_names" src/coco_code` finds registry helper and AgentLoop or executor use.
- [x] `rg "install_from_url" src/coco_code` finds install core and `InstallSkillTool` use.

## Automated Validation

- [x] `ruff check src tests` completes with no errors.
- [x] `pytest tests/test_skills_parser.py -q` passes.
- [x] `pytest tests/test_skills_catalog.py -q` passes.
- [x] `pytest tests/test_skills_active.py -q` passes.
- [x] `pytest tests/test_prompt_skills.py -q` passes.
- [x] `pytest tests/test_tools_load_skill.py -q` passes.
- [x] `pytest tests/test_tools_install_skill.py -q` passes.
- [x] `pytest tests/test_skills_install.py -q` passes.
- [x] `pytest tests/test_skills_executor.py -q` passes.
- [x] `pytest tests/test_command_skills.py -q` passes.
- [x] `pytest tests/test_agent_loop_skills.py -q` passes.
- [x] `pytest tests/test_tui_skills.py -q` passes.
- [x] `pytest tests/test_skill_system_integration.py -q` passes.
- [x] `pytest` passes for the full suite.

## Manual End-To-End Validation

> Start from the repository root with `python -m coco_code`.

- [ ] With no user/project Skills, startup succeeds and `/help` lists built-in Skill commands including `/commit`, `/review`, and `/test` (verify: observe `/help` output).
- [ ] Create `.coco-code/skills/test-skill/SKILL.md` with valid frontmatter and body `Echo hello`; after `/skill reload`, `/help` lists `/test-skill` (verify: observe `/help` output).
- [ ] Run `/test-skill sample args`; the next model turn receives the rendered SOP with `sample args` substituted or appended (verify: fake-provider test or debug prompt capture shows the text).
- [ ] Edit `.coco-code/skills/test-skill/SKILL.md`, run `/test-skill` again without restarting, and observe the updated SOP in the prompt capture (verify: hot reload behavior).
- [ ] Ask naturally for a workflow matching `test-skill`; the model calls `LoadSkill`, and the following turn includes `## Active Skills` with that SOP (verify: tool call and prompt capture).
- [ ] Run `/clear`, then send another message; the following prompt no longer contains `## Active Skills` (verify: prompt capture or debug output).
- [ ] Create an invalid `.coco-code/skills/bad.md`, run `/skill reload`, and observe a warning while other Skills remain available (verify: warning and `/skill list` output).
- [ ] Run a fork-mode Skill and verify only the final summary appears in the main visible history (verify: visible history and session items).
- [ ] Attempt `InstallSkill` with an unsupported host; it fails before writing files (verify: tool result and no new directory under `~/.coco-code/skills`).
- [ ] Attempt `InstallSkill` with a mocked or known safe supported package; it installs, reloads, and the new slash command works without restart (verify: tool result, `/skill list`, and `/help`).

## Documentation

- [x] `README.md` documents Skill file format, storage paths, and examples (verify: `rg "SKILL.md|\\.coco-code/skills|LoadSkill|InstallSkill" README.md` finds the section).
- [x] `docs/skill-system/spec.md` includes remote installation scope and acceptance criteria AC18-AC20 (verify: `rg "Remote Installation|AC18|AC19|AC20" docs/skill-system/spec.md`).
- [x] `docs/skill-system/plan.md` reflects the implemented module boundaries (verify: paths in plan match actual files under `src/coco_code`).
- [x] `docs/skill-system/task.md` progress boxes are updated as implementation tasks are completed (verify: all completed tasks are checked).
- [x] Final change summary mentions built-in Skills, two-stage loading, inline/fork modes, tool whitelists, remote install, and `/skill` management (verify: release note or PR description includes all topics).

