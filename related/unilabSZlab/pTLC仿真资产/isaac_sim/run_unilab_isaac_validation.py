#!/usr/bin/env python3
"""Execute Uni-Lab CR5 point commands inside the pTLC Isaac renderer."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from capture_motion_frames import LINK_PATHS
from unilab_control import (
    configure_template_imports,
    execute_point_sequence,
    load_json_document,
    sha256_file,
)


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def require_authorization() -> None:
    accepted = os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower()
    if accepted not in {"1", "y", "yes"}:
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


def template_revision(template_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(template_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable-on-render-host"


def template_source_hashes(template_root: Path) -> dict[str, str]:
    """Hash the exact template sources that participate in this control path."""

    relative_paths = (
        "packages/unilab-robot-contracts/src/unilab_robot_contracts/commissioning.py",
        "packages/unilab-robot-contracts/src/unilab_robot_contracts/targets.py",
        "packages/unilab-arm-cr5/src/unilab_arm_cr5/kinematics.py",
        "packages/unilab-arm-cr5/src/unilab_arm_cr5/adapters/moveit_commissioning.py",
        "packages/unilab-robot-runtime/src/unilab_robot_runtime/binding.py",
    )
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = template_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Template evidence source is missing: {path}")
        result[relative] = sha256_file(path)
    return result


def smoothstep(before: np.ndarray, target: np.ndarray, progress: float) -> np.ndarray:
    blend = 3.0 * progress**2 - 2.0 * progress**3
    return before + blend * (target - before)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--point-set", type=Path, required=True)
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument(
        "--template-revision",
        default="",
        help="Exact source Git revision recorded before syncing to the render host",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--hold-seconds", type=float, default=0.75)
    parser.add_argument("--move-seconds", type=float, default=2.5)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--rt-subframes", type=int, default=1)
    parser.add_argument("--settle-updates", type=int, default=8)
    parser.add_argument(
        "--targets",
        nargs="+",
        default=["ptlc.P63", "ptlc.P76", "ptlc.P63"],
        help="Ordered Uni-Lab target references to render",
    )
    args = parser.parse_args()

    require_authorization()
    require_idle_gpu()
    if (
        args.fps <= 0
        or args.hold_seconds <= 0.0
        or args.move_seconds <= 0.0
        or args.width <= 0
        or args.height <= 0
        or args.rt_subframes <= 0
        or args.settle_updates <= 0
    ):
        raise ValueError("Frame, duration, resolution, and settling arguments must be positive")

    scene = args.scene.resolve()
    point_set_path = args.point_set.resolve()
    template_root = args.template_root.resolve()
    output = args.output.resolve()
    if not scene.is_file() or not point_set_path.is_file():
        raise FileNotFoundError("Scene or Uni-Lab PointSet is missing")
    configure_template_imports(template_root)
    point_set = load_json_document(point_set_path)
    supplied_revision = args.template_revision.strip().lower()
    if supplied_revision and (
        len(supplied_revision) != 40
        or any(character not in "0123456789abcdef" for character in supplied_revision)
    ):
        raise ValueError("--template-revision must be a 40-character Git commit")

    output.mkdir(parents=True, exist_ok=True)
    frame_directory = output / "frames"
    if frame_directory.exists() and any(frame_directory.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty {frame_directory}")
    frame_directory.mkdir(parents=True, exist_ok=True)
    report_path = output / "unilab_isaac_validation.json"
    report: dict[str, Any] = {
        "schema_version": "ptlc.unilab-isaac-validation.v1",
        "status": "running",
        "control_path": [
            "RuntimeBinding",
            "MaintenanceSession",
            "MoveTargetCommand",
            "MoveItCommissioningAdapter",
            "IsaacGeometryPort",
            "Isaac frame writer",
        ],
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "point_set": str(point_set_path),
        "point_set_sha256": sha256_file(point_set_path),
        "template_root": str(template_root),
        "template_revision": supplied_revision or template_revision(template_root),
        "template_revision_source": (
            "pre-sync-local-git" if supplied_revision else "render-host-git"
        ),
        "template_source_sha256": template_source_hashes(template_root),
        "hardware_connections": "none",
        "authorized_physical_gpu": 1,
        "fps": args.fps,
        "resolution": [args.width, args.height],
        "anti_aliasing": "FXAA",
        "motion_blur": False,
        "requested_targets": list(args.targets),
        "boundary": (
            "Simulation-only, geometry-driven joint interpolation. It validates the "
            "Uni-Lab commissioning command path and approximate recorded joint points, "
            "not MoveIt planning, articulated-body physics, collision-free motion, "
            "Cartesian MoveL fidelity, gripper/instrument interaction, or real hardware."
        ),
    }
    write_json(report_path, report)

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

    frame_metadata: list[dict[str, Any]] = []
    try:
        import carb.settings
        import isaacsim.core.utils.stage as stage_utils
        import omni.replicator.core as rep
        from pxr import Gf

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
            orient_attrs.append(orient_attr)
            base_orients.append(
                Gf.Quatd(
                    float(value.GetReal()),
                    Gf.Vec3d(*[float(component) for component in value.GetImaginary()]),
                )
            )

        rep.orchestrator.set_capture_on_play(False)
        camera = rep.functional.create.camera(
            position=(2.8, -3.35, 2.65),
            look_at=(0.0, 0.0, 1.25),
            parent="/World",
            name="UniLabMotionCamera",
        )
        render_product = rep.create.render_product(camera, (args.width, args.height))
        backend = rep.backends.get("DiskBackend")
        backend.initialize(output_dir=str(frame_directory))
        writer = rep.WriterRegistry.get("BasicWriter")
        writer.initialize(backend=backend, rgb=True)
        writer.attach(render_product)

        def render_joint_frame(
            joint_positions_si: np.ndarray,
            *,
            command_id: str,
            target_ref: str,
            phase: str,
            progress: float,
        ) -> None:
            joint_degrees = np.degrees(joint_positions_si)
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
                            *[float(component) for component in combined.GetImaginary()]
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
            frame_metadata.append(
                {
                    "frame": len(frame_metadata),
                    "command_id": command_id,
                    "target_ref": target_ref,
                    "phase": phase,
                    "progress": progress,
                    "joint_positions_si": joint_positions_si.tolist(),
                    "joint_degrees": joint_degrees.tolist(),
                }
            )

        def render_transition(
            before_values: tuple[float, ...],
            target_values: tuple[float, ...],
            command_id: str,
            target_ref: str,
        ) -> dict[str, Any]:
            before = np.asarray(before_values, dtype=float)
            target = np.asarray(target_values, dtype=float)
            first_frame = len(frame_metadata)
            distance = float(np.max(np.abs(target - before)))
            if distance > 1e-12:
                move_frames = max(1, int(round(args.move_seconds * args.fps)))
                for step in range(1, move_frames + 1):
                    progress = step / move_frames
                    render_joint_frame(
                        smoothstep(before, target, progress),
                        command_id=command_id,
                        target_ref=target_ref,
                        phase=f"move_to_{target_ref.rsplit('.', 1)[-1]}",
                        progress=progress,
                    )
            hold_frames = max(1, int(round(args.hold_seconds * args.fps)))
            for _ in range(hold_frames):
                render_joint_frame(
                    target,
                    command_id=command_id,
                    target_ref=target_ref,
                    phase=f"hold_{target_ref.rsplit('.', 1)[-1]}",
                    progress=1.0,
                )
            return {
                "first_frame": first_frame,
                "last_frame": len(frame_metadata) - 1,
                "frame_count": len(frame_metadata) - first_frame,
                "settlement": "all frames written before completion receipt",
            }

        control_trace = execute_point_sequence(
            point_set=point_set,
            render_transition=render_transition,
            target_refs=tuple(args.targets),
        )
        rep.orchestrator.wait_until_complete()
        writer.detach()
        render_product.destroy()

        images = sorted(frame_directory.glob("rgb*.png"))
        if len(images) != len(frame_metadata):
            raise RuntimeError(
                f"Expected {len(frame_metadata)} PNG frames, found {len(images)}"
            )
        if any(image.stat().st_size == 0 for image in images):
            raise RuntimeError("At least one rendered frame is empty")
        if not control_trace["all_commands_succeeded"]:
            raise RuntimeError("At least one Uni-Lab command did not succeed")
        final_target_ref = args.targets[-1]
        final_group, final_name = final_target_ref.split(".", 1)
        expected_final = tuple(
            float(value)
            for value in point_set["targets"][final_group]["waypoints"][final_name]["value"]
        )
        actual_final = tuple(float(value) for value in control_trace["final_joint_positions_si"])
        if len(actual_final) != 6 or any(
            not math.isclose(actual, expected, abs_tol=1e-12)
            for actual, expected in zip(actual_final, expected_final, strict=True)
        ):
            raise RuntimeError(f"Final Uni-Lab snapshot does not match {final_target_ref}")

        report.update(
            {
                "status": "passed",
                "frame_count": len(frame_metadata),
                "duration_seconds": len(frame_metadata) / args.fps,
                "frames": frame_metadata,
                "frame_files": [str(path) for path in images],
                "frame_bytes_total": sum(path.stat().st_size for path in images),
                "control_trace": control_trace,
                "checks": {
                    "point_set_resolved_against_exact_cr5_model": True,
                    "all_commands_succeeded": True,
                    "completion_receipts_follow_frame_writes": True,
                    "final_snapshot_matches_requested_target": True,
                    "real_hardware_connected": False,
                },
            }
        )
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        write_json(report_path, report)
        simulation_app.close()

    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
