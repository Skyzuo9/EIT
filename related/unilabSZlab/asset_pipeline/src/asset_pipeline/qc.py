from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from pygltflib import GLTF2

from .models import DeviceRecord, Dimensions, MeshyTask, QCReport, ResearchBundle


class QCError(RuntimeError):
    pass


def _gltf_features(path: Path) -> tuple[bool, bool]:
    gltf = GLTF2().load_binary(str(path))
    has_materials = bool(gltf.materials)
    has_textures = bool(gltf.images or gltf.textures)
    return has_materials, has_textures


def _scene_counts(scene: trimesh.Scene) -> tuple[int, int]:
    vertices = 0
    faces = 0
    for geometry in scene.geometry.values():
        vertices += len(getattr(geometry, "vertices", []))
        faces += len(getattr(geometry, "faces", []))
    return vertices, faces


def _target_extents(dimensions: Dimensions) -> np.ndarray:
    if not dimensions.complete:
        raise QCError(
            "Complete width/depth/height dimensions are required for scale normalization"
        )
    return np.array(
        [
            float(dimensions.width_mm) / 1000.0,
            float(dimensions.height_mm) / 1000.0,
            float(dimensions.depth_mm) / 1000.0,
        ]
    )


def normalize_and_check_glb(
    device_id: str,
    source_path: Path,
    output_path: Path,
    dimensions: Dimensions,
    max_proportion_error: float = 0.15,
) -> QCReport:
    report = QCReport(
        device_id=device_id,
        source_glb=str(source_path),
        final_glb=str(output_path),
    )
    try:
        scene = trimesh.load_scene(source_path, process=False)
        report.loadable = bool(scene.geometry)
        report.vertices, report.faces = _scene_counts(scene)
        report.has_materials, report.has_textures = _gltf_features(source_path)
        source_extents = np.asarray(scene.extents, dtype=float)
        report.source_extents = source_extents.tolist()
        if np.any(source_extents <= 0):
            raise QCError("Generated GLB has a zero-sized axis")

        if dimensions.complete:
            target = _target_extents(dimensions)
            target_ratio = target / np.max(target)
            direct_error = float(
                np.max(np.abs(source_extents / np.max(source_extents) - target_ratio))
            )
            swapped_extents = source_extents[[2, 1, 0]]
            swapped_error = float(
                np.max(np.abs(swapped_extents / np.max(swapped_extents) - target_ratio))
            )
            if swapped_error < direct_error:
                scene.apply_transform(
                    trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
                )
                aligned_extents = np.asarray(scene.extents, dtype=float)
                proportion_error = swapped_error
                report.axis_mapping = "swap_xz"
            else:
                aligned_extents = source_extents
                proportion_error = direct_error
            report.proportion_error = proportion_error
            report.target_extents_m = target.tolist()

            scale = target / aligned_extents
            transform = np.eye(4)
            transform[0, 0], transform[1, 1], transform[2, 2] = scale
            scene.apply_transform(transform)
            bounds = np.asarray(scene.bounds, dtype=float)
            translation = np.eye(4)
            translation[:3, 3] = [
                -float((bounds[0, 0] + bounds[1, 0]) / 2),
                -float(bounds[0, 1]),
                -float((bounds[0, 2] + bounds[1, 2]) / 2),
            ]
            scene.apply_transform(translation)
            report.final_extents_m = np.asarray(scene.extents, dtype=float).tolist()
            if proportion_error > max_proportion_error:
                report.warnings.append(
                    f"Source proportions differ from official dimensions by {proportion_error:.1%}"
                )
        else:
            report.warnings.append(
                "Official dimensions incomplete; GLB was not rescaled"
            )
            report.final_extents_m = source_extents.tolist()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        exported = scene.export(file_type="glb")
        if not isinstance(exported, bytes):
            raise QCError("Unexpected trimesh GLB export result")
        output_path.write_bytes(exported)
        final_materials, final_textures = _gltf_features(output_path)
        report.has_materials = report.has_materials and final_materials
        report.has_textures = report.has_textures and final_textures
        report.geometry_pass = all(
            (
                report.loadable,
                report.vertices > 0,
                report.faces > 0,
                report.has_materials,
                report.has_textures,
                dimensions.complete,
                (report.proportion_error or 0.0) <= max_proportion_error,
            )
        )
        report.passed = report.geometry_pass
    except Exception as error:
        report.warnings.append(str(error))
        report.geometry_pass = False
        report.passed = False
    return report


def write_manifest(
    path: Path,
    device: DeviceRecord,
    research: ResearchBundle | None,
    task: MeshyTask | None,
    qc: QCReport | None,
    approvals: list[dict],
) -> Path:
    payload = {
        "device": device.model_dump(mode="json"),
        "research": research.model_dump(mode="json") if research else None,
        "meshy_task": task.model_dump(mode="json") if task else None,
        "qc": qc.model_dump(mode="json") if qc else None,
        "approvals": approvals,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
