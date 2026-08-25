import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from asset_pipeline.agent import (
    _review_generated_asset_with_codex,
    build_visual_qc_request,
)
from asset_pipeline.config import Settings
from asset_pipeline.models import CandidateImage, DeviceRecord, ResearchBundle


def _fixture(tmp_path):
    reference = tmp_path / "reference.png"
    Image.new("RGB", (64, 64), "white").save(reference)
    output = tmp_path / "output"
    output.mkdir()
    for view in ("front", "right", "back", "left"):
        Image.new("RGB", (64, 64), "gray").save(output / f"preview-{view}.png")
    device = DeviceRecord(
        id="device-1",
        source_row=2,
        record_type="Instrument",
        manufacturer_model="Vendor Model",
        preparation_status="准备中",
        route="needs_generation",
    )
    bundle = ResearchBundle(
        device_id=device.id,
        images=[
            CandidateImage(
                id="reference-1",
                source_url="https://example.com/reference.png",
                local_path=str(reference),
                selected=True,
            )
        ],
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data/pipeline.sqlite3",
        codex_cli_path="codex-test",
        codex_model="test-model",
    )
    return settings, device, bundle, output


def test_codex_visual_qc_records_structured_run(tmp_path, monkeypatch) -> None:
    settings, device, bundle, output = _fixture(tmp_path)
    monkeypatch.setattr("asset_pipeline.agent.shutil.which", lambda _: "/bin/codex")

    def fake_run(command, **kwargs):
        result_path = Path(command[command.index("--output-last-message") + 1])
        result_path.write_text(
            json.dumps(
                {
                    "passed": True,
                    "similarity_score": 0.88,
                    "summary": "Silhouette and components match.",
                    "issues": [],
                }
            ),
            encoding="utf-8",
        )
        assert kwargs["input"].startswith("Act as a layout-usability reviewer")
        assert kwargs["timeout"] == settings.codex_timeout_seconds
        assert "--sandbox" in command
        assert "read-only" in command
        assert sum(item.startswith("--image=") for item in command) == 5
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("asset_pipeline.agent.subprocess.run", fake_run)
    review = _review_generated_asset_with_codex(settings, device, bundle, output)

    assert review.passed
    assert review.similarity_score == 0.88
    assert review.provider == "codex-cli"
    assert len(review.evidence_paths) == 5
    assert (output / "visual-qc/codex-request.json").exists()
    assert (output / "visual-qc/codex-run.json").exists()


def test_visual_qc_request_requires_all_four_previews(tmp_path) -> None:
    settings, device, bundle, output = _fixture(tmp_path)
    (output / "preview-back.png").unlink()

    with pytest.raises(RuntimeError, match="preview-back.png"):
        build_visual_qc_request(settings, device, bundle, output)
