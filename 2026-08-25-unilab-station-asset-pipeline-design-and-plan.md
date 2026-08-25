# 工站资产管线：接入 UniLab Workbench 的设计与计划

日期：2026-08-25
状态：设计 + 执行计划（可落地版）
上位文档：[`2026-08-23-lab-device-family-asset-pipeline.md`](./2026-08-23-lab-device-family-asset-pipeline.md)（分层规范，仍是唯一权威）
Windows 生成机说明：[`2026-08-23-lab-asset-pipeline-windows-agent-brief.md`](./2026-08-23-lab-asset-pipeline-windows-agent-brief.md)

本文不修改分层规范，只回答一个问题：**给定「工站 SolidWorks 总装 + 厂家机械臂 URDF」这两类输入，怎么一步步做到模型在本机 UniLab Workbench 里显示、并随工作流指令运动。**

---

## 1. 目标与验收

期待原话：仿照 pTLC 的资产管理做法，让编译后的模型能在本地 UniLab Workbench 显示并接受工作流指令运动。

拆成可验收的四条：

| 编号 | 目标 | 通过标准 |
|---|---|---|
| G1 | 工站几何进 Workbench | 工站被拆成 N 个设备，各自在 Workbench 正确位姿显示、可拾取、版本固定 |
| G2 | 机械臂用厂家真源 | 臂运动学只来自厂家 URDF/Xacro；总装里的臂 CAD 只作对照 |
| G3 | 工作流指令驱动三维 | 提交工作流后，无需真机也能看到臂/机构在 Workbench 里按指令运动 |
| G4 | 分层不塌陷 | 家族包不含 `device_id`/`base_pose`/`tcp`/点表；换一台实例只改部署层 |

**不在本轮**：强制空间互锁、执行资格、真实产线放行。这些需要合格碰撞、标定、点位闭合，属于后续轮次。

---

## 2. 关键发现：OS 已经有家族包的消费口

这是本设计与之前判断的最大差别，也是整个计划能大幅缩短的原因。

`Uni-Lab-OS` 已经实现了一套**摘要锁定的领域包模型 Provider 契约**，位于 `unilabos/device_mesh/`：

| 契约 | 文件 | 作用 |
|---|---|---|
| `package_moveit` | `package_moveit_model.py` | 有运动学的设备（机械臂）：同时产出执行 URDF 与渲染 URDF |
| `package_static` | `package_static_model.py` | 静态外壳：必须有 collision，**禁止** `transmission`/`ros2_control`/`gazebo` |
| `joint_state_provider` | `package_joint_state_model.py` | 仪器机构：静态外壳 + 独立关节拓扑，可与外壳合成 |

它已经内建了我们本来要自己造的东西：

- **不可变性**：注册表里写 `source_digest`（SHA-256），Provider 返回的摘要不一致就**启动关闭**。
- **执行/渲染分离**：`execution_urdf` 给 MoveIt/ros2_control，`render_urdf` 给 Workbench，两者可动关节集合必须完全相同。
- **能力边界**：`package_static` 拒绝任何执行/控制内容，正好对应 `semantic-scene` 之下的资格。
- **部署位姿来自物理图**：`apply_graph_world_mount()` 用 `resolve_graph_world_pose()` 把图上父子位姿合成为世界安装（mm/deg → m/rad）。
- **父子挂载**：父设备可暴露 `mount_link`，子设备唯一的 `world` 固定关节会被改挂到该 link——**这就是「臂装在导轨滑台上」的现成机制**。
- **关节归属**：`qualified_joint_names` 必须由 `device_id` 完全限定，且与渲染 URDF 的可动关节精确一致。

启动时 `kinematic_runtime.compile_kinematic_runtime()` 把结果写到资源上：

```python
config["rendering"]["model"] = {
    "path": f"/api/v1/kinematic-models/{device_id}.urdf",
    "format": "urdf", "position": [0,0,0], "rotation": [0,0,0],
}
config["rendering"]["kinematics"] = {
    "device_id": ..., "topology_digest": ...,
    "qualified_joint_names": [...], "stale_after_s": ...,
}
```

前端 `uni-lab-fe` 正好消费这两个字段：`materialRenderingSnapshot.ts` 读 `config.rendering`，`LabDeviceRenderer` 要求帧的 `deviceId` + `topologyDigest` + 排序后的关节名集合与 `kinematics` **精确相等**才应用关节值。

