"""P0 输入冻结与 P1 handoff 封装工具测试。"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from station_fixture_support import capture_report, minimal_glb  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script(name: str):
    return load_module(name, ROOT / "scripts" / f"{name}.py")


INVENTORY = load_script("inventory_station_source")
FINALIZE = load_script("finalize_station_handoff")
SEMANTICS = load_script("station_glb_semantics")
ADAPTER = load_module(
    "trial_sw_adapter",
    ROOT
    / "unilab-workbench-e2e-handoff-20260824"
    / "pipeline"
    / "trial_sw_adapter.py",
)


def write_glb(path: Path, document: dict, binary: bytes) -> None:
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
VERIFY = load_script("verify_station_handoff")


class StationP0P1ToolsTest(unittest.TestCase):
    def test_swx_pid_document_paths_are_normalized_without_hiding_other_drift(self) -> None:
        first = r"C:\Users\operator\AppData\Local\Temp\swx10144\VC~~\虚拟件\装配体.SLDASM"
        repeat = r"C:\Users\operator\AppData\Local\Temp\swx19676\VC~~\虚拟件\装配体.SLDASM"
        expected = r"C:\Users\operator\AppData\Local\Temp\swx<PID>\VC~~\虚拟件\装配体.SLDASM"
        self.assertEqual(ADAPTER.normalized_document_path(first), expected)
        self.assertEqual(ADAPTER.normalized_document_path(repeat), expected)

        base = {
            "schema": "lab.assembly_snapshot/v0",
            "instances": [{"id": "VIRTUAL-1", "document": first}],
            "mates_candidate": [],
            "root_occurrences": ["VIRTUAL-1"],
        }
        other = json.loads(json.dumps(base))
        other["instances"][0]["document"] = repeat
        self.assertEqual(
            FINALIZE.normalized_snapshot(base),
            FINALIZE.normalized_snapshot(other),
        )
        other["instances"][0]["document"] = repeat.replace("装配体", "另一装配体")
        self.assertNotEqual(
            FINALIZE.normalized_snapshot(base),
            FINALIZE.normalized_snapshot(other),
        )

    def test_glb_semantics_normalizes_indices_but_detects_scene_or_payload_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            document = {
                "asset": {"version": "2.0", "generator": "SOLIDWORKSGLTF"},
                "buffers": [{"byteLength": 4}],
                "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 4}],
                "accessors": [
                    {
                        "bufferView": 0,
                        "componentType": 5126,
                        "count": 1,
                        "type": "VEC3",
                    }
                ],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                "nodes": [
                    {"name": "ROOT", "children": [1]},
                    {"name": "PART", "mesh": 0},
                ],
                "scenes": [{"nodes": [0]}],
                "scene": 0,
            }
            primary = root / "primary.glb"
            repeat = root / "repeat.glb"
            write_glb(primary, document, b"1234")

            reordered = json.loads(json.dumps(document))
            reordered["nodes"] = [
                {"name": "PART", "mesh": 0},
                {"name": "ROOT", "children": [0]},
            ]
            reordered["scenes"][0]["nodes"] = [1]
            write_glb(repeat, reordered, b"1234")
            traversal_only = SEMANTICS.diagnose_glb_pair(primary, repeat)
            self.assertTrue(traversal_only["normalized_glb_semantic_match"])
            self.assertEqual(
                traversal_only["difference_class"],
                "component_traversal_order_only",
            )

            reordered["nodes"][1]["translation"] = [1.0, 0.0, 0.0]
            write_glb(repeat, reordered, b"1234")
            scene_drift = SEMANTICS.diagnose_glb_pair(primary, repeat)
            self.assertFalse(scene_drift["normalized_glb_semantic_match"])

            del reordered["nodes"][1]["translation"]
            write_glb(repeat, reordered, b"5678")
            payload_drift = SEMANTICS.diagnose_glb_pair(primary, repeat)
            self.assertFalse(payload_drift["normalized_glb_semantic_match"])

    def test_inventory_manifest_is_deterministic_and_output_stays_external(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            source.mkdir()
            (source / "投料站方案模拟1.1.SLDASM").write_bytes(b"assembly")
            parts = source / "parts"
            parts.mkdir()
            (parts / "a.SLDPRT").write_bytes(b"part-a")
            (parts / "b.SLDPRT").write_bytes(b"part-b")

            first, first_manifest = INVENTORY.build_inventory(
                source, "投料站方案模拟1.1.SLDASM"
            )
            second, second_manifest = INVENTORY.build_inventory(
                source, "投料站方案模拟1.1.SLDASM"
            )
            self.assertEqual(first_manifest, second_manifest)
            self.assertEqual(first["source_files_digest"], second["source_files_digest"])
            self.assertEqual(first["file_count"], 3)
            self.assertEqual(first["cad_file_count"], 3)

            output = root / "p0"
            INVENTORY.write_outputs(output, first, first_manifest)
            self.assertEqual(
                (output / "files.sha256").read_text(encoding="utf-8"),
                first_manifest,
            )
            self.assertIn("input-inventory-only", json.dumps(first))

    def test_finalize_builds_relative_handoff_bound_to_p0_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "handoff"
            release = root / "source-release"
            capture = root / "capture"
            release.mkdir(parents=True)
            capture.mkdir()
            (release / "station.sldasm").write_bytes(b"solidworks")
            manifest = FINALIZE.source_manifest(release)
            p0 = root / "p0.sha256"
            p0.write_text(manifest, encoding="utf-8")

            identity = {
                "xyz_m": [0.0, 0.0, 0.0],
                "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scale": 1.0,
            }
            snapshot = capture / "raw-snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "lab.assembly_snapshot/v0",
                        "units": {
                            "length": "m",
                            "angle": "rad",
                            "orientation": "quaternion_xyzw",
                        },
                        "instances": [
                            {"id": "ROOT-1", "parent": None, "transform_world": identity}
                        ],
                        "root_occurrences": ["ROOT-1"],
                        "mates_candidate": [],
                    }
                ),
                encoding="utf-8",
            )
            report = capture / "raw-report.json"
            glb_bytes = minimal_glb()
            report.write_text(
                json.dumps(capture_report(1, glb_bytes)),
                encoding="utf-8",
            )
            glb = root / "temporary.glb"
            glb.write_bytes(glb_bytes)
            repeat_snapshot = root / "repeat-snapshot.json"
            repeat_snapshot.write_bytes(snapshot.read_bytes())
            repeat_report = root / "repeat-report.json"
            repeat_report.write_bytes(report.read_bytes())
            repeat_glb = root / "repeat.glb"
            repeat_glb.write_bytes(glb.read_bytes())

            result = FINALIZE.finalize(
                output_root=root,
                source_release_root=release,
                snapshot_input=snapshot,
                report_input=report,
                glb_input=glb,
                repeat_snapshot_input=repeat_snapshot,
                repeat_report_input=repeat_report,
                repeat_glb_input=repeat_glb,
                station="eit.feeding-station",
                p0_manifest=p0,
            )
            self.assertTrue(result["passed"])
            handoff = json.loads((root / "station-handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(
                handoff["solidworks_capture"]["source_release_root"],
                "source-release",
            )
            self.assertFalse(
                Path(handoff["solidworks_capture"]["assembly_snapshot"]).is_absolute()
            )
            self.assertTrue((root / "geometry" / "station.glb").is_file())
            reproducibility = json.loads(
                (root / "audit" / "reproducibility-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(reproducibility["exact_glb_match"])
            self.assertEqual(reproducibility["acceptance_basis"], "exact-bytes")
            validation = VERIFY.HandoffValidation(root / "station-handoff.json").run()
            self.assertTrue(validation["passed"], validation["errors"])

    def test_finalize_accepts_hash_bound_semantic_traversal_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "handoff"
            release = root / "source-release"
            capture = root / "capture"
            release.mkdir(parents=True)
            capture.mkdir()
            (release / "station.sldasm").write_bytes(b"solidworks")
            p0 = root / "p0.sha256"
            p0.write_text(FINALIZE.source_manifest(release), encoding="utf-8")

            transform = {
                "xyz_m": [0.0, 0.0, 0.0],
                "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scale": 1.0,
            }
            snapshot_value = {
                "schema": "lab.assembly_snapshot/v0",
                "units": {
                    "length": "m",
                    "angle": "rad",
                    "orientation": "quaternion_xyzw",
                },
                "instances": [
                    {
                        "id": "VIRTUAL-1",
                        "document": r"C:\Temp\swx10144\VC~~\part.SLDASM",
                        "parent": None,
                        "transform_world": transform,
                    }
                ],
                "root_occurrences": ["VIRTUAL-1"],
                "mates_candidate": [],
            }
            snapshot = capture / "raw-snapshot.json"
            snapshot.write_text(json.dumps(snapshot_value), encoding="utf-8")
            repeat_value = json.loads(json.dumps(snapshot_value))
            repeat_value["instances"][0]["document"] = (
                r"C:\Temp\swx19676\VC~~\part.SLDASM"
            )
            repeat_snapshot = root / "repeat-snapshot.json"
            repeat_snapshot.write_text(json.dumps(repeat_value), encoding="utf-8")

            report_value = {
                "schema": "lab.solidworks_capture_report/v0",
                "status": "passed",
                "source_read_only": True,
                "component_count": 1,
            }
            report = capture / "raw-report.json"
            report.write_text(json.dumps(report_value), encoding="utf-8")
            repeat_report = root / "repeat-report.json"
            repeat_report.write_text(json.dumps(report_value), encoding="utf-8")

            document = {
                "asset": {"version": "2.0", "generator": "SOLIDWORKSGLTF"},
                "buffers": [{"byteLength": 8}],
                "bufferViews": [
                    {"buffer": 0, "byteOffset": 0, "byteLength": 4},
                    {"buffer": 0, "byteOffset": 4, "byteLength": 4},
                ],
                "accessors": [
                    {"bufferView": 0, "componentType": 5123, "count": 2, "type": "SCALAR"},
                    {"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC3"},
                ],
                "meshes": [
                    {"primitives": [{"indices": 0, "attributes": {"POSITION": 1}}]}
                ],
                "nodes": [
                    {"name": "A", "mesh": 0},
                    {"name": "B", "mesh": 0, "translation": [1.0, 0.0, 0.0]},
                ],
            }
            glb = root / "primary.glb"
            repeat_glb = root / "repeat.glb"
            write_glb(glb, document, b"12345678")
            repeat_document = json.loads(json.dumps(document))
            repeat_document["nodes"].reverse()
            write_glb(repeat_glb, repeat_document, b"12345678")
            diagnosis_value = SEMANTICS.diagnose_glb_pair(glb, repeat_glb)
            self.assertFalse(diagnosis_value["exact_glb_match"])
            self.assertTrue(diagnosis_value["normalized_glb_semantic_match"])
            diagnosis = root / "diagnosis.json"
            diagnosis.write_text(json.dumps(diagnosis_value), encoding="utf-8")

            result = FINALIZE.finalize(
                output_root=root,
                source_release_root=release,
                snapshot_input=snapshot,
                report_input=report,
                glb_input=glb,
                repeat_snapshot_input=repeat_snapshot,
                repeat_report_input=repeat_report,
                repeat_glb_input=repeat_glb,
                station="eit.feeding-station",
                p0_manifest=p0,
                semantic_diagnosis_input=diagnosis,
            )
            self.assertTrue(result["passed"])
            reproducibility = json.loads(
                (root / "audit" / "reproducibility-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(reproducibility["exact_glb_match"])
            self.assertTrue(reproducibility["normalized_glb_semantic_match"])
            self.assertEqual(
                reproducibility["acceptance_basis"], "mac-semantic-diagnosis"
            )

            diagnosis_value["repeat_glb"]["sha256"] = "0" * 64
            diagnosis.write_text(json.dumps(diagnosis_value), encoding="utf-8")
            with self.assertRaisesRegex(FINALIZE.FinalizeError, "SHA-256"):
                FINALIZE.finalize(
                    output_root=root,
                    source_release_root=release,
                    snapshot_input=snapshot,
                    report_input=report,
                    glb_input=glb,
                    repeat_snapshot_input=repeat_snapshot,
                    repeat_report_input=repeat_report,
                    repeat_glb_input=repeat_glb,
                    station="eit.feeding-station",
                    p0_manifest=p0,
                    semantic_diagnosis_input=diagnosis,
                )
    def test_finalize_rejects_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "handoff"
            release = root / "source-release"
            release.mkdir(parents=True)
            (release / "station.sldasm").write_bytes(b"changed")
            p0 = root / "p0.sha256"
            p0.write_text("0" * 64 + "  station.sldasm\n", encoding="utf-8")
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "lab.assembly_snapshot/v0",
                        "instances": [{"id": "ROOT-1"}],
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "schema": "lab.solidworks_capture_report/v0",
                        "status": "passed",
                        "source_read_only": True,
                        "component_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            glb = root / "station.glb"
            glb.write_bytes(b"glTF" + b"0" * 20)
            repeat_snapshot = root / "repeat-snapshot.json"
            repeat_snapshot.write_bytes(snapshot.read_bytes())
            repeat_report = root / "repeat-report.json"
            repeat_report.write_bytes(report.read_bytes())
            repeat_glb = root / "repeat.glb"
            repeat_glb.write_bytes(glb.read_bytes())
            with self.assertRaisesRegex(FINALIZE.FinalizeError, "P0 files.sha256"):
                FINALIZE.finalize(
                    output_root=root,
                    source_release_root=release,
                    snapshot_input=snapshot,
                    report_input=report,
                    glb_input=glb,
                    repeat_snapshot_input=repeat_snapshot,
                    repeat_report_input=repeat_report,
                    repeat_glb_input=repeat_glb,
                    station="eit.feeding-station",
                    p0_manifest=p0,
                )


if __name__ == "__main__":
    unittest.main()
