"""Feeding-station Workbench preview receipt and fail-closed API tests."""

from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cr5_telemetry_lab.preview_app import create_station_preview_router
from cr5_telemetry_lab.station_preview import load_station_preview


class StationPreviewTest(unittest.TestCase):
    def test_receipt_projects_static_station_and_read_only_model(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root, receipt_path = _write_fixture(Path(value))
            preview = load_station_preview(root, receipt_path)
            descriptor = preview.descriptor()
            self.assertEqual(
                descriptor["schema"],
                "lab.station_workbench_preview/v0",
            )
            self.assertEqual(descriptor["model"]["format"], "gltf")
            self.assertEqual(
                descriptor["rendering"]["dimensionsMm"],
                [2000.0, 800.0, 1000.0],
            )
            self.assertEqual(descriptor["model"]["rotation"], [0.0, 0.0, 0.0])
            self.assertEqual(
                descriptor["rendering"]["source_coordinate_frame"],
                "solidworks-gltf-y-up",
            )
            self.assertEqual(
                descriptor["rendering"]["material_graph_coordinate_frame"],
                "unilab-z-up",
            )
            projected = preview.gltf_world_to_lab_mm([0.5, 0.2, 0.75])
            for actual, expected in zip(
                projected,
                [500.0, -250.0, 600.0],
                strict=True,
            ):
                self.assertAlmostEqual(actual, expected)
            self.assertTrue(descriptor["p2_draft"]["exact_coverage"])
            self.assertFalse(descriptor["p2_draft"]["human_reviewed"])
            self.assertFalse(descriptor["capability"]["hardware_execution"])
            registration = descriptor["cad_urdf_visual_registration"]
            self.assertEqual(registration["qualification"], "cad-comparison-only")
            self.assertEqual(len(registration["joint_positions"]), 6)
            self.assertTrue(registration["not_a_deploy_base_pose"])
            self.assertRegex(registration["sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(descriptor["capability"]["collision_qualified"])
            self.assertFalse(descriptor["capability"]["w2_eligible"])

            graph_node = preview.material_graph_node()
            rendering = graph_node["material"]["config"]["rendering"]
            self.assertEqual(
                rendering["model"]["path"],
                "/api/v1/station-preview/model.glb",
            )
            self.assertTrue(graph_node["material"]["meta_data"]["preview_only"])
            self.assertEqual(graph_node["relative_position"]["width"], 2000.0)

            app = FastAPI()
            app.include_router(create_station_preview_router(preview))
            with TestClient(app) as client:
                response = client.get("/api/v1/station-preview/descriptor")
                self.assertEqual(response.status_code, 200)
                model = client.get("/api/v1/station-preview/model.glb")
                self.assertEqual(model.status_code, 200)
                self.assertEqual(model.headers["content-type"], "model/gltf-binary")
                self.assertEqual(
                    model.headers["x-unilab-geometry-sha256"],
                    preview.geometry_sha256,
                )
                self.assertEqual(model.content[:4], b"glTF")

    def test_digest_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root, receipt_path = _write_fixture(Path(value))
            (root / "p2-auto" / "station-decomposition.proposal.yaml").write_text(
                "tampered: true\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "bytes 不匹配|SHA-256 不匹配"):
                load_station_preview(root, receipt_path)


def _write_fixture(base: Path) -> tuple[Path, Path]:
    root = base / "handoff"
    p2 = root / "p2-auto"
    geometry_dir = root / "geometry"
    p2.mkdir(parents=True)
    geometry_dir.mkdir()

    model_path = geometry_dir / "station.glb"
    model_path.write_bytes(_minimal_glb())
    handoff_path = root / "station-handoff.json"
    handoff_path.write_text(
        json.dumps(
            {
                "schema": "lab.station_source_handoff/v0",
                "station": "eit.feeding-station",
                "solidworks_capture": {"render_glb": "geometry/station.glb"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    decomposition_path = p2 / "station-decomposition.proposal.yaml"
    decomposition_path.write_text("schema: test\n", encoding="utf-8")
    handoff_sha = _sha256(handoff_path)
    decomposition_sha = _sha256(decomposition_path)
    placements = [
        {
            "family": "robot-family:duco.gcr5_910",
            "subtree_root": "station/robot",
            "anchor_occurrence": "station/robot",
            "solidworks_geometry_role": "comparison_only",
            "kinematics_source": "robot-family:duco.gcr5_910",
            "transform_world": {
                "xyz_m": [0.5, 0.1, 0.75],
                "quat_xyzw": [0.0, -0.7071067811865475, 0.0, 0.7071067811865476],
            },
        },
        {
            "family": "material-family:glass-bottle-4ml",
            "subtree_root": "station/bottle-1",
            "anchor_occurrence": "station/bottle-1",
            "transform_world": {
                "xyz_m": [-0.5, -0.1, 0.5],
                "quat_xyzw": [0.0, 0.0, 0.0, 1.0],
            },
        },
    ]
    layout_path = p2 / "station-layout.draft.json"
    layout_path.write_text(
        json.dumps(
            {
                "schema": "lab.station_layout_candidate/v1",
                "station": "eit.feeding-station",
                "qualification": "decomposition-draft-preview",
                "human_reviewed": False,
                "publication_eligible": False,
                "not_a_deploy_manifest": True,
                "not_a_workcell_activation": True,
                "source_handoff_digest": handoff_sha,
                "source_decomposition_digest": decomposition_sha,
                "placements": placements,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    coverage_path = p2 / "coverage-report.json"
    coverage_path.write_text(
        json.dumps(
            {
                "schema": "lab.station_decomposition_coverage/v1",
                "station": "eit.feeding-station",
                "status": "draft-preview",
                "publication_eligible": False,
                "exact_coverage": True,
                "source_handoff_digest": handoff_sha,
                "source_decomposition_digest": decomposition_sha,
                "occurrence_count": 2,
                "assigned_occurrence_count": 2,
                "placement_count": 2,
                "unassigned_occurrences": [],
                "overlapping_occurrences": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    files = {
        "station_handoff": _file_spec(root, handoff_path),
        "decomposition": _file_spec(root, decomposition_path),
        "layout": _file_spec(root, layout_path),
        "coverage": _file_spec(root, coverage_path),
        "geometry": _file_spec(root, model_path),
    }
    receipt_path = base / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schema": "lab.station_workbench_preview_receipt/v0",
                "station": "eit.feeding-station",
                "run_id": "fixture-run",
                "files": files,
                "geometry": {
                    "counts": {
                        "nodes": 1,
                        "meshes": 1,
                        "primitives": 1,
                        "accessors": 1,
                        "materials": 1,
                    },
                    "bounding_box_m": {
                        "min": [-1.0, -0.4, 0.0],
                        "max": [1.0, 0.4, 1.0],
                        "size": [2.0, 0.8, 1.0],
                    },
                    "cad_source_coordinate_frame": "solidworks-z-up",
                    "source_coordinate_frame": "solidworks-gltf-y-up",
                },
                "cad_urdf_visual_registration": {
                    "schema": "lab.cad_urdf_visual_registration/v0",
                    "qualification": "cad-comparison-only",
                    "comparison_only": True,
                    "not_a_deploy_base_pose": True,
                    "not_calibrated": True,
                    "hardware_execution": False,
                    "publication_eligible": False,
                    "collision_qualified": False,
                    "station_geometry_sha256": files["geometry"]["sha256"],
                    "station_layout_sha256": files["layout"]["sha256"],
                    "robot_subtree_root": "station/robot",
                    "cad_source_coordinate_frame": "solidworks-z-up",
                    "source_coordinate_frame": "solidworks-gltf-y-up",
                    "material_graph_coordinate_frame": "unilab-z-up",
                    "renderer_coordinate_frame": "pascal-y-up-internal",
                    "joint_position_unit": "rad",
                    "robot_topology_digest": (
                        "583e2b65e6422a7fe0c9332f8172bd03"
                        "c3da267ba66da853cb854650eb08ac48"
                    ),
                    "root_pose_gltf_world": {
                        "coordinate_frame": "solidworks-gltf-y-up",
                        "xyz_m": [0.5, 0.1, 0.75],
                        "quat_xyzw": [
                            0.0,
                            0.7071067811865475,
                            0.7071067811865475,
                            0.0,
                        ],
                        "rotation_convention": (
                            "three-euler-intrinsic-XYZ-deg"
                        ),
                        "rotation_xyz_deg": [-90.0, 0.0, -180.0],
                    },
                    "joint_positions": {
                        f"duco_gcr5_910_gcr5_joint_{index}": position
                        for index, position in enumerate(
                            [-0.01, 0.2, 1.6, -0.3, -1.5, -1.6],
                            start=1,
                        )
                    },
                    "residuals": {
                        "max_moving_joint_translation_mm": 0.01,
                        "max_moving_joint_rotation_deg": 0.0001,
                        "base_mesh_trimmed_rms_mm": 2.0,
                    },
                },
                "expected_p2": {
                    "occurrence_count": 2,
                    "assigned_occurrence_count": 2,
                    "placement_count": 2,
                    "robot_family": "robot-family:duco.gcr5_910",
                    "four_ml_family": "material-family:glass-bottle-4ml",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root, receipt_path


def _minimal_glb() -> bytes:
    document = {
        "asset": {"generator": "SOLIDWORKSGLTF", "version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0}, "material": 0}
                ]
            }
        ],
        "accessors": [
            {"componentType": 5126, "count": 3, "type": "VEC3"}
        ],
        "materials": [{}],
        "buffers": [{"byteLength": 4}],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    binary_chunk = b"\x00\x00\x00\x00"
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    return b"".join(
        [
            struct.pack("<4sII", b"glTF", 2, total),
            struct.pack("<II", len(json_chunk), 0x4E4F534A),
            json_chunk,
            struct.pack("<II", len(binary_chunk), 0x004E4942),
            binary_chunk,
        ]
    )


def _file_spec(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
