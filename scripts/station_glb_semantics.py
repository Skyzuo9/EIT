#!/usr/bin/env python3
"""Standard-library GLB semantic signatures for P1 reproducibility checks."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any


DIAGNOSIS_SCHEMA = "lab.station_glb_semantic_diagnosis/v0"
ALGORITHM = "solidworks-gltf-scene-geometry-payload/v2"
SWX_SESSION_SEGMENT = re.compile(r"(?i)(?<=[\\/])swx\d+(?=[\\/])")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_document_path(value: Any) -> str:
    return SWX_SESSION_SEGMENT.sub("swx<PID>", str(value or ""))


def normalized_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = dict(snapshot)
    instances = []
    for raw in snapshot.get("instances", []):
        item = dict(raw)
        if "document" in item:
            item["document"] = normalized_document_path(item["document"])
        instances.append(item)
    value["instances"] = sorted(instances, key=lambda item: item["id"])
    value["mates_candidate"] = sorted(
        snapshot.get("mates_candidate", []), key=lambda item: item.get("id", "")
    )
    value["root_occurrences"] = sorted(snapshot.get("root_occurrences", []))
    return value


def read_glb_layout(path: Path) -> tuple[dict[str, Any], int, int]:
    """Return the JSON document and byte range of the GLB BIN chunk."""

    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12:
            raise ValueError(f"GLB header is truncated: {path}")
        magic, version, total_length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or total_length != size:
            raise ValueError(
                f"invalid GLB header: magic={magic!r}, version={version}, "
                f"declared={total_length}, actual={size}"
            )

        document: dict[str, Any] | None = None
        binary_offset = -1
        binary_length = 0
        while handle.tell() + 8 <= total_length:
            raw_chunk_header = handle.read(8)
            chunk_length, chunk_type = struct.unpack("<II", raw_chunk_header)
            chunk_offset = handle.tell()
            if chunk_offset + chunk_length > total_length:
                raise ValueError(f"GLB chunk exceeds declared length: {path}")
            if chunk_type == 0x4E4F534A:
                chunk = handle.read(chunk_length)
                value = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError(f"GLB JSON chunk is not an object: {path}")
                document = value
            elif chunk_type == 0x004E4942:
                binary_offset = chunk_offset
                binary_length = chunk_length
                handle.seek(chunk_length, 1)
            else:
                handle.seek(chunk_length, 1)

        if handle.tell() != total_length:
            raise ValueError(f"GLB chunk layout does not consume declared length: {path}")

    if document is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    if binary_offset < 0:
        raise ValueError(f"GLB has no BIN chunk: {path}")
    return document, binary_offset, binary_length


def glb_semantic_signature(path: Path) -> dict[str, Any]:
    """Normalize array traversal order while retaining the complete static scene."""

    document, binary_offset, binary_length = read_glb_layout(path)
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    meshes = document.get("meshes", [])
    nodes = document.get("nodes", [])
    materials = document.get("materials", [])
    cameras = document.get("cameras", [])
    accessor_cache: dict[int, dict[str, Any]] = {}
    view_cache: dict[int, dict[str, Any]] = {}
    mesh_cache: dict[int, dict[str, Any]] = {}
    node_cache: dict[int, dict[str, Any]] = {}
    active_nodes: set[int] = set()

    if document.get("skins") or document.get("animations"):
        raise ValueError("static SolidWorks GLB diagnosis does not support skins/animations")

    buffers = document.get("buffers", [])
    if len(buffers) != 1 or buffers[0].get("uri") is not None:
        raise ValueError("semantic diagnosis requires one embedded GLB buffer")

    with path.open("rb") as handle:

        def buffer_view_signature(index: int) -> dict[str, Any]:
            cached = view_cache.get(index)
            if cached is not None:
                return cached
            view = views[index]
            if int(view.get("buffer", 0)) != 0:
                raise ValueError(f"bufferView {index} does not use the embedded buffer")
            relative_start = int(view.get("byteOffset", 0))
            length = int(view["byteLength"])
            if relative_start < 0 or relative_start + length > binary_length:
                raise ValueError(f"bufferView {index} exceeds GLB BIN chunk")
            handle.seek(binary_offset + relative_start)
            payload = handle.read(length)
            if len(payload) != length:
                raise ValueError(f"bufferView {index} is truncated")
            signature = {
                "byteLength": length,
                "byteStride": view.get("byteStride"),
                "target": view.get("target"),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            view_cache[index] = signature
            return signature

        def accessor_signature(index: int) -> dict[str, Any]:
            cached = accessor_cache.get(index)
            if cached is not None:
                return cached
            accessor = accessors[index]
            view_index = accessor.get("bufferView")
            sparse = accessor.get("sparse")
            sparse_signature: dict[str, Any] | None = None
            if sparse is not None:
                indices = sparse["indices"]
                values = sparse["values"]
                sparse_signature = {
                    "count": sparse["count"],
                    "indices": {
                        "componentType": indices["componentType"],
                        "byteOffset": indices.get("byteOffset", 0),
                        "bufferView": buffer_view_signature(indices["bufferView"]),
                    },
                    "values": {
                        "byteOffset": values.get("byteOffset", 0),
                        "bufferView": buffer_view_signature(values["bufferView"]),
                    },
                }
            signature = {
                "componentType": accessor["componentType"],
                "count": accessor["count"],
                "type": accessor["type"],
                "byteOffset": accessor.get("byteOffset", 0),
                "min": accessor.get("min"),
                "max": accessor.get("max"),
                "normalized": accessor.get("normalized", False),
                "sparse": sparse_signature,
                "bufferView": buffer_view_signature(view_index)
                if view_index is not None
                else None,
            }
            accessor_cache[index] = signature
            return signature

        def material_signature(index: int) -> dict[str, Any]:
            return materials[index]

        def mesh_signature(index: int) -> dict[str, Any]:
            cached = mesh_cache.get(index)
            if cached is not None:
                return cached
            mesh = meshes[index]
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
                            for semantic, index in sorted(
                                primitive.get("attributes", {}).items()
                            )
                        },
                        "targets": [
                            {
                                semantic: accessor_signature(index)
                                for semantic, index in sorted(target.items())
                            }
                            for target in primitive.get("targets", [])
                        ],
                        "material": material_signature(primitive["material"])
                        if "material" in primitive
                        else None,
                    }
                )
            signature = {
                "name": mesh.get("name"),
                "weights": mesh.get("weights"),
                "primitives": primitives,
            }
            mesh_cache[index] = signature
            return signature

        def sorted_signatures(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(
                values,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )

        def node_signature(index: int) -> dict[str, Any]:
            cached = node_cache.get(index)
            if cached is not None:
                return cached
            if index in active_nodes:
                raise ValueError(f"GLB node graph contains a cycle at node {index}")
            active_nodes.add(index)
            node = nodes[index]
            children = [node_signature(child) for child in node.get("children", [])]
            signature = {
                "name": node.get("name"),
                "translation": node.get("translation", [0.0, 0.0, 0.0]),
                "rotation": node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
                "scale": node.get("scale", [1.0, 1.0, 1.0]),
                "matrix": node.get("matrix"),
                "weights": node.get("weights"),
                "mesh": mesh_signature(node["mesh"]) if "mesh" in node else None,
                "camera": cameras[node["camera"]] if "camera" in node else None,
                "children": sorted_signatures(children),
            }
            active_nodes.remove(index)
            node_cache[index] = signature
            return signature

        child_indices = {
            child
            for node in nodes
            for child in node.get("children", [])
        }
        root_indices = sorted(set(range(len(nodes))) - child_indices)
        node_forest = sorted_signatures([node_signature(index) for index in root_indices])
        if len(node_cache) != len(nodes):
            raise ValueError("GLB node graph contains unreachable or cyclic nodes")

        scene_signatures = []
        for scene in document.get("scenes", []):
            scene_signatures.append(
                {
                    "name": scene.get("name"),
                    "nodes": sorted_signatures(
                        [node_signature(index) for index in scene.get("nodes", [])]
                    ),
                }
            )
        default_scene_index = document.get("scene", 0)
        default_scene_signature = (
            scene_signatures[default_scene_index]
            if scene_signatures
            else None
        )

        image_signatures = []
        for item in document.get("images", []):
            image_signatures.append(
                {
                    "name": item.get("name"),
                    "mimeType": item.get("mimeType"),
                    "uri": item.get("uri"),
                    "bufferView": buffer_view_signature(item["bufferView"])
                    if "bufferView" in item
                    else None,
                }
            )

        all_accessor_signatures = sorted_signatures(
            [accessor_signature(index) for index in range(len(accessors))]
        )
        all_view_signatures = sorted_signatures(
            [buffer_view_signature(index) for index in range(len(views))]
        )

    return {
        "algorithm": ALGORITHM,
        "asset": document.get("asset"),
        "extensionsUsed": sorted(document.get("extensionsUsed", [])),
        "extensionsRequired": sorted(document.get("extensionsRequired", [])),
        "node_forest": node_forest,
        "scenes": sorted_signatures(scene_signatures),
        "default_scene": default_scene_signature,
        "accessors": all_accessor_signatures,
        "buffer_views": all_view_signatures,
        "materials": sorted_signatures(list(materials)),
        "cameras": sorted_signatures(list(cameras)),
        "images": sorted_signatures(image_signatures),
        "textures": sorted_signatures(list(document.get("textures", []))),
        "samplers": sorted_signatures(list(document.get("samplers", []))),
        "buffer_byte_lengths": sorted(
            int(buffer.get("byteLength", 0)) for buffer in buffers
        ),
    }


def glb_stats(path: Path) -> dict[str, Any]:
    document, _, _ = read_glb_layout(path)
    meshes = document.get("meshes", [])
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "nodes": len(document.get("nodes", [])),
        "meshes": len(meshes),
        "primitives": sum(len(mesh.get("primitives", [])) for mesh in meshes),
        "accessors": len(document.get("accessors", [])),
        "materials": len(document.get("materials", [])),
    }


def _matrix_multiply(left: list[float], right: list[float]) -> list[float]:
    """Multiply two glTF column-major 4x4 matrices."""

    return [
        sum(left[k * 4 + row] * right[column * 4 + k] for k in range(4))
        for column in range(4)
        for row in range(4)
    ]


def _node_matrix(node: dict[str, Any]) -> list[float]:
    if "matrix" in node:
        matrix = [float(value) for value in node["matrix"]]
        if len(matrix) != 16:
            raise ValueError("GLB node matrix must contain 16 values")
        return matrix
    translation = [float(value) for value in node.get("translation", [0.0, 0.0, 0.0])]
    rotation = [float(value) for value in node.get("rotation", [0.0, 0.0, 0.0, 1.0])]
    scale = [float(value) for value in node.get("scale", [1.0, 1.0, 1.0])]
    if len(translation) != 3 or len(rotation) != 4 or len(scale) != 3:
        raise ValueError("GLB node TRS dimensions are invalid")
    x, y, z, w = rotation
    norm = (x * x + y * y + z * z + w * w) ** 0.5
    if norm == 0.0:
        raise ValueError("GLB node quaternion has zero norm")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    sx, sy, sz = scale
    matrix = [
        (1.0 - 2.0 * (y * y + z * z)) * sx,
        (2.0 * (x * y + z * w)) * sx,
        (2.0 * (x * z - y * w)) * sx,
        0.0,
        (2.0 * (x * y - z * w)) * sy,
        (1.0 - 2.0 * (x * x + z * z)) * sy,
        (2.0 * (y * z + x * w)) * sy,
        0.0,
        (2.0 * (x * z + y * w)) * sz,
        (2.0 * (y * z - x * w)) * sz,
        (1.0 - 2.0 * (x * x + y * y)) * sz,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    ]
    return matrix


def _transform_point(matrix: list[float], point: list[float]) -> list[float]:
    x, y, z = point
    return [
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    ]


def glb_geometry_stats(path: Path) -> dict[str, Any]:
    """Return auditable geometry, material, and world-bounds statistics."""

    document, _, _ = read_glb_layout(path)
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    accessors = document.get("accessors", [])
    materials = document.get("materials", [])
    parent_counts = [0] * len(nodes)
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"GLB node {node_index} is not an object")
        for child in node.get("children", []):
            if not isinstance(child, int) or child < 0 or child >= len(nodes):
                raise ValueError(f"GLB node {node_index} has an invalid child index")
            parent_counts[child] += 1
            if parent_counts[child] > 1:
                raise ValueError(f"GLB node {child} has multiple parents")

    primitive_count = 0
    vertex_count = 0
    triangle_count = 0
    material_assignments = 0
    local_bounds: dict[int, tuple[list[float], list[float]]] = {}
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            raise ValueError(f"GLB mesh {mesh_index} is not an object")
        mesh_min: list[float] | None = None
        mesh_max: list[float] | None = None
        for primitive in mesh.get("primitives", []):
            primitive_count += 1
            attributes = primitive.get("attributes", {})
            position_index = attributes.get("POSITION") if isinstance(attributes, dict) else None
            if not isinstance(position_index, int) or not 0 <= position_index < len(accessors):
                raise ValueError(f"GLB mesh {mesh_index} primitive lacks a valid POSITION accessor")
            position = accessors[position_index]
            count = int(position.get("count", 0))
            if count <= 0:
                raise ValueError("GLB POSITION accessor count must be positive")
            vertex_count += count
            minimum = position.get("min")
            maximum = position.get("max")
            if (
                not isinstance(minimum, list)
                or not isinstance(maximum, list)
                or len(minimum) != 3
                or len(maximum) != 3
            ):
                raise ValueError("GLB POSITION accessor must declare three-dimensional min/max")
            primitive_min = [float(value) for value in minimum]
            primitive_max = [float(value) for value in maximum]
            if any(low > high for low, high in zip(primitive_min, primitive_max)):
                raise ValueError("GLB POSITION accessor min exceeds max")
            mesh_min = primitive_min if mesh_min is None else [
                min(left, right) for left, right in zip(mesh_min, primitive_min)
            ]
            mesh_max = primitive_max if mesh_max is None else [
                max(left, right) for left, right in zip(mesh_max, primitive_max)
            ]
            element_count = count
            if "indices" in primitive:
                index = primitive["indices"]
                if not isinstance(index, int) or not 0 <= index < len(accessors):
                    raise ValueError("GLB primitive has an invalid indices accessor")
                element_count = int(accessors[index].get("count", 0))
            mode = int(primitive.get("mode", 4))
            if mode == 4:
                triangle_count += element_count // 3
            elif mode in {5, 6}:
                triangle_count += max(0, element_count - 2)
            if "material" in primitive:
                material_index = primitive["material"]
                if not isinstance(material_index, int) or not 0 <= material_index < len(materials):
                    raise ValueError("GLB primitive has an invalid material index")
                material_assignments += 1
        if mesh_min is not None and mesh_max is not None:
            local_bounds[mesh_index] = (mesh_min, mesh_max)

    identity = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    world_min: list[float] | None = None
    world_max: list[float] | None = None
    visited: set[int] = set()
    active: set[int] = set()

    def visit(index: int, parent_matrix: list[float]) -> None:
        nonlocal world_min, world_max
        if index in active:
            raise ValueError(f"GLB node graph contains a cycle at node {index}")
        active.add(index)
        visited.add(index)
        node = nodes[index]
        world = _matrix_multiply(parent_matrix, _node_matrix(node))
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            if not isinstance(mesh_index, int) or mesh_index not in local_bounds:
                raise ValueError(f"GLB node {index} has an invalid or empty mesh")
            low, high = local_bounds[mesh_index]
            for x in (low[0], high[0]):
                for y in (low[1], high[1]):
                    for z in (low[2], high[2]):
                        point = _transform_point(world, [x, y, z])
                        world_min = point if world_min is None else [
                            min(left, right) for left, right in zip(world_min, point)
                        ]
                        world_max = point if world_max is None else [
                            max(left, right) for left, right in zip(world_max, point)
                        ]
        for child in node.get("children", []):
            visit(child, world)
        active.remove(index)

    for root in (index for index, count in enumerate(parent_counts) if count == 0):
        visit(root, identity)
    if len(visited) != len(nodes):
        raise ValueError("GLB node graph contains unreachable or cyclic nodes")
    if world_min is None or world_max is None:
        raise ValueError("GLB contains no bounded render geometry")
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "nodes": len(nodes),
        "meshes": len(meshes),
        "primitives": primitive_count,
        "vertices": vertex_count,
        "triangles": triangle_count,
        "materials": {
            "count": len(materials),
            "assigned_primitives": material_assignments,
            "names": sorted(
                str(item.get("name"))
                for item in materials
                if isinstance(item, dict) and item.get("name") is not None
            ),
        },
        "bounding_box_m": {
            "min": world_min,
            "max": world_max,
            "size": [high - low for low, high in zip(world_min, world_max)],
        },
    }


def diagnose_glb_pair(primary: Path, repeat: Path) -> dict[str, Any]:
    primary = primary.resolve()
    repeat = repeat.resolve()
    primary_signature = glb_semantic_signature(primary)
    repeat_signature = glb_semantic_signature(repeat)
    primary_semantic_hash = canonical_sha256(primary_signature)
    repeat_semantic_hash = canonical_sha256(repeat_signature)
    primary_stats = glb_stats(primary)
    repeat_stats = glb_stats(repeat)
    exact_match = primary_stats["sha256"] == repeat_stats["sha256"]
    semantic_match = primary_semantic_hash == repeat_semantic_hash
    return {
        "schema": DIAGNOSIS_SCHEMA,
        "status": "passed" if semantic_match else "failed",
        "validator_role": "mac-p1-semantic-diagnostics",
        "algorithm": ALGORITHM,
        "exact_glb_match": exact_match,
        "normalized_glb_semantic_match": semantic_match,
        "difference_class": "none"
        if exact_match
        else "component_traversal_order_only"
        if semantic_match
        else "semantic_difference_requires_investigation",
        "primary_glb": primary_stats,
        "repeat_glb": repeat_stats,
        "primary_semantic_sha256": primary_semantic_hash,
        "repeat_semantic_sha256": repeat_semantic_hash,
        "approved_for_p1_packaging": semantic_match,
        "not_qualified_for": [
            "kinematic-preview",
            "collision",
            "spatial-interlock-enforced",
            "execution",
        ],
    }
