from __future__ import annotations

# Tool results above this byte size are moved to disk individually.
SINGLE_RESULT_LIMIT_BYTES = 50_000

# A single assistant tool-call batch is reduced until it fits this byte budget.
BATCH_RESULT_LIMIT_BYTES = 200_000

# Reserved output budget while deciding whether history is too large.
SUMMARY_RESERVE_TOKENS = 20_000

# Extra headroom used by automatic pre-request compaction.
AUTO_SAFETY_MARGIN_TOKENS = 13_000

# Extra headroom used by manual and emergency compaction.
MANUAL_SAFETY_MARGIN_TOKENS = 3_000

# Recent raw history kept after summary compaction.
RECENT_KEEP_TOKENS = 10_000

# Minimum number of recent conversation items kept after summary compaction.
RECENT_KEEP_ITEMS = 5

# Number of recent file snapshots included in recovery text.
RECOVERY_FILE_LIMIT = 5

# Per-file recovery text cap, estimated rather than tokenized exactly.
RECOVERY_TOKENS_PER_FILE = 5_000

# Consecutive automatic summary failures before the automatic path trips.
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3

# Number of one-group drops before proportional PTL drops begin.
PTL_RETRY_LIMIT = 3

# Proportional group drop used after the initial PTL retries.
PTL_DROP_PERCENTAGE = 0.2

# Approximate character-to-token ratio for the estimator.
ESTIMATE_CHARS_PER_TOKEN = 3.5

# Bytes of tool-result head preview kept in the conversation.
PREVIEW_HEAD_BYTES = 2048

# Lines of tool-result head preview kept in the conversation.
PREVIEW_HEAD_LINES = 20
