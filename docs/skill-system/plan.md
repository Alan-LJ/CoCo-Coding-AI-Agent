# Skill System Plan

## Architecture Overview

The implementation adds a `coco_code.skills` package and connects it to the existing `CoCoCodeApp`, `AgentLoop`, `SessionRuntime`, `ToolRegistry`, command registry, and prompt builder. The current repo does not have a single mutable `Agent` object; the runtime shape is `Provider + Conversation + ToolRegistry + ToolExecutor + AgentLoop`. The Skill design therefore stores active Skills in `SessionRuntime`, updates the provider system prompt before every model turn, and derives the visible tool registry from active Skill whitelists.

Main components:

- `coco_code.skills`: owns Skill types, frontmatter parsing, catalog loading, active Skill state, rendering, execution, built-in Skill resources, and remote installation.
- `coco_code.tools.load_skill`: read-only system tool that activates a Skill by name without returning the full SOP in tool output.
- `coco_code.tools.install_skill`: non-read-only normal tool that installs remote directory Skills into the user Skill directory, then triggers catalog reload.
- `coco_code.tools.registry`: gains system-tool metadata and whitelist filtering helpers.
- `coco_code.prompt`: gains Skill catalog and active Skill rendering, and extends `build_system_prompt` with Skill blocks.
- `coco_code.llm`: providers gain `set_system_prompt(text)` so the Agent loop can rebuild system prompt each iteration.
- `coco_code.agent.loop`: accepts a system prompt builder callback and applies active Skill tool whitelists when collecting and validating tool calls.
- `coco_code.agent.runtime`: stores `ActiveSkills` so active SOPs survive every context rebuild inside the current session and are cleared with the conversation.
- `coco_code.command`: registers Skills as slash commands, adds `/skill`, and adds command-removal support for reload.
- `coco_code.tui.app`: wires startup loading, MCP-aware tool validation, catalog prompt injection, commands, `/clear`, and fork result insertion.

Startup order is important because Skills may whitelist MCP tools:

```text
CoCoCodeApp.__init__
  - create default ToolRegistry
  - register LoadSkill and InstallSkill
  - load Skill catalog from built-in, user, project paths without validating tools yet
  - create command registry with built-ins except the old hard-coded /review

CoCoCodeApp.on_mount
  - start MCP and register MCP tools
  - validate Skill allowed_tools against the complete registry
  - register Skill slash commands and /skill management command
  - build startup Skill catalog text
  - activate provider and enable input
```

## Core Data Structures

### Skill Types

```python
# src/coco_code/skills/types.py
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

class SkillMode(StrEnum):
    INLINE = "inline"
    FORK = "fork"

class SkillContext(StrEnum):
    NONE = "none"
    RECENT = "recent"
    FULL = "full"

class SkillSource(StrEnum):
    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"

@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    allowed_tools: tuple[str, ...] = ()
    mode: SkillMode = SkillMode.INLINE
    context: SkillContext = SkillContext.NONE
    model: str | None = None

@dataclass(frozen=True)
class Skill:
    meta: SkillMeta
    prompt_body: str
    entry_path: Path
    package_dir: Path
    source: SkillSource
    is_directory: bool

@dataclass(frozen=True)
class SkillCatalogItem:
    name: str
    description: str
    source: SkillSource
    mode: SkillMode
    entry_path: Path
```

`entry_path` is the Markdown file to re-read for hot updates. For a directory Skill it is `<dir>/SKILL.md`; for a single-file Skill it is that Markdown file. `package_dir` is the directory that may contain templates, examples, scripts, and references.

### Active Skills

```python
# src/coco_code/skills/active.py
from dataclasses import dataclass
import threading

@dataclass(frozen=True)
class ActiveSkillEntry:
    name: str
    rendered_body: str
    allowed_tools: tuple[str, ...]

class ActiveSkills:
    def activate(self, name: str, rendered_body: str, allowed_tools: tuple[str, ...]) -> None: ...
    def clear(self) -> None: ...
    def snapshot(self) -> tuple[ActiveSkillEntry, ...]: ...
    def allowed_tool_union(self) -> tuple[str, ...]: ...
```

