"""工站 occurrence 精确子树分解与 layout 候选门禁。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from station_fixture_support import (  # noqa: E402
    capture_report,
    minimal_glb,
    sha256,
    write_reproducibility,
)

SPEC = importlib.util.spec_from_file_location(
    "compile_station_decomposition",
    ROOT / "scripts" / "compile_station_decomposition.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StationDecompositionTest(unittest.TestCase):
    def test_compiles_exact_subtrees_multi_instance_and_robot_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = self._write_decomposition(root, manifest)

            result = MODULE.compile_station(manifest, decomposition)
            self.assertTrue(result["human_reviewed"])
            self.assertTrue(result["publication_eligible"])
            self.assertEqual(len(result["placements"]), 5)
            racks = [
                item
                for item in result["placements"]
                if item["family"] == "environment.station-rack"
            ]
            self.assertEqual([item["subtree_root"] for item in racks], ["RACK-1", "RACK-2"])
            self.assertEqual([item["source_occurrence_count"] for item in racks], [2, 2])
            robots = [
                item
                for item in result["placements"]
                if item["kind"] == "robot_replacement"
            ]
            self.assertEqual(len(robots), 2)
            self.assertTrue(
                all(item["kinematics_source"] == "robot-family:dobot.cr5" for item in robots)
            )
            self.assertTrue(
                all(item["solidworks_geometry_role"] == "comparison_only" for item in robots)
            )
            self.assertEqual(len(result["occurrence_coverage"]), 9)
            self.assertNotIn("device_id", json.dumps(result))

    def test_nested_subtrees_and_invalid_root_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = self._write_decomposition(root, manifest)
            value = yaml.safe_load(decomposition.read_text(encoding="utf-8"))
            value["devices"].append(
                {
                    "family": "instrument.rack-part",
                    "kind": "device",
                    "subtree_root": "RACK-PART-1",
                }
            )
            decomposition.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DecompositionError, "同时属于"):
                MODULE.compile_station(manifest, decomposition)

            value["devices"][-1]["subtree_root"] = "NOT-AN-OCCURRENCE"
            decomposition.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DecompositionError, "subtree_root 不存在"):
                MODULE.compile_station(manifest, decomposition)

    def test_unassigned_and_prefix_v0_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = self._write_decomposition(root, manifest)
            value = yaml.safe_load(decomposition.read_text(encoding="utf-8"))
            value["devices"] = value["devices"][:1]
            value["robot_subtrees"] = []
            decomposition.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DecompositionError, "未分配 occurrence"):
                MODULE.compile_station(manifest, decomposition)

            value = self._decomposition_value(manifest)
            value["devices"][0].pop("subtree_root")
            value["devices"][0]["match"] = {"occurrence_prefix": "FRAME-"}
            decomposition.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DecompositionError, "不支持字段"):
                MODULE.compile_station(manifest, decomposition)

    def test_draft_requires_flag_and_generates_non_publishable_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = self._write_decomposition(root, manifest, approved=False)
            with self.assertRaisesRegex(MODULE.DecompositionError, "尚未 approved"):
                MODULE.compile_station(manifest, decomposition)

            layout = MODULE.compile_station(manifest, decomposition, allow_draft=True)
            coverage = MODULE.build_coverage_report(layout)
            review = MODULE.render_review_markdown(layout, coverage)
            self.assertFalse(layout["publication_eligible"])
            self.assertEqual(layout["qualification"], "decomposition-draft-preview")
            self.assertEqual(coverage["status"], "draft-preview")
            self.assertTrue(coverage["exact_coverage"])
            self.assertIn("可进入发布候选：`false`", review)
            self.assertIn("不授予部署、碰撞、空间互锁或执行资格", review)

    def test_cli_writes_layout_coverage_and_review_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._handoff(root)
            decomposition = self._write_decomposition(root, manifest)
            output = root / "station-layout.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "compile_station_decomposition.py"),
                    str(manifest),
                    str(decomposition),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            coverage_path = root / "coverage-report.json"
            review_path = root / "DECOMPOSITION-REVIEW.md"
            self.assertTrue(output.is_file())
            self.assertTrue(coverage_path.is_file())
            self.assertTrue(review_path.is_file())
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            self.assertEqual(coverage["schema"], "lab.station_decomposition_coverage/v1")
            self.assertEqual(coverage["assigned_occurrence_count"], 9)
            self.assertIn("精确 subtree root", review_path.read_text(encoding="utf-8"))

    @classmethod
    def _write_decomposition(
        cls,
        root: Path,
        manifest: Path,
        *,
        approved: bool = True,
    ) -> Path:
        value = cls._decomposition_value(manifest)
        if not approved:
            value["approval"] = {
                "status": "draft",
                "reviewed_by": "",
                "reviewed_at": "",
                "notes": "fixture draft",
            }
        path = root / "station-decomposition.yaml"
        path.write_text(
            yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _decomposition_value(manifest: Path) -> dict[str, object]:
        return {
            "schema": "lab.station_decomposition/v1",
            "station": "eit.station-a",
            "source_handoff_digest": sha256(manifest),
            "devices": [
                {
                    "family": "environment.station-frame",
                    "kind": "static_environment",
                    "subtree_root": "FRAME-1",
                },
                {
                    "family": "environment.station-rack",
                    "kind": "static_environment",
                    "subtree_root": "RACK-1",
                },
                {
                    "family": "environment.station-rack",
                    "kind": "static_environment",
                    "subtree_root": "RACK-2",
                },
            ],
            "robot_subtrees": [
                {
                    "subtree_root": "CR5_BASE-1",
                    "replaced_by": "robot-family:dobot.cr5",
                },
                {
                    "subtree_root": "CR5_BASE-2",
                    "replaced_by": "robot-family:dobot.cr5",
                },
            ],
            "unassigned_policy": "fail",
            "approval": {
                "status": "approved",
                "reviewed_by": "fixture-reviewer",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "notes": "fixture only",
            },
        }

    @staticmethod
    def _handoff(root: Path) -> Path:
        capture = root / "capture"
        release = root / "source-release"
        geometry = root / "geometry"
        repeat = root / "audit" / "repeat"
        capture.mkdir()
        release.mkdir()
        geometry.mkdir()
        repeat.mkdir(parents=True)
        source_file = release / "station.sldasm"
        source_file.write_bytes(b"solidworks-source")
        source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        hashes_path = capture / "files.sha256"
        hashes_path.write_text(f"{source_hash}  station.sldasm\n", encoding="utf-8")
        identity = {
            "xyz_m": [0.0, 0.0, 0.0],
            "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": 1.0,
        }

        def instance(name: str, parent: str | None, x: float) -> dict[str, object]:
            transform = dict(identity)
            transform["xyz_m"] = [x, 0.0, 0.0]
            return {
                "id": name,
                "document": f"C:\\station\\{name}.sldprt",
                "parent": parent,
                "transform_world": transform,
            }

        instances = [
            instance("FRAME-1", None, 0.0),
            instance("RACK-1", None, 1.0),
            instance("RACK-PART-1", "RACK-1", 1.1),
            instance("RACK-2", None, 2.0),
            instance("RACK-PART-2", "RACK-2", 2.1),
            instance("CR5_BASE-1", None, 3.0),
            instance("CR5_LINK-1", "CR5_BASE-1", 3.1),
            instance("CR5_BASE-2", None, 4.0),
            instance("CR5_LINK-2", "CR5_BASE-2", 4.1),
        ]
        snapshot = {
            "schema": "lab.assembly_snapshot/v0",
            "source_document": "C:\\station\\station.sldasm",
            "units": {
                "length": "m",
                "angle": "rad",
                "orientation": "quaternion_xyzw",
            },
            "instances": instances,
            "root_occurrences": [
                "FRAME-1",
                "RACK-1",
                "RACK-2",
                "CR5_BASE-1",
                "CR5_BASE-2",
            ],
            "mates_candidate": [],
        }
        (capture / "assembly.snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        glb = minimal_glb()
        (geometry / "station.glb").write_bytes(glb)
        report = capture_report(len(instances), glb)
        (capture / "capture-report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        (capture / "source.json").write_text(
            json.dumps(
                {
                    "schema": "lab.source/v0",
                    "read_policy": "read-only",
                    "manifest_algorithm": "sha256(utf8(files.sha256))",
                    "source_files_digest": sha256(hashes_path),
                }
            ),
            encoding="utf-8",
        )
        reproducibility = write_reproducibility(root, snapshot, report, glb)
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
                    "reproducibility": reproducibility,
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


if __name__ == "__main__":
    unittest.main()
