#!/usr/bin/env python3
"""Render a clearly labelled CR5 multi-point kinematic preview without Isaac.

This is a software-rasterized preview for reviewing the recorded joint sequence
while the shared Isaac GPU is busy.  It deliberately does not claim collision,
dynamics, controller-frame, or Isaac-render validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POINT_SET = ROOT / "pTLC仿真资产/isaac_sim/config/cr5_ptlc_area7_points.v1.json"
DEFAULT_LAYOUT = ROOT / "pTLC仿真资产/layout_estimate.json"
DEFAULT_MANIFEST = ROOT / "pTLC仿真资产/asset_manifest.json"
DEFAULT_URDF = ROOT / "dobot_rviz/urdf/cr5_robot.urdf"
DEFAULT_OUTPUT = (
    ROOT
    / "pTLC仿真资产/isaac_sim/output/area7_multipt_kinematic_preview_20260814"
)
DEFAULT_SEQUENCE = [
    "P45",
    "P46",
    "P47",
    "P48",
    "P80",
    "P79",
    "P78",
    "P45",
    "P49",
    "P50",
    "P51",
    "P83",
    "P82",
    "P81",
    "P45",
]


COLORS = {
    "machine_deck": (103, 116, 137),
    "rail_11y": (72, 78, 88),
    "photo_scrape_station": (111, 94, 174),
    "powder_collector_fixture": (145, 126, 193),
    "sampling_station": (39, 133, 183),
    "staging_a_6slot": (75, 164, 209),
    "feed_lift": (52, 156, 132),
    "collection_station": (40, 153, 101),
    "staging_b_6slot": (74, 181, 128),
    "tool_station": (207, 85, 77),
    "develop_tank_rack": (48, 109, 188),
    "group_rack_4x3": (38, 142, 150),
}
JOINT_COLORS = [
    (55, 126, 184),
    (255, 127, 14),
    (44, 160, 44),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        try:
            index = 1 if bold and candidate.endswith(".ttc") else 0
            return ImageFont.truetype(candidate, size=size, index=index)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def translation(xyz: np.ndarray) -> np.ndarray:
    result = np.eye(4)
    result[:3, 3] = xyz
    return result


def rpy_matrix(rpy: np.ndarray) -> np.ndarray:
    roll, pitch, yaw = rpy
    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
    result = np.eye(4)
    result[:3, :3] = rz @ ry @ rx
    return result


def axis_rotation(angle: float, axis: np.ndarray) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    one_c = 1.0 - c
    rotation = np.array(
        [
            [c + x * x * one_c, x * y * one_c - z * s, x * z * one_c + y * s],
            [y * x * one_c + z * s, c + y * y * one_c, y * z * one_c - x * s],
            [z * x * one_c - y * s, z * y * one_c + x * s, c + z * z * one_c],
        ]
    )
    result = np.eye(4)
    result[:3, :3] = rotation
    return result


def parse_vector(value: str | None, default: str = "0 0 0") -> np.ndarray:
    return np.asarray([float(item) for item in (value or default).split()], dtype=float)


def origin_transform(element: ET.Element | None) -> np.ndarray:
    if element is None:
        return np.eye(4)
    return translation(parse_vector(element.get("xyz"))) @ rpy_matrix(
        parse_vector(element.get("rpy"))
    )


@dataclass
class Joint:
    name: str
    kind: str
    parent: str
    child: str
    origin: np.ndarray
    axis: np.ndarray


class RobotKinematics:
    def __init__(self, urdf: Path, placement: dict):
        root = ET.parse(urdf).getroot()
        self.joints: list[Joint] = []
        for element in root.findall("joint"):
            axis_element = element.find("axis")
            self.joints.append(
                Joint(
                    name=element.get("name", ""),
                    kind=element.get("type", "fixed"),
                    parent=element.find("parent").get("link"),
                    child=element.find("child").get("link"),
                    origin=origin_transform(element.find("origin")),
                    axis=parse_vector(
                        axis_element.get("xyz") if axis_element is not None else None,
                        "0 0 1",
                    ),
                )
            )
        parents = {joint.parent for joint in self.joints}
        children = {joint.child for joint in self.joints}
        roots = sorted(parents - children)
        if len(roots) != 1:
            raise RuntimeError(f"Expected one URDF root, found {roots}")
        self.root_link = roots[0]
        self.root_world = translation(np.asarray(placement["position_m"], dtype=float)) @ rpy_matrix(
            np.deg2rad(np.asarray(placement["rpy_deg"], dtype=float))
        )

    def joint_points(self, q_rad: np.ndarray) -> np.ndarray:
        q_by_name = {f"joint{index + 1}": float(value) for index, value in enumerate(q_rad)}
        transforms = {self.root_link: self.root_world}
        points = [self.root_world[:3, 3].copy()]
        remaining = list(self.joints)
        while remaining:
            progressed = False
            for joint in list(remaining):
                if joint.parent not in transforms:
                    continue
                motion = np.eye(4)
                if joint.kind in {"revolute", "continuous"}:
                    motion = axis_rotation(q_by_name.get(joint.name, 0.0), joint.axis)
                child = transforms[joint.parent] @ joint.origin @ motion
                transforms[joint.child] = child
                if joint.name.startswith("joint"):
                    points.append(child[:3, 3].copy())
                remaining.remove(joint)
                progressed = True
            if not progressed:
                raise RuntimeError("Could not resolve URDF joint tree")
        tcp = transforms["Link6"] @ translation(np.asarray([0.0, 0.0, 0.10]))
        points.append(tcp[:3, 3].copy())
        return np.asarray(points)


def target_map(point_set: dict) -> dict[str, np.ndarray]:
    waypoints = point_set["targets"]["ptlc"]["waypoints"]
    return {
        name: np.asarray(record["value"], dtype=float)
        for name, record in waypoints.items()
    }


def make_frames(
    targets: dict[str, np.ndarray],
    sequence: list[str],
    move_frames: int,
    hold_frames: int,
) -> list[dict]:
    frames: list[dict] = []
    q0 = targets[sequence[0]]
    for _ in range(hold_frames):
        frames.append(
            {
                "q": q0.copy(),
                "from": sequence[0],
                "to": sequence[0],
                "stop": 1,
                "phase": "hold",
                "alpha": 1.0,
            }
        )
    for stop_index, (source, destination) in enumerate(zip(sequence, sequence[1:]), start=2):
        before, after = targets[source], targets[destination]
        for step in range(1, move_frames + 1):
            linear = step / move_frames
            alpha = 0.5 - 0.5 * math.cos(math.pi * linear)
            frames.append(
                {
                    "q": before + alpha * (after - before),
                    "from": source,
                    "to": destination,
                    "stop": stop_index,
                    "phase": "move",
                    "alpha": alpha,
                }
            )
        for _ in range(hold_frames):
            frames.append(
                {
                    "q": after.copy(),
                    "from": destination,
                    "to": destination,
                    "stop": stop_index,
                    "phase": "hold",
                    "alpha": 1.0,
                }
            )
    return frames


def dimensions(manifest: dict) -> dict[str, np.ndarray]:
    records = list(manifest.get("proxy_assets", [])) + list(manifest.get("tool_proxies", []))
    result = {}
    for record in records:
        if "dimensions_mm" in record:
            result[record["asset_id"]] = np.asarray(record["dimensions_mm"], dtype=float) / 1000.0
    return result


class Projector:
    def __init__(self, box: tuple[int, int, int, int], floor: dict):
        self.box = box
        floor_w, floor_d = floor["floor_size_m"]
        cx, cy, _ = floor["floor_center_m"]
        samples = []
        for x in [cx - floor_w / 2, cx + floor_w / 2]:
            for y in [cy - floor_d / 2, cy + floor_d / 2]:
                for z in [0.0, 2.05]:
                    samples.append(self.raw(np.asarray([x, y, z])))
        samples_array = np.asarray(samples)
        self.minimum = samples_array.min(axis=0)
        self.maximum = samples_array.max(axis=0)

    @staticmethod
    def raw(point: np.ndarray) -> np.ndarray:
        x, y, z = point
        return np.asarray([(x - y) * 0.8660254, (x + y) * 0.40 - z * 1.10])

    def __call__(self, point: np.ndarray) -> tuple[int, int]:
        x0, y0, x1, y1 = self.box
        raw = self.raw(point)
        normalized = (raw - self.minimum) / (self.maximum - self.minimum)
        return (
            int(round(x0 + 8 + normalized[0] * (x1 - x0 - 16))),
            int(round(y1 - 8 - normalized[1] * (y1 - y0 - 16))),
        )


def shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * factor))) for channel in color)


def draw_box(
    draw: ImageDraw.ImageDraw,
    projector: Projector,
    center: np.ndarray,
    size: np.ndarray,
    color: tuple[int, int, int],
    yaw_deg: float,
) -> None:
    width, depth, height = size
    if int(round(yaw_deg)) % 180 == 90:
        width, depth = depth, width
    x0, x1 = center[0] - width / 2, center[0] + width / 2
    y0, y1 = center[1] - depth / 2, center[1] + depth / 2
    z0, z1 = center[2], center[2] + height
    points = [
        projector(np.asarray([x0, y0, z0])),
        projector(np.asarray([x1, y0, z0])),
        projector(np.asarray([x1, y1, z0])),
        projector(np.asarray([x0, y1, z0])),
        projector(np.asarray([x0, y0, z1])),
        projector(np.asarray([x1, y0, z1])),
        projector(np.asarray([x1, y1, z1])),
        projector(np.asarray([x0, y1, z1])),
    ]
    draw.polygon([points[index] for index in [0, 1, 5, 4]], fill=shade(color, 0.74))
    draw.polygon([points[index] for index in [1, 2, 6, 5]], fill=shade(color, 0.88))
    draw.polygon([points[index] for index in [4, 5, 6, 7]], fill=shade(color, 1.10))
    for edge in [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]:
        draw.line([points[edge[0]], points[edge[1]]], fill=shade(color, 0.55), width=1)


def panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    draw.rounded_rectangle(box, radius=12, fill=(247, 249, 252), outline=(210, 217, 228), width=2)
    draw.text((box[0] + 14, box[1] + 10), title, font=font(15, True), fill=(35, 45, 62))


def render_frame(
    frame: dict,
    frame_index: int,
    frame_count: int,
    fps: int,
    layout: dict,
    dims: dict[str, np.ndarray],
    projector: Projector,
    kinematics: RobotKinematics,
    stop_tcp: dict[str, np.ndarray],
    sequence: list[str],
    width: int,
    height: int,
) -> Image.Image:
    image = Image.new("RGB", (width, height), (237, 241, 247))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 58), fill=(24, 36, 55))
    draw.text((22, 10), "CR5 AREA-7 MULTI-POINT MOTION", font=font(22, True), fill="white")
    elapsed = frame_index / fps
    status = (
        f"KINEMATIC PREVIEW  |  13 unique recorded targets  |  "
        f"stop {frame['stop']:02d}/15  |  {elapsed:05.2f}s / {frame_count / fps:05.2f}s"
    )
    draw.text((22, 36), status, font=font(12), fill=(178, 197, 222))

    main_box = (14, 70, 650, 495)
    path_box = (664, 70, 946, 280)
    joint_box = (664, 292, 946, 495)
    panel(draw, main_box, "Approximate lab layout + CR5 URDF skeleton")
    panel(draw, path_box, "TCP path from recorded joint targets")
    panel(draw, joint_box, "Current recorded/interpolated joints")

    floor = layout["scene"]
    fw, fd = floor["floor_size_m"]
    fc = np.asarray(floor["floor_center_m"], dtype=float)
    floor_corners = [
        projector(np.asarray([fc[0] - fw / 2, fc[1] - fd / 2, 0.0])),
        projector(np.asarray([fc[0] + fw / 2, fc[1] - fd / 2, 0.0])),
        projector(np.asarray([fc[0] + fw / 2, fc[1] + fd / 2, 0.0])),
        projector(np.asarray([fc[0] - fw / 2, fc[1] + fd / 2, 0.0])),
    ]
    draw.polygon(floor_corners, fill=(226, 232, 239), outline=(155, 166, 181))
    selected = [
        placement
        for placement in layout["placements"]
        if placement["asset_id"] in COLORS and placement["asset_id"] in dims
    ]
    selected.sort(key=lambda item: item["position_m"][0] + item["position_m"][1], reverse=True)
    for placement in selected:
        asset_id = placement["asset_id"]
        draw_box(
            draw,
            projector,
            np.asarray(placement["position_m"], dtype=float),
            dims[asset_id],
            COLORS[asset_id],
            placement["rpy_deg"][2],
        )

    arm = kinematics.joint_points(frame["q"])
    arm_pixels = [projector(point) for point in arm]
    shadow = [projector(np.asarray([point[0], point[1], 0.86])) for point in arm]
    draw.line(shadow, fill=(90, 99, 112), width=7)
    draw.line(arm_pixels, fill=(23, 29, 38), width=12, joint="curve")
    draw.line(arm_pixels, fill=(232, 238, 247), width=8, joint="curve")
    for index, point in enumerate(arm_pixels):
        radius = 7 if index < len(arm_pixels) - 1 else 9
        fill = (255, 173, 51) if index == len(arm_pixels) - 1 else (61, 77, 99)
        draw.ellipse(
            (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
            fill=fill,
            outline="white",
            width=2,
        )
    tcp = arm[-1]
    target_text = frame["to"] if frame["phase"] == "hold" else f"{frame['from']} -> {frame['to']}"
    draw.rounded_rectangle((30, 438, 350, 480), radius=8, fill=(24, 36, 55))
    draw.text((43, 446), target_text, font=font(18, True), fill=(255, 190, 77))
    draw.text(
        (185, 450),
        f"TCP [{tcp[0]:+.3f}, {tcp[1]:+.3f}, {tcp[2]:+.3f}] m",
        font=font(11),
        fill=(213, 222, 234),
    )

    path_left, path_top, path_right, path_bottom = path_box
    plot = (path_left + 22, path_top + 44, path_right - 18, path_bottom - 20)
    tcp_array = np.asarray(list(stop_tcp.values()))[:, :2]
    minimum = tcp_array.min(axis=0) - 0.05
    maximum = tcp_array.max(axis=0) + 0.05
    span = np.maximum(maximum - minimum, 0.1)

    def top_pixel(point: np.ndarray) -> tuple[int, int]:
        normalized = (point[:2] - minimum) / span
        return (
            int(plot[0] + normalized[0] * (plot[2] - plot[0])),
            int(plot[3] - normalized[1] * (plot[3] - plot[1])),
        )

    for fraction in [0.0, 0.5, 1.0]:
        x = int(plot[0] + fraction * (plot[2] - plot[0]))
        y = int(plot[1] + fraction * (plot[3] - plot[1]))
        draw.line((x, plot[1], x, plot[3]), fill=(221, 226, 234), width=1)
        draw.line((plot[0], y, plot[2], y), fill=(221, 226, 234), width=1)
    route = [top_pixel(stop_tcp[name]) for name in sequence]
    draw.line(route, fill=(136, 151, 171), width=2)
    seen = set()
    for name in sequence:
        if name in seen:
            continue
        seen.add(name)
        px, py = top_pixel(stop_tcp[name])
        active = name == frame["to"]
        radius = 5 if active else 3
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=(255, 145, 35) if active else (55, 126, 184))
        draw.text((px + 4, py - 9), name, font=font(8), fill=(50, 60, 76))
    current_px, current_py = top_pixel(tcp)
    draw.ellipse(
        (current_px - 7, current_py - 7, current_px + 7, current_py + 7),
        fill=(255, 184, 67),
        outline=(116, 71, 0),
        width=2,
    )

    joint_left, joint_top, joint_right, joint_bottom = joint_box
    q_deg = np.rad2deg(frame["q"])
    minimum_deg, maximum_deg = -240.0, 150.0
    zero_x = int(joint_left + 66 + (0.0 - minimum_deg) / (maximum_deg - minimum_deg) * 196)
    draw.line((zero_x, joint_top + 40, zero_x, joint_bottom - 21), fill=(168, 176, 188), width=1)
    for index, value in enumerate(q_deg):
        y = joint_top + 46 + index * 23
        value_x = int(joint_left + 66 + (value - minimum_deg) / (maximum_deg - minimum_deg) * 196)
        draw.text((joint_left + 16, y - 7), f"J{index + 1}", font=font(11, True), fill=(55, 65, 80))
        draw.line((min(zero_x, value_x), y, max(zero_x, value_x), y), fill=JOINT_COLORS[index], width=9)
        draw.ellipse((value_x - 5, y - 5, value_x + 5, y + 5), fill=JOINT_COLORS[index], outline="white")
        draw.text((joint_right - 52, y - 7), f"{value:+6.1f}", font=font(10), fill=(55, 65, 80))
    progress_left, progress_right = joint_left + 18, joint_right - 18
    progress_y = joint_bottom - 14
    draw.line((progress_left, progress_y, progress_right, progress_y), fill=(202, 210, 221), width=5)
    progress = frame_index / max(frame_count - 1, 1)
    progress_x = int(progress_left + progress * (progress_right - progress_left))
    draw.line((progress_left, progress_y, progress_x, progress_y), fill=(255, 155, 41), width=5)

    draw.rectangle((0, 507, width, height), fill=(255, 244, 224))
    footer = (
        "SOFTWARE KINEMATIC PREVIEW ONLY | exact recorded joint endpoints + smooth interpolation | "
        "NOT Isaac / MoveIt / collision / dynamics proof"
    )
    draw.text((20, 517), footer, font=font(11, True), fill=(109, 69, 14))
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--point-set", type=Path, default=DEFAULT_POINT_SET)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--urdf", type=Path, default=DEFAULT_URDF)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--move-frames", type=int, default=18)
    parser.add_argument("--hold-frames", type=int, default=3)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--sequence", nargs="+", default=DEFAULT_SEQUENCE)
    args = parser.parse_args()

    point_set = load_json(args.point_set)
    layout = load_json(args.layout)
    manifest = load_json(args.manifest)
    targets = target_map(point_set)
    missing = [name for name in args.sequence if name not in targets]
    if missing:
        raise ValueError(f"Targets absent from point set: {missing}")
    if len(set(args.sequence)) < 10:
        raise ValueError("Preview requires at least ten unique points")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    video_path = args.output_dir / "ptlc_area7_13_points_kinematic_preview.mp4"
    kinematics = RobotKinematics(args.urdf, layout["robot_placement"])
    frames = make_frames(targets, args.sequence, args.move_frames, args.hold_frames)
    stop_tcp = {name: kinematics.joint_points(targets[name])[-1] for name in set(args.sequence)}
    projector = Projector((22, 104, 640, 432), layout["scene"])
    dims = dimensions(manifest)
    poster_indices = {0, len(frames) // 2, len(frames) - 1}

    writer = imageio.get_writer(
        video_path,
        fps=args.fps,
        codec="libx264",
        pixelformat="yuv420p",
        quality=7,
        macro_block_size=None,
        ffmpeg_log_level="warning",
    )
    try:
        for index, frame_record in enumerate(frames):
            rendered = render_frame(
                frame_record,
                index,
                len(frames),
                args.fps,
                layout,
                dims,
                projector,
                kinematics,
                stop_tcp,
                args.sequence,
                args.width,
                args.height,
            )
            frame_array = np.asarray(rendered)
            writer.append_data(frame_array)
            if index in poster_indices:
                rendered.save(args.output_dir / f"preview_frame_{index:03d}.png")
    finally:
        writer.close()

    reader = imageio.get_reader(video_path)
    decoded = 0
    decoded_shape = None
    try:
        for decoded_frame in reader:
            decoded += 1
            decoded_shape = list(decoded_frame.shape)
    finally:
        reader.close()
    passed = decoded == len(frames) and decoded_shape == [args.height, args.width, 3]
    report = {
        "schema": "unilab.kinematic-preview-validation/v1",
        "passed": passed,
        "artifact": str(video_path.relative_to(ROOT)),
        "artifact_sha256": sha256(video_path),
        "renderer": "Pillow CPU software rasterizer with CR5 URDF forward kinematics",
        "sequence": args.sequence,
        "stop_count": len(args.sequence),
        "unique_target_count": len(set(args.sequence)),
        "unique_targets": sorted(set(args.sequence), key=args.sequence.index),
        "frame_count_expected": len(frames),
        "frame_count_decoded": decoded,
        "frame_shape_decoded": decoded_shape,
        "resolution": [args.width, args.height],
        "fps": args.fps,
        "duration_seconds": len(frames) / args.fps,
        "move_frames": args.move_frames,
        "hold_frames": args.hold_frames,
        "source_sha256": {
            "point_set": sha256(args.point_set),
            "layout": sha256(args.layout),
            "manifest": sha256(args.manifest),
            "urdf": sha256(args.urdf),
        },
        "endpoint_rule": "Every hold frame equals the exact recorded six-joint target; move frames use cosine-smoothed joint interpolation.",
        "evidence_boundary": (
            "Software kinematic preview only. It is not an Isaac Sim render and does not establish "
            "MoveIt planning, collision safety, rigid-body dynamics, controller/world calibration, "
            "or real-device execution."
        ),
    }
    report_path = args.output_dir / "kinematic_preview_validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not passed:
        raise RuntimeError(f"Decoded video validation failed: {report}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
