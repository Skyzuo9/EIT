#!/usr/bin/env python3
"""Download a pinned robot SourceRelease and install it only after SHA-256 verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class SourceFetchError(ValueError):
    """The pinned source cannot be downloaded or verified safely."""


def install_release(
    manifest_path: Path,
    model_id: str,
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    manifest = _read_manifest(manifest_path)
    releases = manifest.get("releases")
    if not isinstance(releases, Mapping) or not isinstance(releases.get(model_id), Mapping):
        raise SourceFetchError(f"未知机器人 SourceRelease: {model_id}")
    spec = releases[model_id]
    archive = _text(spec, "archive")
    expected_digest = _digest(spec, "archive_sha256")
    download_url = _text(spec, "download_url")
    parsed = urllib.parse.urlparse(download_url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "codeload.github.com"}:
        raise SourceFetchError("download_url 必须是 GitHub HTTPS 地址")
    resolved_root = Path(source_root or _resolve_source_root(manifest)).expanduser().resolve()
    destination = (resolved_root / archive).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as error:
        raise SourceFetchError("archive 不能逃逸 source_root") from error

    if destination.is_file():
        actual = _sha256(destination)
        if actual != expected_digest:
            raise SourceFetchError(f"目标已存在但摘要漂移: {destination}")
        return _receipt(model_id, destination, expected_digest, download_url, installed=False)
    if destination.exists():
        raise SourceFetchError(f"目标存在但不是文件: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".part",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            request = urllib.request.Request(
                download_url,
                headers={"User-Agent": "unilab-source-release-fetch/1"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                if response.status != 200:
                    raise SourceFetchError(f"GitHub 下载返回 HTTP {response.status}")
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
        actual = _sha256(temporary)
        if actual != expected_digest:
            raise SourceFetchError(
                f"下载摘要不一致: {actual} != {expected_digest}"
            )
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return _receipt(model_id, destination, expected_digest, download_url, installed=True)


def _receipt(
    model_id: str,
    destination: Path,
    digest: str,
    download_url: str,
    *,
    installed: bool,
) -> dict[str, Any]:
    return {
        "schema": "lab.robot_source_fetch_receipt/v0",
        "model_id": model_id,
        "path": str(destination),
        "sha256": digest,
        "download_url": download_url,
        "installed": installed,
        "verified": True,
    }


def _read_manifest(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceFetchError(f"SourceRelease manifest 不可读: {error}") from error
    if not isinstance(value, Mapping) or value.get("schema") != "lab.robot_source_releases/v0":
        raise SourceFetchError("SourceRelease manifest schema 无效")
    return value


def _resolve_source_root(manifest: Mapping[str, Any]) -> Path:
    source = manifest.get("source_root")
    if not isinstance(source, Mapping):
        raise SourceFetchError("SourceRelease manifest 缺少 source_root")
    environment = _text(source, "environment")
    configured = os.environ.get(environment)
    if configured:
        return Path(configured)
    return Path.home() / _text(source, "default_home_relative")


def _text(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SourceFetchError(f"{field} 必须是非空文本")
    return value.strip()


def _digest(mapping: Mapping[str, Any], field: str) -> str:
    value = _text(mapping, field).lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SourceFetchError(f"{field} 必须是 SHA-256")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_id")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "robot-source-releases.json",
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    try:
        receipt = install_release(
            args.manifest,
            args.model_id,
            source_root=args.source_root,
        )
    except SourceFetchError as error:
        sys.stderr.write(f"SourceRelease fetch rejected: {error}\n")
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
