import numpy as np
import trimesh
from PIL import Image

from asset_pipeline.models import Dimensions
from asset_pipeline.parametric import build_parametric_asset
from asset_pipeline.qc import normalize_and_check_glb


def test_parametric_asset_has_exact_dimensions_and_texture(tmp_path) -> None:
    reference = tmp_path / "reference.jpg"
    Image.new("RGB", (800, 600), "blue").save(reference)
    dimensions = Dimensions(
        width_mm=600,
        depth_mm=400,
        height_mm=500,
        source_url="https://example.com/spec",
        confidence=1,
    )
    source = build_parametric_asset(
        tmp_path / "source.glb",
        dimensions,
        reference,
        "cabinet",
    )
    report = normalize_and_check_glb(
        "parametric-device",
        source,
        tmp_path / "final.glb",
        dimensions,
    )

    assert report.passed
    assert report.has_textures
    assert np.allclose(trimesh.load_scene(source).extents, [0.6, 0.5, 0.4])
