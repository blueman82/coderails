"""Materialize only fixed private objects into an exclusively reserved pristine destination."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

from scripts.sandbox import source_capture as capture


def apply(destination: Path, store: Path, baseline: str, tree: str) -> None:
    """Leave HEAD/index untouched; any failure requires quarantine, never automatic rollback."""
    original = capture.tree_entries(store, baseline)
    proposed = capture.tree_entries(store, tree)
    if capture.raw_entries(destination, store, original) != original:
        raise ValueError("driver_destination_source_drift")
    descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for path in sorted(original.keys() | proposed.keys()):
            if original.get(path) == proposed.get(path):
                continue
            parent = capture.directory(descriptor, path.split("/")[:-1], create=path in proposed)
            try:
                name = path.split("/")[-1]
                try:
                    found = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    found = None
                if path in original:
                    if found is None or not stat.S_ISREG(found.st_mode) or found.st_nlink != 1:
                        raise ValueError("driver_destination_path_drift")
                    current = capture.read_regular(parent, name, found)
                    oid = (
                        capture.store_git(store, "hash-object", "--no-filters", "--stdin", data=current)
                        .decode()
                        .strip()
                    )
                    if oid != original[path][1]:
                        raise ValueError("driver_destination_content_drift")
                elif found is not None:
                    raise ValueError("driver_destination_untracked_drift")
                if path not in proposed:
                    os.unlink(name, dir_fd=parent)
                    continue
                mode, oid = proposed[path]
                if mode not in {"100644", "100755"}:
                    raise ValueError("driver_destination_special_type")
                temporary = ".coderails-transfer-" + uuid.uuid4().hex
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                with os.fdopen(fd, "wb") as target:
                    target.write(capture.blob(store, oid))
                    os.fchmod(target.fileno(), 0o755 if mode == "100755" else 0o644)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                os.close(parent)
    finally:
        os.close(descriptor)
    if capture.raw_entries(destination, store, proposed) != proposed:
        raise ValueError("driver_destination_verification_failed")
