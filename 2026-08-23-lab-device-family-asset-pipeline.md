# 实验室设备家族资产管线

日期：2026-08-23  
状态：设计（尚未实现）  
适用：协作臂 / 工业臂 + 自动化实验仪器 + 物料架 / 耗材  
对照：纠正 pTLC 把几何、运动学、点位、部署编进同一条 Web 资产链的越权

Windows 机器上的生成 agent 请改读交接说明（本设计的可执行压缩版）：[`2026-08-23-lab-asset-pipeline-windows-agent-brief.md`](./2026-08-23-lab-asset-pipeline-windows-agent-brief.md)。

## 1. 目标与硬边界

管线只做一件事：把四类真实输入编译成 **设备家族包** 和 **实例部署包**，再在激活时合成不可变的 `WorkCellActivation`。Workbench、工作流运动投影、空间互锁、真实执行都只消费 activation，不直接加载散落的 URDF / STEP / GLB / 点表。

硬边界：

- 厂家 URDF 是机械臂运动学真源。禁止再为手臂手写全部轴线。
- 仪器 / 货架 / 耗材以 SolidWorks Pack and Go 为主源，STEP 为中立 B-rep 回退。
- 只有 GLB 时默认 `visual-only`。看得见不等于能运动或互锁。
- 点位来自机械臂控制器（你们说的「机械臂里的 PLC」）。它属于 **这台臂、这次安装、这组标定**，不得写进家族 URDF，也不得写进仪器或货架家族包。
- `device_id`、Site UUID、基座位姿、TCP、负载、当前关节值，全部留在部署层。

协作臂 / 工业臂的示教存储器在厂商文档里常叫 PLC、控制器或示教器。本管线把它规范为 **RobotController**，与工位侧 Siemens / 汇川等 **CellPLC** 分开。手臂点位走前者；工位气缸 / 轴 / 程序号走后者，两者都是部署资产。

## 2. 输入现实与 Adapter

| 资产类型 | 你们实际有的输入 | Adapter | 家族包最高默资格 |
|---|---|---|---|
| 协作臂 / 工业臂 | 厂家 URDF / Xacro + mesh（Elite CS、Dobot CR5 等） | `RobotUrdfAdapter` | `execution-candidate`（运动学 + 厂家碰撞；仍无现场点位） |
| 仪器、物料架、大部分耗材 | Pack and Go：`.SLDASM` + `.SLDPRT`，外加装配 STEP | `SwPackAndGoAdapter`，失败则 `StepAssemblyAdapter` | 几何/装配快照；运动语义待人签后才升格 |
| 部分仪器 / 耗材 | 仅 GLB | `GlbVisualAdapter` | `visual-only` |
| 手臂点位 | 控制器导出的示教点 / 程序号 / 实时关节 | `RobotControllerPointAdapter` | 不进家族包，只进该 `device_id` 的部署 Manifest |
| 工位 I/O（如有） | 工位 PLC 点表或程序选择器 | `CellPlcAdapter` | 同上，部署层 |

Uni-Lab-OS 里已有可钉扎的厂家包先例：`unilabos/device_mesh/devices/elite_robot/urdf/cs.urdf.xacro`。pTLC 的 CR5 也已改为固定 commit 的官方 xacro。家族臂包应继续钉版本，而不是从 TLC 总装里的臂 CAD 重建关节。

若 SolidWorks 总装里仍包含手臂零件：Adapter 必须把该子树标为 `replaced_by: robot-family:<model>`，几何可留作对照，**不得**再从 mate 生成臂关节。

## 3. 五层产物

```text
SourceRelease
    ├─ RobotUrdfAdapter / SwPackAndGoAdapter / StepAssemblyAdapter / GlbVisualAdapter
    ▼
Canonical mechanics IR          ← 所有几何/运动语义的唯一中间表示
    ▼
FamilySimBundle (immutable)     ← 设备类型，无 UUID、无点表、无基座
    │
    │   RobotControllerPointAdapter / CellPlcAdapter
    │   Calibration / ToolContext / SiteAccessBinding
    ▼
DeployManifest (per device_id)
    ▼
WorkCellActivation (immutable snapshot)
    ▼
Workbench / 运动投影 / 空间互锁 / 真实执行
```

### 3.1 SourceRelease

每种输入先做只读发布，不在这一层做语义发明。

