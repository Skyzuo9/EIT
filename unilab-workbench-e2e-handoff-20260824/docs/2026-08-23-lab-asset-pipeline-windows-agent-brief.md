# 实验室资产管线 — Windows Agent 交接说明

日期：2026-08-23  
读者：已配置 SolidWorks / Blender / miniforge 的 Windows 机器上的 agent  
目的：理解分层设计，并按该设计做 **第一次生成尝试**  
不要：把现有 pTLC 整机 `machine.glb` 改名冒充新家族包

把本文件整份读完再动手。本文件是单一真源，足够单独执行。

---

## 0. 你的任务

用本机已有的 CAD / URDF / 控制器导出能力，生成 **拆层后的资产**，而不是再跑一遍旧的「整机 SW → 一个 GLB + 点表」。

第一次尝试只要求跑通最小闭环，按下面顺序：

1. 机械臂家族包（厂家 URDF → `mechanics.json` + 视觉/碰撞 GLB）
2. 一台仪器或货架的装配快照（SW Pack and Go / STEP → `assembly.snapshot.json` + 视觉 GLB，运动语义保持候选）
3. 一份控制器点表草稿（若拿得到导出；拿不到就写 Adapter 接口和夹具，不要伪造点）

每一步都要过第 3 节硬门禁。做完写一份 `work/asset-pipeline-trial/REPORT.md`。

---

## 1. 设计（必须遵守）

### 1.1 一句话

家族包证明「这种设备是什么」。部署包证明「这台实例怎么安装、点在哪」。  
Workbench 只加载激活快照。两类资产在激活之前不得混写进同一个 GLB / YAML。

### 1.2 两条链，只在激活汇合

```text
设备家族链
  URDF / SolidWorks Pack and Go / STEP / GLB
        ↓ Adapter
  规范机械 IR（mechanics.json + frame-graph.json + geometry-roles.json）
        ↓
  不可变 FamilySimBundle
        │
        │     部署与控制链
        │       机械臂控制器点表 / 工位 PLC
        │       标定 / TCP / 工具 / payload
        │       device_id / Site
        │             ↓
        │       DeployManifest（每台实例一份）
        └─────────────┘
                      ↓
            WorkCellActivation（不可变快照）
                      ↓
      Workbench / 运动投影 / 空间互锁 / 真实执行
```

### 1.3 输入怎么进哪条链

| 输入 | Adapter | 进哪一层 | 默认资格 |
|---|---|---|---|
| 协作臂 / 工业臂厂家 URDF+Xacro+mesh | `RobotUrdfAdapter` | 家族包 | `kinematic-preview`；厂家碰撞通过后 `collision-qualified`。仍无现场点位，故不是 `execution-qualified` |
| 仪器、物料架、多数耗材：`.SLDASM`+`.SLDPRT` Pack and Go，外加 STEP | `SwPackAndGoAdapter`，失败则 `StepAssemblyAdapter` | 家族包 | 装配快照；mate 只是候选关节，人签之前不得升格 |
| 只有 GLB 的仪器/耗材 | `GlbVisualAdapter` | 家族包 | `visual-only` |
| 机械臂控制器示教点 / 程序号 / 当前关节 | `RobotControllerPointAdapter` | **该** `device_id` 的部署层 | 点位拆三类，见 1.5 |
| 工位 PLC（如有） | `CellPlcAdapter` | 该仪器实例的部署层 | 不得写入手臂 URDF 或仪器家族包 |

机械臂运动学 **只** 来自厂家 URDF。禁止用 `rig_map.yaml` 手写臂关节，禁止从总装 mate 生成臂轴。  
若 SW 总装里仍包含手臂零件：标 `replaced_by: robot-family:<model>`，几何可对照，不得当运动学真源。

SolidWorks 在时，以完整 Pack and Go 的 `.SLDASM` + `.SLDPRT` 为主源；装配 STEP 作中立 B-rep / 审计回退。  
只有 GLB 时，不得因为「看得见」就宣称支持运动或空间互锁。

