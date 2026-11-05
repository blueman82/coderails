"""Bounded security-review applicability: strict summaries and immutable, current PR facts.

The prose assessment is a same-user claim. Object consistency cannot prove that a
reviewer inspected every consumer or that Markdown has no execution semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import quote

from . import review_na_context

BOUNDARY = "standalone_wiki_prose_v2"
MAX_INPUT_BYTES = 131072
MAX_COMMENT_CHARS = 65536
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
CONTROL_DIRS = frozenset(
    [
        ".git",
        ".claude",
        ".codex",
        ".agents",
        ".claude-plugin",
        ".codex-plugin",
        ".coderails",
        ".github",
        ".obsidian",
        "agents",
        "capabilities",
        "policy",
        "instructions",
    ]
)
CONTROL_NAMES = frozenset(
    [
        "agents.md",
        "claude.md",
        "skill.md",
        ".mcp.json",
        "hooks.json",
        "plugin.json",
        "marketplace.json",
        "config.schema.json",
        "workflow.config.yaml",
        "workflow.config.yml",
        "workflow.config.json",
        "workflow.config.toml",
    ]
)
PLUGINS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")


def _object(value: object, fields: set[str]) -> dict[str, Any]:
    """Require exactly the documented object fields."""
    if not isinstance(value, dict) or set(cast(dict[str, Any], value)) != fields:
        raise ValueError("N/A object fields invalid")
    return cast(dict[str, Any], value)


def _text(value: object) -> bool:
    """Nonempty explanatory text; its meaning remains the reviewer's responsibility."""
    return isinstance(value, str) and bool(value.strip())


def _oid(value: object) -> bool:
    """A full lowercase Git object identifier."""
    return isinstance(value, str) and OID.fullmatch(value) is not None


