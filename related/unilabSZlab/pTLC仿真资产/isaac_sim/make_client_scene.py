#!/usr/bin/env python3
"""Add an evidence-bounded timeline and replay guides to a pTLC USD scene."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


FPS = 60.0
HOLD_SECONDS = 1.0
MOVE_SECONDS = 4.0
REPLAY_NAMES = ("P63", "P76", "P63")


def smoothstep(start: np.ndarray, end: np.ndarray, count: int) -> np.ndarray:
    u = np.linspace(0.0, 1.0, count)
    blend = 3.0 * u**2 - 2.0 * u**3
    return start[None, :] + blend[:, None] * (end - start)[None, :]


def timeline_samples(targets_degrees: list[list[float]]) -> list[tuple[int, np.ndarray]]:
    """Build a loopable P63 -> P76 -> P63 joint-target timeline."""

    targets = [np.asarray(values, dtype=float) for values in targets_degrees]
    samples: list[tuple[int, np.ndarray]] = []
    frame = 0
    hold_frames = int(round(HOLD_SECONDS * FPS))
    move_frames = int(round(MOVE_SECONDS * FPS))
    for segment_index, (start, end) in enumerate(zip(targets[:-1], targets[1:])):
        if segment_index == 0:
            for _ in range(hold_frames):
                samples.append((frame, start.copy()))
                frame += 1
        for command in smoothstep(start, end, move_frames + 1)[1:]:
            samples.append((frame, command))
            frame += 1
        for _ in range(hold_frames):
            samples.append((frame, end.copy()))
            frame += 1
    return samples


def load_replay_degrees(input_validation: Path) -> list[list[float]]:
    document = json.loads(input_validation.read_text(encoding="utf-8"))
    records = document["replay"]["points"]
    names = tuple(str(record["point"]) for record in records)
    if names != REPLAY_NAMES:
        raise ValueError(f"Expected replay {REPLAY_NAMES}, got {names}")
    return [[float(value) for value in record["joint_degrees"]] for record in records]


def replay_positions(stage: Any) -> tuple[dict[str, Any], list[str]]:
    positions: dict[str, Any] = {}
    records_found: set[str] = set()
    for prim in stage.Traverse():
        name_attr = prim.GetAttribute("ptlc:pointName")
        position_attr = prim.GetAttribute("ptlc:relativeConstraintPositionM")
        if not name_attr:
            continue
        point_name = name_attr.Get()
        if point_name not in {"P63", "P76"}:
            continue
        records_found.add(str(point_name))
        if position_attr and position_attr.Get() is not None:
            positions[str(point_name)] = position_attr.Get()
    missing_records = sorted({"P63", "P76"} - records_found)
    if missing_records:
        raise RuntimeError(f"Replay records are absent from scene: {missing_records}")
    return positions, sorted({"P63", "P76"} - set(positions))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-scene", type=Path, required=True)
    parser.add_argument("--input-validation", type=Path, required=True)
    parser.add_argument("--output-scene", type=Path, required=True)
    args = parser.parse_args()

    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, Vt

    input_scene = args.input_scene.resolve()
    output_scene = args.output_scene.resolve()
    output_scene.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.Open(str(input_scene))
    if stage is None:
        raise RuntimeError(f"Could not open {input_scene}")

    targets_degrees = load_replay_degrees(args.input_validation.resolve())
    samples = timeline_samples(targets_degrees)
    joints = [
        prim
        for prim in stage.Traverse()
        if prim.IsA(UsdPhysics.RevoluteJoint)
    ]
    joints.sort(key=lambda prim: str(prim.GetPath()))
    expected_paths = [f"/World/RobotSystem/CR5/Physics/joint{i}" for i in range(1, 7)]
    actual_paths = [str(prim.GetPath()) for prim in joints]
    if actual_paths != expected_paths:
        raise RuntimeError(f"Unexpected replay joint paths: {actual_paths}")

    stage.SetTimeCodesPerSecond(FPS)
    stage.SetFramesPerSecond(FPS)
    stage.SetStartTimeCode(0)
    stage.SetEndTimeCode(samples[-1][0])
    for joint_index, prim in enumerate(joints):
        drive = UsdPhysics.DriveAPI.Get(prim, "angular")
        target_attr = drive.GetTargetPositionAttr()
        if not target_attr:
            raise RuntimeError(f"Missing angular drive on {prim.GetPath()}")
        for frame, command in samples:
            target_attr.Set(float(command[joint_index]), Usd.TimeCode(frame))

    positions, unplaced_endpoints = replay_positions(stage)
    guide_root = UsdGeom.Xform.Define(stage, "/World/ReplayGuide")
    guide_root.GetPrim().CreateAttribute(
        "ptlc:evidenceLevel", Sdf.ValueTypeNames.String
    ).Set("joint_replay_with_explicitly_bound_spatial_endpoints_only")
    guide_root.GetPrim().CreateAttribute(
        "ptlc:replay", Sdf.ValueTypeNames.String
    ).Set("P63 -> P76 -> P63")
    guide_root.GetPrim().CreateAttribute(
        "ptlc:clientInstruction", Sdf.ValueTypeNames.String
    ).Set("Press Play; enable Loop for continuous replay")

    if {"P63", "P76"}.issubset(positions):
        curve = UsdGeom.BasisCurves.Define(
            stage, "/World/ReplayGuide/P63_to_P76"
        )
        curve.CreateTypeAttr("linear")
        curve.CreateWrapAttr("nonperiodic")
        curve.CreateCurveVertexCountsAttr([2])
        curve.CreatePointsAttr(
            Vt.Vec3fArray(
                [Gf.Vec3f(*positions["P63"]), Gf.Vec3f(*positions["P76"])]
            )
        )
        curve.CreateWidthsAttr([0.018, 0.018])
        curve.CreateDisplayColorAttr([Gf.Vec3f(1.0, 0.72, 0.05)])

    endpoint_records = []
    for point_name, color in (
        ("P63", Gf.Vec3f(1.0, 0.25, 0.08)),
        ("P76", Gf.Vec3f(1.0, 0.90, 0.10)),
    ):
        if point_name not in positions:
            endpoint_records.append(
                {
                    "point": point_name,
                    "spatially_placed": False,
                    "reason": "no explicit operation-semantic rail-slot binding",
                }
            )
            continue
        sphere = UsdGeom.Sphere.Define(
            stage, f"/World/ReplayGuide/Endpoint_{point_name}"
        )
        sphere.CreateRadiusAttr(0.035)
        UsdGeom.XformCommonAPI(sphere).SetTranslate(
            Gf.Vec3d(*[float(value) for value in positions[point_name]])
        )
        sphere.CreateDisplayColorAttr([color])
        sphere.GetPrim().CreateAttribute(
            "ptlc:pointName", Sdf.ValueTypeNames.String
        ).Set(point_name)
        endpoint_records.append(
            {
                "point": point_name,
                "spatially_placed": True,
                "relative_constraint_position_m": list(positions[point_name]),
            }
        )

    stage.GetRootLayer().Export(str(output_scene))
    report = {
        "schema_version": "ptlc.isaac.client-scene.v1",
        "status": "passed",
        "input_scene": str(input_scene),
        "output_scene": str(output_scene),
        "timeline": {
            "frames_per_second": FPS,
            "start_time_code": 0,
            "end_time_code": samples[-1][0],
            "duration_seconds": samples[-1][0] / FPS,
            "replay": list(REPLAY_NAMES),
            "drive_unit": "degrees for angular USD drive targetPosition",
        },
        "joints": actual_paths,
        "endpoints": endpoint_records,
        "unplaced_endpoints": unplaced_endpoints,
        "boundary": (
            "Only endpoints with an explicit operation-semantic rail-slot binding "
            "are spatially shown. P63 has joint data but no explicit spatial binding. "
            "Timeline motion is smooth joint-drive target interpolation, not DOBOT "
            "MoveL, a measured TCP path, or real-device validation."
        ),
    }
    report_path = output_scene.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
