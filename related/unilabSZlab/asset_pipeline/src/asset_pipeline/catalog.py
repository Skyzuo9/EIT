from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .config import Settings
from .models import utc_now
from .state import StateStore


def _safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", value).strip(" .-")


def _relative_or_absolute(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root.resolve()))
    except ValueError:
        return str(resolved)


def _file_record(path: Path, root: Path) -> dict:
    if not path.exists():
        return {"path": _relative_or_absolute(path, root), "exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": _relative_or_absolute(path, root),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def build_asset_catalog(settings: Settings, store: StateStore) -> dict:
    workspace_root = settings.approved_assets_dir.resolve().parent
    assets: list[dict] = []
    for device, status in store.list_devices():
        fallback = settings.approved_assets_dir / _safe_filename(
            device.manufacturer_model
        )
        glb_path = Path(
            store.get_metadata(f"published:{device.id}") or fallback.with_suffix(".glb")
        )
        stl_path = Path(
            store.get_metadata(f"published_stl:{device.id}")
            or fallback.with_suffix(".stl")
        )
        research = store.get_research(device.id)
        task = store.get_meshy_task(device.id)
        qc = store.get_qc(device.id)
        selected_images = research.selected_images() if research else []
        assets.append(
            {
                "device_id": device.id,
                "manufacturer_model": device.manufacturer_model,
                "route": device.route,
                "workflow_status": status.value,
                "files": {
                    "glb": _file_record(glb_path, workspace_root),
                    "stl": _file_record(stl_path, workspace_root),
                },
                "provenance": {
                    "official_links": device.official_links,
                    "repository_link": device.repository_link,
                    "dimension_source_url": (
                        research.dimensions.source_url if research else None
                    ),
                    "evidence_urls": research.evidence_urls if research else [],
                    "selected_reference_images": [
                        {
                            "source_url": image.source_url,
                            "page_url": image.page_url,
                            "sha256": image.sha256,
                            "view_label": image.view_label,
                        }
                        for image in selected_images
                    ],
                },
                "generation": (
                    {
                        "task_id": task.task_id,
                        "api_endpoint": task.api_endpoint,
                        "status": task.status,
                        "consumed_credits": task.consumed_credits,
                        "updated_at": task.updated_at,
                    }
                    if task
                    else None
                ),
                "qc": qc.model_dump(mode="json") if qc else None,
                "approvals": [
                    approval.model_dump(mode="json")
                    for approval in store.list_approvals(device.id)
                ],
                "redistribution_license": {
                    "status": "not_recorded",
                    "license": None,
                    "source": None,
                },
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "workspace_root": str(workspace_root),
        "asset_count": len(assets),
        "assets": assets,
    }


def write_asset_catalog(
    settings: Settings, store: StateStore, output_path: Path | None = None
) -> Path:
    destination = output_path or settings.approved_assets_dir / "asset-catalog.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_asset_catalog(settings, store), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
