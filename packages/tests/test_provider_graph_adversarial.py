"""Exercise adversarial graph contracts through each provider's native executable."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider


class ProviderAdversarialTests(unittest.TestCase):
    """Keep common refusal semantics independent of provider evidence representation."""

    def setUp(self) -> None:
        """Create separate native stores for both providers."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def test_shape_identity_retry_domain_and_registry(self) -> None:
        """Reject malformed current states atomically and accept registered decimal IDs."""
        for provider in self.providers:
            baseline = provider.state()
            variants: list[dict[str, Any]] = []
            for key in ("session_id", "loop_id", "revision"):
                value = copy.deepcopy(baseline)
                del value[key]
                variants.append(value)
            changes: tuple[tuple[str, object], ...] = (
                ("status", "bogus"),
                ("evidence", {}),
                ("status", "running"),
                ("outcome", "done"),
            )
            for field, replacement in changes:
                value = copy.deepcopy(baseline)
                value["graph"]["nodes"]["U3[1]"][field] = replacement
                variants.append(value)
            for maximum in (0, 6, True):
                value = copy.deepcopy(baseline)
                value["graph"]["nodes"]["U3[1]"]["retry"]["max"] = maximum
                variants.append(value)
            value = provider.state(("U3[1]", "U3[2]", "U3[3]"))
            value["graph"]["edges"] = [{"from": "U3[1]", "to": "U3[2]"}, {"from": "U3[2]", "to": "U3[1]"}]
            variants.append(value)
            for value in variants:
                provider.write(value)
                before = provider.path.read_bytes()
                self.assertNotEqual(provider.call("begin-wave").returncode, 0, value)
                self.assertEqual(provider.path.read_bytes(), before)
            for maximum in (1, 5):
                value = copy.deepcopy(baseline)
                value["graph"]["nodes"]["U3[1]"]["retry"]["max"] = maximum
                provider.write(value)
                provider.success("begin-wave")
            provider.write(provider.state(("S2.7d[1]", "S2.7d[10]")))
            self.assertEqual(provider.success("begin-wave")["nodes"], sorted(["S2.7d[1]", "S2.7d[10]"]))
            value = provider.state()
            value["graph"]["nodes"]["U3[1]"]["label"] = "forged label"
            provider.write(value)
            self.assertNotEqual(provider.call("inspect").returncode, 0)

    def test_wave_ownership_and_result_envelopes(self) -> None:
        """Bind both active-wave fields and every report to exactly the current wave."""
        for provider in self.providers:
            report = {"wave_id": "wave-2", "results": {"U3[1]": {"outcome": "done", "evidence": "done"}}}
            self.assertNotEqual(provider.call("record-wave", json.dumps(report)).returncode, 0)
            provider.success("begin-wave")
            original = provider.read()
            for key, value in (("revision", 0), ("wave_id", "wave-999")):
                state = copy.deepcopy(original)
                state["graph"]["active_wave"][key] = value
                provider.write(state)
                self.assertNotEqual(provider.call("inspect").returncode, 0)
            provider.write(original)
            report = provider.launch()
            for payload in (report["results"], {**report, "wave_id": "wave-1"}, {**report, "wave_id": "wrong"}):
                before = provider.path.read_bytes()
                self.assertNotEqual(provider.call("record-wave", json.dumps(payload)).returncode, 0)
                self.assertEqual(provider.path.read_bytes(), before)
            provider.success("record-wave", json.dumps(report))

    def test_completion_artifact_tampering_and_missing_observation(self) -> None:
        """Typed proof claims and forged grades cannot substitute for observed evidence."""
        for provider in self.providers:
            provider.finish_wave()
            provider.artifacts()
            baseline = provider.read()
            self.assertEqual(provider.complete().returncode, 0)
            provider.write(baseline)
            for filename, key, value in (
                ("evals.json", "grading", {"by": "forged", "checksum": "forged"}),
                ("evals.json", "result", "NO-GO"),
                ("evals.json", "revision", 0),
                ("proof.json", "loop_id", "previous-loop"),
            ):
                document = provider.read(filename)
                provider.write({**document, key: value}, filename)
                before = provider.path.read_bytes()
                self.assertNotEqual(provider.complete().returncode, 0)
                self.assertEqual(provider.path.read_bytes(), before)
                provider.write(document, filename)
            proof = provider.read("proof.json")
            altered = copy.deepcopy(proof)
            altered["proofs"][0]["evidence"] = "   "
            provider.write(altered, "proof.json")
            self.assertEqual(provider.complete().returncode == 0, provider.name == "claude")
            provider.write(baseline)
            provider.write(proof, "proof.json")
            records = provider.parent.read_text().splitlines()
            provider.parent.write_text("\n".join(line for line in records if "proof-1" not in line) + "\n")
            self.assertNotEqual(provider.complete().returncode, 0)

    def test_clean_cache_codex_lifecycle(self) -> None:
        """A copied independent Codex package owns dispatch, grading and completion."""
        provider = self.providers[1]
        destination = provider.home / "cache/coderails-codex"
        shutil.copytree(provider.plugin, destination)
        provider.plugin = destination
        provider.environment["PLUGIN_ROOT"] = str(destination)
        provider.success("begin-wave")
        request = provider.request()
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.stdout, "", result.stderr)
        provider.success("record-wave", json.dumps(provider.launch()))
        provider.artifacts()
        result = provider.complete()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
