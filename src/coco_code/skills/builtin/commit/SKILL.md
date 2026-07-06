---
name: commit
description: Draft a concise commit message from the current changes.
allowed_tools:
  - Bash
  - ReadFile
  - Grep
mode: inline
---

Review the current working tree and draft a commit message.

Use repository evidence rather than guessing. Prefer a short conventional-commit style subject, followed by bullet details only when they add useful context.

User request:

$ARGUMENTS
