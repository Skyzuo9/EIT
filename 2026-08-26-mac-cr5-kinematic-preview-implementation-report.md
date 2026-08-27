# Mac CR5 / FR5 SourceRelease 运动预览与工站导入门禁：实施记录

日期：2026-08-26
状态：CR5/FR5 已在正常 Workbench 主场景同屏显示、拾取并预览运动；真实工站输入仍待完成

## 1. 本轮完成

### 1.1 CR5 / FR5 `kinematic-preview`

已实现本地证明链：

```text
只读厂家 ROS 2 ZIP（Dobot CR5 / FAIRINO FR5）
  → 整包 SHA-256 + ZIP 内 URDF SHA-256 校验
  → SourceRelease Provider
  → OS package_moveit 校验与冻结渲染目录
  → 受限预览指令
  → JointStateProjector
  → DeviceTelemetryHub / SSE
  → uni-lab-fe scene-runtime
  → 现有 Pascal LabDeviceRenderer
```

正常 UniLab Workbench 主入口通过本地 Python Backend 加载 Material Graph：

```text
http://127.0.0.1:5173/?backend=local-python&backendUrl=http%3A%2F%2F127.0.0.1%3A8002&section=scene
```

主场景经 `/api/v1/materials/graph` 同时加载摘要锁定的 CR5/FR5 URDF（每种 7
个 STL），通过正式 device-telemetry SSE 应用关节帧，并支持 Material 级拾取。
`?asset-pipeline-kinematic-preview=1` 只保留为查看源凭据和手动触发预览的辅助
诊断夹具，不再充当 Workbench 主场景验收入口。原始 ZIP 未复制进仓库也未修改；
运行时只把选中 URDF 引用的 mesh 物化到被 Git 忽略的缓存。页面与后端都显式
禁止硬件执行和强制空间互锁。

### 1.2 Windows 工站结果进门门禁

新增 `lab.station_source_handoff/v0` 模板和校验器，检查：

- SolidWorks capture 必须 `passed` 且 `source_read_only=true`；
- `assembly.snapshot.json` 的单位、occurrence 唯一性、世界位姿和根节点；
- Pack and Go 文件哈希与路径不得漂移或越界；
- GLB 文件头与非空内容；
- 机械臂真源必须是 `authority=manufacturer`，Provider 摘要、关节和 mesh 完整。

### 1.3 工站 occurrence 分解

新增 `station-decomposition.yaml` 模板与编译器。编译器只允许按 SolidWorks
occurrence 前缀匹配，要求：

- 每个 occurrence 恰好属于一个设备规则或机械臂替换子树；
- 未分配、重复归属、锚点歧义和 handoff 摘要漂移全部失败关闭；
- 机械臂总装 CAD 只标记 `comparison_only`，运动学指向 `robot-family:*`；
- 输出是 `station-layout-candidate`，不是 DeployManifest 或 WorkCellActivation；
- 分解文件继续禁止 `device_id`、`base_pose`、TCP、payload、点表和当前关节值。

## 2. 已验证证据

| 检查 | 结果 |
|---|---|
| Python 工站 handoff/decomposition | 4 tests passed |
| Python CR5/FR5 SourceRelease preview | 6 tests passed |
| `scene-runtime` | 6 tests passed |
| 前端 realtime SSE | 5 tests passed |
| Pascal 关节应用与场景投影 | 24 tests passed |
| kinematic-preview descriptor/catalog | 6 tests passed |
| kernel-web TypeScript | passed |
| kernel-web production build + bundle gate | passed |
| HTTP 模型接口 | CR5/FR5 URDF 均为 200；拓扑响应头匹配 |
| 两种模型内容 | 各 6 个可动关节、7 个 mesh；mesh 全部非空 |
| SourceRelease 不可变性 | 两个 ZIP 编译前后 SHA-256、size、mtime 完全一致 |
| Workbench 主界面浏览器显示 | “Uni-Lab 调试台”/“三维实验室场景”显示 2 个 Material；无占位体回退 |
| Workbench 主界面拾取 | CR5、FR5 按钮 `aria-pressed` 分别为真且互斥 |
| 预览遥测 | 两种模型均观察到连续 SSE 帧；完整限定关节名一致 |
| 预览终态 | CR5/FR5 均 `succeeded`；`not_a_workflow_task=true` |

浏览器实测在正常 `App → AppShell → SceneWorkbench → PascalLabWorkbench` 路径
完成；辅助诊断页不计入主界面通过证据。控制台无应用错误；仅观察到 Three.js
既有 `THREE.Clock` deprecation warning。

## 3. 运行方法

```bash
./scripts/run_mac_kinematic_preview.sh
```

真实工站回传后：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/<station>/station-handoff.json

./.venv/bin/python scripts/compile_station_decomposition.py \
  incoming/<station>/station-handoff.json \
  incoming/<station>/station-decomposition.yaml \
  --output incoming/<station>/station-layout.json
```

## 4. 当前证据边界

| 能力 | 当前状态 |
|---|---|
| CR5/FR5 ZIP → Provider → 模型 API | 软件与浏览器实测通过 |
| 遥测 SSE → 前端关节合同 | 软件实测通过 |
| Workbench 生产构建 | 通过 |
| Workbench 主界面实际可见、拾取、运动 | 浏览器与 SSE 联合实测通过 |
| 正式 UniLab WorkflowTask 驱动 | 未完成；当前是受限 preview endpoint |
| ROS `/joint_states` 路径 | 未验证；本机无 ROS2 |
| 真实工站分解 | 待 Windows 真实工站 handoff |
| occurrence 子树几何拆包 | 未完成 |
| DeployManifest / activation | 未完成 |
| 碰撞、互锁、真机执行 | 未授权、未完成 |

本轮没有修改或覆盖生产 `machine.glb`、现场点表、标定、TCP 或控制器配置。