**结论：前端不需要新的 activation loader，也不需要移植 pTLC 的 ClipPlayer。资产管线的正确出口是「领域包 Provider」。**

一个重要事实：**当前仓库里没有任何注册表 YAML 使用 `package_moveit` / `package_static`**（只有测试引用）。这条链路已建成但无人使用。我们的管线可以成为它的第一个真实生产者。

---

## 3. 三边现状（简要对齐）

```text
pTLC（能看见+能预演，但不在 UniLab Workbench）
  工站 SLDASM → XR GLB → Blender 按 rig_map 重挂 → 换官方 CR5 网格
    → 一个 machine.official-cr5.glb + device-manifest
    → 点表/操作编成 clips + action-motion-map
    → PlatformUI 孪生页：直播遥测 或 ClipPlayer 预演

UniLab（能看见+真机在动时能跟）
  物料图 / 领域包 Provider → config.rendering → Pascal lab-device
    → 关节动靠 /joint_states → 遥测 SSE → applyJointStateToUrdf
    → 工作流目前只画物料转移线，不播动画

本轮交接包（已完成的一截）
  五类输入 → 五个 semantic-scene 家族包 → 隔离静态 catalog
    → kernel-web 夹具页只读显示 + 列表拾取
```

差别的本质：pTLC 的运动来自**预编译 clip**，UniLab 的运动来自**关节遥测契约**。UniLab 这条更接近真实执行，也更适合分层。所以 G3 的做法不是移植 clip，而是**让仿真也发关节状态**（见 §6）。

---

## 4. 分层：家族 / 部署 / 激活，落到现有实现

上位规范的五层保持不变，本文只补「每层今天落在哪个真实对象上」。

| 层 | 规范对象 | 今天的落点 | 缺口 |
|---|---|---|---|
| SourceRelease | 只读源发布 | 交接包 `captures/` + `files.sha256` | 工站级 Pack and Go 尚未接入 |
| Canonical IR | `mechanics/frame-graph/entity-registry/geometry-roles` | 交接包已产出（仪器侧） | 机械臂 IR 未产出 |
| FamilySimBundle | 不可变家族包 | 交接包 `bundle.json` (`lab.family_sim_bundle/v0`) | 需增加「可发布为 Provider」的形态 |
| DeployManifest | 每 `device_id` 一份 | **物理图节点**（`position` mm + `config.rotation` rad + parent）+ 注册表 `model.source_digest` | 无签署来源，无 TCP/点表/标定 |
| WorkCellActivation | 不可变快照 | OS 启动时的摘要校验事实上等价 | 未落成可引用的快照记录 |

**重要修正**：DeployManifest 不应与物理图并列另造一套。物理图今天**就是**部署事实的载体。正确做法是：

> DeployManifest 是**签署源**，其编译器生成/更新物理图节点与注册表 `model` 块（`provider` + `source_digest`）。图是产物，不是真源。

同理，WorkCellActivation v0 = **启动时把 {图节点 + 家族摘要 + 部署摘要} 冻结成一条可引用记录**，而不是新造一个运行时。OS 已经在做摘要校验并失败关闭，缺的只是把结果落成快照。

---

## 5. 编译链：工站总装 + 厂家 URDF → 家族包

### 5.1 输入分流

工站总装**不是**一个家族包。它同时包含环境、仪器、导轨，以及本该被厂家 URDF 替换掉的臂零件。

```text
输入 A  工站 SolidWorks Pack and Go
输入 B  该工位机械臂厂家 URDF/Xacro（本机已有 Elite CS：
        Uni-Lab-OS/unilabos/device_mesh/devices/elite_robot/urdf/cs.urdf.xacro）

        ┌───────────────┴───────────────┐
        ▼                               ▼
  SwPackAndGoAdapter                RobotUrdfAdapter
  + 工站分解表（人签）                只信厂家 link/joint
  臂子树标 replaced_by                禁止从 mate / rig_map 造臂轴
        │                               │
        ▼                               ▼
  N 个仪器/环境家族包                 1 个机械臂家族包
  semantic-scene 起步                 kinematic-preview 起步
        └───────────────┬───────────────┘
                        ▼
              station-layout.json（部署候选，非家族资产）
```

### 5.2 工站分解表

新增一份人签配置 `station-decomposition.yaml`，是 pTLC `rig_map.yaml` 中**仅几何归属**部分的对应物：

