"""Feeding-station demo WorkflowTask and Workbench projection contracts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from cr5_telemetry_lab.demo_workflow import (
    DEMO_RAIL_MATERIAL_UUID,
    DEMO_VIAL_MATERIAL_UUID,
    DUCO_MATERIAL_UUID,
)
from cr5_telemetry_lab.preview_app import create_app
from test_station_preview import _write_fixture


class FeedingStationDemoWorkflowTest(unittest.TestCase):
    def test_demo_run_uses_standard_workflow_task_jobs_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            base = Path(value)
            root, receipt = _write_fixture(base)
            app = create_app(
                time_scale=0.001,
                station_root=root,
                station_receipt=receipt,
                demo_workflow_db=base / "workflow.db",
            )
            with TestClient(app) as client:
                descriptor = client.get("/api/v1/demo-workflow/descriptor")
                self.assertEqual(descriptor.status_code, 200)
                activation = descriptor.json()["required_activation"]
                self.assertFalse(activation["hardware_execution"])
                self.assertFalse(activation["publication_eligible"])
                self.assertRegex(
                    activation["cad_comparison_pose_sha256"],
                    r"^[0-9a-f]{64}$",
                )

                response = client.post(
                    "/api/v1/demo-workflow/runs",
                    json=activation,
                )
                self.assertEqual(response.status_code, 201)
                data = response.json()["data"]
                self.assertEqual(
                    data["validation_status"],
                    "demo-workflow-validated",
                )
                self.assertEqual(data["task"]["status"], "succeeded")
                self.assertFalse(
                    data["task"]["meta_data"]["hardware_execution"]
                )
                self.assertFalse(
                    data["task"]["meta_data"]["publication_eligible"]
                )
                self.assertEqual(len(data["jobs"]), 6)
                self.assertTrue(
                    all(job["status"] == "succeeded" for job in data["jobs"])
                )

                task_uuid = data["task"]["uuid"]
                task = client.get(f"/api/v1/workflow-tasks/{task_uuid}")
                jobs = client.get(f"/api/v1/workflow-tasks/{task_uuid}/jobs")
                events = client.get(f"/api/v1/workflow-tasks/{task_uuid}/events")
                self.assertEqual(task.status_code, 200)
                self.assertEqual(jobs.status_code, 200)
                self.assertEqual(events.status_code, 200)
                self.assertEqual(task.json()["data"]["status"], "succeeded")
                self.assertEqual(len(jobs.json()["data"]), 6)
                self.assertGreaterEqual(len(events.json()["data"]["items"]), 14)

                state = client.get("/api/v1/demo-workflow/scene-state").json()
                self.assertEqual(state["active_step"], "completed")
                self.assertEqual(state["rail_position_m"], 0.0)
                self.assertEqual(state["vial_state"], "destination")

    def test_demo_graph_is_explicitly_draft_and_keeps_rail_arm_separate(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            base = Path(value)
            root, receipt = _write_fixture(base)
            app = create_app(
                time_scale=0.001,
                station_root=root,
                station_receipt=receipt,
                demo_workflow_db=base / "workflow.db",
            )
            with TestClient(app) as client:
                graph = client.get("/api/v1/materials/graph")
                self.assertEqual(graph.status_code, 200)
                nodes = graph.json()["data"]["nodes"]
                self.assertEqual(len(nodes), 4)
                by_uuid = {node["material"]["uuid"]: node for node in nodes}
                self.assertIn(DEMO_RAIL_MATERIAL_UUID, by_uuid)
                self.assertIn(DUCO_MATERIAL_UUID, by_uuid)
                self.assertIn(DEMO_VIAL_MATERIAL_UUID, by_uuid)

                rail = by_uuid[DEMO_RAIL_MATERIAL_UUID]
                robot = by_uuid[DUCO_MATERIAL_UUID]
                vial = by_uuid[DEMO_VIAL_MATERIAL_UUID]
                self.assertIsNone(rail["material"]["parent_uuid"])
                self.assertEqual(
                    robot["material"]["parent_uuid"],
                    DEMO_RAIL_MATERIAL_UUID,
                )
                self.assertEqual(
                    robot["material"]["config"]["rendering"]["parent_link"],
                    "feeding_station_rail_rail_carriage",
                )
                self.assertEqual(rail["relative_position"]["rotation_z"], 0.0)
                self.assertAlmostEqual(
                    robot["relative_position"]["rotation_x"],
                    0.0,
                    places=6,
                )
                self.assertAlmostEqual(
                    robot["relative_position"]["rotation_z"],
                    -180.0,
                    places=6,
                )
                defaults = robot["material"]["config"]["rendering"][
                    "kinematics"
                ]["default_joint_states"]
                self.assertEqual(len(defaults), 6)
                self.assertAlmostEqual(
                    defaults["duco_gcr5_910_gcr5_joint_1"],
                    -0.01,
                )
                registration = robot["material"]["config"][
                    "cad_urdf_visual_registration"
                ]
                self.assertTrue(registration["comparison_only"])
                self.assertTrue(registration["not_a_deploy_base_pose"])
                self.assertIsNone(vial["material"]["parent_uuid"])
                for node in nodes:
                    meta = node["material"]["meta_data"]
                    self.assertTrue(meta["preview_only"])
                    self.assertFalse(meta["hardware_execution"])
                    self.assertFalse(meta["publication_eligible"])

                rail_model = client.get(
                    "/api/v1/demo-models/feeding_station_rail.urdf"
                )
                vial_model = client.get("/api/v1/demo-models/vial-4ml.urdf")
                self.assertEqual(rail_model.status_code, 200)
                self.assertIn("feeding_station_rail_rail_joint", rail_model.text)
                self.assertEqual(vial_model.status_code, 200)
                self.assertIn("demo_vial_4ml_body", vial_model.text)

    def test_missing_or_wrong_evidence_cannot_create_demo_task(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            base = Path(value)
            root, receipt = _write_fixture(base)
            app = create_app(
                time_scale=0.001,
                station_root=root,
                station_receipt=receipt,
                demo_workflow_db=base / "workflow.db",
            )
            with TestClient(app) as client:
                missing = client.post("/api/v1/demo-workflow/runs", json={})
                self.assertEqual(missing.status_code, 422)

                activation = client.get(
                    "/api/v1/demo-workflow/descriptor"
                ).json()["required_activation"]
                activation["station_layout_sha256"] = "0" * 64
                wrong = client.post(
                    "/api/v1/demo-workflow/runs",
                    json=activation,
                )
                self.assertEqual(wrong.status_code, 409)
                tasks = client.get(
                    "/api/v1/workflow-tasks",
                    params={"workflow_uuid": "d1000000-0000-4000-8000-000000000001"},
                )
                self.assertEqual(tasks.status_code, 200)
                self.assertEqual(tasks.json()["data"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