Repeated activation of the same Skill updates its body and whitelist in place while preserving the first activation position. This keeps multi-Skill rendering deterministic.

### Catalog

```python
# src/coco_code/skills/catalog.py
class SkillCatalog:
    @classmethod
    def load(cls, workspace: Path, *, stderr: TextIO = sys.stderr) -> "SkillCatalog": ...
    def reload(self) -> None: ...
    def get(self, name: str) -> Skill | None: ...
    def get_latest(self, name: str) -> Skill | None: ...
    def list(self) -> tuple[Skill, ...]: ...
    def validate_tools(self, registry: ToolRegistry) -> tuple[SkillValidationIssue, ...]: ...
    def remove_invalid(self, issues: Iterable[SkillValidationIssue]) -> None: ...
    def catalog_text(self) -> str: ...
```

Discovery scans from lowest to highest priority: built-in, user, project. Later entries replace earlier entries with the same normalized name. Parsing errors skip only the failing Skill and write a warning. `get_latest` re-reads the entry file for hot update; if re-read fails, it returns the last cached valid Skill and warns.

Default storage paths:

```text
built-in: package resources under src/coco_code/skills/builtin/
user:    ~/.coco-code/skills/
project: <workspace>/.coco-code/skills/
```

### Skill Executor

```python
# src/coco_code/skills/executor.py
class SkillExecutor:
    async def execute_command(self, name: str, args: str, ui: CommandUI) -> None: ...
    def activate_inline(self, skill: Skill, args: str) -> str: ...
    async def execute_fork(self, skill: Skill, args: str) -> str: ...
```

The executor is constructed by the TUI with references to catalog, runtime, provider config, config providers, conversation, registry, tool context, confirmation callbacks, permission engine, and the current system prompt builder.

## Module Design

### `coco_code.skills.parser`

Responsibilities:

- Parse YAML frontmatter plus Markdown body.
- Support single-file Skills and directory Skills with `SKILL.md`.
- Validate required fields and normalize defaults.
- Reject invalid Skill names before command registration.

Interfaces:

```python
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

class SkillParseError(ValueError): ...

def parse_skill_file(path: Path, source: SkillSource, *, is_directory: bool = False) -> Skill: ...
def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]: ...
def substitute_arguments(prompt_body: str, args: str) -> str: ...
```

Rules:

- Missing `name` or `description` is an error.
- Unknown `mode` or `context` is an error rather than silently changing behavior.
- `allowed_tools` must be a string list if present.
- `model` must be a string if present.
- `$ARGUMENTS` is replaced everywhere. If no placeholder exists and args are non-empty, rendering appends a `## User Request` section.

### `coco_code.skills.catalog`

Responsibilities:

- Scan built-in, user, and project roots.
- Merge by normalized Skill name with project > user > built-in priority.
- Keep deterministic ordering by normalized name for catalog text and commands.
- Re-read entry files on execution for hot update.
- Validate tool whitelists after the complete tool registry exists.

Directory scanning:

- A child directory containing `SKILL.md` is a directory Skill.
- A direct `*.md` file is a single-file Skill.
- Other files are ignored at scan time and may be referenced by directory Skill SOPs.

Validation:

- `allowed_tools` names are checked with `ToolRegistry.get`.
- Missing tools create `SkillValidationIssue(skill_name, tool_name, message)`.
- Invalid Skills are omitted from catalog text and slash commands until fixed and reloaded.
- System tools are not required in `allowed_tools` and are always visible.

### `coco_code.skills.active`

Responsibilities:

- Store active rendered SOPs for the current session.
- Provide snapshots for prompt rendering and tool whitelist derivation.
- Clear active Skills on `/clear`, session reset, and restored-session runtime replacement.

`SessionRuntime` gains:

```python
active_skills: ActiveSkills = field(default_factory=ActiveSkills)
```

When `CoCoCodeApp.detach_cancelled_turn_state` or session restore creates a new `SessionRuntime`, it carries or clears active Skills intentionally. Restored historical sessions start with no active Skills unless future persistence explicitly adds them.

### `coco_code.skills.render`

Responsibilities:

- Render a Skill body with slash/tool arguments.
- Produce active Skill prompt blocks.
- Produce startup catalog blocks.

Interfaces:

```python
def render_skill_body(skill: Skill, args: str) -> str: ...
def render_skills_catalog(skills: Sequence[Skill]) -> str: ...
def render_active_skills_block(entries: Sequence[ActiveSkillEntry]) -> str: ...
```

Catalog text includes only names, descriptions, source labels, and a short instruction to call `LoadSkill`. Active Skill text includes full rendered SOPs and appears near the top of the generated system prompt after runtime facts.

### `coco_code.tools.base` And `coco_code.tools.registry`

`ToolSpec` gains system-tool metadata:

```python
@dataclass(frozen=True)
class ToolSpec:
    ...
    system: bool = False
```

Registry helpers:

```python
class ToolRegistry:
    def names(self) -> tuple[str, ...]: ...
    def filtered_by_names(self, allowed: Iterable[str], *, include_system: bool = True) -> ToolRegistry: ...
    def system_specs(self) -> tuple[ToolSpec, ...]: ...
```

Filtering behavior:

- Empty `allowed` returns the original registry or a shallow equivalent view.
- Missing allowed names raise `SkillDependencyError` during validation.
- System tools pass through even when omitted from `allowed_tools`.
- Filtering only changes model-visible tools. Existing permission checks still run before execution.

### `coco_code.tools.load_skill`

Responsibilities:

- Let the model activate a Skill by name after reading the startup catalog.
- Avoid returning full SOP content in tool output.

Tool spec:

```python
ToolSpec(
    name="LoadSkill",
    description="Load and activate a Skill SOP by name.",
    read_only=True,
    confirmation=ConfirmationPolicy.NEVER,
    system=True,
    parameters_schema={... name ... arguments ...},
)
```

Execution:

1. Validate that catalog and runtime are attached.
2. Look up the latest valid Skill by name.
3. Render body with optional `arguments`.
4. Activate it in `runtime.active_skills`.
5. Return `Skill '<name>' activated. SOP pinned to environment context.`

### `coco_code.tools.install_skill`

Responsibilities:

- Install remote directory Skills into `~/.coco-code/skills/`.
- Enforce download and filesystem safety limits.
- Trigger reload and command refresh after successful install.

Tool spec:

```python
ToolSpec(
    name="InstallSkill",
    description="Install a remote Skill into the user Skill directory.",
    read_only=False,
    destructive=False,
    confirmation=ConfirmationPolicy.REQUIRED,
    system=False,
    parameters_schema={... source_url ...},
)
```

It is a normal tool, not exempt from whitelists unless a Skill includes it explicitly.

### `coco_code.skills.install`

Responsibilities:

- Parse supported remote URLs.
- Download package contents through HTTP.
- Validate package shape and limits.
- Atomically install into the user Skill directory.

Interfaces:

```python
MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
MAX_DEPTH = 4

@dataclass(frozen=True)
class InstallResult:
    name: str
    target_dir: Path
    file_count: int
    total_bytes: int

async def install_from_url(source_url: str, user_root: Path, *, http_client: httpx.AsyncClient | None = None) -> InstallResult: ...
def parse_skill_url(source_url: str) -> SkillRemoteSource: ...
def validate_staged_skill(staging_dir: Path) -> Skill: ...
```

Supported sources:

- `skills.sh` distribution URL.
- `github.com/<owner>/<repo>/tree/<ref>/<path>` tree URL.
- `raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>` URL resolving to a Skill entry file or install manifest.

Safety rules:

- Reject unsupported hosts before writing files.
- Do not require local `git`.
- Use GitHub HTTP APIs for GitHub tree content.
- Reject absolute paths, `..`, symlinks, excessive depth, excessive file count, excessive total bytes, and files over 1 MiB.
- Require exactly one installable Skill package root containing `SKILL.md`.
- Parse `SKILL.md` before moving into place.
- Use a staging directory and `Path.replace` or equivalent atomic rename into `~/.coco-code/skills/<skill-name>`.
- Existing target directory fails clearly in this phase. No overwrite path is implemented.
- On failure, staging is removed and no partial target directory remains.

### `coco_code.prompt`

`build_system_prompt` expands to accept Skill blocks:

```python
def build_system_prompt(
    cwd: Path,
    provider: ProviderConfig,
    instructions: str = "",
    memory: str = "",
    skills_catalog: str = "",
    active_skills: str = "",
) -> str: ...
```

Order:

1. Core system prompt.
2. Runtime facts.
3. Available Skills catalog.
4. Active Skills full SOP block.
5. Memory index.
6. Project and user instructions.

Active Skills are intentionally above memory and custom instructions so the currently selected SOP is easy for the model to notice. The startup catalog remains compact.

### `coco_code.llm` Providers

The `Provider` protocol gains:

```python
def set_system_prompt(self, text: str) -> None: ...
```

`OpenAIProvider`, `OpenAICompatProvider`, and `AnthropicProvider` already store `_system_prompt`, so the setter simply replaces that string. Existing construction still accepts an initial prompt.

### `coco_code.agent.loop`

`AgentLoop` gains two optional callbacks:

```python
SystemPromptBuilder = Callable[[], str]
ActiveRegistryBuilder = Callable[[ToolRegistry, AgentMode], ToolRegistry]
```

Minimal constructor extension:

```python
class AgentLoop:
    def __init__(..., system_prompt_builder: SystemPromptBuilder | None = None) -> None: ...
```

Before every model collection attempt, the loop calls the builder and updates the provider prompt:

```python
if self._system_prompt_builder is not None:
    self._provider.set_system_prompt(self._system_prompt_builder())
```

The loop also computes the effective registry every iteration:

```text
base registry = full registry filtered by active Skill whitelist if any
mode registry = registry_for_mode(base registry, effective mode)
```

Then it uses the effective registry consistently for:

- `collect_stream_turn(..., tools=effective_registry)`
- unknown or hidden tool validation
- tool batching
- context compaction estimates

`ToolExecutor` can still hold the full registry because only calls that survived effective-registry validation are executed.

### `coco_code.skills.executor`

Inline command flow:

1. `catalog.get_latest(name)`.
2. Render Skill body with command args.
3. Activate `runtime.active_skills.activate(name, rendered, allowed_tools)`.
4. Send a concise user trigger message, not the full SOP, into the main conversation.
5. Main `AgentLoop` sees the active SOP in the rebuilt system prompt and uses the active whitelist.

Fork command flow:

1. `catalog.get_latest(name)`.
2. Render Skill body.
3. Build a child `Conversation`:
   - `none`: no prior main history.
   - `recent`: last 5 user/assistant messages from main conversation.
   - `full`: compact summary text plus the rendered Skill request.
4. Build child `SessionRuntime` with its own `ActiveSkills` containing only this Skill.
5. Build child registry using the Skill whitelist plus system tools.
6. Build child `ToolExecutor` using the same tool context and permission callbacks.
7. Build child provider using the current provider config, or a matching configured provider when `model` is set.
8. Run child `AgentLoop` until stopped.
9. Append the final assistant text or failure summary into the main conversation through the UI.

The child conversation does not mutate main history during execution. Only the final summary is appended.

### `coco_code.command`

Command registry changes:

```python
class CommandRegistry:
    def remove_where(self, predicate: Callable[[Command], bool]) -> None: ...
    def names(self) -> tuple[str, ...]: ...
```

Skill command module:

```python
# src/coco_code/command/skills.py
SKILL_COMMAND_MARKER = "skill"

def register_skill_commands(registry: CommandRegistry, catalog: SkillCatalog, executor: SkillExecutor) -> None: ...
def remove_skill_commands(registry: CommandRegistry) -> None: ...
def register_skill_management_command(registry: CommandRegistry, catalog: SkillCatalog, reload_callback: Callable[[], None]) -> None: ...
```

Reserved commands are `help`, `clear`, `compact`, `plan`, `do`, `session`, `memory`, `permission`, `status`, `skill`, `exit`, `resume`, and `tools`. The existing hard-coded `/review` command is migrated to the built-in `review` Skill so `/review` comes from the Skill system.

`/skill` supports:

- `/skill list`: names, descriptions, modes, and source labels.
- `/skill info <name>`: metadata and source path, not full body by default.
- `/skill reload`: rescan catalog, validate tools, rebuild Skill slash commands, refresh provider prompt catalog.

### `coco_code.tui.app`