```yaml
schema: lab.station_decomposition/v0
station: eit.station-a
source_assembly: <Pack and Go 顶层 SLDASM>
devices:
  - family: instrument.ptb22-linear-guide
    match: { occurrence_prefix: "PTB22-" }
    kind: device
  - family: environment.station-frame
    match: { occurrence_prefix: "机架-" }
    kind: static_environment
robot_subtrees:
  - match: { occurrence_prefix: "CS_" }
    replaced_by: robot-family:elite.cs
```

规则：
- `match` 只允许基于 SW occurrence 身份，不允许基于显示名猜测。
- 未被任何规则覆盖的 occurrence 一律进入 `unassigned`，**门禁失败**，不静默丢弃。
- `robot_subtrees` 命中的几何**不进任何家族包的运动学**，只留对照记录。

SW Adapter 已经能提取每个 occurrence 的 `transform_world.xyz_m` + `quat_xyzw`，因此工站内各设备的**相对位姿可以自动导出**，作为 `station-layout.json` 的候选值，等待人签后进入部署层。

### 5.3 家族包的两种发布形态

家族包本身仍是内容寻址的目录（保持现有 `lab.family_sim_bundle/v0`），但要**同时**支持两种消费：

1. **静态 catalog**（已实现）：给夹具页做显示/拾取验证。
2. **领域包 Provider**（新增）：给 OS 真正加载。

Provider 形态的约束（由 OS 校验，必须满足）：

| 约束 | 来源 |
|---|---|
| `qualified_joint_names` 必须 `{device_id}_` 前缀 | `package_joint_state_model.py` / `package_moveit_model.py` |
| 渲染 URDF 可动关节集合 == `qualified_joint_names` | 同上 |
| 渲染 URDF mesh URI 必须是 `{device_id}/meshes/{filename}` | `_validate_render_mesh_uris` |
| `mesh_paths` 文件名不得重复且必须存在 | 同上 |
| SRDF 必须且只能有一个完整 chain group | `package_moveit_client_spec` |
| `package_static` 必须有 collision，禁止执行内容 | `package_static_model.py` |
| link/joint 名必须属于成员命名空间 `{member_id}_` | 同上 |

**关键推论**：家族包里**不能**写死带 `device_id` 前缀的关节名——那是实例事实。家族包存**未加前缀的关节拓扑**，Provider 在实例化时加 `{device_id}_` 前缀并计算 `topology_digest`。这与「家族包禁止 `device_id`」的门禁完全自洽。

---

## 6. 运动链：工作流指令 → 三维

三条通道，优先级从易到难。**都复用同一条关节遥测链，不新增前端渲染路径。**

```text
                   ┌─ 通道 A observed（真机/驱动）
工作流节点 → OS 动作 ─┼─ 通道 B simulated（无硬件）
                   └─ 通道 C planned（MoveIt 预览，可选）
                              │
                    发布 /joint_states（限定名）
                              ▼
        HostJointStateProjection → JointStateProjector（按 qualified 名映射）
                              ▼  40Hz
              EdgeControlBridge → DeviceTelemetryHub
                              ▼  SSE device.telemetry.snapshot / changed
        uni-lab-fe realtime.ts → scene-runtime 帧缓冲
                              ▼  ≥100ms 节流，stale 帧不应用
              LabDeviceRenderer → applyJointStateToUrdf
```

**通道 B 是 G3 的主路径，也是本设计对 pTLC 的最大偏离。**

pTLC 需要 clip，是因为它的孪生页没有关节遥测契约。UniLab 有。因此「不接真机也能动」应该实现为**仿真关节发布器**：读取动作目标，按家族包 `mechanics.json` 的关节限位插值，用限定关节名发布 `/joint_states`。

这样做的好处：

- 真机与仿真**共用同一条链路**，前端零改动，不存在「预演能动、真机不能动」的双份实现。
- 摘要不匹配自动失败关闭（`topology_digest` 校验），不会出现模型与运动学漂移。
- `stale_after_s` 到期自动停，不会出现「看着在动其实断流」。

OS 侧已有可参考的仿真关节发布先例（`liquid_handler_joint_publisher.py`、`joint_republisher.py`），以及 `--action_mode simulate`。

**不做**：把 pTLC 的 `action-motion-map.json` / `ptlc.clip` 作为 UniLab 的主运动源。它可以作为**演示投影**在后期补充，但不得代替执行许可，也不得当点位使用。

物料搬运（取放板、装载）不走关节通道：它是物料图的父子/库位变更，前端已有转移线覆盖层。

---

