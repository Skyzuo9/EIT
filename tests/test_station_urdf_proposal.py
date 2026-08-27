"""URDF companion CSV to exact occurrence proposal tests."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "propose_station_decomposition_from_urdf",
    ROOT / "scripts" / "propose_station_decomposition_from_urdf.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StationUrdfProposalTest(unittest.TestCase):
    def test_generates_exact_robot_replacement_and_parent_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            handoff_dir = root / "handoff"
            capture = handoff_dir / "capture"
            legacy = handoff_dir / "source-release" / "投料站-urdf" / "rack.urdf" / "urdf"
            capture.mkdir(parents=True)
            legacy.mkdir(parents=True)
            robot_root = handoff_dir / "ROBOT"
            robot_root.mkdir()

            robot_parent = "station-1/GCR5-assembly-1"
            instances = [self._instance("station-1", None, "station.SLDASM")]
            instances.append(self._instance("station-1/rack-shell-1", "station-1", "rack.SLDASM"))
            instances.append(self._instance("station-1/rack-shell-1/rack-part-1", "station-1/rack-shell-1", "rack-part.SLDPRT"))
            instances.append(self._instance(robot_parent, "station-1", "GCR5.SLDASM"))
            for index in range(7):
                instances.append(
                    self._instance(
                        f"{robot_parent}/GCR5-J{index}_1.STEP-1",
                        robot_parent,
                        f"GCR5-J{index}_1.STEP.SLDPRT",
                    )
                )
            bottle = "station-1/4ml玻璃瓶(Default_按加工_)-1"
            instances.append(
                self._instance(
                    bottle,
                    "station-1",
                    "4ml玻璃瓶(Default_按加工_).SLDPRT",
                )
            )
            (capture / "assembly.snapshot.json").write_text(
                json.dumps({"instances": instances}, ensure_ascii=False),
                encoding="utf-8",
            )
            handoff = handoff_dir / "station-handoff.json"
            handoff.write_text(
                json.dumps(
                    {
                        "station": "eit.fixture",
                        "solidworks_capture": {"assembly_snapshot": "capture/assembly.snapshot.json"},
                    }
                ),
                encoding="utf-8",
            )
            self._csv(legacy / "rack.csv", ["rack-part-1"])

            archive = robot_root / "robot.zip"
            robot_csv = root / "robot.csv"
            self._csv(robot_csv, [f"GCR5-J{index}_1-1" for index in range(7)])
            with ZipFile(archive, "w") as output:
                output.write(robot_csv, "pkg/robot.csv")
            digest = MODULE._sha256(archive)
            manifest = root / "robot-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "lab.robot_source_releases/v0",
                        "source_root": {
                            "environment": "FIXTURE_UNUSED_SOURCE_ROOT",
                            "default_home_relative": "unused",
                        },
                        "releases": {
                            "duco_gcr5_910": {
                                "display_name": "DUCO GCR5-910",
                                "authority": "project-cad-export",
                                "archive": "robot.zip",
                                "archive_sha256": digest,
                                "csv_member": "pkg/robot.csv",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            proposal, evidence, review = MODULE.generate_proposal(
                handoff,
                legacy.parents[1],
                robot_manifest_path=manifest,
                robot_model_id="duco_gcr5_910",
                source_root=robot_root,
            )
            self.assertEqual(proposal["schema"], "lab.station_decomposition/v1.1")
            self.assertEqual(proposal["approval"]["status"], "draft")
            self.assertFalse(evidence["publication_eligible"])
            self.assertEqual(evidence["robot_occurrence_roots"], [robot_parent])
            self.assertEqual(evidence["bottle_4ml_representative"], bottle)
            robot = proposal["robot_subtrees"][0]
            self.assertEqual(robot["subtree_root"], robot_parent)
            self.assertEqual(robot["replaced_by"], "robot-family:duco.gcr5_910")
            station = next(item for item in proposal["devices"] if item["subtree_root"] == "station-1")
            self.assertIn(robot_parent, station["exclude_subtree_roots"])
            self.assertIn("不得进入真实 W2", review)

    @staticmethod
    def _instance(occurrence: str, parent: str | None, document: str) -> dict[str, object]:
        return {
            "id": occurrence,
            "parent": parent,
            "document": f"C:\\fixture\\{document}",
            "transform_world": {
                "xyz_m": [0.0, 0.0, 0.0],
                "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
            },
        }

    @staticmethod
    def _csv(path: Path, components: list[str]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["Link Name", "SW Components"])
            writer.writeheader()
            for index, component in enumerate(components):
                writer.writerow({"Link Name": f"link{index}", "SW Components": component})


if __name__ == "__main__":
    unittest.main()
