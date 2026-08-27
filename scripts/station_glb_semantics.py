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
