#!/usr/bin/env python3
"""Validate and atomically package an approved Windows W2 geometry handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compile_station_decomposition import (  # noqa: E402
    DecompositionError,
    build_coverage_report,
    compile_station,
    render_review_markdown,
)
from station_glb_semantics import (  # noqa: E402
    ALGORITHM,
    canonical_sha256,
    glb_geometry_stats,
    glb_semantic_signature,
    read_glb_layout,
)


PLAN_SCHEMA = "lab.station_geometry_export_plan/v1"
HANDOFF_SCHEMA = "lab.station_geometry_handoff/v1"
ENTITY_MAP_SCHEMA = "lab.station_geometry_entity_map/v1"
EXPORT_REPORT_SCHEMA = "lab.solidworks_device_geometry_export_report/v1"
REQUIRED_SLICE_ROLES = {"rack", "rail-shell", "robot-cad-comparison", "bottle-4ml"}
MAX_RENDER_GLB_BYTES = 25 * 1024 * 1024
MAX_PRIMITIVES = 500
MAX_TRIANGLES = 3_000_000
DIGEST = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9.-]*-w2$")
ASSET_INSTANCE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class GeometryHandoffError(RuntimeError):
    """W2 evidence is incomplete, ambiguous, or outside its qualification boundary."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GeometryHandoffError(f"{label} 不是可读 UTF-8 JSON: {error}") from error
    return _mapping(value, label)


def _read_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise GeometryHandoffError(f"{label} 不是可读 UTF-8 YAML: {error}") from error
    return _mapping(value, label)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GeometryHandoffError(f"{field} 必须是对象")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise GeometryHandoffError(f"{field} 必须是数组")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeometryHandoffError(f"{field} 必须是非空文本")
    return value.strip()


def _keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise GeometryHandoffError(f"{field} 含不支持字段: {', '.join(unexpected)}")


def _relative_file(root: Path, value: Any, field: str) -> Path:
    relative_text = _text(value, field)
    relative = Path(relative_text)
    if relative.is_absolute() or "\\" in relative_text:
        raise GeometryHandoffError(f"{field} 必须是 POSIX 相对路径")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise GeometryHandoffError(f"{field} 路径越出 export plan 目录") from error
    if not target.is_file():
        raise GeometryHandoffError(f"{field} 文件缺失: {target}")
    return target


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(encoded)


def _write_manifest(root: Path, names: list[str]) -> str:
    manifest = "".join(f"{sha256(root / name)}  {name}\n" for name in sorted(names))
    (root / "files.sha256").write_bytes(manifest.encode("utf-8"))
    return manifest


