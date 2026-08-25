import json

from asset_pipeline.catalog import write_asset_catalog
from asset_pipeline.config import Settings
from asset_pipeline.models import DeviceRecord, MeshyTask, WorkflowStatus
from asset_pipeline.state import StateStore


def test_catalog_records_hashes_without_raw_provider_payload(tmp_path) -> None:
    assets = tmp_path / "模型资产"
    assets.mkdir()
    glb = assets / "Vendor Model.glb"
    stl = assets / "Vendor Model.stl"
    glb.write_bytes(b"glb")
    stl.write_bytes(b"stl")
    settings = Settings(
        approved_assets_dir=assets,
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "working",
        database_path=tmp_path / "data/pipeline.sqlite3",
    )
    store = StateStore(settings.database_path)
    device = DeviceRecord(
        id="device-1",
        source_row=2,
        record_type="Instrument",
        manufacturer_model="Vendor Model",
        preparation_status="准备中",
        route="needs_generation",
    )
    store.upsert_devices([device])
    store.set_status(device.id, WorkflowStatus.APPROVED)
    store.set_metadata(f"published:{device.id}", str(glb))
    store.set_metadata(f"published_stl:{device.id}", str(stl))
    store.save_meshy_task(
        MeshyTask(
            device_id=device.id,
            task_id="task-1",
            status="SUCCEEDED",
            consumed_credits=30,
            raw={"signed_url": "secret-provider-payload"},
        )
    )

    output = write_asset_catalog(settings, store)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["asset_count"] == 1
    assert payload["assets"][0]["files"]["glb"]["sha256"]
    assert payload["assets"][0]["generation"]["consumed_credits"] == 30
    assert payload["assets"][0]["redistribution_license"]["status"] == "not_recorded"
    assert "secret-provider-payload" not in output.read_text(encoding="utf-8")
