"""Strict verification for the portable end-to-end trial output."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_FAMILIES = {
    "instrument.square-tactile",
    "instrument.bigclaw.step-reference",
    "synthesis.250ml-reagent-tray",
    "synthesis.ptb22-linear-guide",
    "synthesis.capping-gripper",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(bundle_path: Path) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    bundle = read_json(bundle_path)
    family = bundle.get("family")
    if bundle.get("schema") != "lab.family_sim_bundle/v0":
        errors.append(f"{bundle_path}: unexpected bundle schema")
    if not bundle.get("immutable_candidate"):
        errors.append(f"{bundle_path}: immutable_candidate is not true")
    artifact_names = {item.get("path") for item in bundle.get("artifacts", [])}
    if "render-lod0.glb" not in artifact_names or "capability.json" not in artifact_names:
        errors.append(f"{bundle_path}: required artifacts are missing")
    for artifact in bundle.get("artifacts", []):
        relative = artifact.get("path")
        if not isinstance(relative, str):
            errors.append(f"{bundle_path}: artifact path is invalid")
            continue
        path = bundle_path.parent / relative
        if not path.is_file():
            errors.append(f"{bundle_path}: missing artifact {relative}")
            continue
        if path.stat().st_size != artifact.get("bytes"):
            errors.append(f"{bundle_path}: byte count mismatch for {relative}")
        if sha256_file(path) != artifact.get("sha256"):
            errors.append(f"{bundle_path}: SHA-256 mismatch for {relative}")
    capability_path = bundle_path.parent / "capability.json"
    if capability_path.is_file():
        capability = read_json(capability_path)
        if "workbench_display" not in capability.get("allows", []):
            errors.append(f"{bundle_path}: workbench_display is not allowed")
        for forbidden in ("motion", "spatial_interlock_enforced", "execution"):
            if forbidden not in capability.get("forbids", []):
                errors.append(f"{bundle_path}: {forbidden} is not explicitly forbidden")
    return family if isinstance(family, str) else None, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    errors: list[str] = []

    for required in ("run-summary.json", "gate-report.json", "REPORT.md", "environment.json"):
        if not (output / required).is_file():
            errors.append(f"missing top-level output: {required}")
    if errors:
        print(json.dumps({"passed": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    gate = read_json(output / "gate-report.json")
    summary = read_json(output / "run-summary.json")
    if not gate.get("passed"):
        errors.append(f"family gate failed: {gate.get('failures', [])}")

    bundle_paths = sorted((output / "families").rglob("bundle.json"))
    families: set[str] = set()
    for bundle_path in bundle_paths:
        family, bundle_errors = verify_bundle(bundle_path)
        if family:
            families.add(family)
        errors.extend(bundle_errors)

    missing_families = EXPECTED_FAMILIES - families
    if missing_families and not args.allow_partial:
        errors.append(f"missing expected families: {sorted(missing_families)}")
    solidworks_status = summary.get("solidworks_capture", {}).get("status")
    if solidworks_status != "passed" and not args.allow_partial:
        errors.append(f"SolidWorks capture is {solidworks_status!r}, expected 'passed'")
    expected_preview_count = len(families)
    if summary.get("preview_assets") != expected_preview_count:
        errors.append(
            f"preview count {summary.get('preview_assets')} does not match bundle count {expected_preview_count}"
        )
    preview_pngs = list((output / "previews").glob("*.png"))
    if len(preview_pngs) != expected_preview_count:
        errors.append(f"preview PNG count {len(preview_pngs)} does not match {expected_preview_count}")

    report = {
        "schema": "lab.asset_pipeline_handoff_verification/v0",
        "passed": not errors,
        "mode": "partial-allowed" if args.allow_partial else "strict-full-flow",
        "output": str(output),
        "families": sorted(families),
        "bundle_count": len(bundle_paths),
        "preview_png_count": len(preview_pngs),
        "family_gate_passed": bool(gate.get("passed")),
        "solidworks_capture_status": solidworks_status,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
