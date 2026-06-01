# Claude Code Failure Log

Blameless record of cases where Claude's output was wrong, misleading, or incomplete.
Source data for the self-checking loop's weekly calibration review.

## How to use
Add a row when you catch a failure. Focus on the system gap, not on Claude.
Per Dekker: ask "why did it make sense to do that?" — not "whose fault?"

## Categories
- `inference` — claimed without verification
- `stale-memory` — recalled fact no longer current
- `hallucination` — fabricated file / function / API / citation
- `incomplete-search` — concluded "not found" from too narrow a query
- `misread-tool-output` — tool returned correct data, Claude misinterpreted it
- `misunderstood-intent` — answered a different question than was asked
- `overconfident` — high-confidence claim that was wrong
- `scope-drift` — went beyond what was authorized

## Entries

| Date | Claim | Reality | Category | What would have caught it |
|------|-------|---------|----------|---------------------------|
| 2026-05-01 | Block-mode Stop hooks (`check_did_not_verify.sh`, `check_confidence_labels.sh`) would safely enforce discipline by forcing Claude to redo non-compliant responses | Hooks fired exit 2 on responses that DID contain the required section/labels — race condition between hook execution and transcript flush. Standalone tests passed; live execution failed reproducibly | inference | A pre-deployment test that (a) runs the hook against a *live* Stop event rather than a synthetic transcript file, (b) checks `transcript_path` content vs `last_text` extracted at hook fire time. None of my standalone tests caught the timing dependency on the harness's transcript-write order |
| 2026-05-01 | "Use `#!/usr/bin/env python3` to fix auto_commit.py shebang" | The fix worked syntactically but pointed at /usr/bin/python3 (Apple's 3.9.6) when the script needs ≥3.11 — produced TypeError on PEP 604 union syntax. Five sibling .py hooks all use `#!/usr/bin/env -S uv run` which would have been the convention to follow | inference | A "match the convention of peers in the same directory" check before proposing any shebang fix. I should have read the other `.py` files in `~/.claude/hooks/` before guessing |
| 2026-05-01 | I would follow my own discipline rules (confidence labels, DNV section) once they were installed in CLAUDE.md and reinforced by warn-mode hooks | Multiple turns this session lacked the DNV section while warn-mode hooks fired silent reminders that I ignored. The user explicitly observed "another claude session just ignored the hooks prompt" — same failure mode | overconfident | Block-mode hooks (which we attempted then had to revert due to race-condition above). Warn-mode + memory-only enforcement is mechanically insufficient — confirms the Shingo prediction quoted during the build |

<!-- newest first; append rows above this comment -->
