"""Initial, evidence-preserving asset-pipeline trial for the current folder.

This is intentionally a candidate compiler.  It publishes no controller
points, deployment identity, robot base pose, tool offset, load, or telemetry
inside family assets.  SolidWorks-exported URDF joints remain unproven
candidates and never enter the formal joint list.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import yaml


RELEVANT_EXTENSIONS = {
    ".csv",
    ".glb",
    ".gltf",
    ".json",
    ".sldasm",
    ".sldprt",
    ".step",
    ".stl",
    ".stp",
    ".urdf",
    ".xacro",
    ".yaml",
    ".yml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path(__file__).with_name("pipeline.yaml")))
    parser.add_argument("--keep-output", action="store_true")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def files_manifest(paths: Iterable[Path], base: Path | None = None) -> list[dict[str, Any]]:
    entries = []
    for path in sorted({item.resolve() for item in paths}, key=lambda item: str(item).lower()):
        label = path.relative_to(base).as_posix() if base and path.is_relative_to(base) else str(path)
        entries.append({"path": label, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return entries


def write_files_sha256(path: Path, entries: list[dict[str, Any]]) -> None:
    lines = [f"{item['sha256']}  {item['path']}" for item in entries]
    write_text(path, "\n".join(lines) + "\n")


def safe_reset_output(workspace: Path, output: Path) -> None:
    workspace = workspace.resolve()
    output = output.resolve()
    if not output.is_relative_to(workspace):
        raise RuntimeError(f"refusing to reset output outside workspace: {output}")
    if output.name != "asset-pipeline-trial":
        raise RuntimeError(f"unexpected trial output directory: {output}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def command_version(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        output = (result.stdout + result.stderr).strip().splitlines()
        return {"available": result.returncode == 0, "exit_code": result.returncode, "output": output[:5]}
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def resolve_urdf_mesh(urdf_path: Path, uri: str) -> Path:
    if uri.startswith("package://"):
        rest = uri[len("package://") :]
        if "/" not in rest:
            raise ValueError(f"invalid package URI: {uri}")
        _, relative = rest.split("/", 1)
        return (urdf_path.parent.parent / relative).resolve()
    return (urdf_path.parent / uri).resolve()


def floats(value: str | None, default: list[float]) -> list[float]:
    if not value:
        return list(default)
    result = [float(item) for item in value.split()]
    if len(result) != len(default):
        raise ValueError(f"expected {len(default)} values, got {value!r}")
    return result


def parse_urdf(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    links = []
    mesh_paths: list[Path] = []
    missing_meshes: list[str] = []
    collision_equals_visual = 0
    for link_node in root.findall("link"):
        visual_mesh_node = link_node.find("visual/geometry/mesh")
        collision_mesh_node = link_node.find("collision/geometry/mesh")
        visual_uri = visual_mesh_node.attrib.get("filename") if visual_mesh_node is not None else None
        collision_uri = collision_mesh_node.attrib.get("filename") if collision_mesh_node is not None else None
        for uri in {visual_uri, collision_uri} - {None}:
            resolved = resolve_urdf_mesh(path, str(uri))
            if resolved.exists():
                mesh_paths.append(resolved)
            else:
                missing_meshes.append(str(resolved))
        if visual_uri and collision_uri and visual_uri == collision_uri:
            collision_equals_visual += 1
        mass_node = link_node.find("inertial/mass")
        color_node = link_node.find("visual/material/color")
        links.append(
            {
                "id": link_node.attrib["name"],
                "visual_uri": visual_uri,
                "collision_candidate_uri": collision_uri,
                "collision_candidate_status": "unqualified-same-as-visual"
                if visual_uri and visual_uri == collision_uri
                else "unreviewed",
                "mass_kg_audit": float(mass_node.attrib["value"]) if mass_node is not None else None,
                "rgba_audit": floats(color_node.attrib.get("rgba"), [0.8, 0.8, 0.8, 1.0])
                if color_node is not None
                else None,
            }
        )

    link_names = {item["id"] for item in links}
    child_names: set[str] = set()
    candidates = []
    bad_endpoints = []
    for joint_node in root.findall("joint"):
        parent = joint_node.find("parent").attrib["link"]
        child = joint_node.find("child").attrib["link"]
        child_names.add(child)
        if parent not in link_names or child not in link_names:
            bad_endpoints.append(joint_node.attrib.get("name", ""))
        origin = joint_node.find("origin")
        axis = joint_node.find("axis")
        limit = joint_node.find("limit")
        candidate = {
            "id": joint_node.attrib.get("name", ""),
            "type": joint_node.attrib.get("type", "unknown"),
            "parent": parent,
            "child": child,
            "origin": {
                "xyz": floats(origin.attrib.get("xyz") if origin is not None else None, [0.0, 0.0, 0.0]),
                "rpy": floats(origin.attrib.get("rpy") if origin is not None else None, [0.0, 0.0, 0.0]),
            },
            "axis": floats(axis.attrib.get("xyz") if axis is not None else None, [1.0, 0.0, 0.0]),
            "limits": {
                key: float(limit.attrib[key]) if limit is not None and key in limit.attrib else None
                for key in ("lower", "upper", "velocity", "effort")
            },
            "role": "candidate",
            "status": "unproven",
            "evidence": "legacy SolidWorks URDF exporter output",
        }
        candidates.append(candidate)
    roots = sorted(link_names - child_names)
    return {
        "name": root.attrib.get("name", path.stem),
        "path": path,
        "is_solidworks_exporter": "SolidWorks to URDF Exporter" in text[:1000],
        "links": links,
        "candidates": candidates,
        "root_links": roots,
        "mesh_paths": sorted(set(mesh_paths), key=lambda item: str(item).lower()),
        "missing_meshes": missing_meshes,
        "bad_joint_endpoints": bad_endpoints,
        "collision_equals_visual": collision_equals_visual,
    }


def step_schema(path: Path) -> str | None:
    with path.open("rb") as stream:
        header = stream.read(256 * 1024).decode("latin-1", errors="replace")
    match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", header, flags=re.IGNORECASE)
    return match.group(1) if match else None


def scan_inventory(workspace: Path) -> dict[str, Any]:
    files = [path for path in workspace.rglob("*") if path.is_file() and "work" not in path.parts]
    relevant = [path for path in files if path.suffix.lower() in RELEVANT_EXTENSIONS]
    counts = collections.Counter(path.suffix.lower() for path in relevant)
    urdf_rows = []
    for path in sorted((item for item in relevant if item.suffix.lower() == ".urdf"), key=str):
        try:
            parsed = parse_urdf(path)
            urdf_rows.append(
                {
                    "path": str(path),
                    "links": len(parsed["links"]),
                    "candidate_joints": len(parsed["candidates"]),
                    "root_count": len(parsed["root_links"]),
                    "solidworks_exporter": parsed["is_solidworks_exporter"],
                    "missing_meshes": len(parsed["missing_meshes"]),
                    "bad_joint_endpoints": len(parsed["bad_joint_endpoints"]),
                    "visual_equals_collision_links": parsed["collision_equals_visual"],
                    "error": None,
                }
            )
        except Exception as exc:
            urdf_rows.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    step_rows = []
    for path in sorted((item for item in relevant if item.suffix.lower() in {".step", ".stp"}), key=str):
        step_rows.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "file_schema": step_schema(path),
            }
        )
    grouped: dict[str, list[str]] = collections.defaultdict(list)
    for item in step_rows:
        grouped[item["sha256"]].append(item["path"])
    duplicate_steps = [paths for paths in grouped.values() if len(paths) > 1]
    valid_urdfs = [item for item in urdf_rows if item.get("error") is None]
    return {
        "schema": "lab.asset_inventory/v0",
        "workspace": str(workspace),
        "extension_counts": dict(sorted(counts.items())),
        "urdf_summary": {
            "files": len(urdf_rows),
            "parsed": len(valid_urdfs),
            "solidworks_exporter": sum(bool(item["solidworks_exporter"]) for item in valid_urdfs),
            "articulated": sum(item["candidate_joints"] > 0 for item in valid_urdfs),
            "candidate_joints": sum(item["candidate_joints"] for item in valid_urdfs),
            "missing_mesh_references": sum(item["missing_meshes"] for item in valid_urdfs),
            "bad_joint_endpoints": sum(item["bad_joint_endpoints"] for item in valid_urdfs),
            "visual_equals_collision_links": sum(item["visual_equals_collision_links"] for item in valid_urdfs),
        },
        "urdfs": urdf_rows,
        "step_files": step_rows,
        "duplicate_step_groups": duplicate_steps,
    }


def read_glb_chunks(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    _, version, total_length = struct.unpack_from("<4sII", data, 0)
    if version != 2 or total_length != len(data):
        raise ValueError(f"invalid GLB header: version={version}, total={total_length}, actual={len(data)}")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
    if document is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return document, binary


def read_glb_json(path: Path) -> dict[str, Any]:
    return read_glb_chunks(path)[0]


def glb_semantic_signature(path: Path) -> dict[str, Any]:
    """Normalize exporter traversal order while retaining geometry evidence."""
    document, binary = read_glb_chunks(path)
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])

    def accessor_signature(index: int) -> dict[str, Any]:
        accessor = accessors[index]
        view = views[accessor["bufferView"]]
        start = int(view.get("byteOffset", 0))
        end = start + int(view["byteLength"])
        return {
            "componentType": accessor["componentType"],
            "count": accessor["count"],
            "type": accessor["type"],
            "min": accessor.get("min"),
            "max": accessor.get("max"),
            "normalized": accessor.get("normalized", False),
            "buffer_view_sha256": hashlib.sha256(binary[start:end]).hexdigest(),
        }

    mesh_nodes = []
    for node in document.get("nodes", []):
        if "mesh" not in node:
            continue
        mesh = document["meshes"][node["mesh"]]
        primitives = []
        for primitive in mesh.get("primitives", []):
            primitives.append(
                {
                    "mode": primitive.get("mode", 4),
                    "indices": accessor_signature(primitive["indices"])
                    if "indices" in primitive
                    else None,
                    "attributes": {
                        semantic: accessor_signature(index)
                        for semantic, index in sorted(primitive.get("attributes", {}).items())
                    },
                    "material": document.get("materials", [])[primitive["material"]]
                    if "material" in primitive
                    else None,
                }
            )
        mesh_nodes.append(
            {
                "name": node.get("name"),
                "translation": node.get("translation", [0.0, 0.0, 0.0]),
                "rotation": node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
                "scale": node.get("scale", [1.0, 1.0, 1.0]),
                "primitives": primitives,
            }
        )
    return {
        "asset": document.get("asset"),
        "mesh_nodes": sorted(mesh_nodes, key=lambda item: str(item["name"])),
    }


def normalized_assembly_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(snapshot)
    normalized["instances"] = sorted(snapshot.get("instances", []), key=lambda item: item["id"])
    normalized["mates_candidate"] = sorted(
        snapshot.get("mates_candidate", []), key=lambda item: item["id"]
    )
    normalized["root_occurrences"] = sorted(snapshot.get("root_occurrences", []))
    return normalized


def glb_stats(path: Path) -> dict[str, Any]:
    document = read_glb_json(path)
    meshes = document.get("meshes", [])
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "nodes": len(document.get("nodes", [])),
        "meshes": len(meshes),
        "primitives": sum(len(mesh.get("primitives", [])) for mesh in meshes),
        "accessors": len(document.get("accessors", [])),
        "materials": len(document.get("materials", [])),
        "animations": len(document.get("animations", [])),
        "skins": len(document.get("skins", [])),
        "scenes": len(document.get("scenes", [])),
    }


def mat_identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def mat_multiply(left: list[float], right: list[float]) -> list[float]:
    result = [0.0] * 16
    for column in range(4):
        for row in range(4):
            result[column * 4 + row] = sum(
                left[k * 4 + row] * right[column * 4 + k] for k in range(4)
            )
    return result


def node_matrix(node: dict[str, Any]) -> list[float]:
    if "matrix" in node:
        return [float(item) for item in node["matrix"]]
    translation = [float(item) for item in node.get("translation", [0.0, 0.0, 0.0])]
    x, y, z, w = [float(item) for item in node.get("rotation", [0.0, 0.0, 0.0, 1.0])]
    sx, sy, sz = [float(item) for item in node.get("scale", [1.0, 1.0, 1.0])]
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        (1 - 2 * (yy + zz)) * sx,
        (2 * (xy + wz)) * sx,
        (2 * (xz - wy)) * sx,
        0.0,
        (2 * (xy - wz)) * sy,
        (1 - 2 * (xx + zz)) * sy,
        (2 * (yz + wx)) * sy,
        0.0,
        (2 * (xz + wy)) * sz,
        (2 * (yz - wx)) * sz,
        (1 - 2 * (xx + yy)) * sz,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    ]


def matrix_quaternion(matrix: list[float]) -> list[float]:
    columns = [[matrix[column * 4 + row] for row in range(3)] for column in range(3)]
    for column in columns:
        length = math.sqrt(sum(value * value for value in column)) or 1.0
        for index in range(3):
            column[index] /= length
    m00, m10, m20 = columns[0]
    m01, m11, m21 = columns[1]
    m02, m12, m22 = columns[2]
    trace = m00 + m11 + m22
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        return [(m21 - m12) / scale, (m02 - m20) / scale, (m10 - m01) / scale, 0.25 * scale]
    if m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2
        return [0.25 * scale, (m01 + m10) / scale, (m02 + m20) / scale, (m21 - m12) / scale]
    if m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2
        return [(m01 + m10) / scale, 0.25 * scale, (m12 + m21) / scale, (m02 - m20) / scale]
    scale = math.sqrt(1.0 + m22 - m00 - m11) * 2
    return [(m02 + m20) / scale, (m12 + m21) / scale, 0.25 * scale, (m10 - m01) / scale]


def build_step_snapshot(source: Path, document: dict[str, Any]) -> dict[str, Any]:
    nodes = document.get("nodes", [])
    parents: dict[int, int] = {}
    for parent_index, node in enumerate(nodes):
        for child in node.get("children", []):
            parents[int(child)] = parent_index
    world_cache: dict[int, list[float]] = {}

    def world(index: int) -> list[float]:
        if index in world_cache:
            return world_cache[index]
        local = node_matrix(nodes[index])
        result = mat_multiply(world(parents[index]), local) if index in parents else local
        world_cache[index] = result
        return result

    instances = []
    for index, node in enumerate(nodes):
        matrix = world(index)
        instances.append(
            {
                "id": f"step-node:{index:04d}",
                "name": node.get("name", f"node-{index}"),
                "document": str(source),
                "parent": f"step-node:{parents[index]:04d}" if index in parents else None,
                "transform_world": {
                    "xyz_m": [matrix[12], matrix[13], matrix[14]],
                    "quat_xyzw": matrix_quaternion(matrix),
                    "frame_ref": "gltf_root",
                },
                "source_gltf_node": index,
                "has_render_mesh": "mesh" in node,
                "suppressed": False,
            }
        )
    return {
        "schema": "lab.assembly_snapshot/v0",
        "source_document": str(source),
        "capture_adapter": "StepAssemblyAdapter/cascadio-0.1.1/trial-v0",
        "units": {"length": "m", "angle": "rad", "orientation": "quaternion_xyzw"},
        "coordinate_note": "world transforms are expressed in the converted glTF root frame",
        "instances": instances,
        "mates_candidate": [],
        "missing": ["solidworks_mates", "solidworks_configuration", "stable_solidworks_occurrence_identity"],
    }


def bundle_artifacts(bundle_dir: Path, names: Iterable[str]) -> list[dict[str, Any]]:
    result = []
    for name in names:
        path = bundle_dir / name
        if path.exists():
            result.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def compile_step_asset(asset: dict[str, Any], output: Path, ascii_temp: Path) -> dict[str, Any]:
    import cascadio

    source = Path(asset["source"]).resolve()
    source_digest = sha256_file(source)
    bundle_dir = output / "families" / "instruments" / "step" / asset["id"] / f"trial-{source_digest[:12]}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = ascii_temp / f"step_{asset['id']}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_input = temp_dir / "source.step"
    temp_output = temp_dir / "render.glb"
    shutil.copy2(source, temp_input)
    started = time.time()
    return_code = cascadio.step_to_glb(
        str(temp_input),
        str(temp_output),
        include_brep=True,
        include_materials=True,
    )
    if return_code != 0 or not temp_output.exists():
        raise RuntimeError(f"cascadio failed for {source}: return code {return_code}")
    render_path = bundle_dir / "render-lod0.glb"
    shutil.copy2(temp_output, render_path)
    document = read_glb_json(render_path)
    stats = glb_stats(render_path)
    source_entries = files_manifest([source])
    write_files_sha256(bundle_dir / "files.sha256", source_entries)
    write_json(
        bundle_dir / "source.json",
        {
            "schema": "lab.source/v0",
            "source_type": "step",
            "source_document": str(source),
            "source_sha256": source_digest,
            "file_schema": step_schema(source),
            "authority": ["brep", "product_structure_if_present", "static_placement"],
            "not_authority": ["robot_kinematics", "control_semantics", "mechanical_mates"],
        },
    )
    snapshot = build_step_snapshot(source, document)
    write_json(bundle_dir / "assembly.snapshot.json", snapshot)
    render_nodes = [item for item in snapshot["instances"] if item["has_render_mesh"]]
    write_json(
        bundle_dir / "entity-registry.json",
        {
            "schema": "lab.entity_registry/v0",
            "entities": [
                {"scene_entity_id": item["id"], "source_node": item["source_gltf_node"], "alias": item["name"]}
                for item in render_nodes
            ],
        },
    )
    write_json(
        bundle_dir / "frame-graph.json",
        {
            "schema": "lab.frame_graph/v0",
            "root": "gltf_root",
            "frames": [{"id": "gltf_root", "parent": None, "status": "converted-step-root"}],
            "missing": ["engineering_z_up_to_gltf_root_approval"],
        },
    )
    write_json(
        bundle_dir / "geometry-roles.json",
        {
            "schema": "lab.geometry_roles/v0",
            "entities": [
                {"id": item["id"], "roles": ["visual", "selection"], "collision_status": "missing"}
                for item in render_nodes
            ],
        },
    )
    write_json(
        bundle_dir / "capability.json",
        {
            "grade": asset.get("capability", "visual-only"),
            "allows": ["workbench_display", "stable_picking"],
            "forbids": ["motion", "spatial_interlock_enforced", "execution"],
            "missing": ["approved_mechanics", "qualified_collision", "site_calibration"],
        },
    )
    write_json(
        bundle_dir / "provenance.json",
        {
            "schema": "lab.provenance/v0",
            "adapter": "StepAssemblyAdapter/cascadio-0.1.1/trial-v0",
            "source_sha256": source_digest,
            "duration_s": round(time.time() - started, 3),
            "glb_stats": stats,
            "note": asset["note"],
        },
    )
    artifact_names = [
        "source.json",
        "files.sha256",
        "assembly.snapshot.json",
        "entity-registry.json",
        "frame-graph.json",
        "geometry-roles.json",
        "capability.json",
        "provenance.json",
        "render-lod0.glb",
    ]
    artifacts = bundle_artifacts(bundle_dir, artifact_names)
    bundle = {
        "schema": "lab.family_sim_bundle/v0",
        "family": asset["family"],
        "trial_revision": f"source-sha256:{source_digest}",
        "immutable_candidate": True,
        "artifacts": artifacts,
    }
    write_json(bundle_dir / "bundle.json", bundle)
    return {"id": asset["id"], "status": "passed", "bundle": str(bundle_dir), "glb": stats}


def compile_legacy_urdf(
    asset: dict[str, Any], output: Path, ascii_temp: Path, blender: Path, blender_script: Path
) -> dict[str, Any]:
    source = Path(asset["source"]).resolve()
    parsed = parse_urdf(source)
    if not parsed["is_solidworks_exporter"]:
        raise RuntimeError(f"legacy fixture is not marked as SolidWorks exporter output: {source}")
    if len(parsed["root_links"]) != 1 or parsed["missing_meshes"] or parsed["bad_joint_endpoints"]:
        raise RuntimeError(f"legacy URDF structural gate failed: {source}")
    all_inputs = [source, *parsed["mesh_paths"]]
    input_entries = files_manifest(all_inputs)
    source_digest = sha256_text("".join(item["sha256"] for item in input_entries))
    bundle_dir = output / "families" / "instruments" / "legacy-sw-urdf" / asset["id"] / f"trial-{source_digest[:12]}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = ascii_temp / f"urdf_{asset['id']}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_glb = temp_dir / "render.glb"
    temp_report = temp_dir / "render-report.json"
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--python",
        str(blender_script),
        "--",
        "--urdf",
        str(source),
        "--output",
        str(temp_glb),
        "--report",
        str(temp_report),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=180,
    )
    console = (result.stdout or "") + (result.stderr or "")
    reports_dir = bundle_dir / "reports"
    write_text(reports_dir / "blender.console.log", console)
    if result.returncode != 0 or "Traceback (most recent call last)" in console or not temp_glb.exists():
        raise RuntimeError(f"Blender legacy URDF compilation failed for {source}; see {reports_dir}")
    render_path = bundle_dir / "render-lod0.glb"
    shutil.copy2(temp_glb, render_path)
    if temp_report.exists():
        shutil.copy2(temp_report, reports_dir / "render.json")
    render_stats = glb_stats(render_path)
    link_ids = [item["id"] for item in parsed["links"]]
    write_files_sha256(bundle_dir / "files.sha256", input_entries)
    write_json(
        bundle_dir / "source.json",
        {
            "schema": "lab.source/v0",
            "source_type": "legacy-sw-urdf-export",
            "source_document": str(source),
            "source_digest": source_digest,
            "authority": ["visual_mesh", "link_names_as_migration_aliases"],
            "not_authority": ["formal_joint_semantics", "qualified_collision", "controller_targets"],
        },
    )
    write_json(
        bundle_dir / "legacy.snapshot.json",
        {
            "schema": "lab.legacy_urdf_snapshot/v0",
            "source_document": str(source),
            "root_link": parsed["root_links"][0],
            "links": [{"id": item["id"], "source_visual": item["visual_uri"]} for item in parsed["links"]],
            "source_joint_evidence": parsed["candidates"],
        },
    )
    write_json(
        bundle_dir / "mechanics.json",
        {
            "schema": "lab.mechanics/v0",
            "family": asset["family"],
            "units": {"length": "m", "angle": "rad"},
            "root_link": parsed["root_links"][0],
            "links": [{"id": item} for item in link_ids],
            "joints": [],
            "candidates": parsed["candidates"],
            "source_authority": "legacy-sw-urdf-unproven",
        },
    )
    candidate_parent = {item["child"]: item["parent"] for item in parsed["candidates"]}
    write_json(
        bundle_dir / "frame-graph.json",
        {
            "schema": "lab.frame_graph/v0",
            "root": parsed["root_links"][0],
            "frames": [
                {"id": item, "parent_candidate": candidate_parent.get(item), "status": "unproven"}
                for item in link_ids
            ],
            "candidate_edges": [
                {
                    "parent": item["parent"],
                    "child": item["child"],
                    "origin": item["origin"],
                    "status": "unproven",
                }
                for item in parsed["candidates"]
            ],
        },
    )
    write_json(
        bundle_dir / "entity-registry.json",
        {
            "schema": "lab.entity_registry/v0",
            "entities": [
                {"scene_entity_id": f"legacy-link:{index:04d}:{link}", "link_alias": link}
                for index, link in enumerate(link_ids)
            ],
        },
    )
    write_json(
        bundle_dir / "geometry-roles.json",
        {
            "schema": "lab.geometry_roles/v0",
            "entities": [
                {
                    "id": item["id"],
                    "roles": ["visual", "selection", "collision-candidate"],
                    "collision_status": item["collision_candidate_status"],
                }
                for item in parsed["links"]
            ],
        },
    )
    missing = ["source_pack_and_go", "approved_mechanics", "qualified_collision", "site_calibration"]
    if any((candidate["limits"].get("velocity") or 0.0) == 0.0 for candidate in parsed["candidates"]):
        missing.append("nonzero_verified_velocity_limits")
    write_json(
        bundle_dir / "capability.json",
        {
            "grade": "semantic-scene",
            "allows": ["workbench_display", "stable_picking"],
            "forbids": ["motion", "spatial_interlock_enforced", "execution"],
            "missing": missing,
        },
    )
    write_json(
        bundle_dir / "provenance.json",
        {
            "schema": "lab.provenance/v0",
            "adapter": "LegacySwUrdfFixtureAdapter/trial-v0",
            "source_digest": source_digest,
            "render": render_stats,
            "candidate_joint_count": len(parsed["candidates"]),
            "visual_collision_same_mesh_links": parsed["collision_equals_visual"],
            "promotion_requires_human_approval": True,
        },
    )
    artifact_names = [
        "source.json",
        "files.sha256",
        "legacy.snapshot.json",
        "mechanics.json",
        "frame-graph.json",
        "entity-registry.json",
        "geometry-roles.json",
        "capability.json",
        "provenance.json",
        "render-lod0.glb",
        "reports/render.json",
    ]
    write_json(
        bundle_dir / "bundle.json",
        {
            "schema": "lab.family_sim_bundle/v0",
            "family": asset["family"],
            "trial_revision": f"input-digest:{source_digest}",
            "immutable_candidate": True,
            "artifacts": bundle_artifacts(bundle_dir, artifact_names),
        },
    )
    return {
        "id": asset["id"],
        "status": "passed",
        "bundle": str(bundle_dir),
        "links": len(parsed["links"]),
        "candidate_joints": len(parsed["candidates"]),
        "glb": render_stats,
    }


def find_forbidden(value: Any, forbidden_keys: set[str], path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in forbidden_keys:
                hits.append(f"{path}.{key}")
            hits.extend(find_forbidden(child, forbidden_keys, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(find_forbidden(child, forbidden_keys, f"{path}[{index}]"))
    return hits


def run_family_gates(families: Path, gate_config: dict[str, Any]) -> dict[str, Any]:
    forbidden_keys = {item.lower().replace("-", "_") for item in gate_config["forbid_family_keys"]}
    forbidden_text = [item.lower() for item in gate_config["forbid_family_text"]]
    failures: list[dict[str, Any]] = []
    checks = 0
    json_files = list(families.rglob("*.json"))
    glb_files = list(families.rglob("*.glb"))
    for path in json_files:
        value = json.loads(path.read_text(encoding="utf-8"))
        checks += 1
        for hit in find_forbidden(value, forbidden_keys):
            failures.append({"file": str(path), "gate": "forbidden-family-key", "detail": hit})
        lowered = json.dumps(value, ensure_ascii=False).lower()
        for token in forbidden_text:
            if token in lowered:
                failures.append({"file": str(path), "gate": "forbidden-family-text", "detail": token})
        if path.name == "mechanics.json" and value.get("source_authority") == "legacy-sw-urdf-unproven":
            if value.get("joints"):
                failures.append({"file": str(path), "gate": "legacy-formal-joints", "detail": "joints must be empty"})
            for candidate in value.get("candidates", []):
                if candidate.get("status") != "unproven":
                    failures.append({"file": str(path), "gate": "candidate-status", "detail": candidate.get("id")})
    for path in glb_files:
        checks += 1
        document = read_glb_json(path)
        stats = glb_stats(path)
        if stats["bytes"] > int(gate_config["max_render_glb_bytes"]):
            failures.append({"file": str(path), "gate": "render-budget", "detail": stats["bytes"]})
        if stats["animations"] or stats["skins"]:
            failures.append({"file": str(path), "gate": "embedded-motion", "detail": stats})
        if stats["primitives"] == 0 or stats["accessors"] == 0:
            failures.append({"file": str(path), "gate": "empty-render-geometry", "detail": stats})
        lowered = json.dumps(document, ensure_ascii=False).lower()
        for token in forbidden_text:
            if token in lowered:
                failures.append({"file": str(path), "gate": "forbidden-glb-text", "detail": token})
    for path in families.rglob("bundle.json"):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        for artifact in bundle.get("artifacts", []):
            artifact_path = path.parent / artifact["path"]
            if not artifact_path.exists():
                failures.append({"file": str(path), "gate": "missing-artifact", "detail": artifact["path"]})
            elif sha256_file(artifact_path) != artifact["sha256"]:
                failures.append({"file": str(path), "gate": "artifact-hash", "detail": artifact["path"]})
    return {
        "schema": "lab.family_release_gate/v0",
        "passed": not failures,
        "checks_run": checks,
        "json_files": len(json_files),
        "glb_files": len(glb_files),
        "failures": failures,
    }


def create_controller_interfaces(output: Path) -> None:
    interface_dir = output / "deploy" / "interfaces"
    write_json(
        interface_dir / "robot-controller-point-adapter.json",
        {
            "schema": "lab.robot_controller_point_adapter_contract/v0",
            "operations": [
                {
                    "name": "capture_raw_snapshot",
                    "input": ["controller_reference", "controller_revision_hint"],
                    "output": "immutable_raw_snapshot",
                },
                {
                    "name": "classify_records",
                    "input": ["immutable_raw_snapshot"],
                    "output": ["target_records", "program_selectors", "observed_joint_records"],
                },
                {
                    "name": "normalize_target_records",
                    "input": ["target_records", "frame_reference", "tool_context", "calibration_reference"],
                    "output": "pointset_candidate",
                    "required_gate": "forward_kinematics_consistency_when_joint_and_pose_are_both_present",
                },
            ],
            "rules": [
                "program selectors never become target points",
                "observed joint records never become target points",
                "no inverse-kinematics solution is frozen when only a Cartesian target is available",
            ],
        },
    )
    write_json(
        interface_dir / "raw-point-snapshot.fixture.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Controller raw snapshot fixture schema; no fabricated records included",
            "type": "object",
            "required": ["controller_revision", "captured_at", "native_units", "records"],
            "properties": {
                "controller_revision": {"type": "string"},
                "captured_at": {"type": "string", "format": "date-time"},
                "native_units": {"type": "object"},
                "records": {"type": "array"},
            },
        },
    )
    write_json(
        interface_dir / "telemetry.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Device telemetry projection",
            "type": "object",
            "required": ["topology_digest", "boot_id", "sequence", "observed_at", "joint_positions_rad", "stale"],
            "properties": {
                "topology_digest": {"type": "string"},
                "boot_id": {"type": "string"},
                "sequence": {"type": "integer", "minimum": 0},
                "observed_at": {"type": "string", "format": "date-time"},
                "joint_positions_rad": {"type": "object", "additionalProperties": {"type": "number"}},
                "stale": {"type": "boolean"},
            },
        },
    )
    write_json(
        output / "slices" / "slice-c-status.json",
        {
            "schema": "lab.trial_slice_status/v0",
            "slice": "C",
            "status": "interface-only",
            "reason": "no controller export was found in the current folder",
            "published_pointset": False,
            "published_programset": False,
            "published_current_values_as_targets": False,
        },
    )


def generate_previews(families: Path, output: Path, blender: Path) -> list[dict[str, Any]]:
    preview_dir = output / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_script = Path(__file__).with_name("trial_blender_preview.py").resolve()
    results = []
    for glb in sorted(families.rglob("render-lod0.glb"), key=str):
        asset_id = glb.parent.parent.name
        png = preview_dir / f"{asset_id}.png"
        report_path = preview_dir / f"{asset_id}.json"
        command = [
            str(blender),
            "--background",
            "--factory-startup",
            "--python",
            str(preview_script),
            "--",
            "--input",
            str(glb),
            "--output",
            str(png),
            "--report",
            str(report_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=180,
        )
        console = (result.stdout or "") + (result.stderr or "")
        if (
            result.returncode != 0
            or "Traceback (most recent call last)" in console
            or not png.exists()
            or not report_path.exists()
        ):
            raise RuntimeError(f"preview gate failed for {glb}: {console[-2000:]}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["asset_id"] = asset_id
        report["png_bytes"] = png.stat().st_size
        report["png_sha256"] = sha256_file(png)
        write_json(report_path, report)
        results.append(report)
    return results


def run_solidworks_capture(config: dict[str, Any], output: Path, ascii_temp: Path, python: Path) -> dict[str, Any]:
    capture_dir = output / "captures" / "solidworks" / "square-tactile"
    source_root = Path(config["source_root"]).resolve()
    assembly = Path(config["primary_assembly"]).resolve()
    cad_files = [path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() in {".sldasm", ".sldprt"}]
    entries = files_manifest(cad_files, base=source_root)
    write_files_sha256(capture_dir / "files.sha256", entries)
    write_json(
        capture_dir / "source.json",
        {
            "schema": "lab.source/v0",
            "source_type": "solidworks-pack-and-go-candidate",
            "source_document": str(assembly),
            "source_root": str(source_root),
            "cad_file_count": len(cad_files),
            "source_files_digest": sha256_text("".join(item["sha256"] for item in entries)),
            "read_policy": "read-only",
        },
    )
    ascii_glb = ascii_temp / config["export_glb_ascii_name"]
    command = [
        str(python),
        str(Path(__file__).with_name("trial_sw_adapter.py")),
        "--assembly",
        str(assembly),
        "--snapshot",
        str(capture_dir / "assembly.snapshot.json"),
        "--report",
        str(capture_dir / "capture-report.json"),
        "--glb-ascii",
        str(ascii_glb),
        "--progid",
        config["progid"],
    ]
    if config.get("visible_first_export"):
        command.append("--visible")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    write_text(capture_dir / "solidworks.console.log", (result.stdout or "") + (result.stderr or ""))
    report_path = capture_dir / "capture-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
        "status": "blocked",
        "failure": {"message": "SolidWorks probe did not write a report"},
    }
    write_json(
        capture_dir / "capability.json",
        {
            "grade": "visual-only" if report.get("status") == "passed" else "not-published",
            "allows": ["workbench_display"] if report.get("status") == "passed" else [],
            "forbids": ["motion", "spatial_interlock_enforced", "execution"],
            "missing": [] if report.get("status") == "passed" else ["solidworks_component_snapshot", "solidworks_native_glb"],
        },
    )
    result_summary = {
        "status": report.get("status", "blocked"),
        "capture": str(capture_dir),
        "exit_code": result.returncode,
        "failure": report.get("failure"),
    }
    if report.get("status") == "passed" and ascii_glb.exists():
        source_record = json.loads((capture_dir / "source.json").read_text(encoding="utf-8"))
        source_digest = source_record["source_files_digest"]
        bundle_dir = (
            output
            / "families"
            / "instruments"
            / "solidworks"
            / "square-tactile"
            / f"trial-{source_digest[:12]}"
        )
        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(capture_dir / "source.json", bundle_dir / "source.json")
        shutil.copy2(capture_dir / "files.sha256", bundle_dir / "files.sha256")
        shutil.copy2(capture_dir / "assembly.snapshot.json", bundle_dir / "assembly.snapshot.json")
        shutil.copy2(ascii_glb, bundle_dir / "render-lod0.glb")
        snapshot = json.loads((bundle_dir / "assembly.snapshot.json").read_text(encoding="utf-8"))
        instances = snapshot["instances"]
        write_json(
            bundle_dir / "entity-registry.json",
            {
                "schema": "lab.entity_registry/v0",
                "entities": [
                    {
                        "scene_entity_id": f"sw-occurrence:{index:04d}",
                        "cad_occurrence_alias": item["id"],
                        "cad_document": item["document"],
                    }
                    for index, item in enumerate(instances)
                ],
            },
        )
        write_json(
            bundle_dir / "frame-graph.json",
            {
                "schema": "lab.frame_graph/v0",
                "root": "cad_assembly_root",
                "frames": [
                    {"id": "cad_assembly_root", "parent": None},
                    *[
                        {
                            "id": f"sw-occurrence:{index:04d}",
                            "parent": "cad_assembly_root",
                            "transform": item["transform_world"],
                            "source": "solidworks_solved_assembly",
                        }
                        for index, item in enumerate(instances)
                    ],
                ],
            },
        )
        write_json(
            bundle_dir / "geometry-roles.json",
            {
                "schema": "lab.geometry_roles/v0",
                "entities": [
                    {
                        "id": f"sw-occurrence:{index:04d}",
                        "roles": ["visual", "selection", "collision-candidate"],
                        "collision_status": "unreviewed-render-geometry",
                    }
                    for index, _ in enumerate(instances)
                ],
            },
        )
        write_json(
            bundle_dir / "capability.json",
            {
                "grade": "semantic-scene",
                "allows": ["workbench_display", "stable_picking"],
                "forbids": ["motion", "spatial_interlock_enforced", "execution"],
                "missing": ["approved_mate_semantics", "qualified_collision", "site_calibration"],
            },
        )
        write_json(
            bundle_dir / "provenance.json",
            {
                "schema": "lab.provenance/v0",
                "adapter": "SwPackAndGoAdapter/SolidWorks-2025-SP05/trial-v0",
                "source_digest": source_digest,
                "com_revision": report.get("com_revision"),
                "open_errors": report.get("open_errors"),
                "open_warnings": report.get("open_warnings"),
                "open_warning_flags": ["read-only", "needs-regeneration"]
                if report.get("open_warnings") == 34
                else ["see-solidworks-warning-bitmask"],
                "component_count": report.get("component_count"),
                "mate_candidate_count": report.get("mate_candidate_count"),
                "render": glb_stats(bundle_dir / "render-lod0.glb"),
            },
        )
        artifact_names = [
            "source.json",
            "files.sha256",
            "assembly.snapshot.json",
            "entity-registry.json",
            "frame-graph.json",
            "geometry-roles.json",
            "capability.json",
            "provenance.json",
            "render-lod0.glb",
        ]
        write_json(
            bundle_dir / "bundle.json",
            {
                "schema": "lab.family_sim_bundle/v0",
                "family": "instrument.square-tactile",
                "trial_revision": f"source-files-digest:{source_digest}",
                "immutable_candidate": True,
                "artifacts": bundle_artifacts(bundle_dir, artifact_names),
            },
        )
        result_summary["bundle"] = str(bundle_dir)
        result_summary["glb"] = glb_stats(bundle_dir / "render-lod0.glb")
        result_summary["component_count"] = report.get("component_count", 0)
        result_summary["mate_candidate_count"] = report.get("mate_candidate_count", 0)
    return result_summary


def check_solidworks_reproducibility(
    config: dict[str, Any],
    output: Path,
    ascii_temp: Path,
    python: Path,
    solidworks: dict[str, Any],
) -> dict[str, Any]:
    report_dir = output / "reproducibility" / "solidworks-square-tactile"
    report_dir.mkdir(parents=True, exist_ok=True)
    if solidworks.get("status") != "passed" or not solidworks.get("bundle"):
        result = {"status": "not-run", "reason": "primary SolidWorks capture did not pass"}
        write_json(report_dir / "reproducibility-report.json", result)
        return result
    assembly = Path(config["primary_assembly"]).resolve()
    repeat_temp_glb = ascii_temp / "square_tactile_repeat.glb"
    command = [
        str(python),
        str(Path(__file__).with_name("trial_sw_adapter.py")),
        "--assembly",
        str(assembly),
        "--snapshot",
        str(report_dir / "repeat.snapshot.json"),
        "--report",
        str(report_dir / "repeat.capture-report.json"),
        "--glb-ascii",
        str(repeat_temp_glb),
        "--progid",
        config["progid"],
    ]
    if config.get("visible_first_export"):
        command.append("--visible")
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    write_text(report_dir / "repeat.console.log", (process.stdout or "") + (process.stderr or ""))
    repeat_capture_path = report_dir / "repeat.capture-report.json"
    repeat_capture = (
        json.loads(repeat_capture_path.read_text(encoding="utf-8"))
        if repeat_capture_path.exists()
        else {"status": "blocked"}
    )
    primary_glb = Path(solidworks["bundle"]) / "render-lod0.glb"
    repeat_glb = report_dir / "repeat-render.glb"
    if repeat_capture.get("status") == "passed" and repeat_temp_glb.exists():
        shutil.copy2(repeat_temp_glb, repeat_glb)
        primary_document = read_glb_json(primary_glb)
        repeat_document = read_glb_json(repeat_glb)
        primary_json_hash = sha256_text(json.dumps(primary_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        repeat_json_hash = sha256_text(json.dumps(repeat_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        primary_snapshot = json.loads(
            (Path(solidworks["capture"]) / "assembly.snapshot.json").read_text(encoding="utf-8")
        )
        repeat_snapshot = json.loads((report_dir / "repeat.snapshot.json").read_text(encoding="utf-8"))
        primary_snapshot_hash = sha256_text(
            json.dumps(primary_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        repeat_snapshot_hash = sha256_text(
            json.dumps(repeat_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        primary_semantic = glb_semantic_signature(primary_glb)
        repeat_semantic = glb_semantic_signature(repeat_glb)
        primary_semantic_hash = sha256_text(
            json.dumps(primary_semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        repeat_semantic_hash = sha256_text(
            json.dumps(repeat_semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        primary_normalized_snapshot = normalized_assembly_snapshot(primary_snapshot)
        repeat_normalized_snapshot = normalized_assembly_snapshot(repeat_snapshot)
        normalized_snapshot_match = primary_normalized_snapshot == repeat_normalized_snapshot
        semantic_match = primary_semantic_hash == repeat_semantic_hash
        exact_match = sha256_file(primary_glb) == sha256_file(repeat_glb)
        result = {
            "schema": "lab.reproducibility_report/v0",
            "status": "passed" if exact_match else "warning",
            "exact_glb_match": exact_match,
            "canonical_glb_json_match": primary_json_hash == repeat_json_hash,
            "assembly_snapshot_match": primary_snapshot_hash == repeat_snapshot_hash,
            "normalized_glb_semantic_match": semantic_match,
            "normalized_assembly_snapshot_match": normalized_snapshot_match,
            "difference_class": "none"
            if exact_match
            else "component_traversal_order_only"
            if semantic_match and normalized_snapshot_match
            else "semantic_difference_requires_investigation",
            "primary_glb": glb_stats(primary_glb),
            "repeat_glb": glb_stats(repeat_glb),
            "primary_canonical_json_sha256": primary_json_hash,
            "repeat_canonical_json_sha256": repeat_json_hash,
            "primary_semantic_sha256": primary_semantic_hash,
            "repeat_semantic_sha256": repeat_semantic_hash,
            "primary_snapshot_sha256": primary_snapshot_hash,
            "repeat_snapshot_sha256": repeat_snapshot_hash,
            "formal_release_allowed": exact_match,
            "note": "Byte mismatch remains release-blocking. The normalized checks distinguish exporter traversal order from missing or changed component geometry.",
        }
    else:
        result = {
            "schema": "lab.reproducibility_report/v0",
            "status": "blocked",
            "reason": "repeat SolidWorks capture failed",
            "repeat_capture": repeat_capture,
            "formal_release_allowed": False,
        }
    write_json(report_dir / "reproducibility-report.json", result)
    return result


def render_report(
    output: Path,
    environment: dict[str, Any],
    inventory: dict[str, Any],
    solidworks: dict[str, Any],
    step_results: list[dict[str, Any]],
    legacy_results: list[dict[str, Any]],
    gate: dict[str, Any],
    previews: list[dict[str, Any]],
    reproducibility: dict[str, Any],
) -> None:
    counts = inventory["extension_counts"]
    urdf = inventory["urdf_summary"]
    legacy_unproven = sum(item.get("candidate_joints", 0) for item in legacy_results)
    solidworks_unproven = solidworks.get("mate_candidate_count", 0)
    unproven = legacy_unproven + solidworks_unproven
    if solidworks["status"] == "passed":
        solidworks_conclusion = (
            "SolidWorks 2025 已只读提取真实组件快照并导出非空 XR GLB；打开警告 34 "
            "被解释为只读与需要重建，已保留在 provenance，未因此提升运动或碰撞资格。"
        )
        solidworks_undone = "SolidWorks 原生 snapshot/XR GLB 已发布为试验候选；mate 仍全部待人工确认。"
    else:
        solidworks_conclusion = (
            "SolidWorks 2025 COM 路径未通过 capture gate，原生装配快照与 XR GLB 未发布。"
        )
        solidworks_undone = "未发布 SolidWorks 原生装配 snapshot/XR GLB：capture gate 未通过。"
    report = f"""# 资产管线初步测试报告

