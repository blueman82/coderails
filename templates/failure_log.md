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

<!-- newest first; append rows above this comment -->
