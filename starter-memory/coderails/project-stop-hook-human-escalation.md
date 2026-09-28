---
name: stop-hook-human-escalation
description: Repair Claude and Codex loop-stop handling so an unresolved graph raises one clear human approval instead of repeated raw hook prompts.
type: project
---

# Stop-hook human escalation

> Supersession note (2026-09-21): This is a historical Stop-hook repair handoff. Current root Stop gates are hooks/scripts/loop_state_guard.py and loop_stall_guard.py; Codex uses packages/codex/hooks/scripts/graph_completion_guard.py. The shell paths and proposed shared names below are not current entrypoints. Preserve the distinct provider-native response contracts.

## Goal

Fix the rough edge shared by the Claude and Codex plugins: an incomplete agentic-loop graph must result in one clear, human-readable escalation, not repeated raw Stop-hook prompts.

## Decisions

- Preserve fail-closed graph completion. Do not silently mark a graph complete or discard a hard stop.
- Keep Claude and Codex implementations independent, but give them the same human-facing behaviour.
- An escalation must say what is missing, why work cannot continue, and the exact next action the human can approve or decline.
- Deduplicate by session and graph revision. A later graph-state change may produce one new escalation; unchanged state must not repeat.

## Constraints

- The Stop hook runs after a final reply. Reinjecting a raw “resume” prompt can make the assistant reply again, creating a feedback loop.
- A hook can redirect and audit but cannot reliably present an interactive approval itself. The assistant must translate the recorded graph state into the user-facing approval request.
- Do not weaken proof, eval, retro, hard-stop, or worker-evidence validation merely to avoid a prompt.
- Keep the graph helper mechanical; it should report state, not decide whether the user has approved a recovery.

## Key files

- `hooks/hooks.json` and `hooks/scripts/loop_state_guard.sh`: Claude Stop-hook registration and graph-state gate.
- `packages/codex/hooks/hooks.json` and `packages/codex/hooks/scripts/loop_state_guard.sh`: Codex equivalent.
- `hooks/scripts/loop_stall_guard.sh` and `packages/codex/hooks/scripts/loop_stall_guard.sh`: completion and stall handling.
- `skills/agentic-loop/SKILL.md` and `packages/codex/skills/agentic-loop/SKILL.md`: required human-escalation wording and resume path.
- `packages/codex/skills/agentic-loop/scripts/graph.py`: mechanical state source; retain its fail-closed completion checks.
- Active recovered state: `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a03d46-3a67-7b82-98d2-6e25e9ed3a77/progress.json`.

## Done so far

- Recovered the Factory loop without changing Factory source during recovery.
- Recorded all six frozen evaluation results as pass and graded the suite `GO` at revision 5.
- Ran `node --test factory/test/*.test.mjs`: 28 passed, 0 failed.
- Added completion-only `proof.json` and `retro.json`; graph completion succeeded at revision 6.
- Identified the failure pattern: an incomplete graph with no ready work caused repeated raw Stop-hook resume prompts; repeated assistant replies amplified it.

## Next steps

1. Read both providers' Stop-hook and loop-skill paths side by side; trace every incomplete/no-ready/hard-stop branch.
2. Write a small shared behaviour specification and frozen tests for: one prompt per unchanged session+revision, clear approval wording, recovery after a changed revision, and no prompt flood.
3. Implement provider-native deduplication and a structured escalation payload in both plugins.
4. Update both agentic-loop skills to require the assistant to present the approval once and then wait, rather than treating injected hook text as user work.
5. Run both providers' hook tests plus a controlled transcript-level regression test proving one escalation only.
6. Independently review exact-head evidence before merge.

## Open questions

- What is the best approval surface in each host: a structured hook payload consumed by the client, or a one-time assistant-generated approval message backed by a session stamp?
- Should a non-recoverable graph state offer only “start a fresh recovery graph”, or also a bounded “repair this graph state” action?
