#!/usr/bin/env python3
"""Compare Mac/Windows collision candidate reports at an explicit QC boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "lab.collision_candidate_cross_platform_comparison/v1"
SIMPLIFIED_LIMITS = {
    "vertex_relative_difference": 0.01,
    "triangle_relative_difference": 0.001,
    "component_relative_difference": 0.02,
    "bounds_absolute_difference_m": 1e-8,
    "missed_envelope_absolute_difference_m": 1e-6,
}


class CandidateComparisonError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateComparisonError(f"报告不可读: {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != "lab.collision_candidate_report/v1":
        raise CandidateComparisonError(f"不是 collision candidate report/v1: {path}")
    return value


def _relative_difference(left: int | float, right: int | float) -> float:
    return abs(float(left) - float(right)) / max(abs(float(left)), abs(float(right)), 1e-15)


def _max_abs(left: Any, right: Any) -> float:
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return max((_max_abs(a, b) for a, b in zip(left, right)), default=0.0)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right))
    return 0.0 if left == right else float("inf")


def compare(left_path: Path, right_path: Path) -> dict[str, Any]:
    left = _read(left_path)
    right = _read(right_path)
    if left.get("asset_id") != right.get("asset_id"):
        raise CandidateComparisonError("asset_id 不一致")
    asset_id = left["asset_id"]
    source_keys = ["kind", "source_sha256", "geometry_sha256", "geometry_basis"]
    source_equal = all(left["source"].get(key) == right["source"].get(key) for key in source_keys)
    policy_equal = left.get("policy") == right.get("policy")
    left_files = {item["path"]: item["sha256"] for item in left.get("files", [])}
    right_files = {item["path"]: item["sha256"] for item in right.get("files", [])}
    file_paths = sorted(set(left_files) | set(right_files))
    file_comparison = [
        {
            "path": path,
            "present_both": path in left_files and path in right_files,
            "exact_sha256_match": left_files.get(path) == right_files.get(path),
            "left_sha256": left_files.get(path),
            "right_sha256": right_files.get(path),
        }
        for path in file_paths
    ]

    left_l2 = left.get("levels", {}).get("l2", {})
    right_l2 = right.get("levels", {}).get("l2", {})
    if set(left_l2) != set(right_l2) or len(left_l2) != 1:
        raise CandidateComparisonError("L2 模式或键不一致")
    key = next(iter(left_l2))
    a = left_l2[key]
    b = right_l2[key]
    method_equal = a.get("method") == b.get("method")
    missed_a = a.get("missed_envelope", {}).get("maximum_missed_envelope_m")
    missed_b = b.get("missed_envelope", {}).get("maximum_missed_envelope_m")
    if not isinstance(missed_a, (int, float)) or not isinstance(missed_b, (int, float)):
        raise CandidateComparisonError("L2 缺少 maximum_missed_envelope_m")
    geometry_a = a.get("geometry", {})
    geometry_b = b.get("geometry", {})
    bounds_delta = _max_abs(
        geometry_a.get("bounds", {}).get("size_m"),
        geometry_b.get("bounds", {}).get("size_m"),
    )
    deviations = {
        "vertex_relative_difference": _relative_difference(
            geometry_a.get("vertices", 0), geometry_b.get("vertices", 0)
        ),
        "triangle_relative_difference": _relative_difference(
            geometry_a.get("triangles", 0), geometry_b.get("triangles", 0)
        ),
        "component_relative_difference": _relative_difference(
            geometry_a.get("component_count", 0), geometry_b.get("component_count", 0)
        ),
        "bounds_absolute_difference_m": bounds_delta,
        "missed_envelope_absolute_difference_m": abs(float(missed_a) - float(missed_b)),
    }
    if key == "compound_convex":
        equivalent = (
            method_equal
            and a.get("sha256") == b.get("sha256")
            and geometry_a == geometry_b
            and a.get("missed_envelope") == b.get("missed_envelope")
            and a.get("cavity_preservation") == b.get("cavity_preservation")
        )
        comparison_mode = "exact-l2-compound"
        limits = {name: 0.0 for name in deviations}
    elif key == "simplified_static_mesh":
        limits = SIMPLIFIED_LIMITS
        equivalent = method_equal and all(
            deviations[name] <= limit for name, limit in limits.items()
        )
        equivalent = equivalent and (
            a.get("cavity_preservation", {}).get("status")
            == b.get("cavity_preservation", {}).get("status")
        )
        comparison_mode = "bounded-qc-simplified-static-mesh"
    else:
        raise CandidateComparisonError(f"未知 L2 模式: {key}")
    passed = source_equal and policy_equal and equivalent
    return {
        "schema": SCHEMA,
        "passed": passed,
        "status": "cross-platform-qc-equivalent" if passed else "cross-platform-mismatch",
        "asset_id": asset_id,
        "reports": {
            "left_ref": str(left_path),
            "left_sha256": _sha256(left_path),
            "right_ref": str(right_path),
            "right_sha256": _sha256(right_path),
        },
        "source_binding_equal": source_equal,
        "policy_equal": policy_equal,
        "file_comparison": file_comparison,
        "l2_comparison": {
            "key": key,
            "mode": comparison_mode,
            "method_equal": method_equal,
            "exact_sha256_match": a.get("sha256") == b.get("sha256"),
            "qc_equivalent": equivalent,
            "deviations": deviations,
            "limits": limits,
        },
        "not_qualified_for": [
            "automatic-admission", "continuous-collision", "robot-execution",
            "hardware-safety-interlock", "deployment",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.left, args.right)
    except CandidateComparisonError as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False))
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
