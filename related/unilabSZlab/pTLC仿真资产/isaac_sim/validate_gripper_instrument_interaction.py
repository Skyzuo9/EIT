#!/usr/bin/env python3
"""Run a contact-gated gripper/object/instrument-port interaction in pTLC.

The validation fixture is added to a derived copy of the existing stage. Two
kinematic jaws must first contact a dynamic vial. A fixed attachment is then
enabled, the vial is transported, released under gravity, and required to
contact and settle in a static receiver. This is representative simulated
interaction, not evidence for a particular real gripper or instrument.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any


ROOT = "/World/InteractionValidation"
PALM = f"{ROOT}/GripperPalm"
LEFT_JAW = f"{ROOT}/LeftJaw"
RIGHT_JAW = f"{ROOT}/RightJaw"
VIAL = f"{ROOT}/DynamicVial"
RECEIVER_PREFIX = f"{ROOT}/InstrumentReceiver"


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_authorization_and_idle_gpu() -> None:
    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower() not in {"1", "y", "yes"}:
        raise RuntimeError("Explicit NVIDIA Omniverse EULA acceptance is required")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "1":
        raise RuntimeError("This validation is authorized only on physical GPU 1")
    result = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            "1",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "nvidia-smi GPU gate failed")
    if result.stdout.strip():
        raise RuntimeError("Physical GPU 1 is occupied; refusing to start:\n" + result.stdout.strip())


def add_cube(
    stage: Any,
    path: str,
    position: tuple[float, float, float],
    half_extents: tuple[float, float, float],
    color: tuple[float, float, float],
    *,
    dynamic: bool = False,
    kinematic: bool = False,
    mass: float = 1.0,
) -> Any:
    from pxr import Gf, UsdGeom, UsdPhysics

    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(2.0)
    api = UsdGeom.XformCommonAPI(cube)
    api.SetTranslate(Gf.Vec3d(*position))
    api.SetScale(Gf.Vec3f(*half_extents))
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    if dynamic:
        body = UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())
        body.CreateKinematicEnabledAttr(bool(kinematic))
        UsdPhysics.MassAPI.Apply(cube.GetPrim()).CreateMassAttr(float(mass))
    return cube


def add_vial(stage: Any, position: tuple[float, float, float]) -> Any:
    from pxr import Gf, UsdGeom, UsdPhysics

    cylinder = UsdGeom.Cylinder.Define(stage, VIAL)
    cylinder.CreateAxisAttr("Z")
    cylinder.CreateRadiusAttr(0.04)
    cylinder.CreateHeightAttr(0.16)
    UsdGeom.XformCommonAPI(cylinder).SetTranslate(Gf.Vec3d(*position))
    cylinder.CreateDisplayColorAttr([Gf.Vec3f(0.15, 0.70, 0.90)])
    UsdPhysics.CollisionAPI.Apply(cylinder.GetPrim())
    body = UsdPhysics.RigidBodyAPI.Apply(cylinder.GetPrim())
    body.CreateKinematicEnabledAttr(False)
    UsdPhysics.MassAPI.Apply(cylinder.GetPrim()).CreateMassAttr(0.12)
    return cylinder


def set_position(geom: Any, position: tuple[float, float, float]) -> None:
    from pxr import Gf, UsdGeom

    UsdGeom.XformCommonAPI(geom).SetTranslate(Gf.Vec3d(*position))


def world_position(prim: Any) -> list[float]:
    from pxr import Usd, UsdGeom

    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    return [float(value) for value in matrix.ExtractTranslation()]


def install_contact_reporting(stage: Any) -> tuple[Any, list[dict[str, Any]]]:
    from omni.physx import get_physx_simulation_interface
    from pxr import PhysxSchema, UsdPhysics

    monitored = (LEFT_JAW, RIGHT_JAW, VIAL)
    for path in monitored:
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid() or not prim.HasAPI(UsdPhysics.RigidBodyAPI):
            raise RuntimeError(f"Missing monitored rigid body: {path}")
        PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr().Set(0.0)

    events: list[dict[str, Any]] = []

    def on_contacts(headers: Any, data: Any) -> None:
        from pxr import PhysicsSchemaTools

        for header in headers:
            actor0 = str(PhysicsSchemaTools.intToSdfPath(header.actor0))
            actor1 = str(PhysicsSchemaTools.intToSdfPath(header.actor1))
            collider0 = str(PhysicsSchemaTools.intToSdfPath(header.collider0))
            collider1 = str(PhysicsSchemaTools.intToSdfPath(header.collider1))
            impulses = []
            begin = int(header.contact_data_offset)
            for index in range(begin, begin + int(header.num_contact_data)):
                impulses.append([float(value) for value in data[index].impulse])
            events.append(
                {
                    "actor0": actor0,
                    "actor1": actor1,
                    "collider0": collider0,
                    "collider1": collider1,
                    "impulses": impulses,
                }
            )

    subscription = get_physx_simulation_interface().subscribe_contact_report_events(on_contacts)
    return subscription, events


def pair_matches(event: dict[str, Any], first: str, second_prefix: str) -> bool:
    values = {event["actor0"], event["actor1"], event["collider0"], event["collider1"]}
    return first in values and any(value.startswith(second_prefix) for value in values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_authorization_and_idle_gpu()

    scene = args.scene.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "gripper_instrument_interaction_report.json"
    report: dict[str, Any] = {
        "schema_version": "ptlc.isaac-contact-interaction.v1",
        "started_at": timestamp(),
        "status": "running",
        "scene": str(scene),
        "authorized_physical_gpu": 1,
        "hardware_connections": "none",
        "interaction_model": "two-jaw contact plus contact-gated fixed attachment",
        "boundary": (
            "Representative PhysX interaction added to the approximate pTLC stage. "
            "It verifies contact, rigid-body transport, release, gravity, and receiver "
            "collision; it does not validate frictional grasp stability, a vendor gripper, "
            "a real vial, or a real instrument interface."
        ),
    }
    write_json(report_path, report)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "headless": True,
            "active_gpu": 1,
            "physics_gpu": 0,
            "multi_gpu": False,
            "width": 960,
            "height": 540,
            "extra_args": [
                "--/renderer/multiGpu/autoEnable=false",
                "--/renderer/multiGpu/enabled=false",
                "--/renderer/multiGpu/maxGpuCount=1",
                "--/isaac/startup/ros_bridge_extension=",
            ],
        }
    )
    subscription = None
    world = None
    try:
        import isaacsim.core.utils.stage as stage_utils
        from isaacsim.core.api import World
        from pxr import Gf, Sdf, UsdGeom, UsdPhysics

        if not stage_utils.open_stage(str(scene)):
            raise RuntimeError(f"Could not open stage: {scene}")
        for _ in range(30):
            simulation_app.update()
        stage = stage_utils.get_current_stage()
        if stage.GetPrimAtPath(ROOT).IsValid():
            stage.RemovePrim(ROOT)
        UsdGeom.Xform.Define(stage, ROOT)

        add_cube(stage, f"{ROOT}/Platform", (2.0, -0.9, 0.55), (0.55, 0.32, 0.04), (0.25, 0.25, 0.28))
        add_cube(stage, f"{ROOT}/PickupPad", (1.78, -0.9, 0.63), (0.13, 0.13, 0.04), (0.35, 0.35, 0.38))
        add_cube(stage, f"{RECEIVER_PREFIX}/Floor", (2.25, -0.9, 0.63), (0.13, 0.13, 0.025), (0.20, 0.60, 0.25))
        add_cube(stage, f"{RECEIVER_PREFIX}/WallXMinus", (2.105, -0.9, 0.75), (0.015, 0.145, 0.12), (0.20, 0.60, 0.25))
        add_cube(stage, f"{RECEIVER_PREFIX}/WallXPlus", (2.395, -0.9, 0.75), (0.015, 0.145, 0.12), (0.20, 0.60, 0.25))
        add_cube(stage, f"{RECEIVER_PREFIX}/WallYMinus", (2.25, -1.045, 0.75), (0.145, 0.015, 0.12), (0.20, 0.60, 0.25))
        add_cube(stage, f"{RECEIVER_PREFIX}/WallYPlus", (2.25, -0.755, 0.75), (0.145, 0.015, 0.12), (0.20, 0.60, 0.25))

        palm = add_cube(stage, PALM, (1.78, -0.9, 0.98), (0.10, 0.08, 0.04), (0.80, 0.35, 0.10), dynamic=True, kinematic=True, mass=0.8)
        left = add_cube(stage, LEFT_JAW, (1.78, -0.80, 0.78), (0.055, 0.015, 0.10), (0.85, 0.45, 0.10), dynamic=True, kinematic=True, mass=0.2)
        right = add_cube(stage, RIGHT_JAW, (1.78, -1.00, 0.78), (0.055, 0.015, 0.10), (0.85, 0.45, 0.10), dynamic=True, kinematic=True, mass=0.2)
        vial = add_vial(stage, (1.78, -0.9, 0.75))

        joint = UsdPhysics.FixedJoint.Define(stage, f"{ROOT}/ContactGatedAttachment")
        joint.CreateBody0Rel().SetTargets([Sdf.Path(PALM)])
        joint.CreateBody1Rel().SetTargets([Sdf.Path(VIAL)])
        joint.CreateLocalPos0Attr(Gf.Vec3f(0.0, 0.0, -0.23))
        joint.CreateLocalPos1Attr(Gf.Vec3f(0.0, 0.0, 0.0))
        joint.CreateJointEnabledAttr(False)

        world = World(stage_units_in_meters=1.0, backend="numpy", device="cpu")
        world.reset()
        subscription, contacts = install_contact_reporting(stage)
        for _ in range(90):
            world.step(render=False)
        initial_position = world_position(vial.GetPrim())

        # Close the two jaws. The attachment is forbidden until a vial/jaw
        # contact has been observed by the PhysX contact-report stream.
        for step in range(80):
            alpha = (step + 1) / 80.0
            offset = 0.10 + alpha * (0.055 - 0.10)
            set_position(left, (1.78, -0.9 + offset, 0.78))
            set_position(right, (1.78, -0.9 - offset, 0.78))
            world.step(render=False)
        jaw_contacts = [
            event
            for event in contacts
            if pair_matches(event, VIAL, LEFT_JAW) or pair_matches(event, VIAL, RIGHT_JAW)
        ]
        if not jaw_contacts:
            raise RuntimeError("No PhysX jaw/vial contact; attachment remains disabled")

        joint.CreateJointEnabledAttr(True)
        for _ in range(20):
            world.step(render=False)
        trajectory = []
        for step in range(180):
            alpha = (step + 1) / 180.0
            x = 1.78 + 0.47 * alpha
            # Finish 10 cm above the pickup height so release produces a
            # measurable gravity-driven fall into the receiver, while the
            # parabolic term provides clearance during transport.
            z = 0.98 + 0.10 * alpha + 0.28 * 4.0 * alpha * (1.0 - alpha)
            set_position(palm, (x, -0.9, z))
            set_position(left, (x, -0.845, z - 0.20))
            set_position(right, (x, -0.955, z - 0.20))
            world.step(render=False)
            if step % 10 == 0:
                trajectory.append(world_position(vial.GetPrim()))

        pre_release_position = world_position(vial.GetPrim())
        joint.CreateJointEnabledAttr(False)
        set_position(left, (2.25, -0.78, 0.78))
        set_position(right, (2.25, -1.02, 0.78))
        release_positions = []
        for step in range(240):
            world.step(render=False)
            if step % 10 == 0:
                release_positions.append(world_position(vial.GetPrim()))
        final_position = world_position(vial.GetPrim())

        receiver_contacts = [
            event for event in contacts if pair_matches(event, VIAL, RECEIVER_PREFIX)
        ]
        max_lift = max(position[2] for position in trajectory) - initial_position[2]
        transferred = pre_release_position[0] - initial_position[0]
        final_in_receiver_xy = abs(final_position[0] - 2.25) <= 0.12 and abs(final_position[1] + 0.9) <= 0.12
        settled_motion = (
            max(
                abs(release_positions[-1][index] - release_positions[-2][index])
                for index in range(3)
            )
            if len(release_positions) >= 2
            else float("inf")
        )
        gates = {
            "jaw_vial_contact": len(jaw_contacts) > 0,
            "lifted_under_attachment": max_lift >= 0.12,
            "transferred_to_receiver": transferred >= 0.35,
            "released_under_gravity": final_position[2] < pre_release_position[2] - 0.08,
            "receiver_contact": len(receiver_contacts) > 0,
            "settled_in_receiver": final_in_receiver_xy and settled_motion <= 0.01,
        }
        passed = all(gates.values())
        derived_stage = output / "ptlc_interaction_validation.usda"
        stage.GetRootLayer().Export(str(derived_stage))
        report.update(
            {
                "finished_at": timestamp(),
                "status": "passed" if passed else "failed",
                "gates": gates,
                "measurements": {
                    "initial_vial_position_m": initial_position,
                    "pre_release_position_m": pre_release_position,
                    "final_vial_position_m": final_position,
                    "max_lift_m": max_lift,
                    "x_transfer_m": transferred,
                    "settled_position_delta_per_10_steps_m": settled_motion,
                    "jaw_vial_contact_events": len(jaw_contacts),
                    "vial_receiver_contact_events": len(receiver_contacts),
                },
                "transport_samples_m": trajectory,
                "release_samples_m": release_positions,
                "contact_events": contacts[:500],
                "contact_events_truncated": len(contacts) > 500,
                "derived_stage": str(derived_stage),
            }
        )
    except Exception as exc:
        report.update(
            {
                "finished_at": timestamp(),
                "status": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        raise
    finally:
        subscription = None
        if world is not None:
            world.stop()
        write_json(report_path, report)
        simulation_app.close()
    print(report_path)
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
