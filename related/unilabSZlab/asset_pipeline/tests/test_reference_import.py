import csv

from PIL import Image
import pytest

from asset_pipeline.config import Settings
from asset_pipeline.models import (
    CandidateImage,
    DeviceRecord,
    Dimensions,
    MeshyTask,
    QCReport,
    ResearchBundle,
    WorkflowStatus,
)
from asset_pipeline.pipeline import AssetPipeline, PipelineError


def test_add_reference_image_records_provenance_and_replaces_selection(
    tmp_path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data" / "pipeline.sqlite3",
    )
    settings.ensure_directories()
    pipeline = AssetPipeline(settings)
    device = DeviceRecord(
        id="device-1",
        source_row=2,
        record_type="Instrument",
        manufacturer_model="Vendor Model",
        preparation_status="missing",
        route="needs_generation",
    )
    pipeline.store.upsert_devices([device])
    pipeline.store.save_research(ResearchBundle(device_id=device.id))
    source = tmp_path / "right.png"
    Image.new("RGB", (80, 60), "white").save(source)

    candidate = pipeline.add_reference_image(
        device.id,
        source,
        "https://example.com/right.png",
        page_url="https://example.com/device",
        title="Exact model right view",
        view_label="right",
        replace_selected=True,
    )

    bundle = pipeline.store.get_research(device.id)
    assert candidate.selected is True
    assert candidate.width == 80
    assert candidate.height == 60
    assert candidate.sha256
    assert candidate.local_path.startswith(str(settings.assets_dir))
    assert bundle.selected_images() == [candidate]
    assert bundle.evidence_urls == ["https://example.com/right.png"]
    assert (settings.asset_dir(device.id) / "manifest.json").exists()


def test_prepare_generation_retry_archives_failed_records(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data" / "pipeline.sqlite3",
        max_retry_per_device=1,
    )
    settings.ensure_directories()
    pipeline = AssetPipeline(settings)
    device = DeviceRecord(
        id="device-1",
        source_row=2,
        record_type="Instrument",
        manufacturer_model="Vendor Model",
        preparation_status="missing",
        route="needs_generation",
    )
    pipeline.store.upsert_devices([device])
    image_path = tmp_path / "front.png"
    Image.new("RGB", (40, 40), "white").save(image_path)
    pipeline.store.save_research(
        ResearchBundle(
            device_id=device.id,
            dimensions=Dimensions(
                width_mm=100,
                depth_mm=100,
                height_mm=100,
                source_url="https://example.com/spec",
            ),
            images=[
                CandidateImage(
                    id="front",
                    source_url="https://example.com/front.png",
                    local_path=str(image_path),
                    selected=True,
                )
            ],
        )
    )
    pipeline.store.save_meshy_task(
        MeshyTask(device_id=device.id, task_id="task-1", status="SUCCEEDED")
    )
    pipeline.store.save_qc(
        QCReport(device_id=device.id, source_glb="source.glb", passed=False)
    )

    assert pipeline.prepare_generation_retry(device.id, "better views") == 1
    assert pipeline.store.get_meshy_task(device.id) is None
    assert pipeline.store.get_qc(device.id) is None
    assert "meshy_task_retry_1" in pipeline.store.list_artifact_kinds(device.id)
    assert "qc_retry_1" in pipeline.store.list_artifact_kinds(device.id)
    statuses = {item.id: status for item, status in pipeline.store.list_devices()}
    assert statuses[device.id] == WorkflowStatus.GENERATION_APPROVED

    pipeline.store.save_meshy_task(
        MeshyTask(device_id=device.id, task_id="task-2", status="SUCCEEDED")
    )
    pipeline.store.save_qc(
        QCReport(device_id=device.id, source_glb="source.glb", passed=False)
    )
    try:
        pipeline.prepare_generation_retry(device.id)
    except PipelineError as error:
        assert "exceeds max retry count" in str(error)
    else:
        raise AssertionError("expected retry limit failure")


def test_research_approval_rejects_low_identity_confidence(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data" / "pipeline.sqlite3",
    )
    settings.ensure_directories()
    pipeline = AssetPipeline(settings)
    device = DeviceRecord(
        id="wrong-device",
        source_row=2,
        record_type="Instrument",
        manufacturer_model="Expected Model",
        preparation_status="missing",
        route="needs_generation",
    )
    image_path = tmp_path / "wrong.png"
    Image.new("RGB", (40, 40), "white").save(image_path)
    pipeline.store.upsert_devices([device])
    pipeline.store.save_research(
        ResearchBundle(
            device_id=device.id,
            identity_confidence=0.1,
            dimensions=Dimensions(
                width_mm=100,
                depth_mm=100,
                height_mm=100,
                source_url="https://example.com/spec",
            ),
            images=[
                CandidateImage(
                    id="wrong",
                    source_url="https://example.com/wrong.png",
                    local_path=str(image_path),
                    selected=True,
                )
            ],
        )
    )

    with pytest.raises(PipelineError, match="Identity confidence"):
        pipeline.approve_research(device.id)


def test_export_dimension_report_contains_coverage_audit_fields(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data" / "pipeline.sqlite3",
    )
    settings.ensure_directories()
    pipeline = AssetPipeline(settings)
    device = DeviceRecord(
        id="coverage-device",
        source_row=2,
        source_kind="coverage_csv",
        record_type="Instrument",
        manufacturer_model="Vendor Model",
        preparation_status="missing",
        route="needs_generation",
    )
    pipeline.store.upsert_devices([device])
    pipeline.store.save_research(
        ResearchBundle(
            device_id=device.id,
            identity_confidence=0.9,
            dimensions=Dimensions(
                width_mm=100,
                depth_mm=200,
                height_mm=300,
                source_url="https://example.com/spec",
            ),
        )
    )

    output = pipeline.export_dimension_report(tmp_path / "dimensions.csv")
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["厂商和型号"] == "Vendor Model"
    assert rows[0]["宽_mm"] == "100.0"
    assert rows[0]["尺寸来源"] == "https://example.com/spec"
    assert rows[0]["可发布"] == "False"
