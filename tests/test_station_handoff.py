"""Windows 工站结果回传门禁测试。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_station_handoff.py"
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

    @staticmethod
    def _fixture(root: Path) -> Path:
        capture = root / "capture"
        release = root / "source-release"
        geometry = root / "geometry"
        capture.mkdir()
        release.mkdir()
        geometry.mkdir()
        source_file = release / "station.sldasm"
        source_file.write_bytes(b"solidworks-source")
        source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        (capture / "files.sha256").write_text(
            f"{source_hash}  station.sldasm\n",
            encoding="utf-8",
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
            "instances": [
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
            ],
            "root_occurrences": ["FRAME-1"],
            "mates_candidate": [],
        }
        (capture / "assembly.snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        report = {
            "schema": "lab.solidworks_capture_report/v0",
            "source_read_only": True,
            "status": "passed",
            "com_revision": "33.5.0",
            "component_count": 1,
            "glb_export": {
                "save_result": True,
                "exists": True,
                "magic": "glTF",
            },
        }
        (capture / "capture-report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        source = {
            "schema": "lab.source/v0",
            "read_policy": "read-only",
            "source_files_digest": source_hash,
        }
        (capture / "source.json").write_text(json.dumps(source), encoding="utf-8")
        (geometry / "station.glb").write_bytes(
            b"glTF" + b"\x02\x00\x00\x00" + b"\x20\x00\x00\x00" + b"0" * 20
        )
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
            "robot_release": {
                "authority": "manufacturer",
                "vendor": "Dobot",
                "model": "CR5",
                "provider": "unilab_arm_cr5:build_moveit_model",
                "source_digest": "8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2",
            },
        }
        manifest = root / "station-handoff.json"
        manifest.write_text(json.dumps(handoff), encoding="utf-8")
        return manifest


if __name__ == "__main__":
    unittest.main()
