"""Deterministic session context manifest and skill-route table, shared byte-for-byte by both providers.

Pure stdlib, Python 3.9 syntax, no entrypoint. SessionStart injects build_manifest(); UserPromptSubmit appends
route(). Hooks can only inject text: a route names skills, it cannot load them, and dropping the old "1% chance"
rule from the injected text is advisory-only (nothing enforces skill use).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

FAILSAFE = "skills: list via the Skill tool / native skill list"
CONSTRAINTS = (
    "constraints: orchestrate and delegate tool work; no merge without owner sign-off; "
    "no edits on main; label claims (verified)/(inferred)/(guess); "
    "if a skill applies you must invoke it before acting, process skills first; subagents skip"
)
FALLBACK = "coderails: active=yes\nauthority: unknown\nloop: unknown\n" + CONSTRAINTS + "\n" + FAILSAFE
NEGATION = re.compile(r"\b(not|no|never|without|dont|don't|skip)\s+(\w+\s+)?$")
MAX_ROUTE_SKILLS = 4
MAX_LISTED_NODES = 6

# (kind, trigger, bare skill names). slash: prompt starts with trigger; kw: trigger in the lowercased prompt;
# loop: an active loop for this session matches regardless of prompt.
ROUTES = (
    ("loop", "", ("agentic-loop",)),
    ("slash", "/workflow", ("workflow",)),
    ("slash", "/prep", ("prep",)),
    ("slash", "/push", ("push",)),
    ("slash", "/merge", ("merge",)),
    ("slash", "/handoff", ("handoff",)),
    ("kw", "merge", ("merge",)),
    ("kw", "git push", ("push",)),
    ("kw", "agentic loop", ("agentic-loop",)),
    ("kw", "spawn a team", ("agentic-loop",)),
    ("kw", "crack on", ("agentic-loop",)),
    ("kw", "premortem", ("premortem",)),
    ("kw", "hand off", ("handoff",)),
    ("kw", "ingest", ("wiki-ingest",)),
    ("kw", "wiki lint", ("wiki-lint",)),
    ("kw", "search the wiki", ("wiki-query",)),
    ("kw", "success evals", ("task-evals",)),
    ("kw", "is it merged", ("verify-merged-pr",)),
)


def loop_root(prefix: str = "coderails") -> Path:
    """Return the loop-state root. Claude: CLAUDE_ then CODERAILS_ (hook_common order). Codex: CODERAILS_ only."""
    override = os.environ.get("CODERAILS_AGENTIC_LOOP_DIR")
    if prefix == "coderails":
        override = os.environ.get("CLAUDE_AGENTIC_LOOP_DIR") or override
    return Path(override or Path.home() / ".coderails" / "agentic-loop")


def safe_id(session_id: str) -> bool:
    """True for a nonempty id that is path-local as written (never sanitised, so ids cannot collide)."""
    return (
        bool(session_id)
        and session_id not in {"?", "."}
        and "/" not in session_id
        and ".." not in session_id
        and "\0" not in session_id
    )


def find_state(root: Path, session_id: str, cwd: str = "") -> Path | None:
    """Return progress.json for this exact session id: the cwd's canonical slug dir first, else any slug dir."""
    if cwd:
        try:
            common = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            common = ""
        canonical = root / (common if common.startswith("/") else cwd).replace("/", "-") / session_id / "progress.json"
        if canonical.is_file():
            return canonical
    # ponytail: first slug dir holding this exact session id; same-session loops under two slugs are not told apart.
    return next((p for p in sorted(root.glob("*/*/progress.json")) if p.parent.name == session_id), None)


def parse_object(raw: str) -> dict[str, Any] | None:
    """Return the JSON object in raw ({} for empty input), or None when it is malformed or not an object."""
    try:
        value: Any = json.loads(raw) if raw else {}
    except ValueError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def route_for_payload(raw: str, prefix: str) -> tuple[str, str, str]:
    """Return (route text or '', reason code, session id) for a UserPromptSubmit payload. Never raises."""
    data = parse_object(raw)
    if data is None:
        return "", "route_payload_malformed", ""
    prompt, sid, cwd = data.get("prompt"), data.get("session_id"), data.get("cwd")
    sid = sid if isinstance(sid, str) else ""
    try:
        active = safe_id(sid) and find_state(loop_root(prefix), sid, cwd if isinstance(cwd, str) else "") is not None
    except OSError:
        active = False
    text = route(prompt if isinstance(prompt, str) else "", active, prefix)
    return text, "route_match" if text else "route_none", sid


def session_manifest(raw: str, plugin_root: Path, prefix: str) -> str:
    """Build the SessionStart manifest from a raw hook payload and trace its reason code. Never raises."""
    data = parse_object(raw)
    fields = data or {}
    sid, cwd, source = (
        str(fields[k]) if isinstance(fields.get(k), str) else "" for k in ("session_id", "cwd", "source")
    )
    text, reason = manifest_with_reason(cwd, sid, source, plugin_root, prefix)
    if data is None:
        text, reason = FALLBACK, "manifest_payload_malformed"
    trace("context_manifest", "ok" if reason == "manifest_ok" else "fail_open", reason, sid, prefix)
    return text


def phrase_hit(text: str, trigger: str, slash: bool) -> bool:
    """True when trigger occurs as a whole word (slash: at a token start) and is not negated just before it."""
    lead = r"(?<![\w/])" if slash else r"\b"
    for match in re.finditer(lead + re.escape(trigger) + r"\b", text):
        if not NEGATION.search(text[max(0, match.start() - 20) : match.start()]):
            return True
    return False


