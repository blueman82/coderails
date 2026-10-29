"""Probe driver stdin with inert launcher shims; no real sandbox or provider runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = "authorized café Ω\nsecond line\r\n".encode() + b"\x00binary\xff\n\ntail\n"


class DriverStdinTests(unittest.TestCase):
    """Only the captured stdin may supply driver prompt contents."""

    def test_source_replacement_or_removal_cannot_replace_captured_bytes(self) -> None:
        """Raw bytes, Unicode and terminal newlines cross the real launcher unchanged."""
        for remove in (False, True):
            with self.subTest(remove=remove), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                checkout = base / "checkout"
                subprocess.run(["git", "init", "-q", "-b", "feature/probe", str(checkout)], check=True)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "-c",
                        "user.name=Probe",
                        "-c",
                        "user.email=probe@example.invalid",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "-m",
                        "base",
                    ],
                    check=True,
                )
                home, tools, temporary = base / "home", base / "bin", base / "tmp"
                tools.mkdir()
                temporary.mkdir()
                home.mkdir()
                gh = tools / "gh"
                gh.write_text(
                    f"#!{sys.executable}\nimport sys\n"
                    "assert sys.argv[1:] == ['auth', 'token']\n"
                    "print('synthetic-unused-token')\n"
                )
                gh.chmod(0o755)
                capture, arguments = base / "stdin.bin", base / "argv.json"
                shim = tools / "npx"
                shim.write_text(
                    f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n"
                    "assert sys.argv[1:3] == ['--yes', '@anthropic-ai/sandbox-runtime@0.0.65']\n"
                    f"Path({str(capture)!r}).write_bytes(sys.stdin.buffer.read())\n"
                    f"Path({str(arguments)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                )
                shim.chmod(0o755)
                for tool in ("rg",):
                    executable = tools / tool
                    executable.write_text("#!/bin/sh\nexit 0\n")
                    executable.chmod(0o755)
                prompt = base / "prompt.txt"
                prompt.write_bytes(EXPECTED)
                if remove:
                    prompt.unlink()
                else:
                    prompt.write_bytes(b"replacement must not be forwarded\n")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/sandbox/spawn_sandboxed_worker.py"),
                        "--driver",
                        str(checkout),
                        str(prompt),
                        "fixture-model",
                    ],
                    cwd=ROOT,
                    input=EXPECTED,
                    env={"HOME": str(home), "TMPDIR": str(temporary), "PATH": f"{tools}:{os.environ['PATH']}"},
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(capture.read_bytes(), EXPECTED)
                argv = json.loads(arguments.read_text())
                self.assertIn("claude", argv)
                self.assertIn("--json-schema", argv)
                self.assertNotIn("replacement must not be forwarded", " ".join(argv))
                self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
