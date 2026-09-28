"""Run required Python tools, materialization checks and dashboard validation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from .source_kind import is_python_source

GENERATED_SEMANTICS = (
    "skills/agentic-loop/scripts/graph_semantics.py",
    "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
)


def run_tool(arguments: list[str], root: Path, environment: dict[str, str] | None = None) -> bool:
    """Run a quality tool, treating spawn and command failures as findings."""
    try:
        return subprocess.run(arguments, cwd=root, env=environment, check=False).returncode == 0
    except OSError as error:
        print(f"quality: tool execution failed: {error}", file=sys.stderr)
        return False


def mypy_environment(directory: Path, root: Path, native_workflow: bool = False) -> dict[str, str]:
    """Resolve imports from the provider owning this independently checked group."""
    codex = root / "packages/codex"
    package_tests = root / "packages/tests"
    provider = codex if directory.is_relative_to(codex) or native_workflow else root
    paths = [provider, provider / "skills/agentic-loop/scripts"]
    if directory.is_relative_to(package_tests) and not native_workflow:
        paths[1:1] = [codex / "skills/agentic-loop/scripts", codex / "hooks/scripts"]
    if directory.is_relative_to(root / "skills/workflow-audit/scripts"):
        paths.extend(
            [
                root / "skills/workflow-audit/scripts",
                root / "skills/workflow-audit/scripts/tests",
                root / "skills/dashboard/scripts",
            ]
        )
    if provider == root:
        paths.append(root / "scripts/integrity-gate")
    else:
        paths.append(provider / "hooks/scripts")
    environment = dict(os.environ)
    environment["MYPYPATH"] = os.pathsep.join(str(path) for path in paths)
    return environment


def python_checks(files: list[Path], root: Path, config: Path) -> bool:
    """Require every Python checker and isolate independently installed module namespaces."""
    python_files = [
        path
        for path in files
        if is_python_source(path)
        and (not path.is_relative_to(root) or path.relative_to(root).as_posix() not in GENERATED_SEMANTICS)
    ]
    if not python_files:
        return True
    for tool in ("ruff", "black", "pyright", "mypy"):
        available = subprocess.run([sys.executable, "-m", tool, "--version"], capture_output=True, check=False)
        if available.returncode:
            print(f"quality: required Python tool unavailable: {tool}", file=sys.stderr)
            return False
    paths = [str(path) for path in python_files]
    passed = run_tool([sys.executable, "-m", "ruff", "check", "--no-cache", "--config", str(config), *paths], root)
    passed = run_tool([sys.executable, "-m", "black", "--check", "--config", str(config), *paths], root) and passed
    groups: dict[tuple[Path, bool], list[str]] = defaultdict(list)
    for path in python_files:
        native_workflow = path.parent == root / "packages/tests" and path.name.startswith("test_codex_workflow_")
        groups[(path.parent, native_workflow)].append(str(path))
    for (directory, native_workflow), group in groups.items():
        passed = run_tool([sys.executable, "-m", "pyright", "--project", str(config), *group], root) and passed
        passed = (
            run_tool(
                [sys.executable, "-m", "mypy", "--config-file", str(config), *group],
                root,
                mypy_environment(directory, root, native_workflow),
            )
            and passed
        )
    return passed


def check_materialization(root: Path) -> bool:
    """Require generated provider semantic copies to equal their maintained source."""
    source = root / "packages/graph-semantics/graph_semantics.py"
    if not source.is_file():
        return True
    passed = True
    for relative in GENERATED_SEMANTICS:
        copy = root / relative
        if not copy.is_file() or copy.read_bytes() != source.read_bytes():
            print(f"quality: generated graph semantics drift: {copy}", file=sys.stderr)
            passed = False
    output_source = root / "hooks/scripts/test_output.py"
    output_copy = root / "packages/codex/hooks/scripts/test_output.py"
    if output_source.is_file() and (
        not output_copy.is_file() or output_source.read_bytes() != output_copy.read_bytes()
    ):
        print(f"quality: generated test-output helper drift: {output_copy}", file=sys.stderr)
        passed = False
    return passed


def shell_checks(files: list[Path], root: Path) -> bool:
    """Retain advisory shell tooling while the retirement inventory is incomplete."""
    paths = [str(path) for path in files if path.suffix in (".sh", ".bash")]
    if not paths:
        return True
    passed = True
    for tool, flags in (("shellcheck", []), ("shfmt", ["-i", "4", "-d"])):
        if shutil.which(tool):
            if paths:
                passed = run_tool([tool, *flags, *paths], root) and passed
        else:
            print(f"quality: {tool} unavailable; Bash tooling remains advisory until installed.", file=sys.stderr)
    return passed


def dashboard_checks(root: Path, strict: bool) -> bool:
    """Check changed dashboards using their own pinned package installations."""
    changed: set[str] = set()
    for flags in (("--name-only", "HEAD"), ("--cached", "--name-only")):
        result = subprocess.run(["git", "diff", *flags], cwd=root, capture_output=True, text=True, check=False)
        changed.update(result.stdout.splitlines())
    passed = True
    for provider in (Path("."), Path("packages/codex")):
        prefix = (provider / "skills/dashboard").as_posix().removeprefix("./") + "/"
        if not any(path.startswith(prefix) and Path(path).suffix in (".js", ".jsx", ".ts", ".tsx") for path in changed):
            continue
        for package in ("app", "lib", "runner", "obsidian"):
            directory = root / provider / "skills/dashboard" / package
            if not (directory / "node_modules").is_dir():
                print(
                    f"quality: {directory} dependencies missing; install from its lockfile before strict checks",
                    file=sys.stderr,
                )
                passed = not strict and passed
                continue
            if (directory / "package.json").is_file():
                for operation in ("lint", "typecheck"):
                    passed = (
                        run_tool(["npm", "--prefix", str(directory), "run", "--if-present", operation], root) and passed
                    )
    return passed


def external_checks(files: list[Path], root: Path, strict: bool) -> bool:
    """Run external checks and retain every independent failure."""
    config = Path(__file__).resolve().parents[2] / "pyproject.toml"
    passed = python_checks(files, root, config)
    passed = shell_checks(files, root) and passed
    passed = dashboard_checks(root, strict) and passed
    if strict:
        passed = check_materialization(root) and passed
    return passed
