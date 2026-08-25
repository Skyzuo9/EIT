#!/usr/bin/env python3
"""Render evidence-bounded still views of the pTLC Isaac Sim scene."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

VIEWS = (
    {
        "name": "01_scene_overview",
        "eye": [3.2, -3.8, 3.0],
        "target": [0.2, 0.0, 0.9],
    },
    {
        "name": "02_robot_and_rail",
        "eye": [2.0, -2.6, 1.8],
        "target": [0.1, 0.0, 0.75],
    },
    {
        "name": "03_scene_top",
        "eye": [0.0, 0.0, 6.5],
        "target": [0.0, 0.0, 0.0],
    },
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--input-validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get("OMNI_KIT_ACCEPT_EULA", "").strip().lower() not in {
        "1",
        "y",
        "yes",
    }:
        raise RuntimeError("Explicit NVIDIA Omniverse EULA acceptance is required")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "1":
        raise RuntimeError("This renderer is authorized only with CUDA_VISIBLE_DEVICES=1")

    scene = args.scene.resolve()
    input_validation = args.input_validation.resolve()
    output = args.output.resolve()
    if not scene.is_file() or not input_validation.is_file():
        raise FileNotFoundError("Scene or input-validation report is missing")
    output.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "headless": True,
            "width": 1280,
            "height": 720,
            "active_gpu": 1,
            "physics_gpu": 0,
            "extra_args": [
                "--/renderer/multiGpu/autoEnable=false",
                "--/renderer/multiGpu/enabled=false",
                "--/renderer/multiGpu/maxGpuCount=1",
                "--/isaac/startup/ros_bridge_extension=",
            ],
        }
    )

    report: dict[str, Any] = {
        "schema_version": "ptlc.isaac.still-views.v1",
        "status": "running",
        "scene": str(scene),
        "hardware_connections": "none",
        "authorized_physical_gpu": 1,
        "views": [],
        "boundary": (
            "Rendered static stills of an approximate proxy scene, provisional CR5 "
            "model, and evidence-bounded point markers. "
            "They are not evidence that WebRTC streaming, collision-free motion, or "
            "real-device execution succeeded."
        ),
    }
    report_path = output / "capture_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    try:
        import isaacsim.core.utils.stage as stage_utils
        import omni.replicator.core as rep

        print(f"Opening stage: {scene}", flush=True)
        if not stage_utils.open_stage(str(scene)):
            raise RuntimeError(f"Could not open scene: {scene}")
        print("Stage opened; warming viewport", flush=True)
        for _ in range(60):
            simulation_app.update()

        rep.orchestrator.set_capture_on_play(False)
        render_products = []
        writers = []
        raw_directories = []
        for index, view in enumerate(VIEWS):
            raw_directory = output / f"raw_{index:02d}"
            raw_directory.mkdir(exist_ok=True)
            camera = rep.functional.create.camera(
                position=tuple(view["eye"]),
                look_at=tuple(view["target"]),
                parent="/World",
                name=f"CaptureCamera_{index:02d}",
            )
            render_product = rep.create.render_product(camera, (1280, 720))
            backend = rep.backends.get("DiskBackend")
            backend.initialize(output_dir=str(raw_directory))
            writer = rep.WriterRegistry.get("BasicWriter")
            writer.initialize(backend=backend, rgb=True)
            writer.attach(render_product)
            render_products.append(render_product)
            writers.append(writer)
            raw_directories.append(raw_directory)

        print("Capturing three Replicator render products", flush=True)
        rep.orchestrator.step(rt_subframes=8, delta_time=0.0, pause_timeline=True)
        rep.orchestrator.wait_until_complete()

        for view, writer, render_product, raw_directory in zip(
            VIEWS, writers, render_products, raw_directories, strict=True
        ):
            candidates = sorted(raw_directory.glob("rgb*.png"))
            if len(candidates) != 1 or candidates[0].stat().st_size == 0:
                raise RuntimeError(
                    f"Expected one RGB image in {raw_directory}, got {candidates}"
                )
            image_path = output / f"{view['name']}.png"
            shutil.copy2(candidates[0], image_path)
            report["views"].append(
                {
                    "path": str(image_path),
                    "bytes": image_path.stat().st_size,
                    "eye": view["eye"],
                    "target": view["target"],
                }
            )
            writer.detach()
            render_product.destroy()

        report["status"] = "passed"
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
