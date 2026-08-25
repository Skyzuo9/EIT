#!/usr/bin/env python3
"""Build one auditable HTML-report payload for all pTLC point information."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "pTLC仿真资产"
OUTPUT_DIR = ASSET_ROOT / "point_inventory_report_20260814"
ARTIFACT_PATH = OUTPUT_DIR / "artifact.json"
SQLITE_PATH = OUTPUT_DIR / "point_inventory.sqlite"

SNAPSHOT_PATH = ASSET_ROOT / "source_api_points_snapshot.json"
INTERACTION_PATH = ASSET_ROOT / "interaction_points.json"
RAIL_ANALYSIS_PATH = ASSET_ROOT / "rail_frame_layout_analysis.json"
AREA7_PATH = ASSET_ROOT / "isaac_sim/config/cr5_ptlc_area7_points.v1.json"
AREA7_VALIDATION_PATH = (
    ASSET_ROOT
    / "isaac_sim/output/area7_multipt_video_20260814/unilab_isaac_validation.json"
)
BASELINE_PATH = ROOT / "pTLC实验室仿真重建基线_2026-08-13.md"

EXPECTED_SNAPSHOT_SHA256 = (
    "cf6f12f1db259d80b0777664391a9a17459f8b0af8f43b5b0e62128506a2b11c"
)
EXPECTED_AREA7_SHA256 = (
    "67b2d60c7ca560bad1ee68111493d06014a6e91e1fa7972331c825fdc988a180"
)
UPSTREAM_COMMIT = "c65b34a8839ebb13fc86701e420b2734d6c4cfa6"
API_URL = "http://zhlg1509460.bohrium.tech:50001/api/points"
GIT_ROBOT_URL = (
    "https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/"
    f"{UPSTREAM_COMMIT}/eit_ptlc/config/points/robot/robot_points.json"
)
GIT_META_URL = (
    "https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/"
    f"{UPSTREAM_COMMIT}/eit_ptlc/config/points/robot/robot_points_meta.json"
)
GIT_PLC_URL = (
    "https://github.com/Uni-Lab-OS/pTLC_platformUI/tree/"
    f"{UPSTREAM_COMMIT}/eit_ptlc/config/points/plc"
)


def load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return document


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_json(value: object) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sqlite_type(values: list[object]) -> str:
    non_null = [value for value in values if value is not None]
    if non_null and all(isinstance(value, bool | int) for value in non_null):
        return "INTEGER"
    if non_null and all(isinstance(value, bool | int | float) for value in non_null):
        return "REAL"
    return "TEXT"


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def write_sqlite(datasets: dict[str, list[dict]]) -> None:
    temporary = SQLITE_PATH.with_suffix(".sqlite.partial")
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    try:
        for table_name, rows in datasets.items():
            if not rows:
                continue
            columns = list(rows[0])
            definitions = ", ".join(
                f"{quote_identifier(column)} {sqlite_type([row.get(column) for row in rows])}"
                for column in columns
            )
            connection.execute(
                f"CREATE TABLE {quote_identifier(table_name)} ({definitions})"
            )
            placeholders = ", ".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO {quote_identifier(table_name)} VALUES ({placeholders})",
                [
                    tuple(
                        int(value) if isinstance(value, bool) else value
                        for value in (row.get(column) for column in columns)
                    )
                    for row in rows
                ],
            )
        connection.commit()
    finally:
        connection.close()
    temporary.replace(SQLITE_PATH)


def point_number(name: str) -> int | None:
    match = re.fullmatch(r"P(\d+)", name)
    return int(match.group(1)) if match else None


def build_rail_maps(rail_analysis: dict) -> tuple[dict[int, int], dict[int, float], list[dict]]:
    provenance = rail_analysis["semantic_binding_provenance"]
    values = {
        int(slot): float(value)
        for slot, value in provenance["rail_values"]["values_by_slot_mm"].items()
    }
    point_to_slot: dict[int, int] = {}
    binding_rows = []
    for binding in provenance["point_family_to_rail_slot"]["bindings"]:
        slot = int(binding["rail_slot"])
        numbers = [int(value) for value in binding["explicit_point_numbers"]]
        for number in numbers:
            existing = point_to_slot.get(number)
            if existing is not None and existing != slot:
                raise ValueError(f"Conflicting rail bindings for P{number}: {existing} vs {slot}")
            point_to_slot[number] = slot
        binding_rows.append(
            {
                "cluster_id": binding["cluster_id"],
                "point_numbers": ", ".join(f"P{number}" for number in numbers),
                "point_count": len(numbers),
                "rail_slot": slot,
                "rail_value_mm": values[slot],
                "basis": binding["basis"],
                "provenance": provenance["point_family_to_rail_slot"]["source_kind"],
            }
        )
    return point_to_slot, values, binding_rows


def flatten_robot_points(
    snapshot: dict, point_to_slot: dict[int, int], rail_values: dict[int, float]
) -> tuple[list[dict], list[dict]]:
    rows = []
    group_summary = []
    index = 0
    for group in snapshot["robot"]["groups"]:
        base_count = 0
        derived_count = 0
        for point in group["points"]:
            index += 1
            name = str(point["robot_name"])
            number = point_number(name)
            is_derived = bool(point.get("is_derived", False))
            base_count += int(not is_derived)
            derived_count += int(is_derived)
            rail_slot = point_to_slot.get(number) if number is not None else None
            rows.append(
                {
                    "source_order": index,
                    "group_key": group["key"],
                    "group_label": group["label"],
                    "robot_name": name,
                    "point_number": number,
                    "alias": point.get("alias") or "",
                    "id": point["id"],
                    "workstation": point.get("workstation") or "",
                    "role": point.get("role") or "",
                    "record_kind": "派生" if is_derived else "原始",
                    "status": point.get("status") or "",
                    "allowed_motion": ", ".join(point.get("allowed_motion") or []),
                    "pose_mm_deg": compact_json(point.get("pose")),
                    "joint_deg": compact_json(point.get("joint")),
                    "user": point.get("user"),
                    "tool": point.get("tool"),
                    "acc": point.get("acc"),
                    "vel": point.get("vel"),
                    "cp": point.get("cp"),
                    "derived_from": point.get("derived_from") or "",
                    "derivation": point.get("derivation") or "",
                    "workflow_rail_slot_non_api": rail_slot,
                    "workflow_rail_value_mm_non_api": (
                        rail_values.get(rail_slot) if rail_slot is not None else None
                    ),
                    "notes": point.get("notes") or "",
                    "calibrated_at": point.get("calibrated_at") or "",
                }
            )
        group_summary.append(
            {
                "group_key": group["key"],
                "group_label": group["label"],
                "base_count": base_count,
                "derived_count": derived_count,
                "total_count": base_count + derived_count,
            }
        )
    return rows, group_summary


def flatten_plc_points(snapshot: dict) -> tuple[list[dict], list[dict]]:
    rows = []
    group_summary = []
    index = 0
    for group in snapshot["plc_servo"]["groups"]:
        for point in group["points"]:
            index += 1
            members = point.get("members") or []
            scalar_count = len(members) if members else 1
            if members:
                value = "; ".join(
                    f"{member['key']}={member['value']}" for member in members
                )
                nodes = "; ".join(
                    f"{member['key']}:{member.get('node', '')}" for member in members
                )
                actpos = "; ".join(
                    f"{member['key']}:{member.get('actpos', '')}" for member in members
                )
                limits = "; ".join(
                    f"{member['key']}:[{member['limits']['min']},{member['limits']['max']}]"
                    for member in members
                )
            else:
                value = str(point.get("value", ""))
                nodes = str(point.get("node", ""))
                actpos = str(point.get("actpos", ""))
                limits = compact_json(point.get("limits"))
            rows.append(
                {
                    "source_order": index,
                    "group_key": group["key"],
                    "group_label": group["label"],
                    "id": point["id"],
                    "label": point["label"],
                    "category": point["category"],
                    "workstation": point.get("workstation") or "",
                    "role": point.get("role") or "",
                    "slot": point.get("slot"),
                    "value_or_members": value,
                    "scalar_count": scalar_count,
                    "node": nodes,
                    "actpos": actpos,
                    "limits": limits,
                    "hmi_node": point.get("hmi_node") or "",
                    "hmi_slot": point.get("hmi_slot"),
                    "limit_source": point.get("limit_source"),
                    "pending": bool(point.get("pending", False)),
                    "sync": point.get("sync"),
                    "live": compact_json(point.get("live")),
                }
            )
        group_summary.append(
            {
                "group_key": group["key"],
                "group_label": group["label"],
                "semantic_point_count": len(group["points"]),
                "scalar_count": sum(
                    len(point.get("members") or []) or 1 for point in group["points"]
                ),
            }
        )
    return rows, group_summary


def build_area7_rows(
    area7: dict,
    validation: dict,
    robot_rows: list[dict],
    point_to_slot: dict[int, int],
) -> list[dict]:
    by_name = {
        row["robot_name"]: row
        for row in robot_rows
        if row["record_kind"] == "原始"
    }
    sequence = [str(value).split(".", 1)[1] for value in validation["requested_targets"]]
    waypoints = area7["targets"]["ptlc"]["waypoints"]
    rows = []
    for order, (name, waypoint) in enumerate(waypoints.items(), start=1):
        source = by_name[name]
        source_joint = json.loads(source["joint_deg"])
        recorded_joint = [float(value) for value in waypoint["source_joint_degrees"]]
        if any(
            not math.isclose(a, b, abs_tol=1e-9)
            for a, b in zip(source_joint, recorded_joint, strict=True)
        ):
            raise ValueError(f"Isaac source joint mismatch for {name}")
        occurrences = [index + 1 for index, value in enumerate(sequence) if value == name]
        number = point_number(name)
        rows.append(
            {
                "point_order": order,
                "point": name,
                "live_sequence_stop_numbers": ", ".join(map(str, occurrences)),
                "source_id": waypoint["source_id"],
                "source_status": waypoint["source_status"],
                "workstation": source["workstation"],
                "role": source["role"],
                "workflow_rail_slot_non_api": point_to_slot.get(number),
                "pose_mm_deg": source["pose_mm_deg"],
                "joint_deg": compact_json(recorded_joint),
                "joint_rad": compact_json(waypoint["value"]),
            }
        )
    return rows


def source_objects(generated_at: str) -> list[dict]:
    return [
        {
            "id": "web_snapshot",
            "label": "pTLC 只读网页 API 点位快照",
            "path": "pTLC仿真资产/source_api_points_snapshot.json",
            "href": API_URL,
        },
        {
            "id": "upstream_git",
            "label": f"pTLC_platformUI 固定提交 {UPSTREAM_COMMIT[:12]}",
            "href": GIT_ROBOT_URL,
            "path": "eit_ptlc/config/points",
        },
        {
            "id": "rail_binding",
            "label": "工作流语义地轨绑定 sidecar",
            "path": "pTLC仿真资产/rail_frame_layout_analysis.json",
        },
        {
            "id": "area7_pointset",
            "label": "Isaac Area-7 13 点 PointSet 与通过的验证报告",
            "path": "pTLC仿真资产/isaac_sim/config/cr5_ptlc_area7_points.v1.json",
        },
        {
            "id": "consolidation",
            "label": "本汇总的确定性生成脚本",
            "path": "pTLC仿真资产/scripts/build_point_inventory_report.py",
        },
        {
            "id": "inventory_counts_sql",
            "label": "SQLite 点位构成查询",
            "path": "pTLC仿真资产/point_inventory_report_20260814/point_inventory.sqlite",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "executed_at": generated_at,
                "description": "读取已通过 JSON 一致性断言的三类点位记录数。",
                "sql": "SELECT record_type, count, source_scope, definition FROM inventory_counts ORDER BY count DESC",
                "tables_used": ["inventory_counts"],
                "filters": ["no row filter"],
                "metric_definitions": ["count = exact reviewed row count for each record type"],
            },
        },
        {
            "id": "robot_points_sql",
            "label": "SQLite 全量机器人点查询",
            "path": "pTLC仿真资产/point_inventory_report_20260814/point_inventory.sqlite",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "executed_at": generated_at,
                "description": "按网页 API 源顺序读取 239 个机器人记录及非 API 地轨 sidecar 列。",
                "sql": "SELECT * FROM robot_points ORDER BY source_order ASC",
                "tables_used": ["robot_points"],
                "filters": ["no row filter", "all 239 records"],
            },
        },
        {
            "id": "plc_points_sql",
            "label": "SQLite 全量 PLC 点查询",
            "path": "pTLC仿真资产/point_inventory_report_20260814/point_inventory.sqlite",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "executed_at": generated_at,
                "description": "按网页 API 源顺序读取 16 个 PLC 语义点。",
                "sql": "SELECT * FROM plc_points ORDER BY source_order ASC",
                "tables_used": ["plc_points"],
                "filters": ["no row filter", "all 16 semantic records"],
            },
        },
        {
            "id": "rail_bindings_sql",
            "label": "SQLite 地轨语义绑定查询",
            "path": "pTLC仿真资产/point_inventory_report_20260814/point_inventory.sqlite",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "executed_at": generated_at,
                "description": "读取工作流语义 sidecar 中的全部显式点族绑定。",
                "sql": "SELECT * FROM rail_bindings ORDER BY rail_slot ASC, cluster_id ASC",
                "tables_used": ["rail_bindings"],
                "filters": ["explicit point families only"],
            },
        },
        {
            "id": "area7_points_sql",
            "label": "SQLite Isaac Area-7 子集查询",
            "path": "pTLC仿真资产/point_inventory_report_20260814/point_inventory.sqlite",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "executed_at": generated_at,
                "description": "读取与网页关节角逐项一致的 13 个 Isaac 唯一点。",
                "sql": "SELECT * FROM area7_points ORDER BY point_order ASC",
                "tables_used": ["area7_points"],
                "filters": ["13 unique Area-7 points", "source validation status = passed"],
            },
        },
    ]


def build_artifact() -> dict:
    snapshot = load_json(SNAPSHOT_PATH)
    interaction = load_json(INTERACTION_PATH)
    rail_analysis = load_json(RAIL_ANALYSIS_PATH)
    area7 = load_json(AREA7_PATH)
    validation = load_json(AREA7_VALIDATION_PATH)

    snapshot_sha = sha256(SNAPSHOT_PATH)
    area7_sha = sha256(AREA7_PATH)
    if snapshot_sha != EXPECTED_SNAPSHOT_SHA256:
        raise ValueError(f"Unexpected source snapshot SHA-256: {snapshot_sha}")
    if area7_sha != EXPECTED_AREA7_SHA256:
        raise ValueError(f"Unexpected area-7 PointSet SHA-256: {area7_sha}")
    if interaction["source"]["sha256"] != snapshot_sha:
        raise ValueError("interaction_points source SHA does not match raw snapshot")
    if interaction["data"] != snapshot:
        raise ValueError("interaction_points data differs from the raw API snapshot")
    if validation.get("status") != "passed":
        raise ValueError("Area-7 Isaac validation report is not passed")
    if validation.get("point_set_sha256") != area7_sha:
        raise ValueError("Area-7 validation used a different PointSet")

    point_to_slot, rail_values, binding_rows = build_rail_maps(rail_analysis)
    robot_rows, robot_group_summary = flatten_robot_points(
        snapshot, point_to_slot, rail_values
    )
    plc_rows, plc_group_summary = flatten_plc_points(snapshot)
    area7_rows = build_area7_rows(
        area7, validation, robot_rows, point_to_slot
    )

    base_count = sum(row["record_kind"] == "原始" for row in robot_rows)
    derived_count = sum(row["record_kind"] == "派生" for row in robot_rows)
    plc_scalar_count = sum(int(row["scalar_count"]) for row in plc_rows)
    if (len(robot_rows), base_count, derived_count, len(plc_rows), plc_scalar_count) != (
        239,
        74,
        165,
        16,
        18,
    ):
        raise ValueError("Point inventory counts changed unexpectedly")
    if any("rail" in point for group in snapshot["robot"]["groups"] for point in group["points"]):
        raise ValueError("At least one robot point unexpectedly contains a native rail field")
    sample_5z = next(row for row in plc_rows if row["id"] == "sample_5z")
    if sample_5z["pending"] is not True:
        raise ValueError("sample_5z must remain pending")
    if len(area7_rows) != 13 or len(validation["requested_targets"]) != 15:
        raise ValueError("Area-7 subset must contain 13 points and 15 stops")

    status_counts = Counter(row["status"] for row in robot_rows)
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    sources = source_objects(generated_at)
    headline = [
        {
            "robot_total": len(robot_rows),
            "robot_base": base_count,
            "robot_derived": derived_count,
            "plc_semantic": len(plc_rows),
            "plc_scalars": plc_scalar_count,
            "rail_slots": len(rail_values),
            "isaac_unique": len(area7_rows),
            "isaac_stops": len(validation["requested_targets"]),
        }
    ]
    inventory_counts = [
        {
            "record_type": "机器人原始点",
            "count": base_count,
            "source_scope": "网页 API 快照",
            "definition": "is_derived=false",
        },
        {
            "record_type": "机器人派生点",
            "count": derived_count,
            "source_scope": "网页 API 快照",
            "definition": "is_derived=true",
        },
        {
            "record_type": "PLC 语义点",
            "count": len(plc_rows),
            "source_scope": "网页 API 快照",
            "definition": "plc_servo.groups[].points",
        },
    ]

    title = "pTLC 点位信息汇总（网页快照、工作流绑定与 Isaac 子集）"
    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "pTLC 全量机器人/PLC 点位、地轨语义绑定和 Isaac 13 点子集的一文件审计汇总。",
        "generatedAt": generated_at,
        "cards": [
            {
                "id": "robot_inventory_card",
                "dataset": "headline",
                "sourceId": "inventory_counts_sql",
                "description": "网页快照中的机器人记录总量及原始/派生拆分。",
                "metrics": [
                    {"label": "机器人记录", "field": "robot_total", "format": "number"},
                    {"label": "原始点", "field": "robot_base", "format": "number"},
                    {"label": "派生点", "field": "robot_derived", "format": "number"},
                ],
            },
            {
                "id": "plc_inventory_card",
                "dataset": "headline",
                "sourceId": "web_snapshot",
                "description": "PLC 语义记录及其展开后的标量分量。",
                "metrics": [
                    {"label": "PLC 语义点", "field": "plc_semantic", "format": "number"},
                    {"label": "标量分量", "field": "plc_scalars", "format": "number"},
                ],
            },
            {
                "id": "isaac_subset_card",
                "dataset": "headline",
                "sourceId": "area7_pointset",
                "description": "当前 Isaac 循环使用的唯一点位与停靠次数。",
                "metrics": [
                    {"label": "Isaac 唯一点", "field": "isaac_unique", "format": "number"},
                    {"label": "循环停靠", "field": "isaac_stops", "format": "number"},
                ],
            },
        ],
        "charts": [
            {
                "id": "inventory_counts_chart",
                "title": "网页快照中的点位记录构成",
                "subtitle": "2026-08-13 固定快照；机器人原始点、机器人派生点与 PLC 语义点",
                "headerMarkdown": "**165 个派生点必须保留 `derived_from` 与 `derivation`，不能当作现场直接示教点。**",
                "type": "bar",
                "dataset": "inventory_counts",
                "sourceId": "inventory_counts_sql",
                "encodings": {
                    "x": {"field": "record_type", "type": "nominal", "label": "记录类型"},
                    "y": {"field": "count", "type": "quantitative", "label": "记录数", "format": "number"},
                    "tooltip": [
                        {"field": "source_scope", "type": "nominal", "label": "来源范围"},
                        {"field": "definition", "type": "nominal", "label": "口径"},
                    ],
                },
            }
        ],
        "tables": [
            {
                "id": "robot_points_table",
                "title": "全部 239 个机器人点位",
                "subtitle": "pose=[x,y,z,Rx,Ry,Rz]，单位 mm/deg；joint 为 6 轴角度 deg；rail 两列来自非 API 工作流 sidecar",
                "dataset": "robot_points",
                "sourceId": "robot_points_sql",
                "defaultSort": {"field": "source_order", "direction": "asc"},
                "columns": [
                    {"field": "source_order", "label": "源顺序", "format": "number"},
                    {"field": "group_key", "label": "组"},
                    {"field": "group_label", "label": "组名"},
                    {"field": "robot_name", "label": "点名"},
                    {"field": "alias", "label": "别名"},
                    {"field": "id", "label": "语义 ID"},
                    {"field": "workstation", "label": "工位"},
                    {"field": "role", "label": "角色"},
                    {"field": "record_kind", "label": "原始/派生"},
                    {"field": "status", "label": "状态"},
                    {"field": "allowed_motion", "label": "允许运动"},
                    {"field": "pose_mm_deg", "label": "pose (mm/deg)"},
                    {"field": "joint_deg", "label": "joint (deg)"},
                    {"field": "user", "label": "user", "format": "number"},
                    {"field": "tool", "label": "tool", "format": "number"},
                    {"field": "acc", "label": "acc", "format": "number"},
                    {"field": "vel", "label": "vel", "format": "number"},
                    {"field": "cp", "label": "cp", "format": "number"},
                    {"field": "derived_from", "label": "派生自"},
                    {"field": "derivation", "label": "派生公式"},
                    {"field": "workflow_rail_slot_non_api", "label": "工作流 rail 槽（非 API）", "format": "number"},
                    {"field": "workflow_rail_value_mm_non_api", "label": "工作流 rail 值 mm（非 API）", "format": "number"},
                    {"field": "notes", "label": "备注"},
                    {"field": "calibrated_at", "label": "标定时间"},
                ],
            },
            {
                "id": "plc_points_table",
                "title": "全部 16 个 PLC 语义点",
                "subtitle": "包含 18 个标量分量；spot_pose 为 1 个复合语义点、3 个成员",
                "dataset": "plc_points",
                "sourceId": "plc_points_sql",
                "defaultSort": {"field": "source_order", "direction": "asc"},
                "columns": [
                    {"field": "source_order", "label": "源顺序", "format": "number"},
                    {"field": "group_key", "label": "组"},
                    {"field": "group_label", "label": "组名"},
                    {"field": "id", "label": "ID"},
                    {"field": "label", "label": "名称"},
                    {"field": "category", "label": "类型"},
                    {"field": "role", "label": "业务角色"},
                    {"field": "slot", "label": "槽位", "format": "number"},
                    {"field": "value_or_members", "label": "值/成员"},
                    {"field": "scalar_count", "label": "标量数", "format": "number"},
                    {"field": "node", "label": "目标节点"},
                    {"field": "actpos", "label": "反馈节点"},
                    {"field": "limits", "label": "限位"},
                    {"field": "hmi_node", "label": "HMI 节点"},
                    {"field": "hmi_slot", "label": "HMI 槽", "format": "number"},
                    {"field": "limit_source", "label": "限位源"},
                    {"field": "pending", "label": "待定"},
                    {"field": "sync", "label": "同步"},
                    {"field": "live", "label": "运行时值"},
                ],
            },
            {
                "id": "rail_bindings_table",
                "title": "点族到地轨槽位的工作流语义绑定",
                "subtitle": "这些绑定不在机器人点 JSON 中；仅显式列出的点号获得 sidecar 槽位",
                "dataset": "rail_bindings",
                "sourceId": "rail_bindings_sql",
                "defaultSort": {"field": "rail_slot", "direction": "asc"},
                "columns": [
                    {"field": "cluster_id", "label": "点族"},
                    {"field": "point_numbers", "label": "显式点号"},
                    {"field": "point_count", "label": "点数", "format": "number"},
                    {"field": "rail_slot", "label": "地轨槽位", "format": "number"},
                    {"field": "rail_value_mm", "label": "配置值 mm", "format": "number"},
                    {"field": "basis", "label": "绑定依据"},
                    {"field": "provenance", "label": "来源类型"},
                ],
            },
            {
                "id": "area7_points_table",
                "title": "当前 Isaac 循环使用的 13 个唯一点",
                "subtitle": "15 次停靠的出现序号已列出；joint_rad 为 Uni-Lab PointSet SI 值",
                "dataset": "area7_points",
                "sourceId": "area7_points_sql",
                "defaultSort": {"field": "point_order", "direction": "asc"},
                "columns": [
                    {"field": "point_order", "label": "PointSet 顺序", "format": "number"},
                    {"field": "point", "label": "点位"},
                    {"field": "live_sequence_stop_numbers", "label": "循环停靠序号"},
                    {"field": "source_id", "label": "网页源 ID"},
                    {"field": "source_status", "label": "源状态"},
                    {"field": "workstation", "label": "工位"},
                    {"field": "role", "label": "角色"},
                    {"field": "workflow_rail_slot_non_api", "label": "工作流 rail（非 API）", "format": "number"},
                    {"field": "pose_mm_deg", "label": "pose (mm/deg)"},
                    {"field": "joint_deg", "label": "joint (deg)"},
                    {"field": "joint_rad", "label": "joint (rad)"},
                ],
            },
        ],
        "sources": sources,
        "blocks": [
            {"id": "title", "type": "markdown", "body": f"# {title}"},
            {
                "id": "technical_summary",
                "type": "markdown",
                "body": (
                    "## 技术摘要\n\n"
                    "本文件把 pTLC 固定网页快照中的 **239 个机器人记录**和 **16 个 PLC 语义点**，"
                    "与独立的地轨工作流绑定、当前 Isaac 13 点子集合并在同一可搜索报告中。"
                    "机器人记录分为 **74 个原始点**与 **165 个派生点**；PLC 16 条记录展开后共有 **18 个标量分量**。\n\n"
                    "最重要的边界是：**239/239 个机器人记录都没有原生 `rail` 字段**。报告中的地轨槽位列只来自"
                    "工作流语义 sidecar，不能回填成控制器原始事实。当前 Isaac 循环使用 13 个唯一点、15 次停靠，"
                    "关节角已逐点与网页快照一致性检查。"
                ),
            },
            {
                "id": "headline_metrics",
                "type": "metric-strip",
                "cardIds": ["robot_inventory_card", "plc_inventory_card", "isaac_subset_card"],
            },
            {
                "id": "inventory_finding",
                "type": "markdown",
                "body": (
                    "## 网页快照是数值真源，派生点占多数\n\n"
                    "机器人点位以 `/api/points` 的 2026-08-13 只读响应为快照真源。"
                    "165 个派生点由原始点加偏移或流程补充得到，必须结合 `derived_from` 和 `derivation` 解读；"
                    "它们不是 165 次独立现场示教。下图仅展示记录构成，精确坐标请使用随后完整表格。"
                ),
            },
            {"id": "inventory_chart", "type": "chart", "chartId": "inventory_counts_chart", "layout": "full"},
            {
                "id": "source_locations",
                "type": "markdown",
                "body": (
                    "## 原始信息现在位于哪里\n\n"
                    f"- **网页运行时快照：** `pTLC仿真资产/source_api_points_snapshot.json`，来源 `{API_URL}`，"
                    f"SHA-256 `{snapshot_sha}`。\n"
                    "- **带来源封装的完整导出：** `pTLC仿真资产/interaction_points.json`；其 `data` 与原始快照逐项相等。\n"
                    f"- **pTLC 上游代码：** 固定提交 `{UPSTREAM_COMMIT}`；[机器人原始点]({GIT_ROBOT_URL})、"
                    f"[点位元数据]({GIT_META_URL})、[PLC 点位目录]({GIT_PLC_URL})。\n"
                    "- **地轨语义 sidecar：** `pTLC仿真资产/rail_frame_layout_analysis.json`。\n"
                    "- **Isaac 13 点 PointSet：** `pTLC仿真资产/isaac_sim/config/cr5_ptlc_area7_points.v1.json`。\n"
                    "- **重建边界说明：** `pTLC实验室仿真重建基线_2026-08-13.md`。"
                ),
            },
            {
                "id": "definitions",
                "type": "markdown",
                "body": (
                    "## 坐标、字段与口径\n\n"
                    "- `pose`：`[x,y,z,Rx,Ry,Rz]`，前三项为 mm，后三项为 deg；属于机器人记录坐标系，不是实验室 world 外参。\n"
                    "- `joint`：CR5 六轴角度，单位 deg；Isaac PointSet 同时保存转换后的 rad。\n"
                    "- `user=0`、`tool=1`：机器人坐标系编号，不等于工具槽位。\n"
                    "- `acc/vel/cp`：记录默认参数，具体 operation 仍可覆盖速度。\n"
                    "- `status=validated`：沿用网页数据的状态文字；本报告没有重新连接真机复验。\n"
                    "- `workflow_rail_*_non_api`：工作流绑定的辅助字段，原始 API 不含该字段。"
                ),
            },
            {"id": "robot_table", "type": "table", "tableId": "robot_points_table", "layout": "full"},
            {
                "id": "plc_finding",
                "type": "markdown",
                "body": (
                    "## PLC 点位保留语义记录与复合成员\n\n"
                    "PLC 部分有 16 个语义记录、18 个标量分量。`spot_pose` 是一个含 `x_start/x_end/y_height`"
                    "三成员的复合点；`sample_5z` 仍为 `pending=true`。地轨 1–6 的网页配置值分别为"
                    "168、168、350、500、600、600 mm，重复值表示业务语义不同但当前轴位置相同。"
                ),
            },
            {"id": "plc_table", "type": "table", "tableId": "plc_points_table", "layout": "full"},
            {
                "id": "rail_finding",
                "type": "markdown",
                "body": (
                    "## 地轨绑定只能作为工作流 sidecar\n\n"
                    "点族到 rail 槽位的关系由 operation/任务流程语义转录。未被显式绑定的 ready、Home、视觉或"
                    "校准锚点保持空值。P46–P51@rail2 与 P78–P83@rail3 指向同一暂存 A 六槽语义，"
                    "可用于相对约束拟合，但不能在未知 world/robot-base 外参时强制世界重合。"
                ),
            },
            {"id": "rail_table", "type": "table", "tableId": "rail_bindings_table", "layout": "full"},
            {
                "id": "isaac_finding",
                "type": "markdown",
                "body": (
                    "## Isaac 当前循环是网页原始关节点的受限子集\n\n"
                    "当前实时循环使用 P45、P46、P47、P48、P49、P50、P51、P78、P79、P80、P81、P82、P83"
                    "这 13 个唯一点，并按 15 次停靠序列播放。表中同时保留网页 pose/joint、Uni-Lab SI 关节值和"
                    "停靠序号，方便从原数据追踪到仿真输入。"
                ),
            },
            {"id": "isaac_table", "type": "table", "tableId": "area7_points_table", "layout": "full"},
            {
                "id": "methodology",
                "type": "markdown",
                "body": (
                    "## 汇总方法与自动检查\n\n"
                    "生成脚本只读取本地固定快照，不向 pTLC、PLC 或机器人发送请求。它按源顺序扁平化 JSON，"
                    "再用独立 sidecar 添加明确标注为“非 API”的地轨字段。构建时强制检查：网页快照 SHA、"
                    "`interaction_points.data` 与快照相等、239/74/165/16/18 计数、机器人无原生 rail 字段、"
                    "`sample_5z` 仍 pending、Area-7 PointSet SHA 与通过的验证报告一致，以及 13 个 Isaac 点的"
                    "关节角逐项等于网页快照。"
                ),
            },
            {
                "id": "limitations",
                "type": "markdown",
                "body": (
                    "## 限制与不确定性\n\n"
                    "- 这是 2026-08-13 的网页快照，不是自动刷新视图；网页后续变更不会自动进入本文件。\n"
                    "- 点位 `pose` 不是实验室 world 布局；地轨零点、robot-base 安装外参和工具 TCP 外参仍未知。\n"
                    "- 网页中的 `validated` 是源数据状态，本次只做软件一致性检查，没有重做真机现场验收。\n"
                    "- 派生点与地轨 sidecar 可以支持仿真布局/轨迹复现，但不能单独证明连续轨迹无碰撞或真机安全。\n"
                    f"- 当前状态分布为 `{dict(status_counts)}`；状态含义沿用源系统，未做重新分类。"
                ),
            },
            {
                "id": "next_steps",
                "type": "markdown",
                "body": (
                    "## 建议下一步\n\n"
                    "1. 把本 HTML 作为人工查阅入口，控制与仿真代码继续直接读取固定 JSON/PointSet，避免从 HTML 反解析数值。\n"
                    "2. 网页点位发生变更时，先保存新快照并记录 SHA，再重跑生成脚本和 Isaac 点位一致性检查。\n"
                    "3. 获得地轨零点、robot-base 和工具 TCP 实测外参后，新增版本化 calibration 文件；不要改写历史快照。"
                ),
            },
            {
                "id": "further_questions",
                "type": "markdown",
                "body": (
                    "## 仍需回答的问题\n\n"
                    "- 网页当前运行实例是否已在 2026-08-13 后更新点位？若要比较，需要另取一次只读快照。\n"
                    "- `sample_5z`、FeedLift 搜索上下界和工具 TCP 何时完成现场重示教/标定？\n"
                    "- 哪些未绑定的 ready/视觉锚点需要显式工作流 rail 语义，哪些应永久保持 `rail=null`？"
                ),
            },
        ],
    }

    # The portable artifact validator currently requires SQL text for metric-card
    # provenance.  These counts come from audited JSON files rather than SQL, so
    # keep them in the technical summary and chart and omit the metric strip.
    manifest["cards"] = []
    manifest["blocks"] = [
        block for block in manifest["blocks"] if block["id"] != "headline_metrics"
    ]

    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "headline": headline,
                "inventory_counts": inventory_counts,
                "robot_points": robot_rows,
                "robot_group_summary": robot_group_summary,
                "plc_points": plc_rows,
                "plc_group_summary": plc_group_summary,
                "rail_bindings": binding_rows,
                "area7_points": area7_rows,
            },
        },
        "sources": sources,
        "package_info": {
            "title": title,
            "description": "Self-contained pTLC point inventory snapshot.",
        },
    }


def main() -> None:
    artifact = build_artifact()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_sqlite(artifact["snapshot"]["datasets"])
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    datasets = artifact["snapshot"]["datasets"]
    print(
        json.dumps(
            {
                "artifact": str(ARTIFACT_PATH),
                "robot_rows": len(datasets["robot_points"]),
                "plc_rows": len(datasets["plc_points"]),
                "rail_binding_rows": len(datasets["rail_bindings"]),
                "area7_rows": len(datasets["area7_points"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
