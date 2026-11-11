---
name: stop-hook-human-escalation
description: Repair Claude and Codex loop-stop handling so an unresolved graph raises one clear human approval instead of repeated raw hook prompts.
type: project
---

# Stop-hook human escalation

> Supersession note (2026-09-21): This is a historical Stop-hook repair handoff. Current root Stop gates are `hooks/scripts/loop_state_guard.py` and `loop_stall_guard.py`. Codex uses `packages/codex/hooks/scripts/graph_completion_guard.py`. The shell paths and proposed shared names below are historical. Keep each provider's own response contract.

## Goal

Repair loop-stop handling in the Claude and Codex plugins. If an agentic-loop graph cannot finish, give the user one clear prompt for approval. Do not show raw Stop-hook prompts again and again.

## Decisions

- Keep the fail-closed checks that run when a graph ends. Do not silently mark a graph complete or discard a hard stop.
- Keep each provider's own implementation. Give users the same behavior in Claude and Codex.
- Name the missing prerequisite. Tell the user why work cannot continue. Name the next step the user can accept or decline.
- Deduplicate by session and graph revision. If the graph changes after an escalation, one new escalation can occur. If it stays the same, do not escalate again.

## Constraints

- The Stop hook runs after the assistant ends its turn. If the hook injects a raw “resume” prompt, the assistant can reply again. This can cause a feedback loop.
- A hook can redirect and audit. The assistant must use the graph record to prompt the user for interactive approval. The hook cannot reliably do this itself.
- Keep all proof, eval, retro, hard-stop, and worker-evidence validation if a prompt occurs.
- Keep the graph helper mechanical. It must report the graph status. The user gives approval for recovery.

## Key files

- `hooks/hooks.json` and `hooks/scripts/loop_state_guard.sh`: Claude Stop-hook registration and graph-state gate.
- `packages/codex/hooks/hooks.json` and `packages/codex/hooks/scripts/loop_state_guard.sh`: Codex equivalent.
- `hooks/scripts/loop_stall_guard.sh` and `packages/codex/hooks/scripts/loop_stall_guard.sh` handle the end of a graph and stalled graphs.
- `skills/agentic-loop/SKILL.md` and `packages/codex/skills/agentic-loop/SKILL.md`: required human-escalation wording and resume path.
- `packages/codex/skills/agentic-loop/scripts/graph.py` supplies the graph status. Keep its fail-closed checks for the end of a graph.
- Active graph after recovery: `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a03d46-3a67-7b82-98d2-6e25e9ed3a77/progress.json`.

## Done so far

- Repaired the Factory loop with its source code unchanged.
- Recorded that all six frozen evals passed and graded the suite `GO` at revision 5.
- Ran `node --test factory/test/*.test.mjs`. All 28 tests passed.
- Added `proof.json` and `retro.json` only for the end of the graph. The graph finished at revision 6.
- Found the cause of the prompt loop. The graph could not finish and had no work it could start. The Stop hook gave the same raw “resume” prompt again, and each assistant reply triggered it again.

## Next steps

1. Read the Stop-hook and loop-skill paths for the two providers. Follow all branches for unfinished graphs, no work to start, or hard stops.
2. Write a small shared behavior specification and frozen tests. Check for one prompt for the same session and revision. Check for clear approval wording, recovery when the revision changes, and no prompt flood.
3. Add provider-native deduplication and a structured escalation payload to the two plugins.
4. Update the two agentic-loop skills. The assistant must prompt for approval one time and wait. It must use injected hook text as context for approval.
5. Run the two providers' hook tests plus a controlled transcript-level regression test proving one escalation only.
6. Independently examine the records for the PR head before merge.

## Open questions

- Which approval interface works best in each host? Options are a structured hook payload for the client or one assistant message with a session stamp.
- If a graph cannot recover, give only the option “start a fresh recovery graph”? Or also give the bounded option “repair this graph state”?
