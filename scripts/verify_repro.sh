#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

git diff --check
git lfs fsck
uv run --frozen python scripts/verify_repro_manifest.py
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen python scripts/compile_collision_geometry_manifest.py --check
uv run --frozen python scripts/compile_spatial_shadow.py --check
uv run --frozen python scripts/export_spatial_workbench_snapshot.py --check

echo "EIT reproducibility checks passed (software/shadow evidence only)."
