"""Demo-only feeding-station WorkflowTask and Workbench scene projection.

This module deliberately reuses the Uni-Lab OS WorkflowStore,
TaskSchedulerBridge, EdgeScheduler and public workflow HTTP router.  The
dispatcher only mutates an in-process visualization state; it never opens a
controller, PLC, ROS action, MoveIt or hardware transport.
"""

from __future__ import annotations

import copy
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from unilab_rail_linear import build_kinematic_model
from unilabos.app.scheduler.service import EdgeScheduler
from unilabos.workflow.service import WorkflowService
from unilabos.workflow.store import StoreNotFound, WorkflowStore
from unilabos.workflow.task_input import PreparedTaskInput
from unilabos.workflow.task_scheduler_bridge import TaskSchedulerBridge

from .station_preview import StationPreview

DEMO_WORKFLOW_UUID = "d1000000-0000-4000-8000-000000000001"
DEMO_RAIL_DEVICE_ID = "feeding_station_rail"
DEMO_RAIL_MATERIAL_UUID = "d5000000-0000-4000-8000-000000000001"
DEMO_RAIL_TEMPLATE_UUID = "d5100000-0000-4000-8000-000000000001"
DEMO_VIAL_MATERIAL_UUID = "d4000000-0000-4000-8000-000000000001"
DEMO_VIAL_TEMPLATE_UUID = "d4100000-0000-4000-8000-000000000001"
DUCO_DEVICE_ID = "duco_gcr5_910"
DUCO_MATERIAL_UUID = "a1000000-0000-4000-8000-000000000003"
DUCO_TEMPLATE_UUID = "d5200000-0000-4000-8000-000000000001"

_NODE_UUIDS = tuple(
    f"d2000000-0000-4000-8000-{index:012d}" for index in range(1, 7)
)
_EDGE_UUIDS = tuple(
    f"d3000000-0000-4000-8000-{index:012d}" for index in range(1, 6)
)
_ACTION_SEQUENCE = (
    (DEMO_RAIL_DEVICE_ID, "rail_move_pick"),
    (DUCO_DEVICE_ID, "gcr5_pick_pose"),
    (DUCO_DEVICE_ID, "vial_4ml_attach"),
    (DUCO_DEVICE_ID, "gcr5_carry_pose"),
    (DUCO_DEVICE_ID, "vial_4ml_detach"),
    (DEMO_RAIL_DEVICE_ID, "robot_rail_reset"),
)
_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
        "result": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    "additionalProperties": False,
}


class RobotPreviewPort(Protocol):
    """The bounded robot projection methods consumed by the demo."""

    def descriptor(self, device_id: str) -> dict[str, Any]: ...

    def publish_positions(
        self,
        device_id: str,
        positions: tuple[float, ...],
    ) -> None: ...


