"""The mirrored receipt modules, exercised through the Codex package only (child process, no Claude scripts/lib)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.receipt_test_support import (  # noqa: E402  # isort: skip
    REPOSITORY,
    make_owner,
    signed_receipt,
    store,
)

# Runs with ONLY the Codex package on sys.path, so every import resolves to packages/codex/scripts/lib.
PROBE = """
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import action_receipt as ar, receipt_signing as rs
assert "packages/codex" in ar.__file__, ar.__file__
case = json.loads(sys.argv[2])
rec, prop, signers = case["rec"], case["prop"], Path(case["signers"])
now = datetime.now(timezone.utc)
if case["mode"] == "verify":
    print(json.dumps(ar.verify(rec, prop, now, "s1", None, signers=signers)))
else:
    base = Path(case["base"])
    r, c = ar.find_valid("s1", prop, now, None, base, True, signers)
    print(r["receipt_id"] if r else "NONE:" + c)
"""


class CodexModuleTests(unittest.TestCase):
    """(b)-(e) through the Codex package modules only, in a child process whose path has no Claude scripts/lib."""

    tmp: tempfile.TemporaryDirectory[str]
    key: Path
    signers: Path
    agent_key: Path
    bind: dict[str, str]
    command: str

    @classmethod
    def setUpClass(cls) -> None:
        """Owner and agent keys."""
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        cls.key, cls.signers = make_owner(base / "owner")
        cls.agent_key, _ = make_owner(base / "agent")
        cls.bind = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": "a" * 40}
        cls.command = "git push origin feature:main"

    def receipt(self, key: Path | None = None, /, **over: object) -> dict[str, Any]:
        """A signed receipt for the command."""
        return signed_receipt(key or self.key, "git_push", self.command, "/repo", "feature", self.bind, **over)

    def proposed(self, **over: object) -> dict[str, Any]:
        """The action as the Codex hook would compute it, with overrides."""
        from scripts.lib import action_receipt as claude  # the hash function is identical in the mirror

        return {**claude.proposed_action("git_push", self.command, "/repo", "feature", self.bind), **over}

    def probe(self, **case: object) -> str:
        """Run PROBE against the Codex package only."""
        case.setdefault("signers", str(self.signers))
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run(
            [sys.executable, "-c", PROBE, str(CODEX), json.dumps(case)], capture_output=True, text=True, env=env,
            cwd=self.tmp.name, check=False,
        )  # fmt: skip
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def verify(self, rec: object, prop: dict[str, Any] | None = None) -> list[Any]:
        """Return the (ok, code) pair that the Codex copy of verify gives."""
        out: list[Any] = json.loads(self.probe(mode="verify", rec=rec, prop=prop or self.proposed()))
        return out

    def test_valid_and_self_minted(self) -> None:
        """(a)+(b) a signed receipt verifies; unsigned, agent-key and edited receipts do not."""
        self.assertEqual(self.verify(self.receipt()), [True, "ok"])
        self.assertEqual(self.verify({**self.receipt(), "signature": None}), [False, "signature_missing"])
        self.assertEqual(self.verify(self.receipt(self.agent_key)), [False, "signer_unknown"])
        self.assertEqual(self.verify({**self.receipt(), "ref": "refs/heads/release/x"}), [False, "signature_invalid"])

    def test_binding_and_malformed(self) -> None:
        """(c) stale sha, wrong repository/ref, missing artifact_sha."""
        for field, value, code in (
            ("artifact_sha", "b" * 40, "sha_mismatch"), ("repository", "github.com/evil/w", "repository_mismatch"),
            ("ref", "refs/heads/release/x", "ref_mismatch"),
        ):  # fmt: skip
            self.assertEqual(self.verify(self.receipt(**{field: value})), [False, code])
        self.assertEqual(self.verify(self.receipt(artifact_sha=None)), [False, "malformed"])

    def test_replay_and_concurrent_double_use(self) -> None:
        """(d)+(e) a second consume is refused; 16 Codex-module processes on one receipt give exactly one winner."""
        rec = self.receipt()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            store(base, rec)
            args = {"mode": "find", "rec": rec, "prop": self.proposed(), "base": tmp}
            self.assertEqual(self.probe(**args), rec["receipt_id"])
            self.assertEqual(self.probe(**args), "NONE:consumed")
            (base / "s1" / "receipts" / f"{rec['receipt_id']}.consumed").unlink()
            gate = f"import time, pathlib\nwhile not pathlib.Path({str(base / 'go')!r}).exists(): time.sleep(0.005)\n"
            argv = [sys.executable, "-c", gate + PROBE, str(CODEX), json.dumps({**args, "signers": str(self.signers)})]
            procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, cwd=tmp) for _ in range(16)]
            time.sleep(0.5)
            (base / "go").write_text("")
            outs = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(outs.count(rec["receipt_id"]), 1, outs)
        self.assertEqual(sum(o.startswith("NONE:") for o in outs), 15, outs)


if __name__ == "__main__":
    unittest.main()
