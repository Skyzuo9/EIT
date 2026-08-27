"""Verified, display-only feeding-station projection for UniLab Workbench.

The projection deliberately keeps the P1 render GLB intact.  P2 decomposition
is consumed as evidence and metadata only until a mechanical/CAD reviewer
approves the family boundaries.  Nothing in this module grants W2, collision,
interlock, calibration, or hardware-execution qualification.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


STATION_MATERIAL_UUID = "c1000000-0000-4000-8000-000000000001"
STATION_TEMPLATE_UUID = "c2000000-0000-4000-8000-000000000001"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class StationPreview:
    """A digest-locked station GLB plus its non-publishable P2 receipt."""

    root: Path
    receipt_path: Path
    model_path: Path
    station: str
    run_id: str
    geometry_sha256: str
    layout_sha256: str
    decomposition_sha256: str
    handoff_sha256: str
    geometry: Mapping[str, Any]
    coverage: Mapping[str, Any]
    robot: Mapping[str, Any]
    four_ml_representative: Mapping[str, Any]

    def descriptor(self) -> dict[str, Any]:
        """Return the evidence-bounded public preview contract."""

        bounds = self.geometry["bounding_box_m"]
        low = bounds["min"]
        high = bounds["max"]
        size = bounds["size"]
        # The SolidWorks GLB is Z-up while Pascal/Three is Y-up.  Recenter the
        # horizontal footprint and place the audited minimum Z on the floor.
        model_position = [
            -((float(low[0]) + float(high[0])) / 2.0),
            -float(low[2]),
            (float(low[1]) + float(high[1])) / 2.0,
        ]
        dimensions_mm = [
            float(size[0]) * 1000.0,
            float(size[2]) * 1000.0,
            float(size[1]) * 1000.0,
        ]
        return {
            "schema": "lab.station_workbench_preview/v0",
            "station": self.station,
            "run_id": self.run_id,
            "material_uuid": STATION_MATERIAL_UUID,
            "display_name": "投料站（P1 几何 + P2 草案）",
            "qualification": "static-asset-pipeline-preview",
            "model": {
                "path": "/api/v1/station-preview/model.glb",
                "format": "gltf",
                "version": f"{self.geometry_sha256}:{self.layout_sha256}",
                "position": model_position,
                "rotation": [-math.pi / 2.0, 0.0, 0.0],
                "attachPoints": [],
            },
            "rendering": {
                "dimensionsMm": dimensions_mm,
                "footprintMm": [dimensions_mm[0], dimensions_mm[2]],
                "source_coordinate_frame": "solidworks-z-up",
                "workbench_coordinate_frame": "pascal-y-up",
            },
            "geometry": dict(self.geometry),
            "p2_draft": {
                "layout_sha256": self.layout_sha256,
                "decomposition_sha256": self.decomposition_sha256,
                "source_handoff_sha256": self.handoff_sha256,
                "exact_coverage": self.coverage["exact_coverage"],
                "occurrence_count": self.coverage["occurrence_count"],
                "assigned_occurrence_count": self.coverage[
                    "assigned_occurrence_count"
                ],
                "placement_count": self.coverage["placement_count"],
                "unassigned_occurrence_count": 0,
                "overlapping_occurrence_count": 0,
                "human_reviewed": False,
                "publication_eligible": False,
            },
            "identified_assets": {
                "robot": dict(self.robot),
                "four_ml_representative": dict(self.four_ml_representative),
            },
            "capability": {
                "grade": "static-asset-pipeline-preview",
                "display": True,
                "stable_picking": True,
                "motion_preview": False,
                "hardware_execution": False,
                "spatial_interlock_enforced": False,
                "collision_qualified": False,
                "w2_eligible": False,
                "reason": (
                    "P1 GLB 已摘要锁定且 P2 草案实现 2021/2021 唯一覆盖；"
                    "设备/family 边界、GCR5 厂家参数、4 ml 物理槽位及碰撞几何仍待审核。"
                ),
            },
        }

    def material_graph_node(self) -> dict[str, Any]:
        """Project the station into the normal Material Graph wire format."""

        descriptor = self.descriptor()
        dimensions = descriptor["rendering"]["dimensionsMm"]
        timestamp = "2026-08-28T00:00:00Z"
        return {
            "material": {
                "uuid": STATION_MATERIAL_UUID,
                "resource_template_uuid": STATION_TEMPLATE_UUID,
                "type": "device",
                "barcode": f"preview-{self.run_id}",
                "name": descriptor["display_name"],
                "description": "摘要锁定的投料站资产管线静态预览；不是部署清单",
                "config": {
                    "category": "feeding-station",
                    "rendering": {
                        "kind": "feeding-station",
                        "materialKind": "device",
                        "dimensionsMm": dimensions,
                        "footprintMm": descriptor["rendering"]["footprintMm"],
                        "model": descriptor["model"],
                    },
                    "asset_pipeline": descriptor["p2_draft"],
                    "identified_assets": descriptor["identified_assets"],
                    "capability": descriptor["capability"],
                },
                "meta_data": {
                    "source_node_id": self.station,
                    "run_id": self.run_id,
                    "preview_only": True,
                    "p2_draft": True,
                    "not_a_deploy_manifest": True,
                    "not_a_workcell_activation": True,
                },
                "parent_uuid": None,
                "revision": 1,
                "create_time": timestamp,
                "update_time": timestamp,
            },
            "relative_position": {
                "material_uuid": STATION_MATERIAL_UUID,
                "position_x": 0.0,
                "position_y": 0.0,
                "position_z": 0.0,
                "rotation_x": 0.0,
                "rotation_y": 0.0,
                "rotation_z": 0.0,
                "width": dimensions[0],
                "depth": dimensions[2],
                "length": dimensions[1],
            },
            "current_site_uuid": None,
            "sites": [],
            "resource_template": {
                "uuid": STATION_TEMPLATE_UUID,
                "name": "preview.eit.feeding-station",
                "display_name": descriptor["display_name"],
                "resource_type": "device",
            },
        }


def load_station_preview(root: Path, receipt_path: Path) -> StationPreview:
    """Load and fail-close validate the local station preview assets."""

    root = root.resolve()
    receipt_path = receipt_path.resolve()
    receipt = _read_json(receipt_path, "preview receipt")
    _require(receipt.get("schema") == "lab.station_workbench_preview_receipt/v0", "preview receipt schema 无效")
    station = _nonempty_string(receipt.get("station"), "receipt.station")
    run_id = _nonempty_string(receipt.get("run_id"), "receipt.run_id")
    files = _mapping(receipt.get("files"), "receipt.files")

    resolved: dict[str, Path] = {}
    digests: dict[str, str] = {}
    for key in ("station_handoff", "decomposition", "layout", "coverage", "geometry"):
        spec = _mapping(files.get(key), f"receipt.files.{key}")
        path_value = _nonempty_string(spec.get("path"), f"receipt.files.{key}.path")
        expected_sha = _sha_string(spec.get("sha256"), f"receipt.files.{key}.sha256")
        path = _resolve_under(root, path_value)
        _require(path.is_file(), f"缺少投料站预览文件: {path}")
        if "bytes" in spec:
            _require(
                path.stat().st_size == int(spec["bytes"]),
                f"投料站预览文件 bytes 不匹配: {key}",
            )
        actual_sha = _sha256(path)
        _require(actual_sha == expected_sha, f"投料站预览文件 SHA-256 不匹配: {key}")
        resolved[key] = path
        digests[key] = actual_sha

    handoff = _read_json(resolved["station_handoff"], "station handoff")
    layout = _read_json(resolved["layout"], "P2 layout")
    coverage = _read_json(resolved["coverage"], "P2 coverage")
    _require(handoff.get("schema") == "lab.station_source_handoff/v0", "P1 handoff schema 无效")
    _require(handoff.get("station") == station, "P1 handoff station 与 receipt 不一致")
    _require(layout.get("schema") == "lab.station_layout_candidate/v1", "P2 layout schema 无效")
    _require(layout.get("station") == station, "P2 layout station 与 receipt 不一致")
    _require(layout.get("qualification") == "decomposition-draft-preview", "P2 layout 不是 draft-preview")
    _require(layout.get("human_reviewed") is False, "P2 layout 不得冒充已人工审核")
    _require(layout.get("publication_eligible") is False, "P2 layout 不得具有发布资格")
    _require(layout.get("not_a_deploy_manifest") is True, "P2 layout 缺少非部署边界")
    _require(layout.get("not_a_workcell_activation") is True, "P2 layout 缺少非激活边界")
    _require(layout.get("source_handoff_digest") == digests["station_handoff"], "P2 layout handoff 摘要不一致")
    _require(layout.get("source_decomposition_digest") == digests["decomposition"], "P2 layout decomposition 摘要不一致")

    _require(coverage.get("schema") == "lab.station_decomposition_coverage/v1", "P2 coverage schema 无效")
    _require(coverage.get("station") == station, "P2 coverage station 与 receipt 不一致")
    _require(coverage.get("status") == "draft-preview", "P2 coverage 不是 draft-preview")
    _require(coverage.get("publication_eligible") is False, "P2 coverage 不得具有发布资格")
    _require(coverage.get("exact_coverage") is True, "P2 coverage 必须为精确覆盖")
    _require(coverage.get("source_handoff_digest") == digests["station_handoff"], "P2 coverage handoff 摘要不一致")
    _require(coverage.get("source_decomposition_digest") == digests["decomposition"], "P2 coverage decomposition 摘要不一致")
    expected = _mapping(receipt.get("expected_p2"), "receipt.expected_p2")
    for key in ("occurrence_count", "assigned_occurrence_count", "placement_count"):
        _require(coverage.get(key) == expected.get(key), f"P2 coverage {key} 与 receipt 不一致")
    _require(coverage.get("occurrence_count") == coverage.get("assigned_occurrence_count"), "P2 coverage 未全分配")
    _require(coverage.get("unassigned_occurrences") == [], "P2 coverage 仍有未分配 occurrence")
    _require(coverage.get("overlapping_occurrences") == [], "P2 coverage 仍有重叠 occurrence")

    geometry = _mapping(receipt.get("geometry"), "receipt.geometry")
    _validate_geometry_receipt(resolved["geometry"], geometry)
    capture = _mapping(handoff.get("solidworks_capture"), "handoff.solidworks_capture")
    _require(_resolve_under(root, _nonempty_string(capture.get("render_glb"), "handoff.render_glb")) == resolved["geometry"], "P1 handoff render_glb 与 receipt 不一致")

    placements = layout.get("placements")
    _require(isinstance(placements, list), "P2 layout placements 必须是数组")
    robot_family = _nonempty_string(expected.get("robot_family"), "expected_p2.robot_family")
    robot_matches = [item for item in placements if isinstance(item, dict) and item.get("family") == robot_family]
    _require(len(robot_matches) == 1, "P2 layout 必须唯一识别 GCR5 robot replacement")
    bottle_family = _nonempty_string(expected.get("four_ml_family"), "expected_p2.four_ml_family")
    bottle_matches = [item for item in placements if isinstance(item, dict) and item.get("family") == bottle_family]
    _require(len(bottle_matches) == 1, "P2 layout 必须唯一识别 4 ml 代表几何")

    return StationPreview(
        root=root,
        receipt_path=receipt_path,
        model_path=resolved["geometry"],
        station=station,
        run_id=run_id,
        geometry_sha256=digests["geometry"],
        layout_sha256=digests["layout"],
        decomposition_sha256=digests["decomposition"],
        handoff_sha256=digests["station_handoff"],
        geometry=geometry,
        coverage=coverage,
        robot={
            "family": robot_family,
            "subtree_root": robot_matches[0]["subtree_root"],
            "solidworks_geometry_role": robot_matches[0].get("solidworks_geometry_role"),
            "kinematics_source": robot_matches[0].get("kinematics_source"),
        },
        four_ml_representative={
            "family": bottle_family,
            "occurrence": bottle_matches[0]["anchor_occurrence"],
            "physical_site_approved": False,
        },
    )


def _validate_geometry_receipt(path: Path, geometry: Mapping[str, Any]) -> None:
    expected_counts = _mapping(geometry.get("counts"), "receipt.geometry.counts")
    bounds = _mapping(geometry.get("bounding_box_m"), "receipt.geometry.bounding_box_m")
    for key in ("min", "max", "size"):
        values = bounds.get(key)
        _require(
            isinstance(values, list)
            and len(values) == 3
            and all(isinstance(value, (int, float)) and math.isfinite(value) for value in values),
            f"receipt.geometry.bounding_box_m.{key} 无效",
        )
    low, high, size = bounds["min"], bounds["max"], bounds["size"]
    _require(all(float(high[i]) > float(low[i]) for i in range(3)), "geometry bounds 必须为正范围")
    _require(all(abs((float(high[i]) - float(low[i])) - float(size[i])) < 1e-6 for i in range(3)), "geometry bounds size 不一致")

    with path.open("rb") as handle:
        header = handle.read(12)
        _require(len(header) == 12, "GLB header 截断")
        magic, version, total_length = struct.unpack("<4sII", header)
        _require(magic == b"glTF" and version == 2, "GLB magic/version 无效")
        _require(total_length == path.stat().st_size, "GLB 声明长度与文件大小不一致")
        chunk_header = handle.read(8)
        _require(len(chunk_header) == 8, "GLB JSON chunk header 截断")
        chunk_length, chunk_type = struct.unpack("<II", chunk_header)
        _require(chunk_type == 0x4E4F534A, "GLB 首块不是 JSON")
        document = json.loads(handle.read(chunk_length).rstrip(b" \t\r\n\x00").decode("utf-8"))
    meshes = document.get("meshes", [])
    actual_counts = {
        "nodes": len(document.get("nodes", [])),
        "meshes": len(meshes),
        "primitives": sum(len(item.get("primitives", [])) for item in meshes if isinstance(item, dict)),
        "accessors": len(document.get("accessors", [])),
        "materials": len(document.get("materials", [])),
    }
    _require(actual_counts == dict(expected_counts), "GLB JSON 几何计数与 receipt 不一致")


def _resolve_under(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    _require(candidate == root or root in candidate.parents, f"预览路径越出 handoff 根目录: {value}")
    return candidate


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field} 不可读: {error}") from error
    return dict(_mapping(value, field))


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _sha_string(value: Any, field: str) -> str:
    value = _nonempty_string(value, field)
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field} 必须是小写 SHA-256")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