def _path(value: object) -> str:
    """Require one unambiguous relative Git path, never a filesystem traversal."""
    if (
        not isinstance(value, str)
        or "\\" in value
        or any(part.casefold() in ("", ".", "..", ".git") for part in value.split("/"))
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise ValueError("N/A path invalid")
    return value


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of silently taking the last value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate N/A JSON key")
        result[key] = value
    return result


def summary(text: str, name: str) -> dict[str, Any]:
    """Parse the only publishable N/A summary, for security-review alone."""
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("N/A summary exceeds input byte limit")
    match = re.fullmatch(r"\s*## Not applicable\r?\n\s*```json\r?\n(.*?)\r?\n```\s*", text, re.S)
    if name != "security-review" or match is None:
        raise ValueError("N/A requires the exact security-review summary")
    scope = json.loads(match[1], object_pairs_hook=_unique)
    validate_schema(scope)
    return cast(dict[str, Any], scope)


def validate_schema(value: object) -> None:
    """Validate the complete scope shape without Git imports or a policy import cycle."""
    scope = _object(value, {"boundary", "binding", "repository_purpose", "consumer_scope"})
    if scope["boundary"] != BOUNDARY or not _text(scope["repository_purpose"]):
        raise ValueError("N/A boundary or purpose invalid")
    binding = _object(
        scope["binding"],
        {
            "repository",
            "pr",
            "base_ref",
            "base_sha",
            "merge_base_sha",
            "head_sha",
            "inventory_sha256",
            "context_inventory_sha256",
        },
    )
    if (
        not isinstance(binding["repository"], str)
        or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", binding["repository"]) is None
        or type(binding["pr"]) is not int
        or binding["pr"] < 1
        or not _text(binding["base_ref"])
        or not all(_oid(binding[field]) for field in ("base_sha", "merge_base_sha", "head_sha"))
        or any(
            not isinstance(binding[field], str) or re.fullmatch(r"[0-9a-f]{64}", binding[field]) is None
            for field in ("inventory_sha256", "context_inventory_sha256")
        )
    ):
        raise ValueError("N/A binding invalid")
    consumers = _object(scope["consumer_scope"], {"complete", "references", "assessment", "unresolved"})
    if (
        consumers["complete"] is not True
        or consumers["unresolved"] != []
        or not isinstance(consumers["references"], list)
        or not _text(consumers["assessment"])
    ):
        raise ValueError("N/A consumer scope incomplete")
    paths: set[str] = set()
    for raw in cast(list[object], consumers["references"]):
        ref = _object(raw, {"paths", "base_change_assessment", "assessment"})
        if (
            not isinstance(ref["paths"], list)
            or not ref["paths"]
            or not _text(ref["assessment"])
            or (ref["base_change_assessment"] is not None and not _text(ref["base_change_assessment"]))
        ):
            raise ValueError("N/A consumer group invalid")
        for value in cast(list[object], ref["paths"]):
            path = unicodedata.normalize("NFC", _path(value)).casefold()
            if path in paths:
                raise ValueError("N/A consumer path duplicate or ambiguous")
            paths.add(path)


def inventory(raw: str) -> list[dict[str, Any]]:
    """Parse every raw-z field without dropping endpoint modes or accepting truncated rows."""
    if not raw or not raw.endswith("\0"):
        raise ValueError("N/A inventory empty or incomplete")
    tokens, index = raw.split("\0")[:-1], 0
    rows: list[dict[str, Any]] = []
    while index < len(tokens):
        match = re.fullmatch(r":([0-7]{6}) ([0-7]{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z][0-9]*)", tokens[index])
        if match is None or not _oid(match[3]) or not _oid(match[4]):
            raise ValueError("N/A inventory malformed")
        old_mode, new_mode, old_blob, new_blob, status = match.groups()
        count = 2 if status.startswith(("R", "C")) else 1
        paths = tokens[index + 1 : index + count + 1]
        if len(paths) != count:
            raise ValueError("N/A inventory truncated")
        for path in paths:
            _path(path)
        rename = re.fullmatch(r"R[0-9]{1,3}", status) is not None and int(status[1:]) <= 100
        if status not in ("A", "M", "D") and not rename:
            raise ValueError("N/A inventory status ineligible")
        old = None if status == "A" else {"path": paths[0], "mode": old_mode, "blob": old_blob}
        new = None if status == "D" else {"path": paths[-1], "mode": new_mode, "blob": new_blob}
        if (status == "A" and (old_mode != "000000" or set(old_blob) != {"0"})) or (
            status == "D" and (new_mode != "000000" or set(new_blob) != {"0"})
        ):
            raise ValueError("N/A inventory absent endpoint invalid")
        rows.append({"status": "R" if status.startswith("R") else status, "old": old, "new": new})
        index += count + 1
    return sorted(
        rows,
        key=lambda row: (
            row["old"]["path"] if row["old"] else "",
            row["new"]["path"] if row["new"] else "",
            row["status"],
        ),
    )


def _trees(sha: str) -> dict[str, dict[str, str]]:
    """Read exact immutable entries, including directories, without following filesystem links."""
    from . import git_common as git

    raw = git.run("git", "--no-replace-objects", "ls-tree", "-r", "-t", "-z", "--full-tree", sha, check=True).stdout
    if raw and not raw.endswith("\0"):
        raise ValueError("N/A tree incomplete")
    entries: dict[str, dict[str, str]] = {}
    for token in raw.split("\0")[:-1]:
        metadata, separator, path = token.partition("\t")
        fields = metadata.split(" ")
        if not separator or len(fields) != 3 or not _oid(fields[2]) or path in entries:
            raise ValueError("N/A tree malformed")
        entries[path] = dict(zip(("mode", "type", "blob"), fields))
    return entries


def _eligible(rows: list[dict[str, Any]]) -> None:
    """Only ordinary prose, and only hooks/commands collisions with the shipped security policy."""
    from . import manifest_policy, review_passes

    policy = review_passes.load_policy()
    security = [pattern for rule in policy["rules"] if rule["pass"] == "security-review" for pattern in rule["paths"]]
    for row in rows:
        for endpoint in (row["old"], row["new"]):
            if endpoint is None:
                continue
            path = endpoint["path"]
            parts = path.lower().split("/")
            if (
                endpoint["mode"] != "100644"
                or not path.lower().endswith(".md")
                or parts[-1] in CONTROL_NAMES
                or any(part in CONTROL_DIRS for part in parts[:-1])
            ):
                raise ValueError("N/A page mode, type or control path ineligible: " + path)
            for pattern in security:
                if pattern not in ("hooks/**", "commands/**") and manifest_policy.matches(path, [pattern]):
                    raise ValueError("N/A security policy collision ineligible: " + path)


def _resolve(number: str, head: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve current remote identity and read each unique immutable tree one time."""
    from . import git_common as git

    if re.fullmatch(r"[1-9][0-9]*", number) is None:
        raise ValueError("pr_number_invalid")
    repository = git.repo()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ValueError("N/A repository unresolved")
    reply = git.run(
        "gh",
        "api",
        f"repos/{repository}/pulls/{number}",
        "--jq",
        "{repository:.base.repo.full_name,head_sha:.head.sha,base_ref:.base.ref}",
        check=True,
    )
    pr = _object(json.loads(reply.stdout, object_pairs_hook=_unique), {"repository", "head_sha", "base_ref"})
    if pr["repository"] != repository or not _oid(pr["head_sha"]) or not _text(pr["base_ref"]):
        raise ValueError("N/A remote PR facts invalid")
    if head and pr["head_sha"] != head:
        raise ValueError("stale: N/A PR head moved")
    head = pr["head_sha"]
    base = git.output(
        "gh",
        "api",
        f"repos/{repository}/git/ref/heads/{quote(pr['base_ref'], safe='')}",
        "--jq",
        ".object.sha",
        check=True,
    )
    if not _oid(base):
        raise ValueError("N/A live base unresolved")
    for sha in (base, head):
        if git.run("git", "--no-replace-objects", "cat-file", "-e", sha + "^{commit}").returncode:
            git.run("git", "fetch", "--no-tags", "origin", sha, check=True)
        git.run("git", "--no-replace-objects", "cat-file", "-e", sha + "^{commit}", check=True)
    bases = git.output("git", "--no-replace-objects", "merge-base", "--all", base, head, check=True).splitlines()
    if len(bases) != 1 or not _oid(bases[0]):
        raise ValueError("N/A unique merge base unavailable")
    merge_base = bases[0]
    binding: dict[str, Any] = {
        "repository": repository,
        "pr": int(number),
        "base_ref": pr["base_ref"],
        "base_sha": base,
        "merge_base_sha": merge_base,
        "head_sha": head,
    }
    unique = {sha: _trees(sha) for sha in {merge_base, base, head}}
    trees = {name: unique[binding[name + "_sha"]] for name in ("merge_base", "base", "head")}
    if any(path in tree for tree in trees.values() for path in PLUGINS):
        raise ValueError("N/A command plugin repository ineligible")
    return binding, trees


def _facts(number: str, head: str = "") -> dict[str, Any]:
    """Complete current facts shared by preparation and every live N/A check."""
    from . import git_common as git

    binding, trees = _resolve(number, head)
    raw = git.run(
        "git",
        "--no-replace-objects",
        "diff",
        "--raw",
        "-z",
        "-M",
        "--no-abbrev",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--no-relative",
        binding["merge_base_sha"],
        binding["head_sha"],
        check=True,
    ).stdout
    rows = inventory(raw)
    _eligible(rows)
    objects: set[str] = set()
    for row in rows:
        for endpoint in (row["old"], row["new"]):
            if endpoint:
                path = endpoint["path"]
                if trees["base"].get(path) != trees["merge_base"].get(path):
                    raise ValueError("N/A affected entry changed on live base: " + path)
                objects.add(endpoint["blob"])
    context = review_na_context.inventory(trees, rows)
    for row in context:
        _path(row["path"])
    objects.update(entry["blob"] for row in context for name, entry in row.items() if name != "path" and entry)
    review_na_context.check_blobs(objects)
    for name, data in (("inventory_sha256", rows), ("context_inventory_sha256", context)):
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        binding[name] = hashlib.sha256(canonical).hexdigest()
    return {"boundary": BOUNDARY, "binding": binding, "inventory": rows, "context_inventory": context}


def prepare(number: str, head: str = "") -> dict[str, Any]:
    """Return complete context metadata without supplying inspection text."""
    facts = _facts(number, head)
    facts["context_inventory"] = review_na_context.compact(facts["context_inventory"])
    return facts


def preparation_json(number: str) -> str:
    """Bound compact metadata plus the CLI's final LF without truncating its context inventory."""
    text = json.dumps(prepare(number), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(text.encode("utf-8")) + 1 > MAX_INPUT_BYTES:
        raise ValueError("N/A preparation exceeds input byte limit")
    return text


def check_comment_bodies(*bodies: str) -> None:
    """Refuse oversized complete comment bodies before a write or reuse."""
    if any(len(body) > MAX_COMMENT_CHARS for body in bodies):
        raise ValueError("review comment exceeds 65536-character limit")


def validate(scope: object, number: str, head: str) -> None:
    """Require exact context coverage, actual immutable entries and base-change group semantics."""
    validate_schema(scope)
    data = cast(dict[str, Any], scope)
    facts = _facts(number, head)
    if data["binding"] != facts["binding"]:
        raise ValueError("stale: N/A binding differs from current PR facts")
    context = {row["path"]: row for row in facts["context_inventory"]}
    refs = data["consumer_scope"]["references"]
    covered = {path for ref in refs for path in ref["paths"]}
    if covered != set(context):
        raise ValueError("N/A context coverage differs from complete tracked inventory")
    for ref in refs:
        changed = {context[path]["base"] != context[path]["merge_base"] for path in ref["paths"]}
        if changed != {ref["base_change_assessment"] is not None}:
            raise ValueError("N/A consumer base change assessment invalid")


def validate_passes(passes: Sequence[dict[str, Any]], number: str, head: str) -> None:
    """Recheck every supplied N/A before a writer posts or reuses any comment."""
    for entry in passes:
        if entry["verdict"] == "not_applicable":
            if entry["name"] != "security-review" or entry["blocking"] is not False:
                raise ValueError("N/A pass name or blocking invalid")
            validate(entry.get("scope"), number, head)


def publication_violations(passes: Sequence[dict[str, Any]], number: str, head: str) -> list[dict[str, str]]:
    """Positively require known dispositions and live eligibility for all supplied N/A entries."""
    if any(item.get("verdict") not in ("pass", "fail", "not_applicable") for item in passes):
        return [{"code": "review_passes_malformed", "detail": "unknown disposition"}]
    try:
        validate_passes(passes, number, head)
    except Exception as error:  # noqa: BLE001 - unavailable or stale scope cannot waive inspection
        return [{"code": "required_review_not_applicable_invalid:security-review", "detail": str(error)}]
    return []
