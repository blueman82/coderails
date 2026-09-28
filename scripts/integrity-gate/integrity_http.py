"""Bounded GitHub REST transport for the root-owned mechanical attestor."""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

JsonObject = dict[str, Any]


class IntegrityError(Exception):
    """Report a safe diagnostic without disclosing credential-bearing argv."""


def log(message: str) -> None:
    """Emit one UTC daemon diagnostic to stderr."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {message}", file=sys.stderr)


def credentials(path: Path) -> dict[str, str]:
    """Read first occurrences of the two supported keys without evaluating them."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise IntegrityError(f"credentials file not found at {path}") from error
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key in {"GH_TOKEN", "MACHINE_USER"}:
            values.setdefault(key, value)
    missing = [key for key in ("GH_TOKEN", "MACHINE_USER") if not values.get(key)]
    if missing:
        raise IntegrityError("; ".join(f"missing a non-empty {key}=" for key in missing))
    return values


def repo_slug() -> str:
    """Resolve the explicitly configured repository or a GitHub origin."""
    configured = os.environ.get("INTEGRITY_GATE_REPO", "")
    if re.fullmatch(r"[^/]+/[^/]+", configured):
        return configured
    result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=False)
    match = re.search(r"github\.com[:/]([^/]+)/(.+)$", result.stdout.strip())
    if result.returncode or not match:
        raise IntegrityError("cannot resolve GitHub repository")
    return f"{match[1]}/{match[2].removesuffix('.git')}"


def object_value(value: object) -> JsonObject:
    """Validate JSON object shape at the transport boundary."""
    if not isinstance(value, dict):
        raise IntegrityError("expected JSON object")
    return cast(JsonObject, cast(object, value))


def array_value(value: object) -> list[JsonObject]:
    """Validate a JSON array of objects at the transport boundary."""
    if not isinstance(value, list):
        raise IntegrityError("expected JSON array")
    return [object_value(item) for item in cast(list[object], value)]


class Client:
    """Keep credentials private while preserving injectable curl transport."""

    def __init__(self, slug: str, token: str, machine_user: str) -> None:
        """Bind one repository and machine identity for this polling tick."""
        self.slug = slug
        self.token = token
        self.machine_user = machine_user
        self.curl = os.environ.get("INTEGRITY_GATE_CURL_BIN", "/usr/bin/curl")
        self.timeout = os.environ.get("INTEGRITY_GATE_WATCHDOG_TIMEOUT", "60")

    def request(self, url: str, arguments: list[str]) -> str:
        """Check transport status without allowing subprocess errors to leak tokens."""
        command = [
            self.curl,
            "-sS",
            "--max-time",
            self.timeout,
            *arguments,
            url,
            "-H",
            f"Authorization: Bearer {self.token}",
        ]
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        except OSError as error:
            raise IntegrityError("integrity transport unavailable") from error
        if result.returncode:
            raise IntegrityError("integrity transport failed")
        return result.stdout

    def get(self, target: str, accept: str = "application/vnd.github+json") -> str:
        """Require a successful HTTP response for repository or absolute endpoints."""
        url = target if target.startswith("https://") else f"https://api.github.com/repos/{self.slug}/{target}"
        response = self.request(url, ["-w", "\n%{http_code}", "-H", f"Accept: {accept}"])
        body, separator, code = response.rpartition("\n")
        if not separator or not re.fullmatch(r"2\d\d", code.strip()):
            raise IntegrityError(f"integrity fetch failed http={code.strip()}")
        return body

    def get_object(self, target: str) -> JsonObject:
        """Fetch and validate a JSON object."""
        try:
            return object_value(json.loads(self.get(target)))
        except ValueError as error:
            raise IntegrityError("invalid JSON response") from error

    def get_array(self, target: str) -> list[JsonObject]:
        """Fetch and validate a JSON array of objects."""
        try:
            return array_value(json.loads(self.get(target)))
        except ValueError as error:
            raise IntegrityError("invalid JSON response") from error

    def comments(self, number: int) -> list[str]:
        """Follow GitHub comment pagination while checking each page's HTTP status."""
        url = f"https://api.github.com/repos/{self.slug}/issues/{number}/comments?per_page=100"
        bodies: list[str] = []
        seen: set[str] = set()
        while url:
            if url in seen or not url.startswith("https://api.github.com/"):
                raise IntegrityError("invalid comment pagination")
            seen.add(url)
            with tempfile.NamedTemporaryFile() as headers:
                body = self.request(url, ["-D", headers.name, "-H", "Accept: application/vnd.github+json"])
                lines = Path(headers.name).read_text().splitlines()
            statuses = [line.split()[1] for line in lines if line.startswith("HTTP/") and len(line.split()) >= 2]
            if not statuses or not re.fullmatch(r"2\d\d", statuses[-1]):
                raise IntegrityError("comment fetch failed")
            try:
                for item in array_value(json.loads(body)):
                    if not isinstance(item.get("body"), str):
                        raise IntegrityError("invalid comment body")
                    bodies.append(item["body"])
            except ValueError as error:
                raise IntegrityError("invalid comment JSON") from error
            links = " ".join(line for line in lines if line.lower().startswith("link:"))
            match = re.search(r'<([^>]+)>; rel="next"', links)
            url = match[1] if match else ""
        return bodies

    def post_status(self, sha: str, state: str, description: str) -> None:
        """Verify the live token identity before every commit-status mutation."""
        actual = self.get_object("https://api.github.com/user").get("login", "")
        if actual != self.machine_user:
            raise IntegrityError(f"integrity identity mismatch expected={self.machine_user} actual={actual}")
        body = json.dumps({"state": state, "context": "integrity-review", "description": description})
        code = self.request(
            f"https://api.github.com/repos/{self.slug}/statuses/{sha}",
            [
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "-X",
                "POST",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                "content-type: application/json",
                "-d",
                body,
            ],
        )
        if not re.fullmatch(r"2\d\d", code.strip()):
            raise IntegrityError("integrity status post failed")