### 1.4 各输入能证明什么

| 输入 | 可作为权威 | 不能默认相信 |
|---|---|---|
| 厂家 URDF/Xacro | link/joint 拓扑、类型、轴线、原点、限位、visual/collision 引用、mimic | 现场基座、真实 TCP、负载、零偏、PLC 点表、最终安全包络 |
| SolidWorks 完整装配 | 实例、层级、静止变换、材料、质量、部分 mate/坐标系、B-rep | mate ≠ 真实控制关节；不能自动定方向、失电、安全行程 |
| 装配 STEP | B-rep、产品结构、实例放置（优先 AP242/AP214） | 通常缺完整 mate、配置、控制语义、稳定 SW 实例身份 |
| GLB | 可视网格、材质、节点层级、静止变换 | 不保证单位、物理坐标、刚体、轴线、质量、碰撞、可编辑装配关系 |
| 臂控制器 / PLC | 现场目标点、关节目标、程序号、工具号、用户坐标系、速度、实时观测 | 不天然含可审计完整路径、碰撞语义或安全资格 |

### 1.5 点位必须拆三类（最容易混）

点位 **不属于** 家族编译。先有手臂 FamilySimBundle，再给该实例绑基座和 ToolContext，然后才编译点表。

**A. 可导出目标点 → PointSet**

原始快照 → 不可变 `raw-point-snapshot` → 米/弧度/四元数/`frame_ref` → 绑 ToolContext/Calibration → 用家族 URDF 做 FK/限位 → PointSet。

- 同时有关节值和 TCP：FK 超容差必须失败，不得挑 IK 解。
- 只有 TCP：不得把某个 IK 解写死进 PointSet。
- PointSet 不存 Site UUID。
- 原始 mm/deg 留在 audit。
- 两台同型号臂 = 两份 PointSet。

**B. 只有程序号 → ProgramSet**

禁止伪造 PointSet。Workbench 禁止把起终点画成直线。无已验证轨迹、无合格保守扫掠时，空间互锁必须是 `unknown`，不是「未发现碰撞」。

**C. 当前关节 → DeviceTelemetryProjection**

只驱动 Workbench observed 姿态。不进 PointSet、ProgramSet、URDF、调度写模型。

「机械臂里的 PLC」在本设计中规范为 **RobotController**（示教器/控制器存储器）。工位 Siemens / 汇川等是 **CellPLC**，走仪器实例部署层。

### 1.6 资格阶梯（尤其 GLB）

| 等级 | 允许 | 禁止 |
|---|---|---|
| `visual-only` | 显示、缩略图 | 运动、互锁、执行 |
| `semantic-scene` | 稳定拾取、部件映射 | 当关节用 |
| `kinematic-preview` | 已人工/已 URDF 补充刚体与关节后的预演 | 当作已验证碰撞 |
| `collision-qualified` | 已验证碰撞体、坐标、裕量 | 当作现场可执行 |
| `execution-qualified` | 点位、标定、动作、现场验证闭合 | 无证据时宣称安全 |

GLB-only 默认停在 `visual-only`。用 `rig_map` 式补丁升级必须留下人工批准记录。

### 1.7 Agent 可以自动做什么

可起草并过几何门禁后进草稿：子装配归组、紧固件删减、材质规则、直线模组行程交叉验证、气缸/抽屉成员名单、枢轴孔壁拟合、CAD 名与点名的对应 **候选**。

只能标 `unproven`、等人签：关节 `sign`、父空间轴向、驱动方式、失电、控制 mm 是否等于物理 mm、DO 极性、示教点数值、允许接触对。

写回只允许白名单补丁，禁止改已冻结 bundle。

### 1.8 运行时

