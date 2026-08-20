#!/usr/bin/env python3
"""Small, dependency-free checks used by native Codex quality feedback."""

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
SOURCE_ROOTS = (
    ".claude-plugin",
    "agents",
    "codex",
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


def check_python(path: Path, text: str, function_limit: int) -> list[str]:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        return [finding(path, f"invalid Python: {error.msg}", error.lineno)]
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        lines = node.end_lineno - node.lineno + 1
        if lines > function_limit:
            issues.append(finding(path, f"function {node.name} is {lines} lines (max {function_limit})", node.lineno))
    return issues


def check_bash(path: Path, text: str, function_limit: int) -> list[str]:
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
        if lines_used > function_limit:
            issues.append(finding(path, f"function {match.group(1)} is {lines_used} lines (max {function_limit})", index + 1))
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
        limit = args.max_loc
        if line_count > limit:
            issues.append(finding(path, f"{line_count} lines (max {limit})"))
        issues.extend(check_format(path, text))
        if path.suffix == ".py":
            issues.extend(check_python(path, text, args.max_function_lines))
        elif path.suffix in {".bash", ".sh"}:
            issues.extend(check_bash(path, text, args.max_function_lines))
        issues.extend(check_commented_code(path, text))
    if root == Path.cwd().resolve() and not args.paths:
        issues.extend(check_diff(root))
    for issue in issues:
        print(issue, file=sys.stderr)
    print(f"quality: scanned {len(files)} file(s), {len(issues)} finding(s)")
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
