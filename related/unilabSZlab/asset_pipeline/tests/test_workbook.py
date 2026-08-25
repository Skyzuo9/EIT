from pathlib import Path
import json
import shutil

from asset_pipeline import workbook as workbook_module
from asset_pipeline.models import WorkflowStatus
from asset_pipeline.state import StateStore
from asset_pipeline.workbook import (
    import_coverage_csv,
    import_devices,
    read_rows,
    write_coverage_results,
    write_team_instrument_names,
)


FIXTURES = Path(__file__).parent / "fixtures"
WORKBOOK = FIXTURES / "硬件规格清单_设备结构化.xlsx"
COVERAGE = FIXTURES / "pylabrobot-unilab_coverage.csv"
TEAM_WORKBOOK = FIXTURES / "待生成3D资产仪器清单.xlsx"


def test_ooxml_fallback_reads_all_rows() -> None:
    rows = read_rows(WORKBOOK)
    assert len(rows) == 152
    assert rows[0]["E"] == "仿真资产准备状况"


def test_import_classifies_in_progress_devices() -> None:
    devices, _ = import_devices(WORKBOOK)
    generation = [device for device in devices if device.route == "needs_generation"]
    reuse = [device for device in devices if device.route == "reuse_existing"]
    assert len(devices) == 13
    assert len(generation) == 9
    assert len(reuse) == 4
    assert len({device.id for device in devices}) == 13


def test_import_simple_team_input_only_requires_instrument_name(
    tmp_path, monkeypatch
) -> None:
    rows = [
        {
            "A": "仪器名称（必填，建议：厂商 + 型号）",
            "B": "官网或产品页（可选）",
            "C": "宽度mm（可选）",
            "D": "深度mm（可选）",
            "E": "高度mm（可选）",
            "F": "尺寸来源链接（可选）",
            "G": "用途或备注（可选）",
        },
        {"A": "Thermo Fisher TSQ Altis Plus"},
        {
            "A": "Waters ACQUITY UPLC I-Class PLUS",
            "B": "https://example.com/product",
            "C": "1000",
            "D": "800",
            "E": "900",
            "F": "https://example.com/dimensions",
            "G": "实验室布局资产",
        },
        {"A": ""},
    ]
    monkeypatch.setattr(workbook_module, "read_rows", lambda _: rows)

    devices, source_rows = workbook_module.import_devices(tmp_path / "team.xlsx")

    assert source_rows == rows
    assert len(devices) == 2
    assert all(device.route == "needs_generation" for device in devices)
    assert all(device.source_kind == "team_input" for device in devices)
    assert devices[0].manufacturer_model == "Thermo Fisher TSQ Altis Plus"
    assert devices[0].official_links == []
    assert devices[0].structured_dimensions == ""
    dimensions = json.loads(devices[1].structured_dimensions)
    assert dimensions == {
        "宽mm": "1000",
        "深mm": "800",
        "高mm": "900",
        "尺寸来源URL": "https://example.com/dimensions",
        "占地/安装备注": "实验室布局资产",
    }
    assert devices[1].official_links == [
        "https://example.com/product",
        "https://example.com/dimensions",
    ]


def test_write_team_instrument_names_preserves_template_and_imports(
    tmp_path,
) -> None:
    workbook_path = tmp_path / TEAM_WORKBOOK.name
    shutil.copyfile(TEAM_WORKBOOK, workbook_path)

    count = write_team_instrument_names(
        workbook_path,
        [
            "Thermo Fisher TSQ Altis Plus",
            "  Waters   ACQUITY UPLC I-Class PLUS  ",
            "Thermo Fisher TSQ Altis Plus",
        ],
        replace=True,
    )
    devices, _ = import_devices(workbook_path)

    assert count == 2
    assert [device.manufacturer_model for device in devices] == [
        "Thermo Fisher TSQ Altis Plus",
        "Waters ACQUITY UPLC I-Class PLUS",
    ]
    assert all(device.source_kind == "team_input" for device in devices)


def test_import_coverage_classifies_missing_models() -> None:
    devices, rows = import_coverage_csv(COVERAGE)
    generation = [device for device in devices if device.route == "needs_generation"]
    manual = [device for device in devices if device.route == "manual_identification"]

    assert len(rows) == 232
    assert len(devices) == 49
    assert len(generation) == 33
    assert len(manual) == 16
    assert all(device.source_kind == "coverage_csv" for device in devices)
    assert len({device.source_key for device in devices}) == 49


def test_write_coverage_only_fills_approved_published_assets(tmp_path) -> None:
    devices, _ = import_coverage_csv(COVERAGE)
    device = next(item for item in devices if item.route == "needs_generation")
    store = StateStore(tmp_path / "pipeline.sqlite3")
    store.upsert_devices([device])
    store.set_status(device.id, WorkflowStatus.APPROVED)
    published = tmp_path / "模型资产" / f"{device.manufacturer_model}.glb"
    published.parent.mkdir()
    published.write_bytes(b"glb")
    store.set_metadata(f"published:{device.id}", str(published))

    output = write_coverage_results(COVERAGE, tmp_path / "result.csv", store)
    text = output.read_text(encoding="utf-8")

    assert device.source_key in text
    assert f"生物实验室3D资产准备/模型资产/{published.name}" in text
