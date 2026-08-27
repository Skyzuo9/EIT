#!/usr/bin/env python3
"""把已验证工站 handoff 与人审分解表编译为精确部署位姿候选。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_station_handoff import HandoffValidation  # noqa: E402

DECOMPOSITION_SCHEMA = "lab.station_decomposition/v1"
LAYOUT_SCHEMA = "lab.station_layout_candidate/v1"
COVERAGE_SCHEMA = "lab.station_decomposition_coverage/v1"
FORBIDDEN_KEYS = {
    "device_id",
    "base_pose",
    "tcp",
    "payload",
    "point_table",
    "pointset",
    "programset",
    "calibration",
    "current_joints",
    "site_uuid",
}
TOP_LEVEL_KEYS = {
    "schema",
    "station",
    "source_handoff_digest",
    "devices",
    "robot_subtrees",
    "unassigned_policy",
    "approval",
}
DEVICE_KEYS = {"family", "kind", "subtree_root", "review_note"}
ROBOT_KEYS = {"replaced_by", "subtree_root", "review_note"}
APPROVAL_KEYS = {"status", "reviewed_by", "reviewed_at", "notes"}


class DecompositionError(ValueError):
    """工站分解无法形成无歧义候选时的失败关闭结果。"""


def compile_station(
    manifest_path: Path,
    decomposition_path: Path,
    *,
    allow_draft: bool = False,
) -> dict[str, Any]:
    """验证输入并产生不含部署实例事实的工站 layout 候选。"""

    validation = HandoffValidation(manifest_path).run()
    if not validation["passed"]:
        raise DecompositionError(
            "station handoff 未通过: " + "; ".join(validation["errors"])
        )
    manifest = _read_json(manifest_path)
    decomposition = _read_yaml(decomposition_path)
    if decomposition.get("schema") != DECOMPOSITION_SCHEMA:
        raise DecompositionError(f"decomposition schema 必须是 {DECOMPOSITION_SCHEMA}")
    unexpected = sorted(set(decomposition) - TOP_LEVEL_KEYS)
    if unexpected:
        raise DecompositionError("decomposition 含不支持字段: " + ", ".join(unexpected))
    if decomposition.get("station") != manifest.get("station"):
        raise DecompositionError("decomposition.station 与 handoff.station 不一致")
    forbidden = sorted(_find_forbidden_keys(decomposition))
    if forbidden:
        raise DecompositionError("家族/工站分解出现部署禁字段: " + ", ".join(forbidden))
    expected_handoff_digest = str(decomposition.get("source_handoff_digest") or "")
    actual_handoff_digest = _sha256(manifest_path)
    if expected_handoff_digest != actual_handoff_digest:
        raise DecompositionError("source_handoff_digest 与交接清单字节不一致")
    if decomposition.get("unassigned_policy") != "fail":
        raise DecompositionError("unassigned_policy 必须是 fail")
    approval = _validate_approval(decomposition.get("approval"), allow_draft=allow_draft)
    approved = approval["status"] == "approved"

    capture = _mapping(manifest.get("solidworks_capture"), "solidworks_capture")
    snapshot_path = _relative_file(
        manifest_path.parent,
        capture.get("assembly_snapshot"),
        "assembly_snapshot",
    )
    snapshot = _read_json(snapshot_path)
    instances = snapshot.get("instances")
    if not isinstance(instances, list) or not instances:
        raise DecompositionError("assembly snapshot 没有 instances")
    by_id: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    for index, raw in enumerate(instances):
        item = _mapping(raw, f"instances[{index}]")
        occurrence_id = _text(item.get("id"), f"instances[{index}].id")
        if occurrence_id in by_id:
            raise DecompositionError(f"occurrence id 重复: {occurrence_id}")
        by_id[occurrence_id] = item
        children[occurrence_id] = []
    for occurrence_id, item in by_id.items():
        parent = item.get("parent")
        if parent is not None:
            if parent not in by_id:
                raise DecompositionError(f"occurrence parent 不存在: {occurrence_id} -> {parent}")
            children[parent].append(occurrence_id)
    for child_ids in children.values():
        child_ids.sort()

    rules = _parse_rules(decomposition)
    if not rules:
        raise DecompositionError("decomposition 至少需要一个 device 或 robot subtree")

    ownership: dict[str, dict[str, Any]] = {}
    placements: list[dict[str, Any]] = []
    for rule in rules:
        root = rule["subtree_root"]
        if root not in by_id:
            raise DecompositionError(f"{rule['rule']}.subtree_root 不存在: {root}")
        matched = _descendants(root, children)
        for occurrence_id in matched:
            previous = ownership.get(occurrence_id)
            if previous is not None:
                raise DecompositionError(
                    f"occurrence {occurrence_id} 同时属于 {previous['rule']} 与 {rule['rule']}"
                )
            ownership[occurrence_id] = rule
        transform = _mapping(
            by_id[root].get("transform_world"),
            f"{root}.transform_world",
        )
        placement: dict[str, Any] = {
            "family": rule["family"],
            "kind": rule["kind"],
            "subtree_root": root,
            "anchor_occurrence": root,
            "source_rule": rule["rule"],
            "source_occurrence_count": len(matched),
            "source_occurrences": matched,
            "transform_world": {
                "xyz_m": transform.get("xyz_m"),
                "quat_xyzw": transform.get("quat_xyzw"),
            },
        }
        if rule.get("review_note"):
            placement["review_note"] = rule["review_note"]
        if rule["kind"] == "robot_replacement":
            placement["solidworks_geometry_role"] = "comparison_only"
            placement["kinematics_source"] = rule["family"]
        placements.append(placement)

    unassigned = sorted(set(by_id) - set(ownership))
    if unassigned:
        raise DecompositionError(
            "存在未分配 occurrence，按 unassigned_policy=fail 拒绝: "
            + ", ".join(unassigned[:20])
        )

    decomposition_digest = _sha256(decomposition_path)
    coverage = [
        {
            "occurrence": occurrence_id,
            "parent": by_id[occurrence_id].get("parent"),
            "source_rule": ownership[occurrence_id]["rule"],
            "subtree_root": ownership[occurrence_id]["subtree_root"],
            "family": ownership[occurrence_id]["family"],
            "kind": ownership[occurrence_id]["kind"],
        }
        for occurrence_id in sorted(by_id)
    ]
    qualification = (
        "station-layout-candidate" if approved else "decomposition-draft-preview"
    )
    return {
        "schema": LAYOUT_SCHEMA,
        "station": manifest["station"],
        "source_handoff_digest": actual_handoff_digest,
        "source_decomposition_digest": decomposition_digest,
        "candidate": True,
        "human_reviewed": approved,
        "publication_eligible": approved,
        "approval": approval,
        "not_a_deploy_manifest": True,
        "not_a_workcell_activation": True,
        "placements": placements,
        "occurrence_coverage": coverage,
        "unassigned_occurrences": [],
        "qualification": qualification,
        "not_qualified_for": [
            "base_pose",
            "tcp",
            "point_table",
            "collision",
            "spatial-interlock-enforced",
            "execution",
        ],
    }


def _parse_rules(decomposition: dict[str, Any]) -> list[dict[str, Any]]:
    devices = decomposition.get("devices")
    robots = decomposition.get("robot_subtrees")
    if not isinstance(devices, list):
        raise DecompositionError("devices 必须是数组")
    if not isinstance(robots, list):
        raise DecompositionError("robot_subtrees 必须是数组")
    rules: list[dict[str, Any]] = []
    for index, raw in enumerate(devices):
        item = _mapping(raw, f"devices[{index}]")
        unexpected = sorted(set(item) - DEVICE_KEYS)
        if unexpected:
            raise DecompositionError(
                f"devices[{index}] 含不支持字段: {', '.join(unexpected)}"
            )
        kind = _text(item.get("kind"), f"devices[{index}].kind")
        if kind not in {"device", "static_environment"}:
            raise DecompositionError(f"devices[{index}].kind 不受支持")
        rules.append(
            {
                "rule": f"devices[{index}]",
                "family": _text(item.get("family"), f"devices[{index}].family"),
                "kind": kind,
                "subtree_root": _text(
                    item.get("subtree_root"),
                    f"devices[{index}].subtree_root",
                ),
                "review_note": _optional_text(item.get("review_note")),
            }
        )
    for index, raw in enumerate(robots):
        item = _mapping(raw, f"robot_subtrees[{index}]")
        unexpected = sorted(set(item) - ROBOT_KEYS)
        if unexpected:
            raise DecompositionError(
                f"robot_subtrees[{index}] 含不支持字段: {', '.join(unexpected)}"
            )
        replacement = _text(
            item.get("replaced_by"),
            f"robot_subtrees[{index}].replaced_by",
        )
        if not replacement.startswith("robot-family:"):
            raise DecompositionError("robot_subtrees.replaced_by 必须是 robot-family: 引用")
        rules.append(
            {
                "rule": f"robot_subtrees[{index}]",
                "family": replacement,
                "kind": "robot_replacement",
                "subtree_root": _text(
                    item.get("subtree_root"),
                    f"robot_subtrees[{index}].subtree_root",
                ),
                "review_note": _optional_text(item.get("review_note")),
            }
        )
    return rules


def _validate_approval(value: Any, *, allow_draft: bool) -> dict[str, str]:
    approval = _mapping(value, "approval")
    unexpected = sorted(set(approval) - APPROVAL_KEYS)
    if unexpected:
        raise DecompositionError("approval 含不支持字段: " + ", ".join(unexpected))
    status = _text(approval.get("status"), "approval.status")
    if status not in {"approved", "draft"}:
        raise DecompositionError("approval.status 只允许 approved 或 draft")
    reviewed_by = _optional_text(approval.get("reviewed_by"))
    reviewed_at = _optional_text(approval.get("reviewed_at"))
    notes = _optional_text(approval.get("notes"))
    if status == "approved":
        if not reviewed_by:
            raise DecompositionError("approval.reviewed_by 必须是非空文本")
        if not reviewed_at:
            raise DecompositionError("approval.reviewed_at 必须是非空文本")
    elif not allow_draft:
        raise DecompositionError("分解表尚未 approved；仅预览可显式使用 --allow-draft")
    return {
        "status": status,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "notes": notes,
    }


def _descendants(root: str, children: dict[str, list[str]]) -> list[str]:
    result: list[str] = []
    pending = [root]
    while pending:
        current = pending.pop()
        result.append(current)
        pending.extend(reversed(children[current]))
    return sorted(result)


def build_coverage_report(layout: dict[str, Any]) -> dict[str, Any]:
    """从已编译 layout 生成可单独审计的 occurrence coverage 报告。"""

    coverage = layout.get("occurrence_coverage")
    placements = layout.get("placements")
    if not isinstance(coverage, list) or not isinstance(placements, list):
        raise DecompositionError("layout 缺少 occurrence coverage 或 placements")
    return {
        "schema": COVERAGE_SCHEMA,
        "status": "passed" if layout.get("human_reviewed") else "draft-preview",
        "station": layout.get("station"),
        "source_handoff_digest": layout.get("source_handoff_digest"),
        "source_decomposition_digest": layout.get("source_decomposition_digest"),
        "approval": layout.get("approval"),
        "placement_count": len(placements),
        "occurrence_count": len(coverage),
        "assigned_occurrence_count": len(coverage),
        "unassigned_occurrences": [],
        "overlapping_occurrences": [],
        "exact_coverage": True,
        "publication_eligible": layout.get("publication_eligible") is True,
        "placements": [
            {
                "source_rule": item.get("source_rule"),
                "subtree_root": item.get("subtree_root"),
                "family": item.get("family"),
                "kind": item.get("kind"),
                "source_occurrence_count": item.get("source_occurrence_count"),
            }
            for item in placements
        ],
        "occurrences": coverage,
        "not_qualified_for": layout.get("not_qualified_for", []),
    }


def render_review_markdown(layout: dict[str, Any], coverage: dict[str, Any]) -> str:
    """渲染供机械/自动化负责人签阅的只读摘要。"""

    approval = _mapping(layout.get("approval"), "layout.approval")
    lines = [
        "# 工站分解人审摘要",
        "",
        f"- station：`{layout.get('station')}`",
        f"- 状态：`{coverage.get('status')}`",
        f"- occurrence 覆盖：{coverage.get('assigned_occurrence_count')}/{coverage.get('occurrence_count')}",
        f"- placement 数量：{coverage.get('placement_count')}",
        f"- 审核人：{approval.get('reviewed_by') or '未填写'}",
        f"- 审核时间：{approval.get('reviewed_at') or '未填写'}",
        f"- 可进入发布候选：`{str(layout.get('publication_eligible') is True).lower()}`",
        "",
        "| 规则 | 精确 subtree root | family | kind | occurrence 数 |",
        "|---|---|---|---|---:|",
    ]
    for item in coverage.get("placements", []):
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(item.get(key))
                for key in (
                    "source_rule",
                    "subtree_root",
                    "family",
                    "kind",
                    "source_occurrence_count",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 人工确认项",
            "",
            "- [ ] 设备边界与重复实例数量正确",
            "- [ ] 机器人 CAD 子树仅作 `comparison_only`，运动学来自厂家家族",
            "- [ ] 每个 subtree root 是稳定 SolidWorks occurrence 身份",
            "- [ ] 隐藏、抑制和活动机构候选已逐项处置",
            "- [ ] CAD 位姿仅为 `station-layout-candidate`，不是现场 `base_pose`",
            "",
            "该报告不授予部署、碰撞、空间互锁或执行资格。",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _find_forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {str(key) for key in value if str(key) in FORBIDDEN_KEYS}
        for item in value.values():
            found.update(_find_forbidden_keys(item))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found.update(_find_forbidden_keys(item))
        return found
    return set()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DecompositionError(f"无法读取 JSON {path}: {error}") from error


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DecompositionError(f"无法读取 YAML {path}: {error}") from error


def _relative_file(root: Path, value: Any, field: str) -> Path:
    relative = Path(_text(value, field))
    if relative.is_absolute():
        raise DecompositionError(f"{field} 必须是相对路径")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise DecompositionError(f"{field} 路径越出 handoff 目录") from error
    if not target.is_file():
        raise DecompositionError(f"{field} 文件缺失: {target}")
    return target


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DecompositionError(f"{field} 必须是对象")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecompositionError(f"{field} 必须是非空文本")
    return value.strip()


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DecompositionError("可选说明字段必须是文本")
    return value.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("decomposition", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--coverage-output", type=Path)
    parser.add_argument("--review-output", type=Path)
    parser.add_argument("--allow-draft", action="store_true")
    args = parser.parse_args()
    try:
        layout = compile_station(
            args.manifest,
            args.decomposition,
            allow_draft=args.allow_draft,
        )
        coverage = build_coverage_report(layout)
        review = render_review_markdown(layout, coverage)
    except DecompositionError as error:
        sys.stderr.write(f"station decomposition rejected: {error}\n")
        return 1
    coverage_output = args.coverage_output or args.output.with_name("coverage-report.json")
    review_output = args.review_output or args.output.with_name("DECOMPOSITION-REVIEW.md")
    _write_json(args.output, layout)
    _write_json(coverage_output, coverage)
    _write_text(review_output, review)
    sys.stdout.write(
        json.dumps(
            {
                "layout": layout,
                "outputs": {
                    "layout": str(args.output),
                    "coverage": str(coverage_output),
                    "review": str(review_output),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