## 7. 资格阶梯与门禁

沿用规范的五级阶梯。本轮各家族的目标资格：

| 资产 | 输入 | 本轮目标资格 | 允许 |
|---|---|---|---|
| 机械臂 | 厂家 URDF/Xacro | `kinematic-preview` | 显示、拾取、关节运动预演 |
| 仪器（有机构） | SW + 人签机构 | `semantic-scene` → 人签后 `kinematic-preview` | 显示、拾取；签后可动 |
| 仪器（静态） | SW / STEP | `semantic-scene` | 显示、拾取 |
| 环境/机架 | SW | `semantic-scene` | 显示 |

门禁改动（现有 `run_family_gates` 需分支）：

- 机械臂家族包允许**非空** `mechanics.joints[]`，但要求 `source_authority` 为厂家 URDF，并校验关节图连通、限位自洽、零姿态 FK 可重复。
- legacy SW URDF 仍强制 `joints: []` + 全部候选 `unproven`（现状保持）。
- 继续禁止家族包出现 `device_id`/`base_pose`/`tcp`/`payload`/`point_table`/`current_joints`。
- 新增：工站分解未覆盖的 occurrence → 失败。
- 新增：Provider 形态自检（关节名、mesh URI、SRDF chain 唯一性）在**编译期**跑一遍，不要等到 OS 启动才失败。

从 pTLC 值得移植的门禁与手法：

- `keepNamed` / `keepLeaves` 式的**节点名保留**：优化不得破坏稳定 ID。
- **硬预算门禁**：≤25 MB / ≤500 primitives / ≤3,000,000 triangles 作为第一版基准，之后按 UniLab 真实场景重测。
- **语义重挂**：按 occurrence 模式把 CAD 零件归组到设备/机构，而不是靠显示名。
- **FK 校验闭环**：钉厂家 URDF + 版本化标定 + 残差指标。
- **失败关闭的编译器**：输入哈希锁定，缺证据就停。

明确不移植：整机单 GLB；`rig_map` 混写家族几何 + 部署标定 + PLC 遥测；clip 既预演又当点位；从 mate 生成臂关节。

---

## 8. 仓库布局

```text
assets/
  families/
    robots/<vendor>/<model>/<digest>/      # 厂家 URDF 家族包
    instruments/<name>/<digest>/
    environment/<name>/<digest>/
  stations/
    <station>/station-decomposition.yaml   # 人签，几何归属
    <station>/station-layout.json          # 自动导出的部署候选
  deploy/
    <lab>/<device_id>/manifest.json        # 签署源
    <lab>/<device_id>/pointset.json
  activations/
    <activation_id>/snapshot.json
packages/
  <domain-package>/                        # 家族包的 Provider 发布形态
```

原始 CAD 留在 hardware root，不进 Git。Git 只存 IR、清单、摘要、资格报告；大 GLB 走 LFS。

---

## 9. 分阶段计划

每阶段都必须可独立验收，且不得跳过资格边界。

### M0 — 已完成（基线）

五个仪器家族包 + 隔离静态 catalog，在本机 kernel-web 夹具页完成显示、列表拾取、四类负向用例（无效 catalog / 缺 GLB / 哈希漂移 / 禁止能力）。等级：仅基线夹具接入，非静态全流程。

### M1 — 机械臂家族包 + Workbench 显示 + 关节可动

**做什么**
1. 实现 `RobotUrdfAdapter`：Elite CS xacro → 展开、抽取 link/joint/limits/collision → `mechanics.json`（正式关节非空）+ mesh 集合。
2. 把该家族包发布为领域包 Provider（`package_moveit`）：产出 `execution_urdf` / `render_urdf` / `srdf` / `qualified_joint_names` / `topology_digest` / `source_digest`。
3. 注册表 YAML 声明 `model: { type: package_moveit, provider: "...:build", source_digest: "..." }`。
4. 物理图放一个该设备节点，给出位姿。

**验收**
- `GET /api/v1/kinematic-models/{device_id}.urdf` 返回，响应头带 `X-UniLab-Topology-Digest`。
- Workbench 里出现该臂，位姿正确，可拾取。
- 手动发一组限定名 `/joint_states` → 臂在 Workbench 里动。
- 故意改 `source_digest` → OS 启动关闭（失败关闭生效）。

**为什么先做这个**：它是最短的一条「显示 + 运动」闭环，且不依赖 SolidWorks 与工站分解。做完就证明整条消费链通了。

