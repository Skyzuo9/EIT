#!/usr/bin/env python3
"""Encode validated Isaac PNG frames to H.264 and verify decoding."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=float, required=True)
    args = parser.parse_args()
    if args.fps <= 0:
        raise ValueError("fps must be positive")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise ValueError("Isaac render report has not passed")
    images = sorted(args.frames.glob("rgb*.png"))
    if not images or len(images) != int(report["frame_count"]):
        raise ValueError("Frame count does not match the Isaac report")
    frame_metadata = report.get("frames", [])
    if len(frame_metadata) != len(images):
        raise ValueError("Frame metadata does not match rendered images")
    unique_target_count = len(set(report["requested_targets"]))
    try:
        title_font = ImageFont.truetype("DejaVuSans.ttf", 22)
        detail_font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        title_font = ImageFont.load_default()
        detail_font = ImageFont.load_default()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        args.output,
        fps=args.fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=None,
        ffmpeg_log_level="warning",
    )
    try:
        for path, metadata in zip(images, frame_metadata, strict=True):
            frame = Image.fromarray(imageio.imread(path)).convert("RGB")
            draw = ImageDraw.Draw(frame)
            target = str(metadata["target_ref"]).rsplit(".", 1)[-1]
            phase = str(metadata["phase"])
            progress = float(metadata["progress"])
            command_parts = str(metadata["command_id"]).rsplit("-", 2)
            stop_index = int(command_parts[-2]) if len(command_parts) == 3 else 0
            state = f"move {progress * 100:3.0f}%" if phase.startswith("move_") else "hold"
            draw.rounded_rectangle((20, 18, 440, 84), radius=10, fill=(18, 25, 35))
            draw.text((34, 27), f"CR5 area-7 | target {target}", font=title_font, fill=(255, 255, 255))
            draw.text(
                (34, 57),
                f"stop {stop_index}/{len(report['requested_targets'])} | {state} | {unique_target_count} unique recorded points",
                font=detail_font,
                fill=(110, 210, 255),
            )
            footer = "SIMULATION ONLY | geometry interpolation | not collision/dynamics proof"
            footer_box = draw.textbbox((0, 0), footer, font=detail_font)
            footer_width = footer_box[2] - footer_box[0]
            x = max(20, frame.width - footer_width - 28)
            y = frame.height - 36
            draw.rounded_rectangle((x - 10, y - 6, frame.width - 18, frame.height - 12), radius=8, fill=(18, 25, 35))
            draw.text((x, y), footer, font=detail_font, fill=(235, 235, 235))
            writer.append_data(np.asarray(frame))
    finally:
        writer.close()

    reader = imageio.get_reader(args.output)
    decoded = 0
    frame_shape = None
    try:
        for frame in reader:
            decoded += 1
            frame_shape = list(frame.shape)
    finally:
        reader.close()
    if decoded != len(images) or frame_shape is None:
        raise RuntimeError(f"Decoded {decoded} frames, expected {len(images)}")

    validation = {
        "schema_version": "ptlc.video-validation.v2",
        "status": "passed",
        "video": str(args.output.resolve()),
        "sha256": sha256(args.output),
        "bytes": args.output.stat().st_size,
        "codec": "h264",
        "fps": args.fps,
        "duration_seconds": decoded / args.fps,
        "decoded_frame_count": decoded,
        "decoded_frame_shape": frame_shape,
        "source_report": str(args.report.resolve()),
        "source_report_sha256": sha256(args.report),
        "requested_targets": report["requested_targets"],
        "unique_target_count": unique_target_count,
    }
    validation_path = args.output.with_name("video_validation.json")
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(validation_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
