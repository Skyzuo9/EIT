from asset_pipeline.models import (
    Approval,
    DeviceRecord,
    ResearchBundle,
    WorkflowStatus,
)
from asset_pipeline.state import StateStore


def make_device() -> DeviceRecord:
    return DeviceRecord(
        id="device-1",
        source_row=2,
        record_type="Instrument",
        manufacturer_model="Vendor Model",
        preparation_status="准备中",
        route="needs_generation",
    )


def test_state_round_trip_and_approval(tmp_path) -> None:
    store = StateStore(tmp_path / "pipeline.sqlite3")
    device = make_device()
    store.upsert_devices([device])
    assert store.get_device(device.id) == device
    assert store.list_devices()[0][1] == WorkflowStatus.IMPORTED

    bundle = ResearchBundle(device_id=device.id)
    store.save_research(bundle)
    assert store.get_research(device.id) == bundle

    approval = Approval(
        device_id=device.id,
        gate="research",
        decision="approved",
        reviewer="codex-interactive",
        override_qc=True,
    )
    store.add_approval(approval)
    assert store.list_approvals(device.id)[0].decision == "approved"
    assert store.list_approvals(device.id)[0].reviewer == "codex-interactive"
    assert store.list_approvals(device.id)[0].override_qc is True

    store.set_status(device.id, WorkflowStatus.AWAITING_GENERATION_APPROVAL)
    assert store.list_devices()[0][1] == WorkflowStatus.AWAITING_GENERATION_APPROVAL


def test_upsert_does_not_reset_existing_status(tmp_path) -> None:
    store = StateStore(tmp_path / "pipeline.sqlite3")
    device = make_device()
    store.upsert_devices([device])
    store.set_status(device.id, WorkflowStatus.AWAITING_RESEARCH_APPROVAL)
    store.upsert_devices([device])
    assert store.list_devices()[0][1] == WorkflowStatus.AWAITING_RESEARCH_APPROVAL
