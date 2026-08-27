#!/usr/bin/env python3
"""为 P0 生成确定性的投料站输入清单、摘要和报告。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAD_SUFFIXES = {".sldasm", ".sldprt", ".x_t", ".step", ".stp"}


class InventoryError(RuntimeError):
    """输入边界不满足 P0 要求。"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_version() -> str | None:
    try:
        result = subprocess.run(
            ["git", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def build_inventory(source_root: Path, top_assembly: str) -> tuple[dict[str, Any], str]:
    root = source_root.resolve()
    if not root.is_dir():
        raise InventoryError(f"输入根目录不存在: {root}")
    top = (root / Path(top_assembly)).resolve()
    try:
        top.relative_to(root)
    except ValueError as error:
        raise InventoryError("顶层总装必须位于输入根目录内") from error
    if not top.is_file():
        raise InventoryError(f"顶层总装不存在: {top}")

    paths = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise InventoryError("输入根目录没有文件")

    entries: list[dict[str, Any]] = []
    suffix_counts: Counter[str] = Counter()
    digest_paths: dict[str, list[str]] = defaultdict(list)
    manifest_lines: list[str] = []
    total_bytes = 0
    for path in paths:
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        digest = sha256(path)
        suffix = path.suffix.lower() or "<none>"
        total_bytes += stat.st_size
        suffix_counts[suffix] += 1
        digest_paths[digest].append(relative)
        manifest_lines.append(f"{digest}  {relative}")
        entries.append(
            {
                "path": relative,
                "bytes": stat.st_size,
                "sha256": digest,
                "suffix": suffix,
                "mtime_ns_audit": stat.st_mtime_ns,
            }
        )

    manifest = "\n".join(manifest_lines) + "\n"
    manifest_digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    duplicates = [
        {"sha256": digest, "paths": values}
        for digest, values in sorted(digest_paths.items())
        if len(values) > 1
    ]
    cad_count = sum(count for suffix, count in suffix_counts.items() if suffix in CAD_SUFFIXES)
    inventory = {
        "schema": "lab.station_input_inventory/v0",
        "generated_at_audit": datetime.now(timezone.utc).isoformat(),
        "source_root_audit": str(root),
        "top_assembly": top.relative_to(root).as_posix(),
        "manifest_algorithm": "sha256(utf8(files.sha256))",
        "source_files_digest": manifest_digest,
        "file_count": len(entries),
        "cad_file_count": cad_count,
        "total_bytes": total_bytes,
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "duplicate_content_groups": duplicates,
        "files": entries,
        "qualification": "input-inventory-only",
        "not_verified": [
            "solidworks_reference_completeness",
            "occurrence_identity",
            "mate_semantics",
            "geometry_export",
            "collision",
            "execution",
        ],
    }
    return inventory, manifest


def write_outputs(
    output_dir: Path,
    inventory: dict[str, Any],
    manifest: str,
) -> None:
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "input-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "files.sha256").write_text(manifest, encoding="utf-8")
    tools = {
        "schema": "lab.station_p0_tool_versions/v0",
        "python": sys.version,
        "platform": platform.platform(),
        "git": git_version(),
        "solidworks": "record_manually_on_windows",
        "blender": "not_required_for_p0",
    }
    (output / "tool-versions.json").write_text(
        json.dumps(tools, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = f"""# 投料站 P0 输入冻结报告

- 状态：`passed`（仅输入清单与摘要）
- 顶层总装：`{inventory['top_assembly']}`
- 文件数：{inventory['file_count']}
- CAD/中立几何文件数：{inventory['cad_file_count']}
- 总字节数：{inventory['total_bytes']}
- `files.sha256` 聚合摘要：`{inventory['source_files_digest']}`

## 本阶段证明

- 给定输入根下的文件清单、大小和 SHA-256 已冻结；
- 相同文件树再次运行应产生字节一致的 `files.sha256`；
- 顶层总装候选存在。

## 本阶段不证明

- Pack and Go 引用完整性；
- SolidWorks occurrence、mate 或配置语义；
- GLB、碰撞、互锁、点位或执行资格。
"""
    (output / "P0-REPORT.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--top-assembly",
        default="投料站方案模拟1.1.SLDASM",
        help="相对于 source-root 的顶层总装路径",
    )
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output_dir = args.output_dir.resolve()
    try:
        output_dir.relative_to(source_root)
    except ValueError:
        pass
    else:
        sys.stderr.write("P0 rejected: output-dir 不得位于只读输入根目录内\n")
        return 1
    try:
        inventory, manifest = build_inventory(source_root, args.top_assembly)
        write_outputs(output_dir, inventory, manifest)
    except (InventoryError, OSError) as error:
        sys.stderr.write(f"P0 rejected: {error}\n")
        return 1
    sys.stdout.write(json.dumps({
        "passed": True,
        "file_count": inventory["file_count"],
        "total_bytes": inventory["total_bytes"],
        "source_files_digest": inventory["source_files_digest"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
