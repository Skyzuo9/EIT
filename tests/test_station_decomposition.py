"""工站 occurrence 分解与 layout 候选门禁。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "compile_station_decomposition",
    ROOT / "scripts" / "compile_station_decomposition.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StationDecompositionTest(unittest.TestCase):
    def test_compiles_exact_ownership_and_robot_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = root / "station-decomposition.yaml"
            decomposition.write_text(
                yaml.safe_dump(
                    {
                        "schema": "lab.station_decomposition/v0",
                        "station": "eit.station-a",
                        "source_handoff_digest": self._sha256(manifest),
                        "devices": [
                            {
                                "family": "environment.station-frame",
                                "match": {"occurrence_prefix": "FRAME-"},
                                "kind": "static_environment",
                            }
                        ],
                        "robot_subtrees": [
                            {
                                "match": {"occurrence_prefix": "CR5_"},
                                "replaced_by": "robot-family:dobot.cr5",
                            }
                        ],
                        "unassigned_policy": "fail",
                        "approval": {
                            "status": "approved",
                            "reviewed_by": "fixture-reviewer",
                            "reviewed_at": "2026-08-26T00:00:00+08:00",
                        },
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            result = MODULE.compile_station(manifest, decomposition)
            self.assertTrue(result["human_reviewed"])
            self.assertEqual(len(result["placements"]), 2)
            robot = next(
                item for item in result["placements"]
                if item["kind"] == "robot_replacement"
            )
            self.assertEqual(robot["kinematics_source"], "robot-family:dobot.cr5")
            self.assertEqual(robot["solidworks_geometry_role"], "comparison_only")
            self.assertNotIn("device_id", json.dumps(result))

    def test_unassigned_and_draft_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = root / "station-decomposition.yaml"
            base = {
                "schema": "lab.station_decomposition/v0",
                "station": "eit.station-a",
                "source_handoff_digest": self._sha256(manifest),
                "devices": [
                    {
                        "family": "environment.station-frame",
                        "match": {"occurrence_prefix": "FRAME-"},
                        "kind": "static_environment",
                    }
                ],
                "robot_subtrees": [],
                "unassigned_policy": "fail",
                "approval": {"status": "draft", "reviewed_by": "", "reviewed_at": ""},
            }
            decomposition.write_text(yaml.safe_dump(base), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DecompositionError, "尚未 approved"):
                MODULE.compile_station(manifest, decomposition)
            with self.assertRaisesRegex(MODULE.DecompositionError, "未分配 occurrence"):
                MODULE.compile_station(manifest, decomposition, allow_draft=True)

    @staticmethod
    def _handoff(root: Path) -> Path:
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
            f"{source_hash}  station.sldasm\n", encoding="utf-8"
        )
        identity = {
            "xyz_m": [0.0, 0.0, 0.0],
            "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": 1.0,
        }
        snapshot = {
            "schema": "lab.assembly_snapshot/v0",
            "units": {
                "length": "m",
                "angle": "rad",
                "orientation": "quaternion_xyzw",
            },
            "instances": [
                {"id": "FRAME-1", "parent": None, "transform_world": identity},
                {
                    "id": "CR5_BASE-1",
                    "parent": None,
                    "transform_world": {
                        "xyz_m": [1.0, 0.0, 0.0],
                        "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "scale": 1.0,
                    },
                },
                {
                    "id": "CR5_LINK-1",
                    "parent": "CR5_BASE-1",
                    "transform_world": {
                        "xyz_m": [1.0, 0.0, 0.5],
                        "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "scale": 1.0,
                    },
                },
            ],
            "root_occurrences": ["FRAME-1", "CR5_BASE-1"],
            "mates_candidate": [],
        }
        (capture / "assembly.snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        (capture / "capture-report.json").write_text(
            json.dumps(
                {
                    "schema": "lab.solidworks_capture_report/v0",
                    "source_read_only": True,
                    "status": "passed",
                    "com_revision": "33.5.0",
                    "component_count": 3,
                    "glb_export": {
                        "save_result": True,
                        "exists": True,
                        "magic": "glTF",
                    },
                }
            ),
            encoding="utf-8",
        )
        (capture / "source.json").write_text(
            json.dumps(
                {
                    "schema": "lab.source/v0",
                    "read_policy": "read-only",
                    "source_files_digest": source_hash,
                }
            ),
            encoding="utf-8",
        )
        (geometry / "station.glb").write_bytes(
            b"glTF" + b"\x02\x00\x00\x00" + b"\x20\x00\x00\x00" + b"0" * 20
        )
        manifest = root / "station-handoff.json"
        manifest.write_text(
            json.dumps(
                {
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
            ),
            encoding="utf-8",
        )
        return manifest

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
