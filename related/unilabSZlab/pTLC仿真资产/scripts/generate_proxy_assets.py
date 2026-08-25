from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "pTLC仿真资产"
MANIFEST_PATH = ASSET_ROOT / "asset_manifest.json"
OUTPUT_ROOT = ASSET_ROOT / "proxies"


COLORS = {
    "steel": (184, 190, 196, 255),
    "dark": (30, 34, 40, 255),
    "white": (232, 234, 238, 255),
    "blue": (38, 96, 180, 255),
    "red": (200, 35, 55, 255),
    "green": (40, 190, 90, 255),
    "amber": (138, 81, 33, 255),
}


def colored(mesh: trimesh.Trimesh, color: tuple[int, int, int, int]) -> trimesh.Trimesh:
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        vertex_colors=np.tile(np.asarray(color, dtype=np.uint8), (len(mesh.vertices), 1)),
    )
    return mesh


def box(extents: tuple[float, float, float], center: tuple[float, float, float], color) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    return colored(mesh, color)


def cylinder(radius: float, height: float, center: tuple[float, float, float], color) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=24)
    mesh.apply_translation(center)
    return colored(mesh, color)


def add(scene: trimesh.Scene, name: str, mesh: trimesh.Trimesh) -> None:
    scene.add_geometry(mesh, node_name=name, geom_name=name)


def frame(
    scene: trimesh.Scene,
    width: float,
    depth: float,
    height: float,
    prefix: str = "frame",
    center_x: float = 0.0,
) -> None:
    p = 0.04
    for ix, x in enumerate((center_x - width / 2 + p / 2, center_x + width / 2 - p / 2)):
        for iy, y in enumerate((-depth / 2 + p / 2, depth / 2 - p / 2)):
            add(scene, f"{prefix}-post-{ix}-{iy}", box((p, p, height), (x, y, height / 2), COLORS["steel"]))
    for z in (p / 2, height - p / 2):
        for iy, y in enumerate((-depth / 2 + p / 2, depth / 2 - p / 2)):
            add(
                scene,
                f"{prefix}-beam-x-{z}-{iy}",
                box((width, p, p), (center_x, y, z), COLORS["steel"]),
            )
        for ix, x in enumerate((center_x - width / 2 + p / 2, center_x + width / 2 - p / 2)):
            add(
                scene,
                f"{prefix}-beam-y-{z}-{ix}",
                box((p, depth, p), (x, 0, z), COLORS["steel"]),
            )


def build_box(w: float, d: float, h: float) -> trimesh.Scene:
    scene = trimesh.Scene()
    add(scene, "body", box((w, d, h), (0, 0, h / 2), COLORS["steel"]))
    return scene


def build_enclosure(w: float, d: float, h: float) -> trimesh.Scene:
    scene = build_box(w, d, h)
    add(scene, "front-window", box((w * 0.7, 0.015, h * 0.45), (0, -d / 2 - 0.008, h * 0.55), (80, 100, 110, 130)))
    return scene


def build_rail(w: float, d: float, h: float) -> trimesh.Scene:
    scene = trimesh.Scene()
    add(scene, "rail-base", box((w, d, h * 0.45), (0, 0, h * 0.225), COLORS["steel"]))
    add(scene, "guide-left", box((w, d * 0.12, h * 0.22), (0, -d * 0.28, h * 0.62), COLORS["dark"]))
    add(scene, "guide-right", box((w, d * 0.12, h * 0.22), (0, d * 0.28, h * 0.62), COLORS["dark"]))
    add(scene, "carriage", box((w * 0.18, d * 1.25, h * 0.35), (0, 0, h * 0.82), COLORS["white"]))
    return scene


def build_station(w: float, d: float, h: float) -> trimesh.Scene:
    scene = trimesh.Scene()
    frame(scene, w, d, h)
    add(scene, "deck", box((w * 0.92, d * 0.92, 0.035), (0, 0, h * 0.38), COLORS["white"]))
    add(scene, "gantry", box((w * 0.72, 0.07, 0.07), (0, 0, h * 0.82), COLORS["steel"]))
    return scene


