#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v git-lfs >/dev/null 2>&1 || {
  echo "git-lfs is required" >&2
  exit 2
}
command -v uv >/dev/null 2>&1 || {
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 2
}

git submodule sync --recursive
git submodule update --init --recursive
git lfs pull
uv sync --frozen

echo "EIT reproducible environment is ready."
