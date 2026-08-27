#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
workspace_root=${script_dir:h}
python_bin=${EIT_PREVIEW_PYTHON:-${workspace_root}/.venv/bin/python}
node22_bin=/opt/homebrew/opt/node@22/bin

if [[ ! -x ${python_bin} ]]; then
  print -u2 "缺少可执行 Python: ${python_bin}"
  exit 2
fi
if [[ ! -x ${node22_bin}/node || ! -x ${node22_bin}/pnpm ]]; then
  print -u2 "缺少可用的 Homebrew Node 22 / pnpm: ${node22_bin}"
  exit 2
fi

export PATH="${node22_bin}:${PATH}"
export PYTHONPATH="${workspace_root}/cr5-telemetry-proof:${workspace_root}/Uni-Lab-OS${PYTHONPATH:+:${PYTHONPATH}}"
export UNILAB_BACKEND_PROXY_TARGET=http://127.0.0.1:8002
export EIT_ROBOT_CONTROL_ROOT=${EIT_ROBOT_CONTROL_ROOT:-${HOME}/Downloads/机械臂control}
export EIT_ROBOT_SOURCE_MANIFEST=${EIT_ROBOT_SOURCE_MANIFEST:-${workspace_root}/config/robot-source-releases.json}
export EIT_ROBOT_SOURCE_CACHE=${EIT_ROBOT_SOURCE_CACHE:-${workspace_root}/cr5-telemetry-proof/.unilabos/cache/robot-source-releases}

for archive in \
  "${EIT_ROBOT_CONTROL_ROOT}/DOBOT_CR_CRA/ros/DOBOT_6Axis_ROS2_V4-37730d08.zip" \
  "${EIT_ROBOT_CONTROL_ROOT}/FR5/ros/frcobot_ros2-v3.0.0_robot-v3.9.7.zip"; do
  if [[ ! -f ${archive} ]]; then
    print -u2 "缺少只读机器人 SourceRelease: ${archive}"
    exit 2
  fi
done

backend_log=$(mktemp -t eit-cr5-preview-backend)
frontend_log=$(mktemp -t eit-cr5-preview-frontend)
backend_pid=''
frontend_pid=''

cleanup() {
  [[ -n ${frontend_pid} ]] && kill ${frontend_pid} 2>/dev/null || true
  [[ -n ${backend_pid} ]] && kill ${backend_pid} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd ${workspace_root}
${python_bin} -m cr5_telemetry_lab.preview_app --port 8002 >${backend_log} 2>&1 &
backend_pid=$!

for _ in {1..80}; do
  if curl -fsS http://127.0.0.1:8002/api/v1/kinematic-preview/catalog >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 ${backend_pid} 2>/dev/null; then
    print -u2 "CR5 / FR5 SourceRelease 预览后端启动失败："
    tail -80 ${backend_log} >&2
    exit 1
  fi
  sleep 0.1
done

cd ${workspace_root}/uni-lab-fe
pnpm --filter @unilab/kernel-web dev >${frontend_log} 2>&1 &
frontend_pid=$!

for _ in {1..160}; do
  if curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 ${frontend_pid} 2>/dev/null; then
    print -u2 "Workbench 前端启动失败："
    tail -120 ${frontend_log} >&2
    exit 1
  fi
  sleep 0.1
done

workbench_url='http://127.0.0.1:5173/?backend=local-python&backendUrl=http%3A%2F%2F127.0.0.1%3A8002&section=scene'
diagnostic_url='http://127.0.0.1:5173/?asset-pipeline-kinematic-preview=1'
open_url=${workbench_url}
should_open=true
for argument in "$@"; do
  [[ ${argument} == '--diagnostic' ]] && open_url=${diagnostic_url}
  [[ ${argument} == '--no-open' ]] && should_open=false
done

print "UniLab Workbench CR5 / FR5 主场景已启动：${workbench_url}"
print "诊断夹具：${diagnostic_url}"
print "后端日志：${backend_log}"
print "前端日志：${frontend_log}"
print "按 Ctrl-C 停止。"

if [[ ${should_open} == true ]]; then
  open ${open_url}
fi

wait ${frontend_pid}
