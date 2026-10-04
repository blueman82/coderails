#!/usr/bin/env python3
"""Print {ok, violations[]} for the diff against a manifest and policy file; exit 1 when not ok.

Needs no hooks, so headless `claude -p` routines can run it. The manifest comes from --progress/--unit
(work_units[unit].manifest) or from a "manifest" key in the policy file. Unreadable inputs fail open (exit 0,
reason_code manifest_unreadable); a progress file owned by another --session is refused (exit 2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import git_common as git
from scripts.lib import manifest_policy as mp


def main(arguments: list[str] | None = None) -> int:
    """Evaluate the current branch diff and print the JSON verdict."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--progress")
    parser.add_argument("--unit")
    parser.add_argument("--session")
    args = parser.parse_args(arguments)
    label = f"{git.output('git', 'rev-parse', '--show-toplevel').rsplit('/', 1)[-1]}@{git.branch() or 'detached'}"

    def finish(payload: dict[str, Any], code: int) -> int:
        print(json.dumps(payload, sort_keys=True))
        return code

    policy = mp.load_json(args.policy)
    if policy is None:
        mp.trace(label, "failed_open", "manifest_unreadable")
        return finish({"ok": True, "violations": [], "reason_code": "manifest_unreadable"}, 0)
    manifest = mp.strings(policy["manifest"]) if "manifest" in policy else None
    if args.progress:
        state = mp.load_json(args.progress)
        units = (state or {}).get("work_units")
        if state is None or not isinstance(units, dict):
            mp.trace(label, "failed_open", "manifest_unreadable")
            return finish({"ok": True, "violations": [], "reason_code": "manifest_unreadable"}, 0)
        if args.session and state.get("session_id") != args.session:
            mp.trace(label, "refused", "foreign_session")
            return finish({"ok": False, "violations": [], "reason_code": "foreign_session"}, 2)
        entry = cast(dict[str, Any], units).get(args.unit or "")
        unit_manifest = mp.strings(cast(dict[str, Any], entry).get("manifest")) if isinstance(entry, dict) else []
        manifest = unit_manifest or manifest
        if manifest is None:
            mp.trace(label, "legacy", "manifest_legacy_absent")
    base = args.base or f"origin/{git.main()}"
    diff = git.run("git", "diff", "--raw", "-z", "-M", f"{base}...{args.head}")
    if diff.returncode:
        mp.trace(label, "failed_open", "manifest_unreadable")
        return finish({"ok": True, "violations": [], "reason_code": "manifest_unreadable"}, 0)
    linked = mp.linked_worktree() if policy.get("require_linked_worktree") else None
    result = mp.check(mp.parse_raw_z(diff.stdout), policy, manifest, linked)
    if result["ok"]:
        mp.trace(label, "ok", "diff_manifest_ok")
    for violation in result["violations"]:
        mp.trace(label, "refused", violation["code"])
    return finish(result, 0 if result["ok"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
