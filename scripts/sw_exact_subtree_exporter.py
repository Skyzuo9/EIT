#!/usr/bin/env python3
"""Fail-closed, read-only dry-run for approved SolidWorks occurrence subtrees.

This module deliberately has no COM imports and performs no SolidWorks calls.  Its
only effect is an optional JSON receipt written after all approval and exact-root
checks pass.  Actual W2 export is a separate, still-unimplemented authority path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finalize_station_geometry_handoff import (  # noqa: E402
    GeometryHandoffError,
    _relative_handoff_file,
    _validate_approval_inputs,
    sha256,
)


REQUEST_SCHEMA = "lab.sw_exact_subtree_export_request/v1"
RECEIPT_SCHEMA = "lab.sw_exact_subtree_export_dry_run/v1"
DIGEST = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*-w2-dry-run$")
ASSET_INSTANCE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ExactSubtreeDryRunError(RuntimeError):
    """Approval, source binding, or exact occurrence selection failed."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExactSubtreeDryRunError(f"{label} 不是可读 UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ExactSubtreeDryRunError(f"{label} 必须是 JSON 对象")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExactSubtreeDryRunError(f"{field} 必须是非空文本")
    return value.strip()


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("缺少 " + ", ".join(missing))
        if unexpected:
            detail.append("不支持 " + ", ".join(unexpected))
        raise ExactSubtreeDryRunError(f"{field} 字段错误: {'; '.join(detail)}")


def _digest(value: Any, field: str) -> str:
    text = _text(value, field)
    if DIGEST.fullmatch(text) is None:
        raise ExactSubtreeDryRunError(f"{field} 必须是 64 位小写 sha256")
    return text


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_request(request: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        request,
        {
            "schema", "run_id", "mode", "station", "source_read_only",
            "approval_binding", "solidworks", "exporter", "devices",
        },
        "request",
    )
    if request.get("schema") != REQUEST_SCHEMA:
        raise ExactSubtreeDryRunError(f"request.schema 必须是 {REQUEST_SCHEMA}")
    run_id = _text(request.get("run_id"), "request.run_id")
    if RUN_ID.fullmatch(run_id) is None:
        raise ExactSubtreeDryRunError("request.run_id 必须以 -w2-dry-run 结尾")
    if request.get("mode") != "dry-run":
        raise ExactSubtreeDryRunError("只允许 mode=dry-run；W2 执行未获授权")
    if request.get("source_read_only") is not True:
        raise ExactSubtreeDryRunError("source_read_only 必须为 true")

    binding = request.get("approval_binding")
    if not isinstance(binding, dict):
        raise ExactSubtreeDryRunError("approval_binding 必须是对象")
    _exact_keys(
        binding,
        {
            "source_handoff_sha256", "source_decomposition_sha256",
            "station_layout_sha256", "source_files_digest",
        },
        "approval_binding",
    )
    binding_value = {key: _digest(value, f"approval_binding.{key}") for key, value in binding.items()}

    solidworks = request.get("solidworks")
    if not isinstance(solidworks, dict):
        raise ExactSubtreeDryRunError("solidworks 必须是对象")
    _exact_keys(solidworks, {"revision", "configuration"}, "solidworks")
    solidworks_value = {
        "revision": _text(solidworks.get("revision"), "solidworks.revision"),
        "configuration": _text(solidworks.get("configuration"), "solidworks.configuration"),
    }

    exporter = request.get("exporter")
    if not isinstance(exporter, dict):
        raise ExactSubtreeDryRunError("exporter 必须是对象")
    _exact_keys(exporter, {"name", "version", "selection_mode"}, "exporter")
    if exporter.get("name") != "SwExactSubtreeExporter":
        raise ExactSubtreeDryRunError("exporter.name 必须是 SwExactSubtreeExporter")
    if exporter.get("selection_mode") != "approved-exact-occurrence-root":
        raise ExactSubtreeDryRunError("selection_mode 必须是 approved-exact-occurrence-root")
    exporter_value = {
        "name": "SwExactSubtreeExporter",
        "version": _text(exporter.get("version"), "exporter.version"),
        "selection_mode": "approved-exact-occurrence-root",
    }

    raw_devices = request.get("devices")
    if not isinstance(raw_devices, list) or not raw_devices:
        raise ExactSubtreeDryRunError("devices 必须是非空数组")
    devices = []
    for index, raw in enumerate(raw_devices):
        field = f"devices[{index}]"
        if not isinstance(raw, dict):
            raise ExactSubtreeDryRunError(f"{field} 必须是对象")
        _exact_keys(raw, {"asset_instance", "slice_role", "family", "exact_subtree_root"}, field)
        asset = _text(raw.get("asset_instance"), f"{field}.asset_instance")
        if ASSET_INSTANCE.fullmatch(asset) is None:
            raise ExactSubtreeDryRunError(f"{field}.asset_instance 必须是安全 ASCII slug")
        devices.append(
            {
                "asset_instance": asset,
                "slice_role": _text(raw.get("slice_role"), f"{field}.slice_role"),
                "family": _text(raw.get("family"), f"{field}.family"),
                "exact_subtree_root": _text(raw.get("exact_subtree_root"), f"{field}.exact_subtree_root"),
            }
        )
    if len({item["asset_instance"] for item in devices}) != len(devices):
        raise ExactSubtreeDryRunError("asset_instance 不得重复")
    if len({item["exact_subtree_root"] for item in devices}) != len(devices):
        raise ExactSubtreeDryRunError("exact_subtree_root 不得重复")
    return {
        "run_id": run_id,
        "station": _text(request.get("station"), "request.station"),
        "approval_binding": binding_value,
        "solidworks": solidworks_value,
        "exporter": exporter_value,
        "devices": devices,
    }