class DemoRunRequest(BaseModel):
    """Fail-closed evidence token for starting the simulation-only run."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo-simulation"]
    station_geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    station_layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    robot_topology_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cad_comparison_pose_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hardware_execution: Literal[False]
    publication_eligible: Literal[False]


class DemoWorkflowConflict(RuntimeError):
    """The requested demo cannot cross its fixed evidence boundary."""


class _QueuedSimulationDispatcher:
    """Collect OS dispatch payloads for deterministic in-process draining."""

    def __init__(self) -> None:
        self._items: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()

    def dispatch(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(dict(payload))

    def pop(self) -> dict[str, Any] | None:
        with self._lock:
            return self._items.popleft() if self._items else None


class FeedingStationDemoWorkflow:
    """Own the standard WorkflowTask authority and visualization-only executor."""

    def __init__(
        self,
        *,
        station: StationPreview,
        robot_runtime: RobotPreviewPort,
        database_path: Path,
    ) -> None:
        self.station = station
        self.robot_runtime = robot_runtime
        self.rail_model = build_kinematic_model(device_id=DEMO_RAIL_DEVICE_ID)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = WorkflowStore(database_path)
        self._ensure_workflow_definition()
        self.dispatcher = _QueuedSimulationDispatcher()
        self.scheduler = EdgeScheduler(dispatcher=self.dispatcher)
        self.bridge = TaskSchedulerBridge(self.store, scheduler=self.scheduler)
        self.service = WorkflowService(
            self.store,
            task_scheduler_bridge=self.bridge,
        )
        self._run_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._rail_position_m = 0.0
        self._vial_state = "source"
        self._active_step = "idle"
        self._last_task_uuid: str | None = None
        self._scene_revision = 1
        self._comparison_joint_positions = self._cad_comparison_joint_positions()
        self.robot_runtime.publish_positions(
            DUCO_DEVICE_ID,
            self._comparison_joint_positions,
        )

    def close(self) -> None:
        self.service.close()

    def descriptor(self) -> dict[str, Any]:
        robot = self.robot_runtime.descriptor(DUCO_DEVICE_ID)
        return {
            "schema": "lab.feeding_station_demo_workflow/v0",
            "workflow_uuid": DEMO_WORKFLOW_UUID,
            "name": "投料站 4 ml 搬运资产管线演示",
            "validation_status": "demo-ready",
            "required_activation": {
                "mode": "demo-simulation",
                "station_geometry_sha256": self.station.geometry_sha256,
                "station_layout_sha256": self.station.layout_sha256,
                "robot_topology_digest": robot["kinematics"][
                    "topology_digest"
                ],
                "cad_comparison_pose_sha256": (
                    self.station.cad_comparison_pose_sha256
                ),
                "hardware_execution": False,
                "publication_eligible": False,
            },
            "actions": [action for _device, action in _ACTION_SEQUENCE],
            "scene": {
                "station_material_uuid": self.station.material_graph_node()[
                    "material"
                ]["uuid"],
                "rail_material_uuid": DEMO_RAIL_MATERIAL_UUID,
                "robot_material_uuid": DUCO_MATERIAL_UUID,
                "vial_material_uuid": DEMO_VIAL_MATERIAL_UUID,
            },
            "capability": {
                "grade": "demo-simulation",
                "display": True,
                "workflow_task_authority": "Uni-Lab-OS",
                "hardware_execution": False,
                "publication_eligible": False,
                "p2_human_reviewed": False,
                "w2_eligible": False,
                "collision_qualified": False,
                "spatial_interlock_enforced": False,
                "motion_planning_qualified": False,
            },
        }

    def state(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "schema": "lab.feeding_station_demo_scene_state/v0",
                "active_step": self._active_step,
                "rail_position_m": self._rail_position_m,
                "vial_state": self._vial_state,
                "last_workflow_task_uuid": self._last_task_uuid,
                "scene_revision": self._scene_revision,
                "hardware_execution": False,
                "publication_eligible": False,
            }

    def create_run(self, request: DemoRunRequest) -> dict[str, Any]:
        self._validate_activation(request)
        if not self._run_lock.acquire(blocking=False):
            raise DemoWorkflowConflict("已有投料站 Demo WorkflowTask 正在运行")
        try:
            self._reset_scene_for_run()
            task_uuid = str(uuid4())
            jobs = [
                {
                    "uuid": str(uuid4()),
                    "workflow_node_uuid": node_uuid,
                    "topological_index": index,
                    "executor_kind": "device_action",
                    "execution_policy": {"mode": "demo-simulation"},
                    "execution_timeout_seconds": 0,
                    "param": {},
                }
                for index, node_uuid in enumerate(_NODE_UUIDS)
            ]
            plan = self._execution_plan()
            task = self.store.create_task_with_jobs(
                workflow_uuid=DEMO_WORKFLOW_UUID,
                task_uuid=task_uuid,
                run_mode="normal",
                target_node_uuid=None,
                description="DEMO / DRAFT / NO HARDWARE: 4 ml 资产管线展示",
                meta_data={
                    "demo": True,
                    "demo_contract": "simulation-only",
                    "hardware_execution": False,
                    "publication_eligible": False,
                    "station_geometry_sha256": self.station.geometry_sha256,
                    "station_layout_sha256": self.station.layout_sha256,
                    "robot_topology_digest": request.robot_topology_digest,
                    "cad_comparison_pose_sha256": (
                        request.cad_comparison_pose_sha256
                    ),
                },
                plan_builder=lambda graph: PreparedTaskInput(
                    workflow_snapshot=graph,
                    resolved_input={},
                    execution_plan=plan,
                    jobs=jobs,
                ),
            )
            with self._state_lock:
                self._last_task_uuid = task_uuid
            self.bridge.submit(task)
            self._drain_simulation_actions()
            terminal = self.service.get_workflow_task(task_uuid)
            terminal_jobs = self.service.list_workflow_node_jobs(task_uuid)
            validation_status = (
                "demo-workflow-validated"
                if terminal["status"] == "succeeded"
                and all(job["status"] == "succeeded" for job in terminal_jobs)
                else "demo-workflow-failed"
            )
            return {
                "validation_status": validation_status,
                "task": terminal,
                "jobs": terminal_jobs,
                "scene_state": self.state(),
                "links": {
                    "task": f"/api/v1/workflow-tasks/{task_uuid}",
                    "jobs": f"/api/v1/workflow-tasks/{task_uuid}/jobs",
                    "events": f"/api/v1/workflow-tasks/{task_uuid}/events",
                    "scene": "/api/v1/materials/graph",
                },
            }
        finally:
            self._run_lock.release()

    def material_graph_nodes(self) -> list[dict[str, Any]]:
        station_node = copy.deepcopy(self.station.material_graph_node())
        station_material = station_node["material"]
        station_material["name"] = "【DEMO / DRAFT / NO HARDWARE】投料站"
        station_material["description"] = (
            "摘要锁定 P1 几何、P2 自动分解草案与仿真投影；不是验收或部署清单"
        )
        station_material["meta_data"].update(
            {
                "demo_channel": True,
                "hardware_execution": False,
                "publication_eligible": False,
            }
        )
        station_material["revision"] = self._scene_revision
        station_material["update_time"] = _utc_now()
        return [
            station_node,
            self._rail_graph_node(),
            self._robot_graph_node(),
            self._vial_graph_node(),
        ]

    def _ensure_workflow_definition(self) -> None:
        try:
            self.store.get_workflow(DEMO_WORKFLOW_UUID)
        except StoreNotFound:
            self.store.create_workflow(
                workflow_uuid=DEMO_WORKFLOW_UUID,
                name="投料站 4 ml Demo Workflow",
                tags=["demo", "feeding-station", "no-hardware"],
                description="仅用于资产管线画面与 WorkflowTask 合同测试",
                meta_data={
                    "demo": True,
                    "hardware_execution": False,
                    "publication_eligible": False,
                },
            )

    def _validate_activation(self, request: DemoRunRequest) -> None:
        robot = self.robot_runtime.descriptor(DUCO_DEVICE_ID)
        checks = {
            "station geometry": (
                request.station_geometry_sha256,
                self.station.geometry_sha256,
            ),
            "station P2 layout": (
                request.station_layout_sha256,
                self.station.layout_sha256,
            ),
            "GCR5 topology": (
                request.robot_topology_digest,
                robot["kinematics"]["topology_digest"],
            ),
            "GCR5 CAD comparison pose": (
                request.cad_comparison_pose_sha256,
                self.station.cad_comparison_pose_sha256,
            ),
        }
        for label, (received, expected) in checks.items():
            if received != expected:
                raise DemoWorkflowConflict(f"{label} 摘要不匹配，Demo 失败关闭")

    def _reset_scene_for_run(self) -> None:
        with self._state_lock:
            self._rail_position_m = 0.0
            self._vial_state = "source"
            self._active_step = "admitted"
            self._scene_revision += 1
        self.robot_runtime.publish_positions(
            DUCO_DEVICE_ID,
            self._comparison_joint_positions,
        )

    def _drain_simulation_actions(self) -> None:
        while True:
            payload = self.dispatcher.pop()
            if payload is None:
                break
            try:
                result = self._execute_action(payload)
            except Exception as error:  # noqa: BLE001 - persist explicit failure
                self.scheduler.on_job_finished(
                    payload["job_id"],
                    False,
                    {"error": str(error), "demo": True},
                )
                break
            self.scheduler.on_job_finished(payload["job_id"], True, result)

    def _execute_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "")
        device_id = str(payload.get("device_id") or "")
        if (device_id, action) not in _ACTION_SEQUENCE:
            raise DemoWorkflowConflict(f"未知 Demo 执行动作：{device_id}/{action}")
        with self._state_lock:
            self._active_step = action
            if action == "rail_move_pick":
                self._rail_position_m = 1.25
            elif action == "gcr5_pick_pose":
                self.robot_runtime.publish_positions(
                    DUCO_DEVICE_ID,
                    (0.0, -0.82, 1.18, 0.0, 0.58, 0.0),
                )
            elif action == "vial_4ml_attach":
                self._vial_state = "attached"
            elif action == "gcr5_carry_pose":
                self.robot_runtime.publish_positions(
                    DUCO_DEVICE_ID,
                    (0.48, -0.48, 0.82, 0.18, 0.22, -0.38),
                )
            elif action == "vial_4ml_detach":
                self._vial_state = "destination"
            elif action == "robot_rail_reset":
                self.robot_runtime.publish_positions(
                    DUCO_DEVICE_ID,
                    self._comparison_joint_positions,
                )
                self._rail_position_m = 0.0
                self._active_step = "completed"
            self._scene_revision += 1
            return {
                "action": action,
                "device_id": device_id,
                "simulation": True,
                "hardware_execution": False,
                "scene_revision": self._scene_revision,
            }

    def _execution_plan(self) -> dict[str, Any]:
        nodes = []
        for node_uuid, (device_id, action) in zip(
            _NODE_UUIDS,
            _ACTION_SEQUENCE,
            strict=True,
        ):
            nodes.append(
                {
                    "uuid": node_uuid,
                    "kind": "device_action",
                    "device_id": device_id,
                    "action_name": action,
                    "action_type": "UniLabJsonCommand",
                    "param": {},
                    "param_schema": copy.deepcopy(_ACTION_SCHEMA),
                    "material_requirements": [],
                    "always_free": False,
                }
            )
        edges = [
            {
                "uuid": edge_uuid,
                "source_node_uuid": _NODE_UUIDS[index],
                "target_node_uuid": _NODE_UUIDS[index + 1],
                "dependency_only": True,
            }
            for index, edge_uuid in enumerate(_EDGE_UUIDS)
        ]
        return {
            "version": 1,
            "run_mode": "normal",
            "target_node_uuid": None,
            "nodes": nodes,
            "handles": [],
            "edges": edges,
        }

    def _rail_graph_node(self) -> dict[str, Any]:
        robot_position, _robot_rotation = self._robot_mount_pose()
        return _material_node(
            material_uuid=DEMO_RAIL_MATERIAL_UUID,
            template_uuid=DEMO_RAIL_TEMPLATE_UUID,
            source_node_id=DEMO_RAIL_DEVICE_ID,
            name="【DEMO】投料站单轴导轨（仿真）",
            description="L1 单轴运动学投影；不连接 PLC",
            category="linear-rail",
            model={
                "path": f"/api/v1/demo-models/{DEMO_RAIL_DEVICE_ID}.urdf",
                "format": "urdf",
                "version": self.rail_model.topology_digest,
                "position": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "attachPoints": [],
            },
            dimensions_mm=[2250.0, 140.0, 120.0],
            position_mm=robot_position,
            rotation_deg=[0.0, 0.0, 0.0],
            revision=self._scene_revision,
            extra_rendering={
                "kinematics": {
                    "device_id": DEMO_RAIL_DEVICE_ID,
                    "topology_digest": self.rail_model.topology_digest,
                    "qualified_joint_names": list(
                        self.rail_model.qualified_joint_names
                    ),
                    "stale_after_s": 1.0,
                }
            },
        )

    def _robot_graph_node(self) -> dict[str, Any]:
        descriptor = self.robot_runtime.descriptor(DUCO_DEVICE_ID)
        _robot_position, robot_rotation = self._robot_mount_pose()
        qualified_names = descriptor["kinematics"]["qualified_joint_names"]
        kinematics = {
            **descriptor["kinematics"],
            "default_joint_states": dict(
                zip(
                    qualified_names,
                    self._comparison_joint_positions,
                    strict=True,
                )
            ),
            "default_joint_state_authority": "cad-comparison-only",
        }
        return _material_node(
            material_uuid=DUCO_MATERIAL_UUID,
            template_uuid=DUCO_TEMPLATE_UUID,
            source_node_id=DUCO_DEVICE_ID,
            name="【DEMO】GCR5-910 运动学叠加层",
            description="与 P1 静态机器人对照的青色仿真叠加层",
            category="robot-arm",
            model={
                **descriptor["model"],
                "version": descriptor["source_digest"],
                "color": "#00d8ff",
                "attachPoints": [],
            },
            dimensions_mm=[1600.0, 1600.0, 1800.0],
            position_mm=[0.0, 0.0, 0.0],
            rotation_deg=robot_rotation,
            revision=self._scene_revision,
            parent_uuid=DEMO_RAIL_MATERIAL_UUID,
            extra_rendering={
                "parent_link": self.rail_model.mount_link,
                "kinematics": kinematics,
            },
            extra_config={
                "source_release": descriptor["source_release"],
                "cad_urdf_visual_registration": {
                    "sha256": self.station.cad_comparison_pose_sha256,
                    "qualification": "cad-comparison-only",
                    "comparison_only": True,
                    "not_a_deploy_base_pose": True,
                    "not_calibrated": True,
                    "residuals": dict(
                        self.station.cad_comparison_pose["residuals"]
                    ),
                },
            },
        )

    def _vial_graph_node(self) -> dict[str, Any]:
        if self._vial_state == "source":
            position = self._candidate_position(self.station.four_ml_representative)
            parent_uuid = None
            parent_link = None
        elif self._vial_state == "attached":
            position = [0.0, 0.0, 120.0]
            parent_uuid = DUCO_MATERIAL_UUID
            parent_link = self._robot_tool_link()
        else:
            position = [-420.0, 180.0, 820.0]
            parent_uuid = None
            parent_link = None
        rendering = {"parent_link": parent_link} if parent_link else {}
        return _material_node(
            material_uuid=DEMO_VIAL_MATERIAL_UUID,
            template_uuid=DEMO_VIAL_TEMPLATE_UUID,
            source_node_id="demo_vial_4ml",
            name="【DEMO】4 ml 有盖玻璃瓶",
            description="由 P2 occurrence 候选实例化的演示瓶；不是批准物理槽位",
            category="vial-4ml",
            model={
                "path": "/api/v1/demo-models/vial-4ml.urdf",
                "format": "urdf",
                "version": "demo-vial-4ml-v1",
                "position": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "attachPoints": [],
            },
            dimensions_mm=[14.0, 14.0, 52.0],
            position_mm=position,
            rotation_deg=[0.0, 0.0, 0.0],
            revision=self._scene_revision,
            parent_uuid=parent_uuid,
            extra_rendering=rendering,
            extra_config={"demo_vial_state": self._vial_state},
        )

    def _robot_tool_link(self) -> str:
        descriptor = self.robot_runtime.descriptor(DUCO_DEVICE_ID)
        names = descriptor["kinematics"]["qualified_joint_names"]
        # The model route owns the exact link topology.  This fallback stays
        # explicit and only affects a transient visualization attachment.
        return str(names[-1]).replace("joint", "link")

    def _robot_mount_pose(self) -> tuple[list[float], list[float]]:
        pose = self.station.cad_comparison_pose["root_pose_solidworks_world"]
        return (
            self.station.solidworks_world_to_lab_mm(pose["xyz_m"]),
            [float(value) for value in pose["rotation_xyz_deg"]],
        )

    def _cad_comparison_joint_positions(self) -> tuple[float, ...]:
        descriptor = self.robot_runtime.descriptor(DUCO_DEVICE_ID)
        topology_digest = descriptor["kinematics"]["topology_digest"]
        pose = self.station.cad_comparison_pose
        if pose["robot_topology_digest"] != topology_digest:
            raise DemoWorkflowConflict(
                "CAD comparison pose 与当前 GCR5 topology digest 不匹配"
            )
        names = descriptor["kinematics"]["qualified_joint_names"]
        positions = pose["joint_positions"]
        if set(names) != set(positions):
            raise DemoWorkflowConflict("CAD comparison pose 未 exact 覆盖 GCR5 六轴")
        return tuple(float(positions[name]) for name in names)

    def _candidate_position(self, candidate: Any) -> list[float]:
        if not isinstance(candidate, dict):
            raise DemoWorkflowConflict("P2 候选不是对象")
        transform = candidate.get("transform_world")
        if not isinstance(transform, dict):
            raise DemoWorkflowConflict("P2 候选缺少 transform_world")
        xyz = transform.get("xyz_m")
        if not isinstance(xyz, list) or len(xyz) != 3:
            raise DemoWorkflowConflict("P2 候选位置无效")
        return self.station.solidworks_world_to_lab_mm(xyz)


def create_demo_router(runtime: FeedingStationDemoWorkflow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/demo-workflow", tags=["demo-workflow"])

    @router.get("/descriptor")
    def descriptor() -> dict[str, Any]:
        return runtime.descriptor()

    @router.get("/scene-state")
    def scene_state() -> dict[str, Any]:
        return runtime.state()

    @router.post("/runs")
    def create_run(body: DemoRunRequest) -> JSONResponse:
        try:
            result = runtime.create_run(body)
        except DemoWorkflowConflict as error:
            return JSONResponse(
                status_code=409,
                content={"code": 409, "error": {"msg": str(error)}},
            )
        status_code = 201 if result["task"]["status"] == "succeeded" else 500
        return JSONResponse(
            status_code=status_code,
            content={"code": 0, "data": result},
        )

    return router


def create_demo_model_router(runtime: FeedingStationDemoWorkflow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/demo-models")

    @router.get(f"/{DEMO_RAIL_DEVICE_ID}.urdf", include_in_schema=False)
    def rail_model() -> Response:
        return Response(
            content=runtime.rail_model.render_urdf,
            media_type="application/xml",
            headers={
                "Cache-Control": "no-store",
                "X-UniLab-Demo-Only": "true",
                "X-UniLab-Topology-Digest": runtime.rail_model.topology_digest,
            },
        )

    @router.get("/vial-4ml.urdf", include_in_schema=False)
    def vial_model() -> Response:
        return Response(
            content=_VIAL_URDF,
            media_type="application/xml",
            headers={
                "Cache-Control": "no-store",
                "X-UniLab-Demo-Only": "true",
            },
        )

    return router


def _material_node(
    *,
    material_uuid: str,
    template_uuid: str,
    source_node_id: str,
    name: str,
    description: str,
    category: str,
    model: dict[str, Any],
    dimensions_mm: list[float],
    position_mm: list[float],
    rotation_deg: list[float],
    revision: int,
    parent_uuid: str | None = None,
    extra_rendering: dict[str, Any] | None = None,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = _utc_now()
    rendering = {
        "kind": category,
        "materialKind": "device",
        "dimensionsMm": dimensions_mm,
        "footprintMm": dimensions_mm[:2],
        "model": model,
        **(extra_rendering or {}),
    }
    return {
        "material": {
            "uuid": material_uuid,
            "resource_template_uuid": template_uuid,
            "type": "device",
            "barcode": f"demo-{source_node_id}",
            "name": name,
            "description": description,
            "config": {
                "category": category,
                "rendering": rendering,
                "capability": {
                    "grade": "demo-simulation",
                    "display": True,
                    "hardware_execution": False,
                    "publication_eligible": False,
                    "w2_eligible": False,
                    "collision_qualified": False,
                    "spatial_interlock_enforced": False,
                    "motion_planning_qualified": False,
                    "physical_site_approved": False,
                },
                **(extra_config or {}),
            },
            "meta_data": {
                "source_node_id": source_node_id,
                "demo_channel": True,
                "preview_only": True,
                "p2_draft": True,
                "hardware_execution": False,
                "publication_eligible": False,
                "not_a_deploy_manifest": True,
                "not_a_workcell_activation": True,
            },
            "parent_uuid": parent_uuid,
            "revision": max(1, revision),
            "create_time": timestamp,
            "update_time": timestamp,
        },
        "relative_position": {
            "material_uuid": material_uuid,
            "position_x": position_mm[0],
            "position_y": position_mm[1],
            "position_z": position_mm[2],
            "rotation_x": rotation_deg[0],
            "rotation_y": rotation_deg[1],
            "rotation_z": rotation_deg[2],
            "width": dimensions_mm[0],
            "depth": dimensions_mm[1],
            "length": dimensions_mm[2],
        },
        "current_site_uuid": None,
        "sites": [],
        "resource_template": {
            "uuid": template_uuid,
            "name": f"demo.{source_node_id}",
            "display_name": name,
            "resource_type": "device",
        },
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


_VIAL_URDF = """<?xml version="1.0"?>
<robot name="demo_vial_4ml">
  <link name="demo_vial_4ml_body">
    <visual>
      <origin xyz="0 0 0.0225" rpy="0 0 0"/>
      <geometry><cylinder radius="0.006" length="0.045"/></geometry>
      <material name="glass"><color rgba="0.70 0.92 1.0 0.68"/></material>
    </visual>
    <visual>
      <origin xyz="0 0 0.048" rpy="0 0 0"/>
      <geometry><cylinder radius="0.007" length="0.006"/></geometry>
      <material name="cap"><color rgba="0.12 0.42 0.85 1.0"/></material>
    </visual>
  </link>
</robot>
"""


__all__ = [
    "DEMO_WORKFLOW_UUID",
    "DemoRunRequest",
    "DemoWorkflowConflict",
    "FeedingStationDemoWorkflow",
    "create_demo_model_router",
    "create_demo_router",
]
