#!/usr/bin/env python3
"""Generate conservative L0/L1/L2 collision candidates and an auditable QC report.

GLB is loaded directly.  STEP is bound to its original CAD digest but requires an
explicit GLB tessellation because this implementation does not pretend that a mesh
loader is a B-rep kernel.  All dimensions are normalized to metres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

try:
    import numpy as np
    import trimesh
except ImportError:  # Keep contract tests/discovery usable without geometry extras.
    np = None
    trimesh = None


REQUEST_SCHEMA = "lab.collision_candidate_request/v1"
REPORT_SCHEMA = "lab.collision_candidate_report/v1"
ASSET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
UNIT_SCALE = {"m": 1.0, "mm": 0.001}


class CollisionCandidateError(RuntimeError):
    """The request, geometry, or quality computation is invalid."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CollisionCandidateError(f"request 不是可读 UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise CollisionCandidateError("request 必须是 JSON 对象")
    return value


def _keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    if missing or unexpected:
        parts = []
        if missing:
            parts.append("缺少 " + ", ".join(missing))
        if unexpected:
            parts.append("不支持 " + ", ".join(unexpected))
        raise CollisionCandidateError(f"{field} 字段错误: {'; '.join(parts)}")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CollisionCandidateError(f"{field} 必须是非空文本")
    return value.strip()


def _relative_file(request_root: Path, value: Any, field: str, suffixes: set[str]) -> Path:
    text = _text(value, field)
    path = Path(text)
    target = path if path.is_absolute() else request_root / path
    target = target.resolve()
    if not target.is_file():
        raise CollisionCandidateError(f"{field} 文件缺失: {target}")
    if target.suffix.lower() not in suffixes:
        raise CollisionCandidateError(f"{field} 文件扩展名不受支持: {target.suffix}")
    return target