```text
source-release/<family>/<revision>/
  source.json              # 类型、厂商、型号、导出工具、责任人
  files.sha256
  urdf-or-cad/             # 钉扎的 xacro/mesh，或 Pack and Go，或 STEP，或 GLB
  capture-report.json      # 单位、缺失 mesh、未解析零件、空节点
```

CAD 原始文件按现有政策留在 hardware root，不进 Git。仓库只保存清单、哈希、Adapter 报告和编译产物摘要。

### 3.2 Canonical IR

四个 Adapter 都编译到同一组文件。Workbench 不再分别理解 SolidWorks、URDF、GLB。

```text
entity-registry.json       # 稳定身份：link / instance / frame
frame-graph.json           # 父子坐标帧
mechanics.json             # 关节、限位、mimic；仪器侧可为空或仅候选
geometry-roles.json        # visual / collision / selection / ignore
collision-map.json         # 引用厂家碰撞或已审凸包
provenance.json            # 源哈希、Adapter 版本、能力等级
```

IR 单位一律米、弧度、四元数。原始 mm/deg 只出现在 provenance 的 audit 段。

### 3.3 FamilySimBundle

内容寻址、不可变、设备家族级。

```text
asset-bundle/<family>/<digest>/
  render-lod0.glb
  render-lod1.glb
  selection.glb
  mechanics.json
  frame-graph.json
  collision-static.glb     # 可空，若资格不足必须显式标记 missing
  collision-dynamic.glb
  attachments.json         # flange / slot / payload 附着帧，不含现场 TCP 数值
  capability.json          # visual-only | semantic-scene | kinematic-preview | collision-qualified
  reports/
  bundle.json              # digest 与文件清单
```

禁止出现的字段：`base_pose`、`tcp`、`point_table`、`device_id`、`site_uuid`、`current_joints`。

`attachments.json` 只声明法兰和插槽的 **家族局部帧**，例如 `flange`、`slot_A1`。现场 TCP 偏移是 ToolContext，在部署层绑定到这些帧。

### 3.4 DeployManifest

每个图节点 `device_id` 一份。同型号两台臂必须两份 Manifest、两份 PointSet。

锁定：

- FamilySimBundle digest
- 安装基座标定（world ← base）
- Calibration（运动学误差、导轨零偏）
- ToolContext + payload
- HardwareProfile（控制器型号、IP、程序修订）
- PointSet **或** ProgramSet（允许并存，但语义不同）
- MotionProfile
- 碰撞环境 digest
- 资格记录
- SiteAccessBinding（库位访问，PointSet 自身不存环境 UUID）

### 3.5 WorkCellActivation

激活编译器解析全部引用，写出不可变快照。工作流任务提交时冻结 activation ID。执行中禁止切到「最新资产」。新版本只能在无执行中命令、无 JobExecutionClaim、栅栏解除后原子切换。

## 4. 三条家族编译链

### 4.1 机械臂：厂家 URDF → 家族包

`RobotUrdfAdapter`：

1. 固定厂家包、型号、Xacro 修订、全部 mesh。
2. 展开 Xacro，解析 `package://`。
3. 提取 link/joint 身份、parent/child、origin、axis、type、position/velocity/effort limits、visual/collision、mimic/transmission。
4. 丢掉或忽略 `world` 固定座。基座位姿不是家族事实。
5. 统一单位与坐标约定。
6. 从 link visual 生成 Workbench GLB LOD。
7. 保留厂家 collision；允许额外生成经审查的凸包 / 凸分解 / 胶囊，但必须另存并留下报告。
8. 门禁：关节图连通、mesh 存在、限位自洽、零姿态 FK 可重复。

输出资格：`kinematic-preview` 起步；厂家碰撞通过检查后升 `collision-qualified`。仍 **不是** `execution-qualified`，因为还没有这台实例的点位和标定。

禁止用手写 `rig_map` 轴来代替这一步。pTLC 对工位轴的手写方法只适用于没有 URDF 的仪器机构。

### 4.2 仪器 / 货架 / 耗材：SolidWorks + STEP

主路径 `SwPackAndGoAdapter`：

1. 校验 Pack and Go 完整性（零件、配置、抑制状态）。
2. 只读打开装配，生成 `assembly.snapshot.json`：
   - 组件实例身份与源文档
   - 父子装配关系
   - 局部 / 世界变换
   - 材料与质量属性（有则记录，无则标 missing）
   - mate / 坐标系 **候选证据**
   - 可见、抑制、隐藏、未解析
