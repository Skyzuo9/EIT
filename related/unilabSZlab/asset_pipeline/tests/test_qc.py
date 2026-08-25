import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import SimpleMaterial
from trimesh.visual.texture import TextureVisuals

from asset_pipeline.models import Dimensions
from asset_pipeline.qc import normalize_and_check_glb


def test_qc_scales_to_meters_and_preserves_texture(tmp_path) -> None:
    mesh = trimesh.creation.box(extents=[2.0, 4.0, 3.0])
    material = SimpleMaterial(image=Image.new("RGB", (8, 8), "blue"))
    mesh.visual = TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=material,
    )
    source = tmp_path / "source.glb"
    source.write_bytes(trimesh.Scene(mesh).export(file_type="glb"))
    final = tmp_path / "final.glb"

    report = normalize_and_check_glb(
        "device-1",
        source,
        final,
        Dimensions(
            width_mm=200,
            height_mm=400,
            depth_mm=300,
            source_url="https://example.com/manual.pdf",
            confidence=1,
        ),
    )

    assert report.loadable
    assert report.has_materials
    assert report.has_textures
    assert report.passed
    assert report.geometry_pass
    assert np.allclose(report.final_extents_m, [0.2, 0.4, 0.3])
    scene = trimesh.load_scene(final, process=False)
    assert np.isclose(scene.bounds[0, 1], 0.0)


def test_qc_corrects_sideways_xz_axis_mapping(tmp_path) -> None:
    mesh = trimesh.creation.box(extents=[3.0, 4.0, 2.0])
    mesh.visual = TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=SimpleMaterial(image=Image.new("RGB", (8, 8), "blue")),
    )
    source = tmp_path / "sideways.glb"
    source.write_bytes(trimesh.Scene(mesh).export(file_type="glb"))
    final = tmp_path / "aligned.glb"

    report = normalize_and_check_glb(
        "device-sideways",
        source,
        final,
        Dimensions(
            width_mm=200,
            height_mm=400,
            depth_mm=300,
            source_url="https://example.com/manual.pdf",
            confidence=1,
        ),
    )

    assert report.passed
    assert report.axis_mapping == "swap_xz"
    assert np.isclose(report.proportion_error, 0)
    assert np.allclose(report.final_extents_m, [0.2, 0.4, 0.3])
