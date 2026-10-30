#!/usr/bin/env python3
"""Generate both native hook registrations and the short hook and reason tables.

Usage: python3 scripts/gen_hooks.py [--check] [--root DIR]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import runpy
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {"claude": "hooks/hooks.json", "codex": "packages/codex/hooks/hooks.json"}
START = "<!-- hook-registry:start -->"
END = "<!-- hook-registry:end -->"
REASON_START = "<!-- hook-reasons:start -->"
REASON_END = "<!-- hook-reasons:end -->"
MODES = {"advisory", "block", "nudge", "observe", "silent"}
HOOK_NAME = {
    "claude": re.compile(r"^\"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/scripts/([a-z][a-z0-9_]*)\.py\"$"),
    "codex": re.compile(r"^\"\$\{PLUGIN_ROOT\}/hooks/scripts/([a-z][a-z0-9_]*)\.py\"$"),
}
CLAUDE_PYTHON = re.compile(r"^python3 \"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/scripts/([a-z][a-z0-9_]*)\.py\"$")


def _object(value: Any, label: str) -> dict[str, Any]:  # noqa: ANN401
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast("dict[str, Any]", value)


def _text(value: Any, label: str) -> str:  # noqa: ANN401
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _hook_name(command: Any, provider: str) -> str:  # noqa: ANN401
    text = _text(command, "hook command")
    match = HOOK_NAME[provider].fullmatch(text)
    if match is None and provider == "claude":
        match = CLAUDE_PYTHON.fullmatch(text)
    if not match:
        raise ValueError(f"unrecognised hook command: {command}")
    return match.group(1)


def load(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read and validate the shared controls, provider overlays, and reason messages."""
    registry = _object(json.loads((root / "hooks/registry.json").read_text()), "registry")
    messages = _object(json.loads((root / "hooks/messages.json").read_text()), "messages")
    if registry.get("schema_version") != 1 or messages.get("schema_version") != 1:
        raise ValueError("hook registry and messages require schema_version 1")
    controls = _object(registry.get("controls"), "controls")
    reasons = _object(messages.get("hooks"), "hook messages")
    overlay_paths = _object(registry.get("provider_overlays"), "provider overlays")
    protocols = _object(registry.get("protocols"), "provider protocols")
    if set(overlay_paths) != set(PROVIDERS) or not controls or set(controls) != set(reasons):
        raise ValueError("provider or hook message coverage differs from the registry")
    providers: dict[str, dict[str, Any]] = {}
    for provider, location in overlay_paths.items():
        path = _text(location, f"{provider} overlay")
        if not path.startswith("hooks/overlays/") or ".." in Path(path).parts:
            raise ValueError(f"{provider} has an invalid overlay path")
        providers[provider] = _object(json.loads((root / path).read_text()), f"{provider} overlay")
    registry["providers"] = providers
    if set(protocols) != set(PROVIDERS):
        raise ValueError("provider protocol coverage differs from the registry")
    for provider, protocol in protocols.items():
        _text(protocol, f"{provider} protocol")
    if messages.get("memory_source") != "scripts/lib/memory_reasons.py":
        raise ValueError("memory reasons must use the maintained source")
    _text(_object(messages.get("fallback"), "fallback").get("remediation"), "fallback remediation")
    aliases = _object(messages.get("aliases", {}), "aliases")
    if any(target not in controls for target in aliases.values()):
        raise ValueError("alias names an unknown control")

    sources: set[str] = set()
    seen: dict[str, set[str]] = {name: set() for name in controls}
    for provider, data in providers.items():
        registration = _object(data, f"{provider} registration")
        events = _object(registration.get("hooks"), f"{provider} events")
        if not events:
            raise ValueError(f"{provider} has no hook events")
        for event, groups in events.items():
            _text(event, "event")
            if not isinstance(groups, list) or not groups:
                raise ValueError(f"{provider}/{event} has no matcher groups")
            group_list = cast("list[object]", groups)
            for group in group_list:
                item = _object(group, "matcher group")
                hooks = item.get("hooks")
                if not isinstance(hooks, list) or not hooks:
                    raise ValueError(f"{provider}/{event} has no hooks")
                if "matcher" in item:
                    _text(item["matcher"], "matcher")
                hook_list = cast("list[object]", hooks)
                for hook in hook_list:
                    entry = _object(hook, "hook")
                    name = _hook_name(entry.get("command"), provider)
                    if name not in controls:
                        raise ValueError(f"{provider}/{event} names unknown hook {name}")
                    if entry.get("type") != "command":
                        raise ValueError(f"{provider}/{event}/{name} has an unsupported type")
                    if "timeout" in entry and (type(entry["timeout"]) is not int or entry["timeout"] < 1):
                        raise ValueError(f"{provider}/{event}/{name} has an invalid timeout")
                    source_root = "hooks/scripts" if provider == "claude" else "packages/codex/hooks/scripts"
                    source = f"{source_root}/{name}.py"
                    if not (root / source).is_file():
                        raise ValueError(f"registered hook source is missing: {source}")
                    sources.add(source)
                    seen[name].add(provider)
    for name, value in controls.items():
        control = _object(value, f"control {name}")
        if control.get("mode") not in MODES:
            raise ValueError(f"{name} has an invalid mode")
        if control.get("providers") != sorted(seen[name]) or not seen[name]:
            raise ValueError(f"{name} has missing or incorrect provider coverage")
        for key in ("category", "failure", "ceiling", "activation"):
            _text(control.get(key), f"{name}.{key}")
        message = _object(reasons[name], f"message {name}")
        if message.get("category") != control["category"]:
            raise ValueError(f"{name} has a missing or inconsistent category")
        _text(message.get("remediation"), f"{name}.remediation")
    emitted = _object(messages.get("reasons"), "emitted reasons")
    if not emitted:
        raise ValueError("the emitted reason catalog is empty")
    for code, value in emitted.items():
        _text(code, "emitted reason")
        entry = _object(value, f"reason {code}")
        _text(entry.get("remediation"), f"{code}.remediation")
        source = _text(entry.get("source"), f"{code}.source")
        provider_roots = ("hooks/scripts/", "packages/codex/hooks/scripts/")
        if not source.startswith(provider_roots) or ".." in Path(source).parts:
            raise ValueError(f"{code} has an invalid source")
        tree = ast.parse((root / source).read_text())
        literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
        if code not in literals:
            raise ValueError(f"{code} is not a literal emitted by {source}")
    for source in sources:
        missing = emitted_reasons(root / source) - set(emitted)
        if missing:
            raise ValueError(f"{source} has uncatalogued emitted reasons: {', '.join(sorted(missing))}")
    return registry, messages


