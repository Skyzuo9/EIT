#!/usr/bin/env bash
set -euo pipefail

workspace="${1:-/home/tyzuo/ptlc_isaac_reproduction_20260813}"
stage="${2:-${workspace}/isaac_output/ptlc_client_scene.usda}"
gpu_index=1
signal_port=49100
stream_port=47998
public_ip=222.29.40.109
isaac_root=/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1
isaac_bin="${isaac_root}/bin/isaacsim"

if [[ "${OMNI_KIT_ACCEPT_EULA:-}" != "YES" ]]; then
  echo "Refusing to start: export OMNI_KIT_ACCEPT_EULA=YES after explicit acceptance." >&2
  exit 2
fi
if [[ ! -f "${stage}" ]]; then
  echo "Refusing to start: missing client scene ${stage}" >&2
  exit 2
fi

gpu_processes="$(nvidia-smi -i "${gpu_index}" --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits 2>/dev/null || true)"
if [[ -n "${gpu_processes//[[:space:]]/}" ]]; then
  echo "Refusing to start: authorized GPU ${gpu_index} is already occupied:" >&2
  echo "${gpu_processes}" >&2
  exit 3
fi
if ss -lntu 2>/dev/null | grep -Eq ":(${signal_port}|${stream_port})[[:space:]]"; then
  echo "Refusing to start: port ${signal_port} or ${stream_port} is already bound." >&2
  exit 4
fi

export CUDA_VISIBLE_DEVICES=1
exec "${isaac_bin}" isaacsim.exp.full.streaming "${stage}" \
  --no-window \
  --/renderer/activeGpu=1 \
  --/physics/cudaDevice=0 \
  --/renderer/multiGpu/autoEnable=false \
  --/renderer/multiGpu/enabled=false \
  --/renderer/multiGpu/maxGpuCount=1 \
  --/app/renderer/resolution/width=1280 \
  --/app/renderer/resolution/height=720 \
  --/app/window/width=1280 \
  --/app/window/height=720 \
  --/exts/omni.kit.livestream.app/primaryStream/targetFps=30 \
  --/exts/omni.kit.livestream.app/primaryStream/allowDynamicResize=false \
  --/exts/omni.services.livestream.session/quitOnSessionEnded=false \
  --/exts/omni.services.livestream.session/resumeTimeout=300 \
  --/isaac/startup/ros_bridge_extension="" \
  --/exts/omni.kit.livestream.app/primaryStream/publicIp="${public_ip}" \
  --/exts/omni.kit.livestream.app/primaryStream/signalPort="${signal_port}" \
  --/exts/omni.kit.livestream.app/primaryStream/streamPort="${stream_port}"