def validate_request(request_path: Path) -> dict[str, Any]:
    request = _read_json(request_path)
    _keys(request, {"schema", "asset_id", "source", "policy"}, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise CollisionCandidateError(f"request.schema 必须是 {REQUEST_SCHEMA}")
    asset_id = _text(request.get("asset_id"), "asset_id")
    if ASSET_ID.fullmatch(asset_id) is None:
        raise CollisionCandidateError("asset_id 必须是安全 ASCII slug")
    source = request.get("source")
    if not isinstance(source, dict):
        raise CollisionCandidateError("source 必须是对象")
    kind = source.get("kind")
    root = request_path.resolve().parent
    if kind == "glb":
        _keys(source, {"kind", "path", "unit"}, "source")
        source_path = _relative_file(root, source.get("path"), "source.path", {".glb"})
        unit = source.get("unit")
        if unit not in UNIT_SCALE:
            raise CollisionCandidateError("source.unit 必须是 m 或 mm")
        source_value = {
            "kind": "glb",
            "source_ref": source["path"],
            "source_path": source_path,
            "source_sha256": sha256(source_path),
            "geometry_path": source_path,
            "geometry_ref": source["path"],
            "geometry_sha256": sha256(source_path),
            "geometry_unit": unit,
            "direct_brep_parsed": False,
            "geometry_basis": "source-glb",
        }
    elif kind == "step":
        _keys(source, {"kind", "path", "tessellated_path", "tessellated_unit"}, "source")
        source_path = _relative_file(root, source.get("path"), "source.path", {".step", ".stp"})
        geometry_path = _relative_file(
            root, source.get("tessellated_path"), "source.tessellated_path", {".glb"}
        )
        unit = source.get("tessellated_unit")
        if unit not in UNIT_SCALE:
            raise CollisionCandidateError("source.tessellated_unit 必须是 m 或 mm")
        source_value = {
            "kind": "step",
            "source_ref": source["path"],
            "source_path": source_path,
            "source_sha256": sha256(source_path),
            "geometry_path": geometry_path,
            "geometry_ref": source["tessellated_path"],
            "geometry_sha256": sha256(geometry_path),
            "geometry_unit": unit,
            "direct_brep_parsed": False,
            "geometry_basis": "explicit-step-tessellation-glb",
        }
    else:
        raise CollisionCandidateError("source.kind 必须是 step 或 glb")

    policy = request.get("policy")
    if not isinstance(policy, dict):
        raise CollisionCandidateError("policy 必须是对象")
    required_policy = {
        "l2_mode", "max_components", "max_sample_vertices",
        "cavity_added_fill_ratio_limit",
    }
    allowed_policy = required_policy | {"target_face_ratio"}
    missing_policy = sorted(required_policy - set(policy))
    unexpected_policy = sorted(set(policy) - allowed_policy)
    if missing_policy or unexpected_policy:
        parts = []
        if missing_policy:
            parts.append("缺少 " + ", ".join(missing_policy))
        if unexpected_policy:
            parts.append("不支持 " + ", ".join(unexpected_policy))
        raise CollisionCandidateError("policy 字段错误: " + "; ".join(parts))
    l2_mode = policy.get("l2_mode")
    if l2_mode not in {"compound-convex", "simplified-static-mesh"}:
        raise CollisionCandidateError(
            "l2_mode 必须是 compound-convex 或 simplified-static-mesh"
        )
    max_components = policy.get("max_components")
    max_samples = policy.get("max_sample_vertices")
    cavity_limit = policy.get("cavity_added_fill_ratio_limit")
    if not isinstance(max_components, int) or not 1 <= max_components <= 4096:
        raise CollisionCandidateError("max_components 必须在 1..4096")
    if not isinstance(max_samples, int) or not 8 <= max_samples <= 100000:
        raise CollisionCandidateError("max_sample_vertices 必须在 8..100000")
    if (
        isinstance(cavity_limit, bool)
        or not isinstance(cavity_limit, (int, float))
        or not 0 <= float(cavity_limit) <= 1
    ):
        raise CollisionCandidateError("cavity_added_fill_ratio_limit 必须在 0..1")
    target_ratio = policy.get("target_face_ratio")
    if l2_mode == "simplified-static-mesh":
        if (
            isinstance(target_ratio, bool)
            or not isinstance(target_ratio, (int, float))
            or not 0 < float(target_ratio) <= 1
        ):
            raise CollisionCandidateError(
                "simplified-static-mesh 必须提供 0 < target_face_ratio <= 1"
            )
    elif target_ratio is not None:
        raise CollisionCandidateError(
            "target_face_ratio 只允许用于 simplified-static-mesh"
        )
    return {
        "asset_id": asset_id,
        "source": source_value,
        "policy": {
            "l2_mode": l2_mode,
            "max_components": max_components,
            "max_sample_vertices": max_samples,
            "cavity_added_fill_ratio_limit": float(cavity_limit),
            **(
                {"target_face_ratio": float(target_ratio)}
                if target_ratio is not None
                else {}
            ),
        },
    }


def _require_geometry_dependencies() -> None:
    if np is None or trimesh is None:
        raise CollisionCandidateError(
            "缺少 numpy/trimesh；可用 `uv run --project related/unilabSZlab/asset_pipeline --with scipy python ...`"
        )


def _as_mesh(value):
    if hasattr(value, "to_mesh"):
        value = value.to_mesh()
    if not isinstance(value, trimesh.Trimesh):
        raise CollisionCandidateError(f"几何后端没有返回 Trimesh: {type(value).__name__}")
    return value.copy()


def _load_mesh(path: Path, scale: float):
    _require_geometry_dependencies()
    try:
        scene = trimesh.load(path, force="scene", process=True)
        mesh = scene.to_mesh()
    except Exception as error:
        raise CollisionCandidateError(f"GLB 无法加载: {error}") from error
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.vertices) < 4 or len(mesh.faces) < 4:
        raise CollisionCandidateError("GLB 没有可用三角网格")
    mesh = mesh.copy()
    if scale != 1.0:
        mesh.apply_scale(scale)
    mesh.remove_unreferenced_vertices()
    if not np.isfinite(mesh.vertices).all():
        raise CollisionCandidateError("GLB 顶点含 NaN/Inf")
    if np.any((mesh.bounds[1] - mesh.bounds[0]) <= 0):
        raise CollisionCandidateError("GLB 包围盒必须在三个轴上都有正尺寸")
    return mesh


def _component_count(mesh) -> int:
    return len(mesh.split(only_watertight=False, repair=False, engine="scipy"))


def _watertight_report(mesh) -> dict[str, Any]:
    counts = np.bincount(mesh.edges_unique_inverse) if len(mesh.edges_unique_inverse) else np.array([])
    return {
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        "is_volume": bool(mesh.is_volume),
        "euler_number": int(mesh.euler_number),
        "boundary_edge_count": int(np.count_nonzero(counts == 1)),
        "nonmanifold_edge_count": int(np.count_nonzero(counts > 2)),
    }