Workbench 只 `load(activationRef)`。  
空间互锁消费 activation、URDF 运动学与碰撞、当前工具/负载、PointSet 轨迹或 ProgramSet 包络、新鲜遥测、库位占用、作业占用、裕量。  
Workbench 不签发执行许可。安全 PLC / 急停 / 硬限位仍是底层权威。

---

## 2. 相对现有 pTLC 管线

现有 `eit_ptlc/three_d/pipeline` 是 **实现零件库**，不是目标发布形态。

可复用：

- `00_export_gltf.py`（SW XR → GLB）
- `01_fix_step_names.py` / `02_convert_step.py`（STEP 回退）
- `03_clean_model.py` + `blender_clean.py`（清洗、官方 CR5 替换）
- `pipeline/rig_map.yaml` 里钉扎的 CR5 xacro：
  `vendor/dobot-cr5-37730d08-full/cra_description/urdf/cr5_robot.xacro`
- SolidWorks MCP：`three_d/mcp_servers/sw_mcp/`（`sw_list_components`、`sw_export_gltf`）
- Blender MCP：`three_d/mcp_servers/blender_mcp/`

必须停止：

- 把整机 `models/machine*.glb` 当作唯一资产
- 把 `generated/robot-points.json` 写进家族包
- 用手写 `rig_map` 轴代替厂家 URDF
- 把 `ptlc.clip` 当执行许可
- 改现有生产产物的文件名来「假装」新包

---

## 3. 硬门禁（违反即失败）

家族包 JSON/GLB 中 **不得出现**：

- `point_table` / `robot-points` / PLC 地址
- `device_id` / Site UUID / 实验室 UUID
- 现场 `base_pose` / `tcp` / `payload` 数值
- `current_joints` / 遥测

发布检查脚本必须扫描这些键；扫到就非零退出。

其他：

- 机械臂关节只来自展开后的厂家 URDF/Xacro
- mate / 圆柱面拟合 = 候选，不是正式关节
- 程序号不能变成 PointSet
- 无合格扫掠时互锁结果只能是 `unknown`
- 单位：发布态米、弧度、四元数；mm/deg 只在 audit

---

## 4. Windows 环境（按本仓库现配置）

以 `pipeline/pipeline.yaml` 为准，换机器先改该文件。当前约定：

```text
Python:   C:\ProgramData\miniforge3\python.exe
Blender:  C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
CAD 根:   E:\eit_lab\eit_lab_hardware\eit_ptlc_station
仓库:     E:\eit_lab\pTLC_platformUI   （或本机实际克隆路径）
```

启动前检查：

```powershell
$py = "C:\ProgramData\miniforge3\python.exe"
$blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
& $py --version
Test-Path $blender
Test-Path "E:\eit_lab\eit_lab_hardware\eit_ptlc_station"
Get-ChildItem "E:\eit_lab\eit_lab_hardware\eit_ptlc_station" -Filter "*.SLDASM" | Select-Object -First 10 Name
```

SolidWorks 必须能 COM 打开装配。动手前用 MCP `sw_info` 看是否有别人未保存的文档占用。只读打开，只关自己打开的文档。

原始 CAD **不复制进 Git**。权威清单：`eit_ptlc/three_d/SOURCE_ASSETS.yaml`。

不要求本机安装 ROS2。Xacro 展开用 Python（`xacro` pip 包或现成展开 URDF）。不要为了第一次尝试去装完整 ROS。

---

## 5. 第一次尝试的输出目录

不要写进 `eit_ptlc/three_d/models/`。新建：

```text
eit_ptlc/three_d/work/asset-pipeline-trial/
  REPORT.md
  families/
    robots/dobot/cr5/<digest 或 trial>/
      source.json
      files.sha256
      mechanics.json
      frame-graph.json
      geometry-roles.json
      provenance.json
      capability.json
      render-lod0.glb          # 可以先只有臂
      collision-static.glb     # 没有就在 capability 里标 missing
      bundle.json
    instruments/<name>/trial/
      source.json
      assembly.snapshot.json   # 实例、层级、变换、mate 候选
      provenance.json
      capability.json          # 先 visual-only 或 semantic-scene
      render-lod0.glb
  deploy/
    trial/<device_id>/
      manifest.json            # 引用家族 digest；可先缺标定
      raw-point-snapshot.json  # 有导出才写
      pointset.json            # 仅当 A 类点可校验时
      programset.json          # 仅当只有程序号时
      telemetry.schema.json    # C 类字段说明，不要写死当前关节当点位
```

