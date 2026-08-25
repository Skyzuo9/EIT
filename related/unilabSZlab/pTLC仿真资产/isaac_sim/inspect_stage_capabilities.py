#!/usr/bin/env python3
"""Inventory physics capabilities authored in a USD stage.

This is a structural gate only.  Presence of schemas does not prove that the
physics simulation is stable or that a trajectory is collision free.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pxr import Usd, UsdPhysics


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_applied(prim: Usd.Prim, schema: Any) -> bool:
    try:
        return prim.HasAPI(schema)
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    stage_path = args.stage.resolve()
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise RuntimeError(f"Could not open stage: {stage_path}")

    type_counts: Counter[str] = Counter()
    articulation_roots: list[str] = []
    rigid_bodies: list[str] = []
    collisions: list[str] = []
    masses: list[str] = []
    joints: list[dict[str, Any]] = []
    drive_attributes: list[dict[str, Any]] = []

    for prim in stage.Traverse():
        path = str(prim.GetPath())
        type_counts[prim.GetTypeName() or "<typeless>"] += 1
        if api_applied(prim, UsdPhysics.ArticulationRootAPI):
            articulation_roots.append(path)
        if api_applied(prim, UsdPhysics.RigidBodyAPI):
            rigid_bodies.append(path)
        if api_applied(prim, UsdPhysics.CollisionAPI):
            collisions.append(path)
        if api_applied(prim, UsdPhysics.MassAPI):
            masses.append(path)

        if prim.IsA(UsdPhysics.Joint):
            joint = UsdPhysics.Joint(prim)
            record = {
                "path": path,
                "type": prim.GetTypeName(),
                "body0": [str(item) for item in joint.GetBody0Rel().GetTargets()],
                "body1": [str(item) for item in joint.GetBody1Rel().GetTargets()],
                "enabled": bool(joint.GetJointEnabledAttr().Get()),
            }
            joints.append(record)

        for attribute in prim.GetAttributes():
            name = attribute.GetName()
            if name.startswith("drive:") or "drive" in name.lower() and name.startswith("physx"):
                value = attribute.Get()
                drive_attributes.append(
                    {
                        "prim": path,
                        "attribute": name,
                        "value": value if isinstance(value, (str, int, float, bool, type(None))) else str(value),
                    }
                )

    robot_prefixes = ("/World/CR5", "/World/Robot")
    robot_joints = [j for j in joints if j["path"].startswith(robot_prefixes)]
    lab_collisions = [p for p in collisions if p.startswith("/World/Lab/")]
    report = {
        "schema_version": "ptlc.usd-physics-inventory.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stage": str(stage_path),
        "stage_sha256": sha256_file(stage_path),
        "prim_count": sum(type_counts.values()),
        "type_counts": dict(sorted(type_counts.items())),
        "articulation_roots": articulation_roots,
        "rigid_body_count": len(rigid_bodies),
        "rigid_bodies": rigid_bodies,
        "collision_count": len(collisions),
        "collisions": collisions,
        "mass_count": len(masses),
        "masses": masses,
        "joint_count": len(joints),
        "joints": joints,
        "robot_joint_count": len(robot_joints),
        "robot_joints": robot_joints,
        "drive_attribute_count": len(drive_attributes),
        "drive_attributes": drive_attributes,
        "lab_collision_count": len(lab_collisions),
        "structural_gates": {
            "has_articulation_root": bool(articulation_roots),
            "has_robot_joints": len(robot_joints) >= 6,
            "has_joint_drives": bool(drive_attributes),
            "has_robot_rigid_bodies": any(
                path.startswith(robot_prefixes) for path in rigid_bodies
            ),
            "has_lab_colliders": bool(lab_collisions),
        },
        "boundary": (
            "Schema inventory only. A passing structural gate is not evidence of "
            "dynamic stability, contact response, or collision-free motion."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["structural_gates"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

