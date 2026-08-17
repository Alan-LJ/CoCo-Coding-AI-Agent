# Post-edit verification gate

CoCo runs a deterministic verification gate after a successful code write and
before the agent loop is allowed to complete. A failed command is inserted back
into the conversation as structured system feedback, so the same agent can fix
the implementation and try again. When the configured repair budget is
exhausted, the run ends with an explicit verification error instead of claiming
success.

## Configuration

Add this section to `.coco-code/config.yaml` or
`.coco-code/config.local.yaml`:

```yaml
verification:
  enabled: true
  # Explicit commands are the most predictable option and override discovery.
  commands:
    - python -m pytest -q
  auto_discover: true
  timeout_seconds: 300
  max_fix_attempts: 2
  fail_fast: true
  output_limit: 12000
```

`max_fix_attempts` counts repair opportunities after the initial failed check.
For example, `2` allows at most three verification runs. `output_limit` keeps
large compiler/test logs from flooding the model context; the tail is retained
because it normally contains the actionable failure.

When `commands` is empty, discovery recognizes only high-confidence project
markers at the workspace root:

- Python: pytest when `tests/`, `pytest.ini`, root `test_*.py`, or pytest config
  is present.
- Node.js: existing `typecheck`, `check`, `test`, and `build` package scripts,
  using the detected lockfile's package manager.
- Rust, Go, .NET, Maven, and Gradle: their standard test commands.

Discovery never installs packages. A missing runtime or dependency therefore
fails verification and is reported to the agent.

## Completion semantics

The gate runs only after a successful built-in write tool changes a source file
or project manifest. Documentation-only writes do not trigger auto-discovered
commands; explicitly configured commands do run after any file write. Read-only
tasks are unaffected.

Commands run sequentially with `CI=true`, a per-command timeout, combined
stdout/stderr, and standard exit-code semantics. A non-zero exit code fails the
gate. The TUI and remote clients expose the result as a
`verification-gate` lifecycle event.

## First-version boundaries

- The gate verifies the final workspace state; it does not prove that a failure
  was introduced by the current edit.
- Writes performed indirectly inside an arbitrary shell command are not yet
  tracked. Built-in `WriteFile` and `EditFile` operations are tracked.
- Root-level discovery is intentionally conservative. Monorepos and unusual
  build systems should configure commands explicitly.
