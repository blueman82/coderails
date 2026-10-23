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
    "decision_blank_phase": "a decision needs a non-blank phase (for example 2.5).",
    "decision_blank_decision": "a decision needs a non-blank decision text; nothing was written.",
    "decision_invalid_chain": (
        "the decision chain is damaged; inspect and preserve the loop state before any further sync."
    ),
    "decision_sync_unknown": "a decision sync may have reached Muninn; inspect the store before any manual retry.",
    "decision_state_error": "the loop state could not be read, validated or locked; nothing was written.",
}