def _bounds_report(mesh) -> dict[str, Any]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    size = bounds[1] - bounds[0]
    return {
        "min_m": bounds[0].tolist(),
        "max_m": bounds[1].tolist(),
        "size_m": size.tolist(),
    }


def _geometry_report(mesh) -> dict[str, Any]:
    return {
        "vertices": int(len(mesh.vertices)),
        "triangles": int(len(mesh.faces)),
        "component_count": _component_count(mesh),
        "bounds": _bounds_report(mesh),
        "watertight": _watertight_report(mesh),
        "volume_m3": float(abs(mesh.volume)) if mesh.is_watertight else None,
    }


def _sample_vertices(vertices, limit: int):
    if len(vertices) <= limit:
        return np.asarray(vertices, dtype=float)
    indices = np.linspace(0, len(vertices) - 1, num=limit, dtype=int)
    return np.asarray(vertices, dtype=float)[indices]


def _convex_missed_envelope(source_points, candidate, sample_limit: int) -> dict[str, Any]:
    """Return maximum outward half-space violation over deterministic source samples."""

    points = _sample_vertices(source_points, sample_limit)
    convex = _as_mesh(candidate.convex_hull)
    normals = np.asarray(convex.face_normals, dtype=float)
    origins = np.asarray(convex.triangles[:, 0], dtype=float)
    offsets = np.einsum("ij,ij->i", normals, origins)
    max_violation = 0.0
    for start in range(0, len(points), 256):
        values = points[start : start + 256] @ normals.T - offsets
        max_violation = max(max_violation, float(np.max(values)))
    max_violation = max(0.0, max_violation)
    return {
        "metric": "sampled-convex-halfspace-outward-violation",
        "sample_count": int(len(points)),
        "maximum_missed_envelope_m": max_violation,
        "passes_at_1e-8_m": max_violation <= 1e-8,
        "scope": "source vertices; not continuous CAD surface",
    }


