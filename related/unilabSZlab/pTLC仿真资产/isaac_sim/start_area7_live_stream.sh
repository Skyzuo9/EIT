#!/usr/bin/env bash
set -euo pipefail

workspace="${1:-/home/tyzuo/ptlc_isaac_reproduction_20260813}"
stage="${workspace}/isaac_output/ptlc_client_scene.usda"
point_set="${workspace}/pTLC仿真资产/isaac_sim/config/cr5_ptlc_area7_points.v1.json"
validation_report="${workspace}/isaac_output/area7_multipt_video_20260814/unilab_isaac_validation.json"
status_file="${workspace}/isaac_output/area7_live_stream_status.json"
script="${workspace}/pTLC仿真资产/isaac_sim/stream_area7_motion.py"
gpu_index=1
signal_port=49100
stream_port=47998
isaac_root=/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1
isaac_python="${isaac_root}/bin/python"
experience="${isaac_root}/lib/python3.12/site-packages/isaacsim/apps/isaacsim.exp.full.streaming.kit"

if [[ "${OMNI_KIT_ACCEPT_EULA:-}" != "YES" ]]; then
  echo "Refusing to start: export OMNI_KIT_ACCEPT_EULA=YES after explicit acceptance." >&2
  exit 2
fi
for required in "${stage}" "${point_set}" "${validation_report}" "${script}" "${experience}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Refusing to start: missing ${required}" >&2
    exit 2
  fi
done

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
exec "${isaac_python}" "${script}" \
  --scene "${stage}" \
  --point-set "${point_set}" \
  --validation-report "${validation_report}" \
  --experience "${experience}" \
  --status-file "${status_file}" \
  --move-seconds 1.5 \
  --hold-seconds 0.25 \
  --width 1280 \
  --height 720 \
  --target-fps 30 \
  --public-ip 222.29.40.109 \
  --signal-port "${signal_port}" \
  --stream-port "${stream_port}"