`capability.json` 示例：

```json
{
  "grade": "kinematic-preview",
  "allows": ["workbench_preview", "fk"],
  "forbids": ["execution", "spatial_interlock_enforced"],
  "missing": ["site_calibration", "pointset"]
}
```

---

## 6. 建议实施步骤

### Slice A — 机械臂家族包（必做）

输入优先：

```text
eit_ptlc/three_d/vendor/dobot-cr5-37730d08-full/cra_description/urdf/cr5_robot.xacro
mesh: .../cra_description/meshes/cr5
```

若本机还有 Uni-Lab-OS：`unilabos/device_mesh/devices/elite_robot/urdf/cs.urdf.xacro` 可作为第二条对照，不要两条混成一个 bundle。

要做：

1. 记录厂家包 commit / 路径到 `source.json` + `files.sha256`。
2. 展开 Xacro，解析 link/joint、parent/child、origin、axis、limits、visual/collision。
3. 丢掉 `world` 固定座。不要把实验室基座位姿写进 `mechanics.json`。
4. 单位换成米、弧度。
5. 用 Blender 把 visual mesh 打成 `render-lod0.glb`（节点名 = link 名）。
6. 厂家 collision 能转就转；不能就 `capability.missing` 写明，不要用视觉网格冒充碰撞。
7. 写 `mechanics.json` / `frame-graph.json` / `provenance.json` / `bundle.json`。
8. 跑门禁：禁止点表/UUID/TCP 字段；关节图连通；mesh 文件存在。
9. 可选：对零位做一次 FK，把法兰帧写进报告，不要写进家族包当现场 TCP。

不要做：从 TLC 总装里的 Dobot CAD 重建六轴。

### Slice B — 仪器/货架装配快照（必做，保持候选）

1. 用 `SOURCE_ASSETS.yaml` 定位总装或 **一个子装配**（第一次不要贪整机 11 分钟转换）。优先 Pack and Go 目录齐全的子装配，例如单个工位。
2. `sw_list_components` 出顶层树；需要视觉时 `sw_export_gltf` 只导该子装配。
3. 写出 `assembly.snapshot.json`：实例名、源文件、父子、世界变换、材料（有则）、mate 列表标 `role: candidate`。
4. 同步保留/导出一份 STEP 作回退（AP214/AP242）。中文名乱码走现有 `01_fix_step_names.py`。
5. `capability.grade` 先 `semantic-scene` 或 `visual-only`。
6. **不要**把 mate 写成 `mechanics.json` 正式关节。最多 `mechanics.candidates[]`。
7. 若总装含手臂：snapshot 里标记 `replaced_by: robot-family:dobot-cr5`。

### Slice C — 控制器点表（有导出就做，没有就做接口）

若能从 Dobot / Elite 控制器或现有 `generated/robot-points.json` 读到示教点：

1. 先复制为 `raw-point-snapshot.json`（原单位、原字段、控制器修订）。
2. 判断 A/B/C：有 TCP/关节目标 → 草稿 PointSet；只有程序号 → ProgramSet；当前关节 → 只写 schema，不当点。
3. `deploy/trial/<device_id>/manifest.json` 引用 Slice A 的 bundle digest。
4. 若同时有关节和 TCP，用 Slice A 的 URDF 做 FK；超差写进 REPORT，不要「修一修」混过去。
5. manifest 里不要把 Site UUID 写进 PointSet 本体。

