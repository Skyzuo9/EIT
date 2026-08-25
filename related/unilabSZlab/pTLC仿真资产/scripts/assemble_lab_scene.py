from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from trimesh.transformations import euler_matrix, rotation_matrix, translation_matrix


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "pTLC仿真资产"
MANIFEST_PATH = ASSET_ROOT / "asset_manifest.json"
LAYOUT_PATH = ASSET_ROOT / "layout_estimate.json"
INTERACTION_POINTS_PATH = ASSET_ROOT / "interaction_points.json"
RAIL_ANALYSIS_PATH = ASSET_ROOT / "rail_frame_layout_analysis.json"
OUTPUT_GLB = ASSET_ROOT / "lab_scene_approx.glb"
OUTPUT_PREVIEW = ASSET_ROOT / "lab_scene_approx_top.png"
OUTPUT_REPORT = ASSET_ROOT / "lab_scene_build_report.json"
OUTPUT_QC = ASSET_ROOT / "layout_collision_qc.json"


COLORS = {
    "floor": (235, 238, 241, 255),
    "robot": (226, 230, 237, 255),
    "machine_deck": (175, 181, 188, 255),
    "rail_11y": (65, 70, 78, 255),
    "photo_scrape_station": (35, 40, 48, 255),
    "develop_tank_rack": (117, 150, 181, 255),
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rounded(values: np.ndarray, digits: int = 6) -> list[float]:
    return [round(float(value), digits) for value in values]


def pair_key(asset_a: str, asset_b: str) -> tuple[str, str]:
    return tuple(sorted((asset_a, asset_b)))


def intersection_extents(bounds_a: np.ndarray, bounds_b: np.ndarray) -> np.ndarray:
    return np.minimum(bounds_a[1], bounds_b[1]) - np.maximum(bounds_a[0], bounds_b[0])


def intersection_volume(bounds_a: np.ndarray, bounds_b: np.ndarray, tolerance: float = 1e-6) -> float:
    overlap = intersection_extents(bounds_a, bounds_b)
    if np.any(overlap <= tolerance):
        return 0.0
    return float(np.prod(overlap))


def transform_from_pose(position_m: list[float], rpy_deg: list[float]) -> np.ndarray:
    transform = translation_matrix(position_m)
    roll, pitch, yaw = np.deg2rad(np.asarray(rpy_deg, dtype=float))
    return transform @ euler_matrix(roll, pitch, yaw, axes="sxyz")


def apply_color(mesh: trimesh.Trimesh, rgba: tuple[int, int, int, int]) -> None:
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        vertex_colors=np.tile(np.asarray(rgba, dtype=np.uint8), (len(mesh.vertices), 1)),
    )


def add_transformed_scene(
    destination: trimesh.Scene,
    source: trimesh.Scene | trimesh.Trimesh,
    world_transform: np.ndarray,
    prefix: str,
) -> int:
    if isinstance(source, trimesh.Trimesh):
        geometries = [source.copy()]
    else:
        geometries = [geometry.copy() for geometry in source.dump(concatenate=False)]
    for index, geometry in enumerate(geometries):
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        geometry.apply_transform(world_transform)
        name = f"{prefix}__{index:03d}"
        destination.add_geometry(geometry, node_name=name, geom_name=name)
    return len(geometries)


def parse_xyz(value: str | None, default: str = "0 0 0") -> np.ndarray:
    return np.asarray([float(item) for item in (value or default).split()], dtype=float)


def urdf_origin(element: ET.Element | None) -> np.ndarray:
    if element is None:
        return np.eye(4)
    xyz = parse_xyz(element.get("xyz"))
    rpy = parse_xyz(element.get("rpy"))
    return translation_matrix(xyz) @ euler_matrix(*rpy, axes="sxyz")


def resolve_package_mesh(uri: str) -> Path:
    prefix = "package://dobot_rviz/"
    if not uri.startswith(prefix):
        raise ValueError(f"Unsupported mesh URI in local CR5 URDF: {uri}")
    return ROOT / "dobot_rviz" / uri.removeprefix(prefix)