def build_feed_lift(w: float, d: float, h: float) -> trimesh.Scene:
    scene = build_station(w, d, h)
    for idx in range(6):
        z = h * (0.14 + idx * 0.10)
        add(scene, f"plate-{idx}", box((w * 0.68, d * 0.62, 0.012), (0, 0, z), COLORS["white"]))
    add(scene, "vertical-slide", box((0.08, d * 0.22, h * 0.78), (w * 0.34, 0, h * 0.48), COLORS["dark"]))
    return scene


def build_develop_tank_rack(w: float, d: float, h: float) -> trimesh.Scene:
    scene = trimesh.Scene()
    # Photos 2/3 and the rail-compensated P11-P18 targets show two opposing
    # four-level side banks with an open robot corridor between them.  Keep
    # each side bank narrow enough that the combined proxy does not close that
    # U-shaped cavity when the asset is rotated into the scene.
    tower_w = w * 0.30
    for col, x in enumerate((-w * 0.35, w * 0.35)):
        frame(scene, tower_w, d, h, f"tower-{col}", center_x=x)
        for row in range(4):
            z = h * (0.13 + row * 0.215)
            add(scene, f"tank-{col}-{row}", box((tower_w * 0.76, d * 0.68, h * 0.12), (x, 0, z), COLORS["white"]))
            add(scene, f"lid-{col}-{row}", box((tower_w * 0.82, d * 0.74, 0.025), (x, 0, z + h * 0.075), COLORS["steel"]))
    return scene


def build_rack(w: float, d: float, h: float, rows: int, cols: int) -> trimesh.Scene:
    scene = trimesh.Scene()
    frame(scene, w, d, h)
    for row in range(rows):
        z = h * (0.12 + row * (0.78 / max(1, rows - 1))) if rows > 1 else h * 0.48
        add(scene, f"shelf-{row}", box((w * 0.9, d * 0.88, 0.025), (0, 0, z), COLORS["white"]))
        for col in range(cols):
            x = (col - (cols - 1) / 2) * (w * 0.72 / max(1, cols - 1)) if cols > 1 else 0
            add(scene, f"slot-{row}-{col}", box((w * 0.20, d * 0.56, 0.035), (x, 0, z + 0.03), COLORS["steel"]))
    return scene


def build_photo_scrape(w: float, d: float, h: float) -> trimesh.Scene:
    scene = trimesh.Scene()
    add(scene, "black-enclosure", box((w * 0.62, d * 0.88, h), (-w * 0.18, 0, h / 2), COLORS["dark"]))
    add(scene, "plate-stage", box((w * 0.64, d * 0.58, 0.035), (w * 0.22, 0, h * 0.27), COLORS["white"]))
    add(scene, "z-column", box((0.10, d * 0.32, h * 0.74), (w * 0.37, 0, h * 0.50), COLORS["steel"]))
    add(scene, "sensor-head", box((w * 0.18, d * 0.10, h * 0.06), (w * 0.32, -d * 0.26, h * 0.55), COLORS["red"]))
    add(scene, "overhead-camera", box((w * 0.20, d * 0.15, h * 0.12), (w * 0.10, 0, h * 0.86), COLORS["dark"]))
    return scene


def build_fixture(w: float, d: float, h: float) -> trimesh.Scene:
    scene = trimesh.Scene()
    add(scene, "base", box((w, d, h * 0.10), (0, 0, h * 0.05), COLORS["steel"]))
    add(scene, "left-jaw", box((w * 0.12, d * 0.72, h * 0.52), (-w * 0.30, 0, h * 0.36), COLORS["white"]))
    add(scene, "right-jaw", box((w * 0.12, d * 0.72, h * 0.52), (w * 0.30, 0, h * 0.36), COLORS["white"]))
    add(scene, "cup", cylinder(min(w, d) * 0.10, h * 0.32, (0, 0, h * 0.30), COLORS["amber"]))
    return scene


