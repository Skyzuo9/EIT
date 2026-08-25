#!/usr/bin/env python3
"""Derive a joint-only Uni-Lab PointSet from recorded interaction points."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SELECTED = tuple(["P45"] + [f"P{i}" for i in range(46, 52)] + [f"P{i}" for i in range(78, 84)])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_points(value: Any, result: dict[str, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        name = value.get("robot_name")
        if name in SELECTED and value.get("joint") is not None:
            if name in result:
                raise ValueError(f"Duplicate recorded point: {name}")
            result[name] = value
        for child in value.values():
            collect_points(child, result)
    elif isinstance(value, list):
        for child in value:
            collect_points(child, result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    document = json.loads(source.read_text(encoding="utf-8"))
    recorded: dict[str, dict[str, Any]] = {}
    collect_points(document, recorded)
    missing = [name for name in SELECTED if name not in recorded]
    if missing:
        raise ValueError(f"Missing recorded joint points: {missing}")

    waypoints = {}
    for name in SELECTED:
        record = recorded[name]
        if record.get("status") != "validated" or record.get("workstation") != "area-7":
            raise ValueError(f"Point is not validated for area-7: {name}")
        degrees = [float(value) for value in record["joint"]]
        if len(degrees) != 6 or not all(math.isfinite(value) for value in degrees):
            raise ValueError(f"Invalid six-axis record: {name}")
        waypoints[name] = {
            "type": "joint_positions",
            "value": [math.radians(value) for value in degrees],
            "source_joint_degrees": degrees,
            "source_id": record["id"],
            "source_status": record["status"],
        }

    result = {
        "schema": "unilab.arm-point-set/v2",
        "revision": "ptlc-cr5-area7-recorded-joints@1.0.0",
        "compatible_model_ref": "package://unilab_arm_cr5/models/model.yaml",
        "tool_context_ref": "ptlc-simulation-no-tool@1.0.0",
        "targets": {
            "ptlc": {
                "description": "Recorded area-7 CR5 joint targets for multi-point Isaac visualization",
                "waypoints": waypoints,
            }
        },
        "source": {
            "path": str(source),
            "sha256": sha256(source),
            "controller_point_names": list(SELECTED),
            "source_unit": "degree",
            "stored_unit": "rad_by_revolute_joint_contract",
        },
        "qualification": "simulation-only-uncalibrated",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
