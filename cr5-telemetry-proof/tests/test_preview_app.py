"""CR5 / FR5 Mac 本地 SourceRelease 运动预览合同测试。"""

from __future__ import annotations

import asyncio
import hashlib
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from cr5_telemetry_lab.preview_app import (
    DOBOT_DEVICE_ID,
    FAIRINO_DEVICE_ID,
    ROBOT_DEFINITIONS,
    PreviewRuntime,
    create_app,
)
from cr5_telemetry_lab.source_release_model import verify_source_release_archive

SOURCE_ROOT = Path.home() / "Downloads" / "机械臂control"
ARCHIVES = {
    DOBOT_DEVICE_ID: SOURCE_ROOT
    / "DOBOT_CR_CRA/ros/DOBOT_6Axis_ROS2_V4-37730d08.zip",
    FAIRINO_DEVICE_ID: SOURCE_ROOT
    / "FR5/ros/frcobot_ros2-v3.0.0_robot-v3.9.7.zip",
}


class PreviewAppTest(unittest.TestCase):
    def test_catalog_models_and_meshes_are_digest_locked(self) -> None:
        app = create_app(time_scale=0.01)
        with TestClient(app) as client:
            response = client.get("/api/v1/kinematic-preview/catalog")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["schema"], "lab.kinematic_preview_catalog/v0")
            robots = {item["device_id"]: item for item in payload["robots"]}
            self.assertEqual(robots.keys(), ROBOT_DEFINITIONS.keys())

            for device_id, descriptor in robots.items():
                definition = ROBOT_DEFINITIONS[device_id]
                self.assertEqual(descriptor["schema"], "lab.kinematic_preview/v1")
                self.assertEqual(descriptor["source_digest"], definition.source_digest)
                self.assertEqual(
                    descriptor["source_release"]["archive_sha256"],
                    definition.source_digest,
                )
                self.assertTrue(descriptor["source_release"]["archive_read_only"])
                self.assertEqual(descriptor["capability"]["grade"], "kinematic-preview")
                self.assertFalse(descriptor["capability"]["hardware_execution"])
                self.assertFalse(
                    descriptor["capability"]["spatial_interlock_enforced"]
                )
                self.assertEqual(
                    len(descriptor["kinematics"]["qualified_joint_names"]),
                    6,
                )

                model = client.get(f"/api/v1/kinematic-models/{device_id}.urdf")
                self.assertEqual(model.status_code, 200)
                self.assertEqual(
                    model.headers["x-unilab-topology-digest"],
                    descriptor["kinematics"]["topology_digest"],
                )
                self.assertIn(
                    descriptor["kinematics"]["qualified_joint_names"][0],
                    model.text,
                )
                mesh = client.get(
                    f"/api/v1/kinematic-models/{device_id}/meshes/base_link.STL"
                )
                self.assertEqual(mesh.status_code, 200)
                self.assertGreater(len(mesh.content), 1000)

    def test_normal_workbench_material_graph_projects_both_providers(self) -> None:
        app = create_app(time_scale=0.01)
        with TestClient(app) as client:
            preflight = client.options(
                "/api/v1/materials/graph",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
            self.assertEqual(preflight.status_code, 200)
            self.assertEqual(
                preflight.headers["access-control-allow-origin"],
                "http://127.0.0.1:5173",
            )
            self.assertEqual(client.get("/api/v1/health").status_code, 200)
            response = client.get("/api/v1/materials/graph")
            self.assertEqual(response.status_code, 200)
            envelope = response.json()
            self.assertEqual(envelope["code"], 0)
            nodes = envelope["data"]["nodes"]
            self.assertEqual(len(nodes), 2)
            by_device = {
                node["material"]["meta_data"]["source_node_id"]: node
                for node in nodes
            }
            self.assertEqual(by_device.keys(), ROBOT_DEFINITIONS.keys())
            for device_id, node in by_device.items():
                rendering = node["material"]["config"]["rendering"]
                self.assertEqual(
                    rendering["model"]["path"],
                    f"/api/v1/kinematic-models/{device_id}.urdf",
                )
                self.assertEqual(
                    rendering["kinematics"]["device_id"],
                    device_id,
                )
                self.assertEqual(
                    len(rendering["kinematics"]["qualified_joint_names"]),
                    6,
                )
                position = node["relative_position"]
                self.assertGreater(position["width"], 1000.0)
                self.assertEqual(position["width"], position["depth"])
                self.assertEqual(position["depth"], position["length"])
                self.assertTrue(node["material"]["meta_data"]["preview_only"])

    def test_preview_workflow_publishes_exact_complete_frames_for_both(self) -> None:
        async def scenario() -> None:
            runtime = PreviewRuntime(time_scale=0.001)
            for device_id, definition in ROBOT_DEFINITIONS.items():
                subscription, snapshot = runtime.telemetry.subscribe(
                    material_uuid=definition.material_uuid,
                    telemetry_type="joint_state",
                )
                self.assertEqual(snapshot, [])
                result = await runtime.start(device_id, "inspection_sweep")
                self.assertEqual(result["status"], "running")
                deadline = time.monotonic() + 2.0
                while runtime.status(device_id)["status"] == "running":
                    self.assertLess(time.monotonic(), deadline)
                    await asyncio.sleep(0.005)
                self.assertEqual(runtime.status(device_id)["status"], "succeeded")
                events = subscription.drain()
                self.assertTrue(events)
                latest = events[-1]
                self.assertEqual(latest["local_device_id"], device_id)
                self.assertEqual(latest["material_uuid"], definition.material_uuid)
                self.assertEqual(
                    set(latest["data"]["joint_states"]),
                    set(runtime.owners[device_id].qualified_joint_names),
                )
                self.assertEqual(len(latest["data"]["joint_states"]), 6)
                self.assertFalse(latest["stale"])
                runtime.telemetry.unsubscribe(subscription)
            await runtime.close()

        asyncio.run(scenario())

    def test_unknown_and_same_robot_concurrent_workflows_fail_closed(self) -> None:
        async def scenario() -> None:
            runtime = PreviewRuntime(time_scale=0.1)
            with self.assertRaises(KeyError):
                await runtime.start("missing", "inspection_sweep")
            with self.assertRaises(KeyError):
                await runtime.start(DOBOT_DEVICE_ID, "missing")
            await runtime.start(DOBOT_DEVICE_ID, "inspection_sweep")
            with self.assertRaisesRegex(RuntimeError, "正在运行"):
                await runtime.start(DOBOT_DEVICE_ID, "inspection_sweep")
            result = await runtime.stop(DOBOT_DEVICE_ID)
            self.assertEqual(result["status"], "cancelled")
            await runtime.close()

        asyncio.run(scenario())

    def test_source_archives_remain_byte_and_stat_identical(self) -> None:
        before = {
            device_id: (_sha256(path), path.stat().st_size, path.stat().st_mtime_ns)
            for device_id, path in ARCHIVES.items()
        }
        runtime = PreviewRuntime(time_scale=0.01)
        after = {
            device_id: (_sha256(path), path.stat().st_size, path.stat().st_mtime_ns)
            for device_id, path in ARCHIVES.items()
        }
        self.assertEqual(after, before)
        for device_id, path in ARCHIVES.items():
            verify_source_release_archive(
                path,
                ROBOT_DEFINITIONS[device_id].source_digest,
            )
        asyncio.run(runtime.close())

    def test_wrong_archive_digest_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "摘要漂移"):
            verify_source_release_archive(ARCHIVES[DOBOT_DEVICE_ID], "0" * 64)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