def emitted_reasons(source: Path) -> set[str]:
    """Read static trace-call reasons, including module constants and conditional arms.

    Runtime-derived reasons retain the hook-level remediation; this is not data-flow analysis.
    """
    tree = ast.parse(source.read_text())
    constants = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    def texts(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name) and node.id in constants:
            return texts(constants[node.id])
        if isinstance(node, ast.IfExp):
            return texts(node.body) | texts(node.orelse)
        return set()

    return {
        code
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"append_row", "append_trace_row"}
        and len(node.args) > 2
        for code in texts(node.args[2])
    }


def splice(document: str, start: str, end: str, block: str) -> str:
    """Replace exactly one marked region, or refuse an absent or repeated marker."""
    if document.count(start) != 1 or document.count(end) != 1 or document.index(start) > document.index(end):
        raise ValueError(f"expected one ordered {start} region")
    head, rest = document.split(start, 1)
    return f"{head}{start}\n{block}\n{end}" + rest.split(end, 1)[1]


def hook_table(registry: dict[str, Any], messages: dict[str, Any]) -> str:
    """One current-source row per registered provider, event, matcher, and hook."""
    controls = registry["controls"]
    rows = [
        *(f"{provider.title()} protocol: {protocol}." for provider, protocol in registry["protocols"].items()),
        "",
        "| Provider | Event | Matcher | Hook | Options | Mode | Default | Category | Action | Failure | Limit |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for provider, data in registry["providers"].items():
        for event, groups in data["hooks"].items():
            for group in groups:
                matcher = str(group.get("matcher", "all"))
                for hook in group["hooks"]:
                    name = _hook_name(hook["command"], provider)
                    control = controls[name]
                    message = messages["hooks"][name]
                    options = ", ".join(
                        f"{key}={value}" for key, value in hook.items() if key not in {"type", "command"}
                    )
                    cells = (
                        provider,
                        event,
                        matcher,
                        f"`{name}.py`",
                        options or "-",
                        control["mode"],
                        control["activation"],
                        control["category"],
                        message["remediation"],
                        control["failure"],
                        control["ceiling"],
                    )
                    rows.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(rows)


def reason_table(root: Path, messages: dict[str, Any]) -> str:
    """Use the existing memory catalog as an input; never copy its entries into messages.json."""
    source = root / messages["memory_source"]
    memory = _object(runpy.run_path(str(source)).get("REASONS"), "memory reasons")
    rows = ["| Control | Category | Action |", "|---|---|---|"]
    for name, item in messages["hooks"].items():
        rows.append(f"| `{name}` | {item['category']} | {item['remediation']} |")
    rows += ["", "| Source | Emitted reason | Action |", "|---|---|---|"]
    for code, item in sorted(messages["reasons"].items()):
        rows.append(f"| `{item['source']}` | `{code}` | {item['remediation']} |")
    for code, action in sorted(memory.items()):
        safe_action = str(action).replace("|", "\\|")
        rows.append(f"| memory | `{code}` | {safe_action} |")
    return "\n".join(rows)


def outputs(root: Path, registry: dict[str, Any], messages: dict[str, Any]) -> dict[str, str]:
    """Return exact generated file bytes for both provider installs and marked docs."""
    rendered = {
        path: json.dumps(registry["providers"][provider], indent=2, ensure_ascii=False) + "\n"
        for provider, path in PROVIDERS.items()
    }
    rendered["packages/codex/hooks/messages.json"] = json.dumps(messages, indent=2, ensure_ascii=False) + "\n"
    table = hook_table(registry, messages)
    for path in ("AGENTS.md", "README.md"):
        rendered[path] = splice((root / path).read_text(), START, END, table)
    path = "docs/RUNBOOK.md"
    rendered[path] = splice((root / path).read_text(), REASON_START, REASON_END, reason_table(root, messages))
    return rendered


def main(argv: list[str] | None = None) -> int:
    """Write generated files, or check them without edits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="refuse stale generated files without writing")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root for a fixture or worktree")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        registry, messages = load(root)
        rendered = outputs(root, registry, messages)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as error:
        print(f"gen_hooks: {error}")
        return 2
    stale = [path for path, body in rendered.items() if not (root / path).exists() or (root / path).read_text() != body]
    if args.check:
        if stale:
            print("gen_hooks: stale generated files: " + ", ".join(stale))
            return 1
        return 0
    for path in stale:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered[path])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
