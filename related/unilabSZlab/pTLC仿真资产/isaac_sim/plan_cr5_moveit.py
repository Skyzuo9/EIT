#!/usr/bin/env python3
"""Plan P63 -> P76 -> P63 with the real MoveIt 2 OMPL pipeline.

The runner is headless and planning-only.  It loads the exact vendored CR5
URDF, a generated SRDF with the reviewed point states, and writes every MoveIt
trajectory waypoint for subsequent Isaac articulation/collision validation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


JOINT_NAMES = [f"joint{index}" for index in range(1, 7)]
DISABLED_COLLISIONS = (
    ("base_link", "Link1", "Adjacent"),
    ("base_link", "Link2", "Never"),
    ("base_link", "Link4", "Never"),
    ("Link1", "Link2", "Adjacent"),
    ("Link1", "Link4", "Never"),
    ("Link2", "Link3", "Adjacent"),
    ("Link3", "Link4", "Adjacent"),
    ("Link4", "Link5", "Adjacent"),
    ("Link4", "Link6", "Never"),
    ("Link5", "Link6", "Adjacent"),
)


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_targets(path: Path) -> dict[str, list[float]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    waypoints = document["targets"]["ptlc"]["waypoints"]
    targets = {name: [float(value) for value in record["value"]] for name, record in waypoints.items()}
    if set(targets) < {"P63", "P76"} or any(len(values) != 6 for values in targets.values()):
        raise ValueError("PointSet must contain six-axis P63 and P76 targets")
    return targets


def derive_urdf(source: Path, mesh_root: Path) -> str:
    root = ET.fromstring(source.read_bytes())
    for mesh in root.findall(".//mesh"):
        name = Path(mesh.attrib["filename"]).name
        resolved = (mesh_root / name).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Missing CR5 mesh: {resolved}")
        mesh.set("filename", resolved.as_uri())
    for index, name in enumerate(JOINT_NAMES):
        joint = root.find(f"joint[@name='{name}']")
        if joint is None:
            raise ValueError(f"CR5 URDF missing {name}")
        limit = joint.find("limit")
        if limit is None:
            raise ValueError(f"CR5 URDF missing limit for {name}")
        limit.set("effort", "150" if index < 3 else "30")
        limit.set("velocity", "3.14")
    return ET.tostring(root, encoding="unicode")


def build_srdf(targets: dict[str, list[float]]) -> str:
    root = ET.Element("robot", {"name": "cr5_robot"})
    group = ET.SubElement(root, "group", {"name": "cr5_arm"})
    ET.SubElement(group, "chain", {"base_link": "dummy_link", "tip_link": "Link6"})
    for state_name in ("P63", "P76"):
        state = ET.SubElement(root, "group_state", {"name": state_name, "group": "cr5_arm"})
        for joint_name, value in zip(JOINT_NAMES, targets[state_name], strict=True):
            ET.SubElement(state, "joint", {"name": joint_name, "value": repr(float(value))})
    for left, right, reason in DISABLED_COLLISIONS:
        ET.SubElement(
            root,
            "disable_collisions",
            {"link1": left, "link2": right, "reason": reason},
        )
    return ET.tostring(root, encoding="unicode")


def moveit_config(urdf: str, srdf: str) -> dict[str, Any]:
    joint_limits = {
        name: {
            "has_velocity_limits": True,
            "max_velocity": 3.14,
            "has_acceleration_limits": True,
            "max_acceleration": 2.0,
        }
        for name in JOINT_NAMES
    }
    return {
        "robot_description": urdf,
        "robot_description_semantic": srdf,
        "robot_description_kinematics": {
            "cr5_arm": {
                "kinematics_solver": "kdl_kinematics_plugin/KDLKinematicsPlugin",
                "kinematics_solver_search_resolution": 0.005,
                "kinematics_solver_timeout": 0.05,
            }
        },
        "robot_description_planning": {"joint_limits": joint_limits},
        "planning_scene_monitor_options": {
            "name": "planning_scene_monitor",
            "robot_description": "robot_description",
            "joint_state_topic": "/joint_states",
            "attached_collision_object_topic": "/moveit_cpp/planning_scene_monitor",
            "publish_planning_scene_topic": "/moveit_cpp/publish_planning_scene",
            "monitored_planning_scene_topic": "/moveit_cpp/monitored_planning_scene",
            "wait_for_initial_state_timeout": 0.0,
        },
        # MoveItCpp/MoveItPy uses this nested selector, while the pipeline's
        # plugin parameters remain in the top-level ``ompl`` namespace below.
        "planning_pipelines": {"pipeline_names": ["ompl"]},
        "ompl": {
            "planning_plugins": ["ompl_interface/OMPLPlanner"],
            "request_adapters": [
                "default_planning_request_adapters/ResolveConstraintFrames",
                "default_planning_request_adapters/ValidateWorkspaceBounds",
                "default_planning_request_adapters/CheckStartStateBounds",
                "default_planning_request_adapters/CheckStartStateCollision",
            ],
            "response_adapters": [
                "default_planning_response_adapters/AddTimeOptimalParameterization",
                "default_planning_response_adapters/ValidateSolution",
            ],
            "start_state_max_bounds_error": 0.1,
            "planner_configs": {
                "RRTConnectkConfigDefault": {
                    "type": "geometric::RRTConnect",
                    "range": 0.0,
                }
            },
            "cr5_arm": {
                "planner_configs": ["RRTConnectkConfigDefault"],
                "projection_evaluator": "joints(joint1,joint2)",
                "longest_valid_segment_fraction": 0.005,
            },
        },
        "plan_request_params": {
            "planning_attempts": 5,
            "planning_pipeline": "ompl",
            "planner_id": "RRTConnectkConfigDefault",
            "planning_time": 10.0,
            "max_velocity_scaling_factor": 0.2,
            "max_acceleration_scaling_factor": 0.2,
        },
    }


def point_to_dict(point: Any) -> dict[str, Any]:
    duration = point.time_from_start
    return {
        "positions": [float(value) for value in point.positions],
        "velocities": [float(value) for value in point.velocities],
        "accelerations": [float(value) for value in point.accelerations],
        "time_from_start_s": float(duration.sec) + float(duration.nanosec) / 1_000_000_000.0,
    }


def check_state_collision(scene: Any, state: Any, positions: list[float]) -> bool:
    state.set_joint_group_positions("cr5_arm", positions)
    state.update()
    return bool(
        scene.is_state_colliding(
            robot_state=state,
            joint_model_group_name="cr5_arm",
            verbose=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urdf", type=Path, required=True)
    parser.add_argument("--mesh-root", type=Path, required=True)
    parser.add_argument("--point-set", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "moveit_plan_report.json"
    targets = load_targets(args.point_set)
    urdf = derive_urdf(args.urdf, args.mesh_root)
    srdf = build_srdf(targets)
    (output / "cr5_moveit.urdf").write_text(urdf + "\n", encoding="utf-8")
    (output / "cr5_moveit.srdf").write_text(srdf + "\n", encoding="utf-8")
    report: dict[str, Any] = {
        "schema_version": "ptlc.moveit-plan.v1",
        "started_at": timestamp(),
        "status": "running",
        "moveit_runtime": "ROS 2 Jazzy / MoveIt 2 / OMPL",
        "planner_id": "RRTConnectkConfigDefault",
        "group": "cr5_arm",
        "urdf_source": str(args.urdf.resolve()),
        "urdf_source_sha256": sha256(args.urdf.resolve()),
        "point_set": str(args.point_set.resolve()),
        "point_set_sha256": sha256(args.point_set.resolve()),
        "hardware_connections": "none",
        "boundary": (
            "Headless MoveIt self-collision planning with the CR5 model. The approximate "
            "pTLC environment collision meshes are validated separately by Isaac PhysX."
        ),
    }
    write_json(report_path, report)

    robot = None
    try:
        import rclpy
        from moveit.core.robot_state import RobotState
        from moveit.planning import MoveItPy

        rclpy.init()
        robot = MoveItPy(node_name="ptlc_cr5_moveit_planner", config_dict=moveit_config(urdf, srdf))
        component = robot.get_planning_component("cr5_arm")
        scene_monitor = robot.get_planning_scene_monitor()
        model = robot.get_robot_model()
        collision_state = RobotState(model)

        segments = []
        all_waypoints: list[list[float]] = []
        for start_name, goal_name in (("P63", "P76"), ("P76", "P63")):
            component.set_start_state(configuration_name=start_name)
            component.set_goal_state(configuration_name=goal_name)
            result = component.plan()
            if not result:
                raise RuntimeError(f"MoveIt planning failed: {start_name}->{goal_name}")
            trajectory_message = result.trajectory.get_robot_trajectory_msg(JOINT_NAMES)
            trajectory = trajectory_message.joint_trajectory
            points = [point_to_dict(point) for point in trajectory.points]
            if len(points) < 2:
                raise RuntimeError(f"MoveIt returned too few waypoints: {start_name}->{goal_name}")
            collision_flags = []
            with scene_monitor.read_only() as scene:
                for point in points:
                    collision_flags.append(check_state_collision(scene, collision_state, point["positions"]))
            endpoint_error = max(
                abs(actual - expected)
                for actual, expected in zip(points[-1]["positions"], targets[goal_name], strict=True)
            )
            segments.append(
                {
                    "from": start_name,
                    "to": goal_name,
                    "joint_names": list(trajectory.joint_names),
                    "waypoint_count": len(points),
                    "duration_s": points[-1]["time_from_start_s"],
                    "goal_max_error_rad": endpoint_error,
                    "self_collision_waypoints": sum(collision_flags),
                    "points": points,
                }
            )
            all_waypoints.extend(point["positions"] for point in points)

        passed = all(
            segment["waypoint_count"] >= 2
            and segment["goal_max_error_rad"] <= 1e-5
            and segment["self_collision_waypoints"] == 0
            for segment in segments
        )
        report.update(
            {
                "finished_at": timestamp(),
                "status": "passed" if passed else "failed",
                "segments": segments,
                "isaac_waypoints": all_waypoints,
                "gates": {
                    "moveit_plan_returned": all(segment["waypoint_count"] >= 2 for segment in segments),
                    "goal_endpoints_match": all(segment["goal_max_error_rad"] <= 1e-5 for segment in segments),
                    "moveit_self_collision_free": all(segment["self_collision_waypoints"] == 0 for segment in segments),
                },
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
        write_json(report_path, report)
        if robot is not None:
            shutdown = getattr(robot, "shutdown", None)
            if callable(shutdown):
                shutdown()
    print(report_path)
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