New fields:

```python
self.skill_catalog: SkillCatalog
self.skill_executor: SkillExecutor | None
self._load_skill_tool: LoadSkillTool
self._install_skill_tool: InstallSkillTool
self._skills_catalog_text: str
```

New methods:

```python
def build_current_system_prompt(self) -> str: ...
def setup_skills_after_tools_ready(self) -> None: ...
def reload_skills(self) -> None: ...
def clear_active_skills(self) -> None: ...
def append_assistant_message(self, text: str) -> None: ...
def list_catalog_skills(self) -> tuple[SkillCatalogItem, ...]: ...
def list_active_skills(self) -> tuple[str, ...]: ...
```

Integration points:

- `__init__` registers `LoadSkillTool` and `InstallSkillTool` before provider activation.
- `on_mount` starts MCP, then calls `setup_skills_after_tools_ready`, then activates provider.
- `activate_provider` uses `build_current_system_prompt()` for the initial provider prompt.
- `submit_user_text` passes `system_prompt_builder=self.build_current_system_prompt` into `AgentLoop`.
- `run_manual_compact` also uses the active registry and system prompt builder.
- `clear_history` clears `runtime.active_skills` and visible history.
- `append_assistant_message` writes fork summaries to both `Conversation` and visible history.

### Built-In Skills

Built-in samples ship as package resources:

```text
src/coco_code/skills/builtin/
  commit/SKILL.md
  review/SKILL.md
  test/SKILL.md
```

They use the exact same parser and catalog path as user and project Skills. Project and user Skills can override them by `name`.

## Module Interactions

### Startup

```text
cli.main
  -> CoCoCodeApp(...)
       -> create_default_registry()
       -> register LoadSkill + InstallSkill
       -> SkillCatalog.load(workspace)
       -> build default command registry without hard-coded review

on_mount
  -> start_mcp()
  -> setup_skills_after_tools_ready()
       -> catalog.validate_tools(full registry)
       -> remove invalid Skills from command/catalog visibility
       -> build /skill and /<skill-name> commands
       -> attach catalog/runtime/reload callbacks to tools
       -> render compact Available Skills catalog
  -> activate_provider()
       -> new_provider(config, build_current_system_prompt())
```

### Natural-Language Activation

```text
User asks for a reusable workflow
  -> model sees compact Available Skills catalog
  -> model calls LoadSkill({"name": "review", "arguments": "..."})
  -> LoadSkill renders and activates SOP in runtime.active_skills
  -> next AgentLoop iteration rebuilds provider system prompt
  -> active SOP appears in Active Skills block
  -> visible tools are filtered by the active Skill whitelist
```

### Slash Execution

```text
User enters /commit optional args
  -> command handler calls SkillExecutor.execute_command("commit", args, ui)
  -> inline Skill activates rendered SOP
  -> ui.send_user_message("Run active Skill commit ...", display_label="/commit ...")
  -> main AgentLoop handles the run with active SOP and whitelist
```

### Fork Execution

```text
User enters /review
  -> SkillExecutor detects mode=fork
  -> child Conversation and child SessionRuntime are created
  -> child AgentLoop runs with isolated prompt, history policy, and tool registry
  -> final child assistant text is appended to main Conversation as one assistant message
```

### Remote Installation

```text
Model or slash flow calls InstallSkill({source_url})
  -> normal permission check runs
  -> install_from_url downloads into staging
  -> package limits and path safety are validated
  -> SKILL.md is parsed
  -> staging is atomically moved into ~/.coco-code/skills/<skill-name>
  -> app reload callback rescans catalog, validates tools, rebuilds commands
  -> new /<skill-name> is available immediately
```

### Clear

```text
/clear
  -> clear visible history
  -> conversation.clear()
  -> runtime.active_skills.clear()
  -> future system prompts omit Active Skills
```

## File Organization

