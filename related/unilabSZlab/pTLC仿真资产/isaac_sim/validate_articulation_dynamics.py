#!/usr/bin/env python3
"""Validate CR5 articulation drives and sampled contacts in the pTLC stage.

This runner advances PhysX normally and commands position drives through the
Isaac articulation controller.  It deliberately does not use
``set_joint_positions`` inside a segment, so a passing result demonstrates
time-stepped rigid-body articulation rather than geometry animation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any

import numpy as np


ROBOT_PATH = "/World/RobotSystem/CR5"
EXPECTED_DOF_NAMES = [f"joint{index}" for index in range(1, 7)]


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_authorization() -> None:
    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower() not in {"1", "y", "yes"}:
        raise RuntimeError("Explicit NVIDIA Omniverse EULA acceptance is required")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "1":
        raise RuntimeError("This validation is authorized only on physical GPU 1")


def require_idle_gpu() -> None:
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


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_targets(path: Path) -> dict[str, np.ndarray]:
    document = json.loads(path.read_text(encoding="utf-8"))
    waypoints = document["targets"]["ptlc"]["waypoints"]
    result = {
        name: np.asarray(record["value"], dtype=np.float64)
        for name, record in waypoints.items()
    }
    if set(result) < {"P63", "P76"} or any(value.shape != (6,) for value in result.values()):
        raise ValueError("PointSet must contain six-axis P63 and P76 targets")
    return result


def load_moveit_plan(path: Path, targets: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("status") != "passed":
        raise ValueError("MoveIt report has not passed")
    segments = document.get("segments", [])
    if len(segments) != 2:
        raise ValueError("MoveIt report must contain P63->P76 and P76->P63")
    expected_pairs = (("P63", "P76"), ("P76", "P63"))
    result = []
    for segment, expected_pair in zip(segments, expected_pairs, strict=True):
        if (segment.get("from"), segment.get("to")) != expected_pair:
            raise ValueError(f"Unexpected MoveIt segment: {segment.get('from')}->{segment.get('to')}")
        if segment.get("joint_names") != EXPECTED_DOF_NAMES:
            raise ValueError(f"Unexpected MoveIt joint order: {segment.get('joint_names')}")
        points = segment.get("points", [])
        if len(points) < 2:
            raise ValueError(f"MoveIt segment {expected_pair} has too few points")
        parsed_points = []
        previous_time = -1.0
        for point in points:
            positions = np.asarray(point["positions"], dtype=np.float64)
            point_time = float(point["time_from_start_s"])
            if positions.shape != (6,) or point_time < previous_time:
                raise ValueError(f"Invalid MoveIt waypoint in {expected_pair}")
            parsed_points.append({"positions": positions, "time_from_start_s": point_time})
            previous_time = point_time
        endpoint_error = float(np.max(np.abs(parsed_points[-1]["positions"] - targets[expected_pair[1]])))
        if endpoint_error > 1e-5:
            raise ValueError(f"MoveIt endpoint mismatch in {expected_pair}: {endpoint_error}")
        result.append(
            {
                "from": expected_pair[0],
                "to": expected_pair[1],
                "points": parsed_points,
                "duration_s": previous_time,
            }
        )
    return result


def install_contact_reporting(stage: Any) -> tuple[Any, list[dict[str, Any]]]:
    from omni.physx import get_physx_simulation_interface
    from pxr import PhysxSchema, UsdPhysics

    for prim in stage.Traverse():
        if str(prim.GetPath()).startswith(ROBOT_PATH) and prim.HasAPI(UsdPhysics.RigidBodyAPI):
            PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr().Set(0.0)

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
            for index in range(begin, begin + int(header.num_contact_data)):
                sample = data[index]
                samples.append(
                    {
                        "position": [float(value) for value in sample.position],
                        "normal": [float(value) for value in sample.normal],
                        "impulse": [float(value) for value in sample.impulse],
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
                        actor0.startswith(ROBOT_PATH) != actor1.startswith(ROBOT_PATH)
                    ),
                    "robot_self": actor0.startswith(ROBOT_PATH) and actor1.startswith(ROBOT_PATH),
                }
            )

    subscription = get_physx_simulation_interface().subscribe_contact_report_events(on_contacts)
    return subscription, events


def follow_moveit_segment(
    *,
    world: Any,
    robot: Any,
    controller: Any,
    plan_segment: dict[str, Any],
    segment_name: str,
    sample_stream: Any,
    max_steps: int,
    tolerance_rad: float,
) -> dict[str, Any]:
    from isaacsim.core.utils.types import ArticulationAction

    points = plan_segment["points"]
    target = points[-1]["positions"]
    start = np.asarray(robot.get_joint_positions(), dtype=np.float64)
    initial_error = float(np.max(np.abs(start - target)))
    max_velocity = 0.0
    max_command_tracking_error = 0.0
    converged_step: int | None = None
    final = start.copy()
    samples = 0
    physics_dt = float(world.get_physics_dt())
    executed_steps = 0

    # Track the time-parameterized MoveIt path. Interpolation prevents the
    # articulation drive target from jumping between 100 ms plan samples.
    for point_index in range(1, len(points)):
        previous = points[point_index - 1]
        current = points[point_index]
        interval = max(physics_dt, current["time_from_start_s"] - previous["time_from_start_s"])
        interval_steps = max(1, int(round(interval / physics_dt)))
        for interval_step in range(interval_steps):
            alpha = (interval_step + 1) / interval_steps
            command = previous["positions"] + alpha * (current["positions"] - previous["positions"])
            controller.apply_action(ArticulationAction(joint_positions=command))
            world.step(render=False)
            executed_steps += 1
            final = np.asarray(robot.get_joint_positions(), dtype=np.float64)
            velocity = np.asarray(robot.get_joint_velocities(), dtype=np.float64)
            tracking_error = float(np.max(np.abs(final - command)))
            max_command_tracking_error = max(max_command_tracking_error, tracking_error)
            max_velocity = max(max_velocity, float(np.max(np.abs(velocity))))
            if executed_steps % 5 == 0:
                sample_stream.write(
                    json.dumps(
                        {
                            "segment": segment_name,
                            "phase": "moveit_path",
                            "physics_step": executed_steps,
                            "moveit_point_index": point_index,
                            "positions_rad": final.tolist(),
                            "command_positions_rad": command.tolist(),
                            "velocities_rad_s": velocity.tolist(),
                            "max_command_tracking_error_rad": tracking_error,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                samples += 1

    for settle_step in range(max_steps):
        controller.apply_action(ArticulationAction(joint_positions=target))
        world.step(render=False)
        executed_steps += 1
        final = np.asarray(robot.get_joint_positions(), dtype=np.float64)
        velocity = np.asarray(robot.get_joint_velocities(), dtype=np.float64)
        error = float(np.max(np.abs(final - target)))
        max_command_tracking_error = max(max_command_tracking_error, error)
        max_velocity = max(max_velocity, float(np.max(np.abs(velocity))))
        if settle_step % 5 == 0 or error <= tolerance_rad:
            sample_stream.write(
                json.dumps(
                    {
                        "segment": segment_name,
                        "phase": "endpoint_settle",
                        "physics_step": executed_steps,
                        "settle_step": settle_step,
                        "positions_rad": final.tolist(),
                        "velocities_rad_s": velocity.tolist(),
                        "max_target_error_rad": error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            samples += 1
        if error <= tolerance_rad:
            converged_step = settle_step
            break

    final_error = float(np.max(np.abs(final - target)))
    joint_displacement = np.abs(final - start)
    return {
        "segment": segment_name,
        "initial_error_rad": initial_error,
        "final_error_rad": final_error,
        "converged": converged_step is not None,
        "endpoint_settle_step": converged_step,
        "physics_steps": executed_steps,
        "moveit_waypoints": len(points),
        "moveit_duration_s": float(plan_segment["duration_s"]),
        "recorded_samples": samples,
        "max_abs_velocity_rad_s": max_velocity,
        "max_command_tracking_error_rad": max_command_tracking_error,
        "max_abs_joint_displacement_rad": float(np.max(joint_displacement)),
        "final_positions_rad": final.tolist(),
        "target_positions_rad": target.tolist(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--point-set", type=Path, required=True)
    parser.add_argument("--moveit-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, default=900)
    parser.add_argument("--tolerance-deg", type=float, default=1.0)
    args = parser.parse_args()

    require_authorization()
    require_idle_gpu()
    if args.max_steps < 60 or not 0.05 <= args.tolerance_deg <= 5.0:
        raise ValueError("Invalid dynamics convergence limits")
    scene = args.scene.resolve()
    point_set = args.point_set.resolve()
    moveit_plan = args.moveit_plan.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets = load_targets(point_set)
    plan_segments = load_moveit_plan(moveit_plan, targets)
    tolerance_rad = math.radians(args.tolerance_deg)
    report: dict[str, Any] = {
        "schema_version": "ptlc.isaac-articulation-dynamics.v1",
        "started_at": timestamp(),
        "status": "running",
        "scene": str(scene),
        "scene_sha256": sha256(scene),
        "point_set": str(point_set),
        "point_set_sha256": sha256(point_set),
        "moveit_plan": str(moveit_plan),
        "moveit_plan_sha256": sha256(moveit_plan),
        "moveit_waypoint_count": sum(len(segment["points"]) for segment in plan_segments),
        "authorized_physical_gpu": 1,
        "hardware_connections": "none",
        "boundary": (
            "Isaac PhysX articulation-drive validation in the approximate pTLC stage. "
            "It is not real-robot, calibrated payload, torque, or controller-timing evidence."
        ),
    }
    report_path = output / "articulation_dynamics_report.json"
    write_json(report_path, report)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "headless": True,
            "active_gpu": 1,
            "physics_gpu": 0,
            "multi_gpu": False,
            "extra_args": [
                "--/renderer/multiGpu/autoEnable=false",
                "--/renderer/multiGpu/enabled=false",
                "--/renderer/multiGpu/maxGpuCount=1",
                "--/isaac/startup/ros_bridge_extension=",
            ],
        }
    )
    contact_subscription = None
    world = None
    try:
        import isaacsim.core.utils.stage as stage_utils
        from isaacsim.core.api import World
        from isaacsim.core.prims import SingleArticulation

        if not stage_utils.open_stage(str(scene)):
            raise RuntimeError(f"Could not open stage: {scene}")
        for _ in range(30):
            simulation_app.update()
        stage = stage_utils.get_current_stage()
        world = World(stage_units_in_meters=1.0, backend="numpy", device="cpu")
        robot = world.scene.add(
            SingleArticulation(
                prim_path=ROBOT_PATH,
                name="ptlc_cr5_dynamics",
                reset_xform_properties=False,
            )
        )
        world.reset()
        if robot.num_dof != 6 or list(robot.dof_names) != EXPECTED_DOF_NAMES:
            raise RuntimeError(f"Unexpected articulation DOFs: {robot.num_dof}, {robot.dof_names}")

        # Initial placement is setup only. All evidence-bearing segment motion below
        # is performed by the position drives while PhysX advances in time.
        robot.set_joint_positions(plan_segments[0]["points"][0]["positions"])
        robot.set_joint_velocities(np.zeros(6, dtype=np.float64))
        for _ in range(30):
            world.step(render=False)
        contact_subscription, contact_events = install_contact_reporting(stage)
        controller = robot.get_articulation_controller()
        samples_path = output / "articulation_samples.jsonl"
        segments = []
        with samples_path.open("w", encoding="utf-8") as sample_stream:
            for plan_segment in plan_segments:
                segments.append(
                    follow_moveit_segment(
                        world=world,
                        robot=robot,
                        controller=controller,
                        plan_segment=plan_segment,
                        segment_name=f"{plan_segment['from']}_to_{plan_segment['to']}",
                        sample_stream=sample_stream,
                        max_steps=args.max_steps,
                        tolerance_rad=tolerance_rad,
                    )
                )

        environment_contacts = [event for event in contact_events if event["robot_environment"]]
        self_contacts = [event for event in contact_events if event["robot_self"]]
        dynamics_passed = all(
            segment["converged"]
            and segment["initial_error_rad"] > 0.1
            and segment["max_abs_joint_displacement_rad"] > 0.1
            and segment["max_abs_velocity_rad_s"] > 1e-3
            for segment in segments
        )
        collision_passed = not environment_contacts and not self_contacts
        report.update(
            {
                "finished_at": timestamp(),
                "status": "passed" if dynamics_passed and collision_passed else "failed",
                "dof_names": list(robot.dof_names),
                "physics_dt_s": float(world.get_physics_dt()),
                "tolerance_degrees": args.tolerance_deg,
                "segments": segments,
                "dynamics_gate": {"passed": dynamics_passed},
                "collision_gate": {
                    "passed": collision_passed,
                    "robot_environment_events": len(environment_contacts),
                    "robot_self_events": len(self_contacts),
                    "sampled_path_scope": "exact MoveIt P63->P76->P63 waypoint trajectory tracked by articulation drives",
                },
                "contact_events": contact_events[:500],
                "contact_events_truncated": len(contact_events) > 500,
                "joint_samples_jsonl": str(samples_path),
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
        contact_subscription = None
        if world is not None:
            world.stop()
        write_json(report_path, report)
        simulation_app.close()
    print(report_path)
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
