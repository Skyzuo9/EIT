#!/usr/bin/env python3
"""Loop the validated area-7 CR5 motion in the Isaac WebRTC experience.

This is deliberately a simulation-only geometry playback.  It reads the same
PointSet and passed validation report as the offline evidence video, then
applies the recorded joint targets to the imported CR5 geometry while the
Isaac Sim Full Streaming experience is running.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np


ROBOT_ROOT = "/World/RobotSystem/CR5/Geometry/dummy_link/base_link"
LINK_PATHS = tuple(
    ROBOT_ROOT + "/" + "/".join(f"Link{index}" for index in range(1, end + 1))
    for end in range(1, 7)
)
EXPECTED_SEQUENCE = (
    "ptlc.P45",
    "ptlc.P46",
    "ptlc.P47",
    "ptlc.P48",
    "ptlc.P80",
    "ptlc.P79",
    "ptlc.P78",
    "ptlc.P45",
    "ptlc.P49",
    "ptlc.P50",
    "ptlc.P51",
    "ptlc.P83",
    "ptlc.P82",
    "ptlc.P81",
    "ptlc.P45",
)


@dataclass(frozen=True)
class MotionSegment:
    phase: str
    target_ref: str
    duration_seconds: float
    before: np.ndarray
    target: np.ndarray


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def require_authorization() -> None:
    accepted = os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower()
    if accepted not in {"1", "y", "yes"}:
        raise RuntimeError("Explicit NVIDIA Omniverse EULA acceptance is required")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "1":
        raise RuntimeError("This live playback is authorized only on physical GPU 1")


def load_validated_playback(
    point_set_path: Path,
    validation_report_path: Path,
) -> tuple[dict[str, np.ndarray], tuple[str, ...], dict[str, Any]]:
    point_set = json.loads(point_set_path.read_text(encoding="utf-8"))
    report = json.loads(validation_report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise ValueError("The source Uni-Lab Isaac validation did not pass")
    if report.get("point_set_sha256") != sha256_file(point_set_path):
        raise ValueError("PointSet hash differs from the passed validation report")
    sequence = tuple(str(value) for value in report.get("requested_targets", ()))
    if sequence != EXPECTED_SEQUENCE:
        raise ValueError(f"Unexpected validated playback sequence: {sequence}")

    targets: dict[str, np.ndarray] = {}
    groups = point_set.get("targets", {})
    for target_ref in sequence:
        group_name, point_name = target_ref.split(".", 1)
        try:
            waypoint = groups[group_name]["waypoints"][point_name]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Missing PointSet target {target_ref}") from exc
        if waypoint.get("type") != "joint_positions":
            raise ValueError(f"Target {target_ref} is not a joint target")
        values = np.asarray(waypoint.get("value"), dtype=float)
        if values.shape != (6,) or not np.all(np.isfinite(values)):
            raise ValueError(f"Target {target_ref} must contain six finite joints")
        targets[target_ref] = values
    return targets, sequence, report


def build_segments(
    targets: dict[str, np.ndarray],
    sequence: Sequence[str],
    *,
    move_seconds: float,
    hold_seconds: float,
) -> tuple[MotionSegment, ...]:
    if move_seconds <= 0.0 or hold_seconds <= 0.0:
        raise ValueError("Move and hold durations must be positive")
    if not sequence:
        raise ValueError("At least one target is required")

    current_ref = sequence[0]
    current = targets[current_ref]
    segments = [
        MotionSegment(
            phase=f"hold_{current_ref.rsplit('.', 1)[-1]}",
            target_ref=current_ref,
            duration_seconds=hold_seconds,
            before=current.copy(),
            target=current.copy(),
        )
    ]
    for target_ref in sequence[1:]:
        target = targets[target_ref]
        segments.append(
            MotionSegment(
                phase=f"move_to_{target_ref.rsplit('.', 1)[-1]}",
                target_ref=target_ref,
                duration_seconds=move_seconds,
                before=current.copy(),
                target=target.copy(),
            )
        )
        segments.append(
            MotionSegment(
                phase=f"hold_{target_ref.rsplit('.', 1)[-1]}",
                target_ref=target_ref,
                duration_seconds=hold_seconds,
                before=target.copy(),
                target=target.copy(),
            )
        )
        current = target
    return tuple(segments)


def smoothstep(before: np.ndarray, target: np.ndarray, progress: float) -> np.ndarray:
    progress = min(1.0, max(0.0, float(progress)))
    blend = 3.0 * progress**2 - 2.0 * progress**3
    return before + blend * (target - before)


def sample_cycle(
    segments: Sequence[MotionSegment], cycle_time: float
) -> tuple[int, MotionSegment, float, np.ndarray]:
    cycle_duration = sum(segment.duration_seconds for segment in segments)
    if cycle_duration <= 0.0:
        raise ValueError("Motion cycle duration must be positive")
    remaining = float(cycle_time) % cycle_duration
    for index, segment in enumerate(segments):
        if remaining < segment.duration_seconds or index == len(segments) - 1:
            progress = remaining / segment.duration_seconds
            if segment.phase.startswith("move_to_"):
                joints = smoothstep(segment.before, segment.target, progress)
            else:
                joints = segment.target.copy()
            return index, segment, progress, joints
        remaining -= segment.duration_seconds
    raise AssertionError("Unreachable motion sampling state")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--point-set", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--experience", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--move-seconds", type=float, default=1.5)
    parser.add_argument("--hold-seconds", type=float, default=0.25)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--target-fps", type=int, default=30)
    parser.add_argument("--public-ip", default="222.29.40.109")
    parser.add_argument("--signal-port", type=int, default=49100)
    parser.add_argument("--stream-port", type=int, default=47998)
    args = parser.parse_args()

    require_authorization()
    scene = args.scene.resolve()
    point_set_path = args.point_set.resolve()
    validation_report_path = args.validation_report.resolve()
    experience = args.experience.resolve()
    status_file = args.status_file.resolve()
    for path in (scene, point_set_path, validation_report_path, experience):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.width <= 0 or args.height <= 0 or args.target_fps <= 0:
        raise ValueError("Resolution and target FPS must be positive")

    targets, sequence, validation_report = load_validated_playback(
        point_set_path, validation_report_path
    )
    segments = build_segments(
        targets,
        sequence,
        move_seconds=args.move_seconds,
        hold_seconds=args.hold_seconds,
    )
    cycle_duration = sum(segment.duration_seconds for segment in segments)
    stop_requested = False

    def request_stop(signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        print(f"Received signal {signum}; stopping after current update", flush=True)
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "headless": True,
            "hide_ui": False,
            "width": args.width,
            "height": args.height,
            "window_width": args.width,
            "window_height": args.height,
            "active_gpu": 1,
            "physics_gpu": 0,
            "multi_gpu": False,
            "max_gpu_count": 1,
            "anti_aliasing": 2,
            "create_new_stage": True,
            "extra_args": [
                "--no-window",
                "--/renderer/multiGpu/autoEnable=false",
                "--/renderer/multiGpu/enabled=false",
                "--/renderer/multiGpu/maxGpuCount=1",
                f"--/exts/omni.kit.livestream.app/primaryStream/targetFps={args.target_fps}",
                "--/exts/omni.kit.livestream.app/primaryStream/allowDynamicResize=false",
                "--/exts/omni.services.livestream.session/quitOnSessionEnded=false",
                "--/exts/omni.services.livestream.session/resumeTimeout=300",
                "--/isaac/startup/ros_bridge_extension=",
                f"--/exts/omni.kit.livestream.app/primaryStream/publicIp={args.public_ip}",
                f"--/exts/omni.kit.livestream.app/primaryStream/signalPort={args.signal_port}",
                f"--/exts/omni.kit.livestream.app/primaryStream/streamPort={args.stream_port}",
            ],
        },
        experience=str(experience),
    )

    status: dict[str, Any] = {
        "schema": "ptlc.isaac-area7-live-stream/v1",
        "status": "starting",
        "pid": os.getpid(),
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "point_set": str(point_set_path),
        "point_set_sha256": sha256_file(point_set_path),
        "source_validation_report": str(validation_report_path),
        "source_validation_status": validation_report["status"],
        "sequence": list(sequence),
        "unique_target_count": len(set(sequence)),
        "stop_count": len(sequence),
        "cycle_duration_seconds": cycle_duration,
        "move_seconds": args.move_seconds,
        "hold_seconds": args.hold_seconds,
        "stream_resolution": [args.width, args.height],
        "stream_target_fps": args.target_fps,
        "authorized_physical_gpu": 1,
        "hardware_connections": "none",
        "completed_cycles": 0,
        "boundary": (
            "Simulation-only, geometry-driven playback of the validated Uni-Lab "
            "joint targets. This is not MoveIt planning, collision certification, "
            "rigid-body dynamics, gripper interaction, or real hardware execution."
        ),
    }
    write_json_atomic(status_file, status)

    try:
        import carb.settings
        import isaacsim.core.utils.stage as stage_utils
        from pxr import Gf

        print(f"Opening validated client stage: {scene}", flush=True)
        if not stage_utils.open_stage(str(scene)):
            raise RuntimeError(f"Could not open scene: {scene}")
        for _ in range(90):
            simulation_app.update()
        stage = stage_utils.get_current_stage()
        settings = carb.settings.get_settings()
        settings.set_bool("/rtx/post/motionblur/enabled", False)

        orient_attrs = []
        base_orients = []
        for link_path in LINK_PATHS:
            prim = stage.GetPrimAtPath(link_path)
            if not prim.IsValid():
                raise RuntimeError(f"Missing link prim: {link_path}")
            orient_attr = prim.GetAttribute("xformOp:orient")
            if not orient_attr or orient_attr.Get() is None:
                raise RuntimeError(f"Missing xformOp:orient: {link_path}")
            value = orient_attr.Get()
            orient_attrs.append(orient_attr)
            base_orients.append(
                Gf.Quatd(
                    float(value.GetReal()),
                    Gf.Vec3d(*[float(component) for component in value.GetImaginary()]),
                )
            )

        def apply_joints(joints_si: np.ndarray) -> None:
            for orient_attr, base_orient, angle_degrees in zip(
                orient_attrs,
                base_orients,
                np.degrees(joints_si),
                strict=True,
            ):
                delta = Gf.Rotation(
                    Gf.Vec3d(0.0, 0.0, 1.0), float(angle_degrees)
                ).GetQuat()
                combined = base_orient * delta
                orient_attr.Set(
                    Gf.Quatf(
                        float(combined.GetReal()),
                        Gf.Vec3f(
                            *[float(component) for component in combined.GetImaginary()]
                        ),
                    )
                )

        started_at = time.monotonic()
        last_segment_index = -1
        last_cycle_index = -1
        status["status"] = "streaming"
        status["started_at_unix"] = time.time()
        print(
            json.dumps(
                {
                    "event": "area7_live_stream_ready",
                    "cycle_duration_seconds": cycle_duration,
                    "sequence": sequence,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        while simulation_app.is_running() and not stop_requested:
            elapsed = time.monotonic() - started_at
            cycle_index = int(elapsed // cycle_duration)
            segment_index, segment, progress, joints = sample_cycle(
                segments, elapsed
            )
            apply_joints(joints)
            simulation_app.update()

            if segment_index != last_segment_index or cycle_index != last_cycle_index:
                if cycle_index > last_cycle_index and last_cycle_index >= 0:
                    status["completed_cycles"] = cycle_index
                status.update(
                    {
                        "updated_at_unix": time.time(),
                        "cycle_index": cycle_index,
                        "segment_index": segment_index,
                        "phase": segment.phase,
                        "target_ref": segment.target_ref,
                        "progress": progress,
                        "joint_positions_si": joints.tolist(),
                        "joint_degrees": np.degrees(joints).tolist(),
                    }
                )
                write_json_atomic(status_file, status)
                print(
                    json.dumps(
                        {
                            "event": "motion_segment",
                            "cycle": cycle_index,
                            "segment": segment_index,
                            "phase": segment.phase,
                            "target_ref": segment.target_ref,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                last_segment_index = segment_index
                last_cycle_index = cycle_index
    except Exception as exc:
        status["status"] = "failed"
        status["error"] = f"{type(exc).__name__}: {exc}"
        status["traceback"] = traceback.format_exc()
        write_json_atomic(status_file, status)
        raise
    finally:
        if status.get("status") != "failed":
            status["status"] = "stopped"
            status["stopped_at_unix"] = time.time()
            write_json_atomic(status_file, status)
        simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