def build_collection_station(w: float, d: float, h: float) -> trimesh.Scene:
    scene = build_station(w, d, h)
    add(scene, "bottle", cylinder(min(w, d) * 0.08, h * 0.28, (-w * 0.18, 0, h * 0.20), COLORS["amber"]))
    add(scene, "collector", cylinder(min(w, d) * 0.07, h * 0.22, (w * 0.18, 0, h * 0.18), COLORS["white"]))
    add(scene, "press", cylinder(min(w, d) * 0.045, h * 0.36, (w * 0.18, 0, h * 0.62), COLORS["steel"]))
    return scene


def build_tool(w: float, d: float, h: float, asset_id: str) -> trimesh.Scene:
    scene = trimesh.Scene()
    add(scene, "quick-coupler", cylinder(min(w, d) * 0.34, h * 0.20, (0, 0, h * 0.90), COLORS["dark"]))
    if asset_id == "tool_suction":
        add(scene, "beam", box((w, d * 0.25, h * 0.10), (0, 0, h * 0.62), COLORS["steel"]))
        for x in (-w * 0.32, w * 0.32):
            add(scene, f"cup-{x}", cylinder(min(w, d) * 0.18, h * 0.42, (x, 0, h * 0.28), COLORS["blue"]))
    else:
        add(scene, "body", box((w * 0.55, d * 0.70, h * 0.40), (0, 0, h * 0.62), COLORS["steel"]))
        for x in (-w * 0.34, w * 0.34):
            add(scene, f"finger-{x}", box((w * 0.16, d * 0.28, h * 0.48), (x, 0, h * 0.24), COLORS["dark"]))
    return scene


def make_scene(asset: dict) -> trimesh.Scene:
    w, d, h = [float(value) / 1000.0 for value in asset["dimensions_mm"]]
    template = asset.get("template", "box")
    if template == "rail":
        return build_rail(w, d, h)
    if template == "station":
        return build_station(w, d, h)
    if template == "enclosure":
        return build_enclosure(w, d, h)
    if template == "feed_lift":
        return build_feed_lift(w, d, h)
    if template == "develop_tank_rack":
        return build_develop_tank_rack(w, d, h)
    if template == "rack_4x3":
        return build_rack(w, d, h, rows=4, cols=3)
    if template == "rack_2x3":
        return build_rack(w, d, h, rows=2, cols=3)
    if template == "photo_scrape":
        return build_photo_scrape(w, d, h)
    if template == "fixture":
        return build_fixture(w, d, h)
    if template == "collection_station":
        return build_collection_station(w, d, h)
    return build_box(w, d, h)


def fit_scene_to_dimensions(scene: trimesh.Scene, width: float, depth: float, height: float) -> None:
    """Normalize a stylized visual proxy to its declared metric envelope."""
    bounds = scene.bounds
    current = bounds[1] - bounds[0]
    target = np.asarray((width, depth, height), dtype=float)
    transform = np.eye(4)
    transform[:3, :3] = np.diag(target / current)
    scene.apply_transform(transform)
    fitted = scene.bounds
    center_xy = (fitted[0, :2] + fitted[1, :2]) / 2.0
    translation = np.eye(4)
    translation[:3, 3] = (-center_xy[0], -center_xy[1], -fitted[0, 2])
    scene.apply_transform(translation)


OPEN_COLLISION_TEMPLATES = {
    "station",
    "feed_lift",
    "develop_tank_rack",
    "rack_4x3",
    "rack_2x3",
    "collection_station",
}

SHAPED_COLLISION_TEMPLATES = {"fixture"}


def scene_components(scene: trimesh.Scene) -> list[trimesh.Trimesh]:
    """Return transformed, disconnected mesh bodies from a scene."""
    dumped = scene.dump(concatenate=False)
    return [geometry.copy() for geometry in dumped if isinstance(geometry, trimesh.Trimesh)]


