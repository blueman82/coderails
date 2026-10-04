#!/usr/bin/env python3
"""Opt-in main-branch ruleset: `plan` diffs read-only, `apply --yes` writes. Never runs by default.

Prints `REASON=<CODE>` last. Codes: DRY_RUN, NO_YES, CHECK_NEVER_SEEN, TEMPLATE_MISSING, NO_DIFF, APPLIED, GH_FAIL.
Exit: 0 for DRY_RUN/NO_DIFF/APPLIED, 2 for GH_FAIL, 1 for a refusal.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.enforcement_trace import emit
from scripts.lib.git_common import repo

ENFORCEMENT_DIR = "docs/external-enforcement"
EXIT = {"DRY_RUN": 0, "NO_DIFF": 0, "APPLIED": 0, "GH_FAIL": 2}


class GhError(RuntimeError):
    """A gh invocation failed; carries its stderr."""


def gh(*args: str, stdin: str | None = None) -> str:
    """Run gh and return stdout, raising GhError on a non-zero exit or a missing binary."""
    try:
        result = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
    except OSError as error:
        raise GhError(str(error)) from error
    if result.returncode:
        raise GhError(result.stderr.strip() or f"gh {args[0]} exited {result.returncode}")
    return result.stdout


def sort_key(item: object) -> str:
    """Order rules by type and anything else by its text, so list comparison ignores server ordering."""
    return str(cast(dict[str, object], item).get("type", "")) if isinstance(item, dict) else str(item)


def covers(live: object, want: object) -> bool:
    """True when live contains everything in want; extra server-side keys in live are ignored."""
    if isinstance(want, dict):
        wanted = cast(dict[str, object], want)
        actual = cast(dict[str, object], live)
        return isinstance(live, dict) and all(k in actual and covers(actual[k], v) for k, v in wanted.items())
    if isinstance(want, list):
        wants, lives = cast(list[object], want), cast(list[object], live)
        if not isinstance(live, list) or len(lives) != len(wants):
            return False
        return all(covers(a, b) for a, b in zip(sorted(lives, key=sort_key), sorted(wants, key=sort_key)))
    return bool(live == want)


def live_ruleset(slug: str, name: str) -> dict[str, Any] | None:
    """Return the live ruleset with this name (full detail), or None when absent."""
    for entry in json.loads(gh("api", f"repos/{slug}/rulesets") or "[]"):
        if entry.get("name") == name:
            return dict(json.loads(gh("api", f"repos/{slug}/rulesets/{entry['id']}")))
    return None


def check_seen(slug: str, context: str) -> bool:
    """True when the required check name appears on any of the 10 most recent commits."""
    for sha in gh("api", f"repos/{slug}/commits?per_page=10", "--jq", ".[].sha").split():
        runs = gh("api", f"repos/{slug}/commits/{sha}/check-runs", "--jq", ".check_runs[].name").split()
        statuses = gh("api", f"repos/{slug}/commits/{sha}/statuses", "--jq", ".[].context").split()
        if context in runs + statuses:
            return True
    return False


def execute(command: str, root: Path, yes: bool) -> str:
    """Return the reason code for plan/apply; prints the diff or refusal detail along the way."""
    if command == "apply" and not yes:
        print("refusing: apply needs --yes")
        return "NO_YES"
    template = root / ENFORCEMENT_DIR / "verify.yml.template"
    if command == "apply" and not template.is_file():
        print(f"refusing: {template} is absent, nothing could ever post the required check")
        return "TEMPLATE_MISSING"
    want = json.loads((root / ENFORCEMENT_DIR / "ruleset.json").read_text())
    slug = repo()
    try:
        if command == "apply":
            context = next(
                c["context"]
                for r in want["rules"]
                if r["type"] == "required_status_checks"
                for c in r["parameters"]["required_status_checks"]
            )
            if not check_seen(slug, context):
                print(f"refusing: check {context!r} never observed on a recent commit; applying would lock merges")
                return "CHECK_NEVER_SEEN"
        live = live_ruleset(slug, want["name"])
        if live is not None and covers(live, want):
            return "NO_DIFF"
        action = "CREATE" if live is None else f"UPDATE id={live['id']}"
        if command == "plan":
            print(f"would {action}:\n{json.dumps(want, indent=2, sort_keys=True)}")
            return "DRY_RUN"
        verb, path = ("POST", "rulesets") if live is None else ("PUT", f"rulesets/{live['id']}")
        gh("api", "-X", verb, f"repos/{slug}/{path}", "--input", "-", stdin=json.dumps(want))
        return "APPLIED"
    except (GhError, ValueError, KeyError, StopIteration) as error:
        print(f"gh failure: {error}", file=sys.stderr)
        return "GH_FAIL"


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run plan/apply, record an advisory trace row and print the reason code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--yes", action="store_true", help="required for apply to write")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="repository root")
    args = parser.parse_args(argv)
    reason = execute(args.command, Path(args.root), args.yes)
    emit(f"external_enforcement.{args.command}", reason)
    print(f"REASON={reason}")
    return EXIT.get(reason, 1)


if __name__ == "__main__":
    raise SystemExit(main())
