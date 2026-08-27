"""P0 输入冻结与 P1 handoff 封装工具测试。"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY = load_script("inventory_station_source")
FINALIZE = load_script("finalize_station_handoff")


class StationP0P1ToolsTest(unittest.TestCase):
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
            report.write_text(
                json.dumps(
                    {
                        "schema": "lab.solidworks_capture_report/v0",
                        "status": "passed",
                        "source_read_only": True,
                        "component_count": 1,
                        "glb_export": {
                            "save_result": True,
                            "exists": True,
                            "magic": "glTF",
                        },
                    }
                ),
                encoding="utf-8",
            )
            glb = root / "temporary.glb"
            glb.write_bytes(b"glTF" + b"\x02\x00\x00\x00" + b"\x20\x00\x00\x00" + b"0" * 20)
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
