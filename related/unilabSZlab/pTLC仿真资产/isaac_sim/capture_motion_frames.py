#!/usr/bin/env python3
"""Render a geometry-only P63 -> P76 -> P63 motion sequence in Isaac Sim."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


ROBOT_ROOT = "/World/RobotSystem/CR5/Geometry/dummy_link/base_link"
LINK_PATHS = tuple(
    ROBOT_ROOT + "/" + "/".join(f"Link{index}" for index in range(1, end + 1))
    for end in range(1, 7)
)


def load_targets(path: Path) -> tuple[np.ndarray, np.ndarray]:
    document = json.loads(path.read_text(encoding="utf-8"))
    records = document["replay"]["points"]
    names = [str(record["point"]) for record in records]
    if names != ["P63", "P76", "P63"]:
        raise ValueError(f"Expected P63 -> P76 -> P63, got {names}")
    q0 = np.asarray(records[0]["joint_degrees"], dtype=float)
    q1 = np.asarray(records[1]["joint_degrees"], dtype=float)
    if q0.shape != (6,) or q1.shape != (6,):
        raise ValueError("Expected six joint angles at P63 and P76")
    return q0, q1


def smoothstep(a: np.ndarray, b: np.ndarray, u: float) -> np.ndarray:
    blend = 3.0 * u**2 - 2.0 * u**3
    return a + blend * (b - a)


def make_sequence(
    q0: np.ndarray,
    q1: np.ndarray,
    fps: int,
    hold_seconds: float,
    move_seconds: float,
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    hold_frames = max(1, int(round(hold_seconds * fps)))
    move_frames = max(1, int(round(move_seconds * fps)))
    frames: list[np.ndarray] = []
    metadata: list[dict[str, Any]] = []

    def append(q: np.ndarray, phase: str, progress: float) -> None:
        frames.append(q.copy())
        metadata.append(
            {
                "frame": len(frames) - 1,
                "phase": phase,
                "progress": progress,
                "joint_degrees": q.tolist(),
            }
        )

    for _ in range(hold_frames):
        append(q0, "hold_P63_initial", 0.0)
    for step in range(1, move_frames + 1):
        u = step / move_frames
        append(smoothstep(q0, q1, u), "move_P63_to_P76", u)
    for _ in range(hold_frames):
        append(q1, "hold_P76", 1.0)
    for step in range(1, move_frames + 1):
        u = step / move_frames
        append(smoothstep(q1, q0, u), "move_P76_to_P63", u)
    for _ in range(hold_frames):
        append(q0, "hold_P63_final", 1.0)
    return frames, metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--input-validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--hold-seconds", type=float, default=0.75)
    parser.add_argument("--move-seconds", type=float, default=2.5)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--rt-subframes", type=int, default=8)
    parser.add_argument("--settle-updates", type=int, default=8)
    args = parser.parse_args()

    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower() not in {
        "1",
        "y",
        "yes",
    }:
        raise RuntimeError("Explicit NVIDIA Omniverse EULA acceptance is required")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "1":
        raise RuntimeError("This renderer is authorized only with CUDA_VISIBLE_DEVICES=1")
    if (
        args.fps <= 0
        or args.width <= 0
        or args.height <= 0
        or args.rt_subframes <= 0
        or args.settle_updates <= 0
    ):
        raise ValueError(
            "fps, width, height, rt-subframes, and settle-updates must be positive"
        )

    scene = args.scene.resolve()
    validation = args.input_validation.resolve()
    output = args.output.resolve()
    if not scene.is_file() or not validation.is_file():
        raise FileNotFoundError("Scene or input-validation report is missing")
    output.mkdir(parents=True, exist_ok=True)
    frame_directory = output / "frames"
    if frame_directory.exists() and any(frame_directory.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty {frame_directory}")
    frame_directory.mkdir(parents=True, exist_ok=True)

    q0, q1 = load_targets(validation)
    joint_frames, frame_metadata = make_sequence(
        q0, q1, args.fps, args.hold_seconds, args.move_seconds
    )

    report: dict[str, Any] = {
        "schema_version": "ptlc.isaac.motion-frames.v1",
        "status": "running",
        "scene": str(scene),
        "hardware_connections": "none",
        "authorized_physical_gpu": 1,
        "replay": ["P63", "P76", "P63"],
        "fps": args.fps,
        "frame_count": len(joint_frames),
        "duration_seconds": len(joint_frames) / args.fps,
        "resolution": [args.width, args.height],
        "rt_subframes": args.rt_subframes,
        "settle_updates": args.settle_updates,
        "anti_aliasing": "FXAA",
        "motion_blur": False,
        "motion_method": (
            "smooth joint-space interpolation applied directly to the imported "
            "CR5 geometry hierarchy"
        ),
        "boundary": (
            "Geometry-only offline Isaac Sim rendering from recorded joint points. "
            "It is not a physics-controlled trajectory, DOBOT MoveL reproduction, "
            "collision-free certification, WebRTC evidence, or real-device execution."
        ),
        "frames": frame_metadata,
    }
    report_path = output / "motion_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "headless": True,
            "width": args.width,
            "height": args.height,
            "active_gpu": 1,
            "physics_gpu": 0,
            "anti_aliasing": 2,
            "extra_args": [
                "--/renderer/multiGpu/autoEnable=false",
                "--/renderer/multiGpu/enabled=false",
                "--/renderer/multiGpu/maxGpuCount=1",
                "--/isaac/startup/ros_bridge_extension=",
            ],
        }
    )

    try:
        import isaacsim.core.utils.stage as stage_utils
        import carb.settings
        import omni.replicator.core as rep
        from pxr import Gf, UsdGeom

        print(f"Opening stage: {scene}", flush=True)
        if not stage_utils.open_stage(str(scene)):
            raise RuntimeError(f"Could not open scene: {scene}")
        for _ in range(60):
            simulation_app.update()
        stage = stage_utils.get_current_stage()
        settings = carb.settings.get_settings()
        settings.set_bool("/rtx/post/motionblur/enabled", False)
        settings.set_bool("/omni/replicator/captureMotionBlur", False)

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
            base_orient = Gf.Quatd(
                float(value.GetReal()),
                Gf.Vec3d(*[float(component) for component in value.GetImaginary()]),
            )
            orient_attrs.append(orient_attr)
            base_orients.append(base_orient)

        rep.orchestrator.set_capture_on_play(False)
        camera = rep.functional.create.camera(
            position=(2.8, -3.35, 2.65),
            look_at=(0.0, 0.0, 1.25),
            parent="/World",
            name="MotionCamera",
        )
        render_product = rep.create.render_product(
            camera, (args.width, args.height)
        )
        backend = rep.backends.get("DiskBackend")
        backend.initialize(output_dir=str(frame_directory))
        writer = rep.WriterRegistry.get("BasicWriter")
        writer.initialize(backend=backend, rgb=True)
        writer.attach(render_product)

        print(f"Rendering {len(joint_frames)} frames", flush=True)
        for frame_index, joint_degrees in enumerate(joint_frames):
            for orient_attr, base_orient, angle_degrees in zip(
                orient_attrs, base_orients, joint_degrees, strict=True
            ):
                delta = Gf.Rotation(
                    Gf.Vec3d(0.0, 0.0, 1.0), float(angle_degrees)
                ).GetQuat()
                combined = base_orient * delta
                orient_attr.Set(
                    Gf.Quatf(
                        float(combined.GetReal()),
                        Gf.Vec3f(
                            *[
                                float(component)
                                for component in combined.GetImaginary()
                            ]
                        ),
                    )
                )
            for _ in range(args.settle_updates):
                simulation_app.update()
            rep.orchestrator.step(
                rt_subframes=args.rt_subframes,
                delta_time=0.0,
                pause_timeline=True,
            )
            if frame_index == 0 or (frame_index + 1) % 10 == 0:
                print(
                    f"Rendered {frame_index + 1}/{len(joint_frames)}",
                    flush=True,
                )

        rep.orchestrator.wait_until_complete()
        writer.detach()
        render_product.destroy()

        images = sorted(frame_directory.glob("rgb*.png"))
        if len(images) != len(joint_frames):
            raise RuntimeError(
                f"Expected {len(joint_frames)} PNG frames, found {len(images)}"
            )
        if any(image.stat().st_size == 0 for image in images):
            raise RuntimeError("At least one rendered frame is empty")
        report["status"] = "passed"
        report["frame_files"] = [str(image) for image in images]
        report["frame_bytes_total"] = sum(image.stat().st_size for image in images)
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        simulation_app.close()

    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