日期：2026-08-24  
状态：候选试验；不得用于执行或强制空间互锁

## 结论

当前文件夹已完成可重复的资产盘点、SolidWorks 装配摄取、STEP 几何回退、三类 legacy SolidWorks URDF 迁移夹具编译、GLB 输出和家族层硬门禁。厂家机械臂 URDF/Xacro 与控制器导出缺失，因此没有伪造 Robot FamilySimBundle、PointSet 或 ProgramSet。{solidworks_conclusion}

## 本机环境

- Python：`{environment['python']['executable']}`，`{environment['python']['version']}`
- Blender：`{environment['blender'].get('output', ['unavailable'])[0]}`
- SolidWorks COM：版本探测 `33.5.0`；文档打开状态 `{solidworks['status']}`
- 配置与交接说明不一致项：Python 与 SolidWorks 安装路径已在本地 `pipeline.yaml` 中显式覆盖；原 pTLC 仓库不存在，本试验输出改在当前工作区。

## 输入盘点

- URDF `{urdf['files']}` 份，全部可解析 `{urdf['parsed']}` 份；SolidWorks Exporter 输出 `{urdf['solidworks_exporter']}` 份。
- URDF 候选活动机构 `{urdf['articulated']}` 份、候选关节 `{urdf['candidate_joints']}` 个、缺失 mesh 引用 `{urdf['missing_mesh_references']}` 个。
- Visual 与 collision 指向同一 mesh 的 link `{urdf['visual_equals_collision_links']}` 个，均未获得碰撞资格。
- `.SLDASM` `{counts.get('.sldasm', 0)}`、`.SLDPRT` `{counts.get('.sldprt', 0)}`、`.STEP/.STP` `{counts.get('.step', 0) + counts.get('.stp', 0)}`、`.STL` `{counts.get('.stl', 0)}`。

