# Token Limit Calibration Guide

## Overview

Token/byte caps in Claude Code are configured via `RACHEL_MAX_TURNS` (agent SDK) or directly in Claude Code's `settings.json` under runtime limits. This document guides calibration based on observed token burn in agentic loops.

## Where Token Limits Live

1. **Claude Code settings**: `~/.claude/settings.json` → `runtime.max_tokens_per_session` (or `maxTurns` for turn limits)
2. **Agent SDK**: Environment variable `RACHEL_MAX_TURNS` (for turn-limited loops)
3. **Coderails workflow**: No built-in token cap (delegates to Claude Code runtime)

## Calibration Process

### Step 1: Run a Representative Task Loop

Use `/coderails:agentic-loop` with a typical task (2–3 implementation units):
- Measure the total tokens burned across all turns
- Note the number of turns taken
- Record the loop type (implementation/review/investigation)

### Step 2: Examine Loop Artifacts

After loop completion, find:
- **`~/.claude/agentic-loop/<session_id>/retro.json`** — contains `cost.total_tokens` (as of schema_version ≥ 2)
- **Dashboard metrics** — `/coderails:dashboard` live-shows cost per dispatch
- **PR comment artifact** — `/coderails:post-evals` posts grading info with final token/USD spend

### Step 3: Calculate Headroom

Typical ratios for coderails loops:
- **Small task (1 unit)**: 50k–80k tokens
- **Medium task (2–3 units)**: 120k–200k tokens
- **Large task (4+ units)**: 250k–400k tokens

Add 20% headroom for context compaction and re-expansion overhead.

### Step 4: Set Limits

If observed burn is `X` tokens:
- **Conservative**: Set cap at `X × 1.3` (30% headroom)
- **Moderate**: Set cap at `X × 1.5` (50% headroom)
- **Generous**: Set cap at `X × 2.0` (100% headroom, accounts for edge cases)

## Measurement Example

**Hypothetical loop** (this repo, add tier-gate docs):
```
Turn 1 (planning):           12k tokens
Turn 2 (implementation):      45k tokens
Turn 3 (review + fixes):      28k tokens
Turn 4 (docs + test verification): 15k tokens
───────────────────────────
Total:                       100k tokens
```

**Recommended cap**: 130k–150k tokens (30–50% headroom)

## For This Repo (coderails)

No loop-driven token cap is currently configured. To calibrate for future contributors:

1. Run `/coderails:agentic-loop` on a typical feature (e.g., "add a new skill")
2. Observe `retro.json` cost breakdown
3. Set `runtime.maxTurns` or `max_tokens_per_session` in Claude Code settings based on findings
4. Update this document with the empirical limit

## Headless-Run Consideration

Headless runs (via `/coderails:dashboard` or API) may have lower overhead. Measure separately if deploying a scheduled loop.

## When to Re-Calibrate

- After major codebase changes that increase response sizes
- When adding new implementation-unit types (e.g., `frontend-render` workers)
- Quarterly, to account for model efficiency improvements in Claude

## References

- [Agentic Loop SKILL.md](../skills/agentic-loop/SKILL.md) — Phase 13 retro minting + cost mining
- [Coderails Dashboard](../skills/dashboard/) — Real-time token burn visualization
- [Claude SDK cost tracking](https://github.com/anthropics/anthropic-sdk-python) — `usage.output_tokens` / `usage.input_tokens`
