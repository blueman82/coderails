"""Raw, bounded proposed-source objects in a root-selected private Git context."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import unicodedata
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from scripts.lib import manifest_policy
from scripts.sandbox.containment import SECRET_PATTERNS

MAX_ENTRIES = 10_000
MAX_DEPTH = 64
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
Entry = tuple[str, str]


def git(*arguments: str, data: bytes | None = None, allow_absent: bool = False) -> bytes:
    """Run trusted Git without inherited repository selectors or executable configuration."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1")
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *arguments],
        input=data,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )
    if result.returncode and not (allow_absent and result.returncode == 1):
        raise ValueError(f"driver_capture_git: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def store_git(store: Path, *arguments: str, data: bytes | None = None) -> bytes:
    """Address only the root-owned object database."""
    return git("--git-dir", str(store), *arguments, data=data)


def digest(path: Path) -> str:
    """Hash one regular control artifact without following a final symlink."""
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("driver_capture_control_type")
        return hashlib.sha256(stream.read()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read a bounded regular root control record."""
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError("driver_capture_control_invalid")
    value: object = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("driver_capture_control_invalid")
    return cast(dict[str, Any], value)


def write_once(path: Path, value: dict[str, Any]) -> None:
    """Publish an exclusive immutable record; torn records fail on reuse."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > 1024 * 1024:
        raise ValueError("driver_capture_control_bound")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def valid_path(path: str) -> None:
    """Reject paths whose filesystem spelling cannot safely represent a proposal."""
    path.encode("utf-8", errors="strict")
    parts = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts)
        or unicodedata.normalize("NFC", path) != path
        or len(parts) > MAX_DEPTH
    ):
        raise ValueError("driver_capture_path_invalid")


def tree_entries(store: Path, tree: str) -> dict[str, Entry]:
    """Read baseline or captured entries from immutable objects, never a worker index."""
    entries: dict[str, Entry] = {}
    folded: dict[str, str] = {}
    for row in store_git(store, "ls-tree", "-r", "-z", tree).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, _kind, oid = metadata.decode().split()
        path = raw_path.decode("utf-8", errors="strict")
        valid_path(path)
        parts = path.split("/")
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            if prefix.casefold() in folded and folded[prefix.casefold()] != prefix:
                raise ValueError("driver_capture_case_collision")
            folded[prefix.casefold()] = prefix
        entries[path] = mode, oid
    return entries


def blob(store: Path, oid: str) -> bytes:
    """Read raw object bytes without attributes, textconv or checkout filters."""
    data = store_git(store, "cat-file", "blob", oid)
    identity = store_git(store, "hash-object", "--no-filters", "--stdin", data=data).decode().strip()
    if identity != oid:
        raise ValueError("driver_capture_object_changed")
    return data


