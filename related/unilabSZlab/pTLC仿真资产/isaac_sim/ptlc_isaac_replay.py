#!/usr/bin/env python3
"""Build and replay the evidence-bounded pTLC scene in Isaac Sim 6.0.1."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gc
import json
import math
import os
import re
import shutil
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from validate_replay_inputs import DEFAULT_REPLAY_POINTS, validate_inputs


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def require_authorization(gpu_index: int) -> None:
    accepted = os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower()
    if accepted not in {"1", "y", "yes"}:
        raise RuntimeError(
            "NVIDIA Omniverse EULA acceptance is required. Set "
            "OMNI_KIT_ACCEPT_EULA=YES only after explicit user agreement."
        )
    if gpu_index != 1:
        raise RuntimeError(
            f"This pTLC run is authorized only for physical GPU 1, got {gpu_index}"
        )
    cuda_visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_visible_devices not in {None, "", "1"}:
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES may only be unset or exactly '1' for this run; "
            f"got {cuda_visible_devices!r}."
        )


def physics_gpu_index(gpu_index: int) -> int:
    """Return CUDA's logical index while Vulkan keeps the physical index."""

    if os.environ.get("CUDA_VISIBLE_DEVICES") == "1":
        return 0
    return gpu_index


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def gpu_snapshot() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    rows = subprocess.check_output(command, text=True).splitlines()
    keys = (
        "index",
        "uuid",
        "name",
        "memory_total_mib",
        "memory_used_mib",
        "memory_free_mib",
        "utilization_gpu_percent",
    )
    result = []
    for row in rows:
        values = [value.strip() for value in row.split(",")]
        record: dict[str, Any] = dict(zip(keys, values, strict=True))
        for key in (
            "index",
            "memory_total_mib",
            "memory_used_mib",
            "memory_free_mib",
            "utilization_gpu_percent",
        ):
            record[key] = int(record[key])
        result.append(record)
    return result


def current_process_gpu_allocations() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ]
    output = subprocess.check_output(command, text=True).strip()
    result = []
    if not output:
        return result
    for row in output.splitlines():
        uuid, pid, process_name, used_memory = [
            value.strip() for value in row.split(",", 3)
        ]
        if int(pid) == os.getpid():
            result.append(
                {
                    "gpu_uuid": uuid,
                    "pid": int(pid),
                    "process_name": process_name,
                    "used_memory_mib": int(used_memory),
                }
            )
    return result


def safe_identifier(value: str) -> str:
    identifier = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not identifier or identifier[0].isdigit():
        identifier = f"p_{identifier}"
    return identifier


def derive_robot_urdf(workspace: Path, output_dir: Path) -> Path:
    source_urdf = workspace / "dobot_rviz/urdf/cr5_robot.urdf"
    prepared_root = output_dir / "prepared_robot"
    prepared_meshes = prepared_root / "meshes/cr5"
    prepared_meshes.mkdir(parents=True, exist_ok=True)
    for mesh_path in sorted((workspace / "dobot_rviz/meshes/cr5").glob("*.STL")):
        shutil.copy2(mesh_path, prepared_meshes / mesh_path.name)

    tree = ET.parse(source_urdf)
    root = tree.getroot()
    for mesh in root.findall(".//mesh"):
        filename = mesh.get("filename", "")
        prefix = "package://dobot_rviz/meshes/cr5/"
        if not filename.startswith(prefix):
            raise ValueError(f"Unsupported CR5 mesh URI: {filename}")
        mesh.set("filename", f"../meshes/cr5/{filename.removeprefix(prefix)}")
    derived_urdf = prepared_root / "urdf/cr5_robot_isaac.urdf"
    derived_urdf.parent.mkdir(parents=True, exist_ok=True)
    tree.write(derived_urdf, encoding="utf-8", xml_declaration=True)
    return derived_urdf


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_cr5(derived_urdf: Path, output_dir: Path, simulation_app: Any) -> Path:
    import omni.kit.app
    from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig

    extension_manager = omni.kit.app.get_app().get_extension_manager()
    extension_manager.set_extension_enabled_immediate(
        "isaacsim.asset.importer.urdf", True
    )
    simulation_app.update()
    importer = URDFImporter(
        URDFImporterConfig(
            urdf_path=str(derived_urdf),
            usd_path=str(output_dir / "cr5.usd"),
            merge_mesh=True,
            allow_self_collision=True,
            fix_base=True,
            joint_drive_type="force",
            joint_target_type="position",
            override_joint_stiffness=8000.0,
            override_joint_damping=800.0,
        )
    )
    imported_path = Path(importer.import_urdf()).resolve()
    if not imported_path.is_file():
        raise RuntimeError(f"CR5 import did not create {imported_path}")
    simulation_app.update()
    return imported_path