```text
src/coco_code/
  skills/
    __init__.py
    types.py
    parser.py
    catalog.py
    active.py
    render.py
    executor.py
    install.py
    builtin/
      __init__.py
      commit/SKILL.md
      review/SKILL.md
      test/SKILL.md
  tools/
    base.py                  # add ToolSpec.system
    registry.py              # names, system specs, filtered_by_names
    load_skill.py            # new LoadSkill tool
    install_skill.py         # new InstallSkill tool
  prompt.py                  # Skill catalog and active Skill prompt rendering
  llm/
    __init__.py              # Provider.set_system_prompt protocol
    openai_provider.py       # setter
    anthropic_provider.py    # setter
  agent/
    runtime.py               # active_skills field
    loop.py                  # dynamic prompt + active registry
    tools.py                 # registry filtering/validation uses effective registry
  command/
    builtins.py              # remove hard-coded review, add /skill registration path
    handlers.py              # clear calls ui.clear_active_skills
    registry.py              # remove_where, names
    skills.py                # register Skill slash commands and /skill
    types.py                 # CommandUI additions
  tui/
    app.py                   # Skill wiring, reload, fork summary, prompt builder

tests/
  test_skills_parser.py
  test_skills_catalog.py
  test_skills_active.py
  test_skills_render.py
  test_skills_executor.py
  test_skills_install.py
  test_tools_load_skill.py
  test_tools_install_skill.py
  test_prompt_skills.py
  test_command_skills.py
  test_agent_loop_skills.py
  test_tui_skills.py

docs/skill-system/
  spec.md
  plan.md
  task.md
  checklist.md
```

## Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| Skill roots | built-in < user < project | Matches spec priority and local project override expectations. |
| Built-in samples | Package resource Markdown files | Same parser and behavior as user Skills. |
| Skill name regex | `^[a-z][a-z0-9_-]*$` | Compatible with slash command parsing and provider tool naming habits. |
| Frontmatter failures | Skip single Skill, warn | One broken local file must not block startup. |
| Missing allowed tool | Remove/report invalid Skill at startup or reload | Fail fast once full registry, including MCP, is assembled. |
| System tool marker | `ToolSpec.system` | Current tools expose behavior through `ToolSpec`; registry filtering already works on specs. |
| Dynamic prompt | Provider setter plus AgentLoop builder callback | Current providers store system prompt once, but active Skills can change during a tool loop. |
| Inline whitelist | ActiveSkills union applied in AgentLoop | Ensures model-visible tools change while active SOPs are pinned. |
| Whitelist composition | Union of active whitelists plus system tools | Multiple active Skills can cooperate without hiding each other's declared tools. |
| Permission behavior | Keep existing ToolExecutor permission checks | Whitelists guide visibility, not authority. |
| Fork isolation | New Conversation and SessionRuntime | Keeps child tool history out of main history until final summary. |
| Fork full history | Use compact summary text | Bounded context while preserving useful prior state. |
| Model override | Match configured provider by name or model | Avoid ad hoc provider config construction without credentials. |
| Remote install | HTTP APIs, no local git | Works in constrained installs and is easier to bound. |
| Install overwrite | No overwrite in this phase | Avoid accidental loss of user Skills. |
| Install atomicity | Staging plus rename | Prevents partially installed packages. |
| `/review` | Migrate to built-in Skill | Avoid conflict and proves built-in Skills behave like normal Skills. |
| Reload | Rebuild Skill commands after catalog swap | Keeps completion and `/help` in sync. |

## Spec Coverage

| Spec area | Plan owner |
|---|---|
| F1-F6 definition format | `skills.parser`, `skills.types`, parser tests |
| F7-F10 storage and priority | `skills.catalog`, package resources |
| F11-F16 two-stage loading | `skills.render`, `LoadSkillTool`, `prompt.py`, `AgentLoop` dynamic prompt |
| F17-F21 execution modes | `skills.executor`, `SessionRuntime`, child `AgentLoop` |
| F22-F26 tool whitelist | `ToolSpec.system`, `ToolRegistry.filtered_by_names`, `AgentLoop` effective registry |
| F27-F33 slash and management | `command.skills`, `CommandRegistry.remove_where`, TUI reload hooks |
| F34-F43 remote installation | `skills.install`, `InstallSkillTool`, TUI reload callback |
| F44-F46 built-in samples | `skills/builtin/*/SKILL.md`, catalog priority |
| N1-N10 quality and safety | Prompt compactness, warnings, install limits, tests |
| AC1-AC20 acceptance | Focused unit and integration tests listed above |
