#!/usr/bin/env python3
"""Verify the EIT reproduction manifest against the checked-out tree."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "repro" / "manifest.lock.json"


def _git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []

    for item in manifest["submodules"]:
        path = REPO_ROOT / item["path"]
        actual = _git_head(path) if path.exists() else "missing"
        if actual != item["commit"]:
            failures.append(
                f"submodule {item['path']}: expected {item['commit']}, got {actual}"
            )

    for relative, expected in manifest["artifacts"].items():
        path = REPO_ROOT / relative
        actual = _sha256(path) if path.is_file() else "missing"
        if actual != expected:
            failures.append(f"artifact {relative}: expected {expected}, got {actual}")

    qualification = manifest["qualification"]
    expected_boundary = {
        "decision": "unknown",
        "effect": "none",
        "mode": "shadow-only",
        "hardware_qualified": False,
        "publication_eligible": False,
    }
    if qualification != expected_boundary:
        failures.append("qualification boundary was upgraded or changed")

    if failures:
        print("EIT reproduction manifest FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("EIT reproduction manifest OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