## Slice A — 机械臂家族

状态：**阻塞且未伪造**。当前无厂家 Xacro；82 份 URDF 均是 SolidWorks 导出，不满足机器人运动学真源要求。五轴机械臂 CAD/STEP 只进入输入盘点与几何审计，不生成正式机器人 mechanics。

## Slice B — 装配与视觉资产

- SolidWorks 小装配源发布：`captures/solidworks/square-tactile/`；状态 `{solidworks['status']}`。文件哈希已冻结，COM 失败原文保存在 capture report 与 console log。
- STEP 回退：{len(step_results)} 个代表资产通过，生成 `assembly.snapshot.json` 与 `render-lod0.glb`；资格不高于 `semantic-scene`。
- Legacy 迁移夹具：{len(legacy_results)} 个代表资产通过，包括静态托盘、单轴导轨和复合拧盖夹爪。正式 `joints` 均为空，保留 legacy 关节候选 `{legacy_unproven}` 个；SolidWorks mate 候选 `{solidworks_unproven}` 个；合计 `unproven` `{unproven}` 个。

## Slice C — 控制器点表

状态：**接口完成、数据未发布**。当前 CSV 是 SolidWorks URDF Exporter 元数据，不是控制器导出。已生成 Adapter 合同、原始快照夹具 schema 和遥测 schema；未生成 PointSet、ProgramSet，也未把当前关节伪装成目标点。