def open_frame_collision(width: float, depth: float, height: float) -> list[trimesh.Trimesh]:
    """Four non-intersecting posts that retain the full station envelope."""
    post = min(0.04, width * 0.15, depth * 0.15)
    return [
        trimesh.creation.box(
            extents=(post, post, height),
            transform=trimesh.transformations.translation_matrix((x, y, height / 2.0)),
        )
        for x in (-width / 2.0 + post / 2.0, width / 2.0 - post / 2.0)
        for y in (-depth / 2.0 + post / 2.0, depth / 2.0 - post / 2.0)
    ]


def inner_box_collision(
    width: float,
    depth: float,
    height: float,
    center: tuple[float, float, float],
) -> trimesh.Trimesh:
    return trimesh.creation.box(
        extents=(width, depth, height),
        transform=trimesh.transformations.translation_matrix(center),
    )


def open_collision_components(asset: dict, width: float, depth: float, height: float) -> list[trimesh.Trimesh]:
    """Create disjoint collision primitives for stations with traversable cavities."""
    template = asset.get("template")
    parts = open_frame_collision(width, depth, height)
    post = min(0.04, width * 0.15, depth * 0.15)
    gap = max(0.002, min(width, depth) * 0.01)
    inner_w = max(0.001, width - 2.0 * (post + gap))
    inner_d = max(0.001, depth - 2.0 * (post + gap))

    if template == "station":
        parts.append(inner_box_collision(inner_w, inner_d, 0.035, (0, 0, height * 0.38)))
        parts.append(inner_box_collision(inner_w * 0.78, 0.04, 0.06, (0, 0, height * 0.82)))
        return parts

    if template == "feed_lift":
        plate_h = min(0.012, height * 0.02)
        for idx in range(6):
            z = height * (0.14 + idx * 0.10)
            parts.append(inner_box_collision(inner_w * 0.78, inner_d * 0.78, plate_h, (0, 0, z)))
        return parts

    if template == "develop_tank_rack":
        # Rebuild as two independent four-post towers plus eight inset tank bodies.
        parts = []
        tower_w = width * 0.30
        tower_center = width * 0.35
        for x_center in (-tower_center, tower_center):
            for local_x in (-tower_w / 2.0 + post / 2.0, tower_w / 2.0 - post / 2.0):
                for y in (-depth / 2.0 + post / 2.0, depth / 2.0 - post / 2.0):
                    parts.append(
                        inner_box_collision(post, post, height, (x_center + local_x, y, height / 2.0))
                    )
            tank_w = max(0.001, tower_w - 2.0 * (post + gap))
            tank_d = inner_d * 0.80
            tank_h = height * 0.12
            for row in range(4):
                z = height * (0.13 + row * 0.215)
                parts.append(inner_box_collision(tank_w, tank_d, tank_h, (x_center, 0, z)))
        return parts

    if template in {"rack_4x3", "rack_2x3"}:
        rows = 4 if template == "rack_4x3" else 2
        shelf_h = min(0.025, height * 0.07)
        for row in range(rows):
            z = height * (0.12 + row * (0.78 / max(1, rows - 1))) if rows > 1 else height * 0.48
            parts.append(inner_box_collision(inner_w, inner_d, shelf_h, (0, 0, z)))
        return parts

    if template == "collection_station":
        deck_h = min(0.035, height * 0.05)
        deck_z = height * 0.38
        parts.append(inner_box_collision(inner_w, inner_d, deck_h, (0, 0, deck_z)))
        radius = min(width, depth) * 0.07
        press = trimesh.creation.cylinder(radius=radius, height=height * 0.30, sections=24)
        press.apply_translation((width * 0.18, 0, height * 0.65))
        parts.append(press)
        return parts

    raise ValueError(f"No open collision recipe for template: {template}")