3. 同步导出 AP242/AP214 STEP，作为 B-rep 审计回退。
4. 可选：XR 原生 GLB 作为视觉网格来源（pTLC `00_export_gltf` 可复用），但 GLB 不是运动学真源。

然后进入 **语义创作**（人 + Agent，见第 6 节）：

- 静态外壳 vs 候选刚体组 `RigidGroup`
- 抽屉、门、升降轴、夹具等候选关节
- 轴线、枢轴、零位、行程
- 可放置物料的业务插槽与交互帧
- 哪些几何参与渲染、选择、碰撞

SolidWorks mate、圆柱面、组件运动只能提出候选，不能自动变成正式 `mechanics.json` 关节。驱动方式、方向、限位、失电状态必须由机械 / 控制负责人确认。

STEP 回退 `StepAssemblyAdapter`：能恢复 B-rep、产品结构、实例放置；通常没有完整 mate 与稳定 SW 实例身份。能力默认低于 Pack and Go，缺的字段标 `unknown`，禁止用包围盒补猜关节。

### 4.3 GLB-only 降级链

`GlbVisualAdapter` 只发布视觉能力。升级必须走显式补丁和验证证据：

| 资格 | 允许 | 禁止 |
|---|---|---|
| `visual-only` | Workbench 显示、缩略图 | 运动、互锁、执行 |
| `semantic-scene` | 稳定拾取、部件映射 | 当关节用 |
| `kinematic-preview` | 已人工补充刚体、关节、轴、行程后的预演 | 当作已验证碰撞 |
| `collision-qualified` | 已补充并验证碰撞体、坐标、裕量 | 当作现场可执行 |
| `execution-qualified` | 与点位、标定、动作、现场验证闭合 | 无资格记录时宣称安全 |

GLB 节点层级较好时，可用类似 `rig_map` 的语义补丁升级，但必须保留人工批准。这是例外通道，不是仪器主链。

## 5. 点位链：从机械臂控制器来，且必须拆三类

点位 **不属于** 家族编译。它在手臂 FamilySimBundle 已经存在、该 `device_id` 已绑定基座和 ToolContext 之后发生。

### 5.1 A. 控制器可导出的目标点表 → PointSet

典型记录：点名、TCP pose、可选关节值、tool/user frame、导轨位置、速度、程序关联、控制器修订。

`RobotControllerPointAdapter`：

```text
控制器原始快照
  → 不可变 raw-point-snapshot
  → 单位 / 姿态规范化（发布态：米、弧度、四元数、显式 frame_ref）
  → 绑定 frame_ref、ToolContext、Calibration
  → 用家族 URDF 做 FK / 限位校验
  → PointSet
```

规则：

- 同时给了关节值和 TCP：必须用家族 URDF + 当前 ToolContext 做 FK，超容差失败，不得平均或挑一个解。
- 只有 TCP：不得随便选一个 IK 解并永久写入 PointSet。IK 属于运动规划策略和资格记录。
- PointSet 不保存 Site UUID。库位关系在 SiteAccessBinding。
- 原始 mm/deg 保留在 audit 段。

两台同型号臂即使点名相同，也是两份 PointSet。

### 5.2 B. 只暴露程序号或内部示教程序 → ProgramSet

不能伪造外部 PointSet。生成：

```text
ProgramSet
  - program selector
  - revision / checksum
  - typed parameters
  - expected completion witness
  - compatible hardware / adapter profile
```

Workbench 不得把起点到终点画成直线。只允许：已验证轨迹回放、阶段级估计动画、或资格确认过的保守扫掠包络。没有轨迹也没有合格包络时，空间互锁必须是 `unknown`。

### 5.3 C. 当前关节位置 → 遥测投影

`DeviceTelemetryProjection`：`device_id`、topology digest、boot_id、sequence、observed_at、关节、stale。只驱动 Workbench 的 observed 姿态，不进入 PointSet、ProgramSet、URDF 或调度写模型。

### 5.4 工位 PLC

若仪器还有独立 PLC：`CellPlcAdapter` 产出该仪器 `device_id` 的 PointSet 或 ProgramSet（例如缸到位、轴目标、程序号）。这些同样不得写进仪器家族包，也不得塞进手臂 URDF。

## 6. Agent 在管线中的位置

Agent 是候选编译器，不是定稿器。

允许自动起草并过几何门禁后进入草稿：

