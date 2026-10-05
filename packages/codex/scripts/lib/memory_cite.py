"""User-anchored cite forms for typed memory writes. An agent cannot cite its own conclusions.

Two forms, both anchored in a user prompt:
- quote_only: a substantive quote (12-300 chars after whitespace collapse) of a user prompt. With no ref, muninn finds
  the caller session's own prompt; a ref is optional. Shorter than 12 with no ref is `cite_too_short`.
- approved_reply: the reply that proposed the claim plus the user's (possibly one-word) approval prompt.
A cite set whose anchor is not a user prompt is `cite_not_user`, decided BEFORE muninn is spawned. Roles are declared by
the caller; the CLI resolves them from `muninn session <root>` payloads with `role_of` / `approved_reply`.
This is a cooperating-agent safeguard: muninn re-verifies verbatim quotes, it does not stop a lying caller.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, cast

QUOTE_MIN, QUOTE_MAX, APPROVAL_MAX = 12, 300, 80
REF = re.compile(r"(claude|codex):(.+):(\d+)\.(\d+)")


class Cited(Protocol):
    """The Record fields this module reads."""

    cite: str
    quote: str
    cite_role: str
    cite_kind: str
    reply_cite: str
    reply_quote: str


def collapse(text: str) -> str:
    """Collapse whitespace runs, as muninn does before comparing quotes."""
    return " ".join(text.split())


def check(r: Cited) -> str | None:
    """Return a reason code when the cite set may not be sent to muninn, else None."""
    if (r.cite_role, r.cite_kind) != ("user", "prompt"):
        return "cite_not_user"
    if r.reply_cite and (not r.cite or not r.reply_quote.strip()):
        return "cite_unresolved"  # an approval needs both halves
    if not r.cite and not r.reply_cite and len(collapse(r.quote)) < QUOTE_MIN:
        return "cite_too_short"
    return None


def argv(r: Cited) -> list[str]:
    """The `know add` cite flags for the record's form."""
    if r.reply_cite:
        return ["--cite", r.reply_cite, "--quote", r.reply_quote, "--cite", r.cite, "--quote", r.quote]
    return ["--cite", r.cite, "--quote", r.quote] if r.cite else ["--quote", r.quote]


def session_of(ref: str) -> str:
    """The session id inside a `claude:<session>:<line>.<part>` ref, or empty."""
    m = REF.fullmatch(ref)
    return m[2] if m else ""


def _key(ref: str) -> tuple[int, int]:
    m = REF.fullmatch(ref)
    return (int(m[3]), int(m[4])) if m else (0, 0)


def _text(event: dict[str, Any]) -> str:
    """Event text (`text` in the fake, `preview` in muninn), whitespace-collapsed, minus a truncation mark."""
    return collapse(str(event.get("text") or event.get("preview") or "")).removesuffix("...").removesuffix("…")


def _events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw: object = payload.get("events")
    if not isinstance(raw, list):
        return []
    return [cast("dict[str, Any]", e) for e in cast("list[object]", raw) if isinstance(e, dict)]


def role_of(payload: dict[str, Any], ref: str) -> tuple[str, str]:
    """(role, kind) of `ref` in a `muninn session` payload; ('', '') when it is not there."""
    for e in _events(payload):
        if e.get("ref") == ref:
            return str(e.get("role", "")), str(e.get("kind", ""))
    return "", ""


def approved_reply(payload: dict[str, Any], approval_ref: str) -> tuple[str, str, str] | str:
    """Resolve an approval prompt to (reply_ref, reply_quote, approval_quote), or a reason code.

    The approval must be a short user prompt, and the reply must be the event right before it (no user prompt between).
    """
    if role_of(payload, approval_ref) != ("user", "prompt"):
        return "cite_not_user" if role_of(payload, approval_ref) != ("", "") else "cite_unresolved"
    here = _key(approval_ref)
    replies = [e for e in _events(payload) if e.get("kind") == "reply" and _key(str(e.get("ref"))) < here]
    if not replies:
        return "cite_unresolved"
    reply = max(replies, key=lambda e: _key(str(e["ref"])))
    approval = next(e for e in _events(payload) if e.get("ref") == approval_ref)
    between = [e for e in _events(payload) if _key(str(reply["ref"])) < _key(str(e.get("ref"))) < here]
    user_between = any(role_of(payload, str(e.get("ref"))) == ("user", "prompt") for e in between)
    if user_between or len(_text(approval)) > APPROVAL_MAX:
        return "cite_bad_approval"  # not adjacent to the reply it answers, or too long to be an approval
    return str(reply["ref"]), _text(reply)[:QUOTE_MAX], _text(approval)[:QUOTE_MAX]


def prompt_has(payload: dict[str, Any], quote: str) -> bool:
    """True when `quote` sits inside a user prompt of the session payload (the caller's own session)."""
    want = collapse(quote)
    return bool(want) and any(
        (e.get("role"), e.get("kind")) == ("user", "prompt") and want in _text(e) for e in _events(payload)
    )


def resolve(r: Any, payload: dict[str, Any], approval: bool, session_id: str) -> str | None:  # noqa: ANN401
    """Set the record's cite role/kind (and an approval's reply) from the caller's session; a reason code on refusal."""
    if r.cite and session_of(r.cite) != session_id:
        return "cite_not_own_session"  # only the caller's own session may anchor a write
    if not r.cite:
        r.cite_role, r.cite_kind = ("user", "prompt") if prompt_has(payload, r.quote) else ("", "")
        return None
    r.cite_role, r.cite_kind = role_of(payload, r.cite)
    if approval and (r.cite_role, r.cite_kind) == ("user", "prompt"):
        got = approved_reply(payload, r.cite)
        if isinstance(got, str):
            return got
        r.reply_cite, r.reply_quote, r.quote = got
    return None
