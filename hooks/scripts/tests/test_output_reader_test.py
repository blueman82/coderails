#!/usr/bin/env python3
"""Black-box contracts for retained test output and explicit reader history."""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[3]
READER = REPO / "hooks/scripts/test_output.py"
NATIVE = REPO / "packages/codex/hooks/scripts/test_output.py"
CREATE_RUN = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_output import begin_run, finish_run
run = begin_run(sys.argv[2], Path(sys.argv[3]), sys.argv[4])
(run / 'output.log').write_bytes(Path(sys.argv[5]).read_bytes())
notice = finish_run(run, int(sys.argv[6]))
print(json.dumps({'run': str(run), 'notice': notice}))
"""


class OutputFixtures(unittest.TestCase):
    """Exercise the independently installed output reader."""

    def setUp(self) -> None:
        """Give every test a private persistent store and project identity."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.directory = Path(self.scratch.name).resolve()
        self.project = self.directory / "project with € spaces"
        self.project.mkdir()
        self.store = self.directory / "output"
        self.environment = {**os.environ, "CODERAILS_TEST_OUTPUT_DIR": str(self.store)}

    def make_run(
        self,
        data: bytes,
        *,
        provider: str = "claude",
        project: Path | None = None,
        command: str = "python checks.py --exact '€'",
        exit_code: int = 1,
        reader: Path = READER,
    ) -> Path:
        """Invoke the public lifecycle API in a separate process with real log bytes."""
        self.assertTrue(reader.is_file(), f"Missing reader: {reader}")
        fixture = self.directory / f"{uuid.uuid4().hex}.input"
        fixture.write_bytes(data)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                CREATE_RUN,
                str(reader.parent),
                provider,
                str(project or self.project),
                command,
                str(fixture),
                str(exit_code),
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = cast("dict[str, Any]", json.loads(result.stdout))
        run = Path(response["run"])
        self.assertTrue(run.is_relative_to(self.store))
        self.assertEqual(self.log_bytes(run), data)
        return run

    @staticmethod
    def log_bytes(run: Path) -> bytes:
        """Read retained source bytes regardless of lossless archival state."""
        raw = run / "output.log"
        return raw.read_bytes() if raw.exists() else gzip.decompress((run / "output.log.gz").read_bytes())

    def invoke(self, *arguments: str, reader: Path = READER) -> subprocess.CompletedProcess[str]:
        """Call only the documented standalone CLI boundary."""
        return subprocess.run(
            [sys.executable, str(reader), *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def read(self, run: Path, *arguments: str, reader: Path = READER) -> dict[str, Any]:
        """Parse a successful reader response and check its invariant measurements."""
        result = self.invoke("read", str(run), *arguments, reader=reader)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = cast("dict[str, Any]", json.loads(result.stdout))
        self.assertIn(response["log_path"], (str(run / "output.log"), str(run / "output.log.gz")))
        self.assertTrue(Path(response["log_path"]).is_file())
        self.assertEqual(response["total_bytes"], len(self.log_bytes(run)))
        self.assertEqual(response["returned_text_bytes"], len(response["text"].encode("utf-8")))
        self.assertIs(response["policy_truncated"], False)
        self.assertIsNone(response["delivered_bytes"])
        self.assertIsNone(response["delivery_truncated"])
        request = Path(response["request_path"])
        self.assertTrue(request.is_file())
        return response


class OutputReaderTests(OutputFixtures):
    """Exercise explicit retrieval through the standalone CLI."""

    def test_reader_exists(self) -> None:
        """The canonical reader must exist before its contract can run."""
        self.assertTrue((Path(__file__).resolve().parents[1] / "test_output.py").is_file())

    def test_full_read_retains_early_error_unicode_binary_and_line_endings(self) -> None:
        """Full retrieval retains every source byte, with truthful replacement measurements."""
        data = b"FIRST ERROR\r\n" + b"x" * 1499 + "€🙂".encode() + b"\n" + b"tail\n" * 80 + b"bad:\xff"
        run = self.make_run(data)
        response = self.read(run, "--all")
        self.assertEqual(response["text"], data.decode("utf-8", errors="replace"))
        self.assertEqual(response["total_lines"], 83)
        self.assertEqual(response["selected_ranges"], [[1, 83]])
        self.assertEqual(response["returned_source_bytes"], len(data))
        self.assertGreater(response["returned_text_bytes"], response["returned_source_bytes"])
        self.assertEqual(response["omitted_lines"], 0)
        self.make_run(b"later\n", exit_code=0)
        self.assertEqual(self.log_bytes(run), data)
        metadata = json.loads((run / "run.json").read_text())
        for key in ("run_id", "provider", "project", "command", "exit_code", "total_bytes", "total_lines"):
            self.assertIn(key, metadata)
        self.assertEqual(metadata["exit_code"], 1)
        self.assertEqual(metadata["run_id"], response["run_id"])

    def test_full_read_has_no_implicit_size_limit(self) -> None:
        """An explicit full request returns a long single line and all later lines."""
        data = b"L" * 70000 + b"\n" + b"next\n" * 300
        run = self.make_run(data)
        self.assertEqual(self.read(run, "--all")["text"].encode(), data)

    def test_empty_and_unterminated_line_counts(self) -> None:
        """Empty, newline-terminated and unterminated logs have consistent source lines."""
        for data, count in ((b"", 0), (b"one", 1), (b"one\n", 1), (b"one\r\n\nlast", 3)):
            with self.subTest(data=data):
                run = self.make_run(data)
                response = self.read(run, "--all")
                self.assertEqual(response["total_lines"], count)
                self.assertEqual(response["text"], data.decode())
                self.assertEqual(response["returned_source_bytes"], len(data))

    def test_untrained_default_has_no_guessed_window(self) -> None:
        """A fresh command returns no guessed text and leaves explicit-reading guidance."""
        run = self.make_run(b"early\n" + b"late\n" * 40)
        response = self.read(run)
        self.assertEqual(response["text"], "")
        self.assertEqual(response["selected_ranges"], [])
        self.assertEqual(response["returned_source_bytes"], 0)
        self.assertEqual(response["omitted_lines"], 41)
        self.assertIn("--all", json.dumps(response))

    def test_explicit_followups_expand_selection_without_predicting_future_demand(self) -> None:
        """Callers can expand requested regions without injecting predictions into defaults."""
        data = b"".join(f"line {number}\n".encode() for number in range(1, 13))
        first = self.make_run(data)
        narrow = self.read(first, "--start", "2", "--end", "3")
        self.assertEqual(narrow["text"], "line 2\nline 3\n")
        wider = self.read(first, "--start", "2", "--end", "9")
        self.assertEqual(wider["text"], "".join(f"line {number}\n" for number in range(2, 10)))
        self.assertEqual(wider["selected_ranges"], [[2, 9]])
        self.assertEqual(wider["omitted_lines"], 4)
        self.assertEqual(self.read(first)["text"], "")
        self.assertEqual(self.read(self.make_run(b"short\n"))["text"], "")
        self.read(first, "--all")
        longer = data + b"newly added\n"
        later = self.make_run(longer)
        self.assertEqual(self.read(later)["text"], "")
        self.assertEqual(self.read(later, "--all")["text"].encode(), longer)

    def test_runs_scoped_by_provider_project_and_exact_command(self) -> None:
        """Similar path and command spellings must never alias unrelated run scopes."""
        first_project = self.directory / "same-a"
        second_project = self.directory / "same a"
        first_project.mkdir()
        second_project.mkdir()
        data = b"one\ntwo\nthree\n"
        run = self.make_run(data, project=first_project, command="check-a")
        self.read(run, "--start", "2", "--end", "2")
        others = (
            self.make_run(data, project=second_project, command="check-a"),
            self.make_run(data, project=first_project, command="check a"),
            self.make_run(data, provider="codex", project=first_project, command="check-a"),
        )
        for other in others:
            self.assertNotEqual(other.parent, run.parent)
            self.assertEqual(self.read(other)["text"], "")
        repeated = self.make_run(data, project=first_project, command="check-a")
        self.assertEqual(repeated.parent, run.parent)
        self.assertEqual(self.read(repeated)["text"], "")

    def test_literal_search_context_and_actual_selected_regions(self) -> None:
        """Metacharacters remain literal and overlapping context is returned once."""
        data = 'before\n.*["\\€ hit\nmiddle\n.*["\\€ hit\nafter\nlast\n'.encode()
        run = self.make_run(data)
        response = self.read(run, "--search", '.*["\\€', "--before", "1", "--after", "1")
        self.assertEqual(response["selected_ranges"], [[1, 5]])
        self.assertEqual(response["text"].encode(), b"".join(data.splitlines(keepends=True)[:5]))
        self.assertEqual(response["omitted_lines"], 1)
        self.assertEqual(response["returned_source_bytes"], len(response["text"].encode()))
        changed = self.make_run(b"a\nb\nc\nd\ne\nf\n")
        self.assertEqual(self.read(changed)["text"], "")
        no_match = self.make_run(data, command="no matches")
        self.assertEqual(self.read(no_match, "--search", "does not exist")["text"], "")
        self.assertEqual(self.read(no_match)["selected_ranges"], [])

    def test_invalid_ranges_never_train_history(self) -> None:
        """Rejected indices and conflicting selectors leave future defaults untrained."""
        run = self.make_run(b"one\ntwo\nthree\n")
        invalid = (
            ("--start", "-1", "--end", "2"),
            ("--start", "0", "--end", "2"),
            ("--start", "3", "--end", "2"),
            ("--search", "one", "--before", "-1"),
            ("--all", "--start", "1", "--end", "2"),
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.assertNotEqual(self.invoke("read", str(run), *arguments).returncode, 0)
                self.assertEqual(self.read(run)["text"], "")
        response = self.read(run, "--start", "10", "--end", "20")
        self.assertEqual(response["selected_ranges"], [])
        self.assertEqual(response["omitted_lines"], 3)

    def test_followup_ranges_preserve_exact_binary_accounting(self) -> None:
        """A later requested range includes only its own source lines and bytes."""
        data = b"first\ninvalid:\xff\r\nthird\nfourth"
        run = self.make_run(data)
        response = self.read(run, "--start", "2", "--end", "2")
        self.assertEqual(response["text"], "invalid:�\r\n")
        self.assertEqual(response["returned_source_bytes"], len(b"invalid:\xff\r\n"))
        self.assertEqual(response["returned_text_bytes"], len("invalid:�\r\n".encode()))
        wider = self.read(run, "--start", "2", "--end", "4")
        self.assertEqual(wider["selected_ranges"], [[2, 4]])
        self.assertEqual(wider["text"], "invalid:�\r\nthird\nfourth")
        self.assertEqual(wider["omitted_lines"], 1)
        self.assertEqual(self.read(run)["text"], "")

    def test_concurrent_runs_and_read_requests_remain_independent(self) -> None:
        """Concurrent creation and reads preserve every log and history event."""
        payloads = tuple(b"".join(f"run {run} line {line}\n".encode() for line in range(1, 5)) for run in range(4))
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs = list(pool.map(self.make_run, payloads))
        self.assertEqual(len(set(runs)), 4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.read, run, "--start", str(i), "--end", str(i)) for i, run in enumerate(runs, 1)]
            responses = [future.result() for future in futures]
        paths = [Path(response["request_path"]) for response in responses]
        self.assertEqual(len(set(paths)), 4)
        self.assertTrue(all(path.is_file() for path in paths))
        for index, run in enumerate(runs):
            self.assertEqual(self.log_bytes(run), payloads[index])
            self.assertEqual(responses[index]["text"], f"run {index} line {index + 1}\n")
        self.assertEqual(self.read(self.make_run(b"a\nb\nc\nd\n"))["text"], "")

    def test_observation_is_separate_and_bound_to_exact_request(self) -> None:
        """Explicit delivery feedback creates an observation without rewriting raw evidence."""
        run = self.make_run(b"one\ntwo\n")
        response = self.read(run, "--all")
        request = Path(response["request_path"])
        original = request.read_bytes()
        before = set(self.store.rglob("*.json"))
        result = self.invoke(
            "observe", str(request), "--delivered-bytes", "3", "--truncated", "yes", "--source", "test consumer"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(request.read_bytes(), original)
        added = set(self.store.rglob("*.json")) - before
        self.assertEqual(len(added), 1)
        observation = json.loads(added.pop().read_text())
        self.assertEqual(observation["request_path"], str(request))
        self.assertEqual(observation["source"], "test consumer")
        self.assertEqual(observation["delivered_bytes"], 3)
        self.assertIs(observation["delivery_truncated"], True)
        next_response = self.read(run, "--all")
        self.assertNotEqual(next_response["request_path"], str(request))

    def test_native_copy_is_identical_and_independently_executable(self) -> None:
        """A provider-only directory supports lifecycle and reader CLI without root imports."""
        self.assertEqual(NATIVE.read_bytes(), READER.read_bytes())
        standalone = self.directory / "native-only"
        standalone.mkdir()
        reader = standalone / "test_output.py"
        reader.write_bytes(NATIVE.read_bytes())
        run = self.make_run(b"native\n", provider="codex", reader=reader)
        self.assertEqual(self.read(run, "--all", reader=reader)["text"], "native\n")


if __name__ == "__main__":
    unittest.main()