def _compound_missed_envelope(source_components, candidate_components, sample_limit: int) -> dict[str, Any]:
    total_vertices = sum(len(component.vertices) for component in source_components)
    remaining = sample_limit
    maximum = 0.0
    sampled = 0
    for index, (source, candidate) in enumerate(zip(source_components, candidate_components)):
        components_left = len(source_components) - index
        allocation = min(len(source.vertices), max(8, remaining // components_left))
        result = _convex_missed_envelope(source.vertices, candidate, allocation)
        maximum = max(maximum, result["maximum_missed_envelope_m"])
        sampled += result["sample_count"]
        remaining = max(0, remaining - result["sample_count"])
    return {
        "metric": "sampled-per-component-convex-halfspace-outward-violation",
        "sample_count": sampled,
        "available_source_vertex_count": total_vertices,
        "maximum_missed_envelope_m": maximum,
        "passes_at_1e-8_m": maximum <= 1e-8,
        "scope": "source vertices paired to connected-component hulls; not continuous CAD surface",
    }


def _simplified_surface_error(source_points, candidate, sample_limit: int) -> dict[str, Any]:
    """Approximate missed-envelope risk by source-to-candidate vertex distance."""

    try:
        from scipy.spatial import cKDTree
    except ImportError as error:
        raise CollisionCandidateError("simplified-static-mesh QC 需要 scipy") from error
    points = _sample_vertices(source_points, sample_limit)
    tree = cKDTree(np.asarray(candidate.vertices, dtype=float))
    distances, _ = tree.query(points, workers=1)
    maximum = float(np.max(distances)) if len(distances) else 0.0
    return {
        "metric": "sampled-source-to-candidate-vertex-distance",
        "sample_count": int(len(points)),
        "maximum_missed_envelope_m": maximum,
        "passes_at_1e-8_m": maximum <= 1e-8,
        "containment_guarantee": False,
        "scope": "upper-biased vertex-distance approximation; not inside/outside CAD surface classification",
    }


def _size_error(source, candidate) -> dict[str, Any]:
    source_size = np.asarray(source.bounds[1] - source.bounds[0], dtype=float)
    candidate_size = np.asarray(candidate.bounds[1] - candidate.bounds[0], dtype=float)
    absolute = np.abs(candidate_size - source_size)
    relative = absolute / np.maximum(source_size, 1e-15)
    try:
        source_obb = np.sort(np.asarray(source.bounding_box_oriented.primitive.extents, dtype=float))
        candidate_obb = np.sort(np.asarray(candidate.bounding_box_oriented.primitive.extents, dtype=float))
        obb_absolute = np.abs(candidate_obb - source_obb)
    except Exception:
        source_obb = candidate_obb = obb_absolute = None
    return {
        "aabb_source_size_m": source_size.tolist(),
        "aabb_candidate_size_m": candidate_size.tolist(),
        "aabb_absolute_error_m": absolute.tolist(),
        "aabb_max_relative_error": float(np.max(relative)),
        "obb_source_extents_sorted_m": source_obb.tolist() if source_obb is not None else None,
        "obb_candidate_extents_sorted_m": candidate_obb.tolist() if candidate_obb is not None else None,
        "obb_absolute_error_sorted_m": obb_absolute.tolist() if obb_absolute is not None else None,
    }


def _cavity_report(source, candidate, ratio_limit: float) -> dict[str, Any]:
    envelope_size = np.asarray(source.bounds[1] - source.bounds[0], dtype=float)
    envelope_volume = float(np.prod(envelope_size))
    source_component_count = _component_count(source)
    candidate_component_count = _component_count(candidate)
    base = {
        "metric": "added-solid-volume-fraction-of-source-aabb",
        "limit": ratio_limit,
        "source_aabb_volume_m3": envelope_volume,
        "source_component_count": source_component_count,
        "candidate_component_count": candidate_component_count,
        "component_separation_preserved": candidate_component_count == source_component_count,
    }
    if not source.is_watertight or not candidate.is_watertight:
        return {
            **base,
            "status": "not-measurable",
            "cavity_preserved": None,
            "reason": "source and candidate must both be watertight for volume-based cavity QC",
            "source_volume_m3": float(abs(source.volume)) if source.is_watertight else None,
            "candidate_volume_m3": float(abs(candidate.volume)) if candidate.is_watertight else None,
            "added_solid_volume_m3": None,
            "added_fill_ratio": None,
        }
    source_volume = float(abs(source.volume))
    candidate_volume = float(abs(candidate.volume))
    added = max(0.0, candidate_volume - source_volume)
    ratio = added / max(envelope_volume, 1e-15)
    preserved = ratio <= ratio_limit
    return {
        **base,
        "status": "preserved" if preserved else "not-preserved",
        "cavity_preserved": preserved,
        "reason": "candidate added solid volume is within limit" if preserved else "candidate fills too much source-envelope empty space",
        "source_volume_m3": source_volume,
        "candidate_volume_m3": candidate_volume,
        "added_solid_volume_m3": added,
        "added_fill_ratio": ratio,
    }


def _export_glb(path: Path, named_meshes: list[tuple[str, Any]]) -> str:
    scene = trimesh.Scene()
    for name, mesh in named_meshes:
        scene.add_geometry(_as_mesh(mesh), geom_name=name, node_name=name)
    payload = scene.export(file_type="glb")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256(path)


def _export_binary_stl(path: Path, mesh) -> str:
    """Export the exact runtime triangles in metres for dependency-free consumers."""

    payload = trimesh.exchange.stl.export_stl(_as_mesh(mesh))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256(path)


def _multi_sphere_cover(
    source_components: list[Any], sample_limit: int, cavity_limit: float
) -> tuple[list[dict[str, Any]], list[tuple[str, Any]], dict[str, Any]]:
    """Build one conservative analytic bounding sphere per connected component.

    The GLB meshes are previews only. Runtime consumers must use the analytic JSON
    centres and radii so tessellation cannot introduce a missed envelope.
    """

    spheres: list[dict[str, Any]] = []
    previews: list[tuple[str, Any]] = []
    maximum_missed = 0.0
    sampled = 0
    preview_meshes: list[Any] = []
    for index, component in enumerate(source_components):
        bounding = component.bounding_sphere
        center = np.asarray(bounding.primitive.center, dtype=float)
        radius = float(bounding.primitive.radius)
        if not np.isfinite(center).all() or not math.isfinite(radius) or radius <= 0:
            raise CollisionCandidateError(f"multi-sphere component {index} 拟合无效")
        points = _sample_vertices(component.vertices, max(8, sample_limit // len(source_components)))
        violations = np.linalg.norm(points - center, axis=1) - radius
        maximum_missed = max(maximum_missed, float(max(0.0, np.max(violations))))
        sampled += int(len(points))
        preview = trimesh.creation.icosphere(subdivisions=2, radius=radius)
        preview.apply_translation(center)
        preview_meshes.append(preview)
        previews.append((f"sphere-component-{index:04d}", preview))
        spheres.append(
            {
                "sphere_id": f"sphere-component-{index:04d}",
                "source_component_index": index,
                "center_m": [float(value) for value in center],
                "radius_m": radius,
            }
        )

    source_aabb_volume = float(np.prod(source_components[0].bounds[1] - source_components[0].bounds[0]))
    source_mesh = trimesh.util.concatenate(source_components)
    source_aabb_volume = float(np.prod(source_mesh.bounds[1] - source_mesh.bounds[0]))
    source_volume = float(abs(source_mesh.volume)) if source_mesh.is_watertight else None
    sphere_volume = sum(4.0 * math.pi * sphere["radius_m"] ** 3 / 3.0 for sphere in spheres)
    added = max(0.0, sphere_volume - source_volume) if source_volume is not None else None
    added_ratio = added / max(source_aabb_volume, 1e-15) if added is not None else None
    preserved = added_ratio is not None and added_ratio <= cavity_limit
    preview_mesh = trimesh.util.concatenate(preview_meshes)
    report = {
        "method": "per-connected-component-minimum-enclosing-sphere",
        "geometry": {
            **_geometry_report(preview_mesh),
            "analytic_primitive": "sphere-set",
            "primitive_count": len(spheres),
            "preview_tessellation_only": True,
        },
        "missed_envelope": {
            "metric": "sampled-point-to-analytic-sphere-outward-violation",
            "sample_count": sampled,
            "maximum_missed_envelope_m": maximum_missed,
            "passes_at_1e-8_m": maximum_missed <= 1e-8,
            "containment_basis": "analytic-spheres-not-preview-triangles",
            "scope": "source vertices paired to connected-component bounding spheres",
        },
        "cavity_preservation": {
            "metric": "summed-sphere-volume-addition-fraction-of-source-aabb",
            "limit": cavity_limit,
            "source_aabb_volume_m3": source_aabb_volume,
            "source_component_count": len(source_components),
            "candidate_component_count": len(spheres),
            "component_separation_preserved": True,
            "status": "preserved" if preserved else "not-preserved",
            "cavity_preserved": preserved,
            "reason": (
                "summed analytic sphere volume is within limit"
                if preserved
                else "analytic sphere cover overfills source-envelope empty space"
            ),
            "source_volume_m3": source_volume,
            "candidate_volume_m3": sphere_volume,
            "added_solid_volume_m3": added,
            "added_fill_ratio": added_ratio,
            "volume_scope": "summed primitive volumes; overlaps are not boolean-unioned",
        },
        "fallbacks": [],
    }
    return spheres, previews, report


def _export_multi_sphere_json(path: Path, spheres: list[dict[str, Any]]) -> str:
    payload = {
        "schema": "lab.multi-sphere-collision/v1",
        "unit": "m",
        "primitive_count": len(spheres),
        "spheres": spheres,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return sha256(path)


def _candidate_record(
    *,
    source,
    candidate,
    path: Path,
    method: str,
    missed: dict[str, Any],
    cavity_limit: float,
    fallbacks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "method": method,
        "path": "/".join(path.parts[-2:]),
        "sha256": sha256(path),
        "geometry": _geometry_report(candidate),
        "size_error": _size_error(source, candidate),
        "missed_envelope": missed,
        "cavity_preservation": _cavity_report(source, candidate, cavity_limit),
        "fallbacks": fallbacks or [],
    }


def _hull_or_box(mesh, label: str):
    try:
        return _as_mesh(mesh.convex_hull), None
    except Exception as error:
        return _as_mesh(mesh.bounding_box), f"{label}: convex hull failed; used AABB ({type(error).__name__})"


def generate(request_path: Path, output_dir: Path) -> dict[str, Any]:
    _require_geometry_dependencies()
    request = validate_request(request_path)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CollisionCandidateError("output-dir 必须不存在或为空，禁止覆盖已有候选证据")
    source_info = request["source"]
    source = _load_mesh(source_info["geometry_path"], UNIT_SCALE[source_info["geometry_unit"]])
    policy = request["policy"]
    sample_limit = policy["max_sample_vertices"]
    cavity_limit = policy["cavity_added_fill_ratio_limit"]

    aabb = _as_mesh(source.bounding_box)
    obb = _as_mesh(source.bounding_box_oriented)
    primitives: list[tuple[str, Any]] = [("box", obb)]
    primitive_failures: list[str] = []
    for name, getter in (
        ("sphere", lambda: source.bounding_sphere),
        ("cylinder", lambda: source.bounding_cylinder),
    ):
        try:
            primitives.append((name, _as_mesh(getter())))
        except Exception as error:
            primitive_failures.append(f"{name} unavailable: {type(error).__name__}")
    primitive_name, primitive = min(primitives, key=lambda item: abs(item[1].volume))
    hull, hull_fallback = _hull_or_box(source, "l1")
    l2_mode = policy["l2_mode"]
    source_components = None
    compound_components = None
    compound_fallbacks: list[str] = []
    multi_sphere_data = None
    multi_sphere_previews = None
    multi_sphere_report = None
    if l2_mode == "compound-convex":
        source_components = list(
            source.split(only_watertight=False, repair=False, engine="scipy")
        )
        if len(source_components) > policy["max_components"]:
            raise CollisionCandidateError(
                f"source component 数 {len(source_components)} 超过 max_components={policy['max_components']}"
            )
        compound_components = []
        for index, component in enumerate(source_components):
            hull_component, fallback = _hull_or_box(component, f"l2 component {index}")
            compound_components.append(hull_component)
            if fallback:
                compound_fallbacks.append(fallback)
        l2_candidate = trimesh.util.concatenate(compound_components)
        l2_filename = "compound-convex.glb"
        l2_method = "connected-component-convex-hulls"
        l2_missed = _compound_missed_envelope(
            source_components, compound_components, sample_limit
        )
        l2_named_meshes = [
            (f"convex-component-{index:04d}", mesh)
            for index, mesh in enumerate(compound_components)
        ]
        l2_key = "compound_convex"
        multi_sphere_data, multi_sphere_previews, multi_sphere_report = _multi_sphere_cover(
            source_components, sample_limit, cavity_limit
        )
    else:
        target_faces = max(4, int(math.ceil(len(source.faces) * policy["target_face_ratio"])))
        try:
            l2_candidate = source.simplify_quadric_decimation(face_count=target_faces)
        except ModuleNotFoundError as error:
            raise CollisionCandidateError(
                "simplified-static-mesh 需要 fast-simplification；uv 增加 `--with fast-simplification`"
            ) from error
        except Exception as error:
            raise CollisionCandidateError(f"静态网格简化失败: {error}") from error
        l2_candidate = _as_mesh(l2_candidate)
        l2_filename = "simplified-static-mesh.glb"
        l2_method = "quadric-decimation-static-mesh"
        l2_missed = _simplified_surface_error(source.vertices, l2_candidate, sample_limit)
        l2_named_meshes = [("simplified-static-mesh", l2_candidate)]
        l2_key = "simplified_static_mesh"

    # No files are written until every level has been constructed successfully.
    output_dir.mkdir(parents=True, exist_ok=True)
    aabb_path = output_dir / "l0" / "aabb.glb"
    obb_path = output_dir / "l0" / "obb.glb"
    primitive_path = output_dir / "l1" / "best-primitive.glb"
    hull_path = output_dir / "l1" / "convex-hull.glb"
    multi_sphere_preview_path = output_dir / "l1" / "multi-sphere-cover.glb"
    multi_sphere_runtime_path = output_dir / "l1" / "multi-sphere-cover.json"
    l2_path = output_dir / "l2" / l2_filename
    l2_runtime_path = output_dir / "l2" / l2_filename.replace(".glb", ".runtime.stl")
    _export_glb(aabb_path, [("aabb", aabb)])
    _export_glb(obb_path, [("obb", obb)])
    _export_glb(primitive_path, [(f"best-{primitive_name}", primitive)])
    _export_glb(hull_path, [("convex-hull", hull)])
    _export_glb(l2_path, l2_named_meshes)
    if multi_sphere_data is not None and multi_sphere_previews is not None:
        _export_glb(multi_sphere_preview_path, multi_sphere_previews)
        _export_multi_sphere_json(multi_sphere_runtime_path, multi_sphere_data)
    _export_binary_stl(l2_runtime_path, l2_candidate)

    l0 = {
        "aabb": _candidate_record(
            source=source,
            candidate=aabb,
            path=aabb_path,
            method="axis-aligned-bounding-box",
            missed=_convex_missed_envelope(source.vertices, aabb, sample_limit),
            cavity_limit=cavity_limit,
        ),
        "obb": _candidate_record(
            source=source,
            candidate=obb,
            path=obb_path,
            method="oriented-bounding-box",
            missed=_convex_missed_envelope(source.vertices, obb, sample_limit),
            cavity_limit=cavity_limit,
        ),
    }
    l1 = {
        "best_primitive": _candidate_record(
            source=source,
            candidate=primitive,
            path=primitive_path,
            method=f"minimum-volume-bounding-{primitive_name}",
            missed=_convex_missed_envelope(source.vertices, primitive, sample_limit),
            cavity_limit=cavity_limit,
            fallbacks=primitive_failures,
        ),
        "convex_hull": _candidate_record(
            source=source,
            candidate=hull,
            path=hull_path,
            method="whole-mesh-convex-hull",
            missed=_convex_missed_envelope(source.vertices, hull, sample_limit),
            cavity_limit=cavity_limit,
            fallbacks=[hull_fallback] if hull_fallback else [],
        ),
    }
    if multi_sphere_report is not None:
        multi_sphere_report["path"] = "l1/multi-sphere-cover.glb"
        multi_sphere_report["sha256"] = sha256(multi_sphere_preview_path)
        multi_sphere_report["runtime_artifact"] = {
            "path": "l1/multi-sphere-cover.json",
            "sha256": sha256(multi_sphere_runtime_path),
            "format": "json",
            "source_unit": "m",
        }
        multi_sphere_report["size_error"] = _size_error(source, trimesh.util.concatenate(
            [mesh for _, mesh in multi_sphere_previews]
        ))
        l1["multi_sphere"] = multi_sphere_report
    l2 = {
        l2_key: _candidate_record(
            source=source,
            candidate=l2_candidate,
            path=l2_path,
            method=l2_method,
            missed=l2_missed,
            cavity_limit=cavity_limit,
            fallbacks=compound_fallbacks,
        )
    }
    l2[l2_key]["runtime_artifact"] = {
        "path": f"l2/{l2_runtime_path.name}",
        "sha256": sha256(l2_runtime_path),
        "format": "stl",
        "source_unit": "m",
        "representation": (
            "compound-convex" if l2_mode == "compound-convex" else "simplified-static-mesh"
        ),
        "component_triangle_counts": [
            int(len(mesh.faces)) for _, mesh in l2_named_meshes
        ],
    }
    output_files = [aabb_path, obb_path, primitive_path, hull_path, l2_path, l2_runtime_path]
    if multi_sphere_data is not None:
        output_files.extend([multi_sphere_preview_path, multi_sphere_runtime_path])
    report = {
        "schema": REPORT_SCHEMA,
        "status": "candidate-generated",
        "qualification": "offline-collision-candidate",
        "asset_id": request["asset_id"],
        "request_sha256": sha256(request_path),
        "generator": {
            "name": "unilab-generic-collision-candidate-generator",
            "version": "v3",
            "script_ref": "scripts/generate_collision_candidates.py",
            "script_sha256": sha256(Path(__file__).resolve()),
            "numpy_version": np.__version__,
            "trimesh_version": trimesh.__version__,
        },
        "source": {
            key: value
            for key, value in source_info.items()
            if key not in {"source_path", "geometry_path"}
        },
        "policy": policy,
        "source_geometry": _geometry_report(source),
        "levels": {"l0": l0, "l1": l1, "l2": l2},
        "files": [
            {"path": path.relative_to(output_dir).as_posix(), "sha256": sha256(path)}
            for path in output_files
        ],
        "not_qualified_for": [
            "automatic-admission", "continuous-collision", "robot-execution",
            "hardware-safety-interlock", "deployment",
        ],
    }
    report_path = output_dir / "collision-candidate-report.json"
    report_path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="validate request and dependencies without writing")
    args = parser.parse_args()
    try:
        if args.check:
            _require_geometry_dependencies()
            value = validate_request(args.request)
            result = {
                "passed": True,
                "effect": "none",
                "asset_id": value["asset_id"],
                "source_kind": value["source"]["kind"],
            }
        else:
            report = generate(args.request, args.output_dir)
            result = {
                "passed": True,
                "status": report["status"],
                "asset_id": report["asset_id"],
                "report": str(args.output_dir / "collision-candidate-report.json"),
            }
    except CollisionCandidateError as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
