"""Single source of truth for typed-memory reason codes: code -> one-line remediation.

Every code the adapter (or a Muninn refusal mapped to `refused_<code>`) can emit is here, and a test checks that
docs/RUNBOOK.md ("Memory degraded (Muninn authoritative)") names each one.
"""

from __future__ import annotations

REASONS: dict[str, str] = {
    "memory_backend_off": (
        "The workflow config sets `memory.backend` to `off`. To write typed memory, set it to `muninn` or remove "
        "the key."
    ),
    "memory_backend_invalid": "Set `memory.backend` to `muninn` or `off` in `.coderails/workflow.config.yaml`.",
    "muninn_absent": "Install `muninn` and put it on `PATH`. The Markdown path cannot serve as a fallback.",
    "muninn_old_ledger": (
        "The installed Muninn command has no learning tasks, or this record has only an earlier K-id. Legacy "
        "bindings cannot establish the source of the current learning task."
    ),
    "muninn_timeout": "Muninn took more than 10 seconds. Run `muninn know list` by hand and check the store locks.",
    "muninn_error": (
        "Muninn gave a nonzero exit code or JSON that cannot be read. Run the same `muninn know ...` command again "
        "and read stderr."
    ),
    "muninn_bad_output": (
        "The Muninn reply does not agree with the learning task or the current Note rules. Examine the output."
    ),
    "learning_pending": "Muninn accepted the learning task. Keep its R_ ID and use it to check the same task again.",
    "learning_request_unknown": (
        "Muninn can accept a learning task without giving its R_ ID. Examine `muninn learn list`. Do not send the "
        "task again."
    ),
    "learning_request_failed": (
        "The saved Muninn task did not finish successfully, or it was cancelled. Examine it with `muninn learn "
        "show R_ID`."
    ),
    "learning_no_matching_record": (
        "The completed task gave no active Note for this task and text. Examine the receipt and Notes."
    ),
    "learning_no_change": "The saved task ended without a change to knowledge. No Note was written.",
    "learning_request_mismatch": (
        "The binding and the learning task differ in project, task, source window, or receipt identity."
    ),
    "learning_receipt_unavailable": (
        "The learning task has no committed receipt that this reader can use. Muninn can accept the task without "
        "writing a Note."
    ),
    "learning_record_changed": "Listed and shown current revisions differ. Read again with the same binding.",
    "learning_record_expired": "The current Note reached its expiry time. Do not use it.",
    "learning_record_ambiguous": (
        "More than one receipt matches this K-id and revision. No learning task was selected."
    ),
    "learning_form_unsupported": "This reader reads Notes only. It cannot use Guides.",
    "learning_conditional_use_unsupported": (
        "The Note has conditions for use or expiry. Legacy dispatch, promotion, and render cannot check those "
        "conditions. Keep the metadata. Do not use the Note unconditionally."
    ),
    "learning_selection_unavailable": (
        "An E-id, ref, hash, or excerpt is necessary but unavailable. Do not cite this Note."
    ),
    "learning_evidence_mismatch": (
        "The saved record identity, selector, scope, or source window differs from the binding."
    ),
    "learning_source_changed": "A physical source or its saved provenance changed. Do not cite it.",
    "learning_source_unavailable": "A necessary live source file is unavailable. Do not cite it.",
    "learning_source_authority": (
        "Use only live, primary, unflagged, unredacted prompts directly from the owner as sources. Current Muninn "
        "has no `normal` or `restricted` classes. Do not infer a class."
    ),
    "learning_quote_mismatch": "The saved excerpt differs from the source in the public quote check. Do not cite it.",
    "learning_read_limit": "The read exceeded a time, reply, record, or source limit. It did not give all results.",
    "learning_project_unavailable": "The calling project directory is unavailable. Do not use the graph key.",
    "muninn_store_missing": (
        "There is no Muninn store at `$MUNINN_HOME` or `~/.local/share/muninn`. Run `muninn ingest` one time."
    ),
    "muninn_schema_old": (
        "The D4 adapter expects retired schema v2. Current Muninn uses schema v1. Do not migrate the store to v2."
    ),
    "muninn_schema_incomplete": (
        "The D4 adapter expects retired v2 columns or tables. Examine the current store with `muninn doctor`. Then "
        "redesign the adapter."
    ),
    "uncited_write": (
        "Supply a verbatim `--quote` and `--cite ref`. The adapter cannot write a record without a quote."
    ),
    "restricted_refused": "The adapter does not write restricted records. Write a normal-sensitivity claim.",
    "bad_record": (
        "The record has an error in its type, scope, tag, date, claim text, or loop ID. A claim must have text, "
        "and loop scope must have a loop ID."
    ),
    "handwritten_protected": "The target has no generator marker and is hand-written. Write the view to a new path.",
    "cite_not_user": (
        "The citation must point to a user prompt. Cite the owner's words or use the approved-reply syntax."
    ),
    "cite_too_short": (
        "A quote-only citation must have 12 to 300 characters. Use more text from the user's prompt or cite the "
        "approval with its reply."
    ),
    "cite_unresolved": (
        "The ref did not occur in `muninn session <root>`, or the approval has no preceding reply. Check the ref."
    ),
    "cite_not_own_session": (
        "The ref points to a different session. Only a user prompt from the calling session (`--session`) can "
        "authorize the write."
    ),
    "cite_bad_approval": (
        "the approval must be a short user prompt (80 chars or fewer) that directly follows the reply it answers."
    ),
    "refused_uncited": "Muninn got no citation. Supply `--cite` and `--quote`.",
    "refused_not_found": "The ref does not resolve. Run `muninn ingest` and check the ref.",
    "refused_not_citable": (
        "The citation points to a subagent thread. Only the orchestrator session can write typed records."
    ),
    "refused_quote_length": (
        "A quote must have 12 to 300 characters. A shorter quote must be the full approval prompt."
    ),
    "refused_quote_not_found": "The quote differs from the cited text. Copy the source text verbatim.",
    "refused_approval_needs_reply": "For a short approval, also cite the reply it answers. Use `--approval REF`.",
    "refused_preference_needs_user": "a preference must cite a user prompt.",
    "refused_bad_supersedes": "There is no K-id to supersede, or the K-id is out of date or has a different scope.",
    "refused_bad_contradicts": "There is no K-id for the contradiction.",
    "refused_bad_valid_until": "valid_until must be a future ISO date.",
    "refused_bad_tags": "Use tags with the format `[a-z0-9_-]{1,32}`.",
    "refused_bad_loop_scope": "The loop ID has an error, or the caller used `--global` with loop scope.",
    "refused_bad_kind": "Muninn does not accept this record type.",
    "refused_text_length": "the claim must be 1 to 500 characters.",
    "refused_no_caller_session": (
        "quote-only writes need CLAUDE_CODE_SESSION_ID or CODEX_SESSION_ID in the environment."
    ),
    "refused_other": (
        "Muninn refused the write with a code this catalog does not list. Read `refused_<code>` and the Muninn docs."
    ),
    "decision_wrong_session": (
        "The loop belongs to a different session. Record the decision only from the session that owns the loop."
    ),
    "decision_wrong_loop": (
        "The loop changed after the caller read it. Read the current loop ID before you record the decision."
    ),
    "decision_wrong_revision": (
        "The graph changed after the caller read it. Read the current revision before you record the decision."
    ),
    "decision_blank_phase": "a decision needs a non-blank phase (for example 2.5).",
    "decision_blank_decision": "A decision must have text. The command did not write a record.",
    "decision_invalid_chain": (
        "The decision chain has damage. Examine and preserve the loop data before you sync again."
    ),
    "decision_sync_unknown": "Muninn can have received the decision. Examine the store before you retry by hand.",
    "decision_state_error": "The command could not read, check, or lock the loop data. It did not write a record.",
    "order_chain_broken": (
        "Someone edited `orders.json` by hand. The hash chain names the entry. Use a saved copy or examine the "
        "named entry. To seal the entry again, record it with `orders.py`."
    ),
    "order_blank_field": (
        "A standing instruction must have text for the problem and the lesson. The command did not write an entry."
    ),
    "order_lesson_too_long": (
        "The collapsed lesson has more than 500 characters. Write a shorter complete claim. Do not truncate it."
    ),
    "order_bad_id": "Use the format `[a-z0-9][a-z0-9_-]{0,119}` for the standing instruction ID.",
    "order_id_collision": "That ID names a different problem or scope. Use the ID for this entry or make a new one.",
    "order_not_found": "There is no entry with that ID in `orders.json`. Check the ID with `orders.py lessons`.",
    "order_state_error": (
        "The command could not read, lock, or write the standing instructions, prepared data, or receipt. Check "
        "the repo-key directory, `orders.lock`, and `teardown.jsonl.lock`."
    ),
    "order_loop_unknown": (
        "There is no source at `<repo-key dir>/<session>/progress.json`. Supply the `--session` that owns it and "
        "the logical `--loop`."
    ),
    "order_wrong_session": (
        "The source directory, session, or logical loop does not belong to this operation. Use the directory and "
        "IDs that own it."
    ),
    "order_source_invalid": (
        "The `progress.json` file, prepared data, or observations have a format error. Put the correct checked "
        "source files back."
    ),
    "order_source_mismatch": (
        "The prepared source or hash is out of date. Before the loop ends, run `prepare --refresh-from-sha256` "
        "with its current `evidence_sha256`."
    ),
    "order_loop_ineligible": (
        "The owned graph or work units did not finish or have stopped. Complete the required work."
    ),
    "order_not_complete": (
        "The prepared data is for future use. Apply recurrence or aging only after the owned `progress.json` "
        "records `complete`."
    ),
    "order_pending_teardown": (
        "The saved loop is complete, but the local update or its observation did not succeed. Retry `tick` with "
        "the same source binding."
    ),
    "order_retro_validator_unavailable": (
        "Schema 3 retros use the matching `retro_check` validator. Install it before graduation."
    ),
    "order_already_ticked": "The tick skipped this session and logical loop because the count includes them.",
    "no_user_cite": (
        "The local diagnostic has no checked citation from the current owner. A caller quote cannot prove the "
        "learning task."
    ),
    "legacy_uncited": "The legacy import has no saved selection for the current learning task. Keep it uncited.",
    "legacy_parse_error": (
        "The local legacy input has an entry with missing data, an ambiguous meaning, or a collision. Correct that "
        "entry and run `import-legacy` again. Keep the initial file."
    ),
    "legacy_missing": (
        "There is no hand-written `standing-orders.md` to import. The file may not be there, may have no text, or "
        "may come from a generator."
    ),
    "retro_not_assembled": (
        "`retro.json` has a schema version below 3 or has no `source_hashes`. Run `python3 scripts/lib/retro.py "
        "assemble <state-dir> --session <session_id>`."
    ),
    "retro_source_mismatch": (
        "A hashed source changed after assembly. The message names it. Run `retro.py assemble` again when the "
        "source files are complete."
    ),
    "retro_decisions_chain_broken": (
        "The `verify_chain` check rejected `decisions_absorbed`. The message gives the sequence number. Put the "
        "rows back. Record decisions only with `graph.py record-decision`. Then assemble again."
    ),
    "retro_steps_missing": (
        "Check `teardown.jsonl` for a missing step or an incorrect sequence. Run `proof.py run --all` or `proof.py "
        "disposition`. Then flush decisions. Next run `orders.py prepare`. Last, run `retro.py assemble`."
    ),
    "retro_state_error": "The command could not read `progress.json`. It did not assemble a retro.",
    "retro_wrong_session": "The loop belongs to a different session. Assemble only from the session that owns it.",
    "retro_free_invalid": "`--free-file` must contain one JSON object. The command did not assemble a retro.",
    "handoff_state_unreadable": (
        "`handoff_derive` could not read the loop's `progress.json`. Supply the path to that file."
    ),
    "graph_unavailable": (
        "`graph.py summarize` or `graph.py inspect` did not succeed for this graph. The done and next-step lists "
        "are empty. Run the command by hand and read stderr."
    ),
    "lesson_not_current": (
        "The saved learning task has no current Note that meets its rules. Examine its saved receipt. A caller "
        "quote cannot give it authority."
    ),
}
