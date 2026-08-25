#!/usr/bin/env python3
"""Validate the pTLC Isaac Sim replay inputs without importing Isaac Sim."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_REPLAY_POINTS = ("P63", "P76", "P63")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def robot_points(points_document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        point
        for group in points_document["data"]["robot"]["groups"]
        for point in group["points"]
    ]


def urdf_joint_limits(urdf_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(urdf_path).getroot()
    limits: list[dict[str, Any]] = []
    for joint in root.findall("joint"):
        joint_type = joint.get("type", "fixed")
        if joint_type not in {"revolute", "continuous", "prismatic"}:
            continue
        limit = joint.find("limit")
        if limit is None:
            raise ValueError(f"Joint {joint.get('name')} has no limit element")
        limits.append(
            {
                "name": joint.get("name"),
                "type": joint_type,
                "lower": float(limit.get("lower", "-inf")),
                "upper": float(limit.get("upper", "inf")),
                "velocity": float(limit.get("velocity", "inf")),
            }
        )
    return limits


def original_point_number(point: dict[str, Any]) -> int | None:
    name = str(point.get("robot_name", ""))
    if name.startswith("P") and name[1:].isdigit():
        return int(name[1:])
    return None


def point_to_rail_slot_map(rail_analysis: dict[str, Any]) -> dict[int, int]:
    result: dict[int, int] = {}
    bindings = rail_analysis["semantic_binding_provenance"][
        "point_family_to_rail_slot"
    ]["bindings"]
    for binding in bindings:
        slot = int(binding["rail_slot"])
        for point_number in binding["explicit_point_numbers"]:
            previous = result.setdefault(int(point_number), slot)
            if previous != slot:
                raise ValueError(
                    f"Point P{point_number} maps to conflicting rail slots "
                    f"{previous} and {slot}"
                )
    return result


def validate_inputs(
    workspace: Path,
    replay_points: tuple[str, ...] = DEFAULT_REPLAY_POINTS,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    asset_root = workspace / "pTLC仿真资产"
    paths = {
        "interaction_points": asset_root / "interaction_points.json",
        "layout": asset_root / "layout_estimate.json",
        "rail_analysis": asset_root / "rail_frame_layout_analysis.json",
        "asset_manifest": asset_root / "asset_manifest.json",
        "collision_qc": asset_root / "collision_qc_report.json",
        "layout_collision_qc": asset_root / "layout_collision_qc.json",
        "robot_urdf": workspace / "dobot_rviz/urdf/cr5_robot.urdf",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    points_document = load_json(paths["interaction_points"])
    layout = load_json(paths["layout"])
    rail_analysis = load_json(paths["rail_analysis"])
    collision_qc = load_json(paths["collision_qc"])
    layout_collision_qc = load_json(paths["layout_collision_qc"])
    points = robot_points(points_document)
    point_by_name = {point["robot_name"]: point for point in points}
    if len(point_by_name) != len(points):
        raise ValueError("robot_name values are not unique")

    expected_counts = points_document["counts"]
    status_counts = Counter(point.get("status") for point in points)
    joint_points = [point for point in points if point.get("joint") is not None]
    derived_points = [point for point in points if point.get("is_derived")]
    checks = {
        "robot_total_239": len(points) == 239 == expected_counts["robot_total"],
        "robot_base_74": len(joint_points) == 74 == expected_counts["robot_base"],
        "robot_derived_165": len(derived_points) == 165 == expected_counts["robot_derived"],
        "placeholder_count_4": status_counts["placeholder"] == 4,
        "plc_semantic_points_16": expected_counts["plc_semantic_points"] == 16,
        "layout_placements_15": len(layout["placements"]) == 15,
        "collision_asset_count_15": collision_qc.get("count") == 15,
        "collision_assets_passed": all(
            collision_qc.get(key) is True
            for key in (
                "all_watertight",
                "all_bounds_match_target",
                "all_expected_cavities_preserved",
                "all_open_source_components_disjoint",
            )
        ),
        "layout_collision_passed": layout_collision_qc.get("status") == "passed",
        "layout_unexpected_overlap_zero": layout_collision_qc.get(
            "unexpected_component_overlap_count"
        )
        == 0,
        "world_transform_unset": layout["controller_frame_boundary"].get(
            "world_rigid_transform"
        )
        is None,
    }

    proxy_records: list[dict[str, Any]] = []
    for placement in layout["placements"]:
        asset_id = placement["asset_id"]
        visual = asset_root / "proxies" / asset_id / "visual.glb"
        collision = asset_root / "proxies" / asset_id / "collision.stl"
        if not visual.is_file() or not collision.is_file():
            raise FileNotFoundError(
                f"Missing proxy pair for {asset_id}: {visual}, {collision}"
            )
        proxy_records.append(
            {
                "asset_id": asset_id,
                "visual": str(visual.relative_to(workspace)),
                "visual_sha256": sha256(visual),
                "collision": str(collision.relative_to(workspace)),
                "collision_sha256": sha256(collision),
            }
        )

    limits = urdf_joint_limits(paths["robot_urdf"])
    if len(limits) != 6:
        raise ValueError(f"Expected six CR5 joints, found {len(limits)}")
    replay_records: list[dict[str, Any]] = []
    for point_name in replay_points:
        if point_name not in point_by_name:
            raise KeyError(f"Replay point is missing: {point_name}")
        point = point_by_name[point_name]
        if point.get("status") != "validated":
            raise ValueError(f"Replay point is not validated: {point_name}")
        joint_degrees = point.get("joint")
        if not isinstance(joint_degrees, list) or len(joint_degrees) != 6:
            raise ValueError(f"Replay point lacks six joint values: {point_name}")
        joint_radians = [math.radians(float(value)) for value in joint_degrees]
        violations = []
        for limit, value in zip(limits, joint_radians, strict=True):
            if not limit["lower"] <= value <= limit["upper"]:
                violations.append(
                    {
                        "joint": limit["name"],
                        "value_rad": value,
                        "lower_rad": limit["lower"],
                        "upper_rad": limit["upper"],
                    }
                )
        if violations:
            raise ValueError(f"Joint-limit violation at {point_name}: {violations}")
        replay_records.append(
            {
                "point": point_name,
                "workstation": point["workstation"],
                "role": point["role"],
                "allowed_motion": point["allowed_motion"],
                "user": point["user"],
                "tool": point["tool"],
                "joint_degrees": joint_degrees,
                "joint_radians": joint_radians,
                "raw_controller_pose": point["pose"],
            }
        )

    same_context = {
        "workstation": len({record["workstation"] for record in replay_records}) == 1,
        "user": len({record["user"] for record in replay_records}) == 1,
        "tool": len({record["tool"] for record in replay_records}) == 1,
    }
    checks["replay_same_context"] = all(same_context.values())
    checks["replay_points_validated"] = all(
        point_by_name[name]["status"] == "validated" for name in replay_points
    )
    checks["replay_joint_limits_passed"] = True

    rail_slots = point_to_rail_slot_map(rail_analysis)
    bound_original_points = [
        point
        for point in points
        if (number := original_point_number(point)) is not None and number in rail_slots
    ]

    failed = sorted(name for name, passed in checks.items() if not passed)
    report = {
        "schema_version": "ptlc.isaac.input-validation.v1",
        "status": "passed" if not failed else "failed",
        "workspace": str(workspace),
        "checks": checks,
        "failed_checks": failed,
        "counts": {
            "robot_total": len(points),
            "robot_base_with_joint": len(joint_points),
            "robot_derived": len(derived_points),
            "robot_validated": status_counts["validated"],
            "robot_placeholder": status_counts["placeholder"],
            "plc_semantic_points": expected_counts["plc_semantic_points"],
            "layout_placements": len(layout["placements"]),
            "rail_bound_original_points": len(bound_original_points),
        },
        "coordinate_contract": {
            "scene": layout["coordinate_frame"],
            "controller_boundary": layout["controller_frame_boundary"],
            "visual_glb": "meters, Z-up",
            "collision_stl": "millimeters, Z-up; runtime divides vertices by 1000",
            "robot_joint_source": "raw DOBOT joint degrees",
            "cartesian_pose_policy": (
                "preserved as raw evidence; not used for IK until the controller "
                "Euler convention and Tool 1 TCP are verified"
            ),
        },
        "replay": {
            "kind": "joint-space interpolation between recorded controller joint states",
            "points": replay_records,
            "same_context": same_context,
            "rail_slot": 2,
            "rail_binding_basis": "P63/P76 photo-stage operation semantics",
            "not_claimed": [
                "DOBOT MoveL reproduction",
                "surveyed world pose reproduction",
                "verified CR5A dynamics or TCP",
            ],
        },
        "joint_limits": limits,
        "source_hashes": {
            name: sha256(path) for name, path in paths.items()
        },
        "proxy_assets": proxy_records,
        "blocked_placeholder_points": sorted(
            point["robot_name"]
            for point in points
            if point.get("status") == "placeholder"
        ),
    }
    if failed:
        raise RuntimeError(f"Input validation failed: {failed}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--replay-point",
        action="append",
        dest="replay_points",
        help="Repeat to override the default P63 -> P76 -> P63 sequence",
    )
    args = parser.parse_args()
    replay_points = tuple(args.replay_points or DEFAULT_REPLAY_POINTS)
    report = validate_inputs(args.workspace, replay_points)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(args.output.resolve())
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
