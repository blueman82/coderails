#!/usr/bin/env python3
"""Focused test for hooks/scripts/inject_context.py's UserPromptSubmit contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "inject_context.py"


def run(payload: str) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with the given stdin payload and return its result."""
    return subprocess.run(["python3", str(HOOK)], input=payload, text=True, capture_output=True, check=False)


def fail(message: str) -> None:
    """Report a test failure and exit non-zero."""
    print(f"inject_context_test: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_context(payload: str) -> str:
    """Run the hook and return its additionalContext string."""
    result = run(payload)
    if result.returncode != 0:
        fail(f"hook exited {result.returncode}: {result.stderr}")
    data = json.loads(result.stdout)
    context = data["hookSpecificOutput"]["additionalContext"]
    assert isinstance(context, str)
    return context


def check_valid_json_envelope() -> None:
    """Output is a JSON object naming the UserPromptSubmit event."""
    result = run('{"session_id":"S1"}')
    data = json.loads(result.stdout)
    if data.get("hookSpecificOutput", {}).get("hookEventName") != "UserPromptSubmit":
        fail(f"unexpected hookEventName: {result.stdout}")


def check_context_fields_present() -> None:
    """AdditionalContext always carries the [ctx] prefix, date, cwd, and branch."""
    context = parse_context('{"session_id":"S1"}')
    today = date.today().strftime("%Y-%m-%d")
    for expected in ("[ctx]", today, "cwd=", "branch="):
        if expected not in context:
            fail(f"context missing {expected!r}: {context}")


def check_first_prompt_gets_reminder(scratch: Path) -> None:
    """An empty (or missing) transcript is treated as the first prompt."""
    transcript = scratch / "empty.jsonl"
    transcript.write_text("", encoding="utf-8")
    context = parse_context(json.dumps({"session_id": "S1", "transcript_path": str(transcript)}))
    if "[discipline]" not in context:
        fail(f"first prompt should include discipline reminder: {context}")


def check_later_prompt_omits_reminder(scratch: Path) -> None:
    """A transcript with prior content omits the discipline reminder."""
    transcript = scratch / "prior.jsonl"
    transcript.write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n', "utf-8")
    context = parse_context(json.dumps({"session_id": "S1", "transcript_path": str(transcript)}))
    if "[discipline]" in context:
        fail(f"later prompt should omit discipline reminder: {context}")


def check_malformed_payload_still_emits_context() -> None:
    """Invalid JSON on stdin degrades to the first-prompt reminder, never a crash."""
    context = parse_context("not json")
    if "[discipline]" not in context:
        fail(f"malformed payload should fall back to the discipline reminder: {context}")


def main() -> int:
    """Run every inject_context_test scenario, each in its own scratch subdirectory."""
    check_valid_json_envelope()
    check_context_fields_present()
    with tempfile.TemporaryDirectory(prefix="coderails-inject-context.") as raw_scratch:
        scratch = Path(raw_scratch)
        check_first_prompt_gets_reminder(scratch)
        check_later_prompt_omits_reminder(scratch)
    check_malformed_payload_still_emits_context()
    print("inject_context_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