def directory(root: int, parts: list[str], *, create: bool) -> int:
    """Pin every parent directory and refuse symlink traversal."""
    current = os.dup(root)
    try:
        for part in parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, dir_fd=current)
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def seed(root: Path, store: Path, entries: dict[str, Entry]) -> None:
    """Materialize a trusted baseline into a new clone without invoking its Git configuration."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for path, (mode, oid) in entries.items():
            parent = directory(descriptor, path.split("/")[:-1], create=True)
            try:
                name = path.split("/")[-1]
                if mode == "120000":
                    os.symlink(blob(store, oid).decode(), name, dir_fd=parent)
                elif mode in {"100644", "100755"}:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    with os.fdopen(fd, "wb") as target:
                        target.write(blob(store, oid))
                        os.fchmod(target.fileno(), 0o755 if mode == "100755" else 0o644)
                else:
                    raise ValueError("driver_capture_baseline_type")
            finally:
                os.close(parent)
    finally:
        os.close(descriptor)


def read_regular(parent: int, name: str, before: os.stat_result) -> bytes:
    """Read a bounded pinned regular file and reject observed replacement races."""
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("driver_capture_type_race")
        if opened.st_nlink != 1:
            raise ValueError("driver_capture_hardlink")
        data = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("driver_capture_bound_file")
        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("driver_capture_changed_during_read")
        return data


def raw_entries(
    root: Path,
    store: Path,
    baseline: dict[str, Entry],
    *,
    ignore_baseline: str | None = None,
    excluded: list[str] | None = None,
) -> dict[str, Entry]:
    """Freeze bounded no-follow filesystem observations, not a coherent terminal snapshot."""
    entries: dict[str, Entry] = {}
    spelling: dict[str, str] = {}
    budget = [0, 0]

    def walk(parent: int, prefix: str) -> None:
        """Walk."""
        with os.scandir(parent) as children:
            names: list[str] = []
            for child in children:
                budget[0] += 1
                if budget[0] > MAX_ENTRIES:
                    raise ValueError("driver_capture_bound_entries")
                names.append(child.name)
        metadata: dict[str, os.stat_result] = {}
        candidates: list[str] = []
        for name in sorted(names):
            if not prefix and name == ".git":
                continue
            path = prefix + name
            valid_path(path)
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            metadata[name] = before
            baseline_parent = any(item.startswith(path + "/") for item in baseline)
            baseline_path = path in baseline or (baseline_parent and stat.S_ISDIR(before.st_mode))
            if not baseline_path and any(
                part.casefold() in {".codex", ".claude", ".mcp.json"} for part in path.split("/")
            ):
                raise ValueError("driver_capture_control_path")
            if not baseline_path:
                candidates.append(path + ("/" if stat.S_ISDIR(before.st_mode) else ""))
        ignored: set[str] = ignored_paths(store, ignore_baseline, candidates) if ignore_baseline else set()
        for name, before in metadata.items():
            path = prefix + name
            folded = path.casefold()
            if folded in spelling and spelling[folded] != path:
                raise ValueError("driver_capture_case_collision")
            spelling[folded] = path
            if stat.S_ISDIR(before.st_mode):
                child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    opened = os.fstat(child_fd)
                    if (before.st_ino, before.st_dev) != (opened.st_ino, opened.st_dev):
                        raise ValueError("driver_capture_directory_race")
                    if path + "/" in ignored:
                        if excluded is not None:
                            excluded.append(path + "/")
                    else:
                        walk(child_fd, path + "/")
                finally:
                    os.close(child_fd)
                continue
            if stat.S_ISLNK(before.st_mode):
                data = os.readlink(name, dir_fd=parent).encode()
                mode = "120000"
            elif stat.S_ISREG(before.st_mode):
                if path in ignored:
                    if excluded is not None:
                        excluded.append(path)
                    continue
                data = read_regular(parent, name, before)
                mode = "100755" if before.st_mode & 0o111 else "100644"
            else:
                raise ValueError("driver_capture_special_type")
            budget[1] += len(data)
            if budget[1] > MAX_TOTAL_BYTES:
                raise ValueError("driver_capture_bound_total")
            oid = store_git(store, "hash-object", "-w", "--no-filters", "--stdin", data=data).decode().strip()
            if mode == "120000" and baseline.get(path) != (mode, oid):
                raise ValueError("driver_capture_symlink_type")
            entries[path] = mode, oid

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(descriptor, "")
    finally:
        os.close(descriptor)
    return entries


def make_tree(store: Path, entries: dict[str, Entry]) -> str:
    """Build explicit Git trees from captured blob identities; no worker Git is consulted."""
    children: dict[str, dict[str, Entry]] = {}
    rows: list[bytes] = []
    for path, (mode, oid) in entries.items():
        name, separator, rest = path.partition("/")
        if separator:
            children.setdefault(name, {})[rest] = mode, oid
        else:
            rows.append(f"{mode} blob {oid}\t{name}".encode() + b"\0")
    for name, subtree in children.items():
        if name in entries:
            raise ValueError("driver_capture_directory_file_type")
        rows.append(f"040000 tree {make_tree(store, subtree)}\t{name}".encode() + b"\0")
    return store_git(store, "mktree", "-z", data=b"".join(rows)).decode().strip()


def freeze(
    clone: Path,
    store: Path,
    baseline: str,
    manifest: list[str],
    write_scope: list[str],
    credential: str,
) -> dict[str, Any]:
    """Validate a fixed source proposal before root writes any destination bytes."""
    original = tree_entries(store, baseline)
    excluded: list[str] = []
    entries = raw_entries(clone, store, original, ignore_baseline=baseline, excluded=excluded)
    tree = make_tree(store, entries)
    raw = store_git(
        store, "diff", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", baseline + "^{tree}", tree, "--"
    ).decode("utf-8")
    changes = manifest_policy.parse_raw_z(raw)
    for scope in (manifest, write_scope):
        verdict = manifest_policy.check(changes, {}, scope)
        if changes and (not scope or not verdict["ok"]):
            raise ValueError("driver_capture_scope_refused")
    for path, (mode, oid) in entries.items():
        if original.get(path) == (mode, oid):
            continue
        data = blob(store, oid)
        if credential and credential.encode() in data:
            raise ValueError("driver_capture_secret_refused")
        if any(re.search(pattern.pattern.encode(), data) for _label, pattern in SECRET_PATTERNS):
            raise ValueError("driver_capture_secret_refused")
    return {
        "tree": tree,
        "baseline": baseline,
        "excluded": sorted(excluded),
        "eligibility": "trusted-H-ignore-v1",
        "entries_sha256": hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def ignored_paths(store: Path, baseline: str, paths: list[str]) -> set[str]:
    """Classify only new paths using immutable H ignore files in root's private context."""
    if not paths:
        return set()
    worktree = store.parent / "eligibility"
    marker = store.parent / "eligibility.json"
    if not marker.exists():
        worktree.mkdir()
        ignores = {
            path: entry for path, entry in tree_entries(store, baseline).items() if path.split("/")[-1] == ".gitignore"
        }
        if any(mode not in {"100644", "100755"} for mode, _oid in ignores.values()):
            raise ValueError("driver_capture_ignore_type")
        seed(worktree, store, ignores)
        (store / "info" / "exclude").write_bytes(b"")
        write_once(marker, {"baseline": baseline})
    if read_json(marker) != {"baseline": baseline}:
        raise ValueError("driver_capture_ignore_baseline_changed")
    output = git(
        "--git-dir",
        str(store),
        "--work-tree",
        str(worktree),
        "-c",
        "core.bare=false",
        "-c",
        "core.excludesFile=/dev/null",
        "check-ignore",
        "--no-index",
        "-z",
        "--stdin",
        data=b"".join(path.encode() + b"\0" for path in paths),
        allow_absent=True,
    )
    return {path.decode("utf-8") for path in output.split(b"\0") if path}