### M2 — 工站分解

**做什么**
1. `station-decomposition.yaml` schema + 人签流程。
2. SW Adapter 支持按 occurrence 子树导出多个家族包（今天是单装配单包）。
3. 臂子树标 `replaced_by: robot-family:<vendor>.<model>`。
4. 自动导出 `station-layout.json`（各设备相对工站原点位姿，来自 SW `transform_world`）。

**验收**
- 一个工站总装 → N 个家族包 + 1 份 layout 候选，无 `unassigned` occurrence。
- 静态夹具页能按 layout 层级摆出工站（不再是 2 m 网格）。
- 臂位置由 M1 的家族包占据，总装臂 CAD 不产出运动学。

### M3 — 部署层

**做什么**
1. `DeployManifest v0`：`device_id`、家族包 digest、基座位姿、挂载父与 `mount_link`、工具/TCP、点表引用、标定引用。
2. 编译器：Manifest → 物理图节点 + 注册表 `model` 块。
3. 「臂装在导轨上」用 OS 现成的父 `mount_link` 机制验证。

**验收**
- 同型号两台 = 两份 Manifest、两个 `device_id`、两套限定关节名，互不串扰。
- 改 Manifest 的基座位姿 → 场景变化；家族包字节不变。
- 家族包门禁仍拒绝 `base_pose`/`tcp`/`device_id`。

### M4 — 工作流驱动三维运动（G3）

**做什么**
1. 仿真关节发布器：动作目标 → 按家族包限位插值 → 限定名 `/joint_states`。
2. 仪器机构走 `package_static` + `joint_state_provider` 合成路径。
3. 断流/摘要漂移行为验证。

**验收**
- 无硬件下提交工作流 → 臂与仪器机构在 Workbench 里按步骤运动。
- 拔掉遥测源 → 超过 `stale_after_s` 后停止，不冻结在错误姿态。
- 家族包换版本但 Manifest 未更新 → 拒绝运动，不静默降级。

### M5 — 点位 / 程序 / 互锁（受限）

**做什么**
1. 有真实控制器导出时才做 PointSet；只有程序号时只出 ProgramSet，**不伪造点**。
2. planned / commanded / observed 三层姿态投影。
3. 空间互锁先 shadow；无合格扫掠一律返回 `unknown`。

**验收**
- PointSet 与 ProgramSet 语义分离，当前关节值不进任何一方。
- Workbench 只显示互锁结论，不签发执行许可。

---

## 10. 风险与边界

| 风险 | 说明 | 处置 |
|---|---|---|
| SW 导出不可复现 | 已知两次导出 GLB 字节不同（`component_traversal_order_only`） | 语义摘要作为家族修订依据；字节差异记入 provenance，不阻塞显示资格 |
| 工站装配巨大 | 单次整机转换耗时长、预算超限 | 先做单工位子装配；预算门禁失败即停，不放宽 |
| 关节名前缀契约 | 家族包若写死 `device_id` 前缀会破坏分层 | 家族存无前缀拓扑，Provider 实例化时加前缀 |
| 仪器机构升格冲动 | mate/legacy 关节看起来能动 | 驱动方式、方向、限位、失电状态必须人签后才升 `kinematic-preview` |
| 把本轮当执行资格 | 显示能动 ≠ 可执行 | 任何阶段产出都不得标 `execution-qualified` |
| 前端拾取粒度 | 今天是设备级 bbox，非 link/occurrence | M2 之后单独评估；`entity-registry` 已具备映射数据 |

**明确不做**：覆盖现有 `machine.glb` 或生产模型；把 `previewTransform` 当 `base_pose`；从 SW mate 生成臂关节；把静态 catalog 当 `WorkCellActivation` 加载进生产 Workbench 入口。

---

## 11. 与上位规范的差异登记

本文对 [`2026-08-23`](./2026-08-23-lab-device-family-asset-pipeline.md) 规范做了两处**实现层修正**，语义边界未变：

1. **DeployManifest 不另起炉灶**：物理图节点是部署事实的现有载体，Manifest 作为签署源生成图，而不是与图并列。
2. **家族包的发布出口是领域包 Provider**：规范第 7 步「Workbench 改为只通过 activation 加载」在实现上落为「OS 通过摘要锁定的 Provider 加载，activation 记录该次冻结」，前端不新增第二套加载器。

其余（家族/部署分离、资格阶梯、点位三分、互锁 `unknown` 默认）全部沿用。