def collision_components(
    asset: dict,
    visual_scene: trimesh.Scene,
    width: float,
    depth: float,
    height: float,
) -> tuple[list[trimesh.Trimesh], str, bool]:
    """Build one or more closed collision bodies while retaining one-STL-per-asset output."""
    template = asset.get("template", "box")
    if template in OPEN_COLLISION_TEMPLATES:
        return open_collision_components(asset, width, depth, height), "multi_body_open", True
    if template in SHAPED_COLLISION_TEMPLATES or asset["asset_id"].startswith("tool_"):
        return scene_components(visual_scene), "multi_body_shaped", False
    solid = trimesh.creation.box(extents=(width, depth, height))
    solid.apply_translation((0, 0, height / 2.0))
    return [solid], "solid_aabb", False


def rounded(values: np.ndarray, digits: int = 6) -> list[float]:
    return [round(float(value), digits) for value in values]


def connected_shell_count(mesh: trimesh.Trimesh) -> int:
    """Count face components without scipy/networkx optional dependencies."""
    face_count = len(mesh.faces)
    if face_count == 0:
        return 0
    parent = list(range(face_count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    first_face_for_vertex: dict[int, int] = {}
    for face_index, face in enumerate(mesh.faces):
        for vertex_index in face:
            vertex_index = int(vertex_index)
            if vertex_index in first_face_for_vertex:
                union(face_index, first_face_for_vertex[vertex_index])
            else:
                first_face_for_vertex[vertex_index] = face_index
    return len({find(index) for index in range(face_count)})


def components_have_disjoint_aabbs(components: list[trimesh.Trimesh], tolerance: float = 1e-9) -> bool:
    """Check that component interiors do not overlap; touching faces are allowed."""
    for left_index, left in enumerate(components):
        for right in components[left_index + 1 :]:
            overlap = np.minimum(left.bounds[1], right.bounds[1]) - np.maximum(
                left.bounds[0], right.bounds[0]
            )
            if np.all(overlap > tolerance):
                return False
    return True


def collision_qc(
    asset: dict,
    collision_path: Path,
    components_m: list[trimesh.Trimesh],
    mode: str,
    open_cavity_expected: bool,
) -> dict:
    """Validate the actual STL after its millimetre-unit round trip."""
    loaded = trimesh.load_mesh(collision_path, file_type="stl", process=True)
    if not isinstance(loaded, trimesh.Trimesh):
        raise RuntimeError(f"Collision STL did not reload as a mesh: {collision_path}")

    target_mm = np.asarray(asset["dimensions_mm"], dtype=float)
    bounds_mm = loaded.bounds
    extents_mm = bounds_mm[1] - bounds_mm[0]
    envelope_volume_m3 = float(np.prod(target_mm / 1000.0))
    component_volume_m3 = float(sum(abs(component.volume) for component in components_m))
    volume_ratio = component_volume_m3 / envelope_volume_m3 if envelope_volume_m3 else 0.0
    component_count = len(components_m)
    components_watertight = [bool(component.is_watertight) for component in components_m]
    source_components_disjoint = components_have_disjoint_aabbs(components_m)
    reloaded_shell_count = connected_shell_count(loaded)
    cavity_preserved = (
        bool(component_count > 1 and volume_ratio < 0.70) if open_cavity_expected else None
    )

    return {
        "asset_id": asset["asset_id"],
        "collision_stl": str(collision_path.relative_to(ROOT)),
        "stl_units": "mm",
        "collision_mode": mode,
        "component_count": component_count,
        "connected_shell_count_after_stl_reload": reloaded_shell_count,
        "all_source_components_watertight": all(components_watertight),
        "source_components_aabb_disjoint": source_components_disjoint,
        "watertight_after_stl_reload": bool(loaded.is_watertight),
        "bounds_mm": [rounded(bounds_mm[0], 3), rounded(bounds_mm[1], 3)],
        "extents_mm": rounded(extents_mm, 3),
        "target_dimensions_mm": asset["dimensions_mm"],
        "bounds_match_target": bool(np.allclose(extents_mm, target_mm, atol=0.01, rtol=0.0)),
        "summed_component_volume_ratio": round(volume_ratio, 6),
        "open_cavity_expected": open_cavity_expected,
        "open_cavity_preserved": cavity_preserved,
        "cavity_check": (
            "pass when collision uses multiple closed bodies and their summed volume is below 70% of the envelope; "
            "overlap volumes are not boolean-unioned"
            if open_cavity_expected
            else "not applicable to conservative solid or non-station shaped collision"
        ),
    }


def export_asset(asset: dict) -> tuple[dict, dict]:
    asset_id = asset["asset_id"]
    output_dir = OUTPUT_ROOT / asset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    scene = build_tool(*[float(value) / 1000.0 for value in asset["dimensions_mm"]], asset_id) if asset_id.startswith("tool_") else make_scene(asset)
    w, d, h = [float(value) / 1000.0 for value in asset["dimensions_mm"]]
    fit_scene_to_dimensions(scene, w, d, h)
    glb = scene.export(file_type="glb")
    if not isinstance(glb, bytes):
        raise RuntimeError(f"GLB export failed for {asset_id}")
    glb_path = output_dir / "visual.glb"
    glb_path.write_bytes(glb)

    collision_parts, collision_mode, open_cavity_expected = collision_components(asset, scene, w, d, h)
    if not collision_parts:
        raise RuntimeError(f"No collision components generated for {asset_id}")
    generated_component_count = len(collision_parts)
    if open_cavity_expected and generated_component_count < 2:
        raise RuntimeError(
            f"Open collision for {asset_id} unexpectedly collapsed to "
            f"{generated_component_count} components"
        )
    collision = trimesh.util.concatenate(collision_parts)
    collision_path = output_dir / "collision.stl"
    collision_mm = collision.copy()
    collision_mm.apply_scale(1000.0)
    collision_path.write_bytes(collision_mm.export(file_type="stl"))

    qc = collision_qc(
        asset,
        collision_path,
        collision_parts,
        collision_mode,
        open_cavity_expected,
    )
    if qc["component_count"] != generated_component_count:
        raise RuntimeError(
            f"QC component count changed for {asset_id}: "
            f"generated={generated_component_count}, qc={qc['component_count']}"
        )

    bounds = scene.bounds
    result = {
        "asset_id": asset_id,
        "visual_glb": str(glb_path.relative_to(ROOT)),
        "collision_stl": str(collision_path.relative_to(ROOT)),
        "visual_extents_m": [round(float(value), 6) for value in (bounds[1] - bounds[0])],
        "target_dimensions_mm": asset["dimensions_mm"],
        "collision_mode": qc["collision_mode"],
        "collision_component_count": qc["component_count"],
        "collision_watertight": qc["watertight_after_stl_reload"],
        "collision_bounds_match_target": qc["bounds_match_target"],
        "open_cavity_preserved": qc["open_cavity_preserved"],
    }
    return result, qc


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assets = manifest["proxy_assets"] + manifest["tool_proxies"]
    results = []
    qc_results = []
    for asset in assets:
        result, qc = export_asset(asset)
        results.append(result)
        qc_results.append(qc)
    (ASSET_ROOT / "proxy_build_report.json").write_text(
        json.dumps({"count": len(results), "assets": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (ASSET_ROOT / "collision_qc_report.json").write_text(
        json.dumps(
            {
                "count": len(qc_results),
                "all_watertight": all(item["watertight_after_stl_reload"] for item in qc_results),
                "all_bounds_match_target": all(item["bounds_match_target"] for item in qc_results),
                "all_expected_cavities_preserved": all(
                    item["open_cavity_preserved"] is not False for item in qc_results
                ),
                "all_open_source_components_disjoint": all(
                    (not item["open_cavity_expected"]) or item["source_components_aabb_disjoint"]
                    for item in qc_results
                ),
                "assets": qc_results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"count": len(results), "output": str(OUTPUT_ROOT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
