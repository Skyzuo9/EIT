"""Windows 工站结果回传门禁测试。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from station_fixture_support import (  # noqa: E402
    capture_report,
    minimal_glb,
    sha256,
    write_reproducibility,
)

SCRIPT = ROOT / "scripts" / "verify_station_handoff.py"
SPEC = importlib.util.spec_from_file_location("verify_station_handoff", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
HandoffValidation = MODULE.HandoffValidation


class StationHandoffTest(unittest.TestCase):
    def test_valid_handoff_passes_without_granting_runtime_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = self._fixture(Path(raw))
            result = HandoffValidation(manifest).run()
            self.assertTrue(result["passed"], result["errors"])
            self.assertEqual(result["details"]["instance_count"], 1)
            self.assertEqual(result["details"]["render_glb_geometry"]["triangles"], 1)
            self.assertTrue(result["details"]["reproducibility"]["exact_glb_match"])
            self.assertEqual(result["details"]["robot"]["joint_count"], 6)
            self.assertIn("execution", result["not_qualified_for"])

    def test_hash_drift_and_path_escape_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._fixture(root)
            source_file = root / "source-release" / "station.sldasm"
            source_file.write_bytes(b"drift")
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["solidworks_capture"]["render_glb"] = "../escape.glb"
            manifest.write_text(json.dumps(value), encoding="utf-8")
            result = HandoffValidation(manifest).run()
            self.assertFalse(result["passed"])
            self.assertTrue(any("哈希不匹配" in item for item in result["errors"]))
            self.assertTrue(any("越出交接目录" in item for item in result["errors"]))

    def test_repeat_glb_drift_requires_mac_semantic_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._fixture(root)
            repeat_glb = root / "audit" / "repeat" / "station.glb"
            repeat_glb.write_bytes(repeat_glb.read_bytes() + b"drift")
            result = HandoffValidation(manifest).run()
            self.assertFalse(result["passed"])
            self.assertTrue(
                any("Mac 语义诊断" in item for item in result["errors"]),
                result["errors"],
            )

    def test_parent_graph_component_count_and_source_aggregate_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._fixture(root)
            snapshot_path = root / "capture" / "assembly.snapshot.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["instances"][0]["parent"] = "MISSING-PARENT"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            report_path = root / "capture" / "capture-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["component_count"] = 2
            report_path.write_text(json.dumps(report), encoding="utf-8")
            source_path = root / "capture" / "source.json"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["source_files_digest"] = hashlib.sha256(b"wrong").hexdigest()
            source_path.write_text(json.dumps(source), encoding="utf-8")

            result = HandoffValidation(manifest).run()
            self.assertFalse(result["passed"])
            self.assertTrue(any("parent 引用不存在" in item for item in result["errors"]))
            self.assertTrue(any("component_count 不一致" in item for item in result["errors"]))
            self.assertTrue(any("聚合摘要不一致" in item for item in result["errors"]))

    def test_parent_cycle_invalid_glb_and_repeat_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._fixture(root, two_nodes=True)
            for relative in (
                "capture/assembly.snapshot.json",
                "audit/repeat/assembly.snapshot.json",
            ):
                path = root / relative
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                snapshot["instances"][0]["parent"] = "CHILD-1"
                snapshot["instances"][1]["parent"] = "FRAME-1"
                snapshot["root_occurrences"] = ["FRAME-1"]
                path.write_text(json.dumps(snapshot), encoding="utf-8")
            (root / "geometry" / "station.glb").write_bytes(b"glTF" + b"broken")
            repeat_snapshot = root / "audit" / "repeat" / "assembly.snapshot.json"
            repeat = json.loads(repeat_snapshot.read_text(encoding="utf-8"))
            repeat["instances"][1]["transform_world"]["xyz_m"] = [2.0, 0.0, 0.0]
            repeat_snapshot.write_text(json.dumps(repeat), encoding="utf-8")

            result = HandoffValidation(manifest).run()
            self.assertFalse(result["passed"])
            self.assertTrue(any("parent 图存在环" in item for item in result["errors"]))
            self.assertTrue(any("结构/几何无效" in item for item in result["errors"]))
            self.assertTrue(any("snapshot 不一致" in item for item in result["errors"]))

    def test_flattened_name2_hierarchy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._fixture(root, two_nodes=True)
            for relative in (
                "capture/assembly.snapshot.json",
                "audit/repeat/assembly.snapshot.json",
            ):
                path = root / relative
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                snapshot["instances"][1]["id"] = "FRAME-1/CHILD-1"
                snapshot["instances"][1]["parent"] = None
                snapshot["root_occurrences"] = ["FRAME-1", "FRAME-1/CHILD-1"]
                path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = HandoffValidation(manifest).run()
            self.assertFalse(result["passed"])
            self.assertTrue(
                any("parent 图退化: 1 个 occurrence" in item for item in result["errors"]),
                result["errors"],
            )

    def test_unexpected_absolute_path_fails_and_warning_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._fixture(root)
            report_path = root / "capture" / "capture-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["open_warnings"] = 34
            report["semantic_output"] = "C:\\private\\unexpected.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = HandoffValidation(manifest).run()
            self.assertFalse(result["passed"])
            self.assertTrue(any("open_warnings=34" in item for item in result["warnings"]))
            self.assertTrue(any("绝对路径只能" in item for item in result["errors"]))

    @staticmethod
    def _fixture(root: Path, *, two_nodes: bool = False) -> Path:
        capture = root / "capture"
        release = root / "source-release"
        geometry = root / "geometry"
        capture.mkdir()
        release.mkdir()
        geometry.mkdir()
        source_file = release / "station.sldasm"
        source_file.write_bytes(b"solidworks-source")
        source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        hashes_path = capture / "files.sha256"
        hashes_path.write_text(f"{source_hash}  station.sldasm\n", encoding="utf-8")
        instances = [
            {
                "id": "FRAME-1",
                "document": "C:\\station\\frame.sldprt",
                "parent": None,
                "transform_world": {
                    "xyz_m": [0.0, 0.0, 0.0],
                    "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "scale": 1.0,
                },
            }
        ]
        if two_nodes:
            instances.append(
                {
                    "id": "CHILD-1",
                    "document": "C:\\station\\child.sldprt",
                    "parent": "FRAME-1",
                    "transform_world": {
                        "xyz_m": [1.0, 0.0, 0.0],
                        "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "scale": 1.0,
                    },
                }
            )
        snapshot = {
            "schema": "lab.assembly_snapshot/v0",
            "source_document": "C:\\station\\station.sldasm",
            "capture_adapter": "SwPackAndGoAdapter/trial-v0",
            "units": {
                "length": "m",
                "angle": "rad",
                "orientation": "quaternion_xyzw",
            },
            "instances": instances,
            "root_occurrences": ["FRAME-1"],
            "mates_candidate": [],
        }
        snapshot_path = capture / "assembly.snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        glb = minimal_glb()
        (geometry / "station.glb").write_bytes(glb)
        report = capture_report(len(instances), glb)
        (capture / "capture-report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        source = {
            "schema": "lab.source/v0",
            "read_policy": "read-only",
            "manifest_algorithm": "sha256(utf8(files.sha256))",
            "source_files_digest": sha256(hashes_path),
        }
        (capture / "source.json").write_text(json.dumps(source), encoding="utf-8")
        reproducibility = write_reproducibility(root, snapshot, report, glb)
        handoff = {
            "schema": "lab.station_source_handoff/v0",
            "station": "eit.station-a",
            "solidworks_capture": {
                "assembly_snapshot": "capture/assembly.snapshot.json",
                "capture_report": "capture/capture-report.json",
                "source": "capture/source.json",
                "files_sha256": "capture/files.sha256",
                "source_release_root": "source-release",
                "render_glb": "geometry/station.glb",
            },
            "reproducibility": reproducibility,
            "robot_release": {
                "authority": "manufacturer",
                "vendor": "Dobot",
                "model": "CR5",
                "provider": "unilab_arm_cr5:build_moveit_model",
                "source_digest": "8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2",
            },
            "reproducibility": {
                "report": "audit/reproducibility-report.json",
                "repeat_snapshot": "audit/repeat/assembly.snapshot.json",
                "repeat_capture_report": "audit/repeat/capture-report.json",
                "repeat_glb": "audit/repeat/station.glb",
                "glb_semantic_diagnosis": None,
            },
        }
        manifest = root / "station-handoff.json"
        manifest.write_text(json.dumps(handoff), encoding="utf-8")
        return manifest


if __name__ == "__main__":
    unittest.main()
