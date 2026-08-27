# 投料站资产管线全流程开发与测试设计

日期：2026-08-26
状态：实施设计草案（可执行，尚未完成真实工站闭环）
适用输入：`/Users/newtides/EIT/投料站`、`/Users/newtides/EIT/投料站-urdf`
上位规范：[`2026-08-23-lab-device-family-asset-pipeline.md`](./2026-08-23-lab-device-family-asset-pipeline.md)
现有实施计划：[`2026-08-25-unilab-station-asset-pipeline-design-and-plan.md`](./2026-08-25-unilab-station-asset-pipeline-design-and-plan.md)
Windows 生成机说明：[`2026-08-23-lab-asset-pipeline-windows-agent-brief.md`](./2026-08-23-lab-asset-pipeline-windows-agent-brief.md)
P0–P1 当前执行入口：[`2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](./2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)

本文是针对“投料站”真实输入的全流程开发与测试设计。它不替代上位分层规范；若发生冲突，以上位规范为准。本文把当前已经验证的 CR5/FR5 Workbench 预览、现有 handoff/decomposition 门禁、legacy SolidWorks URDF 迁移试验，以及尚未完成的部署、activation 和正式工作流运动串成一条可逐阶段验收的路线。

---

## 1. 目标、非目标与最终完成定义

### 1.1 总目标

把投料站的 SolidWorks 总装、legacy SolidWorks URDF/STL、厂家机械臂模型和部署事实编译成摘要锁定、分层清晰、可复现的 UniLab 资产，并实现：

1. 工站按设备实例在本地 UniLab Workbench 中正确显示、拾取和分层。
2. 导轨、机械臂和已批准的仪器机构可以由正式工作流指令驱动三维运动。
3. 同型号的多个设备实例具有独立 `device_id`、位姿、关节命名和遥测，不串扰。
4. 家族资产、部署事实和运行时观测不混写；更换一个实例只修改部署层。
5. 摘要、拓扑、单位、路径、输入完整性或遥测新鲜度不满足时失败关闭。

### 1.2 本阶段不承诺

以下内容必须单独取得证据，不能由“模型能显示/能运动”推导出来：

- 强制空间互锁；
- 真实控制器执行许可；
- 真实 TCP、payload、基座标定和导轨零偏；
- 控制器 PointSet/ProgramSet 的正确性；
- 现场安全、急停和产线放行。

### 1.3 最终完成定义

只有同时满足以下条件，才能称为“投料站资产管线全流程软件闭环完成”：

| 编号 | 完成条件 | 必需证据 |
|---|---|---|
| G1 | Windows 对真实总装完成只读 SourceRelease | 前后源哈希一致、capture report、完整 occurrence snapshot、可读 GLB |
| G2 | 每个 occurrence 被唯一分配或明确忽略/替换 | 已批准 decomposition、`unassigned=0`、无重复归属 |
| G3 | 选定家族包可重复编译 | bundle 清单、文件摘要、能力等级、两次构建比较 |
| G4 | 厂家机械臂 Provider 和导轨 Provider 独立装配 | Provider 检查器、唯一 link/joint、父子图验证 |
| G5 | DeployManifest 可生成物理图和注册表投影 | 两个同型号实例测试、位姿改变只影响部署层 |
| G6 | activation 可冻结并由 Workbench 加载 | activation 摘要、模型 API 200、正常主场景显示与拾取 |
| G7 | 正式 WorkflowTask 可驱动模拟关节状态 | Task/Job 权威状态、完整 SSE 帧、终态、stale 行为 |
| G8 | 所有负向门禁失败关闭 | 摘要漂移、单位缺失、路径越界、缺 mesh、拓扑漂移、断流测试 |

“真实硬件闭环完成”需要在 G1–G8 之外再增加现场标定、点位/程序、控制器、硬限位、碰撞包络和机器人实测证据。

---

## 2. 当前输入证据与使用边界

### 2.1 SolidWorks 主源：`投料站`

当前顶层共有 447 个 CAD 文件：

- 281 个 `.SLDPRT`；
- 165 个 `.SLDASM`；
- 1 个 `.x_t`；
- 顶层总装候选：`投料站方案模拟1.1.SLDASM`；
- 中立几何审计候选：`投料站方案模拟1.1.x_t`。

用途：

- 作为仪器、料架、环境和耗材的主要 SourceRelease；
- 从真实 SolidWorks occurrence 提取父子关系和静止世界变换；
- 生成整站和设备级视觉几何；
- 提供 mate、质量和坐标系的候选证据。

限制：

- Mac 不能直接提取可靠的 SolidWorks occurrence/mate；
- `.x_t` 只作为 B-rep/几何回退，不替代稳定 occurrence 身份；
- 总装中的机械臂 CAD 只能作对照，不能作为机械臂运动学真源；
- 旧 exporter 日志出现过保存源装配的行为，不能复用为“只读采集”证据。

### 2.2 Legacy 导出：`投料站-urdf`

当前包含：

- 19 个可解析 URDF；
- 14 个单 link 静态包；
- 5 个活动机构包，共 9 个 prismatic 关节；
- 28 个包内 STL，约 55.8 万三角面；
- 10 个独立 STL；
- 全部 URDF mesh 引用存在。

必须保留的边界：

- SolidWorks exporter 关节全部只进入 `mechanics.candidates[]`，默认 `unproven`；
- 9 个活动关节的 `effort/velocity=0`，不能直接成为正式控制限位；
- visual 与 collision 使用同一 STL，只能标 `collision-candidate`；
- 19 个 ROS 包名都不是稳定的 ASCII 产品包名，发布时必须重命名并保留别名映射；
- 包内 STL 的尺寸表现为米，10 个独立 STL 的尺寸表现为毫米；单位必须由清单显式声明，包围盒只用于发现异常，不能自动猜测并静默修正；
- `投料站/投料站-urdf` 与根目录 `投料站-urdf` 的实际文件内容重复。扫描器必须只选择一个根或按摘要去重。

### 2.3 厂家机械臂真源

首选现有摘要锁定的 Dobot CR5 Provider：

```text
provider: unilab_arm_cr5:build_moveit_model
source_digest: 8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2
```

FAIRINO FR5 可作为第二模型和异构回归样本，但不与 CR5 混成一个家族包。

机械臂总装 CAD 子树必须在 decomposition 中标记：

```yaml
kind: robot_replacement
solidworks_geometry_role: comparison_only
kinematics_source: robot-family:dobot.cr5
```

### 2.4 当前已验证的软件基础

截至本文生成时：

- 工站 handoff/decomposition 测试：4 项通过；
- CR5/FR5 SourceRelease 预览测试：6 项通过；
- legacy 试验管线单测：4 项通过，1 项因未生成真实 trial output 跳过；
- CR5/FR5 已有浏览器实测记录，但本次文档生成未重新执行浏览器 E2E；
- 真实 `投料站` 尚无 `station-handoff.json`、`assembly.snapshot.json`、设备级 GLB 或批准后的 decomposition；
- DeployManifest、activation、正式 WorkflowTask 运动仍未实现。

所有 Python 命令统一使用仓库 `./.venv/bin/python`。系统 `python3` 不保证能导入领域 Provider。

---

## 3. 选定的纵向测试资产

第一条完整纵切不一次覆盖整站，而是选择能覆盖四类关键合同的最小资产集合。

| 角色 | 测试资产 | 当前事实 | 第一阶段目标 |
|---|---|---|---|
| 静态环境/料架 | `投料站料架.urdf` | 1 link、0 joint，约 0.510 × 0.140 × 0.450 m | `semantic-scene`、显示、拾取、稳定 digest |
| 独立活动轴 | `滑轨ETH17-L5-1250-BL-M40-A1(0).urdf` | 2 links、1 个 0–1.28 m prismatic 候选轴，约 1.533 m 长 | 静态外壳 + 人签后的 `unilab_rail_linear` 运动学 |
| 机械臂 | 官方 Dobot CR5 Provider | 6 个可动关节、7 个受管 mesh，摘要已锁定 | `package_moveit`、挂在导轨 `mount_link` 下、模拟运动 |
| 耗材/物料 | `4ml玻璃瓶(Default_按加工_).STL` | 原始包围盒约 15 × 46 × 15，单位为 mm | 显式 `scale=0.001`、作为物料/耗材，不产生关节 |

第二阶段扩展资产：

| 角色 | 测试资产 | 要验证的新问题 |
|---|---|---|
| 双侧机构 | `开盖瓶子夹持机构.urdf` | 两个 prismatic 候选轴是否独立、同步或 mimic，必须人签 |
| 高复杂度末端 | `末端工具2号.urdf` | 20 万级三角面单资产的 LOD、拾取与碰撞简化预算 |
| 重复实例 | 两个同型号机器人/料架 occurrence | `device_id` 限定关节、相同 family 不串扰 |
| 全站 | `投料站方案模拟1.1.SLDASM` | occurrence 全覆盖、设备级位姿、加载与内存预算 |

测试顺序必须是“最小纵切通过 → 重复实例 → 复杂机构 → 全站”，不得从整站截图直接跳到执行资格。

---

## 4. 核心架构与不可变规则

### 4.1 五层产物

```text
SourceRelease
  原始文件、files.sha256、source.json、capture-report、assembly.snapshot
        │
        ▼
Canonical IR
  entity-registry / frame-graph / mechanics / geometry-roles / provenance
        │
        ▼
FamilySimBundle / Domain Provider
  家族级、不含 device_id/base_pose/TCP/点表/当前关节
        │
        ▼
DeployManifest
  每个 device_id 的安装、父子挂载、工具/标定/点表引用
        │
        ▼
WorkCellActivation
  本次启动冻结的家族摘要 + 部署摘要 + 图投影
        │
        ▼
Workbench / Workflow / Telemetry
```

### 4.2 机械臂与导轨装配规则

导轨和机械臂始终是两个设备：

| 角色 | 模型合同 | 运行后端 | 关键链接 |
|---|---|---|---|
| 导轨 | `package_static` + `joint_state_provider` | `mock` / `simulation` / 领域 PLC；禁止 `moveit` | `{rail_id}_rail_carriage` 是 `mount_link` |
| 机械臂 | `package_moveit` | `moveit` / `moveit_sim` 或领域控制后端 | `parent = rail_id` |

禁止：

- 把导轨做成机械臂第七轴；
- 在 MoveIt/SRDF/ros2_control 中添加 `arm_base_joint`；
- 让静态外壳根与运动学 `{device_id}_rail_base` 同名；
- 同时在物理图和 `mount_yaw_deg` 中写非零安装偏航；
- 让 Workbench 订阅 `/tf` 驱动设备；Workbench 只消费 Host 投影后的完整 `/joint_states` 帧。

### 4.3 几何、运动学与部署权威

| 事实 | 权威来源 | 不允许的替代来源 |
|---|---|---|
| 机械臂六轴拓扑/限位 | 厂家 URDF/Provider | 总装 CAD、SW mate、截图、rig map |
| 静态外壳与 occurrence | SolidWorks snapshot/设备级导出 | 文件名或截图猜测 |
| 仪器/夹爪运动语义 | 人签 mechanics patch + 控制资料 | legacy URDF 自动升格 |
| 导轨几何 | SolidWorks/legacy mesh | 通用运动学包中的占位外壳 |
| 导轨运动学 | `unilab_rail_linear` + 人签行程/方向 | 直接信任 legacy `m_joint` |
| 设备安装位姿 | DeployManifest/物理图 | 家族包、previewTransform |
| 当前关节 | telemetry | URDF、PointSet、部署清单 |
| TCP/点位/程序 | 控制器与部署层 | 网格或工作流动画猜测 |

### 4.4 Workbench 和工作流唯一通路

```text
Domain Provider
  → config.rendering.model + config.rendering.kinematics
  → /api/v1/kinematic-models/{device_id}.urdf
  → Material Graph
  → Pascal LabDeviceRenderer

WorkflowTask / Device Action
  → simulated / planned / observed joint source
  → 完整限定名 /joint_states
  → JointStateProjector
  → DeviceTelemetryHub
  → SSE
  → scene-runtime
  → applyJointStateToUrdf
```

不新增第二套前端 renderer，不把 pTLC clip 作为主运动源，不让预览 endpoint 冒充正式 WorkflowTask。

### 4.5 目标仓库布局

```text
assets/
  source-releases/
    feeding-station/<source-digest>/       # 只存清单/摘要/报告；原始 CAD 在 Git 外
  families/
    environment/feeding-station-rack/<digest>/
    mechanisms/eth17-linear-rail/<digest>/
    consumables/vial-4ml/<digest>/
  stations/
    feeding-station/
      station-decomposition.yaml
      station-layout.json
deploy/
  feeding-station/<device_id>/manifest.json
activations/
  <activation_id>/snapshot.json
packages/
  feeding_station_domain/                  # @device、Provider、注册表和图编译入口
reports/
  feeding-station/<stage>/<run-id>/
```

原始 `.SLDASM/.SLDPRT/.x_t/STL`、厂家 ZIP 和 Windows 运行缓存不进入 Git。Git 保存 schema、IR、清单、摘要、能力、资格与可重复构建所需代码；允许发布的大几何按仓库政策进入 Git LFS。

---

## 5. Windows 与 Mac 的职责边界

### 5.1 总体分工

| 能力 | Windows / SolidWorks 生成机 | Mac / EIT 开发机 |
|---|---|---|
| 原始 CAD 读取 | 负责，只读打开 | 不直接解析 SolidWorks |
| occurrence/mate/配置采集 | 负责 | 校验、消费 |
| 原生整站/设备级 GLB 导出 | 负责 | 校验、打包、提供给 Workbench |
| Legacy URDF/STL 解析 | 可做源侧预检 | 负责 Canonical IR、单位/名称规范化 |
| 厂家机器人 Provider | 只提供/校验源发布 | 负责 Provider、OS、Workbench 集成 |
| 人签 decomposition | 提供 occurrence 证据 | 生成草稿并组织人签；签署人拥有最终决定权 |
| FamilySimBundle | 可生成候选几何 | 负责最终摘要、能力和 Provider 形态 |
| DeployManifest/activation | 不拥有 | 负责 |
| Workbench/Workflow/SSE | 不负责 | 负责 |
| 真实 CAD 回归 | 负责 | 读取 Windows 报告 |
| 浏览器 E2E | 可做交接冒烟 | 负责正式验收 |

### 5.2 为什么需要两次 Windows–Mac 往返

一次整站 GLB 不能同时证明设备身份、稳定 occurrence 和可独立发布的家族边界。因此采用：

```text
Windows W1：发现性只读采集
  ↓
Mac M1：校验 + decomposition 草稿 + 人签
  ↓
Windows W2：按已签 occurrence 根导出设备级几何
  ↓
Mac M2：家族编译 + 部署 + activation + Workbench/Workflow
```

如果未来 Windows 导出的整站 GLB 能以稳定 occurrence ID 写入 node/extras，并通过两次导出语义一致性门禁，可在全站扩展阶段评估在 Mac 上拆分；第一条纵切仍优先采用设备级导出，减少身份错配。

---

## 6. 跨机交接合同

### 6.1 W1 发现性交接目录

```text
incoming/feeding-station-<date>-capture/
  station-handoff.json
  capture/
    assembly.snapshot.json
    capture-report.json
    source.json
    files.sha256
    station.glb
    station.glb.report.json
    console.log
  source-release/
    投料站方案模拟1.1.SLDASM
    ...Pack and Go 依赖...
  audit/
    station.x_t
    environment.json
    tool-versions.json
```

要求：

- JSON/YAML 使用 UTF-8；
- 清单引用必须是交接目录内 POSIX 相对路径；
- Windows 绝对路径只允许出现在 provenance/audit 字段；
- 每个源文件有 bytes + SHA-256；
- 记录 SolidWorks/Exporter/Blender/Python 版本；
- `source_read_only=true` 必须由“只读打开 + 前后哈希一致 + 无保存事件”共同证明，不能只检查文件权限位；
- capture report 的 component count 必须与 snapshot 一致；
- 父引用、根集合、环、重复 occurrence、隐藏/抑制/未解析状态必须可验证。

### 6.2 人签 decomposition

旧 v0 的 `occurrence_prefix` 一条规则只产生一个 placement，不足以自然表达重复料架和多台机器人。2026-08-27 已升级为精确子树 v1：

```yaml
schema: lab.station_decomposition/v1
station: eit.feeding-station
source_handoff_digest: <sha256>
devices:
  - subtree_root: <exact-rack-occurrence-id>
    family: environment.feeding-station-rack
    kind: static_environment
  - subtree_root: <exact-rail-occurrence-id>
    family: mechanism.eth17-linear-rail
    kind: device
robot_subtrees:
  - subtree_root: <exact-robot-occurrence-id>
    replaced_by: robot-family:dobot.cr5
unassigned_policy: fail
approval:
  status: approved
  reviewed_by: <human>
  reviewed_at: <ISO-8601>
```

规则：

- `subtree_root` 必须精确匹配 snapshot 中一个 occurrence；
- 编译器沿 parent 图展开子树，不靠显示名前缀猜测；
- 一个 occurrence 只能属于一个实例；
- 同一 family 可以出现多个 placement；
- `subtree_root` 与规则位置共同提供候选身份，不引入部署层 `device_id`；
- 机械臂 occurrence 只输出 comparison record，不进入仪器几何运动学。

### 6.3 W2 设备级几何交接

```text
incoming/feeding-station-<date>-geometry/
  geometry-handoff.json
  devices/
    rack-left-01/
      render.glb
      entity-map.json
      export-report.json
      files.sha256
    rail-front-01/
      render.glb
      entity-map.json
      export-report.json
      files.sha256
    bottle-4ml/
      source.stl
      unit-declaration.json
      files.sha256
```

`entity-map.json` 必须把 GLB node 与精确 occurrence ID 对齐。若无法建立映射，该导出只能是 `visual-only`，不得标 `semantic-scene`。

---

## 7. 分阶段开发与测试计划

每阶段都必须独立结束、产出可审计文件，并明确“通过代表什么、不代表什么”。

### P0 — 输入冻结与仓库卫生

目标：建立唯一输入边界，避免重复扫描、误提交和源文件漂移。

Windows 开发：

- 明确 `投料站方案模拟1.1.SLDASM` 为顶层总装候选；
- 验证 Pack and Go 引用完整、配置可打开；
- 准备只读工作副本，不在唯一源目录上运行 exporter；
- 生成源文件清单和工具版本清单。

Windows 测试：

- 文件数、总字节数和 SHA-256 重跑一致；
- 缺一个依赖零件时 preflight 必须失败；
- SolidWorks 已被其他用户打开时采集器拒绝接管；
- 采集前后源文件 hash/size/mtime 不变。

Mac 开发：

- 新增显式输入清单，只扫描根 `投料站-urdf`；
- 将 `投料站/投料站-urdf` 标为重复来源并排除；
- 原始 CAD/URDF/STL 保持 Git 外，Git 只保存清单、摘要、IR 和报告；
- 增加输入审计脚本，报告扩展名、单位声明、ROS 名称合法性和重复摘要。

Mac 测试：

- 扫描结果固定为 19 个 URDF，而不是重复后的 38 个；
- 10 个独立 STL 缺单位声明时失败；
- 不执行 `git add -A`；用 `git status --short` 确认原始目录没有误入暂存区。

验收产物：`input-inventory.json`、`input-roots.yaml`、`files.sha256`、`P0-REPORT.md`。

执行拆分：Windows 完成 `P0-W`（两次确定性清单一致、顶层总装存在、无共享
SolidWorks 会话）；Mac 完成 `P0-M`（确认原始目录仍在 Git 外、清单边界和重复根
策略明确）。Windows 显示 `p0-w-ready` 不是整个 P0 已完成。具体命令见 P0–P1
运行手册。

### P1 — Windows W1：真实总装只读采集

目标：产出 Mac 可验证的工站 occurrence 快照和整站视觉候选。

Windows 开发：

- 加固 `trial_sw_adapter.py`：
  - `OpenDoc6` 使用 silent + read-only；
  - 记录打开错误和 warning bitmask；
  - 捕获精确 occurrence ID、parent、document、configuration、suppression、visibility；
  - 记录局部变换和世界变换；
  - mate 只写 `candidate/unproven`；
  - 记录未解析、轻量化和重建状态；
  - 导出到 ASCII 临时路径，再复制到交接目录；
  - 采集前后重新计算全部源摘要。
- 输出整站 native GLB 和几何统计；
- 可选同步复制 `.x_t` 作为 B-rep 审计回退。

Windows 测试：

- 两次独立 SolidWorks 会话的 snapshot 规范化后相同；
- GLB magic、长度、mesh/primitives 非零；
- GLB 字节若不同，必须比较语义签名并登记差异原因；
- 所有 parent 引用存在、图无环、根集合正确；
- snapshot 数量与 capture report component count 一致；
- 故意令一个文件 hash 漂移，交接生成必须失败；
- 故意使用非 ASCII 临时导出路径，wrapper 应改用安全临时路径或明确失败。

Mac 开发：无业务编译，只准备接收目录。

Mac 测试：运行现有门禁：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/<capture>/station-handoff.json
```

验收条件：验证器返回 `passed=true`、`qualification=source-input-validated`，同时明确 `not_qualified_for` 仍含 collision、interlock 和 execution。

P1 的所有权是“Windows 生产，Mac 验收”：Windows 封装成功时只写
`ready-for-mac-validation`；Mac 独立重算摘要并通过现有验证器后，才写
`source-input-validated`。完整 handoff 走非 Git 传输，Git 只保存工具、合同和去敏
验证报告。

### P2 — Mac M1：handoff 加固与人签分解

目标：把真实 occurrence 图变成无遗漏、无重叠的设备实例候选。

2026-08-27 实施状态：以下 Mac 代码和夹具测试已完成；真实 W1 handoff、真实
occurrence coverage 与人工批准仍待 Windows 回传，因此当前状态是
`fixture-tested`，不是 `source-input-validated` 或真实工站 P2 完成。

Mac 开发：

- 加固 `verify_station_handoff.py`：
  - 校验 parent 引用、图环、根集合精确性；
  - 比较 snapshot/report component count；
  - 定义并校验 `source_files_digest` 与 `files.sha256` 的聚合算法；
  - 校验 GLB 几何统计，不只检查 magic；
  - 检查所有绝对路径只出现在 audit 字段。
- 将 decomposition 升级为 v1 精确 `subtree_root` 语义；
- 编译器按每个根生成一个 placement，支持同 family 多实例；
- 生成 coverage 报告和人审页面/Markdown；
- 用说明图只辅助人审，不自动生成位姿。

Mac 测试：

- 未分配、重复归属、无效根、父环、摘要漂移全部失败；
- 同一料架 family 的多个 occurrence 不冲突；
- 用两个同型号机器人 occurrence 夹具验证多实例；若真实 snapshot 确认存在多个实例，再替换为真实 occurrence；
- 修改一个 occurrence 的 parent 后 coverage 测试失败；
- draft 只能显式 `--allow-draft` 生成预览，不能进入发布。

当前可运行命令：

```bash
./.venv/bin/python scripts/compile_station_decomposition.py \
  incoming/<capture>/station-handoff.json \
  incoming/<capture>/station-decomposition.yaml \
  --output incoming/<capture>/station-layout.json
```

人工测试：机械/自动化负责人逐项确认：

- 设备边界；
- 重复实例数量；
- 机器人替换子树；
- 设备锚点；
- 隐藏/抑制 occurrence 的处置；
- 哪些活动机构仅为候选。

验收产物：批准后的 `station-decomposition.yaml`、`station-layout.json`、`coverage-report.json`。

### P3 — Windows W2：设备级几何导出

目标：按批准后的 exact occurrence roots 生成可独立发布的设备几何。

Windows 开发：

- 读取已批准 decomposition，不接受显示名模糊匹配；
- 对四个纵切资产分别导出：料架、导轨外壳、机器人 CAD 对照、4 ml 瓶；
- 机器人 CAD 对照只进入 comparison 输出，不进入正式 robot family；
- 保留每个 GLB node 到 occurrence ID 的 `entity-map.json`；
- 记录材质、三角面、primitives、包围盒、单位和导出日志；
- 对 4 ml 瓶显式声明 `source_unit: mm`。

Windows 测试：

- 同一设备两次导出的 entity 集合和语义几何签名一致；
- 不同设备 occurrence 不得混入同一输出；
- 导轨 GLB 外包络与预期米制范围相符；
- 4 ml 瓶缩放前约 15 × 46 × 15 mm，单位声明存在；
- 机器人对照几何带 `comparison_only=true`；
- 未找到 exact occurrence root 时失败，不回退到名称搜索。

Mac 测试：

- 校验 W2 `files.sha256`、路径边界、GLB 和 entity map；
- 把 W2 geometry digest 与 W1 decomposition digest 绑定；
- 任一 digest 漂移时拒绝进入 P4。

验收产物：`geometry-handoff.json` 和四个设备级几何目录。

### P4 — Mac：Canonical IR 与 FamilySimBundle

目标：把四类输入编译成分层正确、能力受限的家族包。

Mac 开发：

1. `LegacySwUrdfAdapter` 产品化：
   - 重用现有 `compile_legacy_urdf()` 的失败关闭逻辑；
   - 中文原名保存在 `display_name/source_aliases`；
   - family、link、mesh 使用稳定 ASCII slug；
   - mesh URI 改为发布合同要求的相对 URI；
   - legacy joint 只进入 `candidates[]`。
2. `StandaloneStlAdapter`：
   - 单位必须由 `unit-declaration.json` 显式给出；
   - 4 ml 瓶应用 0.001 缩放并记录原始/规范包围盒；
   - 物料/耗材不生成虚假 inertial、joint 或 Site。
3. `SwOccurrenceGeometryAdapter`：
   - 依据 entity map 生成 `entity-registry` 和 `geometry-roles`；
   - 输出 render LOD、selection mesh、collision candidate；
   - 保留 occurrence provenance。
4. 家族门禁：
   - 禁止 `device_id/base_pose/tcp/payload/point_table/current_joints/site_uuid`；
   - legacy `mechanics.joints` 必须为空；
   - 所有 artifact bytes/hash 必须匹配；
   - render bundle 初始预算：≤25 MB、≤500 primitives、≤3,000,000 triangles。

四个纵切输出：

| Family | 初始能力 | 明确禁止 |
|---|---|---|
| `environment.feeding-station-rack` | `semantic-scene` | motion/interlock/execution |
| `mechanism.eth17-linear-rail-shell` | `semantic-scene` | 未人签前 motion/interlock/execution |
| `robot.dobot.cr5` | `kinematic-preview` | site execution/现场互锁 |
| `consumable.vial-4ml` | `semantic-scene` 或 material geometry | motion/interlock/execution |

Mac 测试：

- golden IR/bundle 测试；
- 单位缺失、非法 package name、缺 mesh、重复 mesh basename、摘要漂移测试；
- legacy 正式 joints 非空时失败；
- family JSON 出现部署字段时失败；
- 两次构建 artifact digest 或语义签名一致；
- 4 ml 瓶规范尺寸约 0.015 × 0.046 × 0.015 m；
- visual/collision 共用网格时 capability 必须保持非 collision-qualified。

验收产物：四个内容寻址的 FamilySimBundle 和 gate report。

### P5 — Mac：领域 Provider 与物理图

目标：从家族包进入正常 UniLab Material Graph，而不是诊断夹具。

Mac 开发：

- 静态料架 Provider：`package_static`；
- 导轨静态外壳 Provider：`package_static`，根名 `{member_id}_base_link`；
- 导轨运动学：`unilab_rail_linear:build_kinematic_model`；
- CR5：`unilab_arm_cr5:build_moveit_model`；
- CR5 物理图 parent 指向导轨，导轨 carriage 为 `mount_link`；
- 4 ml 瓶作为 Material/Site 子物料，不混入机器人 URDF；
- 为每个 Provider 锁定 `source_digest` 和 topology digest；
- 安装偏航只使用物理图或 `mount_yaw_deg` 之一，默认沿用 pTLC 的物理图角度来源。

Mac 自动测试：

- 运行机械臂/导轨装配检查器：

```bash
./.venv/bin/python \
  dependencies/unilab_robot_template/.cursor/skills/use-unilab-arm-package/scripts/check_domain_arm_assembly.py \
  --domain <feeding-station-domain>
```

- 静态根和运动学根不重名；
- MoveIt 规划组只有 CR5 六轴；
- 导轨 joint 不出现在 CR5 `qualified_joint_names`；
- 图中不存在 `arm_base_joint`；
- 错误 source digest 启动失败；
- 两个 CR5 实例生成不同的限定关节名，帧不会交叉应用；
- 无本地 `entry` 时不写伪造 `format: urdf`。

验收产物：领域设备定义、Provider、注册表条目和最小物理图。

### P6 — Mac：DeployManifest 与 WorkCellActivation

目标：把家族事实和工站实例事实正式分开，并冻结一次可引用启动快照。

Mac 开发：

- 定义 `DeployManifest v0`：
  - `device_id`；
  - family/provider digest；
  - parent 与 `mount_link`；
  - 相对安装位姿；
  - calibration/tool/pointset/programset 引用，允许明确 missing；
  - capability/qualification；
  - 不保存当前关节。
- Manifest 编译为物理图节点和注册表 `model` 块；
- CAD `station-layout` 位姿只可作为 `cad_nominal` 预览候选；未经过部署审核/标定时不得标为现场 `base_pose`；
- activation 冻结：图节点摘要、家族摘要、部署摘要、编译器版本；
- activation ID 不得在运行中自动指向“最新”。

Mac 测试：

- 同 family 两个 `device_id` 对应两份 Manifest；
- 只改基座位姿时 family bytes/digest 不变；
- family digest 变化但 Manifest 未更新时 activation 编译失败；
- parent/mount_link 不存在或成环时失败；
- 缺 TCP/点表时允许预览，但 capability 明确禁止 execution；
- activation 内容完全相同则 ID 稳定；任一输入摘要变化则 ID 改变。

验收产物：最小纵切的 DeployManifest 集合、物理图产物和 activation snapshot。

### P7 — Mac：Workbench 主场景显示与拾取

目标：验证 activation 通过正式 Material Graph 在 Workbench 中加载。

Mac 开发：

- 使用现有 `config.rendering.model/kinematics` 契约；
- 保持 Pascal 唯一 renderer；
- 设备级选择使用稳定 Material/device ID；
- 4 ml 瓶通过 Material 图和 Site 关系显示/跟随；
- camera fit 根据可见 bounding volume 通用计算，不写测试资产特例。

Mac 自动测试：

- 模型和 mesh API 均返回 200；
- `X-UniLab-Topology-Digest` 与 activation 一致；
- 料架、导轨、CR5、4 ml 瓶全部非占位体；
- 点击四个资产得到互斥、正确的 selection；
- 2D/2.5D/3D/Split 不产生第二份实体；
- 页面无 `console.error`、`pageerror`；
- 缺 mesh、错误 topology、错误 activation 时 fail closed；
- 本地加载预算和内存记录进入报告。

现有冒烟入口：

```bash
./scripts/run_mac_kinematic_preview.sh
```

该入口只证明 CR5/FR5 预览链；P7 验收必须使用投料站 activation 和正常 Workbench 主场景。

验收证据：浏览器截图、可访问性树/selection 记录、网络请求清单、控制台日志、模型摘要。

### P8 — Mac：正式 WorkflowTask 驱动模拟运动

目标：用正式工作流而不是预览 endpoint 驱动导轨和 CR5 三维运动。

Mac 开发：

- 定义最小动作：
  - `rail.move_to(position_m)`；
  - `robot.move_joints(target_rad[])` 或受限 commissioning 动作；
  - `material.attach/detach` 只走 Material 图命令；
- simulated backend 按批准的限位插值；
- 以完全限定 joint names 发布完整帧；
- Task/Job 状态由 OS 权威接口产生；
- SSE 只是 invalidation/telemetry，不伪造工作流成功；
- `stale_after_s` 超时后停止应用新姿态；
- 同一个机器人拒绝并发冲突运动。

最小验证工作流：

```text
1. rail.move_to(0.20 m)
2. robot.move_joints(home → preview-pose-A)
3. attach 4 ml bottle to approved Site（仅物料图变化）
4. robot.move_joints(preview-pose-A → preview-pose-B)
5. detach bottle to target Site
6. rail.move_to(0.00 m)
```

步骤 3/5 不得通过关节帧移动物料，也不得把 Site 写进家族包。

Mac 测试：

- WorkflowTask create/read、Job 顺序、终态和 feedback；
- 每帧关节集合与 topology 精确相等；
- CR5 帧不能改变 rail joint，rail 帧不能改变 CR5 joints；
- 两个 CR5 实例并存时只移动目标实例；
- 中途断流后 stale；恢复后 sequence/boot_id 行为正确；
- 摘要漂移、缺关节、重复关节、超限目标、并发动作全部失败；
- cancel/pause/resume/step 使用统一 command 路径；
- HTTP accepted 不等于 Job succeeded，UI 如实显示中间态。

验收证据：WorkflowTask/Jobs REST 快照、SSE 帧、Workbench 录屏、终态和失败用例报告。

### P9 — 扩展到复杂机构、重复实例和整站

目标：在纵切稳定后扩大覆盖面，而不放宽门禁。

Mac/Windows共同开发：

- 按相同两次往返流程导入其余 17 个 URDF 家族和 9 个独立 STL；
- 对双侧夹爪逐项人签驱动关系、方向、行程和失电状态；
- 对高三角面末端生成 LOD 和简化 collision candidate；
- 增加两个同型号机器人、多个料架/耗材实例；
- 编译全站 activation。

共同测试：

- 全部 occurrence 覆盖；
- 设备计数与说明图/机械审核一致；
- 同 family 多实例无 ID/mesh/joint 冲突；
- 全站加载性能、内存、网络请求和交互帧率；
- 两次全站构建的语义摘要稳定；
- 任一单设备损坏不允许静默以占位体进入发布 activation。

### P10 — 碰撞、点位与真实硬件（独立资格项目）

目标：在软件闭环后，按证据逐项升级资格。

Windows/Mac 开发：

- 视觉 mesh 与碰撞 mesh 分离；
- 生成并审查凸包/凸分解/胶囊；
- 导入控制器 PointSet 或 ProgramSet，不可用程序号伪造点；
- 绑定 Calibration、ToolContext、payload 和 HardwareProfile；
- planned/commanded/observed 三层分离；
- 空间互锁先 shadow；无合格轨迹/扫掠返回 `unknown`。

测试顺序：

1. 离线 FK/限位；
2. 合格 collision 几何；
3. 标定与点位一致性；
4. 仿真 shadow；
5. 控制器 dry-run；
6. 低速空载现场测试；
7. 真实工艺验证。

P10 未完成不影响 G1–G8 的“软件资产管线闭环”结论，但禁止使用 `execution-qualified`。

---

## 8. 测试矩阵

### 8.1 四个纵切资产

| 测试 | 料架 | ETH17 导轨 | CR5 | 4 ml 瓶 |
|---|---:|---:|---:|---:|
| 源摘要与路径 | 必须 | 必须 | 必须 | 必须 |
| 单位声明/包围盒 | m | m | URDF m/rad | mm → m |
| ASCII family/mesh 名 | 必须 | 必须 | 已规范 | 必须 |
| entity/occurrence 映射 | 必须 | 必须 | CAD 仅对照 | 来源实体 |
| 正式运动学 | 无 | 人签后 1 轴 | 厂家 6 轴 | 无 |
| visual/collision 分离 | 后续 | 后续 | 厂家 collision 审核 | 通常无 collision 资格 |
| Provider 摘要 | 必须 | 外壳 + joint provider | 必须 | Material geometry digest |
| 多实例测试 | 需要 | 需要 | 强制 | 强制 |
| Workbench 显示/拾取 | 必须 | 必须 | 必须 | 必须 |
| Workflow 运动 | 不适用 | 必须 | 必须 | 仅 attach/detach 跟随 |
| 执行资格 | 禁止 | 禁止 | 禁止 | 禁止 |

### 8.2 失败关闭测试

每个发布阶段至少覆盖：

- 源文件 hash 漂移；
- 交接路径越界；
- 缺失源文件/mesh/GLB；
- 重复或非法 occurrence；
- parent 环或不存在的 parent；
- 单位缺失、异常缩放、非有限变换；
- 非归一化四元数；
- family 包出现部署禁字段；
- legacy joint 被误放入正式 `joints[]`；
- Provider source digest 不一致；
- mesh basename 冲突；
- 重复 link/joint；
- topology digest 或关节集合不匹配；
- stale/乱序/不同 boot_id 遥测；
- 工作流动作越限、并发冲突、取消中断；
- 模型 API 404、页面 console error 或占位体回退。

### 8.3 可复现性测试

| 层 | 比较方式 | 允许差异 |
|---|---|---|
| SourceRelease | 文件逐项 SHA-256 | 不允许 |
| assembly snapshot | 排序后的规范 JSON | 时间、绝对 audit 路径可剥离 |
| GLB | 字节 hash + 语义几何签名 | exporter traversal-only 差异可登记，不可影响实体/几何 |
| Canonical IR | 规范 JSON hash | 不允许未声明差异 |
| FamilySimBundle | artifact manifest hash | 不允许 |
| DeployManifest | 规范 JSON hash | 只有明确部署变更 |
| activation | 引用与内容摘要 | 任一输入变化必须产生新 ID |
| telemetry | 拓扑/序列合同 | 时间和值按测试轨迹变化 |

---

## 9. 自动化命令与新增工具清单

### 9.1 已存在、可立即运行

```bash
# 工站交接与分解单测
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest discover -s tests -v

# CR5/FR5 预览服务单测
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest discover \
  -s cr5-telemetry-proof/tests -v

# 真实 handoff 验证
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/<station>/station-handoff.json

# decomposition 编译
./.venv/bin/python scripts/compile_station_decomposition.py \
  incoming/<station>/station-handoff.json \
  incoming/<station>/station-decomposition.yaml \
  --output incoming/<station>/station-layout.json

# 现有机械臂预览冒烟
./scripts/run_mac_kinematic_preview.sh
```

### 9.2 建议新增的 Windows 工具

```text
windows/00-preflight-feeding-station.ps1
windows/01-capture-station-source-release.ps1
windows/02-export-approved-device-geometry.ps1
windows/03-verify-windows-output.ps1
windows/04-package-handoff.ps1
windows/capture_station.py
windows/export_device_subtrees.py
```

其中 P0 清单和 P1 封装已分别由可跨平台运行的
`scripts/inventory_station_source.py` 与 `scripts/finalize_station_handoff.py` 实现；
SolidWorks occurrence/GLB 采集当前复用交接包中的
`unilab-workbench-e2e-handoff-20260824/pipeline/trial_sw_adapter.py`。其余 Windows
包装器仍是建议接口，不能宣称已在 Windows 真实总装上执行。

### 9.3 建议新增的 Mac 工具

```text
scripts/audit_feeding_station_inputs.py
scripts/verify_geometry_handoff.py
scripts/compile_station_families.py
scripts/compile_deploy_manifests.py
scripts/freeze_workcell_activation.py
scripts/verify_workcell_activation.py
tests/test_feeding_station_inventory.py
tests/test_feeding_station_units.py
tests/test_station_decomposition_v1.py
tests/test_feeding_station_family_gates.py
tests/test_feeding_station_providers.py
tests/test_feeding_station_activation.py
tests/test_feeding_station_workflow_motion.py
```

新增命令在实现前只代表接口设计，不得在报告中写成“已可运行”。

---

## 10. 证据、报告与状态用语

每个阶段输出 `REPORT.md`，至少包含：

```text
阶段 / 日期 / 主机 / 工具版本
输入路径 + SHA-256
执行命令
自动测试通过/失败/跳过
人工审核人和结论
产物路径 + SHA-256
资格等级
明确 not_qualified_for
已知限制和下一阻塞项
```

统一状态：

| 状态 | 含义 |
|---|---|
| `planned` | 只有设计，无实现 |
| `implemented-untested` | 已写代码，未运行验证 |
| `fixture-tested` | 只用合成/小夹具测试 |
| `software-tested` | 用真实输入在软件链验证 |
| `browser-tested` | 正常 Workbench 主场景实测 |
| `simulation-tested` | 正式工作流 + 模拟关节链验证 |
| `bench-tested` | 台架或控制器 dry-run |
| `robot-tested` | 真实机器人执行并留证 |
| `blocked` | 有明确阻塞，未伪造结果 |

禁止把以下等同：

- 文件可解析 ≠ 模型可正确显示；
- Workbench 可显示 ≠ 位姿正确；
- 能播放预览 ≠ 正式 WorkflowTask；
- legacy joint 存在 ≠ 机构运动学已批准；
- visual mesh 可用 ≠ collision-qualified；
- 模拟通过 ≠ 真机通过；
- HTTP accepted ≠ Job succeeded；
- screenshot ≠ occurrence/位姿真源。

---

## 11. 推荐实施节奏与停止规则

### 第一迭代：真实输入进门

完成 P0–P2。停止条件是取得真实 W1 handoff 和批准后的四资产 decomposition。没有 occurrence snapshot 时，不继续编造站内位姿。

### 第二迭代：四资产家族闭环

完成 P3–P5。停止条件是四个家族通过门禁、Provider 检查器通过并能进入正常 Material Graph。导轨关节未人签时保持静态。

### 第三迭代：部署与 Workbench

完成 P6–P7。停止条件是 activation 可冻结，四资产在主场景显示/拾取，无占位体、无控制台错误。

### 第四迭代：正式工作流运动

完成 P8。停止条件是 WorkflowTask 权威状态、SSE、CR5/导轨运动和物料 attach/detach 全部闭合，并通过 stale/摘要/并发负向用例。

### 第五迭代：扩展全站

完成 P9。只有在最小纵切和重复实例测试稳定后，才批量导入剩余资产。

### 后续资格项目

P10 单独立项。缺真实控制器、标定、碰撞或点位时，保持 `blocked` 或 `unknown`，不通过放宽门禁推进。

---

## 12. 下一步的具体起点

下一步应从 P0/P1 开始，而不是继续写 Workbench 前端：

1. 在 Windows 机器上确认顶层总装和 Pack and Go 完整性。
2. 加固只读 SolidWorks capture，加入前后源哈希、父图和 component count 门禁。
3. 生成第一份真实 `station-handoff.json` 并放入 `incoming/`。
4. 在 Mac 上运行 handoff 验证器。
5. 基于真实 occurrence 只签四个纵切资产。
6. 回到 Windows 导出四个设备级 GLB/entity map。
7. 再开始 FamilySimBundle、Provider、DeployManifest 和 Workbench 集成。

这条顺序优先消除当前最大的未知量：真实 occurrence 身份和站内位姿。它同时复用已经通过的软件门禁与 CR5/FR5 预览链，避免重做前端加载器或把 legacy URDF 升格为未经证实的运动学。