若控制器连不上：写 Adapter 函数签名、夹具 JSON、以及「缺控制器所以未发布 PointSet」。禁止用网格猜点。

### 不要在第一次尝试里做

- Workbench 改加载路径
- 强制空间互锁
- 整机 13 工位语义一次做完
- 把 clip 编译器接到新包上
- 改生产用 `models/machine.official-cr5.glb`

---

## 7. 最小 schema（第一次就按这个写）

### `mechanics.json`（臂）

```json
{
  "schema": "lab.mechanics/v0",
  "family": "dobot.cr5",
  "units": { "length": "m", "angle": "rad" },
  "root_link": "base_link",
  "links": [{ "id": "base_link" }],
  "joints": [{
    "id": "joint1",
    "type": "revolute",
    "parent": "base_link",
    "child": "link1",
    "origin": { "xyz": [0, 0, 0], "rpy": [0, 0, 0] },
    "axis": [0, 0, 1],
    "limits": { "lower": -3.14, "upper": 3.14, "velocity": 3.14, "effort": 0 }
  }]
}
```

不要加 `device_id`、`points`、`tcp`。

### `assembly.snapshot.json`（仪器）

```json
{
  "schema": "lab.assembly_snapshot/v0",
  "source_document": "....SLDASM",
  "instances": [{
    "id": "工位-1",
    "document": "....SLDASM",
    "parent": null,
    "transform_world": { "xyz_m": [0, 0, 0], "quat_xyzw": [0, 0, 0, 1] },
    "suppressed": false
  }],
  "mates_candidate": [{ "type": "concentric", "entities": ["A", "B"], "status": "unproven" }]
}
```

### `deploy/manifest.json`

```json
{
  "schema": "lab.deploy_manifest/v0",
  "device_id": "trial_cr5_01",
  "family_bundle": "families/robots/dobot/cr5/<digest>",
  "base_pose": null,
  "tool_context": null,
  "pointset": null,
  "programset": null,
  "notes": "trial; calibration not signed"
}
```

---

## 8. 验收

`REPORT.md` 必须包含：

- 本机路径是否与 `pipeline.yaml` 一致
- Slice A/B/C 各产出了哪些文件
- `capability.grade`
- 门禁扫描结果（家族包无点表/UUID）
- 未做项与原因
- 需要人签的 `unproven` 列表

命令示例：

```powershell
$root = "E:\eit_lab\pTLC_platformUI\eit_ptlc\three_d\work\asset-pipeline-trial"
Get-ChildItem $root -Recurse -File | Select-Object FullName, Length
Select-String -Path "$root\families\**\*.json" -Pattern "device_id|point_table|robot-points|site_uuid|tcp" -SimpleMatch
```

有命中 = 失败。

---

## 9. 实施顺序（本尝试对应前 3 步）

1. 冻结上述 v0 schema 与资格枚举；家族包含点表则失败。
2. `RobotUrdfAdapter`：CR5 URDF → GLB + mechanics。
3. `SwPackAndGoAdapter`：一个子装配 snapshot；STEP 回退。
4. （后续）`GlbVisualAdapter` visual-only。
5. （后续）控制器点表三类 Adapter。
6. （后续）每 `device_id` 的 Manifest 与原子 activation。
7. （后续）Workbench 只通过 activation 加载。
8. （后续）互锁先 shadow，证据齐全再强制。

---

## 10. 给 agent 的工作方式

- 中文写报告和提交说明。
- 先检查环境，再写小脚本到 `eit_ptlc/three_d/pipeline/trial_*.py`，不要改生产 `blender_clean.py` 行为，除非加纯新增、默认可关的函数。
- SolidWorks / Blender 用现有 MCP；COM 操作串行。
- 路径含中文时，OCCT/STEP 中间文件用 ASCII slug，中文名放 mapping CSV（现有 01 步已如此）。
- 失败就停在该 Slice，留下日志，不要用包围盒补关节或猜示教点让流程「变绿」。
