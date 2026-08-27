"""投料站 handoff 单测使用的确定性 GLB 与复现性夹具。"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


GLB_GEOMETRY = {"nodes": 1, "meshes": 1, "primitives": 1, "accessors": 1}


def minimal_glb() -> bytes:
    document = {
        "asset": {"version": "2.0", "generator": "station-fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [1.0, 1.0, 0.0],
            }
        ],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
        "buffers": [{"byteLength": 36}],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary_chunk = struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(binary_chunk), 0x004E4942)
        + binary_chunk
    )


def capture_report(component_count: int, glb: bytes) -> dict[str, Any]:
    return {
        "schema": "lab.solidworks_capture_report/v0",
        "source_document": "C:\\station\\station.sldasm",
        "source_read_only": True,
        "status": "passed",
        "com_revision": "33.5.0",
        "open_errors": 0,
        "open_warnings": 0,
        "component_count": component_count,
        "glb_export": {
            "save_result": True,
            "exists": True,
            "bytes": len(glb),
            "magic": "glTF",
            "geometry": dict(GLB_GEOMETRY),
        },
    }


def write_reproducibility(
    root: Path,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    glb: bytes,
) -> dict[str, str]:
    repeat = root / "audit" / "repeat"
    repeat.mkdir(parents=True, exist_ok=True)
    primary_snapshot = root / "capture" / "assembly.snapshot.json"
    primary_glb = root / "geometry" / "station.glb"
    repeat_snapshot = repeat / "assembly.snapshot.json"
    repeat_report = repeat / "capture-report.json"
    repeat_glb = repeat / "station.glb"
    repeat_snapshot.write_text(json.dumps(snapshot), encoding="utf-8")
    repeat_report.write_text(json.dumps(report), encoding="utf-8")
    repeat_glb.write_bytes(glb)
    repro = {
        "schema": "lab.station_capture_reproducibility/v0",
        "status": "passed",
        "normalized_snapshot_match": True,
        "exact_glb_match": True,
        "normalized_glb_semantic_match": True,
        "difference_class": "none",
        "acceptance_basis": "exact-bytes",
        "primary_snapshot_sha256": sha256(primary_snapshot),
        "repeat_snapshot_sha256": sha256(repeat_snapshot),
        "primary_glb_sha256": sha256(primary_glb),
        "repeat_glb_sha256": sha256(repeat_glb),
    }
    report_path = root / "audit" / "reproducibility-report.json"
    report_path.write_text(json.dumps(repro), encoding="utf-8")
    return {
        "report": "audit/reproducibility-report.json",
        "repeat_snapshot": "audit/repeat/assembly.snapshot.json",
        "repeat_capture_report": "audit/repeat/capture-report.json",
        "repeat_glb": "audit/repeat/station.glb",
        "glb_semantic_diagnosis": None,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
