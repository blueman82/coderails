"""Pure integrity installation checks and explicit privileged launchd operations."""

from __future__ import annotations

import contextlib
import difflib
import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from integrity_http import IntegrityError, credentials, object_value

RUNTIME_FILES = ("integrity_gate_runner.py", "integrity_http.py", "integrity_policy.py")
LABEL = "com.coderails.integrity-gate"


def check_tools() -> None:
    """Name every required executable missing from the owner's environment."""
    missing = [name for name in ("gh", "curl") if not shutil.which(name)]
    if missing:
        raise IntegrityError("preflight: missing required tools: " + ", ".join(missing))
    if not Path("/usr/bin/python3").is_file():
        raise IntegrityError("preflight: /usr/bin/python3 is required for the root-owned daemon")


def check_machine_user_collaborator(login: str, gh_bin: str = "gh") -> None:
    """Require the stored or supplied machine user to resolve as a collaborator."""
    if not login:
        raise IntegrityError("preflight: no machine-user login provided")
    result = subprocess.run(
        [gh_bin, "api", f"repos/{{owner}}/{{repo}}/collaborators/{login}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise IntegrityError(f'preflight: machine user "{login}" is not resolvable as a collaborator on this repo')


def resolve_repo_slug(gh_bin: str = "gh") -> str:
    """Resolve a nonempty owner/repo from the caller's checked-out repository."""
    result = subprocess.run(
        [gh_bin, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    slug = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[^/]+/[^/]+", slug):
        raise IntegrityError("preflight: could not resolve repo slug — run install.py inside the target checkout")
    return slug


def render_plist(template: Path, runner: Path, creds: Path, slug: str) -> bytes:
    """Escape literal paths and bind an absolute system Python interpreter."""
    if not re.fullmatch(r"[^/]+/[^/]+", slug):
        raise ValueError("repo slug must be owner/repo")
    text = template.read_text()
    for key, value in {"RUNNER_PATH": str(runner), "CREDS_PATH": str(creds), "REPO": slug}.items():
        text = text.replace(f"__INTEGRITY_GATE_{key}__", escape(value))
    text = text.replace("<array>", "<array>\n    <string>/usr/bin/python3</string>", 1)
    plistlib.loads(text.encode())
    return text.encode()


def classify_mode(text: str) -> str:
    """Underclaim server enforcement on any malformed or empty rules response."""
    try:
        value: object = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, list) and value:
        return "MODE: enforced"
    return "MODE: audit (server leg absent) — verdict unforgeable, merge gate local-only and bypassable"


def diff_before_promote(source: Path, installed: Path, label: str) -> bool:
    """Display source changes before allowing their promotion to a root-owned copy."""
    if not installed.is_file():
        print(f"{label}: no installed copy yet at {installed} — this is a first install.")
        return True
    if source.read_bytes() == installed.read_bytes():
        print(f"{label}: repo copy matches installed copy — no change.")
        return True
    print(f"{label}: repo copy DIFFERS from installed copy at {installed}:")
    print(
        "".join(
            difflib.unified_diff(
                installed.read_text().splitlines(True),
                source.read_text().splitlines(True),
                fromfile=str(installed),
                tofile=str(source),
            )
        ),
        end="",
    )
    return False


def same_file(left: Path, right: Path) -> bool:
    """Compare device and inode, including hardlinks, without treating absence as error."""
    try:
        return left.samefile(right)
    except OSError:
        return False


def other_instance_labels(destination: Path, pattern: str) -> list[str]:
    """Discover other daemon labels sharing the root-owned runner and credentials."""
    labels: list[str] = []
    for name in glob.glob(pattern):
        path = Path(name)
        if not path.is_file() or same_file(path, destination):
            continue
        try:
            value = object_value(plistlib.loads(path.read_bytes()))
            label = value.get("Label")
            if isinstance(label, str) and label:
                labels.append(label)
        except (OSError, ValueError, IntegrityError, plistlib.InvalidFileException):
            continue
    return labels


def sudo(arguments: list[str], *, required: bool = True, content: bytes | None = None) -> bool:
    """Run a visible owner-authorized privileged action with optional stdin data."""
    result = subprocess.run(["sudo", *arguments], input=content, stdout=subprocess.DEVNULL, check=False)
    if required and result.returncode:
        raise IntegrityError("privileged operation failed: " + " ".join(arguments[:2]))
    return result.returncode == 0


def activate(destination: Path) -> None:
    """Reap per-user ghosts, bootstrap system launchd and verify the final domains."""
    uid = None
    with contextlib.suppress(OSError):
        uid = Path("/dev/console").stat().st_uid
    domains = [f"gui/{uid}", f"user/{uid}"] if uid is not None else []
    for domain in domains:
        if sudo(["launchctl", "print", f"{domain}/{LABEL}"], required=False):
            print(f"WARNING: reaping stale per-user ghost in {domain}")
            sudo(["launchctl", "bootout", f"{domain}/{LABEL}"], required=False)
    sudo(["launchctl", "bootout", f"system/{LABEL}"], required=False)
    sudo(["launchctl", "bootstrap", "system", str(destination)])
    if not sudo(["launchctl", "print", f"system/{LABEL}"], required=False):
        raise IntegrityError(f"INSTALL FAILED — system/{LABEL} is not registered after bootstrap")
    for domain in domains:
        if sudo(["launchctl", "print", f"{domain}/{LABEL}"], required=False):
            raise IntegrityError(f"INSTALL FAILED — a per-user ghost in {domain} survived the sweep")


def promote(source: Path, install_root: Path, creds: Path, destination: Path, rendered: bytes) -> None:
    """Install the entire root-owned runtime, credentials, plist and log rotation policy."""
    sudo(["mkdir", "-p", str(install_root)])
    for filename in RUNTIME_FILES:
        sudo(
            [
                "install",
                "-m",
                "0755" if filename == RUNTIME_FILES[0] else "0644",
                str(source / filename),
                str(install_root / filename),
            ]
        )
    target = install_root / "credentials"
    if same_file(creds, target):
        sudo(["chmod", "0600", str(target)])
    else:
        sudo(["install", "-m", "0600", str(creds), str(target)])
    sudo(["chown", "root:wheel", str(target)])
    sudo(["tee", str(destination)], content=rendered)
    sudo(
        [
            "install",
            "-m",
            "0644",
            str(source / "coderails-integrity-gate.conf"),
            "/etc/newsyslog.d/coderails-integrity-gate.conf",
        ]
    )
    activate(destination)


def preflight() -> tuple[Path, Path, Path, str]:
    """Validate root installation inputs without changing files or launchd state."""
    check_tools()
    root = Path(os.environ.get("TGI_INSTALL_ROOT", "/etc/coderails-integrity-gate"))
    destination = Path(os.environ.get("TGI_PLIST_DEST", f"/Library/LaunchDaemons/{LABEL}.plist"))
    creds = Path(os.environ.get("TGI_CREDS_SRC", str(root / "credentials")))
    values = credentials(creds)
    login = os.environ.get("TGI_MACHINE_USER", values["MACHINE_USER"])
    check_machine_user_collaborator(login)
    return root, destination, creds, resolve_repo_slug()