def xform_pose(xform: Any, position: list[float], rpy_degrees: list[float]) -> None:
    from pxr import Gf, UsdGeom

    api = UsdGeom.XformCommonAPI(xform)
    api.SetTranslate(Gf.Vec3d(*[float(value) for value in position]))
    api.SetRotate(
        Gf.Vec3f(*[float(value) for value in rpy_degrees]),
        UsdGeom.XformCommonAPI.RotationOrderXYZ,
    )


def transformed_meshes(path: Path, *, scale: float = 1.0) -> list[Any]:
    import trimesh

    loaded = trimesh.load(path, force="scene", process=False)
    meshes = []
    for geometry in loaded.dump(concatenate=False):
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        mesh = geometry.copy()
        if scale != 1.0:
            mesh.apply_scale(scale)
        if mesh.faces.shape[1] != 3:
            mesh = mesh.triangulate()
        meshes.append(mesh)
    if not meshes:
        raise RuntimeError(f"No mesh geometry in {path}")
    return meshes


def author_mesh(
    stage: Any,
    prim_path: str,
    mesh: Any,
    *,
    collision: bool,
) -> str:
    from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics, Vt

    usd_mesh = UsdGeom.Mesh.Define(stage, prim_path)
    points = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    usd_mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points))
    usd_mesh.CreateFaceVertexCountsAttr([3] * len(faces))
    usd_mesh.CreateFaceVertexIndicesAttr(faces.reshape(-1).tolist())
    usd_mesh.CreateSubdivisionSchemeAttr("none")

    color = np.array([0.55, 0.60, 0.65], dtype=float)
    opacity = 1.0
    visual = getattr(mesh, "visual", None)
    vertex_colors = getattr(visual, "vertex_colors", None)
    if vertex_colors is not None and len(vertex_colors):
        rgba = np.asarray(vertex_colors, dtype=float).mean(axis=0) / 255.0
        color = rgba[:3]
        opacity = float(rgba[3]) if len(rgba) > 3 else 1.0
    gprim = UsdGeom.Gprim(usd_mesh.GetPrim())
    gprim.CreateDisplayColorAttr([Gf.Vec3f(*color.tolist())])
    gprim.CreateDisplayOpacityAttr([opacity])

    if collision:
        UsdPhysics.CollisionAPI.Apply(usd_mesh.GetPrim())
        mesh_collision = UsdPhysics.MeshCollisionAPI.Apply(usd_mesh.GetPrim())
        mesh_collision.CreateApproximationAttr("none")
        PhysxSchema.PhysxCollisionAPI.Apply(usd_mesh.GetPrim())
        usd_mesh.CreatePurposeAttr("guide")
        UsdGeom.Imageable(usd_mesh.GetPrim()).MakeInvisible()
    return str(usd_mesh.GetPath())


def author_proxy_assets(
    stage: Any,
    workspace: Path,
    layout: dict[str, Any],
) -> dict[str, Any]:
    from pxr import UsdGeom

    root = UsdGeom.Scope.Define(stage, "/World/Lab/Assets")
    del root
    records = []
    for placement in layout["placements"]:
        asset_id = placement["asset_id"]
        asset_path = f"/World/Lab/Assets/{safe_identifier(asset_id)}"
        asset_xform = UsdGeom.Xform.Define(stage, asset_path)
        xform_pose(asset_xform, placement["position_m"], placement["rpy_deg"])

        visual_path = workspace / f"pTLC仿真资产/proxies/{asset_id}/visual.glb"
        collision_path = workspace / f"pTLC仿真资产/proxies/{asset_id}/collision.stl"
        visual_meshes = transformed_meshes(visual_path)
        collision_meshes = transformed_meshes(collision_path, scale=0.001)
        visual_prims = [
            author_mesh(
                stage,
                f"{asset_path}/Visual/mesh_{index:03d}",
                mesh,
                collision=False,
            )
            for index, mesh in enumerate(visual_meshes)
        ]
        collision_prims = [
            author_mesh(
                stage,
                f"{asset_path}/Collision/mesh_{index:03d}",
                mesh,
                collision=True,
            )
            for index, mesh in enumerate(collision_meshes)
        ]
        records.append(
            {
                "asset_id": asset_id,
                "prim": asset_path,
                "visual_mesh_count": len(visual_prims),
                "collision_mesh_count": len(collision_prims),
                "position_m": placement["position_m"],
                "rpy_degrees": placement["rpy_deg"],
            }
        )
    return {"count": len(records), "assets": records}


