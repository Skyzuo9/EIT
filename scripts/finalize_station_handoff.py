#!/usr/bin/env python3
"""把 Windows SolidWorks 只读采集结果封装成标准 P1 handoff。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    from station_glb_semantics import ALGORITHM, DIAGNOSIS_SCHEMA, normalized_snapshot
except ModuleNotFoundError:  # 允许测试从仓库根目录加载脚本
    from scripts.station_glb_semantics import (
        ALGORITHM,
        DIAGNOSIS_SCHEMA,
        normalized_snapshot,
    )


class FinalizeError(RuntimeError):
    """P1 输入不完整或与 P0 冻结摘要不一致。"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_manifest(root: Path) -> str:
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise FinalizeError("source-release 为空")
    return "".join(
        f"{sha256(path)}  {path.relative_to(root).as_posix()}\n"
        for path in paths
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FinalizeError(f"{label} 不是可读 JSON: {error}") from error
    if not isinstance(value, dict):
        raise FinalizeError(f"{label} 必须是 JSON 对象")
    return value


def copy_if_needed(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def finalize(
    *,
    output_root: Path,
    source_release_root: Path,
    snapshot_input: Path,
    report_input: Path,
    glb_input: Path,
    repeat_snapshot_input: Path,
    repeat_report_input: Path,
    repeat_glb_input: Path,
    station: str,
    p0_manifest: Path | None,
    semantic_diagnosis_input: Path | None = None,
) -> dict[str, Any]:
    root = output_root.resolve()
    release = source_release_root.resolve()
    expected_release = (root / "source-release").resolve()
    if release != expected_release:
        raise FinalizeError("source-release-root 必须等于 output-root/source-release")
    if not release.is_dir():
        raise FinalizeError(f"source-release 不存在: {release}")
    if not station.strip():
        raise FinalizeError("station 不得为空")

    snapshot = load_json(snapshot_input, "assembly snapshot")
    report = load_json(report_input, "capture report")
    repeat_snapshot = load_json(repeat_snapshot_input, "repeat assembly snapshot")
    repeat_report = load_json(repeat_report_input, "repeat capture report")
    if snapshot.get("schema") != "lab.assembly_snapshot/v0":
        raise FinalizeError("assembly snapshot schema 无效")
    if report.get("schema") != "lab.solidworks_capture_report/v0":
        raise FinalizeError("capture report schema 无效")
    if report.get("status") != "passed" or report.get("source_read_only") is not True:
        raise FinalizeError("capture report 未证明只读采集通过")
    if (
        repeat_report.get("schema") != "lab.solidworks_capture_report/v0"
        or repeat_report.get("status") != "passed"
        or repeat_report.get("source_read_only") is not True
    ):
        raise FinalizeError("repeat capture report 未证明第二次只读采集通过")
    if repeat_snapshot.get("schema") != "lab.assembly_snapshot/v0":
        raise FinalizeError("repeat assembly snapshot schema 无效")
    instances = snapshot.get("instances")
    if not isinstance(instances, list) or not instances:
        raise FinalizeError("assembly snapshot 没有 occurrence")
    if report.get("component_count") != len(instances):
        raise FinalizeError("snapshot occurrence 数量与 capture report 不一致")
    repeat_instances = repeat_snapshot.get("instances")
    if not isinstance(repeat_instances, list) or not repeat_instances:
        raise FinalizeError("repeat assembly snapshot 没有 occurrence")
    if repeat_report.get("component_count") != len(repeat_instances):
        raise FinalizeError("repeat snapshot occurrence 数量与 capture report 不一致")
    if normalized_snapshot(snapshot) != normalized_snapshot(repeat_snapshot):
        raise FinalizeError("两次独立 SolidWorks 会话的规范化 snapshot 不一致")
    if not glb_input.is_file() or glb_input.stat().st_size < 20:
        raise FinalizeError("GLB 缺失或过小")
    with glb_input.open("rb") as handle:
        if handle.read(4) != b"glTF":
            raise FinalizeError("GLB magic 不是 glTF")
    if not repeat_glb_input.is_file() or repeat_glb_input.stat().st_size < 20:
        raise FinalizeError("repeat GLB 缺失或过小")
    with repeat_glb_input.open("rb") as handle:
        if handle.read(4) != b"glTF":
            raise FinalizeError("repeat GLB magic 不是 glTF")
    primary_glb_digest = sha256(glb_input)
    repeat_glb_digest = sha256(repeat_glb_input)
    exact_glb_match = primary_glb_digest == repeat_glb_digest
    semantic_glb_match = exact_glb_match
    difference_class = "none"
    semantic_diagnosis: dict[str, Any] | None = None
    if not exact_glb_match:
        if semantic_diagnosis_input is None:
            raise FinalizeError(
                "两次 GLB 字节摘要不一致；P1 暂停，由 Mac 做语义几何差异诊断"
            )
        semantic_diagnosis = load_json(
            semantic_diagnosis_input,
            "GLB semantic diagnosis",
        )
        if semantic_diagnosis.get("schema") != DIAGNOSIS_SCHEMA:
            raise FinalizeError("GLB semantic diagnosis schema 无效")
        if semantic_diagnosis.get("algorithm") != ALGORITHM:
            raise FinalizeError("GLB semantic diagnosis 算法版本无效")
        if (
            semantic_diagnosis.get("status") != "passed"
            or semantic_diagnosis.get("normalized_glb_semantic_match") is not True
            or semantic_diagnosis.get("approved_for_p1_packaging") is not True
            or semantic_diagnosis.get("difference_class")
            != "component_traversal_order_only"
        ):
            raise FinalizeError("GLB semantic diagnosis 未批准 P1 封装")
        primary_value = semantic_diagnosis.get("primary_glb")
        repeat_value = semantic_diagnosis.get("repeat_glb")
        if not isinstance(primary_value, dict) or not isinstance(repeat_value, dict):
            raise FinalizeError("GLB semantic diagnosis 缺少 GLB 摘要")
        primary_diagnosed = primary_value.get("sha256")
        repeat_diagnosed = repeat_value.get("sha256")
        if primary_diagnosed != primary_glb_digest or repeat_diagnosed != repeat_glb_digest:
            raise FinalizeError("GLB semantic diagnosis 与本次 GLB SHA-256 不绑定")
        semantic_glb_match = True
        difference_class = "component_traversal_order_only"
    elif semantic_diagnosis_input is not None:
        raise FinalizeError("两次 GLB 字节一致时不得附加不必要的语义诊断")

    manifest = source_manifest(release)
    if p0_manifest is not None:
        try:
            expected = p0_manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise FinalizeError(f"无法读取 P0 files.sha256: {error}") from error
        if expected != manifest:
            raise FinalizeError("source-release 与 P0 files.sha256 不一致")

    capture_dir = root / "capture"
    geometry_dir = root / "geometry"
    repeat_dir = root / "audit" / "repeat"
    audit_dir = root / "audit"
    capture_dir.mkdir(parents=True, exist_ok=True)
    geometry_dir.mkdir(parents=True, exist_ok=True)
    repeat_dir.mkdir(parents=True, exist_ok=True)
    snapshot_target = capture_dir / "assembly.snapshot.json"
    report_target = capture_dir / "capture-report.json"
    glb_target = geometry_dir / "station.glb"
    copy_if_needed(snapshot_input, snapshot_target)
    copy_if_needed(report_input, report_target)
    copy_if_needed(glb_input, glb_target)
    copy_if_needed(repeat_snapshot_input, repeat_dir / "assembly.snapshot.json")
    copy_if_needed(repeat_report_input, repeat_dir / "capture-report.json")
    copy_if_needed(repeat_glb_input, repeat_dir / "station.glb")
    semantic_diagnosis_target: Path | None = None
    if semantic_diagnosis_input is not None:
        semantic_diagnosis_target = audit_dir / "glb-semantic-diagnosis.json"
        copy_if_needed(semantic_diagnosis_input, semantic_diagnosis_target)
    (capture_dir / "files.sha256").write_text(manifest, encoding="utf-8")
    aggregate = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    source = {
        "schema": "lab.source/v0",
        "read_policy": "read-only",
        "manifest_algorithm": "sha256(utf8(files.sha256))",
        "source_files_digest": aggregate,
    }
    (capture_dir / "source.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    handoff = {
        "schema": "lab.station_source_handoff/v0",
        "station": station,
        "solidworks_capture": {
            "assembly_snapshot": "capture/assembly.snapshot.json",
            "capture_report": "capture/capture-report.json",
            "source": "capture/source.json",
            "files_sha256": "capture/files.sha256",
            "source_release_root": "source-release",
            "render_glb": "geometry/station.glb",
        },
        "robot_release": {
            "authority": "manufacturer",
            "vendor": "Dobot",
            "model": "CR5",
            "provider": "unilab_arm_cr5:build_moveit_model",
            "source_digest": "8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2",
        },
        "reproducibility": {
            "report": "audit/reproducibility-report.json",
            "repeat_snapshot": "audit/repeat/assembly.snapshot.json",
            "repeat_capture_report": "audit/repeat/capture-report.json",
            "repeat_glb": "audit/repeat/station.glb",
            "glb_semantic_diagnosis": "audit/glb-semantic-diagnosis.json"
            if semantic_diagnosis_target is not None
            else None,
        },
    }
    handoff_path = root / "station-handoff.json"
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reproducibility = {
        "schema": "lab.station_capture_reproducibility/v0",
        "status": "passed",
        "normalized_snapshot_match": True,
        "exact_glb_match": exact_glb_match,
        "normalized_glb_semantic_match": semantic_glb_match,
        "difference_class": difference_class,
        "acceptance_basis": "exact-bytes"
        if exact_glb_match
        else "mac-semantic-diagnosis",
        "primary_snapshot_sha256": sha256(snapshot_target),
        "repeat_snapshot_sha256": sha256(repeat_dir / "assembly.snapshot.json"),
        "primary_glb_sha256": primary_glb_digest,
        "repeat_glb_sha256": repeat_glb_digest,
    }
    (root / "audit" / "reproducibility-report.json").write_text(
        json.dumps(reproducibility, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_md = f"""# 投料站 P1 Windows W1 采集报告

- 状态：`ready-for-mac-validation`
- station：`{station}`
- occurrence 数量：{len(instances)}
- 源文件数量：{len(manifest.splitlines())}
- 源发布聚合摘要：`{aggregate}`
- GLB SHA-256：`{sha256(glb_target)}`
- 两次规范化 snapshot：一致
- 两次 GLB 字节摘要：{"一致" if exact_glb_match else "不一致；Mac 语义诊断一致"}
- GLB 差异分类：`{difference_class}`
- handoff SHA-256：`{sha256(handoff_path)}`

本报告只说明 Windows 交接包结构完整且与 P0 摘要一致。Mac 运行
`verify_station_handoff.py` 返回 `passed=true` 之前，P1 不算双方验收完成；
本结果不授予碰撞、互锁或执行资格。
"""
    (root / "P1-REPORT.md").write_text(report_md, encoding="utf-8")
    return {
        "passed": True,
        "status": "ready-for-mac-validation",
        "station": station,
        "instance_count": len(instances),
        "source_file_count": len(manifest.splitlines()),
        "source_files_digest": aggregate,
        "handoff": str(handoff_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--source-release-root", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--capture-report", required=True, type=Path)
    parser.add_argument("--render-glb", required=True, type=Path)
    parser.add_argument("--repeat-snapshot", required=True, type=Path)
    parser.add_argument("--repeat-capture-report", required=True, type=Path)
    parser.add_argument("--repeat-render-glb", required=True, type=Path)
    parser.add_argument("--station", default="eit.feeding-station")
    parser.add_argument("--p0-files-sha256", type=Path)
    parser.add_argument("--glb-semantic-diagnosis", type=Path)
    args = parser.parse_args()
    try:
        result = finalize(
            output_root=args.output_root,
            source_release_root=args.source_release_root,
            snapshot_input=args.snapshot,
            report_input=args.capture_report,
            glb_input=args.render_glb,
            repeat_snapshot_input=args.repeat_snapshot,
            repeat_report_input=args.repeat_capture_report,
            repeat_glb_input=args.repeat_render_glb,
            station=args.station,
            p0_manifest=args.p0_files_sha256,
            semantic_diagnosis_input=args.glb_semantic_diagnosis,
        )
    except (FinalizeError, OSError) as error:
        sys.stderr.write(f"P1 rejected: {error}\n")
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
