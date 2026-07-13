# Skill System Spec

## Background

CoCo Code users often repeat the same AI operation prompts: commit message rules, code review checklists, test-running procedures, migration playbooks, and project-specific SOPs. Today these reusable prompts either live as hard-coded slash commands or must be pasted by the user each time. This creates three problems:

- Reusable AI procedures are hard to share, override, and maintain as ordinary project assets.
- When many tools are available, the model has more chances to pick the wrong tool for a narrow task.
- There is no task-level way to load a full SOP only when needed, isolate work into a separate conversation, or clear temporary instructions with the conversation.

The Skill system turns a reusable AI operation into a Markdown-based capability package. At startup the agent only sees a catalog of Skill names and one-line descriptions. When a Skill is needed, a system-level loader tool fetches the full SOP and pins it into the environment context for subsequent turns.

## Goals

- Define a file format for reusable Skills using YAML frontmatter plus Markdown SOP body.
- Load Skills from project, user, and built-in locations with deterministic priority.
- Support two-stage disclosure: lightweight catalog at startup, full SOP only on demand.
- Keep activated Skill instructions prominent and persistent across every environment-context rebuild until the conversation is cleared.
- Support both shared execution in the current conversation and isolated execution in a separate conversation.
- Use Skill-declared tool whitelists to narrow the visible tool set and improve tool choice.
- Register loaded Skills as slash shortcuts and support hot updates without restarting the app.
- Provide built-in sample Skills for commit, review, and test workflows.

## Functional Requirements

### Skill Definition Format

- F1: A single-file Skill MUST be a Markdown file with YAML frontmatter followed by a Markdown body. The frontmatter contains metadata; the body is the SOP instruction sent to the model when the Skill is activated or executed.
- F2: A directory Skill MUST be a directory containing an entry Markdown file named `SKILL.md`. The directory MAY also contain templates, examples, helper scripts, and reference documents. The directory is treated as one capability package.
- F3: The frontmatter MUST support these fields:
  - `name`: unique Skill name, used for catalog lookup and slash command registration.
  - `description`: one sentence shown in the startup catalog.
  - `allowed_tools`: optional list of visible tool names for this Skill.
  - `mode`: execution mode, `inline` for shared conversation or `fork` for isolated conversation. If absent, defaults to `inline`.
  - `context`: isolated-mode history policy, `none`, `recent`, or `full`. If absent, defaults to `none` and only affects `fork` mode.
  - `model`: optional model override for this Skill.
- F4: Skill names MUST be compared case-insensitively and MUST be valid slash-command names. A project or user Skill with the same name as a built-in sample Skill overrides the lower-priority Skill.
- F5: The Markdown body MUST support parameter placeholder substitution. `$ARGUMENTS` is replaced with the text passed by the user through the slash command or tool invocation. If no placeholder exists and arguments are provided, the system MAY append the user arguments in a clearly marked request section.
- F6: Invalid frontmatter, missing required fields, malformed YAML, unreadable files, or invalid Skill names MUST cause only that Skill to be skipped with a warning. One broken Skill file MUST NOT block loading other Skills.

### Storage And Priority

- F7: Skills MUST be discovered from three levels, in priority order: project directory, user directory, then built-in directory. Higher-priority Skills with the same name override lower-priority Skills.
- F8: Project Skills live under the current project configuration area, user Skills live under the user configuration area, and built-in Skills ship with the application. The exact paths are implementation details, but they MUST be documented for users.
- F9: Directory and single-file Skills MAY coexist in the same storage level. A directory Skill is identified by its `SKILL.md`; a single-file Skill is identified by its own Markdown file.
- F10: Discovery order MUST be deterministic. The same filesystem state MUST produce the same catalog, override decisions, slash commands, and startup catalog text.

### Two-Stage Loading

- F11: At startup, the system MUST inject only each available Skill's `name` and `description` into the conversation. Full SOP bodies, templates, examples, helper scripts, and reference documents MUST NOT be injected at startup.
- F12: The startup catalog MUST tell the model that it can call the Skill-loading tool when a listed Skill is relevant.
- F13: A built-in `LoadSkill` tool MUST load a Skill's complete SOP on demand by name. It returns a short confirmation and MUST NOT return the full SOP as tool output.
- F14: `LoadSkill` is a system-level read-only tool. It MUST remain available even when a Skill's `allowed_tools` whitelist would otherwise hide tools.
- F15: Loading a Skill MUST activate it by pinning the rendered SOP into the environment context. The active Skill block MUST appear in the most prominent environment-context area after core runtime facts and before ordinary project or user instruction blocks.
- F16: Every agent turn that rebuilds environment context MUST include all currently active Skills. Multiple Skills MAY be active at the same time and MUST be rendered in deterministic activation order.

