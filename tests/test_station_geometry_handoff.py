"""Windows W2 device-geometry contract and fail-closed packaging tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from station_fixture_support import (  # noqa: E402
    capture_report,
    minimal_glb,
    write_reproducibility,
)


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DECOMPOSITION = load_script("compile_station_decomposition")
W2 = load_script("finalize_station_geometry_handoff")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def named_box_glb(name: str, size: tuple[float, float, float]) -> bytes:
    sx, sy, sz = size
    document = {
        "asset": {"version": "2.0", "generator": "w2-station-fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [sx, sy, sz],
            }
        ],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
        "buffers": [{"byteLength": 36}],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary = struct.pack("<9f", 0.0, 0.0, 0.0, sx, 0.0, 0.0, 0.0, sy, sz)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


class StationGeometryHandoffTest(unittest.TestCase):
    def test_packages_four_slice_w2_with_bound_stats_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            result = self._finalize(fixture)
            self.assertTrue(result["passed"])
            output = fixture["output"]
            handoff = json.loads((output / "geometry-handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["schema"], "lab.station_geometry_handoff/v1")
            self.assertEqual(handoff["status"], "ready-for-mac-w2-validation")
            self.assertEqual(len(handoff["devices"]), 4)
            self.assertEqual(
                {item["slice_role"] for item in handoff["devices"]},
                W2.REQUIRED_SLICE_ROLES,
            )
            robot = next(item for item in handoff["devices"] if item["slice_role"] == "robot-cad-comparison")
            bottle = next(item for item in handoff["devices"] if item["slice_role"] == "bottle-4ml")
            self.assertTrue(robot["comparison_only"])
            self.assertEqual(bottle["source_unit"], "mm")
            report = json.loads(
                (output / "devices" / bottle["asset_instance"] / "export-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["geometry"]["bounding_box_m"]["size"], [0.015, 0.046, 0.015])
            self.assertTrue(report["reproducibility"]["semantic_match"])
            manifest_lines = (
                output / "devices" / bottle["asset_instance"] / "files.sha256"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 3)
            self.assertFalse(any("\\" in line for line in manifest_lines))

    def test_rejects_draft_or_mutated_p2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            decomposition = yaml.safe_load(fixture["decomposition"].read_text(encoding="utf-8"))
            decomposition["approval"]["status"] = "draft"
            decomposition["approval"]["reviewed_by"] = ""
            decomposition["approval"]["reviewed_at"] = ""
            fixture["decomposition"].write_text(
                yaml.safe_dump(decomposition, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(W2.GeometryHandoffError, "P2 批准产物"):
                self._finalize(fixture)

    def test_rejects_inexact_root_and_foreign_occurrence_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            plan = json.loads(fixture["plan"].read_text(encoding="utf-8"))
            plan["devices"][0]["subtree_root"] = "RACK"
            fixture["plan"].write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(W2.GeometryHandoffError, "不是批准 layout 的精确根"):
                self._finalize(fixture)

        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            plan = json.loads(fixture["plan"].read_text(encoding="utf-8"))
            entity_path = fixture["plan"].parent / plan["devices"][0]["primary"]["entity_map"]
            entity_map = json.loads(entity_path.read_text(encoding="utf-8"))
            entity_map["nodes"][0]["occurrence_id"] = "RAIL-1"
            entity_path.write_text(json.dumps(entity_map), encoding="utf-8")
            with self.assertRaisesRegex(W2.GeometryHandoffError, "批准子树之外"):
                self._finalize(fixture)

    def test_rejects_repeat_semantic_drift_unit_boundary_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            plan = json.loads(fixture["plan"].read_text(encoding="utf-8"))
            repeat_path = fixture["plan"].parent / plan["devices"][1]["repeat"]["render_glb"]
            repeat_path.write_bytes(named_box_glb("rail-node", (2.0, 0.2, 0.1)))
            with self.assertRaisesRegex(W2.GeometryHandoffError, "语义几何签名不一致"):
                self._finalize(fixture)

        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            plan = json.loads(fixture["plan"].read_text(encoding="utf-8"))
            plan["devices"][3]["source_unit"] = "m"
            fixture["plan"].write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(W2.GeometryHandoffError, "source_unit=mm"):
                self._finalize(fixture)

        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            with mock.patch.object(W2, "MAX_RENDER_GLB_BYTES", 1):
                with self.assertRaisesRegex(W2.GeometryHandoffError, "25 MB"):
                    self._finalize(fixture)

    @staticmethod
    def _finalize(fixture: dict[str, Path]):
        return W2.finalize_geometry_handoff(
            plan_path=fixture["plan"],
            output_root=fixture["output"],
            station_handoff=fixture["handoff"],
            decomposition=fixture["decomposition"],
            station_layout=fixture["layout"],
            coverage_report=fixture["coverage"],
            review=fixture["review"],
        )

    @staticmethod
    def _fixture(root: Path) -> dict[str, Path]:
        handoff_root = root / "w1"
        capture = handoff_root / "capture"
        release = handoff_root / "source-release"
        geometry = handoff_root / "geometry"
        repeat = handoff_root / "audit" / "repeat"
        capture.mkdir(parents=True)
        release.mkdir()
        geometry.mkdir()
        repeat.mkdir(parents=True)
        source_file = release / "station.sldasm"
        source_file.write_bytes(b"solidworks-source")
        source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        hashes_path = capture / "files.sha256"
        hashes_path.write_bytes(f"{source_hash}  station.sldasm\n".encode("utf-8"))
        identity = {
            "xyz_m": [0.0, 0.0, 0.0],
            "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": 1.0,
        }
        instances = [
            {"id": "RACK-1", "parent": None, "transform_world": identity},
            {"id": "RAIL-1", "parent": None, "transform_world": identity},
            {"id": "CR5-1", "parent": None, "transform_world": identity},
            {"id": "BOTTLE-4ML-1", "parent": None, "transform_world": identity},
        ]
        snapshot = {
            "schema": "lab.assembly_snapshot/v0",
            "source_document": "C:\\station\\station.sldasm",
            "units": {"length": "m", "angle": "rad", "orientation": "quaternion_xyzw"},
            "instances": instances,
            "root_occurrences": [item["id"] for item in instances],
            "mates_candidate": [],
        }
        snapshot_path = capture / "assembly.snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        glb = minimal_glb()
        (geometry / "station.glb").write_bytes(glb)
        report = capture_report(len(instances), glb)
        (capture / "capture-report.json").write_text(json.dumps(report), encoding="utf-8")
        source_digest = sha256(hashes_path)
        (capture / "source.json").write_text(
            json.dumps(
                {
                    "schema": "lab.source/v0",
                    "read_policy": "read-only",
                    "manifest_algorithm": "sha256(utf8(files.sha256))",
                    "source_files_digest": source_digest,
                }
            ),
            encoding="utf-8",
        )
        reproducibility = write_reproducibility(handoff_root, snapshot, report, glb)
        handoff = handoff_root / "station-handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema": "lab.station_source_handoff/v0",
                    "station": "eit.feeding-station",
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
        decomposition = root / "station-decomposition.yaml"
        decomposition.write_text(
            yaml.safe_dump(
                {
                    "schema": "lab.station_decomposition/v1",
                    "station": "eit.feeding-station",
                    "source_handoff_digest": sha256(handoff),
                    "devices": [
                        {"family": "environment.rack", "kind": "static_environment", "subtree_root": "RACK-1"},
                        {"family": "mechanism.rail-shell", "kind": "device", "subtree_root": "RAIL-1"},
                        {"family": "consumable.bottle-4ml", "kind": "device", "subtree_root": "BOTTLE-4ML-1"},
                    ],
                    "robot_subtrees": [
                        {"subtree_root": "CR5-1", "replaced_by": "robot-family:dobot.cr5"}
                    ],
                    "unassigned_policy": "fail",
                    "approval": {
                        "status": "approved",
                        "reviewed_by": "fixture-reviewer",
                        "reviewed_at": "2026-08-27T18:00:00+08:00",
                        "notes": "fixture only",
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        layout_value = DECOMPOSITION.compile_station(handoff, decomposition)
        coverage_value = DECOMPOSITION.build_coverage_report(layout_value)
        review_value = DECOMPOSITION.render_review_markdown(layout_value, coverage_value)
        layout = root / "station-layout.json"
        coverage = root / "coverage-report.json"
        review = root / "DECOMPOSITION-REVIEW.md"
        layout.write_text(json.dumps(layout_value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        coverage.write_text(json.dumps(coverage_value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        review.write_text(review_value, encoding="utf-8")

        exports = root / "exports"
        exports.mkdir()
        device_data = [
            ("rack-left-01", "rack", "environment.rack", "RACK-1", "semantic-scene", "m", False, "rack-node", (1.0, 0.5, 2.0)),
            ("rail-front-01", "rail-shell", "mechanism.rail-shell", "RAIL-1", "semantic-scene", "m", False, "rail-node", (1.0, 0.2, 0.1)),
            ("cr5-cad-01", "robot-cad-comparison", "robot-family:dobot.cr5", "CR5-1", "comparison-only", "m", True, "cr5-node", (0.7, 0.7, 1.5)),
            ("bottle-4ml-01", "bottle-4ml", "consumable.bottle-4ml", "BOTTLE-4ML-1", "semantic-scene", "mm", False, "bottle-node", (0.015, 0.046, 0.015)),
        ]
        plan_devices = []
        for asset, role, family, occurrence, qualification, unit, comparison, node_name, size in device_data:
            primary_glb = exports / f"{asset}-primary.glb"
            repeat_glb = exports / f"{asset}-repeat.glb"
            primary_map = exports / f"{asset}-primary.entity-map.json"
            repeat_map = exports / f"{asset}-repeat.entity-map.json"
            payload = named_box_glb(node_name, size)
            primary_glb.write_bytes(payload)
            repeat_glb.write_bytes(payload)
            geometry_role = "comparison" if comparison else "semantic"
            entity_map = {
                "schema": "lab.station_geometry_entity_map/v1",
                "subtree_root": occurrence,
                "qualification": qualification,
                "nodes": [
                    {
                        "node_index": 0,
                        "node_name": node_name,
                        "occurrence_id": occurrence,
                        "mapping": "exact-occurrence",
                        "geometry_role": geometry_role,
                    }
                ],
            }
            primary_map.write_text(json.dumps(entity_map), encoding="utf-8")
            repeat_map.write_text(json.dumps(entity_map), encoding="utf-8")
            item = {
                "asset_instance": asset,
                "slice_role": role,
                "family": family,
                "subtree_root": occurrence,
                "qualification": qualification,
                "source_unit": unit,
                "comparison_only": comparison,
                "primary": {
                    "render_glb": primary_glb.relative_to(root).as_posix(),
                    "entity_map": primary_map.relative_to(root).as_posix(),
                    "source_digest_before": source_digest,
                    "source_digest_after": source_digest,
                },
                "repeat": {
                    "render_glb": repeat_glb.relative_to(root).as_posix(),
                    "entity_map": repeat_map.relative_to(root).as_posix(),
                    "source_digest_before": source_digest,
                    "source_digest_after": source_digest,
                },
            }
            if role in {"rail-shell", "bottle-4ml"}:
                item["expected_size_m"] = list(size)
                item["size_tolerance_m"] = [0.000001, 0.000001, 0.000001]
            plan_devices.append(item)
        plan = root / "geometry-export-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema": "lab.station_geometry_export_plan/v1",
                    "run_id": "feeding-station-20260828-win03-w2",
                    "station": "eit.feeding-station",
                    "solidworks": {
                        "revision": "33.5.0",
                        "configuration": "默认",
                        "source_read_only": True,
                    },
                    "exporter": {
                        "name": "SwExactSubtreeExporter",
                        "version": "w2-contract-v1",
                        "selection_mode": "exact-subtree-root",
                    },
                    "devices": plan_devices,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "handoff": handoff,
            "decomposition": decomposition,
            "layout": layout,
            "coverage": coverage,
            "review": review,
            "plan": plan,
            "output": root / "feeding-station-20260828-win03-w2",
        }


if __name__ == "__main__":
    unittest.main()
