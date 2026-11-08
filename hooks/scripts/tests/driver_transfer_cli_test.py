"""The real public driver stages immutable synthetic source for root publication."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hooks.scripts.tests import driver_workspace_test as fixture
from scripts.sandbox import source_capture as capture


class TransferCLITests(unittest.TestCase):
    """Inert provider and synthetic publication response; no model, SRT or GitHub acceptance claim."""

    def test_public_drive_transfers_before_root_publication_and_resumes_fixed_receipt(self) -> None:
        """Public drive transfers before root publication and resumes fixed receipt."""
        context = fixture.WorkspaceTests("test_preparation_is_owned_idempotent_and_leaves_destination_clean")
        self.addCleanup(context.doCleanups)
        context.setUp()
        tools = context.base / "bin"
        tools.mkdir()
        pin = context.home / ".npm/_npx/fixture/node_modules/@anthropic-ai/sandbox-runtime/package.json"
        pin.parent.mkdir(parents=True)
        pin.write_text(json.dumps({"version": "0.0.65"}))
        report = {
            "outcome": "done",
            "evidence": "inert source proposal",
            "final_report": {
                "claims": [{"text": "wrote proposed source", "label": "verified", "source": "allowed.txt"}],
                "did_not_verify": [],
            },
        }
        npx = tools / "npx"
        npx.write_text(
            f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
            "data=sys.stdin.buffer.read()\n"
            "assert ('Checkout: '+os.getcwd()+'\\n').encode() in data\n"
            "Path('allowed.txt').write_bytes(b'worker proposal\\n')\n"
            "print(json.dumps({'type':'system','subtype':'init','session_id':'synthetic'}))\n"
            f"print(json.dumps({{'type':'result','subtype':'success','is_error':False,'structured_output':{report!r}}}))\n"
        )
        npx.chmod(0o755)
        for name in ("sandbox-exec", "bwrap", "rg"):
            tool = tools / name
            tool.write_text("#!/bin/sh\nexit 0\n")
            tool.chmod(0o755)
        gh = tools / "gh"
        gh.write_text(
            f"#!{sys.executable}\nimport json,subprocess\n"
            "head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()\n"
            "print(json.dumps({'number':42,'state':'OPEN','headRefOid':head}))\n"
        )
        gh.chmod(0o755)
        with patch.dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}"):
            first = context.case.graph("drive", "--checkout", str(context.destination), "--wait-seconds", "10")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)["reason"], "publication_required")
            self.assertEqual((context.destination / "allowed.txt").read_bytes(), b"worker proposal\n")
            attempt = context.case.path.parent / "driver-evidence" / context.identifier
            receipt = (attempt / "transfer.json").read_bytes()
            mapping = json.loads((attempt / "workspace.json").read_bytes())
            Path(mapping["execution"], "allowed.txt").write_text("late worker change")
            (context.destination / "allowed.txt").write_text("root reviewed edit\n")
            paused = context.case.graph("drive", "--checkout", str(context.destination), "--wait-seconds", "1")
            self.assertEqual(json.loads(paused.stdout)["reason"], "publication_required")
            self.assertEqual((attempt / "transfer.json").read_bytes(), receipt)
            self.assertEqual((context.destination / "allowed.txt").read_text(), "root reviewed edit\n")
            capture.git("-C", str(context.destination), "add", "allowed.txt")
            capture.git(
                "-C",
                str(context.destination),
                "-c",
                "user.name=Root",
                "-c",
                "user.email=root@example.invalid",
                "commit",
                "-qm",
                "root publication fixture",
            )
            final = context.case.graph("drive", "--checkout", str(context.destination), "--wait-seconds", "1")
            self.assertEqual(final.returncode, 0, final.stderr)
            self.assertEqual(json.loads(final.stdout)["status"], "recorded")
            manifest = json.loads((attempt / "manifest.json").read_bytes())
            self.assertIn("transfer_sha256", manifest)
            self.assertEqual(manifest["checkout"], str(context.destination))
            self.assertEqual(json.loads((attempt / "terminal.json").read_bytes())["head_at_exit"], mapping["head"])
            before = context.case.path.read_bytes()
            captured = json.loads((attempt / "capture.json").read_bytes())
            captured["tree"] = "0" * 40
            (attempt / "capture.json").write_text(json.dumps(captured))
            refused = context.case.graph("drive", "--checkout", str(context.destination), "--wait-seconds", "1")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("capture changed", refused.stderr)
            self.assertEqual(context.case.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
