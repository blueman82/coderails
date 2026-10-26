"""Decide whether implementation workers run sandboxed (config `sandbox_workers`, default ON).

resolve() returns {mode, reason_code}:
  sandboxed  sandbox_workers is true or absent, the OS sandbox + npx + the pinned srt are present, and the owner has
             provisioned a worker credential.
  fallback   the sandbox (sandbox_unavailable) or credential (worker_credential_missing) is missing;
             graph implementation dispatch stops until the prerequisite is restored.
  off        sandbox_workers is false (sandbox_workers_off).
The worker credential is a file the OWNER creates, `~/.coderails/worker_credential`, mode 0600, one line
`ANTHROPIC_API_KEY=<key>` or `CLAUDE_CODE_OAUTH_TOKEN=<token from claude setup-token>`. It is the only secret a
sandboxed worker is given. A loopback probe showed headless claude with an isolated HOME + CLAUDE_CONFIG_DIR sends it
(x-api-key / Bearer); live-account acceptance is unverified. Until the owner provisions the file, mode stays fallback.
`python3 scripts/sandbox/containment.py [dir]` prints the decision as JSON and traces it (sandbox_launch/resolved);
the agentic-loop skill dispatches through spawn_sandboxed_worker.py only when the mode is sandboxed.
Cooperating-agent safeguard: an agent that edits the in-repo config can set sandbox_workers false.
"""

from __future__ import annotations

import json
import os
import platform
import posixpath
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.action_binding import binding
from scripts.lib.config import config_path, load_config

SRT_VERSION = "0.0.65"
ACK_KIND = "worker_fallback"
CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
# The seam for protected_paths.json: a manifest that can touch any of these needs an owner acknowledgement to run in
# process. Entries are repository-relative prefixes (or exact files).
HIGH_RISK_PREFIXES = (
    "hooks/",
    "scripts/",
    "capabilities/",
    "agents/",
    "skills/",
    "commands/",
    ".claude-plugin/",
    ".coderails/",
    ".github/",
    "packages/codex/",
    "packages/graph-semantics/",
    "workflow.config",
    "config.schema.json",
    "install.sh",
    "install.py",
    "pyproject.toml",
    "agents.md",
    "claude.md",
)


def ack_command(unit: str) -> str:
    """The text an acknowledgement receipt is bound to (one receipt per unit)."""
    return f"{ACK_KIND} {unit}"


def fallback_binding(cwd: str) -> dict[str, str] | None:
    """{repository, ref, sha} of the directory the in-process worker would build on (origin + branch + HEAD)."""
    return binding(ACK_KIND, ack_command(""), cwd)


def worker_credential(home: Path | None = None) -> tuple[str, str] | None:
    """(variable, value) from the owner's credential file, or None when absent, loose, malformed or not allowlisted."""
    path = (home or Path.home()) / ".coderails/worker_credential"
    try:
        if path.stat().st_mode & 0o077:
            return None  # readable by group/other: not provisioned by the owner
        name, _, value = path.read_text(encoding="utf-8").strip().partition("=")
    except OSError:
        return None
    return (name, value) if name in CREDENTIAL_VARS and value and "\n" not in value else None


def srt_cached(home: Path) -> bool:
    """True when the pinned sandbox-runtime is already in the npx cache (usable offline)."""
    for manifest in (home / ".npm/_npx").glob("*/node_modules/@anthropic-ai/sandbox-runtime/package.json"):
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("version") == SRT_VERSION:
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def runtime_present(home: Path, which: Callable[[str], str | None], system: str) -> bool:
    """OS sandbox (Seatbelt + ripgrep on macOS, bubblewrap on Linux), npx and the pinned srt are all reachable."""
    tools = ("sandbox-exec", "rg", "npx") if system == "Darwin" else ("bwrap", "npx") if system == "Linux" else ()
    return bool(tools) and all(which(tool) for tool in tools) and srt_cached(home)


def resolve(
    cwd: str,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    system: str | None = None,
) -> dict[str, str]:
    """The containment decision for a project directory."""
    path = config_path(cwd)
    values, findings = load_config(path)
    if findings or "sandbox_workers" not in values:
        reason = findings[0]["code"] if findings else "config_schema_unreadable"
        return {"mode": "fallback", "reason_code": reason}
    setting = values["sandbox_workers"]
    if setting is False:
        return {"mode": "off", "reason_code": "sandbox_workers_off"}
    home = home or Path.home()
    if not runtime_present(home, which, system or platform.system()):
        return {"mode": "fallback", "reason_code": "sandbox_unavailable"}
    if worker_credential(home) is None:
        return {"mode": "fallback", "reason_code": "worker_credential_missing"}
    return {"mode": "sandboxed", "reason_code": "sandboxed"}


def main(arguments: list[str] | None = None) -> int:
    """Print resolve() for a directory as JSON (the agentic-loop's dispatch decision) and trace it; always exit 0."""
    arguments = sys.argv[1:] if arguments is None else arguments
    result = resolve(arguments[0] if arguments else os.getcwd())
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
    if session:
        append_row("sandbox_launch", "resolved", result["reason_code"], session, None, {"mode": result["mode"]})
    print(json.dumps(result))
    return 0


def _literal_prefix(entry: str) -> str | None:
    """The glob-free, normalised, casefolded head of a manifest entry ('src/**' -> 'src'); None if it cannot be trusted.

    Absolute paths, '..' components, backslashes and non-ASCII text are untrustworthy (None = high risk).
    """
    text = entry.strip()
    if not text.isascii() or "\\" in text or text.startswith("/") or ".." in text.split("/"):
        return None
    cut = min((i for i in (text.find(c) for c in "*?[{") if i >= 0), default=len(text))
    head = posixpath.normpath(text[:cut]) if text[:cut] else ""
    return "" if head == "." else head.casefold()


def is_high_risk(manifest: list[str]) -> bool:
    """True when any entry can reach a protected tree; an empty manifest cannot prove low risk."""
    if not manifest:
        return True
    heads = [_literal_prefix(entry) for entry in manifest]
    return any(head is None or p.startswith(head) or head.startswith(p) for head in heads for p in HIGH_RISK_PREFIXES)


if __name__ == "__main__":
    raise SystemExit(main())
