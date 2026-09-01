#!/usr/bin/env python3
"""Compile spatial-ready collision asset metadata without upgrading qualification.

The first adapter consumes the existing pTLC parametric proxy release.  It binds
visual and collision bytes, nominal dimensions, uncertainty, cavity QC, and the
generator implementation into one deterministic CollisionGeometryManifest/v1.
An explicit, fail-closed selection policy may replace an asset's parametric
collision proxy with a source-derived candidate that passed the recorded QC
thresholds.  Selection never upgrades the geometry beyond candidate status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA = "lab.collision-geometry-manifest/v1"
ALGORITHM = "ptlc-parametric-proxy-manifest-compiler"
ALGORITHM_VERSION = "v2"
DEFAULT_OUTPUT = Path(
    "artifacts/collision-assets/v1/ptlc-collision-geometry-manifest.json"
)
ASSET_MANIFEST = Path("related/unilabSZlab/pTLC仿真资产/asset_manifest.json")
BUILD_REPORT = Path("related/unilabSZlab/pTLC仿真资产/proxy_build_report.json")
COLLISION_QC = Path("related/unilabSZlab/pTLC仿真资产/collision_qc_report.json")
PROXY_ROOT = Path("related/unilabSZlab/pTLC仿真资产/proxies")
PROXY_GENERATOR = Path(
    "related/unilabSZlab/pTLC仿真资产/scripts/generate_proxy_assets.py"
)
IMPLEMENTATION = Path("scripts/compile_collision_geometry_manifest.py")
CANDIDATE_SELECTION = Path("config/ptlc-collision-candidate-selection.v1.json")
CANDIDATE_SELECTION_SCHEMA = Path(
    "schemas/collision-candidate-selection-v1.schema.json"
)
CANDIDATE_GENERATOR = Path("scripts/generate_collision_candidates.py")


class CollisionManifestError(ValueError):
    """Raised when an input cannot support a fail-closed candidate manifest."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_digest(path: Path, mode: str) -> str:
    if mode == "raw-bytes":
        return _sha256(path)
    if mode == "utf8-lf-v1":
        try:
            normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeError) as error:
            raise CollisionManifestError(f"无法规范化文本摘要: {path}: {error}") from error
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if mode == "canonical-json-v1":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CollisionManifestError(f"无法规范化 JSON 摘要: {path}: {error}") from error
        return hashlib.sha256(_canonical_bytes(value)).hexdigest()
    raise CollisionManifestError(f"不支持的 digest mode: {mode}")


def _canonical_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise CollisionManifestError(f"不能规范化 JSON: {error}") from error
    return payload.encode("utf-8")


