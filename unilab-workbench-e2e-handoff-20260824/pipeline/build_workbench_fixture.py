"""Build an isolated, static Workbench fixture from gated family bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")


def verify_source_bundle(bundle_path: Path) -> dict[str, Any]:
    bundle = read_json(bundle_path)
    if bundle.get("schema") != "lab.family_sim_bundle/v0":
        raise ValueError(f"unexpected bundle schema: {bundle_path}")
    artifacts = bundle.get("artifacts", [])
    for artifact in artifacts:
        path = bundle_path.parent / artifact["path"]
        if not path.is_file():
            raise FileNotFoundError(f"missing bundle artifact: {path}")
        if path.stat().st_size != artifact["bytes"] or sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"bundle artifact failed hash verification: {path}")
    capability = read_json(bundle_path.parent / "capability.json")
    if "workbench_display" not in capability.get("allows", []):
        raise ValueError(f"bundle is not display-qualified: {bundle_path}")
    return {"bundle": bundle, "capability": capability}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-output", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fixture-id", default="asset-pipeline-e2e-20260824")
    args = parser.parse_args()

    trial_output = Path(args.trial_output).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty fixture directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    gate_path = trial_output / "gate-report.json"
    gate = read_json(gate_path)
    if not gate.get("passed"):
        raise RuntimeError("refusing to stage family bundles whose release gate did not pass")

    catalog_assets: list[dict[str, Any]] = []
    bundle_paths = sorted((trial_output / "families").rglob("bundle.json"))
    for index, bundle_path in enumerate(bundle_paths):
        verified = verify_source_bundle(bundle_path)
        bundle = verified["bundle"]
        capability = verified["capability"]
        family = str(bundle["family"])
        revision = str(bundle["trial_revision"]).split(":", 1)[-1][:12]
        asset_id = safe_slug(family)
        relative_dir = Path("bundles") / asset_id / revision
        destination = output / relative_dir
        if destination.exists():
            raise RuntimeError(f"duplicate fixture destination: {destination}")
        shutil.copytree(bundle_path.parent, destination)
        render_path = destination / "render-lod0.glb"
        if not render_path.is_file() or render_path.stat().st_size == 0:
            raise RuntimeError(f"copied fixture has no renderable GLB: {destination}")
        x = float((index % 3) * 2.0)
        y = float((index // 3) * 2.0)
        catalog_assets.append(
            {
                "id": asset_id,
                "family": family,
                "trialRevision": bundle["trial_revision"],
                "capabilityGrade": capability.get("grade"),
                "bundleUrl": (relative_dir / "bundle.json").as_posix(),
                "renderUrl": (relative_dir / "render-lod0.glb").as_posix(),
                "previewTransform": {
                    "translationM": [x, y, 0.0],
                    "rotationQuatXyzw": [0.0, 0.0, 0.0, 1.0],
                    "scale": 1.0,
                    "fixtureOnly": True,
                },
                "expected": {
                    "display": True,
                    "stablePicking": "stable_picking" in capability.get("allows", []),
                    "motion": False,
                    "spatialInterlockEnforced": False,
                    "execution": False,
                },
            }
        )

    catalog = {
        "schema": "lab.workbench_static_scene_fixture/v0",
        "fixtureId": args.fixture_id,
        "purpose": "static_workbench_display_and_picking_only",
        "candidate": True,
        "notAWorkCellActivation": True,
        "sourceFamilyGateSha256": sha256_file(gate_path),
        "assetCount": len(catalog_assets),
        "safety": {
            "motionAllowed": False,
            "spatialInterlockAllowed": False,
            "executionAllowed": False,
            "reason": "No manufacturer robot URDF, qualified collision, deployment binding, or activation is present.",
        },
        "assets": catalog_assets,
    }
    write_json(output / "scene-catalog.json", catalog)

    marker = {
        "schema": "lab.workbench_fixture_marker/v0",
        "fixtureId": args.fixture_id,
        "safeToRemoveAsOneTestFolder": True,
    }
    write_json(output / ".asset-pipeline-e2e-marker.json", marker)

    checksum_lines = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "CHECKSUMS.sha256":
            continue
        checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(json.dumps(catalog, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