def point_records(points_document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        point
        for group in points_document["data"]["robot"]["groups"]
        for point in group["points"]
    ]


def rail_slot_map(rail_analysis: dict[str, Any]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    bindings = rail_analysis["semantic_binding_provenance"][
        "point_family_to_rail_slot"
    ]["bindings"]
    for binding in bindings:
        for number in binding["explicit_point_numbers"]:
            mapping[int(number)] = int(binding["rail_slot"])
    return mapping


def original_point_number(point_name: str) -> int | None:
    return int(point_name[1:]) if re.fullmatch(r"P\d+", point_name) else None


def marker_world_position(
    point: dict[str, Any],
    rail_slot: int,
    rail_analysis: dict[str, Any],
    robot_base_z: float,
) -> list[float]:
    fit = rail_analysis["rail_fit"]
    x, y, z = [float(value) for value in point["pose"][:3]]
    p = np.array([x, y, z], dtype=float)
    l_axis = np.asarray(fit["l_axis_unit_in_controller_xyz"], dtype=float)
    n_axis = np.asarray(fit["n_axis_unit_in_controller_xyz"], dtype=float)
    q_values = rail_analysis["semantic_binding_provenance"]["rail_values"][
        "values_by_slot_mm"
    ]
    q = float(q_values[str(rail_slot)])
    reference_q = float(fit["common_frame_equation"]["reference_q_mm"])
    scale = float(fit["fitted_scale_mm_translation_per_mm_command"])
    l_value = float(np.dot(p, l_axis) + scale * (q - reference_q))
    n_value = float(np.dot(p, n_axis))
    return [l_value / 1000.0, n_value / 1000.0, robot_base_z + z / 1000.0]


def author_interaction_points(
    stage: Any,
    points_document: dict[str, Any],
    rail_analysis: dict[str, Any],
    robot_base_z: float,
) -> dict[str, Any]:
    from pxr import Gf, Sdf, UsdGeom

    points = point_records(points_document)
    direct_slots = rail_slot_map(rail_analysis)
    placed = 0
    placed_validated = 0
    record_scope = UsdGeom.Scope.Define(stage, "/World/InteractionPoints/Records")
    marker_scope = UsdGeom.Scope.Define(stage, "/World/InteractionPoints/Markers")
    del record_scope, marker_scope

    for index, point in enumerate(points):
        point_name = str(point["robot_name"])
        # USD prim identifiers may not start with a digit.
        identifier = f"point_{index:03d}_{safe_identifier(point_name)}"
        record_prim = stage.DefinePrim(
            f"/World/InteractionPoints/Records/{identifier}", "Scope"
        )
        record_prim.CreateAttribute("ptlc:pointName", Sdf.ValueTypeNames.String).Set(
            point_name
        )
        record_prim.CreateAttribute("ptlc:status", Sdf.ValueTypeNames.String).Set(
            str(point["status"])
        )
        record_prim.CreateAttribute("ptlc:workstation", Sdf.ValueTypeNames.String).Set(
            str(point["workstation"])
        )
        record_prim.CreateAttribute("ptlc:rawPose", Sdf.ValueTypeNames.DoubleArray).Set(
            [float(value) for value in point["pose"]]
        )
        if point.get("joint") is not None:
            record_prim.CreateAttribute(
                "ptlc:jointDegrees", Sdf.ValueTypeNames.DoubleArray
            ).Set([float(value) for value in point["joint"]])

        number = original_point_number(point_name)
        slot = direct_slots.get(number) if number is not None else None
        if slot is None and point.get("derived_from"):
            parent_number = original_point_number(str(point["derived_from"]))
            slot = direct_slots.get(parent_number) if parent_number is not None else None
        record_prim.CreateAttribute("ptlc:spatiallyPlaced", Sdf.ValueTypeNames.Bool).Set(
            slot is not None
        )
        if slot is None:
            continue
        position = marker_world_position(point, slot, rail_analysis, robot_base_z)
        record_prim.CreateAttribute("ptlc:railSlot", Sdf.ValueTypeNames.Int).Set(slot)
        record_prim.CreateAttribute(
            "ptlc:relativeConstraintPositionM", Sdf.ValueTypeNames.Double3
        ).Set(Gf.Vec3d(*position))
        sphere = UsdGeom.Sphere.Define(
            stage, f"/World/InteractionPoints/Markers/{identifier}"
        )
        sphere.CreateRadiusAttr(0.008 if point.get("is_derived") else 0.014)
        xform_pose(sphere, position, [0.0, 0.0, 0.0])
        color = (
            Gf.Vec3f(0.85, 0.15, 0.10)
            if point["status"] == "placeholder"
            else Gf.Vec3f(0.10, 0.75, 0.30)
            if not point.get("is_derived")
            else Gf.Vec3f(0.15, 0.45, 0.95)
        )
        UsdGeom.Gprim(sphere.GetPrim()).CreateDisplayColorAttr([color])
        placed += 1
        placed_validated += int(point["status"] == "validated")

    return {
        "record_count": len(points),
        "spatial_marker_count": placed,
        "spatial_validated_marker_count": placed_validated,
        "unplaced_record_count": len(points) - placed,
        "policy": (
            "Every point is stored as metadata; only points with an operation-semantic "
            "rail binding are placed in the relative constraint frame."
        ),
    }


def create_scene(
    workspace: Path,
    output_dir: Path,
    robot_usd: Path,
    input_report: dict[str, Any],
) -> tuple[Any, dict[str, Any], str]:
    import isaacsim.core.utils.stage as stage_utils
    from pxr import Gf, PhysxSchema, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics

    stage_utils.create_new_stage()
    stage = stage_utils.get_current_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    world.GetPrim().CreateAttribute(
        "ptlc:evidenceLevel", Sdf.ValueTypeNames.String
    ).Set("simulation_only_approximate_layout")
    world.GetPrim().CreateAttribute(
        "ptlc:hardwareConnections", Sdf.ValueTypeNames.String
    ).Set("none")

    physics_scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    physics_scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
    physics_scene.CreateGravityMagnitudeAttr(9.81)
    physx_scene = PhysxSchema.PhysxSceneAPI.Apply(physics_scene.GetPrim())
    physx_scene.CreateEnableGPUDynamicsAttr(False)
    physx_scene.CreateBroadphaseTypeAttr("MBP")

    light = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    light.CreateIntensityAttr(1200.0)

    layout = load_json(workspace / "pTLC仿真资产/layout_estimate.json")
    points_document = load_json(workspace / "pTLC仿真资产/interaction_points.json")
    rail_analysis = load_json(
        workspace / "pTLC仿真资产/rail_frame_layout_analysis.json"
    )
    proxy_report = author_proxy_assets(stage, workspace, layout)

    rail_slot = int(input_report["replay"]["rail_slot"])
    slot_positions = rail_analysis[
        "rail_carriage_l_positions_relative_to_reference"
    ]["positions_by_slot_mm"]
    rail_x = float(slot_positions[str(rail_slot)]) / 1000.0
    robot_base_z = float(layout["robot_placement"]["position_m"][2])
    robot_prim_path = "/World/RobotSystem/CR5"
    robot_xform = UsdGeom.Xform.Define(stage, robot_prim_path)
    robot_xform.GetPrim().GetReferences().AddReference(str(robot_usd))
    xform_pose(robot_xform, [rail_x, 0.0, robot_base_z], [0.0, 0.0, 180.0])
    robot_xform.GetPrim().CreateAttribute(
        "ptlc:railSlot", Sdf.ValueTypeNames.Int
    ).Set(rail_slot)
    robot_xform.GetPrim().CreateAttribute(
        "ptlc:geometryStatus", Sdf.ValueTypeNames.String
    ).Set("provisional CR5 skeleton for photographed CR5A")

    point_report = author_interaction_points(
        stage, points_document, rail_analysis, robot_base_z
    )
    scene_path = output_dir / "ptlc_scene.usda"
    stage.GetRootLayer().Export(str(scene_path))
    return (
        stage,
        {
            "scene_path": str(scene_path),
            "proxy_assets": proxy_report,
            "interaction_points": point_report,
            "robot": {
                "prim_path": robot_prim_path,
                "source_usd": str(robot_usd),
                "rail_slot": rail_slot,
                "position_m": [rail_x, 0.0, robot_base_z],
                "rpy_degrees": [0.0, 0.0, 180.0],
            },
        },
        robot_prim_path,
    )


async def capture_viewport(path: Path, eye: list[float], target: list[float]) -> dict[str, Any]:
    from isaacsim.core.rendering_manager import ViewportManager
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

    path.parent.mkdir(parents=True, exist_ok=True)
    ViewportManager.set_camera_view(
        camera="/OmniverseKit_Persp", eye=eye, target=target
    )
    ready, frames_waited = ViewportManager.wait_for_viewport(max_frames=120)
    viewport = get_active_viewport()
    if not ready or viewport is None:
        raise RuntimeError(
            f"Viewport was not ready: ready={ready}, viewport={viewport}"
        )
    await capture_viewport_to_file(
        viewport, file_path=str(path), is_hdr=False
    ).wait_for_result()
    for _ in range(4):
        await asyncio.sleep(0)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Screenshot was not created: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "frames_waited": frames_waited}