def _document_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CollisionManifestError(f"无法读取 {label}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise CollisionManifestError(f"{label} 必须是 JSON object: {path}")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CollisionManifestError(f"{label} 必须是 object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CollisionManifestError(f"{label} 必须是 array")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CollisionManifestError(f"{label} 必须是非空字符串")
    return value


def _vec3(value: Any, label: str, *, scale: float = 1.0) -> list[float]:
    items = _sequence(value, label)
    if len(items) != 3:
        raise CollisionManifestError(f"{label} 必须恰好包含 3 个数")
    result: list[float] = []
    for index, item in enumerate(items):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise CollisionManifestError(f"{label}[{index}] 必须是数值")
        number = float(item) * scale
        if not math.isfinite(number) or number < 0:
            raise CollisionManifestError(f"{label}[{index}] 必须是有限非负数")
        result.append(round(number, 12))
    return result


def _bounds(value: Any, label: str, *, scale: float = 1.0) -> list[list[float]]:
    items = _sequence(value, label)
    if len(items) != 2:
        raise CollisionManifestError(f"{label} 必须包含 min/max")
    low = _numeric_vec3(items[0], f"{label}.min", scale=scale)
    high = _numeric_vec3(items[1], f"{label}.max", scale=scale)
    if any(left > right for left, right in zip(low, high)):
        raise CollisionManifestError(f"{label} 的 min 不能大于 max")
    return [low, high]


def _numeric_vec3(value: Any, label: str, *, scale: float = 1.0) -> list[float]:
    items = _sequence(value, label)
    if len(items) != 3:
        raise CollisionManifestError(f"{label} 必须恰好包含 3 个数")
    result: list[float] = []
    for index, item in enumerate(items):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise CollisionManifestError(f"{label}[{index}] 必须是数值")
        number = float(item) * scale
        if not math.isfinite(number):
            raise CollisionManifestError(f"{label}[{index}] 必须是有限数")
        rounded = round(number, 12)
        result.append(0.0 if rounded == 0.0 else rounded)
    return result


def _index_by_asset_id(value: Any, label: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(value, label)):
        item = _mapping(raw, f"{label}[{index}]")
        asset_id = _text(item.get("asset_id"), f"{label}[{index}].asset_id")
        if asset_id in result:
            raise CollisionManifestError(f"{label} 中 asset_id 重复: {asset_id}")
        result[asset_id] = item
    return result


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise CollisionManifestError(f"artifact 不在仓库内: {path}") from error


def _verify_glb(path: Path) -> None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError as error:
        raise CollisionManifestError(f"无法读取 visual GLB: {path}: {error}") from error
    if len(header) != 12 or header[:4] != b"glTF":
        raise CollisionManifestError(f"visual GLB 头无效: {path}")
    declared_length = int.from_bytes(header[8:12], "little")
    if int.from_bytes(header[4:8], "little") != 2 or declared_length != size:
        raise CollisionManifestError(f"visual GLB version/长度无效: {path}")


def _verify_collision_file(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise CollisionManifestError(f"无法读取 collision 文件: {path}: {error}") from error
    if size < 84:
        raise CollisionManifestError(f"collision 文件过小: {path}")


def _binary_stl_triangle_count(path: Path) -> int:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise CollisionManifestError(f"无法读取 binary STL: {path}: {error}") from error
    if len(payload) < 84:
        raise CollisionManifestError(f"collision 文件过小: {path}")
    count = int.from_bytes(payload[80:84], "little")
    if len(payload) != 84 + count * 50:
        raise CollisionManifestError(f"collision 文件不是确定的 binary STL: {path}")
    return count


def _validate_global_qc(qc: Mapping[str, Any]) -> None:
    required_true = (
        "all_watertight",
        "all_bounds_match_target",
        "all_expected_cavities_preserved",
        "all_open_source_components_disjoint",
    )
    missing = [key for key in required_true if qc.get(key) is not True]
    if missing:
        raise CollisionManifestError(f"碰撞代理全局 QC 未通过: {missing}")


def _candidate_specs(
    asset_manifest: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    specs: dict[str, Mapping[str, Any]] = {}
    pointers: dict[str, str] = {}
    for section in ("proxy_assets", "tool_proxies"):
        for index, raw in enumerate(_sequence(asset_manifest.get(section), f"asset_manifest.{section}")):
            spec = _mapping(raw, f"asset_manifest.{section}[{index}]")
            asset_id = _text(spec.get("asset_id"), f"{section}[{index}].asset_id")
            if asset_id in specs:
                raise CollisionManifestError(f"asset_manifest asset_id 重复: {asset_id}")
            specs[asset_id] = spec
            pointers[asset_id] = f"/{section}/{index}"
    if not specs:
        raise CollisionManifestError("asset_manifest 没有碰撞候选资产")
    return specs, pointers


def _non_negative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CollisionManifestError(f"{label} 必须是数值")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise CollisionManifestError(f"{label} 必须是有限非负数")
    return result


def _selection_by_asset_id(
    selection: Mapping[str, Any], expected_sample_id: str
) -> dict[str, Mapping[str, Any]]:
    if selection.get("schema") != "lab.collision-candidate-selection/v1":
        raise CollisionManifestError("collision candidate selection schema 无效")
    if selection.get("sample_id") != expected_sample_id:
        raise CollisionManifestError("collision candidate selection sample_id 不匹配")
    if selection.get("fallback_policy") != "use-parametric-proxy":
        raise CollisionManifestError("collision candidate selection fallback_policy 无效")
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(selection.get("selections"), "selections")):
        item = _mapping(raw, f"selections[{index}]")
        asset_id = _text(item.get("asset_id"), f"selections[{index}].asset_id")
        if asset_id in result:
            raise CollisionManifestError(f"collision candidate selection 资产重复: {asset_id}")
        result[asset_id] = item
    return result


def _selected_candidate(
    repo_root: Path,
    asset_id: str,
    selection: Mapping[str, Any],
    *,
    report_value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve and verify one source-derived candidate for manifest binding."""

    report_path = repo_root / _text(selection.get("report_path"), f"{asset_id}.report_path")
    report = (
        dict(report_value)
        if report_value is not None
        else _read_json(report_path, f"{asset_id} collision candidate report")
    )
    if report.get("schema") != "lab.collision_candidate_report/v1":
        raise CollisionManifestError(f"{asset_id} candidate report schema 无效")
    if report.get("status") != "candidate-generated" or report.get("qualification") != "offline-collision-candidate":
        raise CollisionManifestError(f"{asset_id} candidate report 状态或资格无效")
    report_asset_id = _text(selection.get("report_asset_id"), f"{asset_id}.report_asset_id")
    if report.get("asset_id") != report_asset_id:
        raise CollisionManifestError(f"{asset_id} candidate report asset_id 不匹配")

    generator = _mapping(report.get("generator"), f"{asset_id}.generator")
    generator_path = repo_root / CANDIDATE_GENERATOR
    if generator.get("script_ref") != CANDIDATE_GENERATOR.as_posix():
        raise CollisionManifestError(f"{asset_id} candidate generator path 漂移")
    generator_sha = _artifact_digest(generator_path, "utf8-lf-v1")
    if generator.get("script_sha256") != generator_sha:
        raise CollisionManifestError(f"{asset_id} candidate generator digest 漂移")

    level_name = _text(selection.get("level"), f"{asset_id}.level")
    level = _mapping(_mapping(report.get("levels"), f"{asset_id}.levels").get(level_name), f"{asset_id}.{level_name}")
    candidate_key = _text(selection.get("candidate_key"), f"{asset_id}.candidate_key")
    candidate = _mapping(level.get(candidate_key), f"{asset_id}.{level_name}.{candidate_key}")
    geometry = _mapping(candidate.get("geometry"), f"{asset_id}.candidate.geometry")
    watertight = _mapping(geometry.get("watertight"), f"{asset_id}.candidate.watertight")
    if selection.get("require_watertight") is True and watertight.get("is_watertight") is not True:
        raise CollisionManifestError(f"{asset_id} candidate 不是 watertight")
    size_error = _mapping(candidate.get("size_error"), f"{asset_id}.candidate.size_error")
    max_relative_error = _non_negative_number(
        size_error.get("aabb_max_relative_error"), f"{asset_id}.aabb_max_relative_error"
    )
    if max_relative_error > _non_negative_number(
        selection.get("max_aabb_relative_error"), f"{asset_id}.max_aabb_relative_error"
    ):
        raise CollisionManifestError(f"{asset_id} candidate AABB 尺寸误差超限")
    missed = _mapping(candidate.get("missed_envelope"), f"{asset_id}.candidate.missed_envelope")
    max_missed = _non_negative_number(
        missed.get("maximum_missed_envelope_m"), f"{asset_id}.maximum_missed_envelope_m"
    )
    if missed.get("passes_at_1e-8_m") is not True or max_missed > _non_negative_number(
        selection.get("max_missed_envelope_m"), f"{asset_id}.max_missed_envelope_m"
    ):
        raise CollisionManifestError(f"{asset_id} candidate 漏包络误差超限")
    cavity = _mapping(candidate.get("cavity_preservation"), f"{asset_id}.candidate.cavity_preservation")
    if selection.get("require_cavity_preserved") is True and (
        cavity.get("cavity_preserved") is not True or cavity.get("status") != "preserved"
    ):
        raise CollisionManifestError(f"{asset_id} candidate 空腔未保留")

    runtime_key = _text(selection.get("runtime_artifact_key"), f"{asset_id}.runtime_artifact_key")
    runtime = _mapping(candidate.get(runtime_key), f"{asset_id}.candidate.{runtime_key}")
    runtime_relative = _text(runtime.get("path"), f"{asset_id}.runtime.path")
    runtime_path = (report_path.parent / runtime_relative).resolve()
    _relative(repo_root, runtime_path)
    if runtime.get("sha256") != _sha256(runtime_path):
        raise CollisionManifestError(f"{asset_id} candidate runtime artifact digest 漂移")
    if runtime.get("format") != "stl" or runtime.get("source_unit") != "m":
        raise CollisionManifestError(f"{asset_id} candidate runtime artifact 必须是米制 STL")
    representation = _text(runtime.get("representation"), f"{asset_id}.runtime.representation")
    if representation not in {"compound-convex", "simplified-static-mesh"}:
        raise CollisionManifestError(f"{asset_id} candidate representation 不支持")
    _verify_collision_file(runtime_path)

    component_count = geometry.get("component_count")
    if isinstance(component_count, bool) or not isinstance(component_count, int) or component_count < 1:
        raise CollisionManifestError(f"{asset_id} candidate component_count 无效")
    component_triangle_counts: list[int] = []
    for index, value in enumerate(
        _sequence(runtime.get("component_triangle_counts"), f"{asset_id}.component_triangle_counts")
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 4:
            raise CollisionManifestError(
                f"{asset_id}.component_triangle_counts[{index}] 必须是至少 4 个 triangle"
            )
        component_triangle_counts.append(value)
    if len(component_triangle_counts) != component_count:
        raise CollisionManifestError(f"{asset_id} runtime component triangle 分段数不一致")
    if sum(component_triangle_counts) != _binary_stl_triangle_count(runtime_path):
        raise CollisionManifestError(f"{asset_id} runtime component triangle 总数不一致")
    bounds = _mapping(geometry.get("bounds"), f"{asset_id}.candidate.bounds")
    local_bounds = {
        "min_m": _numeric_vec3(bounds.get("min_m"), f"{asset_id}.candidate.bounds.min_m"),
        "max_m": _numeric_vec3(bounds.get("max_m"), f"{asset_id}.candidate.bounds.max_m"),
    }
    if any(left > right for left, right in zip(local_bounds["min_m"], local_bounds["max_m"])):
        raise CollisionManifestError(f"{asset_id} candidate bounds 无效")
    candidate_volume = _non_negative_number(geometry.get("volume_m3"), f"{asset_id}.candidate.volume")
    source_aabb_volume = _non_negative_number(
        cavity.get("source_aabb_volume_m3"), f"{asset_id}.source_aabb_volume"
    )
    return {
        "report_path": report_path,
        "report": report,
        "generator_sha": generator_sha,
        "generator_version": _text(generator.get("version"), f"{asset_id}.generator.version"),
        "candidate": candidate,
        "runtime": runtime,
        "runtime_path": runtime_path,
        "representation": representation,
        "component_count": component_count,
        "component_triangle_counts": component_triangle_counts,
        "watertight": watertight.get("is_watertight") is True,
        "local_bounds": local_bounds,
        "bounds_error": _vec3(size_error.get("aabb_absolute_error_m"), f"{asset_id}.aabb_absolute_error_m"),
        "cavity": cavity,
        "volume_ratio": candidate_volume / source_aabb_volume if source_aabb_volume > 0 else 0.0,
    }


def compile_ptlc_candidate_manifest(
    repo_root: Path,
    *,
    asset_manifest_value: Mapping[str, Any] | None = None,
    build_report_value: Mapping[str, Any] | None = None,
    collision_qc_value: Mapping[str, Any] | None = None,
    candidate_selection_value: Mapping[str, Any] | None = None,
    candidate_report_values: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile the existing pTLC proxy release into a deterministic candidate manifest."""

    repo_root = repo_root.resolve()
    asset_manifest_path = repo_root / ASSET_MANIFEST
    build_report_path = repo_root / BUILD_REPORT
    collision_qc_path = repo_root / COLLISION_QC
    generator_path = repo_root / PROXY_GENERATOR
    implementation_path = repo_root / IMPLEMENTATION
    selection_path = repo_root / CANDIDATE_SELECTION

    asset_manifest = (
        dict(asset_manifest_value)
        if asset_manifest_value is not None
        else _read_json(asset_manifest_path, "pTLC asset manifest")
    )
    build_report = (
        dict(build_report_value)
        if build_report_value is not None
        else _read_json(build_report_path, "pTLC proxy build report")
    )
    collision_qc = (
        dict(collision_qc_value)
        if collision_qc_value is not None
        else _read_json(collision_qc_path, "pTLC collision QC")
    )
    candidate_selection = (
        dict(candidate_selection_value)
        if candidate_selection_value is not None
        else _read_json(selection_path, "collision candidate selection")
    )

    convention = _mapping(asset_manifest.get("coordinate_convention"), "coordinate_convention")
    if convention.get("visual_glb") != "meters, Z-up, footprint-center origin, bottom Z=0":
        raise CollisionManifestError("pTLC visual_glb 坐标约定漂移")
    if convention.get("collision_stl") != "millimeters, Z-up, footprint-center origin, bottom Z=0":
        raise CollisionManifestError("pTLC collision_stl 坐标约定漂移")
    if asset_manifest.get("purpose") != "pTLC lab layout reconstruction; simulation_proxy_only":
        raise CollisionManifestError("pTLC proxy purpose 不能升级或漂移")

    _validate_global_qc(collision_qc)
    selections = _selection_by_asset_id(candidate_selection, "eit-ptlc-historical-v1")
    specs, pointers = _candidate_specs(asset_manifest)
    build_by_id = _index_by_asset_id(build_report.get("assets"), "proxy_build_report.assets")
    qc_by_id = _index_by_asset_id(collision_qc.get("assets"), "collision_qc.assets")
    expected = set(specs)
    if set(build_by_id) != expected or set(qc_by_id) != expected:
        raise CollisionManifestError("asset manifest、build report 与 collision QC 的资产集合不一致")
    if build_report.get("count") != len(expected) or collision_qc.get("count") != len(expected):
        raise CollisionManifestError("build/QC count 与资产集合不一致")
    if not set(selections).issubset(expected):
        raise CollisionManifestError("collision candidate selection 引用了未知资产")

    asset_manifest_sha = _artifact_digest(asset_manifest_path, "canonical-json-v1")
    generator_sha = _artifact_digest(generator_path, "utf8-lf-v1")
    assets: list[dict[str, Any]] = []
    mode_map = {
        "solid_aabb": "solid-aabb",
        "multi_body_open": "multi-body-open",
        "multi_body_shaped": "multi-body-shaped",
    }

    for asset_id in sorted(expected):
        spec = specs[asset_id]
        build = build_by_id[asset_id]
        qc = qc_by_id[asset_id]
        nominal_m = _vec3(spec.get("dimensions_mm"), f"{asset_id}.dimensions_mm", scale=0.001)
        uncertainty_m = _vec3(
            spec.get("uncertainty_mm"), f"{asset_id}.uncertainty_mm", scale=0.001
        )
        target_mm = _vec3(qc.get("target_dimensions_mm"), f"{asset_id}.target_dimensions_mm")
        if any(abs(value - target) > 1e-9 for value, target in zip(
            _vec3(spec.get("dimensions_mm"), f"{asset_id}.dimensions_mm.raw"),
            target_mm,
        )):
            raise CollisionManifestError(f"{asset_id} nominal 与 QC target 不一致")
        extents_mm = _vec3(qc.get("extents_mm"), f"{asset_id}.extents_mm")
        build_extents_m = _vec3(build.get("visual_extents_m"), f"{asset_id}.visual_extents_m")
        if any(abs(value - target) > 1e-9 for value, target in zip(build_extents_m, nominal_m)):
            raise CollisionManifestError(f"{asset_id} visual extents 与 nominal 不一致")
        if qc.get("bounds_match_target") is not True:
            raise CollisionManifestError(f"{asset_id} collision bounds QC 未通过")
        if qc.get("watertight_after_stl_reload") is not True:
            raise CollisionManifestError(f"{asset_id} collision 不是 watertight")
        open_expected = qc.get("open_cavity_expected")
        open_preserved = qc.get("open_cavity_preserved")
        if not isinstance(open_expected, bool):
            raise CollisionManifestError(f"{asset_id} open_cavity_expected 无效")
        if open_expected and open_preserved is not True:
            raise CollisionManifestError(f"{asset_id} 开放空腔未保留")
        if open_expected and qc.get("source_components_aabb_disjoint") is not True:
            raise CollisionManifestError(f"{asset_id} 开放碰撞子体意外重叠")

        mode = _text(qc.get("collision_mode"), f"{asset_id}.collision_mode")
        if mode not in mode_map or build.get("collision_mode") != mode:
            raise CollisionManifestError(f"{asset_id} collision_mode 不支持或 build/QC 不一致")
        component_count = qc.get("component_count")
        if (
            isinstance(component_count, bool)
            or not isinstance(component_count, int)
            or component_count < 1
            or build.get("collision_component_count") != component_count
        ):
            raise CollisionManifestError(f"{asset_id} component_count 无效或不一致")

        visual_path = repo_root / PROXY_ROOT / asset_id / "visual.glb"
        collision_path = repo_root / PROXY_ROOT / asset_id / "collision.stl"
        expected_visual = f"pTLC仿真资产/proxies/{asset_id}/visual.glb"
        expected_collision = f"pTLC仿真资产/proxies/{asset_id}/collision.stl"
        if build.get("visual_glb") != expected_visual or build.get("collision_stl") != expected_collision:
            raise CollisionManifestError(f"{asset_id} build report 路径不符合冻结布局")
        if qc.get("collision_stl") != expected_collision:
            raise CollisionManifestError(f"{asset_id} QC collision 路径不符合冻结布局")
        _verify_glb(visual_path)
        _verify_collision_file(collision_path)

        collision_bounds = _bounds(qc.get("bounds_mm"), f"{asset_id}.bounds_mm", scale=0.001)
        nominal_bounds = {
            "min_m": [round(-nominal_m[0] / 2.0, 12), round(-nominal_m[1] / 2.0, 12), 0.0],
            "max_m": [round(nominal_m[0] / 2.0, 12), round(nominal_m[1] / 2.0, 12), nominal_m[2]],
        }
        bounds_error = [
            round(abs(actual * 0.001 - target * 0.001), 12)
            for actual, target in zip(extents_mm, target_mm)
        ]
        volume_ratio = qc.get("summed_component_volume_ratio")
        if isinstance(volume_ratio, bool) or not isinstance(volume_ratio, (int, float)):
            raise CollisionManifestError(f"{asset_id} volume ratio 无效")
        source_disjoint = qc.get("source_components_aabb_disjoint")
        if not isinstance(source_disjoint, bool):
            raise CollisionManifestError(f"{asset_id} source_components_aabb_disjoint 无效")

        selected: dict[str, Any] | None = None
        if asset_id in selections:
            selected = _selected_candidate(
                repo_root,
                asset_id,
                selections[asset_id],
                report_value=(candidate_report_values or {}).get(asset_id),
            )

        role = "stored-tool" if asset_id.startswith("tool_") and asset_id != "tool_station" else "static-environment"
        frame = {
            "frame_id": f"asset:{asset_id}:local",
            "unit": "m",
            "up_axis": "+Z",
            "handedness": "right-handed",
            "origin_convention": "footprint-center-bottom-z0",
        }
        assets.append(
            {
                "asset_id": asset_id,
                "entity_id": f"ptlc.proxy:{asset_id}",
                "role": role,
                "source": {
                    "kind": "parametric-spec",
                    "artifact_ref": ASSET_MANIFEST.as_posix(),
                    "artifact_digest_mode": "canonical-json-v1",
                    "artifact_sha256": asset_manifest_sha,
                    "parameter_pointer": pointers[asset_id],
                    "parameter_digest": _document_digest(dict(spec)),
                },
                "frame": frame,
                "nominal_dimensions_m": nominal_m,
                "visual": {
                    "path": _relative(repo_root, visual_path),
                    "sha256": _sha256(visual_path),
                    "format": "glb",
                    "source_unit": "m",
                    "local_aabb_m": nominal_bounds,
                },
                "broad_phase": {"kind": "aabb", "local_aabb_m": nominal_bounds},
                "narrow_phase": (
                    {
                        "path": _relative(repo_root, selected["runtime_path"]),
                        "sha256": _sha256(selected["runtime_path"]),
                        "format": "stl",
                        "source_unit": "m",
                        "local_aabb_m": selected["local_bounds"],
                        "representation": selected["representation"],
                        "component_count": selected["component_count"],
                        "component_triangle_counts": selected["component_triangle_counts"],
                        "watertight": selected["watertight"],
                    }
                    if selected is not None
                    else {
                        "path": _relative(repo_root, collision_path),
                        "sha256": _sha256(collision_path),
                        "format": "stl",
                        "source_unit": "mm",
                        "local_aabb_m": {
                            "min_m": collision_bounds[0],
                            "max_m": collision_bounds[1],
                        },
                        "representation": mode_map[mode],
                        "component_count": component_count,
                        "watertight": True,
                    }
                ),
                "derivation": (
                    {
                        "algorithm": "source-geometry-collision-candidate-selection",
                        "algorithm_version": selected["generator_version"],
                        "generator_ref": CANDIDATE_GENERATOR.as_posix(),
                        "generator_digest_mode": "utf8-lf-v1",
                        "generator_sha256": selected["generator_sha"],
                    }
                    if selected is not None
                    else {
                        "algorithm": "ptlc-parametric-visual-and-structural-collision",
                        "algorithm_version": "v1",
                        "generator_ref": PROXY_GENERATOR.as_posix(),
                        "generator_digest_mode": "utf8-lf-v1",
                        "generator_sha256": generator_sha,
                    }
                ),
                "uncertainty_m_xyz": uncertainty_m,
                "qc": (
                    {
                        "bounds_abs_error_m_xyz": selected["bounds_error"],
                        "bounds_match_nominal": True,
                        "open_cavity_expected": open_expected,
                        "open_cavity_preserved": selected["cavity"].get("cavity_preserved"),
                        "source_components_disjoint": selected["cavity"].get("component_separation_preserved") is True,
                        "summed_component_volume_ratio": round(float(selected["volume_ratio"]), 12),
                        "method": _text(selected["cavity"].get("metric"), f"{asset_id}.candidate.cavity.metric"),
                    }
                    if selected is not None
                    else {
                        "bounds_abs_error_m_xyz": bounds_error,
                        "bounds_match_nominal": True,
                        "open_cavity_expected": open_expected,
                        "open_cavity_preserved": open_preserved,
                        "source_components_disjoint": source_disjoint,
                        "summed_component_volume_ratio": round(float(volume_ratio), 12),
                        "method": _text(qc.get("cavity_check"), f"{asset_id}.cavity_check"),
                    }
                ),
                "qualification": "collision-candidate",
                "reason_codes": [
                    "collision-candidate-not-qualified",
                    "photo-and-point-derived-not-metrology",
                    "world-registration-not-qualified",
                ],
            }
        )

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "manifest_id": "collision-geometry-manifest:eit-ptlc-proxies/v1",
        "sample_id": "eit-ptlc-historical-v1",
        "qualification": "collision-candidate",
        "allowed_uses": ["offline-review", "shadow"],
        "frame": {
            "frame_id": "ptlc.proxy-assets.local-v1",
            "unit": "m",
            "up_axis": "+Z",
            "handedness": "right-handed",
            "origin_convention": "per-asset-footprint-center-bottom-z0",
        },
        "source_artifacts": [
            {
                "role": "asset-manifest",
                "path": ASSET_MANIFEST.as_posix(),
                "digest_mode": "canonical-json-v1",
                "sha256": asset_manifest_sha,
            },
            {
                "role": "proxy-build-report",
                "path": BUILD_REPORT.as_posix(),
                "digest_mode": "canonical-json-v1",
                "sha256": _artifact_digest(build_report_path, "canonical-json-v1"),
            },
            {
                "role": "collision-qc",
                "path": COLLISION_QC.as_posix(),
                "digest_mode": "canonical-json-v1",
                "sha256": _artifact_digest(collision_qc_path, "canonical-json-v1"),
            },
            {
                "role": "collision-candidate-selection",
                "path": CANDIDATE_SELECTION.as_posix(),
                "digest_mode": "canonical-json-v1",
                "sha256": _artifact_digest(selection_path, "canonical-json-v1"),
            },
            *[
                artifact
                for asset_id in sorted(selections)
                for artifact in (
                    {
                        "role": f"collision-candidate-report:{asset_id}",
                        "path": _relative(
                            repo_root,
                            repo_root / _text(selections[asset_id].get("report_path"), f"{asset_id}.report_path"),
                        ),
                        "digest_mode": "canonical-json-v1",
                        "sha256": _artifact_digest(
                            repo_root / _text(selections[asset_id].get("report_path"), f"{asset_id}.report_path"),
                            "canonical-json-v1",
                        ),
                    },
                    {
                        "role": f"collision-runtime-geometry:{asset_id}",
                        "path": next(item for item in assets if item["asset_id"] == asset_id)["narrow_phase"]["path"],
                        "digest_mode": "raw-bytes",
                        "sha256": next(item for item in assets if item["asset_id"] == asset_id)["narrow_phase"]["sha256"],
                    },
                )
            ],
        ],
        "generator": {
            "algorithm": ALGORITHM,
            "version": ALGORITHM_VERSION,
            "implementation_path": IMPLEMENTATION.as_posix(),
            "implementation_digest_mode": "utf8-lf-v1",
            "implementation_sha256": _artifact_digest(implementation_path, "utf8-lf-v1"),
        },
        "assets": assets,
        "capabilities": {
            "render": True,
            "broad_phase": True,
            "narrow_phase": True,
            "dynamic_links": False,
            "collision_qualified": False,
        },
        "limitations": [
            "mixed-parametric-and-source-glb-derived-candidates",
            "dynamic-robot-links-not-in-this-manifest",
            "nominal-shape-and-uncertainty-are-recorded-separately",
            "photo-and-point-derived-dimensions-are-not-metrology",
            "workcell-world-registration-not-qualified",
        ],
    }
    manifest["manifest_digest"] = _document_digest(manifest)
    return manifest


def validate_manifest_identity(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != SCHEMA:
        raise CollisionManifestError("manifest schema 无效")
    if manifest.get("qualification") != "collision-candidate":
        raise CollisionManifestError("pTLC 第一纵切只能发布 collision-candidate")
    if "software-admission" in _sequence(manifest.get("allowed_uses"), "allowed_uses"):
        raise CollisionManifestError("collision-candidate 禁止 software-admission")
    capabilities = _mapping(manifest.get("capabilities"), "capabilities")
    if capabilities.get("collision_qualified") is not False:
        raise CollisionManifestError("candidate manifest 不能声明 collision_qualified")
    assets = _sequence(manifest.get("assets"), "assets")
    ids = [_text(_mapping(item, "asset").get("asset_id"), "asset.asset_id") for item in assets]
    if len(ids) != len(set(ids)):
        raise CollisionManifestError("manifest asset_id 重复")
    supplied = _text(manifest.get("manifest_digest"), "manifest_digest")
    without_digest = dict(manifest)
    without_digest.pop("manifest_digest", None)
    expected = _document_digest(without_digest)
    if supplied != expected:
        raise CollisionManifestError("manifest_digest 与内容不一致")


def _encoded_document(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail when the checked-in artifact drifts")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    try:
        manifest = compile_ptlc_candidate_manifest(repo_root)
        validate_manifest_identity(manifest)
        payload = _encoded_document(manifest)
        if args.check:
            if not output.is_file():
                raise CollisionManifestError(f"待检查 artifact 不存在: {output}")
            if output.read_bytes() != payload:
                raise CollisionManifestError(f"artifact 漂移，请重新编译: {output}")
        else:
            _write_atomic(output, payload)
    except CollisionManifestError as error:
        sys.stderr.write(f"collision geometry manifest rejected: {error}\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "schema": manifest["schema"],
                "qualification": manifest["qualification"],
                "asset_count": len(manifest["assets"]),
                "manifest_digest": manifest["manifest_digest"],
                "output": _relative(repo_root, output),
                "checked": bool(args.check),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
