---
name: review
description: Review code changes for bugs, regressions, missing tests, and security risks.
allowed_tools:
  - ReadFile
  - Grep
  - Glob
  - Bash
mode: inline
context: recent
---

Review the current code changes and context. Prioritize bugs, behavioral regressions, missing tests, security risks, and maintainability issues.

Present findings first. Include concrete file, symbol, command, or behavior references. Keep summaries brief and put them after findings.

User request:

$ARGUMENTS

