#!/usr/bin/env python3
"""Small, dependency-free source quality checks for coderails."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_LOC = 400
DEFAULT_FUNCTION_LINES = 100
LOC_EXCEPTIONS = {
    "hooks/scripts/tests/enforce_pr_workflow.test.sh": 1149,
    "hooks/scripts/tests/graph_dispatch_complete.test.sh": 700,
    "hooks/scripts/lib/graph_evidence_revalidate.sh": 421,
    "hooks/scripts/tests/merge_wiki_debt_gate.test.sh": 567,
    "hooks/scripts/lib/loop_state_common.sh": 1606,
    "hooks/scripts/tests/loop_stall_guard.test.sh": 2323,
    "packages/codex/hooks/scripts/destructive_bash_gate.sh": 903,
    "packages/codex/scripts/merge.sh": 512,
    "packages/codex/scripts/post_evals.sh": 1229,
    "packages/codex/skills/dashboard/app/src/components/AssistantLinkPanel.tsx": 418,
    "packages/codex/skills/dashboard/app/src/components/OutputViewerPanel.client.test.tsx": 406,
    "packages/codex/skills/dashboard/app/test/AssistantLinkPanel.test.ts": 707,
    "packages/codex/skills/dashboard/app/test/events.test.ts": 694,
    "packages/codex/skills/dashboard/app/test/run.test.ts": 693,
    "packages/codex/skills/dashboard/app/test/runBuilder.test.ts": 558,
    "packages/codex/skills/dashboard/app/test/sessions.test.ts": 612,
    "packages/codex/skills/dashboard/app/test/usage.test.ts": 449,
    "packages/codex/skills/dashboard/runner/test/artifactGate.test.ts": 492,
    "packages/codex/skills/dashboard/runner/test/sweep.test.ts": 714,
    "scripts/merge.sh": 512,
}
FUNCTION_EXCEPTIONS = {
    ("packages/codex/hooks/scripts/destructive_bash_gate.sh", "deny"): 107,
    ("packages/codex/scripts/merge.sh", "merge::has_wiki_ingest_for_merged_prs"): 185,
    ("packages/codex/scripts/merge.sh", "merge::main"): 209,
    ("packages/codex/scripts/post_evals.sh", "post_evals::validate_structure"): 122,
    ("packages/codex/scripts/post_evals.sh", "post_evals::validate_smoke_execution"): 113,
    ("packages/codex/scripts/post_evals.sh", "post_evals::smoke_verify"): 152,
    ("packages/codex/scripts/post_evals.sh", "post_evals::validate_discriminating"): 105,
    ("packages/codex/scripts/push.sh", "push::main"): 120,
    ("hooks/scripts/lib/loop_state_common.sh", "als_gate_proofs_on_complete"): 364,
    ("hooks/scripts/lib/loop_state_common.sh", "als_report_cost_on_complete"): 165,
    ("hooks/scripts/tests/loop_stall_guard.test.sh", "mk_malformed_transcript"): 2066,
    ("scripts/merge.sh", "merge::has_wiki_ingest_for_merged_prs"): 185,
    ("scripts/merge.sh", "merge::main"): 209,
    ("scripts/lib/post_evals_structure.sh", "post_evals::validate_structure"): 188,
    ("scripts/lib/post_evals_smoke_freeze.sh", "post_evals::validate_smoke_execution"): 113,
    ("scripts/lib/post_evals_smoke_gate.sh", "post_evals::smoke_verify"): 147,
    ("scripts/lib/post_evals_freeze.sh", "post_evals::validate_discriminating"): 105,
}
SOURCE_ROOTS = (
    ".claude-plugin",
    "agents",
    "commands",
    "hooks",
    "instructions",
    "packages",
    "scripts",
    "skills",
)
EXTENSIONS = {".bash", ".cfg", ".js", ".json", ".jsx", ".md", ".py", ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
EXCLUDED_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
EXCLUDED_PARTS = {".build", "assets", "dist", "fixtures", "node_modules"}


def source_files(root: Path, paths: list[str]) -> list[Path]:
    if paths:
        candidates = [root / path for path in paths]
    else:
        candidates = [root] if root != Path.cwd().resolve() else [root / source_root for source_root in SOURCE_ROOTS]
    files = []
    for candidate in candidates:
        if candidate.is_absolute():
            candidate = candidate.resolve()
        if candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(path for path in candidate.rglob("*") if path.is_file())
    return sorted(
        path
        for path in set(files)
        if path.suffix in EXTENSIONS
        and path.name not in EXCLUDED_NAMES
        and not EXCLUDED_PARTS.intersection(path.relative_to(root).parts)
    )


def finding(path: Path, message: str, line: int | None = None) -> str:
    suffix = f":{line}" if line else ""
    return f"{path}{suffix}: {message}"


def check_format(path: Path, text: str) -> list[str]:
    issues = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.rstrip("\n\r") != line.rstrip():
            issues.append(finding(path, "trailing whitespace", number))
    if text and not text.endswith("\n"):
        issues.append(finding(path, "missing final newline"))
    if path.suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            issues.append(finding(path, f"invalid JSON: {error.msg}", error.lineno))
    return issues


def check_python(path: Path, text: str, path_key: str, function_limit: int) -> list[str]:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        return [finding(path, f"invalid Python: {error.msg}", error.lineno)]
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        lines = node.end_lineno - node.lineno + 1
        limit = FUNCTION_EXCEPTIONS.get((path_key, node.name), function_limit)
        if lines > limit:
            issues.append(finding(path, f"function {node.name} is {lines} lines (max {limit})", node.lineno))
    return issues


def check_bash(path: Path, text: str, path_key: str, function_limit: int) -> list[str]:
    start_pattern = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_:]*)\s*\(\s*\)\s*\{")
    lines = text.splitlines()
    issues = []
    for index, line in enumerate(lines):
        match = start_pattern.match(line)
        if not match:
            continue
        depth = 0
        end = index
        for end in range(index, len(lines)):
            depth += lines[end].count("{") - lines[end].count("}")
            if depth <= 0:
                break
        lines_used = end - index + 1
        name = match.group(1)
        limit = FUNCTION_EXCEPTIONS.get((path_key, name), function_limit)
        if lines_used > limit:
            issues.append(finding(path, f"function {name} is {lines_used} lines (max {limit})", index + 1))
    return issues


COMMENTED_CODE = (
    re.compile(r"^\s*#\s*(?:def\s+\w+\s*\(|class\s+\w+\s*[:(]|from\s+\S+\s+import\s+|import\s+\S+|return\s+(?:[0-9]+|\w+\s*[+*/-])\b)"),
    re.compile(r"^\s*#\s*(?:function\s+\w+\s*\(|local\s+\w+=|if\s+\[\[|for\s+\w+\s+in\s+|case\s+\S+\s+in|echo\s+['\"]|git\s+\w+|python3\s+|node\s+|return\s+[0-9])"),
    re.compile(r"^\s*//\s*(?:function\s+\w+\s*\(|(?:const|let|var)\s+\w+\s*=|(?:if|for|while)\s*\(|return\s+\S+\s*[+*/=-])"),
)


def check_commented_code(path: Path, text: str) -> list[str]:
    if path.suffix not in {".bash", ".js", ".jsx", ".py", ".sh", ".ts", ".tsx"}:
        return []
    issues = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("///") or re.match(r"^\s*//\s*MARK:", line):
            continue
        if any(pattern.match(line) for pattern in COMMENTED_CODE):
            issues.append(finding(path, "looks like commented-out code", number))
    return issues


def check_diff(root: Path) -> list[str]:
    issues = []
    for args in (("git", "diff", "--check"), ("git", "diff", "--cached", "--check")):
        result = subprocess.run(args, cwd=root, text=True, capture_output=True, check=False)
        if result.returncode:
            issues.extend(result.stdout.splitlines() + result.stderr.splitlines())
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="return non-zero when findings exist")
    parser.add_argument("--changed", action="store_true", help="scan only changed tracked files")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--max-loc", type=int, default=int(os.environ.get("MAX_LOC", DEFAULT_LOC)))
    parser.add_argument(
        "--max-function-lines",
        type=int,
        default=int(os.environ.get("MAX_FUNCTION_LINES", DEFAULT_FUNCTION_LINES)),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    issues: list[str] = []
    files = source_files(root, args.paths)
    if args.changed and not args.paths:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"], cwd=root, text=True, capture_output=True, check=False
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=root, text=True, capture_output=True, check=False
        )
        changed = {line for line in result.stdout.splitlines() + staged.stdout.splitlines() if line}
        files = [path for path in files if str(path.relative_to(root)) in changed]
    for path in files:
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        path_key = path.relative_to(root).as_posix()
        limit = LOC_EXCEPTIONS.get(path_key, args.max_loc)
        if line_count > limit:
            issues.append(finding(path, f"{line_count} lines (max {limit})"))
        issues.extend(check_format(path, text))
        if path.suffix == ".py":
            issues.extend(check_python(path, text, path_key, args.max_function_lines))
        elif path.suffix in {".bash", ".sh"}:
            issues.extend(check_bash(path, text, path_key, args.max_function_lines))
        issues.extend(check_commented_code(path, text))
    if root == Path.cwd().resolve() and not args.paths:
        issues.extend(check_diff(root))
    for issue in issues:
        print(issue, file=sys.stderr)
    print(f"quality: scanned {len(files)} file(s), {len(issues)} finding(s)")
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
