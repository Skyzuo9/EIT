from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import SimpleMaterial
from trimesh.visual.texture import TextureVisuals

from asset_pipeline.config import Settings
from asset_pipeline.agent import GeneratedVisualReview
from asset_pipeline.models import (
    CandidateImage,
    MeshyTask,
    ResearchBundle,
    WorkflowStatus,
)
from asset_pipeline.pipeline import AssetPipeline
from asset_pipeline.research import dimensions_from_device


WORKBOOK = Path(__file__).parent / "fixtures" / "硬件规格清单_设备结构化.xlsx"


class FakeResearcher:
    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def research(self, device):
        path = self.settings.asset_dir(device.id) / "candidates" / "pilot.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 1024), "white").save(path)
        return ResearchBundle(
            device_id=device.id,
            dimensions=dimensions_from_device(device),
            images=[
                CandidateImage(
                    id="pilot-image",
                    source_url="https://example.com/pilot.png",
                    page_url="https://example.com/device",
                    local_path=str(path),
                    width=1024,
                    height=1024,
                    score=1,
                    selected=True,
                )
            ],
            identity_confidence=1,
        )


class FakeMeshyClient:
    TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED"}

    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def create_task(self, bundle):
        return MeshyTask(
            device_id=bundle.device_id,
            task_id="pilot-task",
            status="SUCCEEDED",
            consumed_credits=30,
            model_url="mock://source.glb",
        )

    def download_outputs(self, task, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        mesh = trimesh.creation.box(extents=[0.762, 0.343, 0.622])
        mesh.visual = TextureVisuals(
            uv=np.zeros((len(mesh.vertices), 2)),
            material=SimpleMaterial(image=Image.new("RGB", (8, 8), "gray")),
        )
        source = output_dir / "source.glb"
        source.write_bytes(trimesh.Scene(mesh).export(file_type="glb"))
        Image.new("RGB", (256, 256), "gray").save(output_dir / "preview.png")
        for view in ("front", "right", "back", "left"):
            Image.new("RGB", (256, 256), "gray").save(
                output_dir / f"preview-{view}.png"
            )
        return source


def fake_visual_review(settings, device, bundle, output_dir):
    evidence = [
        str(Path(image.local_path).resolve()) for image in bundle.selected_images()
    ]
    evidence.extend(
        str((output_dir / f"preview-{view}.png").resolve())
        for view in ("front", "right", "back", "left")
    )
    return GeneratedVisualReview(
        passed=True,
        similarity_score=0.9,
        summary="Test visual review passed.",
        provider="test-codex",
        model="test-model",
        evidence_paths=evidence,
    )


def test_one_device_end_to_end_dry_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("asset_pipeline.pipeline.ImageResearcher", FakeResearcher)
    monkeypatch.setattr("asset_pipeline.pipeline.MeshyClient", FakeMeshyClient)
    monkeypatch.setattr(
        "asset_pipeline.pipeline.review_generated_asset", fake_visual_review
    )
    settings = Settings(
        workbook_path=WORKBOOK,
        output_workbook_path=tmp_path / "result.xlsx",
        approved_assets_dir=tmp_path / "published",
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data" / "pipeline.sqlite3",
        meshy_api_key="fake",
        cursor_api_key=None,
        gemini_api_key="",
        candidate_review_provider="none",
    )
    settings.ensure_directories()
    pipeline = AssetPipeline(settings)
    assert pipeline.bootstrap() == (9, 4)
    device = pipeline.store.list_devices(WorkflowStatus.IMPORTED)[0][0]

    pipeline.research_device(device.id)
    pipeline.approve_research(device.id, "pilot")
    assert pipeline.approve_generation([device.id], "pilot") == 30
    pipeline.generate_device(device.id)
    pipeline.approve_final(device.id, "pilot")
    output = pipeline.export_results()

    statuses = {item.id: status for item, status in pipeline.store.list_devices()}
    assert statuses[device.id] == WorkflowStatus.APPROVED
    assert pipeline.store.get_qc(device.id).passed
    assert pipeline.store.get_qc(device.id).geometry_pass
    assert pipeline.store.get_qc(device.id).visual_provider == "test-codex"
    assert output.exists()
    assert (settings.asset_dir(device.id) / "manifest.json").exists()
    published_glb = settings.approved_assets_dir / f"{device.manufacturer_model}.glb"
    published_stl = settings.approved_assets_dir / f"{device.manufacturer_model}.stl"
    assert published_glb.exists()
    assert published_stl.exists()
    assert np.allclose(trimesh.load_scene(published_glb).extents, [0.762, 0.622, 0.343])
    assert np.allclose(trimesh.load_scene(published_stl).extents, [762, 622, 343])

    pipeline.record_visual_qc(
        device.id,
        GeneratedVisualReview(
            passed=False,
            similarity_score=0.4,
            summary="Major mismatch found during backfill.",
            issues=["Invented component"],
            provider="codex-interactive",
        ),
    )
    statuses = {item.id: status for item, status in pipeline.store.list_devices()}
    assert statuses[device.id] == WorkflowStatus.AWAITING_FINAL_APPROVAL
    decision = pipeline.store.list_approvals(device.id)[-1]
    assert decision.gate == "visual_qc"
    assert decision.decision == "rejected"
    assert decision.reviewer == "codex-interactive"