- 按子装配名 / 包围盒归工位或外壳
- 紧固件、拖链删减候选
- 材质规则草稿
- 直线模组行程与型号交叉验证
- 气缸 / 抽屉成员名单草稿（名称 + 贴面 + `expect_count`）
- 枢轴孔壁拟合（沿用 pTLC Blender 残差门禁）
- CAD 名称与控制器点名的 **对应关系候选**

必须人确认，Agent 只能标 `unproven`：

- 关节 `sign`、父空间轴向
- 真实驱动方式、失电状态
- 控制 mm 与物理 mm 是否同尺度
- DO 极性
- 示教点数值本身（来自控制器导出，不由网格猜）
- 允许接触对、工艺因果

写回只允许经 `rigPatch` 一类白名单补丁，禁止直接改冻结 bundle。

## 7. 运行时如何消费

Workbench 只调用：

```text
load(activationRef) → LabSceneSession
```

内部处理 URDF/GLB、LOD、节点绑定、坐标转换、遥测插值、工具挂载。禁止页面自己拼 `machine.glb` + `robot_points.json`。

工作流下发：

```text
作业尝试
  → 动作参数 + SiteAccessBinding + activation
  → ResolvedMotionIntent
       ├─ Workbench planned / commanded 投影
       ├─ Adapter → RobotCommand
       └─ SpatialInterlockDecision
```

空间互锁至少消费：当前 activation、URDF 运动学与碰撞、当前 Tool/payload、PointSet 轨迹或 ProgramSet 保守包络、新鲜遥测、SiteOccupancy、JobExecutionClaim、安全裕量与标定不确定度。

没有合格扫掠时返回 `unknown`，不得报「未发现碰撞」。Workbench 只显示结果，不签发执行许可。控制器硬限位、急停、安全 PLC 仍是底层安全权威。

## 8. 相对 pTLC 现管线的具体修正

| 现况 | 修正后 |
|---|---|
| 整机 SW → GLB，CR5 在 Blender 里替换，点表和 clip 与模型一起发布 | 臂走 URDF 家族包；仪器走 SW 家族包；点表走该臂 DeployManifest |
| `rig_map.yaml` 手写工位轴，也容易把手臂语义混进去 | 手臂关节禁止手写；`rig_map` 只服务无 URDF 的仪器机构 |
| `generated/robot-points.json` 跟三维产物放在一起 | PointSet 是部署资产，按 `device_id` 存储 |
| `ptlc.clip` 同时承担预演和点位展开 | clip 只是 Workbench 投影；执行许可另走 Adapter + 互锁 |
| 默认 GLB 可动画即可运行 | 资格不足的家族包不能进入强制互锁 |

pTLC 的 `00_export_gltf`、Blender 清洗、meshopt 预算门禁、官方 CR5 xacro 钉扎，作为 **Adapter 实现细节** 可以保留，但发布边界必须拆开。

## 9. 建议仓库布局

```text
assets/
  families/
    robots/<vendor>/<model>/     # SourceRelease 指针 + FamilySimBundle
    instruments/<name>/
    racks/<name>/
    consumables/<name>/
  deploy/
    <lab>/<device_id>/manifest.json
    <lab>/<device_id>/pointset.json
    <lab>/<device_id>/programset.json
  activations/
    <activation_id>/snapshot.json
```

原始 CAD 仍在 hardware root。Git 保存 IR、bundle 清单、digest、资格报告。大 GLB 走 LFS。

## 10. 实施顺序

1. 冻结 IR schema 与能力等级枚举；加发布门禁：家族包含点表 / UUID 则失败。
2. 实现 `RobotUrdfAdapter`，用现有 Elite / CR5 xacro 跑通 URDF → GLB + mechanics + collision。
3. 实现 `SwPackAndGoAdapter`；STEP Adapter 作回退；先出 `assembly.snapshot.json`，运动语义保持候选。
4. 实现 `GlbVisualAdapter` 的 `visual-only` 发布。
5. 实现 `RobotControllerPointAdapter`，严格区分 PointSet / ProgramSet / 遥测。
6. 为每个 `device_id` 建 DeployManifest 与原子 activation。
7. Workbench 改为只通过 activation 加载。
8. 空间互锁先 shadow，只有碰撞 + 点位/程序 + 标定 + 资格齐全才进强制模式。

本轮停在设计。不把现有 pTLC `three_d` 产物改名冒充新包。
