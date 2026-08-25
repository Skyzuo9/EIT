#!/usr/bin/env bash
set -euo pipefail

workspace="${1:-/home/tyzuo/ptlc_isaac_reproduction_20260813}"
output="${2:-${workspace}/isaac_output/area7_multipt_video_20260814}"
isaac_python=/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1/bin/python

if [[ "${OMNI_KIT_ACCEPT_EULA:-}" != "YES" ]]; then
  echo "Refusing to queue: OMNI_KIT_ACCEPT_EULA=YES is required." >&2
  exit 2
fi
if [[ -d "${output}/frames" ]] && find "${output}/frames" -type f -print -quit | grep -q .; then
  echo "Refusing to overwrite existing frames: ${output}/frames" >&2
  exit 3
fi

while :; do
  gpu_processes="$(nvidia-smi -i 1 --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits 2>/dev/null || true)"
  if [[ -z "${gpu_processes//[[:space:]]/}" ]]; then
    break
  fi
  printf '%s waiting for physical GPU 1; current processes: %s\n' "$(date -Is)" "${gpu_processes//$'\n'/; }"
  sleep 20
done

echo "$(date -Is) physical GPU 1 is idle; starting the area-7 render"
export CUDA_VISIBLE_DEVICES=1
exec "${isaac_python}" \
  "${workspace}/pTLC仿真资产/isaac_sim/run_unilab_isaac_validation.py" \
  --scene "${workspace}/isaac_output/ptlc_client_scene.usda" \
  --point-set "${workspace}/pTLC仿真资产/isaac_sim/config/cr5_ptlc_area7_points.v1.json" \
  --template-root "${workspace}/unilab_robot_template" \
  --template-revision e8964842c4da3d123323cc46cfa565678c909849 \
  --output "${output}" \
  --fps 12 \
  --hold-seconds 0.25 \
  --move-seconds 1.5 \
  --width 960 \
  --height 540 \
  --rt-subframes 1 \
  --settle-updates 4 \
  --targets \
    ptlc.P45 ptlc.P46 ptlc.P47 ptlc.P48 \
    ptlc.P80 ptlc.P79 ptlc.P78 ptlc.P45 \
    ptlc.P49 ptlc.P50 ptlc.P51 ptlc.P83 \
    ptlc.P82 ptlc.P81 ptlc.P45
