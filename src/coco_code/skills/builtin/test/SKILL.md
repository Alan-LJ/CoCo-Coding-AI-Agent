---
name: test
description: Identify and run the relevant project tests, then report evidence.
allowed_tools:
  - Bash
  - ReadFile
  - Glob
  - Grep
mode: inline
---

Identify the project type and the most relevant test command for the user's request. Run the smallest useful test set first, then broaden only if needed.

Report the exact command, whether it passed or failed, and the key output needed to understand the result.

User request:

$ARGUMENTS