def route(prompt: str, loop_active: bool, prefix: str) -> str:
    """Return 'route: p:a, p:b' for matching triggers, or '' when nothing matches."""
    text = prompt.lower()
    names: list[str] = []
    for kind, trigger, skills in ROUTES:
        hit = loop_active if kind == "loop" else phrase_hit(text, trigger, kind == "slash")
        names += [f"{prefix}:{s}" for s in skills if hit and f"{prefix}:{s}" not in names]
    return f"route: {', '.join(names[:MAX_ROUTE_SKILLS])}" if names else ""


def authority_line(root: Path, session_id: str) -> str:
    """Summarise this exact session's unexpired authority.json; anything else (foreign, expired, torn) is none."""
    try:
        data = json.loads((root / session_id / "authority.json").read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
        if data["session_id"] != session_id or expires <= datetime.now(timezone.utc):
            return "authority: none"
        return (
            f"authority: active id={data['authority_id']} scope={','.join(data['scope'])} expires={data['expires_at']}"
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "authority: none"


def inspect_graph(plugin_root: Path, state: Path) -> dict[str, Any] | None:
    """Run the provider graph CLI's read-only inspect, or None when it fails."""
    graph = plugin_root / "skills" / "agentic-loop" / "scripts" / "graph.py"
    try:
        result = subprocess.run(
            [sys.executable, str(graph), "inspect", str(state)], capture_output=True, check=False, text=True, timeout=5
        )
        return parse_object(result.stdout) if result.returncode == 0 and result.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


def loop_lines(root: Path, session_id: str, plugin_root: Path, cwd: str = "") -> tuple[list[str], str, bool]:
    """Return (lines, reason, active) for this session's loop. Raises ValueError/OSError on unreadable state."""
    state = find_state(root, session_id, cwd)
    if state is None:
        return ["loop: none"], "manifest_ok", False
    raw = parse_object(state.read_text(encoding="utf-8"))
    if raw is None:
        raise ValueError("progress.json is not an object")
    if raw.get("session_id") != session_id:
        return ["loop: none"], "manifest_ok", False
    nodes: dict[str, Any] = raw.get("graph", {}).get("nodes", {})
    digest: dict[str, str] = {}
    for key, node in nodes.items():
        evidence: Any = cast(dict[str, Any], node).get("evidence") if isinstance(node, dict) else None
        if evidence:
            blob = json.dumps(evidence, sort_keys=True).encode()
            digest[key] = f"{len(evidence)}:{hashlib.sha256(blob).hexdigest()[:8]}"
    inspected = inspect_graph(plugin_root, state)
    ready: list[Any] = (inspected or {}).get("ready", [])
    hard_stop: dict[str, Any] = (inspected or {}).get("hard_stop") or {}
    stop_node = hard_stop.get("node", "-")
    listed = ",".join(map(str, ready[:MAX_LISTED_NODES])) + (
        f"+{len(ready) - MAX_LISTED_NODES}" if len(ready) > MAX_LISTED_NODES else ""
    )
    head = (
        f"loop: id={raw.get('loop_id')} owner={raw.get('session_id')} state={state} "
        f"revision={raw.get('revision')} ready={listed or '-'} hard_stop={stop_node}"
    )
    lines = [head if inspected else head + " graph=invalid"]
    if digest:
        lines.append("evidence: " + " ".join(f"{k}={v}" for k, v in sorted(digest.items())[:MAX_LISTED_NODES]))
    return lines, "manifest_ok" if inspected else "manifest_graph_invalid", True


def manifest_with_reason(
    cwd: str, session_id: str, source: str, plugin_root: Path, prefix: str = "coderails"
) -> tuple[str, str]:
    """Return (manifest text, reason code). Never raises: any failure yields the static fallback manifest."""
    try:
        root = loop_root(prefix)
        head = f"coderails: active=yes source={source or 'unknown'}"
        if not safe_id(session_id):
            body, reason = [head, "authority: none", "loop: none"], "manifest_no_session"
        else:
            try:
                loop, reason, active = loop_lines(root, session_id, plugin_root, cwd)
            except (OSError, ValueError, AttributeError, TypeError):
                return FALLBACK, "manifest_state_unreadable"
            body = [head, authority_line(root, session_id)] + loop
            hint = route("", active, prefix)
            body += [hint] if hint else []
        return "\n".join(body + [CONSTRAINTS, FAILSAFE]), reason
    except Exception:  # fail open on anything unforeseen
        return FALLBACK, "manifest_error"


def build_manifest(
    cwd: str, session_id: str, source: str, plugin_root: Path | None = None, prefix: str = "coderails"
) -> str:
    """Return the compact line-oriented manifest text."""
    return manifest_with_reason(cwd, session_id, source, plugin_root or Path(__file__).resolve().parents[3], prefix)[0]


def trace(command: str, outcome: str, reason: str, session_id: str, prefix: str = "coderails") -> bool:
    """Append a non-authoritative trace row via the sibling trace_row.py; False on any problem (never raises).

    A missing or unsafe session id is bucketed under `_unattributed` so fail-open events are still counted.
    """
    session_id = session_id if safe_id(session_id) else "_unattributed"
    try:
        spec = importlib.util.spec_from_file_location("trace_row", Path(__file__).with_name("trace_row.py"))
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return bool(module.append_row(command, outcome, reason, session_id, base=loop_root(prefix)))
    except Exception:
        return False
