from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import SimpleMaterial
from trimesh.visual.texture import TextureVisuals

from .models import Dimensions


def _box(
    extents: tuple[float, float, float],
    center: tuple[float, float, float],
    color: tuple[int, int, int, int],
) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        vertex_colors=np.tile(
            np.asarray(color, dtype=np.uint8), (len(mesh.vertices), 1)
        ),
    )
    return mesh


def _front_decal(
    width: float,
    height: float,
    depth: float,
    center_y: float,
    image_path: Path,
) -> trimesh.Trimesh:
    x0, x1 = -width / 2, width / 2
    y0, y1 = center_y - height / 2, center_y + height / 2
    z = depth / 2 - 0.0001
    vertices = np.array(
        [[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]], dtype=float
    )
    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=np.array([[0, 1, 2], [0, 2, 3]]),
        process=False,
    )
    image = Image.open(image_path).convert("RGB")
    image.thumbnail((2048, 2048))
    mesh.visual = TextureVisuals(
        uv=np.array([[0, 1], [1, 1], [1, 0], [0, 0]], dtype=float),
        material=SimpleMaterial(image=image),
    )
    return mesh


def _add(scene: trimesh.Scene, name: str, mesh: trimesh.Trimesh) -> None:
    scene.add_geometry(mesh, node_name=name, geom_name=name)


def build_parametric_asset(
    output_path: Path,
    dimensions: Dimensions,
    reference_image: Path,
    template: str,
) -> Path:
    if not dimensions.complete:
        raise ValueError("Complete dimensions are required")
    width = float(dimensions.width_mm) / 1000
    depth = float(dimensions.depth_mm) / 1000
    height = float(dimensions.height_mm) / 1000
    scene = trimesh.Scene()

    body_color = (224, 226, 230, 255)
    dark = (35, 40, 48, 255)

    if template == "mpc":
        _add(
            scene,
            "body",
            _box((width, height * 0.88, depth), (0, height * 0.44, 0), body_color),
        )
        _add(
            scene,
            "lid",
            _box(
                (width * 0.96, height * 0.18, depth * 0.94),
                (0, height * 0.91, 0),
                (30, 120, 200, 255),
            ),
        )
        decal_height, decal_y = height * 0.38, height * 0.38
    elif template == "qpix":
        _add(
            scene,
            "base",
            _box((width, height * 0.42, depth), (0, height * 0.21, 0), body_color),
        )
        _add(
            scene,
            "window",
            _box(
                (width * 0.78, height * 0.5, depth * 0.96),
                (-width * 0.08, height * 0.66, 0),
                (28, 38, 50, 255),
            ),
        )
        _add(
            scene,
            "controls",
            _box(
                (width * 0.18, height * 0.52, depth * 0.94),
                (width * 0.4, height * 0.66, 0),
                body_color,
            ),
        )
        decal_height, decal_y = height * 0.9, height * 0.52
    elif template == "uplc":
        module_gap = width * 0.025
        module_width = (width - module_gap) / 2
        for column in range(2):
            x = (-0.5 if column == 0 else 0.5) * (module_width + module_gap)
            for row in range(3):
                module_height = height / 3
                _add(
                    scene,
                    f"module-{column}-{row}",
                    _box(
                        (module_width, module_height * 0.96, depth),
                        (x, module_height * (row + 0.5), 0),
                        (61, 69, 98, 255),
                    ),
                )
        decal_height, decal_y = height * 0.94, height * 0.5
    elif template == "cytomat":
        _add(
            scene,
            "cabinet",
            _box((width, height, depth), (0, height / 2, 0), body_color),
        )
        _add(
            scene,
            "blue-column",
            _box(
                (width * 0.12, height * 0.92, depth * 0.02),
                (width * 0.31, height * 0.5, depth * 0.49),
                (116, 155, 205, 255),
            ),
        )
        decal_height, decal_y = height * 0.92, height * 0.5
    elif template == "dyna":
        body_height = height * 0.72
        _add(
            scene,
            "analyzer",
            _box((width, body_height, depth), (0, body_height / 2, 0), dark),
        )
        _add(
            scene,
            "screen",
            _box(
                (width * 0.48, height * 0.24, depth * 0.08),
                (0, height * 0.86, 0),
                (30, 34, 40, 255),
            ),
        )
        decal_height, decal_y = body_height * 0.92, body_height * 0.5
    elif template == "proraman":
        _add(
            scene,
            "chassis",
            _box((width, height, depth), (0, height / 2, 0), dark),
        )
        for index in (-0.2, 0.2):
            knob = trimesh.creation.cylinder(
                radius=min(width, height) * 0.07,
                height=depth * 0.04,
                sections=24,
            )
            knob.apply_transform(
                trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
            )
            knob.apply_translation((width * index, height * 0.43, depth * 0.49))
            knob.visual = trimesh.visual.ColorVisuals(
                mesh=knob,
                vertex_colors=np.tile(
                    np.asarray((170, 170, 170, 255), dtype=np.uint8),
                    (len(knob.vertices), 1),
                ),
            )
            _add(scene, f"knob-{index}", knob)
        decal_height, decal_y = height * 0.86, height * 0.5
    else:
        _add(
            scene,
            "cabinet",
            _box((width, height, depth), (0, height / 2, 0), body_color),
        )
        decal_height, decal_y = height * 0.9, height * 0.5

    _add(
        scene,
        "reference-decal",
        _front_decal(
            width * 0.92,
            decal_height,
            depth,
            decal_y,
            reference_image,
        ),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    exported = scene.export(file_type="glb")
    if not isinstance(exported, bytes):
        raise RuntimeError("Unexpected GLB export result")
    output_path.write_bytes(exported)
    return output_path
