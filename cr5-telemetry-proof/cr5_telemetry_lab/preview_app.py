"""Mac 本地 DOBOT CR5 / FAIRINO FR5 运动学预览服务。

两个 ``package_moveit`` Provider 都从摘要锁定的只读厂家 ZIP 编译。服务复用
Uni-Lab-OS 的 ``JointStateProjector``、``DeviceTelemetryHub`` 和正式模型路由；
不连接控制器、不启动 MoveIt、不授予执行或空间互锁资格。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import struct
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from unilabos.app.edge_control.device_telemetry import DeviceTelemetryHub
from unilabos.app.edge_control.device_telemetry_api import (
    create_device_telemetry_router,
)
from unilabos.device_mesh.joint_state_projector import JointStateProjector
from unilabos.device_mesh.package_moveit_model import (
    collect_package_joint_state_owners,
    get_package_render_mesh,
    get_package_render_model,
)

from .source_release_model import get_verified_source_release_receipt

DOBOT_DEVICE_ID = "dobot_cr5"
FAIRINO_DEVICE_ID = "fairino_fr5"
DEVICE_ID = DOBOT_DEVICE_ID  # 兼容第一版 CR5 证明调用方。


@dataclass(frozen=True, slots=True)
class RobotDefinition:
    model_id: str
    device_id: str
    material_uuid: str
    display_name: str
    class_name: str
    provider: str
    source_digest: str


ROBOT_DEFINITIONS = {
    DOBOT_DEVICE_ID: RobotDefinition(
        model_id="dobot_cr5",
        device_id=DOBOT_DEVICE_ID,
        material_uuid="a1000000-0000-4000-8000-000000000001",
        display_name="Dobot CR5",
        class_name="community.robot_source_release_preview.dobot_cr5",
        provider="cr5_telemetry_lab.source_release_model:build_dobot_cr5_model",
        source_digest="487463ecc4941fe7df57e9fb2fea38477164d91907699a0e0de3e0c2c44b468c",
    ),
    FAIRINO_DEVICE_ID: RobotDefinition(
        model_id="fairino_fr5",
        device_id=FAIRINO_DEVICE_ID,
        material_uuid="a1000000-0000-4000-8000-000000000002",
        display_name="FAIRINO FR5",
        class_name="community.robot_source_release_preview.fairino_fr5",
        provider="cr5_telemetry_lab.source_release_model:build_fairino_fr5_model",
        source_digest="5e46a19e271638a7e1420f2727aaf8fb977016101a354b3694cc440f1fb9f071",
    ),
}
MATERIAL_UUID = ROBOT_DEFINITIONS[DOBOT_DEVICE_ID].material_uuid


@dataclass(frozen=True, slots=True)
class PreviewWorkflow:
    """一条受限、无执行资格的六轴关节空间预览序列。"""

    workflow_id: str
    label: str
    targets: tuple[tuple[float, ...], ...]
    seconds_per_segment: float


WORKFLOWS = {
    "inspection_sweep": PreviewWorkflow(
        workflow_id="inspection_sweep",
        label="检查位往返",
        targets=(
            (0.0, -0.45, 0.65, 0.0, 0.35, 0.0),
            (0.45, -0.30, 0.50, 0.25, 0.15, -0.30),
            (-0.35, -0.55, 0.75, -0.20, 0.30, 0.25),
            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ),
        seconds_per_segment=0.8,
    ),
}


@dataclass(slots=True)
class RobotRunState:
    positions: tuple[float, ...]
    task: asyncio.Task[None] | None = None
    run_id: str | None = None
    workflow_id: str | None = None
    status: str = "idle"
    last_error: str | None = None


def _graph_node(definition: RobotDefinition) -> dict[str, Any]:
    return {
        "id": definition.device_id,
        "type": "device",
        "class": definition.class_name,
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "config": {
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "joint_state_telemetry": {"stale_after_s": 1.0},
        },
    }


class PreviewRuntime:
    """把两种机器人的受限预览工作流投影到 OS 正式遥测合同。"""

    def __init__(self, *, rate_hz: float = 20.0, time_scale: float = 1.0) -> None:
        if not math.isfinite(rate_hz) or rate_hz <= 0:
            raise ValueError("rate_hz 必须为正有限数")
        if not math.isfinite(time_scale) or time_scale <= 0:
            raise ValueError("time_scale 必须为正有限数")
        nodes = {
            definition.device_id: _graph_node(definition)
            for definition in ROBOT_DEFINITIONS.values()
        }
        registry = {
            definition.class_name: {
                "model": {
                    "type": "package_moveit",
                    "provider": definition.provider,
                    "source_digest": definition.source_digest,
                }
            }
            for definition in ROBOT_DEFINITIONS.values()
        }
        owners = collect_package_joint_state_owners(nodes, registry)
        self.owners = {owner.device_id: owner for owner in owners}
        if set(self.owners) != set(ROBOT_DEFINITIONS):
            raise RuntimeError("机器人预览没有编译出 CR5 与 FR5 的 exact 关节归属")
        self.projector = JointStateProjector(owners, max_publish_hz=rate_hz)
        self.material_by_device = {
            definition.device_id: definition.material_uuid
            for definition in ROBOT_DEFINITIONS.values()
        }
        self.telemetry = DeviceTelemetryHub(
            lambda local_device_id, material_uuid: (
                self.material_by_device.get(local_device_id) == material_uuid
            )
        )
        self.rate_hz = rate_hz
        self.time_scale = time_scale
        self._states = {
            device_id: RobotRunState(
                positions=tuple(0.0 for _ in owner.qualified_joint_names)
            )
            for device_id, owner in self.owners.items()
        }
        self._lock = asyncio.Lock()

    def catalog(self) -> dict[str, Any]:
        """返回 Workbench 可切换的已验证机器人描述符目录。"""

        return {
            "schema": "lab.kinematic_preview_catalog/v0",
            "robots": [self.descriptor(device_id) for device_id in ROBOT_DEFINITIONS],
        }

    def descriptor(self, device_id: str) -> dict[str, Any]:
        """返回前端所需的冻结模型、源凭据与资格边界。"""

        definition = self._definition(device_id)
        owner = self.owners[device_id]
        model = get_package_render_model(device_id)
        receipt = get_verified_source_release_receipt(definition.model_id)
        if model is None or receipt is None:
            raise RuntimeError(f"{definition.display_name} 渲染模型或源凭据尚未编译")
        return {
            "schema": "lab.kinematic_preview/v1",
            "device_id": device_id,
            "material_uuid": definition.material_uuid,
            "display_name": definition.display_name,
            "source_digest": definition.source_digest,
            "source_release": {
                "archive_name": receipt.archive_path.name,
                "archive_sha256": receipt.archive_sha256,
                "repository": receipt.repository,
                "exact_ref": receipt.exact_ref,
                "urdf_member": receipt.urdf_member,
                "urdf_sha256": receipt.urdf_sha256,
                "archive_read_only": receipt.archive_read_only,
            },
            "model": {
                "path": f"/api/v1/kinematic-models/{device_id}.urdf",
                "format": "urdf",
                "position": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0],
            },
            "kinematics": {
                "device_id": device_id,
                "topology_digest": model.topology_digest,
                "qualified_joint_names": list(model.qualified_joint_names),
                "stale_after_s": owner.stale_after_s,
            },
            "capability": {
                "grade": "kinematic-preview",
                "display": True,
                "stable_picking": True,
                "motion_preview": True,
                "hardware_execution": False,
                "spatial_interlock_enforced": False,
                "reason": (
                    "Mac 本地关节空间预览；厂家 ZIP 只读，"
                    "无控制器、标定与合格碰撞资格。"
                ),
            },
            "workflows": [
                {
                    "id": workflow.workflow_id,
                    "label": workflow.label,
                    "step_count": len(workflow.targets),
                }
                for workflow in WORKFLOWS.values()
            ],
        }

    def status(self, device_id: str) -> dict[str, Any]:
        """返回指定机器人的预览状态，不冒充正式 WorkflowTask。"""

        self._definition(device_id)
        state = self._states[device_id]
        return {
            "schema": "lab.kinematic_preview_status/v0",
            "device_id": device_id,
            "run_id": state.run_id,
            "workflow_id": state.workflow_id,
            "status": state.status,
            "last_error": state.last_error,
            "not_a_workflow_task": True,
        }

    async def start(self, device_id: str, workflow_id: str) -> dict[str, Any]:
        """为指定机器人启动预览；同一机器人并发运行失败关闭。"""

        self._definition(device_id)
        workflow = WORKFLOWS.get(workflow_id)
        if workflow is None:
            raise KeyError(workflow_id)
        async with self._lock:
            state = self._states[device_id]
            if state.task is not None and not state.task.done():
                raise RuntimeError(f"{device_id} 已有运动预览正在运行")
            state.run_id = str(uuid.uuid4())
            state.workflow_id = workflow.workflow_id
            state.status = "running"
            state.last_error = None
            state.task = asyncio.create_task(
                self._run(device_id, workflow),
                name=f"{device_id}-preview-{state.run_id}",
            )
        return self.status(device_id)

    async def stop(self, device_id: str) -> dict[str, Any]:
        """停止指定机器人的预览；不会向控制器发送命令。"""

        self._definition(device_id)
        async with self._lock:
            state = self._states[device_id]
            task = state.task
            if task is not None and not task.done():
                task.cancel()
            state.status = "cancelled" if task is not None else "idle"
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        return self.status(device_id)

    async def close(self) -> None:
        """应用关闭时清理所有后台预览任务。"""

        for device_id in ROBOT_DEFINITIONS:
            await self.stop(device_id)

    async def _run(self, device_id: str, workflow: PreviewWorkflow) -> None:
        state = self._states[device_id]
        try:
            for target in workflow.targets:
                await self._interpolate(
                    device_id,
                    target,
                    duration_s=workflow.seconds_per_segment * self.time_scale,
                )
            state.status = "succeeded"
        except asyncio.CancelledError:
            state.status = "cancelled"
            raise
        except Exception as error:  # noqa: BLE001 - 状态必须可被前端读取
            state.status = "failed"
            state.last_error = str(error)
        finally:
            state.task = None

    async def _interpolate(
        self,
        device_id: str,
        target: tuple[float, ...],
        *,
        duration_s: float,
    ) -> None:
        state = self._states[device_id]
        if len(target) != len(state.positions):
            raise ValueError(f"{device_id} 预览目标必须是六轴完整状态")
        start = state.positions
        steps = max(1, math.ceil(duration_s * self.rate_hz))
        interval_s = duration_s / steps
        for index in range(1, steps + 1):
            ratio = index / steps
            positions = tuple(
                left + (right - left) * ratio
                for left, right in zip(start, target, strict=True)
            )
            self._publish(device_id, positions)
            await asyncio.sleep(interval_s)
        state.positions = target

    def _publish(self, device_id: str, positions: tuple[float, ...]) -> None:
        now = time.time()
        owner = self.owners[device_id]
        accepted = self.projector.ingest(
            owner.qualified_joint_names,
            positions,
            observed_epoch_s=now,
        )
        if not accepted:
            raise RuntimeError(f"JointStateProjector 拒绝了 {device_id} 完整关节状态")
        for frame in self.projector.drain(now_epoch_s=now):
            observed_at = datetime.fromtimestamp(
                frame.observed_epoch_s,
                tz=timezone.utc,
            ).isoformat(timespec="microseconds").replace("+00:00", "Z")
            commit = self.telemetry.ingest_joint_states(
                self.material_by_device[frame.device_id],
                {
                    "local_device_id": frame.device_id,
                    "boot_id": frame.boot_id,
                    "samples": [
                        {
                            "sequence": frame.sequence,
                            "observed_at": observed_at,
                            "stale_after_s": frame.stale_after_s,
                            "topology_digest": frame.topology_digest,
                            "joint_states": dict(frame.joint_states),
                        }
                    ],
                },
            )
            self.telemetry.notify(commit.notification_payload())

    @staticmethod
    def _definition(device_id: str) -> RobotDefinition:
        definition = ROBOT_DEFINITIONS.get(str(device_id))
        if definition is None:
            raise KeyError(device_id)
        return definition


def create_app(*, time_scale: float = 1.0) -> FastAPI:
    """创建无 ROS、无硬件的双机器人本地运动预览应用。"""

    runtime = PreviewRuntime(time_scale=time_scale)
    authority = SimpleNamespace(telemetry=runtime.telemetry)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await runtime.close()

    app = FastAPI(
        title="Robot SourceRelease Kinematic Preview",
        version="0.2.0",
        lifespan=lifespan,
    )
    # Mac Workbench runs on Vite's :5173 origin while this bounded preview
    # authority runs on :8002.  Keep the allow-list loopback-only so the
    # normal Workbench can consume Material Graph, model and SSE APIs directly
    # without rewriting their canonical /api/v1 paths through a dev proxy.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.preview_runtime = runtime
    app.include_router(create_workbench_material_router(runtime))
    app.include_router(create_preview_model_router())
    app.include_router(create_device_telemetry_router(authority))

    router = APIRouter(prefix="/api/v1/kinematic-preview")

    @router.get("/catalog")
    def catalog() -> dict[str, Any]:
        return runtime.catalog()

    @router.get("/descriptor")
    def legacy_descriptor() -> dict[str, Any]:
        return runtime.descriptor(DOBOT_DEVICE_ID)

    @router.get("/robots/{device_id}/descriptor", response_model=None)
    def descriptor(device_id: str) -> Any:
        try:
            return runtime.descriptor(device_id)
        except KeyError:
            return _not_found("未知机器人预览设备")

    @router.get("/status")
    def legacy_status() -> dict[str, Any]:
        return runtime.status(DOBOT_DEVICE_ID)

    @router.get("/robots/{device_id}/status", response_model=None)
    def status(device_id: str) -> Any:
        try:
            return runtime.status(device_id)
        except KeyError:
            return _not_found("未知机器人预览设备")

    @router.post("/workflows/{workflow_id}/runs")
    async def legacy_run_workflow(workflow_id: str) -> JSONResponse:
        return await _start_response(runtime, DOBOT_DEVICE_ID, workflow_id)

    @router.post("/robots/{device_id}/workflows/{workflow_id}/runs")
    async def run_workflow(device_id: str, workflow_id: str) -> JSONResponse:
        return await _start_response(runtime, device_id, workflow_id)

    @router.post("/runs/current:cancel")
    async def legacy_cancel_workflow() -> dict[str, Any]:
        return {"code": 0, "data": await runtime.stop(DOBOT_DEVICE_ID)}

    @router.post("/robots/{device_id}/runs/current:cancel")
    async def cancel_workflow(device_id: str) -> JSONResponse:
        try:
            result = await runtime.stop(device_id)
        except KeyError:
            return _not_found("未知机器人预览设备")
        return JSONResponse(status_code=200, content={"code": 0, "data": result})

    app.include_router(router)
    return app


def create_workbench_material_router(runtime: PreviewRuntime) -> APIRouter:
    """把双机器人投影到正常 Workbench 消费的公共 Material Graph。"""

    router = APIRouter(prefix="/api/v1")

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "robot-source-release-kinematic-preview",
            "hardware_execution": False,
        }

    @router.get("/materials/graph")
    def material_graph() -> dict[str, Any]:
        return {"code": 0, "data": {"nodes": _material_graph_nodes(runtime)}}

    @router.get("/material-shapes")
    def material_shapes() -> dict[str, Any]:
        return {"code": 0, "data": {"items": []}}

    return router


def _material_graph_nodes(runtime: PreviewRuntime) -> list[dict[str, Any]]:
    timestamp = "2026-08-26T00:00:00Z"
    x_positions_mm = {DOBOT_DEVICE_ID: -900.0, FAIRINO_DEVICE_ID: 900.0}
    nodes: list[dict[str, Any]] = []
    for index, device_id in enumerate(ROBOT_DEFINITIONS, start=1):
        descriptor = runtime.descriptor(device_id)
        definition = ROBOT_DEFINITIONS[device_id]
        model = get_package_render_model(device_id)
        if model is None:
            raise RuntimeError(f"{device_id} Material 投影缺少冻结渲染模型")
        envelope_mm = _conservative_preview_envelope_mm(model.mesh_paths)
        template_uuid = f"b1000000-0000-4000-8000-{index:012d}"
        nodes.append(
            {
                "material": {
                    "uuid": definition.material_uuid,
                    "resource_template_uuid": template_uuid,
                    "type": "device",
                    "barcode": f"preview-{device_id}",
                    "name": definition.display_name,
                    "description": "只读厂家 SourceRelease 的本地运动学预览实例",
                    "config": {
                        "category": "robot-arm",
                        "rendering": {
                            "kind": "robot-arm",
                            "materialKind": "device",
                            "model": {
                                **descriptor["model"],
                                "version": descriptor["source_digest"],
                                "attachPoints": [],
                            },
                            "kinematics": descriptor["kinematics"],
                        },
                        "capability": descriptor["capability"],
                        "source_release": descriptor["source_release"],
                    },
                    "meta_data": {
                        "source_node_id": device_id,
                        "preview_only": True,
                        "not_a_deploy_manifest": True,
                    },
                    "parent_uuid": None,
                    "revision": 1,
                    "create_time": timestamp,
                    "update_time": timestamp,
                },
                "relative_position": {
                    "material_uuid": definition.material_uuid,
                    "position_x": x_positions_mm[device_id],
                    "position_y": 0.0,
                    "position_z": 0.0,
                    "rotation_x": 0.0,
                    "rotation_y": 0.0,
                    "rotation_z": 0.0,
                    "width": envelope_mm,
                    "depth": envelope_mm,
                    "length": envelope_mm,
                },
                "current_site_uuid": None,
                "sites": [],
                "resource_template": {
                    "uuid": template_uuid,
                    "name": f"preview.{device_id}",
                    "display_name": definition.display_name,
                    "resource_type": "device",
                },
            }
        )
    return nodes


def _conservative_preview_envelope_mm(mesh_paths: tuple[Any, ...]) -> float:
    """从受管 STL 派生保守显示包络；不作为碰撞、互锁或部署尺寸。"""

    total_span_m = 0.0
    for value in mesh_paths:
        path = value if hasattr(value, "read_bytes") else None
        if path is None:
            raise ValueError("Workbench Material 投影遇到无效 mesh 路径")
        data = path.read_bytes()
        vertices: list[tuple[float, float, float]] = []
        if len(data) >= 84:
            triangle_count = struct.unpack_from("<I", data, 80)[0]
            expected_size = 84 + triangle_count * 50
            if triangle_count > 0 and expected_size <= len(data):
                for triangle_index in range(triangle_count):
                    offset = 84 + triangle_index * 50 + 12
                    for vertex_index in range(3):
                        vertices.append(
                            struct.unpack_from(
                                "<fff",
                                data,
                                offset + vertex_index * 12,
                            )
                        )
        if not vertices:
            for line in data.decode("ascii", errors="ignore").splitlines():
                fields = line.strip().split()
                if len(fields) == 4 and fields[0].lower() == "vertex":
                    vertices.append(tuple(float(field) for field in fields[1:]))
        if not vertices:
            raise ValueError(f"Workbench Material 投影无法读取 STL: {path.name}")
        spans = [
            max(vertex[axis] for vertex in vertices)
            - min(vertex[axis] for vertex in vertices)
            for axis in range(3)
        ]
        total_span_m += max(spans)
    if not math.isfinite(total_span_m) or total_span_m <= 0:
        raise ValueError("Workbench Material 投影 mesh 包络无效")
    return total_span_m * 1000.0


async def _start_response(
    runtime: PreviewRuntime,
    device_id: str,
    workflow_id: str,
) -> JSONResponse:
    try:
        result = await runtime.start(device_id, workflow_id)
    except KeyError:
        return _not_found("未知机器人或运动预览工作流")
    except RuntimeError as error:
        return JSONResponse(
            status_code=409,
            content={"code": 409, "error": {"msg": str(error)}},
        )
    return JSONResponse(status_code=202, content={"code": 0, "data": result})


def _not_found(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"code": 404, "error": {"msg": message}},
    )


def create_preview_model_router() -> APIRouter:
    """挂载与 OS 正式模型接口相同的只读路由。"""

    router = APIRouter(prefix="/api/v1/kinematic-models")

    @router.get("/{device_id}.urdf", include_in_schema=False)
    def read_render_model(device_id: str) -> Response:
        model = get_package_render_model(device_id)
        if model is None:
            return Response(status_code=404)
        return Response(
            content=model.render_urdf,
            media_type="application/xml",
            headers=_model_headers(model.device_id, model.topology_digest),
        )

    @router.get("/{device_id}/meshes/{asset_name}", include_in_schema=False)
    def read_mesh(device_id: str, asset_name: str) -> Response:
        model = get_package_render_model(device_id)
        asset = get_package_render_mesh(device_id, asset_name)
        if model is None or asset is None:
            return Response(status_code=404)
        return FileResponse(
            asset,
            media_type="model/stl" if asset.suffix.lower() == ".stl" else None,
            headers=_model_headers(model.device_id, model.topology_digest),
        )

    return router


def _model_headers(device_id: str, topology_digest: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "X-UniLab-Device-Id": device_id,
        "X-UniLab-Topology-Digest": topology_digest,
    }


def main() -> None:
    """运行本地证明服务。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8002, type=int)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
