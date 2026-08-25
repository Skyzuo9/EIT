"""Blender-side legacy URDF visual compiler used by the local trial.

The script intentionally treats every URDF joint as geometry hierarchy only.
It never publishes joint motion semantics or collision qualification.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import bpy
from mathutils import Euler, Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(argv)


def resolve_mesh(urdf_path: Path, uri: str) -> Path:
    if uri.startswith("package://"):
        rest = uri[len("package://") :]
        _, relative = rest.split("/", 1)
        return (urdf_path.parent.parent / relative).resolve()
    return (urdf_path.parent / uri).resolve()


def vector(text: str | None, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not text:
        return default
    values = tuple(float(part) for part in text.split())
    if len(values) != 3:
        raise ValueError(f"expected three values, got {text!r}")
    return values


def import_stl(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        bpy.ops.import_mesh.stl(filepath=str(path))
    return [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]


def main() -> int:
    args = parse_args()
    urdf_path = Path(args.urdf).resolve()
    output_path = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    root = ET.parse(urdf_path).getroot()
    robot_name = root.attrib.get("name", urdf_path.stem)
    links = {node.attrib["name"]: node for node in root.findall("link")}
    joints = root.findall("joint")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    link_objects: dict[str, bpy.types.Object] = {}
    imported_meshes = 0
    triangle_count = 0
    missing_meshes: list[str] = []

    for index, (link_name, link_node) in enumerate(links.items()):
        empty = bpy.data.objects.new(link_name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty["scene_entity_id"] = f"legacy-link:{index:04d}:{link_name}"
        empty["source_kind"] = "legacy-sw-urdf"
        empty["motion_status"] = "unproven"
        scene.collection.objects.link(empty)
        link_objects[link_name] = empty

        visual = link_node.find("visual")
        mesh = visual.find("geometry/mesh") if visual is not None else None
        if mesh is None or not mesh.attrib.get("filename"):
            continue
        mesh_path = resolve_mesh(urdf_path, mesh.attrib["filename"])
        if not mesh_path.exists():
            missing_meshes.append(str(mesh_path))
            continue
        imported = import_stl(mesh_path)
        for mesh_index, obj in enumerate(imported):
            obj.name = f"{link_name}__visual" if mesh_index == 0 else f"{link_name}__visual_{mesh_index}"
            obj.parent = empty
            obj["scene_entity_id"] = empty["scene_entity_id"]
            obj["geometry_role"] = "visual"
            obj["source_mesh"] = mesh.attrib["filename"]
            imported_meshes += 1
            triangle_count += sum(len(poly.vertices) - 2 for poly in obj.data.polygons)

    child_links: set[str] = set()
    for joint in joints:
        parent = joint.find("parent").attrib["link"]
        child = joint.find("child").attrib["link"]
        child_links.add(child)
        child_obj = link_objects[child]
        child_obj.parent = link_objects[parent]
        origin = joint.find("origin")
        xyz = vector(origin.attrib.get("xyz") if origin is not None else None, (0.0, 0.0, 0.0))
        rpy = vector(origin.attrib.get("rpy") if origin is not None else None, (0.0, 0.0, 0.0))
        child_obj.location = Vector(xyz)
        child_obj.rotation_euler = Euler(rpy, "XYZ")
        child_obj["source_joint"] = joint.attrib.get("name", "")
        child_obj["source_joint_type"] = joint.attrib.get("type", "")

    root_links = sorted(set(links) - child_links)
    if len(root_links) != 1:
        raise RuntimeError(f"expected exactly one root link, found {root_links}")
    if missing_meshes:
        raise FileNotFoundError("missing visual meshes: " + ", ".join(missing_meshes))

    bpy.context.view_layer.update()
    mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    world_points = [obj.matrix_world @ Vector(corner) for obj in mesh_objects for corner in obj.bound_box]
    if world_points:
        minimum = [min(point[i] for point in world_points) for i in range(3)]
        maximum = [max(point[i] for point in world_points) for i in range(3)]
    else:
        minimum = maximum = [0.0, 0.0, 0.0]

    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        use_selection=False,
        export_animations=False,
        export_skins=False,
        export_cameras=False,
        export_lights=False,
        export_yup=True,
        export_extras=True,
    )

    report = {
        "schema": "lab.render_capture/v0",
        "source_kind": "legacy-sw-urdf",
        "robot_name": robot_name,
        "root_link": root_links[0],
        "link_count": len(links),
        "source_joint_count": len(joints),
        "imported_mesh_objects": imported_meshes,
        "triangle_count": triangle_count,
        "bounds_source_z_up_m": {"min": minimum, "max": maximum},
        "exported_glb": str(output_path),
        "animations_exported": False,
        "skins_exported": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TRIAL_BLENDER_RESULT=" + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
