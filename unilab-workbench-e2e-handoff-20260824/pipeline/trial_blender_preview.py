"""Render a deterministic Workbench-style preview for GLB QA."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    if not points:
        raise RuntimeError(f"no renderable mesh objects in {input_path}")
    minimum = Vector([min(point[index] for point in points) for index in range(3)])
    maximum = Vector([max(point[index] for point in points) for index in range(3)])
    center = (minimum + maximum) * 0.5
    extent = maximum - minimum
    radius = max(extent.length * 0.5, 0.05)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.background_type = "THEME"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    camera_data = bpy.data.cameras.new("qa_camera")
    camera = bpy.data.objects.new("qa_camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    direction = Vector((1.35, -1.65, 1.05)).normalized()
    camera.location = center + direction * radius * 3.2
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 52
    camera_data.clip_start = max(radius / 1000.0, 0.0001)
    camera_data.clip_end = max(radius * 20.0, 100.0)

    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)

    report = {
        "schema": "lab.render_preview_report/v0",
        "input": str(input_path),
        "output": str(output_path),
        "mesh_objects": len(meshes),
        "triangle_count": sum(sum(len(poly.vertices) - 2 for poly in obj.data.polygons) for obj in meshes),
        "bounds_m": {"min": list(minimum), "max": list(maximum), "extent": list(extent)},
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TRIAL_PREVIEW_RESULT=" + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
