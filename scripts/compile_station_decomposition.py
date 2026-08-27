#!/usr/bin/env python3
"""把已验证工站 source handoff 与人审分解表编译为部署位姿候选。"""

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

DECOMPOSITION_SCHEMA = "lab.station_decomposition/v0"
LAYOUT_SCHEMA = "lab.station_layout_candidate/v0"
FORBIDDEN_KEYS = {
    "device_id",
    "base_pose",
    "tcp",
    "payload",
    "point_table",
    "current_joints",
}


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
    if decomposition.get("station") != manifest.get("station"):
        raise DecompositionError("decomposition.station 与 handoff.station 不一致")
    forbidden = sorted(_find_forbidden_keys(decomposition))
    if forbidden:
        raise DecompositionError("家族/工站分解出现部署禁字段: " + ", ".join(forbidden))
    expected_handoff_digest = str(decomposition.get("source_handoff_digest") or "")
    actual_handoff_digest = _sha256(manifest_path)
    if expected_handoff_digest != actual_handoff_digest:
        raise DecompositionError("source_handoff_digest 与交接清单字节不一致")
    approval = _mapping(decomposition.get("approval"), "approval")
    approved = approval.get("status") == "approved"
    if approved:
        _text(approval.get("reviewed_by"), "approval.reviewed_by")
        _text(approval.get("reviewed_at"), "approval.reviewed_at")
    elif not allow_draft:
        raise DecompositionError("分解表尚未 approved；仅预览可显式使用 --allow-draft")

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
    for index, raw in enumerate(instances):
        item = _mapping(raw, f"instances[{index}]")
        occurrence_id = _text(item.get("id"), f"instances[{index}].id")
        if occurrence_id in by_id:
            raise DecompositionError(f"occurrence id 重复: {occurrence_id}")
        by_id[occurrence_id] = item

    rules: list[dict[str, Any]] = []
    devices = decomposition.get("devices")
    robots = decomposition.get("robot_subtrees")
    if not isinstance(devices, list):
        raise DecompositionError("devices 必须是数组")
    if not isinstance(robots, list):
        raise DecompositionError("robot_subtrees 必须是数组")
    for index, raw in enumerate(devices):
        item = _mapping(raw, f"devices[{index}]")
        kind = _text(item.get("kind"), f"devices[{index}].kind")
        if kind not in {"device", "static_environment"}:
            raise DecompositionError(f"devices[{index}].kind 不受支持")
        rules.append(
            {
                "rule": f"devices[{index}]",
                "family": _text(item.get("family"), f"devices[{index}].family"),
                "kind": kind,
                "match": item.get("match"),
                "anchor_occurrence": item.get("anchor_occurrence"),
            }
        )
    for index, raw in enumerate(robots):
        item = _mapping(raw, f"robot_subtrees[{index}]")
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
                "match": item.get("match"),
                "anchor_occurrence": item.get("anchor_occurrence"),
            }
        )

    ownership: dict[str, str] = {}
    placements: list[dict[str, Any]] = []
    for rule in rules:
        match = _mapping(rule["match"], f"{rule['rule']}.match")
        if set(match) != {"occurrence_prefix"}:
            raise DecompositionError(
                f"{rule['rule']}.match 只允许 occurrence_prefix"
            )
        prefix = _text(match.get("occurrence_prefix"), f"{rule['rule']}.match.occurrence_prefix")
        matched = sorted(name for name in by_id if name.startswith(prefix))
        if not matched:
            raise DecompositionError(f"{rule['rule']} 未匹配任何 occurrence")
        for occurrence_id in matched:
            previous = ownership.setdefault(occurrence_id, rule["rule"])
            if previous != rule["rule"]:
                raise DecompositionError(
                    f"occurrence {occurrence_id} 同时属于 {previous} 与 {rule['rule']}"
                )
        anchor = _resolve_anchor(rule, matched, by_id)
        transform = _mapping(
            by_id[anchor].get("transform_world"),
            f"{anchor}.transform_world",
        )
        placement: dict[str, Any] = {
            "family": rule["family"],
            "kind": rule["kind"],
            "anchor_occurrence": anchor,
            "source_occurrences": matched,
            "transform_world": {
                "xyz_m": transform.get("xyz_m"),
                "quat_xyzw": transform.get("quat_xyzw"),
            },
        }
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
    if decomposition.get("unassigned_policy") != "fail":
        raise DecompositionError("unassigned_policy 必须是 fail")

    return {
        "schema": LAYOUT_SCHEMA,
        "station": manifest["station"],
        "source_handoff_digest": actual_handoff_digest,
        "source_decomposition_digest": _sha256(decomposition_path),
        "candidate": True,
        "human_reviewed": approved,
        "not_a_deploy_manifest": True,
        "not_a_workcell_activation": True,
        "placements": placements,
        "unassigned_occurrences": [],
        "qualification": "station-layout-candidate",
        "not_qualified_for": [
            "base_pose",
            "tcp",
            "point_table",
            "collision",
            "spatial-interlock-enforced",
            "execution",
        ],
    }


def _resolve_anchor(
    rule: dict[str, Any],
    matched: list[str],
    by_id: dict[str, dict[str, Any]],
) -> str:
    explicit = rule.get("anchor_occurrence")
    if explicit is not None:
        anchor = _text(explicit, f"{rule['rule']}.anchor_occurrence")
        if anchor not in matched:
            raise DecompositionError(
                f"{rule['rule']}.anchor_occurrence 不属于该规则匹配结果"
            )
        return anchor
    matched_set = set(matched)
    candidates = [
        occurrence_id
        for occurrence_id in matched
        if by_id[occurrence_id].get("parent") not in matched_set
    ]
    if len(candidates) != 1:
        raise DecompositionError(
            f"{rule['rule']} 无法唯一推导 anchor_occurrence；候选={candidates}"
        )
    return candidates[0]


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("decomposition", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-draft", action="store_true")
    args = parser.parse_args()
    try:
        result = compile_station(
            args.manifest,
            args.decomposition,
            allow_draft=args.allow_draft,
        )
    except DecompositionError as error:
        sys.stderr.write(f"station decomposition rejected: {error}\n")
        return 1
    _write_json(args.output, result)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
