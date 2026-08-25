#!/usr/bin/env python3
"""Create reproducible, non-generative Meshy input views from field photo 4."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
SOURCE = WORKSPACE / "现场照片" / "现场照片4.jpg"

# Pixel coordinates in the source image. Pillow uses [left, upper, right, lower),
# therefore the output is exactly 1450 x 2100 pixels.
CROP_BOX = (300, 200, 1750, 2300)

# Manual subject masks in crop-local coordinates. These polygons cover the
# black enclosure, camera/actuator column, white working deck, and aluminum
# support frame. They are intentionally conservative; no pixels are invented.
SUBJECT_POLYGONS = [
    # Black enclosure and its attached cable/actuator area.
    [
        (150, 470),
        (530, 455),
        (695, 750),
        (690, 1715),
        (230, 1835),
        (130, 1640),
    ],
    # Upper optical/actuation column and white vertical mechanisms.
    [
        (390, 85),
        (835, 80),
        (1165, 210),
        (1215, 965),
        (1020, 1225),
        (645, 1115),
        (445, 740),
    ],
    # Working platform, sample stage, and aluminum support frame.
    [
        (245, 910),
        (1295, 925),
        (1365, 1785),
        (1195, 1905),
        (300, 1905),
        (170, 1750),
    ],
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    with Image.open(SOURCE) as source:
        source.load()
        source_rgb = source.convert("RGB")
        crop = source_rgb.crop(CROP_BOX)

    raw_png = HERE / "photo4_crop_x300-1750_y200-2300.png"
    raw_jpg = HERE / "photo4_crop_x300-1750_y200-2300_q98.jpg"
    crop.save(raw_png, format="PNG", optimize=True)
    crop.save(raw_jpg, format="JPEG", quality=98, subsampling=0, optimize=True)

    mask = Image.new("L", crop.size, 0)
    draw = ImageDraw.Draw(mask)
    for polygon in SUBJECT_POLYGONS:
        draw.polygon(polygon, fill=255)

    # Feather only the alpha boundary. RGB pixels always remain source pixels.
    # No inpainting, content-aware fill, synthesis, or generative editing occurs.
    mask_path = HERE / "photo4_subject_manual_mask.png"
    mask.save(mask_path, format="PNG", optimize=True)

    transparent = crop.convert("RGBA")
    transparent.putalpha(mask)
    transparent_path = HERE / "photo4_subject_manual_transparent.png"
    transparent.save(transparent_path, format="PNG", optimize=True)

    audit = {
        "schema_version": "1.0",
        "asset_id": "photo_scrape_station",
        "created_by": "deterministic_crop_and_manual_polygon_mask",
        "source": {
            "path": str(SOURCE.relative_to(WORKSPACE)),
            "sha256": sha256(SOURCE),
            "pixel_size": [4096, 3072],
            "orientation": "upper-left",
        },
        "crop": {
            "coordinate_convention": "source pixels; [left, upper, right, lower), origin at top-left",
            "box_xyxy": list(CROP_BOX),
            "pixel_size": list(crop.size),
            "raw_png": {"path": raw_png.name, "sha256": sha256(raw_png)},
            "high_quality_jpeg": {
                "path": raw_jpg.name,
                "sha256": sha256(raw_jpg),
                "quality": 98,
                "chroma_subsampling": 0,
            },
        },
        "manual_mask": {
            "coordinate_convention": "crop-local pixels; origin at top-left",
            "polygons": SUBJECT_POLYGONS,
            "mask_path": mask_path.name,
            "mask_sha256": sha256(mask_path),
            "transparent_path": transparent_path.name,
            "transparent_sha256": sha256(transparent_path),
            "operation": "binary alpha mask only; RGB values inside mask copied from source crop",
            "generative_content": False,
        },
        "subject_scope": {
            "included": [
                "left black enclosure",
                "vertical camera or actuator head",
                "white striped working platform",
                "aluminum-profile support frame",
                "attached visible pneumatic lines and mechanisms",
            ],
            "excluded_or_mostly_excluded": [
                "DOBOT CR5A on the right",
                "right-side tool rack",
                "foreground parcel and loose tabletop objects",
                "most rear chemistry workstation background",
            ],
            "unavoidable_contamination": [
                "some rear workstation pixels visible through open-frame gaps",
                "occluding cables, hoses, and adjacent mechanisms",
                "left enclosure may be a neighboring subsystem rather than part of the target",
            ],
        },
        "fitness": {
            "recommended_primary_input": transparent_path.name,
            "recommended_audit_reference": raw_png.name,
            "intended_use": "Meshy pilot/reference for a layout-grade photo_scrape_station proxy",
            "not_suitable_for": [
                "manufacturing geometry",
                "collision-critical dimensions",
                "precise hidden-side reconstruction",
                "exact device identity claims",
            ],
            "single_view_risk": "high",
            "risk_reasons": [
                "only one oblique view",
                "rear, left, and underside geometry are hidden",
                "strong occlusion and reflective white/metal surfaces",
                "target boundary is ambiguous because it is integrated into a larger custom workstation",
                "no scale marker or calibrated camera intrinsics",
            ],
        },
    }
    audit_path = HERE / "evidence_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