def add_robot_from_urdf(
    scene: trimesh.Scene,
    placement: dict,
) -> dict:
    urdf_path = ROOT / placement["urdf"]
    root = ET.parse(urdf_path).getroot()
    joints: list[dict] = []
    for joint in root.findall("joint"):
        axis_element = joint.find("axis")
        joints.append(
            {
                "name": joint.get("name", ""),
                "type": joint.get("type", "fixed"),
                "parent": joint.find("parent").get("link"),
                "child": joint.find("child").get("link"),
                "origin": urdf_origin(joint.find("origin")),
                "axis": parse_xyz(axis_element.get("xyz") if axis_element is not None else None, "0 0 1"),
            }
        )

    parents = {joint["parent"] for joint in joints}
    children = {joint["child"] for joint in joints}
    root_links = sorted(parents - children)
    if len(root_links) != 1:
        raise RuntimeError(f"Expected one URDF root link, found {root_links}")

    root_world = transform_from_pose(placement["position_m"], placement["rpy_deg"])
    link_transforms = {root_links[0]: root_world}
    remaining = list(joints)
    q_deg = placement["joint_positions_deg"]
    while remaining:
        progressed = False
        for joint in list(remaining):
            parent = joint["parent"]
            if parent not in link_transforms:
                continue
            motion = np.eye(4)
            if joint["type"] in {"revolute", "continuous"}:
                angle = math.radians(float(q_deg.get(joint["name"], 0.0)))
                motion = rotation_matrix(angle, joint["axis"])
            link_transforms[joint["child"]] = link_transforms[parent] @ joint["origin"] @ motion
            remaining.remove(joint)
            progressed = True
        if not progressed:
            raise RuntimeError(f"Could not resolve URDF transform tree: {remaining}")

    mesh_records = []
    for link in root.findall("link"):
        link_name = link.get("name", "")
        if link_name not in link_transforms:
            continue
        for visual_index, visual in enumerate(link.findall("visual")):
            mesh_element = visual.find("geometry/mesh")
            if mesh_element is None:
                continue
            mesh_path = resolve_package_mesh(mesh_element.get("filename", ""))
            mesh = trimesh.load_mesh(mesh_path, process=False)
            if not isinstance(mesh, trimesh.Trimesh):
                raise RuntimeError(f"Robot mesh did not load as Trimesh: {mesh_path}")
            scale = parse_xyz(mesh_element.get("scale"), "1 1 1")
            if not np.allclose(scale, 1.0):
                mesh.apply_scale(scale)
            mesh.apply_transform(link_transforms[link_name] @ urdf_origin(visual.find("origin")))
            apply_color(mesh, COLORS["robot"])
            node_name = f"robot_cr5_proxy__{link_name}__{visual_index}"
            scene.add_geometry(mesh, node_name=node_name, geom_name=node_name)
            mesh_records.append(
                {
                    "link": link_name,
                    "mesh": str(mesh_path.relative_to(ROOT)),
                    "vertices": int(len(mesh.vertices)),
                    "faces": int(len(mesh.faces)),
                }
            )

    return {
        "included": True,
        "urdf": str(urdf_path.relative_to(ROOT)),
        "root_link": root_links[0],
        "joint_count": len(joints),
        "visual_mesh_count": len(mesh_records),
        "joint_positions_deg": q_deg,
        "geometry_status": placement["geometry_status"],
        "kinematic_status": placement["kinematic_status"],
        "meshes": mesh_records,
    }


