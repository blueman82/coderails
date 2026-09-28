#!/usr/bin/env python3
"""Preserve tolerant transcript extraction, outer failure boundaries, and session audit mining."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.discipline_common import extract_last_text, file_count, mine_hook_blocks, stable_text
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


def assistant(content: object) -> str:
    """Encode a native assistant record without normalizing malformed fixture shapes."""
    return json.dumps({"type": "assistant", "message": {"content": content}})


class DisciplineCommonTests(HookTestCase):
    """Retain tolerant local parsing and intentionally broad aggregate fail-open semantics."""

    def test_last_text_shapes_order_tail_and_failure_boundary(self) -> None:
        """Malformed outer entries recover; a malformed text value invalidates the extraction."""
        real = assistant([{"type": "text", "text": "REAL"}])
        rows = [
            (
                [
                    assistant(
                        [{"type": "text", "text": "hello"}, {"type": "tool_use"}, {"type": "text", "text": "world"}]
                    )
                ],
                "hello world",
            ),
            ([assistant("plain string")], "plain string"),
            ([real, assistant("second")], "second"),
            ([assistant([{"type": "tool_use", "name": "Read"}])], ""),
            (["not json", real], "REAL"),
            ([real, "not json", assistant("last")], "last"),
            ([real, '{"torn'], "REAL"),
            (["not json", '{"torn'], ""),
            (['"scalar"', real], "REAL"),
            ([real, '{"type":"assistant","message":["bare"]}'], "REAL"),
            ([assistant(["bare", {"type": "text", "text": "REAL"}])], "REAL"),
            ([real, assistant([{"type": "text", "text": {"nested": "object"}}])], ""),
            ([assistant([{"type": "text", "text": {"nested": "object"}}]), real], ""),
        ]
        path = self.directory / "texts.jsonl"
        for lines, expected in rows:
            with self.subTest(lines=lines):
                path.write_text("\n".join(lines))
                self.assertEqual(extract_last_text(str(path), 200), expected)
        path.write_text(real + "\nnot json")
        self.assertEqual(extract_last_text(str(path), 1), "")
        self.assertEqual(extract_last_text(str(self.directory / "missing"), 10), "")

    def test_file_count_shapes_deduplication_and_turn_boundary(self) -> None:
        """Bad outer shapes are ignored, bad tool input fails open for the complete turn."""
        edit = assistant([{"type": "tool_use", "name": "Edit", "input": {"file_path": "/a.py"}}])
        write = assistant([{"type": "tool_use", "name": "Write", "input": {"file_path": "/b.py"}}])
        path = self.directory / "edits.jsonl"
        malformed = [
            '"scalar"',
            "bad",
            '{"type":"assistant","message":"wrong"}',
            '{"type":"user","message":"wrong"}',
            '{"torn',
        ]
        for shape in malformed:
            path.write_text("\n".join([edit, shape, write]))
            self.assertEqual(file_count(str(path)), 2)
        path.write_text("\n".join([edit, edit, edit]))
        self.assertEqual(file_count(str(path)), 1)
        path.write_text(assistant(["bare", {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a.py"}}]))
        self.assertEqual(file_count(str(path)), 1)
        path.write_text(edit + "\n" + assistant([{"type": "tool_use", "name": "Write", "input": "wrong"}]))
        self.assertEqual(file_count(str(path)), 0)
        prompt = json.dumps({"type": "user", "message": {"content": "next turn"}})
        result = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
        path.write_text("\n".join([edit, prompt, write, result]))
        self.assertEqual(file_count(str(path)), 1)

    def test_stable_text_retries_length_and_empty_window(self) -> None:
        """The flush-race backoff stops on stable nonempty length and respects attempt budget."""
        with patch(
            "hooks.scripts.lib.discipline_common.extract_last_text", side_effect=["", "hello", "world"]
        ) as reader:
            self.assertEqual(stable_text("unused", 200, 5, 0), ("world", 2))
            self.assertEqual(reader.call_count, 3)
        with patch("hooks.scripts.lib.discipline_common.extract_last_text", return_value="") as reader:
            self.assertEqual(stable_text("unused", 200, 3, 0), ("", 3))
            self.assertEqual(reader.call_count, 3)

    def test_mining_exact_sessions_flags_and_missing_inputs(self) -> None:
        """Only matching session tokens count; each flagged event increments once."""
        path = self.directory / "mine.log"
        path.write_text(
            "\n".join(
                [
                    "ts=1 session=sess-a hook=alpha blocked=0",
                    "ts=2 session=sess-ab hook=alpha blocked=1",
                    "ts=3 session=sess-a hook=alpha blocked=1 would_block=1",
                    "ts=4 session=sess-a hook=beta nudged=1",
                    "ts=5 session=sess-a hook=beta would_block=1",
                    "ts=6 hook=beta blocked=1",
                    "garbage",
                    "session=sess-a no_hook",
                ]
            )
        )
        expected = {"alpha": {"events": 2, "flagged": 1}, "beta": {"events": 2, "flagged": 2}}
        self.assertEqual(mine_hook_blocks("sess-a", str(path)), expected)
        self.assertNotEqual(mine_hook_blocks("sess-a", str(path)), {"alpha": {"events": 99, "flagged": 99}})
        self.assertEqual(mine_hook_blocks("", str(path)), {})
        self.assertEqual(mine_hook_blocks("missing", str(path)), {})
        self.assertEqual(mine_hook_blocks("sess-a", str(self.directory / "missing")), {})


if __name__ == "__main__":
    unittest.main()