def install_contact_reporting(stage: Any, robot_prefix: str) -> tuple[Any, list[dict[str, Any]]]:
    from omni.physx import get_physx_simulation_interface
    from pxr import PhysxSchema, UsdPhysics

    for prim in stage.Traverse():
        if str(prim.GetPath()).startswith(robot_prefix) and prim.HasAPI(
            UsdPhysics.RigidBodyAPI
        ):
            api = PhysxSchema.PhysxContactReportAPI.Apply(prim)
            api.CreateThresholdAttr().Set(0.0)

    events: list[dict[str, Any]] = []

    def on_contacts(headers: Any, data: Any) -> None:
        from pxr import PhysicsSchemaTools

        for header in headers:
            actor0 = str(PhysicsSchemaTools.intToSdfPath(header.actor0))
            actor1 = str(PhysicsSchemaTools.intToSdfPath(header.actor1))
            collider0 = str(PhysicsSchemaTools.intToSdfPath(header.collider0))
            collider1 = str(PhysicsSchemaTools.intToSdfPath(header.collider1))
            samples = []
            begin = int(header.contact_data_offset)
            end = begin + int(header.num_contact_data)
            for index in range(begin, end):
                sample = data[index]
                samples.append(
                    {
                        "position": list(sample.position),
                        "normal": list(sample.normal),
                        "impulse": list(sample.impulse),
                        "separation": float(sample.separation),
                    }
                )
            events.append(
                {
                    "actor0": actor0,
                    "actor1": actor1,
                    "collider0": collider0,
                    "collider1": collider1,
                    "samples": samples,
                    "robot_environment": (
                        (actor0.startswith(robot_prefix) and not actor1.startswith(robot_prefix))
                        or (actor1.startswith(robot_prefix) and not actor0.startswith(robot_prefix))
                    ),
                    "robot_self": actor0.startswith(robot_prefix)
                    and actor1.startswith(robot_prefix),
                }
            )

    subscription = get_physx_simulation_interface().subscribe_contact_report_events(
        on_contacts
    )
    return subscription, events