### Execution Modes

- F17: In `inline` mode, Skill execution happens in the current conversation. The rendered SOP and the user's request participate in the main Agent loop, and all assistant messages and tool results remain in the main history.
- F18: In `fork` mode, Skill execution happens in an isolated conversation. The child run MUST NOT mutate the main conversation until it finishes.
- F19: `fork` mode MUST support three history policies:
  - `none`: pass no prior main conversation history.
  - `recent`: pass a bounded recent slice of main conversation history.
  - `full`: pass a compacted or summarized representation of the main conversation.
- F20: A completed `fork` run MUST write a concise result summary back into the main conversation. Tool calls and intermediate child history SHOULD remain outside the main history unless explicitly summarized.
- F21: If a Skill specifies `model`, the isolated run SHOULD use that model when available. If the model is unavailable or unsupported, the user MUST receive a clear error or fallback notice.

### Tool Whitelist

- F22: `allowed_tools` narrows the tools visible to the model while the Skill is executing or active. System-level tools, including `LoadSkill`, are exempt and remain available.
- F23: Startup and hot reload MUST validate every `allowed_tools` entry after the full tool registry is assembled. If a valid Skill references a tool that does not exist, the system MUST immediately report an error naming the Skill and missing tool. The error MUST NOT be deferred until execution time.
- F24: For `fork` mode, the child conversation MUST receive only the whitelisted tools plus system-level tools. If `allowed_tools` is empty or absent, the child receives the normal available tool set.
- F25: For active `inline` Skills, the current conversation's visible tool set MUST be narrowed while any active Skill declares a whitelist. If multiple active Skills declare whitelists, the effective visible set is the union of their whitelists plus system-level tools.
- F26: Tool whitelisting is a visibility and tool-choice mechanism. It MUST NOT bypass the existing permission system, confirmation rules, filesystem sandbox, or command safety checks.

### Slash Commands And Management

- F27: Each loaded Skill MUST automatically register a slash shortcut named `/<skill-name>`.
- F28: Slash shortcut execution MUST use the same Skill executor as model-triggered loading, so explicit user commands and model intent recognition share the same behavior.
- F29: Core built-in slash commands such as clear, quit, help, and Skill management commands are reserved. A Skill name that conflicts with a reserved command MUST be rejected with a clear warning or error.
- F30: The system MUST provide Skill management commands for listing loaded Skills, inspecting metadata and source location, and reloading the Skill catalog.
- F31: Hot update MUST allow changed Skill files to take effect without restarting the application. Re-executing or reloading a Skill MUST read the latest valid source from disk.
- F32: If a hot-updated Skill becomes invalid, the system MUST keep the last valid version for already registered commands when possible and report a warning. New invalid Skills are skipped.
- F33: Clearing the conversation MUST also clear all active Skills. The catalog remains loaded, but no previously active SOP remains pinned into subsequent environment context.

### Remote Installation

- F34: The system MUST provide an `InstallSkill` tool that installs directory Skills into the user Skill directory from supported remote URLs.
- F35: `InstallSkill` is NOT a system-level tool. It writes files and uses network access, so it MUST be treated as a normal non-read-only tool and remain subject to the existing permission and confirmation system.
- F36: Supported URL forms MUST include:
  - a Skill distribution URL from `skills.sh`,
  - a GitHub repository tree URL,
  - a `raw.githubusercontent.com` URL that resolves to a Skill entry file or install manifest.
- F37: Unsupported hosts or unsupported URL shapes MUST be rejected before any files are written.
- F38: Remote installation MUST fetch the package without requiring a local `git` executable. GitHub tree URLs SHOULD use the GitHub Contents API or another HTTP-based GitHub API.
- F39: Installation MUST enforce these limits: each file no larger than 1 MiB, total downloaded content no larger than 8 MiB, no more than 64 files, and directory depth no greater than 4.
- F40: Installation MUST stage downloads in a temporary sibling or temporary user directory, validate that the package contains a `SKILL.md`, parse the Skill successfully, and then atomically move it into the user Skill directory.
- F41: Installation MUST prevent path traversal, absolute paths, symlink writes, and writes outside the intended user Skill directory.
- F42: If a target Skill directory already exists, installation MUST fail with a clear message unless the implementation provides an explicit overwrite path that goes through normal permission checks.
- F43: After a successful install, the system MUST reload the Skill catalog, validate tool whitelists, and refresh slash command registration so the new Skill can be used without restarting.

### Built-In Samples

