"""Keep old timestamp-bound order observations readable after hash normalization."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from packages.tests.provider_fixture import Provider


class LegacyObservationTests(unittest.TestCase):
    """Read old completed receipts through both native completion verifiers."""

    def test_old_observation_binding(self) -> None:
        """An unchanged current timestamp can still prove an old receipt."""
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("claude", "codex"):
                with self.subTest(provider=name):
                    provider = Provider(Path(temporary), name)
                    provider.finish_wave()
                    provider.artifacts()
                    retro = provider.read("retro.json")
                    provider.write({**retro, "schema_version": 2}, "retro.json")
                    recorded = subprocess.run(
                        [
                            sys.executable,
                            str(provider.plugin / "scripts/lib/orders.py"),
                            "--dir",
                            str(provider.path.parent.parent),
                            "--session",
                            provider.session,
                            "record",
                            "--failure-mode",
                            "legacy-observation",
                            "--lesson",
                            "Keep the cited lesson.",
                            "--loop",
                            "fixture-loop",
                        ],
                        cwd=provider.home,
                        env=provider.environment,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(recorded.returncode, 0, recorded.stderr)
                    completed = provider.complete()
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

                    lifecycle = runpy.run_path(str(provider.plugin / "scripts/lib/orders_lifecycle.py"))
                    receipt_path = next(provider.path.parent.glob("orders-prepared-*.json"))
                    receipt = json.loads(receipt_path.read_text())
                    receipt["binding"]["progress_sha256"] = lifecycle["legacy_source_sha"](provider.read())
                    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                    digest = lifecycle["sha"](receipt)
                    observations = provider.path.parent / "teardown.jsonl"
                    rows = [json.loads(line) for line in observations.read_text().splitlines()]
                    for row in rows:
                        if row["step"] in {"orders_ticked", "orders_rendered"}:
                            row["binding"] = receipt["binding"]
                        if row["step"] == "orders_ticked":
                            row["evidence_sha256"] = digest
                    observations.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

                    arguments = ["--session", provider.session]
                    if name == "codex":
                        for artifact in ("evals", "proof", "retro"):
                            arguments.extend(["--" + artifact, str(provider.path.with_name(artifact + ".json"))])
                        arguments.extend(["--transcript", str(provider.parent)])
                    verified = provider.call("verify-completion", *arguments)
                    self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)


if __name__ == "__main__":
    unittest.main()