def resolve_approved_roots(
    *,
    request_path: Path,
    station_handoff: Path,
    decomposition: Path,
    station_layout: Path,
    coverage_report: Path,
    review: Path,
) -> dict[str, Any]:
    """Resolve approved exact occurrence selections without invoking SolidWorks."""

    request = _validate_request(_read_json(request_path, "dry-run request"))
    try:
        handoff, layout, _, source_digest = _validate_approval_inputs(
            station_handoff, decomposition, station_layout, coverage_report, review
        )
    except GeometryHandoffError as error:
        raise ExactSubtreeDryRunError(f"审批门失败，拒绝解析 occurrence roots: {error}") from error

    if request["station"] != handoff.get("station"):
        raise ExactSubtreeDryRunError("request.station 与批准 handoff 不一致")
    actual_binding = {
        "source_handoff_sha256": sha256(station_handoff),
        "source_decomposition_sha256": sha256(decomposition),
        "station_layout_sha256": sha256(station_layout),
        "source_files_digest": source_digest,
    }
    if request["approval_binding"] != actual_binding:
        raise ExactSubtreeDryRunError("approval_binding 与当前批准证据不一致")

    capture = handoff.get("solidworks_capture")
    if not isinstance(capture, dict):
        raise ExactSubtreeDryRunError("handoff.solidworks_capture 缺失")
    try:
        snapshot_path = _relative_handoff_file(
            station_handoff.resolve().parent,
            capture.get("assembly_snapshot"),
            "solidworks_capture.assembly_snapshot",
        )
    except GeometryHandoffError as error:
        raise ExactSubtreeDryRunError(str(error)) from error
    snapshot = _read_json(snapshot_path, "assembly.snapshot.json")
    if snapshot.get("schema") != "lab.assembly_snapshot/v0":
        raise ExactSubtreeDryRunError("assembly snapshot schema 不受支持")
    raw_instances = snapshot.get("instances")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise ExactSubtreeDryRunError("assembly snapshot 没有 instances")
    instance_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_instances):
        if not isinstance(raw, dict):
            raise ExactSubtreeDryRunError(f"snapshot.instances[{index}] 必须是对象")
        occurrence_id = _text(raw.get("id"), f"snapshot.instances[{index}].id")
        if occurrence_id in instance_by_id:
            raise ExactSubtreeDryRunError(f"snapshot occurrence id 重复: {occurrence_id}")
        instance_by_id[occurrence_id] = raw

    raw_placements = layout.get("placements")
    if not isinstance(raw_placements, list):
        raise ExactSubtreeDryRunError("批准 layout 缺少 placements")
    placements = {
        item.get("subtree_root"): item
        for item in raw_placements
        if isinstance(item, dict) and isinstance(item.get("subtree_root"), str)
    }
    resolved = []
    for device in request["devices"]:
        root = device["exact_subtree_root"]
        placement = placements.get(root)
        if placement is None:
            raise ExactSubtreeDryRunError(f"不是批准 layout 的精确 occurrence root: {root}")
        if device["family"] != placement.get("family"):
            raise ExactSubtreeDryRunError(f"{root} 的 family 与批准 layout 不一致")
        approved_occurrences = placement.get("source_occurrences")
        if not isinstance(approved_occurrences, list) or root not in approved_occurrences:
            raise ExactSubtreeDryRunError(f"{root} 的批准 source_occurrences 不完整")
        if len(approved_occurrences) != len(set(approved_occurrences)):
            raise ExactSubtreeDryRunError(f"{root} 的批准 source_occurrences 含重复项")
        missing = sorted(set(approved_occurrences) - set(instance_by_id))
        if missing:
            raise ExactSubtreeDryRunError(f"{root} 的批准 occurrence 在 snapshot 缺失: {missing[0]}")

        excluded = placement.get("excluded_subtree_roots", [])
        if not isinstance(excluded, list):
            raise ExactSubtreeDryRunError(f"{root}.excluded_subtree_roots 必须是数组")
        structural = sorted(
            occurrence_id
            for occurrence_id in instance_by_id
            if occurrence_id == root or occurrence_id.startswith(root + "/")
        )
        computed = [
            occurrence_id
            for occurrence_id in structural
            if not any(
                occurrence_id == excluded_root
                or occurrence_id.startswith(excluded_root + "/")
                for excluded_root in excluded
            )
        ]
        approved_sorted = sorted(approved_occurrences)
        if computed != approved_sorted:
            raise ExactSubtreeDryRunError(
                f"{root} 的结构解析结果与批准 source_occurrences 不一致"
            )
        selection = {
            **device,
            "approved_kind": placement.get("kind"),
            "excluded_exact_subtree_roots": sorted(excluded),
            "resolved_occurrence_count": len(computed),
            "resolved_occurrence_ids": computed,
            "resolved_occurrences_sha256": _canonical_sha256(computed),
        }
        resolved.append(selection)

    selection_payload = [
        {
            "exact_subtree_root": item["exact_subtree_root"],
            "excluded_exact_subtree_roots": item["excluded_exact_subtree_roots"],
            "resolved_occurrence_ids": item["resolved_occurrence_ids"],
        }
        for item in resolved
    ]
    return {
        "schema": RECEIPT_SCHEMA,
        "run_id": request["run_id"],
        "status": "approved-roots-resolved",
        "effect": "none",
        "w2_export_started": False,
        "solidworks_api_calls": 0,
        "source_mutations": 0,
        "host": {"system": platform.system(), "release": platform.release()},
        "approval_binding": actual_binding,
        "solidworks": request["solidworks"],
        "exporter": request["exporter"],
        "snapshot": {
            "path": str(snapshot_path),
            "sha256": sha256(snapshot_path),
            "occurrence_count": len(instance_by_id),
        },
        "devices": resolved,
        "selection_sha256": _canonical_sha256(selection_payload),
        "not_qualified_for": [
            "w2-export", "geometry", "collision", "deployment",
            "workcell-activation", "execution",
        ],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--station-handoff", type=Path, required=True)
    parser.add_argument("--decomposition", type=Path, required=True)
    parser.add_argument("--station-layout", type=Path, required=True)
    parser.add_argument("--coverage-report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = resolve_approved_roots(
            request_path=args.request,
            station_handoff=args.station_handoff,
            decomposition=args.decomposition,
            station_layout=args.station_layout,
            coverage_report=args.coverage_report,
            review=args.review,
        )
    except ExactSubtreeDryRunError as error:
        print(json.dumps({"passed": False, "effect": "none", "error": str(error)}, ensure_ascii=False))
        return 2
    if args.output:
        _write_json(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