def smooth_interpolation(q0: np.ndarray, q1: np.ndarray, count: int) -> np.ndarray:
    u = np.linspace(0.0, 1.0, count)
    blend = 3.0 * u**2 - 2.0 * u**3
    return q0[None, :] + blend[:, None] * (q1 - q0)[None, :]


def replay_joint_sequence(
    simulation_app: Any,
    stage: Any,
    robot_prim_path: str,
    input_report: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation

    world = World(stage_units_in_meters=1.0, backend="numpy", device="cpu")
    robot = world.scene.add(
        SingleArticulation(
            prim_path=robot_prim_path,
            name="ptlc_cr5",
            reset_xform_properties=False,
        )
    )
    world.reset()
    for _ in range(30):
        world.step(render=True)

    if robot.num_dof != 6:
        raise RuntimeError(f"Expected six CR5 DOFs, found {robot.num_dof}")
    dof_names = list(robot.dof_names)
    expected_names = [f"joint{index}" for index in range(1, 7)]
    if dof_names != expected_names:
        raise RuntimeError(f"Unexpected CR5 DOF order: {dof_names}")

    contact_subscription, contact_events = install_contact_reporting(
        stage, robot_prim_path
    )
    del contact_subscription
    # Keep a fresh subscription alive for the full replay.
    contact_subscription, contact_events = install_contact_reporting(
        stage, robot_prim_path
    )

    replay_points = input_report["replay"]["points"]
    q_targets = [
        np.asarray(record["joint_radians"], dtype=np.float64)
        for record in replay_points
    ]
    limits = robot.dof_properties
    lower = np.asarray(limits["lower"], dtype=float)
    upper = np.asarray(limits["upper"], dtype=float)
    max_step_rad = math.radians(1.0)

    robot.set_joint_positions(q_targets[0])
    for _ in range(5):
        world.step(render=True)
    screenshots = []
    first_path = output_dir / "screenshots/00_P63_initial.png"
    screenshots.append(
        asyncio.get_event_loop().run_until_complete(
            capture_viewport(first_path, [3.2, -3.8, 3.0], [0.2, 0.0, 0.9])
        )
    )

    segments = []
    frame_index = 0
    max_tracking_error_rad = 0.0
    samples_path = output_dir / "joint_samples.jsonl"
    with samples_path.open("w", encoding="utf-8") as samples_file:
        for segment_index, (start, end) in enumerate(
            zip(q_targets[:-1], q_targets[1:], strict=True)
        ):
            max_delta = float(np.max(np.abs(end - start)))
            sample_count = max(2, int(math.ceil(max_delta / max_step_rad)) + 1)
            segment_start_frame = frame_index
            for q_command in smooth_interpolation(start, end, sample_count):
                if np.any(q_command < lower) or np.any(q_command > upper):
                    raise RuntimeError("Interpolated command exceeded imported limits")
                # Quasi-static dense pose sweep: deterministic collision sampling,
                # not a calibrated dynamic controller reproduction.
                robot.set_joint_positions(q_command)
                world.step(render=True)
                q_measured = np.asarray(robot.get_joint_positions(), dtype=float)
                error = float(np.max(np.abs(q_measured - q_command)))
                max_tracking_error_rad = max(max_tracking_error_rad, error)
                sample = {
                    "frame": frame_index,
                    "segment": segment_index,
                    "command_rad": q_command.tolist(),
                    "measured_rad": q_measured.tolist(),
                    "max_error_rad": error,
                }
                samples_file.write(json.dumps(sample, ensure_ascii=False) + "\n")
                frame_index += 1
            segments.append(
                {
                    "from": replay_points[segment_index]["point"],
                    "to": replay_points[segment_index + 1]["point"],
                    "sample_count": sample_count,
                    "start_frame": segment_start_frame,
                    "end_frame": frame_index - 1,
                    "max_joint_delta_degrees": math.degrees(max_delta),
                }
            )
            screenshot_path = output_dir / (
                f"screenshots/{segment_index + 1:02d}_"
                f"{replay_points[segment_index + 1]['point']}.png"
            )
            screenshots.append(
                asyncio.get_event_loop().run_until_complete(
                    capture_viewport(
                        screenshot_path,
                        [3.2, -3.8, 3.0],
                        [0.2, 0.0, 0.9],
                    )
                )
            )

    final_positions = np.asarray(robot.get_joint_positions(), dtype=float)
    environment_contacts = [
        event for event in contact_events if event["robot_environment"]
    ]
    self_contacts = [event for event in contact_events if event["robot_self"]]
    scene_path = output_dir / "ptlc_scene_final.usda"
    stage.GetRootLayer().Export(str(scene_path))
    result = {
        "evidence_level": "isaac_sim_quasistatic_joint_pose_sweep",
        "passed": (
            max_tracking_error_rad <= math.radians(0.05)
            and not environment_contacts
            and not self_contacts
        ),
        "robot_prim_path": robot_prim_path,
        "dof_names": dof_names,
        "segments": segments,
        "frame_count": frame_index,
        "max_joint_sample_step_degrees": 1.0,
        "max_tracking_error_degrees": math.degrees(max_tracking_error_rad),
        "final_joint_radians": final_positions.tolist(),
        "final_target_error_degrees": np.rad2deg(
            np.abs(final_positions - q_targets[-1])
        ).tolist(),
        "contact_summary": {
            "all_events": len(contact_events),
            "robot_environment_events": len(environment_contacts),
            "robot_self_events": len(self_contacts),
        },
        "contact_events": contact_events[:500],
        "contact_events_truncated": len(contact_events) > 500,
        "screenshots": screenshots,
        "joint_samples_jsonl": str(samples_path),
        "final_scene": str(scene_path),
        "boundary": (
            "Dense kinematic pose sweep through recorded joint states. This tests "
            "sampled collision in the approximate scene; it is not MoveL, timing, "
            "torque, payload, suction, or real-device validation."
        ),
    }
    contact_subscription = None
    world.stop()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-index", type=int, default=1)
    parser.add_argument("--replay-point", action="append", dest="replay_points")
    args = parser.parse_args()
    require_authorization(args.gpu_index)

    workspace = args.workspace.resolve()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    replay_points = tuple(args.replay_points or DEFAULT_REPLAY_POINTS)
    input_report = validate_inputs(workspace, replay_points)
    write_json(output_dir / "input_validation.json", input_report)

    report: dict[str, Any] = {
        "schema_version": "ptlc.isaac.replay.v1",
        "started_at": now(),
        "status": "running",
        "authorization": {
            "eula_explicitly_accepted": True,
            "authorized_physical_gpu": 1,
            "hardware_connections": "none",
        },
        "requested_gpu_index": args.gpu_index,
        "gpu_before_start": gpu_snapshot(),
    }
    write_json(output_dir / "run_report.json", report)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "headless": True,
            "hide_ui": True,
            "active_gpu": args.gpu_index,
            "physics_gpu": physics_gpu_index(args.gpu_index),
            "multi_gpu": False,
            "max_gpu_count": 1,
            "extra_args": [
                "--/renderer/multiGpu/autoEnable=false",
                "--/renderer/multiGpu/enabled=false",
                "--/renderer/multiGpu/maxGpuCount=1",
            ],
            "sync_loads": True,
            "width": 1280,
            "height": 720,
        }
    )
    try:
        allocations = current_process_gpu_allocations()
        gpu_by_uuid = {record["uuid"]: record["index"] for record in gpu_snapshot()}
        allocation_indices = sorted(
            {gpu_by_uuid[item["gpu_uuid"]] for item in allocations}
        )
        if allocation_indices != [args.gpu_index]:
            raise RuntimeError(
                "Isaac process did not allocate exclusively on authorized GPU 1: "
                f"allocations={allocations}, indices={allocation_indices}"
            )
        report["current_process_gpu_allocations"] = allocations

        derived_urdf = derive_robot_urdf(workspace, output_dir)
        robot_usd = import_cr5(derived_urdf, output_dir, simulation_app)
        stage, scene_report, robot_prim_path = create_scene(
            workspace, output_dir, robot_usd, input_report
        )
        for _ in range(10):
            simulation_app.update()
        replay_report = replay_joint_sequence(
            simulation_app,
            stage,
            robot_prim_path,
            input_report,
            output_dir,
        )
        report.update(
            {
                "status": "passed" if replay_report["passed"] else "failed",
                "finished_at": now(),
                "derived_robot_urdf": str(derived_urdf),
                "robot_usd": str(robot_usd),
                "scene": scene_report,
                "replay": replay_report,
                "gpu_after_replay": gpu_snapshot(),
            }
        )
    except Exception as error:
        report.update(
            {
                "status": "error",
                "finished_at": now(),
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        )
        write_json(output_dir / "run_report.json", report)
        raise
    finally:
        write_json(output_dir / "run_report.json", report)
        gc.collect()
        simulation_app.close()
    print(output_dir / "run_report.json")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