def _canonical_lines(value: str) -> list[str]:
    return value.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def _validate_approval_inputs(
    station_handoff: Path,
    decomposition: Path,
    station_layout: Path,
    coverage_report: Path,
    review: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    try:
        expected_layout = compile_station(station_handoff, decomposition)
    except DecompositionError as error:
        raise GeometryHandoffError(f"P2 批准产物无法重编译: {error}") from error
    layout = _read_json(station_layout, "station-layout.json")
    if layout != expected_layout:
        raise GeometryHandoffError("station-layout.json 不是当前 handoff/decomposition 的重编译产物")
    expected_coverage = build_coverage_report(expected_layout)
    coverage = _read_json(coverage_report, "coverage-report.json")
    if coverage != expected_coverage:
        raise GeometryHandoffError("coverage-report.json 不是当前 layout 的重编译产物")
    if (
        layout.get("human_reviewed") is not True
        or layout.get("publication_eligible") is not True
        or layout.get("qualification") != "station-layout-candidate"
        or layout.get("unassigned_occurrences") != []
        or coverage.get("exact_coverage") is not True
        or coverage.get("overlapping_occurrences") != []
    ):
        raise GeometryHandoffError("P2 尚未达到 approved-for-w2-geometry-export")
    expected_review = render_review_markdown(expected_layout, expected_coverage)
    try:
        review_text = review.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise GeometryHandoffError(f"DECOMPOSITION-REVIEW.md 不可读: {error}") from error
    if _canonical_lines(review_text) != _canonical_lines(expected_review):
        raise GeometryHandoffError("DECOMPOSITION-REVIEW.md 不是当前 layout 的重编译产物")

    handoff = _read_json(station_handoff, "station-handoff.json")
    capture = _mapping(handoff.get("solidworks_capture"), "solidworks_capture")
    handoff_root = station_handoff.resolve().parent
    source_path = _relative_handoff_file(handoff_root, capture.get("source"), "source")
    source = _read_json(source_path, "source.json")
    source_digest = str(source.get("source_files_digest") or "")
    if DIGEST.fullmatch(source_digest) is None:
        raise GeometryHandoffError("source.json 缺少有效 source_files_digest")
    return handoff, layout, coverage, source_digest


def _relative_handoff_file(root: Path, value: Any, field: str) -> Path:
    text = _text(value, field)
    relative = Path(text)
    if relative.is_absolute() or "\\" in text:
        raise GeometryHandoffError(f"handoff.{field} 必须是 POSIX 相对路径")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise GeometryHandoffError(f"handoff.{field} 越出 handoff 目录") from error
    if not target.is_file():
        raise GeometryHandoffError(f"handoff.{field} 文件缺失")
    return target


def _validate_plan_header(
    plan: dict[str, Any],
    *,
    expected_station: str,
    output_root: Path,
) -> tuple[str, dict[str, str], dict[str, str]]:
    _keys(plan, {"schema", "run_id", "station", "solidworks", "exporter", "devices"}, "plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise GeometryHandoffError(f"plan.schema 必须是 {PLAN_SCHEMA}")
    run_id = _text(plan.get("run_id"), "run_id")
    if RUN_ID.fullmatch(run_id) is None or "win02" in run_id:
        raise GeometryHandoffError("W2 必须使用新的、以 -w2 结尾且不覆盖 win02 的 RunId")
    if output_root.name != run_id:
        raise GeometryHandoffError("output-root 目录名必须精确等于 plan.run_id")
    if plan.get("station") != expected_station:
        raise GeometryHandoffError("plan.station 与批准 handoff 不一致")
    solidworks = _mapping(plan.get("solidworks"), "solidworks")
    _keys(solidworks, {"revision", "configuration", "source_read_only"}, "solidworks")
    if solidworks.get("source_read_only") is not True:
        raise GeometryHandoffError("solidworks.source_read_only 必须为 true")
    solidworks_value = {
        "revision": _text(solidworks.get("revision"), "solidworks.revision"),
        "configuration": _text(solidworks.get("configuration"), "solidworks.configuration"),
    }
    exporter = _mapping(plan.get("exporter"), "exporter")
    _keys(exporter, {"name", "version", "selection_mode"}, "exporter")
    if exporter.get("selection_mode") != "exact-subtree-root":
        raise GeometryHandoffError("exporter.selection_mode 必须是 exact-subtree-root")
    exporter_value = {
        "name": _text(exporter.get("name"), "exporter.name"),
        "version": _text(exporter.get("version"), "exporter.version"),
        "selection_mode": "exact-subtree-root",
    }
    return run_id, solidworks_value, exporter_value


def _validate_entity_map(
    path: Path,
    glb: Path,
    *,
    subtree_root: str,
    qualification: str,
    allowed_occurrences: set[str],
    geometry_role: str,
    label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    value = _read_json(path, label)
    _keys(value, {"schema", "subtree_root", "qualification", "nodes"}, label)
    if value.get("schema") != ENTITY_MAP_SCHEMA:
        raise GeometryHandoffError(f"{label}.schema 必须是 {ENTITY_MAP_SCHEMA}")
    if value.get("subtree_root") != subtree_root:
        raise GeometryHandoffError(f"{label}.subtree_root 与批准根不一致")
    if value.get("qualification") != qualification:
        raise GeometryHandoffError(f"{label}.qualification 与 export plan 不一致")
    try:
        document, _, _ = read_glb_layout(glb)
    except (OSError, ValueError, IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise GeometryHandoffError(f"{label} 对应 GLB 无效: {error}") from error
    glb_nodes = document.get("nodes", [])
    raw_nodes = _list(value.get("nodes"), f"{label}.nodes")
    by_index: dict[int, dict[str, Any]] = {}
    entity_records: list[dict[str, Any]] = []
    for map_index, raw in enumerate(raw_nodes):
        item = _mapping(raw, f"{label}.nodes[{map_index}]")
        _keys(
            item,
            {"node_index", "node_name", "occurrence_id", "mapping", "geometry_role"},
            f"{label}.nodes[{map_index}]",
        )
        node_index = item.get("node_index")
        if isinstance(node_index, bool) or not isinstance(node_index, int):
            raise GeometryHandoffError(f"{label}.nodes[{map_index}].node_index 必须是整数")
        if node_index in by_index:
            raise GeometryHandoffError(f"{label} 重复映射 GLB node {node_index}")
        if node_index < 0 or node_index >= len(glb_nodes):
            raise GeometryHandoffError(f"{label} 引用不存在的 GLB node {node_index}")
        if item.get("node_name") != glb_nodes[node_index].get("name"):
            raise GeometryHandoffError(f"{label} node {node_index} 名称与 GLB 不绑定")
        occurrence_id = _text(
            item.get("occurrence_id"),
            f"{label}.nodes[{map_index}].occurrence_id",
        )
        if occurrence_id not in allowed_occurrences:
            raise GeometryHandoffError(
                f"{label} node {node_index} 混入批准子树之外 occurrence: {occurrence_id}"
            )
        if item.get("mapping") != "exact-occurrence":
            raise GeometryHandoffError(
                f"{label} node {node_index} 无精确 occurrence 映射；只能停止为 visual-only"
            )
        if item.get("geometry_role") != geometry_role:
            raise GeometryHandoffError(f"{label} node {node_index} geometry_role 不正确")
        by_index[node_index] = item
        entity_records.append(
            {
                "node_name": item.get("node_name"),
                "occurrence_id": occurrence_id,
                "geometry_role": geometry_role,
            }
        )
    if set(by_index) != set(range(len(glb_nodes))):
        missing = sorted(set(range(len(glb_nodes))) - set(by_index))
        raise GeometryHandoffError(f"{label} 未覆盖全部 GLB nodes: {missing[:20]}")
    entity_records.sort(
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return value, entity_records, canonical_sha256(entity_records)


def _validate_digest(value: Any, field: str, expected: str) -> None:
    digest = str(value or "").lower()
    if DIGEST.fullmatch(digest) is None or digest != expected:
        raise GeometryHandoffError(f"{field} 必须与 W1 source_files_digest 一致")


def _validate_capture(
    raw: Any,
    *,
    plan_root: Path,
    field: str,
    source_digest: str,
) -> dict[str, Any]:
    capture = _mapping(raw, field)
    _keys(
        capture,
        {"render_glb", "entity_map", "source_digest_before", "source_digest_after"},
        field,
    )
    _validate_digest(capture.get("source_digest_before"), f"{field}.source_digest_before", source_digest)
    _validate_digest(capture.get("source_digest_after"), f"{field}.source_digest_after", source_digest)
    return {
        "render_glb": _relative_file(plan_root, capture.get("render_glb"), f"{field}.render_glb"),
        "entity_map": _relative_file(plan_root, capture.get("entity_map"), f"{field}.entity_map"),
    }


def _vector3(value: Any, field: str, *, positive: bool) -> list[float]:
    values = _list(value, field)
    if len(values) != 3:
        raise GeometryHandoffError(f"{field} 必须有 3 个数值")
    result: list[float] = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise GeometryHandoffError(f"{field} 必须只包含数值")
        number = float(item)
        if (positive and number <= 0) or (not positive and number < 0):
            qualifier = "正数" if positive else "非负数"
            raise GeometryHandoffError(f"{field} 必须只包含{qualifier}")
        result.append(number)
    return result


def _validate_size_expectation(device: dict[str, Any], stats: dict[str, Any], field: str) -> None:
    expected = device.get("expected_size_m")
    tolerance = device.get("size_tolerance_m")
    required = device.get("slice_role") in {"rail-shell", "bottle-4ml"}
    if expected is None and tolerance is None and not required:
        return
    if expected is None or tolerance is None:
        raise GeometryHandoffError(f"{field} 必须同时声明 expected_size_m 与 size_tolerance_m")
    expected_values = _vector3(expected, f"{field}.expected_size_m", positive=True)
    tolerance_values = _vector3(tolerance, f"{field}.size_tolerance_m", positive=False)
    actual = stats["bounding_box_m"]["size"]
    if any(abs(value - target) > limit for value, target, limit in zip(actual, expected_values, tolerance_values)):
        raise GeometryHandoffError(
            f"{field} GLB 包围盒尺寸超出已审预期: actual={actual}, "
            f"expected={expected_values}, tolerance={tolerance_values}"
        )


def _validate_budget(stats: dict[str, Any], field: str) -> None:
    if stats["bytes"] > MAX_RENDER_GLB_BYTES:
        raise GeometryHandoffError(f"{field} render.glb 超过 25 MB 预算")
    if stats["primitives"] > MAX_PRIMITIVES:
        raise GeometryHandoffError(f"{field} primitives 超过 500 预算")
    if stats["triangles"] > MAX_TRIANGLES:
        raise GeometryHandoffError(f"{field} triangles 超过 3,000,000 预算")


def _validate_device(
    raw: Any,
    *,
    index: int,
    plan_root: Path,
    placements: dict[str, dict[str, Any]],
    source_digest: str,
) -> dict[str, Any]:
    field = f"devices[{index}]"
    device = _mapping(raw, field)
    _keys(
        device,
        {
            "asset_instance",
            "slice_role",
            "family",
            "subtree_root",
            "qualification",
            "source_unit",
            "comparison_only",
            "expected_size_m",
            "size_tolerance_m",
            "primary",
            "repeat",
        },
        field,
    )
    asset_instance = _text(device.get("asset_instance"), f"{field}.asset_instance")
    if ASSET_INSTANCE.fullmatch(asset_instance) is None:
        raise GeometryHandoffError(f"{field}.asset_instance 必须是安全 ASCII slug")
    slice_role = _text(device.get("slice_role"), f"{field}.slice_role")
    if slice_role not in REQUIRED_SLICE_ROLES:
        raise GeometryHandoffError(f"{field}.slice_role 不受支持")
    subtree_root = _text(device.get("subtree_root"), f"{field}.subtree_root")
    placement = placements.get(subtree_root)
    if placement is None:
        raise GeometryHandoffError(f"{field}.subtree_root 不是批准 layout 的精确根")
    if device.get("family") != placement.get("family"):
        raise GeometryHandoffError(f"{field}.family 与批准 layout 不一致")
    is_robot = slice_role == "robot-cad-comparison"
    comparison_only = device.get("comparison_only")
    if comparison_only is not is_robot:
        raise GeometryHandoffError(f"{field}.comparison_only 与纵切角色不一致")
    if is_robot:
        if (
            placement.get("kind") != "robot_replacement"
            or placement.get("solidworks_geometry_role") != "comparison_only"
            or placement.get("kinematics_source") != "robot-family:dobot.cr5"
        ):
            raise GeometryHandoffError("机器人 W2 CAD 对照必须绑定批准的 Dobot CR5 replacement")
        qualification = "comparison-only"
        geometry_role = "comparison"
    else:
        if placement.get("kind") == "robot_replacement":
            raise GeometryHandoffError(f"{field} 非机器人纵切不能引用 robot replacement")
        qualification = "semantic-scene"
        geometry_role = "semantic"
    if device.get("qualification") != qualification:
        raise GeometryHandoffError(f"{field}.qualification 必须是 {qualification}")
    source_unit = _text(device.get("source_unit"), f"{field}.source_unit")
    if source_unit not in {"mm", "m"}:
        raise GeometryHandoffError(f"{field}.source_unit 必须明确为 mm 或 m")
    if slice_role == "bottle-4ml" and source_unit != "mm":
        raise GeometryHandoffError("4 ml 瓶必须显式声明 source_unit=mm")

    primary = _validate_capture(
        device.get("primary"),
        plan_root=plan_root,
        field=f"{field}.primary",
        source_digest=source_digest,
    )
    repeat = _validate_capture(
        device.get("repeat"),
        plan_root=plan_root,
        field=f"{field}.repeat",
        source_digest=source_digest,
    )
    allowed = set(placement.get("source_occurrences") or [])
    if not allowed or subtree_root not in allowed:
        raise GeometryHandoffError(f"{field} 批准 layout 缺少 source_occurrences")
    primary_map, primary_entities, primary_entity_digest = _validate_entity_map(
        primary["entity_map"],
        primary["render_glb"],
        subtree_root=subtree_root,
        qualification=qualification,
        allowed_occurrences=allowed,
        geometry_role=geometry_role,
        label=f"{field}.primary.entity_map",
    )
    _, repeat_entities, repeat_entity_digest = _validate_entity_map(
        repeat["entity_map"],
        repeat["render_glb"],
        subtree_root=subtree_root,
        qualification=qualification,
        allowed_occurrences=allowed,
        geometry_role=geometry_role,
        label=f"{field}.repeat.entity_map",
    )
    if primary_entities != repeat_entities or primary_entity_digest != repeat_entity_digest:
        raise GeometryHandoffError(f"{field} 两次导出的 entity 集合不一致")
    try:
        primary_semantic_digest = canonical_sha256(glb_semantic_signature(primary["render_glb"]))
        repeat_semantic_digest = canonical_sha256(glb_semantic_signature(repeat["render_glb"]))
        primary_stats = glb_geometry_stats(primary["render_glb"])
        repeat_stats = glb_geometry_stats(repeat["render_glb"])
    except (OSError, ValueError, IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise GeometryHandoffError(f"{field} GLB 无法形成 W2 语义证据: {error}") from error
    if primary_semantic_digest != repeat_semantic_digest:
        raise GeometryHandoffError(f"{field} 两次独立导出的语义几何签名不一致")
    _validate_budget(primary_stats, f"{field}.primary")
    _validate_budget(repeat_stats, f"{field}.repeat")
    _validate_size_expectation(device, primary_stats, field)
    primary_comparable = dict(primary_stats)
    repeat_comparable = dict(repeat_stats)
    primary_comparable.pop("sha256", None)
    repeat_comparable.pop("sha256", None)
    primary_comparable.pop("bytes", None)
    repeat_comparable.pop("bytes", None)
    if primary_comparable != repeat_comparable:
        raise GeometryHandoffError(f"{field} 两次导出的几何统计不一致")
    return {
        "asset_instance": asset_instance,
        "slice_role": slice_role,
        "family": placement["family"],
        "kind": placement["kind"],
        "subtree_root": subtree_root,
        "qualification": qualification,
        "source_unit": source_unit,
        "comparison_only": is_robot,
        "kinematics_source": placement.get("kinematics_source") if is_robot else None,
        "primary_glb": primary["render_glb"],
        "primary_entity_map": primary_map,
        "primary_stats": primary_stats,
        "repeat_stats": repeat_stats,
        "entity_set_sha256": primary_entity_digest,
        "semantic_algorithm": ALGORITHM,
        "semantic_sha256": primary_semantic_digest,
        "exact_glb_match": primary_stats["sha256"] == repeat_stats["sha256"],
    }


def finalize_geometry_handoff(
    *,
    plan_path: Path,
    output_root: Path,
    station_handoff: Path,
    decomposition: Path,
    station_layout: Path,
    coverage_report: Path,
    review: Path,
) -> dict[str, Any]:
    output = output_root.resolve()
    if output.exists():
        raise GeometryHandoffError("output-root 已存在；W2 必须使用全新 RunId，禁止覆盖")
    plan = _read_json(plan_path, "geometry export plan")
    handoff, layout, _, source_digest = _validate_approval_inputs(
        station_handoff,
        decomposition,
        station_layout,
        coverage_report,
        review,
    )
    station = _text(handoff.get("station"), "station-handoff.station")
    run_id, solidworks, exporter = _validate_plan_header(
        plan,
        expected_station=station,
        output_root=output,
    )
    placements_raw = _list(layout.get("placements"), "station-layout.placements")
    placements = {
        _text(item.get("subtree_root"), "placement.subtree_root"): item
        for item in placements_raw
        if isinstance(item, dict)
    }
    devices_raw = _list(plan.get("devices"), "plan.devices")
    if not devices_raw:
        raise GeometryHandoffError("plan.devices 不得为空")
    validated = [
        _validate_device(
            raw,
            index=index,
            plan_root=plan_path.resolve().parent,
            placements=placements,
            source_digest=source_digest,
        )
        for index, raw in enumerate(devices_raw)
    ]
    instances = [item["asset_instance"] for item in validated]
    if len(instances) != len(set(instances)):
        raise GeometryHandoffError("asset_instance 重复")
    roots = [item["subtree_root"] for item in validated]
    if len(roots) != len(set(roots)):
        raise GeometryHandoffError("同一批准 subtree_root 不得重复导出")
    roles = {item["slice_role"] for item in validated}
    missing_roles = sorted(REQUIRED_SLICE_ROLES - roles)
    if missing_roles:
        raise GeometryHandoffError("第一条 W2 纵切缺少: " + ", ".join(missing_roles))

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        approval_dir = staging / "approval"
        approval_dir.mkdir()
        approval_sources = {
            "station-decomposition.yaml": decomposition,
            "station-layout.json": station_layout,
            "coverage-report.json": coverage_report,
            "DECOMPOSITION-REVIEW.md": review,
        }
        approval_manifest: dict[str, dict[str, Any]] = {}
        for name, source in approval_sources.items():
            target = approval_dir / name
            shutil.copy2(source, target)
            approval_manifest[name] = {"path": f"approval/{name}", "sha256": sha256(target)}

        manifest_devices: list[dict[str, Any]] = []
        for item in validated:
            device_dir = staging / "devices" / item["asset_instance"]
            device_dir.mkdir(parents=True)
            shutil.copy2(item["primary_glb"], device_dir / "render.glb")
            _write_json(device_dir / "entity-map.json", item["primary_entity_map"])
            export_report = {
                "schema": EXPORT_REPORT_SCHEMA,
                "status": "passed",
                "asset_instance": item["asset_instance"],
                "slice_role": item["slice_role"],
                "family": item["family"],
                "kind": item["kind"],
                "exact_subtree_root": item["subtree_root"],
                "source_handoff_digest": sha256(station_handoff),
                "source_decomposition_digest": sha256(decomposition),
                "source_files_digest": source_digest,
                "source_read_only": True,
                "source_digest_before": source_digest,
                "source_digest_after": source_digest,
                "source_unit": item["source_unit"],
                "render_unit": "m",
                "comparison_only": item["comparison_only"],
                "kinematics_source": item["kinematics_source"],
                "solidworks": solidworks,
                "exporter": exporter,
                "geometry": item["primary_stats"],
                "reproducibility": {
                    "primary_glb_sha256": item["primary_stats"]["sha256"],
                    "repeat_glb_sha256": item["repeat_stats"]["sha256"],
                    "exact_glb_match": item["exact_glb_match"],
                    "entity_set_match": True,
                    "entity_set_sha256": item["entity_set_sha256"],
                    "semantic_match": True,
                    "semantic_algorithm": item["semantic_algorithm"],
                    "semantic_sha256": item["semantic_sha256"],
                },
                "budgets": {
                    "max_render_glb_bytes": MAX_RENDER_GLB_BYTES,
                    "max_primitives": MAX_PRIMITIVES,
                    "max_triangles": MAX_TRIANGLES,
                    "passed": True,
                },
                "not_qualified_for": ["collision", "kinematics", "spatial-interlock-enforced", "execution"],
            }
            _write_json(device_dir / "export-report.json", export_report)
            device_manifest = _write_manifest(
                device_dir,
                ["entity-map.json", "export-report.json", "render.glb"],
            )
            manifest_devices.append(
                {
                    "asset_instance": item["asset_instance"],
                    "slice_role": item["slice_role"],
                    "family": item["family"],
                    "kind": item["kind"],
                    "exact_subtree_root": item["subtree_root"],
                    "qualification": item["qualification"],
                    "source_unit": item["source_unit"],
                    "comparison_only": item["comparison_only"],
                    "path": f"devices/{item['asset_instance']}",
                    "files_sha256": f"devices/{item['asset_instance']}/files.sha256",
                    "files_manifest_sha256": hashlib.sha256(
                        device_manifest.encode("utf-8")
                    ).hexdigest(),
                }
            )

        payload_files = sorted(path for path in staging.rglob("*") if path.is_file())
        handoff_value = {
            "schema": HANDOFF_SCHEMA,
            "run_id": run_id,
            "station": station,
            "status": "ready-for-mac-w2-validation",
            "qualification": "device-geometry-candidate",
            "source_handoff_digest": sha256(station_handoff),
            "source_decomposition_digest": sha256(decomposition),
            "source_files_digest": source_digest,
            "approval": approval_manifest,
            "solidworks": solidworks,
            "exporter": exporter,
            "semantic_algorithm": ALGORITHM,
            "devices": manifest_devices,
            "payload_file_count": len(payload_files),
            "payload_total_bytes": sum(path.stat().st_size for path in payload_files),
            "not_a_deploy_manifest": True,
            "not_a_workcell_activation": True,
            "not_qualified_for": [
                "base_pose",
                "tcp",
                "point_table",
                "collision",
                "kinematics",
                "spatial-interlock-enforced",
                "execution",
            ],
        }
        _write_json(staging / "geometry-handoff.json", handoff_value)
        staging.replace(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "passed": True,
        "status": "ready-for-mac-w2-validation",
        "run_id": run_id,
        "station": station,
        "device_count": len(validated),
        "geometry_handoff": str(output / "geometry-handoff.json"),
        "geometry_handoff_sha256": sha256(output / "geometry-handoff.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--station-handoff", required=True, type=Path)
    parser.add_argument("--decomposition", required=True, type=Path)
    parser.add_argument("--station-layout", required=True, type=Path)
    parser.add_argument("--coverage-report", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = finalize_geometry_handoff(
            plan_path=args.plan,
            output_root=args.output_root,
            station_handoff=args.station_handoff,
            decomposition=args.decomposition,
            station_layout=args.station_layout,
            coverage_report=args.coverage_report,
            review=args.review,
        )
    except (GeometryHandoffError, OSError) as error:
        sys.stderr.write(f"W2 geometry handoff rejected: {error}\n")
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
