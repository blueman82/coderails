#!/usr/bin/env python3
"""Independent-runner verification of a PR head: repo suites plus the existing SHA-bound merge-gate checks.

Reuses git_common's artifact gates and post_evals.smoke_verify unchanged. Prints `REASON=<CODE>` last and exits
non-zero on any failure. Codes: OK, SUITE_FAIL, REVIEW_ABSENT, EVAL_ABSENT_OR_NOGO, FETCH_FAIL, SHA_MISMATCH,
SMOKE_FAIL. Integrity attestation is skipped by design (no machine_user is configured without the daemon).
The runner must pin _PR_TRUSTED_LOGIN and _PR_TRUSTED_PERMISSION: a GITHUB_TOKEN usually fails `gh api user`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.enforcement_trace import emit
from scripts.lib.git_common import gate_eval_summary_for_pr, gate_review_summary_for_pr, output, pr_field
from scripts.post_evals import smoke_verify

ROOT = Path(__file__).resolve().parents[1]

# The pre-commit pair. The quality checker is the trusted copy (ROOT) aimed at the PR head ({head}) as data.
# ponytail: run_all.py must be the head's own (it runs the suites beside itself), so a PR can still alter its
# tests; only a second identity reviewing test changes closes that (see README trust analysis).
SUITES = [
    [sys.executable, str(ROOT / "scripts/quality/check.py"), "--strict", "--root", "{head}"],
    [sys.executable, "{head}/hooks/scripts/tests/run_all.py"],
]


def verify(pr: str, sha: str, head_dir: Path = ROOT) -> str:
    """Return OK or the first failing reason code. head_dir is the checkout of the PR head (data under test)."""
    os.chdir(head_dir)  # gh and git resolve the repository from cwd; the runner's workspace root is not a repo
    head = pr_field(pr, "headRefOid")
    if not head or not sha or head != sha or output("git", "-C", str(head_dir), "rev-parse", "HEAD") != sha:
        return "SHA_MISMATCH"
    commands = [[part.replace("{head}", str(head_dir)) for part in command] for command in SUITES]
    if any(subprocess.run(command, cwd=head_dir, check=False).returncode for command in commands):
        return "SUITE_FAIL"
    status, _ = gate_review_summary_for_pr(pr, sha)
    if status:
        return "FETCH_FAIL" if status == 2 else "REVIEW_ABSENT"
    summary = gate_eval_summary_for_pr(pr, sha)
    if summary.status:
        return "FETCH_FAIL" if summary.status == 2 else "EVAL_ABSENT_OR_NOGO"
    if not summary.embed:
        return "EVAL_ABSENT_OR_NOGO"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "evals.json"
        path.write_text(summary.embed)
        return "SMOKE_FAIL" if smoke_verify(path, sha) else "OK"


def main(argv: list[str] | None = None) -> int:
    """Run verification for one PR head, record an advisory trace row, print the reason code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--head-dir", type=Path, default=ROOT, help="checkout of the PR head (default: this repo)")
    args = parser.parse_args(argv)
    reason = verify(args.pr, args.sha, args.head_dir.resolve())
    emit("ci_verify.run", reason)
    print(f"REASON={reason}")
    return 0 if reason == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