## 门禁

- 家族 JSON/GLB 检查数：`{gate['checks_run']}`
- 家族 JSON：`{gate['json_files']}`；GLB：`{gate['glb_files']}`
- 禁止字段、点表文本、嵌入动画/skin、25 MB 预算与 artifact 哈希：**{'通过' if gate['passed'] else '失败'}**
- 失败项：`{len(gate['failures'])}`

## 视觉 QA

- Blender 5.2 以固定视角重载并渲染 `{len(previews)}` 个 GLB；每个预览都同时检查退出码、traceback 文本、PNG 与结构化报告。
- 预览总三角形数：`{sum(item['triangle_count'] for item in previews)}`；所有资产均有非零 mesh 和合理有限包围盒。
- 标准图位于 `previews/`，用于发现空几何、异常尺度、错位和离群部件；本轮人工目视未见明显缺失或离群。

## 可复现性

- SolidWorks 同一源装配隔离重导：`{reproducibility.get('status')}`。
- GLB 字节完全一致：`{reproducibility.get('exact_glb_match')}`；规范化 GLB JSON 一致：`{reproducibility.get('canonical_glb_json_match')}`；装配 snapshot 一致：`{reproducibility.get('assembly_snapshot_match')}`。
- 按组件名、变换、accessor 元数据及二进制 payload 哈希归一后，GLB 语义一致：`{reproducibility.get('normalized_glb_semantic_match')}`；排序后的装配 snapshot 一致：`{reproducibility.get('normalized_assembly_snapshot_match')}`；差异分类：`{reproducibility.get('difference_class')}`。
- 正式发布许可：`{reproducibility.get('formal_release_allowed', False)}`。若字节不一致，当前候选仍可用于视觉测试，但必须先定位 XR/Draco 非确定性来源，不能宣称可复现正式发布。

