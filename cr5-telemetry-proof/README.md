# CR5 / GCR5 / FR5 Mac 本地 SourceRelease 运动预览证明

本目录把本机 `机械臂control` 中的两个厂家 ROS 2 ZIP 和一个项目 CAD 导出 ZIP
作为只读、摘要锁定的
`SourceRelease` 输入，编译为 Uni-Lab-OS `package_moveit` Provider，再由现有
Workbench/Pascal renderer 显示、拾取并应用完整关节帧。

```text
只读 SourceRelease ZIP + SHA-256 清单
  → Robot SourceRelease Adapter
  → execution/render URDF + SRDF + 7 个受管 mesh
  → OS package_moveit 摘要/拓扑校验
  → JointStateProjector → DeviceTelemetryHub / SSE
  → scene-runtime → LabDeviceRenderer
```

当前接入：

- Dobot CR5：`DOBOT_6Axis_ROS2_V4-37730d08.zip`
- DUCO GCR5-910：固定 GitHub commit `94d4030...` 的项目 CAD URDF
- FAIRINO FR5：`frcobot_ros2-v3.0.0_robot-v3.9.7.zip`

源清单位于 [`../config/robot-source-releases.json`](../config/robot-source-releases.json)。
Provider 打开 ZIP 时只读，锁定整包 SHA-256 和 ZIP 内 URDF SHA-256；只把 URDF
引用的 mesh 原子化物化到 `.unilabos/cache/`，该缓存不进入 Git。

GCR5 ZIP 可由锁定清单自动下载并校验；Provider 本身不隐式联网：

```bash
./.venv/bin/python scripts/fetch_robot_source_release.py duco_gcr5_910
```

## 运行

```bash
./scripts/run_mac_kinematic_preview.sh
```

然后打开：

```text
http://127.0.0.1:5173/?backend=local-python&backendUrl=http%3A%2F%2F127.0.0.1%3A8002&section=scene
```

这是正常的 UniLab Workbench 主界面（“三维实验室场景”），其中同时显示
CR5/GCR5/FR5 三个 Material，可分别拾取，并通过正式 joint-state SSE 消费四步
“检查位往返”预览。启动脚本默认打开该入口。

辅助诊断夹具仍保留在：

```text
http://127.0.0.1:5173/?asset-pipeline-kinematic-preview=1
```

它用于查看 SourceRelease 凭据与手动触发预览，不作为 Workbench 主场景验收证据。
需要直接打开它时可运行 `./scripts/run_mac_kinematic_preview.sh --diagnostic`。
如果源 ZIP、URDF、mesh、限定关节名或拓扑摘要漂移，启动失败关闭。

如源目录不在默认的 `~/Downloads/机械臂control`：

```bash
EIT_ROBOT_CONTROL_ROOT=/absolute/path/to/机械臂control \
  ./scripts/run_mac_kinematic_preview.sh
```

## 证据边界

- 这是 `kinematic-preview`，不是 `execution-qualified`。
- 预览端点不是正式 UniLab `WorkflowTask`；状态显式标记
  `not_a_workflow_task: true`。
- 当前 Mac 无 ROS2，预览从 `JointStateProjector` 入口注入完整关节状态；尚未证明
  ROS `/joint_states` 传输。
- CR5 厂家 URDF 的 effort/velocity 为零占位值；Adapter 只为 mock 预览写入清单中
  明示的正默认值，不把这些值用于真机控制。
- GCR5 URDF 的六轴被导出为无 limit 的 continuous joint；Adapter 注入的 ±π、
  effort=1、velocity=0.5 仅约束本地预览。其 authority 是
  `project-cad-export`，不是厂家限位或真机控制证据。
- visual/collision mesh 存在不等于碰撞资格已经合格。
- 不启动 MoveIt，不连接控制器，不使用现场点位、TCP、payload 或标定。

## 测试

```bash
PYTHONPATH="cr5-telemetry-proof:Uni-Lab-OS" \
  ./.venv/bin/python -m unittest discover -s cr5-telemetry-proof/tests -v

PATH=/opt/homebrew/opt/node@22/bin:$PATH \
  pnpm --dir uni-lab-fe --filter @unilab/kernel-web \
  exec vitest run \
  src/integrations/asset-pipeline-kinematic-preview/descriptor.test.ts

PATH=/opt/homebrew/opt/node@22/bin:$PATH \
  pnpm --dir uni-lab-fe --filter @unilab/kernel-web typecheck
```