- F44: The application MUST ship built-in sample Skills named `commit`, `review`, and `test`.
- F45: Built-in sample Skills MUST use the same file format, loading path, slash registration, tool whitelist validation, and activation behavior as user and project Skills.
- F46: User-level or project-level Skills with the same names as built-in samples MUST override the built-in samples according to the standard priority rules.

## Non-Functional Requirements

- N1: Startup catalog injection MUST stay compact. It includes only names, one-line descriptions, and a short instruction to call `LoadSkill`.
- N2: Full SOP bodies MUST appear only after explicit slash execution or model-triggered `LoadSkill`.
- N3: Parsing failures are isolated per Skill and reported as warnings without blocking unrelated Skills.
- N4: Missing tool dependencies in `allowed_tools` are fail-fast validation errors for that Skill and are reported during startup or reload.
- N5: `fork` mode MUST isolate conversation state, active Skills, and child tool history from the main conversation except for the final summary.
- N6: Hot reload MUST be deterministic and safe under concurrent user interaction. A reload cannot leave the catalog or slash command registry in a partially updated state.
- N7: Skill files may contain sensitive local workflow details. Logs, warnings, and tool results MUST avoid dumping full SOP bodies unless the user explicitly asks to inspect a Skill.
- N8: The feature MUST preserve existing behavior when no Skills are installed beyond built-in samples.
- N9: The implementation MUST include focused tests for parsing, priority override, catalog injection, activation, tool filtering, slash registration, hot reload, clear behavior, and both execution modes.
- N10: Remote installation MUST be defensive by default: bounded downloads, no path traversal, no implicit overwrites, no cleartext secret logging, and no partial installed directory after failure.

## Out Of Scope

- Marketplace distribution, publishing, rating, discovery, or version management for Skills.
- Package signing, dependency resolution, update channels, or automatic upgrades.
- A standalone Skill server protocol.
- Automatic natural-language intent classification outside the model's normal ability to read the startup catalog and call `LoadSkill`.
- Non-Markdown Skill entry formats.
- Security bypasses based on Skill metadata. Skills cannot grant themselves filesystem, command, network, or permission privileges.

## Acceptance Criteria

- AC1: Given valid project, user, and built-in Skills with overlapping names, the catalog shows the highest-priority version and skips lower-priority duplicates.
- AC2: Given one invalid Skill file and several valid Skill files, startup skips only the invalid file, reports a warning, and loads the valid Skills.
- AC3: Given a Skill with `name` and `description`, startup injects only those fields into the Skill catalog and does not inject the full SOP body.
- AC4: Given a relevant user request, the model can call `LoadSkill` by name and receive a confirmation while the full SOP is pinned into the next environment context.
- AC5: Given multiple active Skills, every subsequent environment-context rebuild includes all active SOPs in deterministic activation order.
- AC6: Given `/clear`, the main conversation history is cleared and the active Skill list becomes empty.
- AC7: Given a Skill with `$ARGUMENTS`, slash execution replaces `$ARGUMENTS` with the user-provided text.
- AC8: Given an `inline` Skill, assistant output and tool results remain in the main conversation history.
- AC9: Given a `fork` Skill with `context: none`, the child run starts without main conversation history and writes only a final summary back to the main conversation.
- AC10: Given `fork` Skills with `context: recent` and `context: full`, the child run receives the configured amount of main history and keeps intermediate child history out of the main conversation.
- AC11: Given a Skill with `allowed_tools`, the model sees only those tools plus system-level tools during Skill execution or activation.
- AC12: Given `allowed_tools` containing a nonexistent tool, startup or reload reports an immediate error naming the missing tool and does not silently defer the failure.
- AC13: Given a whitelist that omits `LoadSkill`, nested Skill loading still works because `LoadSkill` is system-level and exempt.
- AC14: Given a changed `SKILL.md`, reloading or re-executing the Skill uses the latest valid SOP without restarting the application.
- AC15: Given a changed `SKILL.md` with invalid frontmatter, the previous valid version remains usable when cached and the user sees a warning.
- AC16: Given built-in `commit`, `review`, and `test` Skills, `/commit`, `/review`, and `/test` are available unless overridden by higher-priority Skills.
- AC17: Given no user or project Skills, the application still starts with built-in samples and existing non-Skill behavior remains unchanged.
- AC18: Given a supported remote Skill URL, InstallSkill downloads it into a staging area, validates SKILL.md, atomically installs it into the user Skill directory, reloads the catalog, and makes its slash command available without restart.
- AC19: Given an unsupported host, oversized file, excessive file count, excessive depth, missing SKILL.md, invalid Skill metadata, symlink, absolute path, or path traversal entry, installation fails without leaving a partially installed Skill.
- AC20: Given an existing target Skill directory, installation fails clearly unless the user explicitly chooses a supported overwrite path.



