"""Single source of truth for typed-memory reason codes: code -> one-line remediation.

Every code the adapter (or a Muninn refusal mapped to `refused_<code>`) can emit is here, and a test checks that
docs/RUNBOOK.md ("Memory degraded (Muninn authoritative)") names each one.
"""

from __future__ import annotations

REASONS: dict[str, str] = {
    "memory_backend_off": (
        "memory.backend is off in the workflow config; set it to muninn (or remove the key) to write " "typed memory."
    ),
    "memory_backend_invalid": "memory.backend must be muninn or off; fix the value in .coderails/workflow.config.yaml.",
    "muninn_absent": "muninn is not on PATH; install it (the Markdown path is not a fallback).",
    "muninn_old_ledger": "muninn lacks the Part A flags (--scope-loop, --confidence, ...); upgrade muninn.",
    "muninn_timeout": "muninn hung past 10s; run `muninn know list` by hand and check store locks.",
    "muninn_error": (
        "muninn exited nonzero or returned unparseable JSON; rerun the same `muninn know ...` command and "
        "read stderr."
    ),
    "muninn_bad_output": (
        "muninn wrote the entry but printed no K-id; run `muninn know list --scope-loop <id>` to find it."
    ),
    "muninn_store_missing": "no Muninn store at $MUNINN_HOME (or ~/.local/share/muninn); run `muninn ingest` once.",
    "muninn_schema_old": (
        "the store is schema v1 (PRAGMA user_version != 2); upgrade it with muninn itself, never by hand."
    ),
    "muninn_schema_incomplete": (
        "the store lacks a typed column or table (confidence, valid_until, sensitivity, contradicts, "
        "tags, fts); run `muninn doctor`."
    ),
    "uncited_write": "give a verbatim --quote (and --cite ref); a record without a quote is never written.",
    "restricted_refused": "restricted records are never written by the adapter; write a normal-sensitivity claim.",
    "bad_record": (
        "the record failed validation (type, scope, tag, date, empty claim, or loop scope without a loop " "id)."
    ),
    "handwritten_protected": "the render target is hand-written (no generator marker); render to a new path.",
    "cite_not_user": (
        "the cite must anchor in a user prompt; cite the owner's own words or use the approved-reply " "form."
    ),
    "cite_too_short": (
        "a quote-only cite needs 12 to 300 characters; quote more of the user's prompt or cite an "
        "approval with its reply."
    ),
    "cite_unresolved": (
        "the cite ref was not found in `muninn session <root>`, or the approval has no reply before it; "
        "check the ref."
    ),
    "cite_not_own_session": (
        "the cite ref belongs to another session; only a prompt of the caller's own session (--session) can "
        "anchor a write."
    ),
    "cite_bad_approval": (
        "the approval must be a short user prompt (80 chars or fewer) that directly follows the reply it answers."
    ),
    "refused_uncited": "muninn got no citation; pass --cite/--quote.",
    "refused_not_found": "the cite ref does not resolve; run `muninn ingest` and check the ref.",
    "refused_not_citable": (
        "the cited event is a subagent thread; only the orchestrator session can write typed records."
    ),
    "refused_quote_length": (
        "the quote must be 12 to 300 characters (a shorter one is valid only as a whole approval prompt)."
    ),
    "refused_quote_not_found": "the quote is not verbatim in the cited event; copy it exactly.",
    "refused_approval_needs_reply": (
        "a short approval needs the reply it answers cited too; use the approved-reply form (--approval " "REF)."
    ),
    "refused_preference_needs_user": "a preference must cite a user prompt.",
    "refused_bad_supersedes": "the superseded K-id is missing, not current, or in another scope.",
    "refused_bad_contradicts": "the contradicted K-id does not exist.",
    "refused_bad_valid_until": "valid_until must be a future ISO date.",
    "refused_bad_tags": "tags must match [a-z0-9_-]{1,32}.",
    "refused_bad_loop_scope": "the loop id is invalid, or --global was combined with a loop scope.",
    "refused_bad_kind": "the record kind is not one muninn accepts.",
    "refused_text_length": "the claim must be 1 to 500 characters.",
    "refused_no_caller_session": (
        "quote-only writes need CLAUDE_CODE_SESSION_ID or CODEX_SESSION_ID in the environment."
    ),
    "refused_other": (
        "muninn refused with a code not listed here; the reason is `refused_<code>`, read it and the " "muninn docs."
    ),
    "decision_wrong_session": "the loop state belongs to another session; record only from the owning session.",
    "decision_wrong_loop": "the loop changed after the caller read it; read its current loop ID before recording.",
    "decision_wrong_revision": "the graph changed after the caller read it; read its revision before recording.",
    "decision_blank_phase": "a decision needs a non-blank phase (for example 2.5).",
    "decision_blank_decision": "a decision needs a non-blank decision text; nothing was written.",
    "decision_invalid_chain": (
        "the decision chain is damaged; inspect and preserve the loop state before any further sync."
    ),
    "decision_sync_unknown": "a decision sync may have reached Muninn; inspect the store before any manual retry.",
    "decision_state_error": "the loop state could not be read, validated or locked; nothing was written.",
    "order_chain_broken": (
        "orders.json was edited by hand (the hash chain names the order); restore it from backup or review the "
        "named order, then re-seal by recording through orders.py."
    ),
    "order_blank_field": "an order needs a non-blank failure mode and lesson; nothing was written.",
    "order_lesson_too_long": (
        "the collapsed lesson exceeds 500 characters; provide a shorter complete claim, never truncate it."
    ),
    "order_bad_id": "an explicit order id must match [a-z0-9][a-z0-9_-]{0,119}; use a canonical id.",
    "order_id_collision": (
        "that order id already names another failure mode or scope; use its real identity or a distinct id."
    ),
    "order_not_found": "no order with that id in orders.json; check the id with `orders.py lessons`.",
    "order_state_error": (
        "orders, preparation or receipt could not be read, locked or written; check the repo-key dir, "
        "orders.lock and persistent teardown.jsonl.lock."
    ),
    "order_loop_unknown": (
        "no source at <repo-key dir>/<session>/progress.json; pass the owning --session and its separate "
        "logical --loop."
    ),
    "order_wrong_session": (
        "the source directory, session or logical loop is foreign; use the owning directory and identifiers."
    ),
    "order_source_invalid": (
        "progress, preparation or observations are malformed; restore genuine validated source artifacts."
    ),
    "order_source_mismatch": (
        "the prepared source/hash is stale; before completion use prepare --refresh-from-sha256 with its "
        "CURRENT evidence_sha256."
    ),
    "order_loop_ineligible": (
        "the owned graph or work units are incomplete or stopped; finish the existing completion requirements."
    ),
    "order_not_complete": (
        "preparation is prospective; durably save owned progress as complete before applying recurrence or aging."
    ),
    "order_pending_teardown": (
        "completion saved but local apply or its observation failed; retry tick with the same bound source."
    ),
    "order_retro_validator_unavailable": (
        "schema3 retros require the matching retro_check validator; install the matching validator before graduation."
    ),
    "order_already_ticked": "this session and logical loop were already counted; the tick was skipped (informational).",
    "no_user_cite": (
        "the order was stored without a user quote; attach it with `orders.py cite <id> --quote <verbatim owner "
        "prompt text>`."
    ),
    "legacy_uncited": "an imported hand-written order has no cite yet; attach one with `orders.py cite <id> --quote`.",
    "legacy_parse_error": (
        "the local legacy input has an incomplete, ambiguous or colliding entry; fix the named entry and "
        "rerun import-legacy, preserving the original."
    ),
    "legacy_missing": "there is no hand-written standing-orders.md to import (absent, empty or already generated).",
    "lesson_not_current": (
        "the order has no unambiguous current cited Muninn claim (retracted, expired, superseded or conflicting "
        "current claims); inspect the current evidence and explicitly record the intended lesson with a fresh quote."
    ),
}