## 需要人工确认的 unproven 项

- legacy URDF 中所有候选关节的方向、父空间轴向、行程、速度、驱动方式和失电状态。
- STEP/GLB 的工程 Z-up 到 glTF 根坐标变换与稳定实例身份。
- visual mesh 是否可以派生独立保守碰撞体；当前不得用于空间互锁。
- 方形视触觉 Pack and Go 的配置、显示状态、引用完整性，以及 SolidWorks COM/RPC 失败原因。
- 真实 RobotController 点表、程序修订、标定和工具上下文。

## 未做项

- 未发布机器人 FamilySimBundle：缺厂家 URDF/Xacro。
- {solidworks_undone}
- 未发布 collision GLB、PointSet、ProgramSet、DeployManifest 或 activation：证据不足。
- 未修改 Workbench、生产模型或任何原始 CAD/URDF/STL。
"""
    write_text(output / "REPORT.md", report)


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    workspace = Path(config["paths"]["workspace"]).resolve()
    output = Path(config["paths"]["output"]).resolve()
    ascii_temp = Path(config["paths"]["ascii_temp"]).resolve()
    python = Path(config["paths"]["python"]).resolve()
    blender = Path(config["paths"]["blender"]).resolve()
    if not args.keep_output:
        safe_reset_output(workspace, output)
    else:
        output.mkdir(parents=True, exist_ok=True)
    ascii_temp.mkdir(parents=True, exist_ok=True)
    started = time.time()

    environment = {
        "schema": "lab.trial_environment/v0",
        "python": {"executable": str(python), "version": platform.python_version()},
        "blender": command_version([str(blender), "--version"]),
        "solidworks_progid": config["solidworks"]["progid"],
        "workspace": str(workspace),
        "config": str(config_path),
        "cascadio": command_version([str(python), "-c", "import cascadio; print('cascadio 0.1.1')"]),
        "node": command_version(["node", "--version"]),
    }
    write_json(output / "environment.json", environment)
    inventory = scan_inventory(workspace)
    write_json(output / "inventory.json", inventory)

    urdf_summary = inventory["urdf_summary"]
    slice_a = {
        "schema": "lab.trial_slice_status/v0",
        "slice": "A",
        "status": "blocked",
        "reason": "manufacturer_robot_urdf_or_xacro_missing",
        "xacro_count": inventory["extension_counts"].get(".xacro", 0),
        "urdf_count": urdf_summary["files"],
        "solidworks_exporter_urdf_count": urdf_summary["solidworks_exporter"],
        "published_robot_family": False,
    }
    write_json(output / "slices" / "slice-a-status.json", slice_a)

    solidworks = run_solidworks_capture(config["solidworks"], output, ascii_temp, python)
    reproducibility = check_solidworks_reproducibility(
        config["solidworks"], output, ascii_temp, python, solidworks
    )
    step_results = [compile_step_asset(asset, output, ascii_temp) for asset in config["step_assets"]]
    blender_script = Path(__file__).with_name("trial_blender_urdf.py").resolve()
    legacy_results = [
        compile_legacy_urdf(asset, output, ascii_temp, blender, blender_script)
        for asset in config["legacy_urdf_assets"]
    ]
    create_controller_interfaces(output)

    gate = run_family_gates(output / "families", config["gates"])
    write_json(output / "gate-report.json", gate)
    previews = generate_previews(output / "families", output, blender)
    render_report(
        output,
        environment,
        inventory,
        solidworks,
        step_results,
        legacy_results,
        gate,
        previews,
        reproducibility,
    )
    summary = {
        "schema": "lab.asset_pipeline_trial_result/v0",
        "status": "partial-pass" if gate["passed"] else "failed",
        "duration_s": round(time.time() - started, 3),
        "slice_a": slice_a,
        "solidworks_capture": solidworks,
        "step_assets": step_results,
        "legacy_assets": legacy_results,
        "slice_c": "interface-only",
        "family_gate_passed": gate["passed"],
        "preview_assets": len(previews),
        "reproducibility": reproducibility,
    }
    write_json(output / "run-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