def draw_top_preview(
    layout: dict,
    dimensions_m: dict[str, np.ndarray],
    rail_analysis: dict,
) -> None:
    width_px, height_px = 1800, 1200
    image = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    floor_w, floor_d = layout["scene"]["floor_size_m"]
    floor_x, floor_y, _ = layout["scene"]["floor_center_m"]
    margin = 100
    scale = min((width_px - 2 * margin) / floor_w, (height_px - 2 * margin) / floor_d)

    def pixel(x: float, y: float) -> tuple[int, int]:
        px = width_px / 2 + (x - floor_x) * scale
        py = height_px / 2 - (y - floor_y) * scale
        return int(round(px)), int(round(py))

    floor_min = pixel(floor_x - floor_w / 2, floor_y + floor_d / 2)
    floor_max = pixel(floor_x + floor_w / 2, floor_y - floor_d / 2)
    draw.rectangle([floor_min, floor_max], fill=(245, 247, 249), outline=(120, 125, 130), width=3)

    for placement in layout["placements"]:
        asset_id = placement["asset_id"]
        dims = dimensions_m[asset_id]
        x, y, _ = placement["position_m"]
        yaw = int(round(placement["rpy_deg"][2])) % 180
        footprint = dims[:2] if yaw == 0 else dims[:2][::-1]
        corner_a = pixel(x - footprint[0] / 2, y + footprint[1] / 2)
        corner_b = pixel(x + footprint[0] / 2, y - footprint[1] / 2)
        rgba = COLORS.get(asset_id, (120, 165, 184, 255))
        fill = tuple(int(0.72 * channel + 0.28 * 255) for channel in rgba[:3])
        draw.rectangle([corner_a, corner_b], fill=fill, outline=rgba[:3], width=3)
        label = asset_id
        if asset_id in {"tool_suction", "tool_large_gripper", "tool_small_gripper"}:
            label = {
                "tool_suction": "suction",
                "tool_large_gripper": "large",
                "tool_small_gripper": "small",
            }[asset_id]
        text_box = draw.textbbox((0, 0), label, font=font)
        text_width = text_box[2] - text_box[0]
        draw.text((pixel(x, y)[0] - text_width / 2, pixel(x, y)[1] - 5), label, fill=(15, 20, 25), font=font)

    cluster_lookup = {
        cluster["cluster_id"]: cluster
        for cluster in rail_analysis["interaction_target_clusters"]
    }
    for marker in layout["interaction_marker_clusters"]:
        cluster = cluster_lookup[marker["cluster_id"]]
        l_mm, n_mm, _ = cluster["interaction_target_cluster_lnz_mm"]["center"]
        center = pixel(l_mm / 1000.0, n_mm / 1000.0)
        color = tuple(marker["color"])
        radius = 7
        draw.ellipse(
            [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
            fill=color,
            outline=(255, 255, 255),
            width=2,
        )
        draw.text((center[0] + 9, center[1] - 7), marker["label"], fill=color, font=font)

    for guide in layout.get("photo_point_surface_guides", []):
        x, y, _ = guide["position_m"]
        center = pixel(x, y)
        radius = 8
        draw.line(
            [(center[0] - radius, center[1]), (center[0] + radius, center[1])],
            fill=(20, 85, 95),
            width=3,
        )
        draw.line(
            [(center[0], center[1] - radius), (center[0], center[1] + radius)],
            fill=(20, 85, 95),
            width=3,
        )

    for marker in layout["rail_station_markers"]["markers"]:
        x, y, _ = marker["position_m"]
        center = pixel(x, y)
        draw.line([(center[0], center[1] - 14), (center[0], center[1] + 14)], fill=(245, 210, 20), width=5)
        slot_label = "/".join(str(slot) for slot in marker["slots"])
        draw.text((center[0] - 8, center[1] + 17), f"R{slot_label}", fill=(120, 90, 0), font=font)

    robot = layout["robot_placement"]
    robot_x, robot_y, _ = robot["position_m"]
    radius = 0.12 * scale
    center = pixel(robot_x, robot_y)
    draw.ellipse(
        [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
        fill=(232, 235, 241),
        outline=(30, 76, 150),
        width=4,
    )
    draw.text((center[0] + radius + 6, center[1] - 7), "CR5 proxy base", fill=(30, 76, 150), font=font)

    origin = pixel(0.0, 0.0)
    x_end = pixel(0.6, 0.0)
    y_end = pixel(0.0, 0.6)
    draw.line([origin, x_end], fill=(200, 35, 55), width=5)
    draw.line([origin, y_end], fill=(40, 150, 75), width=5)
    draw.text((x_end[0] + 6, x_end[1]), "+X", fill=(200, 35, 55), font=font)
    draw.text((y_end[0] + 6, y_end[1]), "+Y", fill=(40, 150, 75), font=font)
    draw.text((margin, 35), "pTLC layout v2 - fitted rail-relative constraint frame (meters, Z-up)", fill=(10, 10, 10), font=font)
    draw.text((margin, 55), "NOT SURVEYED | circles=TCP cluster centroids | crosses=photo/point surface priors", fill=(170, 35, 35), font=font)
    image.save(OUTPUT_PREVIEW)


def add_constraint_markers(scene: trimesh.Scene, layout: dict, rail_analysis: dict) -> dict:
    cluster_lookup = {
        cluster["cluster_id"]: cluster
        for cluster in rail_analysis["interaction_target_clusters"]
    }
    tcp_markers = []
    robot_base_z = float(layout["robot_placement"]["position_m"][2])
    for marker in layout["interaction_marker_clusters"]:
        cluster = cluster_lookup[marker["cluster_id"]]
        l_mm, n_mm, z_mm = cluster["interaction_target_cluster_lnz_mm"]["center"]
        center = np.asarray([l_mm / 1000.0, n_mm / 1000.0, robot_base_z + z_mm / 1000.0])
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=0.016)
        mesh.apply_translation(center)
        apply_color(mesh, tuple(marker["color"] + [255]))
        name = f"constraint_tcp_centroid__{marker['cluster_id']}"
        scene.add_geometry(mesh, node_name=name, geom_name=name)
        tcp_markers.append(
            {
                "cluster_id": marker["cluster_id"],
                "position_m": rounded(center),
                "source_common_lnz_mm": rounded(np.asarray([l_mm, n_mm, z_mm])),
                "boundary": "rail-relative TCP cluster centroid; not a device center or surveyed world point",
            }
        )

    rail_markers = []
    for marker in layout["rail_station_markers"]["markers"]:
        center = np.asarray(marker["position_m"], dtype=float)
        mesh = trimesh.creation.cylinder(radius=0.025, height=0.015, sections=24)
        mesh.apply_translation(center)
        apply_color(mesh, (245, 210, 20, 255))
        slots = "_".join(str(slot) for slot in marker["slots"])
        name = f"constraint_rail_marker__slots_{slots}"
        scene.add_geometry(mesh, node_name=name, geom_name=name)
        rail_markers.append(marker)

    return {
        "tcp_cluster_centroids": tcp_markers,
        "rail_carriage_markers": rail_markers,
        "tcp_marker_z_rule": "scene_z = displayed_robot_base_z + common_controller_z_mm/1000",
        "world_boundary": layout["controller_frame_boundary"]["rule"],
    }


def collision_qc(
    layout: dict,
    placed_component_bounds: dict[str, list[np.ndarray]],
) -> dict:
    allowed_pairs = {
        pair_key(*entry["assets"]): entry["reason"]
        for entry in layout.get("allowed_component_overlaps", [])
    }
    assets = sorted(placed_component_bounds)
    pair_records = []
    unexpected = []
    for index, asset_a in enumerate(assets):
        components_a = placed_component_bounds[asset_a]
        broad_a = np.asarray(
            [
                np.min([bounds[0] for bounds in components_a], axis=0),
                np.max([bounds[1] for bounds in components_a], axis=0),
            ]
        )
        for asset_b in assets[index + 1 :]:
            components_b = placed_component_bounds[asset_b]
            broad_b = np.asarray(
                [
                    np.min([bounds[0] for bounds in components_b], axis=0),
                    np.max([bounds[1] for bounds in components_b], axis=0),
                ]
            )
            broad_volume = intersection_volume(broad_a, broad_b)
            if broad_volume == 0.0:
                continue
            component_hits = []
            component_volume_sum = 0.0
            for component_a, bounds_a in enumerate(components_a):
                for component_b, bounds_b in enumerate(components_b):
                    volume = intersection_volume(bounds_a, bounds_b)
                    if volume > 0.0:
                        component_volume_sum += volume
                        component_hits.append(
                            {
                                "component_a": component_a,
                                "component_b": component_b,
                                "aabb_intersection_volume_m3": round(volume, 9),
                            }
                        )
            key = pair_key(asset_a, asset_b)
            allowed = key in allowed_pairs
            record = {
                "assets": [asset_a, asset_b],
                "broad_aabb_intersection_volume_m3": round(broad_volume, 9),
                "component_aabb_hit_count": len(component_hits),
                "component_aabb_intersection_volume_sum_m3": round(component_volume_sum, 9),
                "allowed_support_or_nested_pair": allowed,
                "allowance_reason": allowed_pairs.get(key),
                "component_hits": component_hits,
            }
            pair_records.append(record)
            if component_hits and not allowed:
                unexpected.append(record)

    return {
        "schema_version": "0.1",
        "method": "asset broad-phase AABB followed by per-visual-component AABB intersections; touching faces within 1e-6 m are ignored",
        "scope_boundary": "Conservative proxy QC only; it is not continuous collision detection and does not certify robot motion.",
        "status": "passed" if not unexpected else "failed",
        "placed_asset_count": len(assets),
        "broad_phase_pair_count": len(pair_records),
        "unexpected_component_overlap_count": len(unexpected),
        "unexpected_overlaps": unexpected,
        "all_broad_phase_pairs": pair_records,
    }


def main() -> None:
    manifest = load_json(MANIFEST_PATH)
    layout = load_json(LAYOUT_PATH)
    points = load_json(INTERACTION_POINTS_PATH)
    rail_analysis = load_json(RAIL_ANALYSIS_PATH)
    assets = {
        asset["asset_id"]: asset
        for group in (manifest["proxy_assets"], manifest["tool_proxies"])
        for asset in group
    }
    dimensions_m = {
        asset_id: np.asarray(asset["dimensions_mm"], dtype=float) / 1000.0
        for asset_id, asset in assets.items()
    }

    scene = trimesh.Scene()
    floor_w, floor_d = layout["scene"]["floor_size_m"]
    floor_h = float(layout["scene"]["floor_thickness_m"])
    floor = trimesh.creation.box(extents=(floor_w, floor_d, floor_h))
    floor.apply_translation(layout["scene"]["floor_center_m"])
    apply_color(floor, COLORS["floor"])
    scene.add_geometry(floor, node_name="lab_floor", geom_name="lab_floor")

    source_checks = []
    placed_assets = []
    placed_component_bounds: dict[str, list[np.ndarray]] = {}
    for placement in layout["placements"]:
        asset_id = placement["asset_id"]
        if asset_id not in assets:
            raise KeyError(f"Layout references unknown manifest asset: {asset_id}")
        source_path = ASSET_ROOT / "proxies" / asset_id / "visual.glb"
        source = trimesh.load(source_path, force="scene", process=False)
        source_extents = np.asarray(source.extents, dtype=float)
        declared = dimensions_m[asset_id]
        max_dimension_error_m = float(np.max(np.abs(source_extents - declared)))
        if max_dimension_error_m > 1e-5:
            raise RuntimeError(
                f"Proxy dimensions do not match manifest for {asset_id}: "
                f"loaded={source_extents}, declared={declared}"
            )
        source_checks.append(
            {
                "asset_id": asset_id,
                "source": str(source_path.relative_to(ROOT)),
                "loaded_extents_m": rounded(source_extents),
                "declared_extents_m": rounded(declared),
                "max_dimension_error_m": round(max_dimension_error_m, 9),
                "passed": True,
            }
        )
        instance_transform = transform_from_pose(placement["position_m"], placement["rpy_deg"])
        geometry_count = add_transformed_scene(scene, source, instance_transform, asset_id)
        component_bounds = []
        for geometry in source.dump(concatenate=False):
            if not isinstance(geometry, trimesh.Trimesh):
                continue
            geometry = geometry.copy()
            geometry.apply_transform(instance_transform)
            component_bounds.append(np.asarray(geometry.bounds, dtype=float))
        placed_component_bounds[asset_id] = component_bounds
        placed_assets.append(
            {
                "asset_id": asset_id,
                "geometry_count": geometry_count,
                "position_m": placement["position_m"],
                "rpy_deg": placement["rpy_deg"],
                "support": placement["support"],
                "layout_confidence": placement["layout_confidence"],
            }
        )

    constraint_markers = add_constraint_markers(scene, layout, rail_analysis)
    robot_report = add_robot_from_urdf(scene, layout["robot_placement"])
    scene.export(OUTPUT_GLB)

    reloaded = trimesh.load(OUTPUT_GLB, force="scene", process=False)
    if not isinstance(reloaded, trimesh.Scene):
        raise RuntimeError("Assembled GLB did not reload as a Trimesh Scene")
    if len(reloaded.geometry) == 0 or not np.isfinite(reloaded.bounds).all():
        raise RuntimeError("Assembled GLB has empty or invalid geometry bounds")

    draw_top_preview(layout, dimensions_m, rail_analysis)

    qc_report = collision_qc(layout, placed_component_bounds)
    with OUTPUT_QC.open("w", encoding="utf-8") as handle:
        json.dump(qc_report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if qc_report["status"] != "passed":
        unexpected_pairs = [
            record["assets"] for record in qc_report["unexpected_overlaps"]
        ]
        raise RuntimeError(f"Unexpected component AABB overlaps: {unexpected_pairs}")

    report = {
        "schema_version": "0.1",
        "status": "passed_with_photo_layout_uncertainty",
        "outputs": {
            "scene_glb": str(OUTPUT_GLB.relative_to(ROOT)),
            "top_preview_png": str(OUTPUT_PREVIEW.relative_to(ROOT)),
            "layout_source": str(LAYOUT_PATH.relative_to(ROOT)),
            "collision_qc": str(OUTPUT_QC.relative_to(ROOT)),
        },
        "coordinate_contract": layout["coordinate_frame"],
        "controller_point_safety_gate": {
            "interaction_points_file": str(INTERACTION_POINTS_PATH.relative_to(ROOT)),
            "source_sha256": points["source"]["sha256"],
            "robot_point_count": points["counts"]["robot_total"],
            "lab_from_controller_transform": None,
            "relative_constraint_frame_used": True,
            "raw_points_inserted_into_scene": 0,
            "rail_relative_cluster_centroids_inserted": len(constraint_markers["tcp_cluster_centroids"]),
            "passed": True,
            "reason": "Raw DOBOT points were not claimed as world coordinates. Only fitted rail-relative TCP cluster centroids are displayed as explicit constraint markers.",
        },
        "constraint_markers": constraint_markers,
        "proxy_source_checks": source_checks,
        "placed_asset_count": len(placed_assets),
        "placed_assets": placed_assets,
        "robot": robot_report,
        "glb_reload_check": {
            "geometry_count": len(reloaded.geometry),
            "bounds_min_m": rounded(reloaded.bounds[0]),
            "bounds_max_m": rounded(reloaded.bounds[1]),
            "extents_m": rounded(reloaded.extents),
            "finite_bounds": bool(np.isfinite(reloaded.bounds).all()),
            "passed": True,
        },
        "collision_qc_summary": {
            "status": qc_report["status"],
            "broad_phase_pair_count": qc_report["broad_phase_pair_count"],
            "unexpected_component_overlap_count": qc_report["unexpected_component_overlap_count"],
        },
        "limitations": [
            "The constraint-frame origin/yaw and most device-body offsets remain inferred from points and three oblique photographs; nothing is surveyed.",
            "The local CR5 articulated mesh is a provisional CR5A visual proxy; its CR5A geometry and calibration are unverified.",
            "The U-shaped development/inventory cluster is assembled on the main deck; its marked TCP planes are stronger evidence than the proxy wall offsets.",
            "Component AABB QC is conservative and can miss non-AABB contacts; allowed support/nesting overlaps are documented in layout_estimate.json.",
            "This scene is suitable for layout blocking and asset replacement, not reachability, collision-clearance, or motion validation.",
        ],
    }
    with OUTPUT_REPORT.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(json.dumps(report["glb_reload_check"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
