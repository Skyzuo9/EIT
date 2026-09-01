# UniLab 通用资产管线与空间约束自动计算：项目级 Design & Plan

日期：2026-08-28
范围：`unilab-asset-pipeline`、`pTLC_platformUI`、`Uni-Lab-OS`、`uni-lab-fe`、`unilab_robot_template`
测试样例：投料站、EIT 既有 pTLC 工站
文档状态：`implementation-authority-draft/v8`；已回填全轨迹离线播放、MoveL 编译轨迹、随动工具/payload 与采样式环境代理碰撞诊断
当前执行模式：`offline + shadow`；不授予碰撞、互锁或真机执行资格
家族分层权威：[2026-08-23 实验室设备家族资产管线](./2026-08-23-lab-device-family-asset-pipeline.md)
本文相对 08-23 只增加空间证书链、运行模式和 v0 产物合同；不取代家族/部署分层

## 0. 结论与状态口径

项目已经具备从 CAD/URDF 输入、稳定身份与坐标转换、家族包、Workbench 场景、
运动学预览，到标准 WorkflowTask 可视化回放的主要软件骨架。两个测试样例互补：

- **投料站**验证通用性：真实整站 SolidWorks handoff、自动设备边界候选、独立机器人
  URDF、跨仓加载、坐标转换和模拟工作流；空间侧本轮只是摘要锁与失败关闭夹具；
- **pTLC**验证空间算法：已有整机模型、真实控制器点表、标定、机器人/机构动作脚本、
  并行流程黄金样本和一批碰撞代理；本轮已有离线 candidate scene、waypoint 合同和
  `unknown` 证书。

不能把设计、前置资产或 pTLC 投影格式写成通用求值器已完成。状态必须按四条正交轴
书写，一条轴上的进展不得带动其他轴：

| 轴 | 允许取值 | 当前项目落点 |
|---|---|---|
| 实现深度 | `not-started` / `partial` / `implemented-and-tested` | 离线纵切、CR5 FK/link-state、14 段/522 帧播放、7 段已编译 MoveL、随动工具/payload、采样式环境 AABB 距离与盒体 SAT、OS 派发前 Shadow 准入端口、默认关闭的空间硬件互锁适配器和独立 Workbench 审阅器已测；控制器级 CP/MoveJ 精确插补、合格环境注册/原始 CAD 窄相、OS 持久 decision store、Activation/Pascal 主场景叠加未实现 |
| 合同成熟度 | `design-intent` / `design-frozen` / `schema-frozen-v0` | v0 十份 schema 已在本地冻结其**窄绑定面**、尚待提交；通用 MotionContract、Stop/Recovery 算法仍是 intent |
| 运行模式 | `offline` / `shadow` / `enforced` | 只允许 `offline + shadow` |
| 硬件资格 | `none` / `historical-as-built-shadow` / `hardware-qualified` | pTLC 为历史影子；投料站为 none；没有任何样例 hardware-qualified |
| 阶段关闭 | `phase-not-closed` / `phase-closed` | SP0–SP8 均未关闭 |

`shadow-only` 不是实现深度。已测的离线编译器仍然是 shadow：可以计算和展示，不改变
调度许可，不声称安全资格。`hardware-qualified` 需要现场标定、停止模型、碰撞几何和
联合审核；当前为零。

截至本文：

- **已完成并测试**：输入摘要与门禁、坐标/运动学投影、投料站 Demo Workflow、pTLC
  点表/动作/标定输入、静态代理 QC、机器人命令侧 `execution_unknown + Fence` 基础合同，
  空间 shadow 首个可重复运行的**离线纵切**（pTLC 产物 + 投料站 lock-only），以及正式
  Theia Workbench 中读取冻结快照的独立离线 Shadow 审阅器；本轮新增 14 段/522 帧离线
  播放、7 段编译 MoveL 轨迹、工具与 plate payload 随动、候选坐标配准、逐帧环境 AABB
  距离和生成盒体 SAT 精检；此前已有 4 段连续保守 link AABB、自碰撞 broad-phase 候选、
  OS 同步派发前 Shadow 准入端口，以及默认关闭/故障即拒绝的空间硬件互锁适配器；
- **schema-frozen-v0**：十份本地 JSON Schema 草案及其已生成实例，当前均待提交；绑定面
  以 schema 为准，不以正文愿望清单为准；
- **design-frozen**：失败关闭规则、已绑定摘要漂移后的证书身份重算规则、shadow 不改变派发、
  Workbench 不授予许可、走廊的名义扫掠公式；
- **design-intent**：通用 MotionContract、有界 Stop/Recovery 算法、OS 持久 decision store、
  uncertainty 签署预算、enforced 决定；
- **已部分实现**：两样例摘要锁、pTLC 静态候选 collision scene、tank1 waypoint
  提取、7-link FK/link-state、14 段诊断播放、动态工具/plate attach、逐播放帧环境代理碰撞、
  4 段 `move_j/cp=0` 自适应离散 AABB 走廊与连续保守宽相候选，以及结构化
  `unknown / effect=none` 证书与决定；Workbench 可播放 35.83 s 轨迹并显示距离、首次接触
  时间/位置、XY/XZ AABB/连续包络投影、未覆盖原因和摘要，但不进入 Pascal 主场景；OS Shadow 结果目前经
  可注入 recorder 输出，尚无正式持久表或 Workbench runtime 流；
- **尚未实现**：静态 proxy 世界与 full-machine glTF 世界的现场审核合格注册、CP blend 与
  `move_j` 控制器精确插补、原始 CAD/非盒体网格窄相、严格连续的 link-vs-environment
  首次接触求解、允许接触对和有符号最小距离、Stop/RecoveryEnvelope、
  动作冲突矩阵、OS shadow decision 持久化，以及由 `WorkCellActivation` 绑定的 Pascal
  corridor/stop/conflict overlay；
- **尚未具备**：任何强制空间互锁或真机安全放行。

### 0.1 2026-08-28 初始实施回填

本节保留初始纵切的历史计数；当前实现与测试口径以 §0.7 v8 和 §9.0 为准。

SP0 的首个纵切已经实现并测试，但尚未达到 SP0 整阶段关闭条件：

- 八份 v0 JSON Schema：test lock、collision scene、MotionContract、link-state sequence、
  partial MotionCorridor、continuous-collision candidate、certificate、decision；
- 两个样例共 27 个输入文件的确定性摘要锁，其中包括投料站 283,695,812-byte GLB 的
  bytes/SHA（大文件本身不进 Git 权威，见 §9.4）；
- pTLC 15 个静态/存储态 simulation proxy 的 Z-up 候选 collision scene；
- `robot_tank_pick(tank_id=1)` 在 P1 锚点、rail slot 5 settled 之后的 14 个机器人
  waypoint 和 2 个 tool-state；
- 一个结构化 `unknown / effect=none` shadow certificate/decision；
- 路径逃逸、重复角色、输入漂移、Z-up yaw/AABB、Schema 正负例、CR5 FK/mesh/rail、
  P11 stale-joint 拒绝、部分走廊边界、连续包络覆盖性质和 Workbench 快照导出的 17 项空间定向/合同测试；
- `compile_spatial_shadow.py --check` 通过，根仓 `unittest discover -s tests -v`
  为 43/43 通过。

因此：

- SP0 = `implemented-and-tested`（slice）+ `schema-frozen-v0`（窄面）+ `phase-not-closed`；
- SP1 = `partial`：15 个静态代理仍在任意原点 proxy world；7 个 CR5 link 已从锁定
  URDF/mesh 发布候选 FK/AABB，但位于另一套 full-machine glTF-Z-up frame，尚未合格注册；
- SP2 = `partial`：14 waypoint link-state 已生成，4 段 `move_j/cp=0` 已自适应采样并形成
  `candidate-partial` corridor；同 4 段已形成保守连续 link AABB 与非相邻连杆自碰撞
  broad-phase（60 个 pair-segment 结果中 27 个 overlap candidate、33 个保守分离）；
  `move_l`、CP、工具/板、环境碰撞与窄相仍未闭合，合同保持
  `unresolved`；
- SP4 = `partial`：独立离线 Workbench Shadow 审阅器已实现并测试；它读取工作区冻结
  快照并显示连续包络/自碰撞候选，不进入 `WorkCellActivation` 或 Pascal 主场景，也不写 runtime claim；
- SP5 = `partial`：OS 已在既有同步 pre-dispatch 边界消费显式 `spatial_admission` 绑定；
  Shadow 先记录后派发，任何 v0 `enforced` 请求均在设备适配器前失败关闭；尚无正式
  decision store、world snapshot 服务或默认生产装配；
- SP6 = `partial-foundation`：机器人模板已有 Claim/Fence/PhysicalSettlement 基础；本轮新增
  默认关闭的独立空间 PLC 许可适配器和类型/过期/断连故障注入，尚未绑定现场节点、停止距离
  或真实安全链资格。
- 投料站本轮 = `lock-and-fail-closed-fixture-only`，**不是**与 pTLC 对称的空间纵切。

动态工具/plate attach、完整轨迹插补、环境/窄相碰撞、StopEnvelope、OS 持久 admission 和
Activation/Pascal 场景叠加仍未实现。详见
[初步开发报告](./2026-08-28-spatial-shadow-initial-development-report.md)。

当前本地冻结、待提交的 v0 草案实例是生成物，不是 §4.4 的愿望字段表。本文仍是
`implementation-authority-draft/v8`；下列 schema、编译器、测试和生成物目前均为本地
未提交修改，不能称为“已签入”或“已发布权威”。本地实现审阅以这些文件为准：

- `schemas/motion-contract-v0.schema.json`
- `schemas/spatial-collision-scene-v0.schema.json`
- `schemas/spatial-link-state-sequence-v0.schema.json`
- `schemas/spatial-playback-trajectory-v0.schema.json`
- `schemas/spatial-environment-collision-v0.schema.json`
- `schemas/motion-corridor-v0.schema.json`
- `schemas/continuous-collision-candidate-v0.schema.json`
- `schemas/spatial-occupancy-certificate-v0.schema.json`
- `schemas/spatial-interlock-decision-v0.schema.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-motion-contract.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-link-states.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-playback.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-environment-collision.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-motion-corridor.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-continuous-collision.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-spatial-certificate.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-shadow-decision.json`
- `scripts/export_spatial_workbench_snapshot.py`
- `tests/test_spatial_workbench_snapshot.py`
- `pTLC_platformUI/.unilab/spatial-shadow/current.v0.json`
- `uni-lab-fe/packages/spatial-diagnostics/`
- `uni-lab-fe/packages/workbench-theia/src/browser/workbench-spatial-shadow-source.ts`

### 0.2 v3 相对 v2 的合同收窄

v3 不改变当前代码行为，只纠正文档越权：

1. `lab.motion-contract/v0` 降为 **pTLC waypoint 投影**，不再称为通用合同；
2. 证书 v0 只绑定 `test_lock` / `collision_scene` / `motion_contract` 三个 digest；
3. Stop/Recovery 从 `design-frozen` 降为 `design-intent`；
4. Workbench 正常主场景只加载 `WorkCellActivation`；
5. SP2 关闭线改为只验收 `move_j` FK；`move_l`/CP 保持 `unknown`；
6. SP4 先做离线证书投影；断流/陈旧许可放到 SP5 之后；
7. 投料站本轮改称 lock-only fixture。

### 0.3 v4 合同审阅修订

v4 保持 draft 身份，并把当前本地实现与未来目标拆开：

1. 所有 spatial schema、编译器、测试和生成物均称为“本地冻结草案/待提交”，不再误称
   “已签入”或“已发布权威”；
2. certificate v0 的 `qualification` 固定为 `candidate`，不能表达碰撞或硬件资格；
3. shadow 可记录 `allowed / blocked / unknown` 假设分类，但 `effect` 恒为 `none`，其中
   `allowed` 不等于放行；
4. v0 摘要漂移的现有能力只到“重新编译改变证书身份”；运行时拒绝旧证书尚未实现；
5. 通用 MotionContract v1 统一为 `design-intent` + candidate 字段表；
6. 跨平台规范化产物禁止携带环境相关绝对路径。

### 0.4 v5 SP1/SP2 候选实现回填

v5 增加可重复计算结果，但不提升任何安全资格：

1. TestLock 新增 rig map、rail 点表和 tank1 已编译片段，共锁定 pTLC 20 个、投料站
   7 个输入；
2. 编译器逐项核对锁定 CR5 URDF 与 calibration 的 6 轴 parent/child、origin、axis，读取
   7 个 binary STL（40,764 triangles，原生单位为米）的局部 AABB；
3. 对 P1 + tank1 14 waypoint 输出 15 个确定性 link-state，每态含 7 个 link 的
   `matrix_link_to_world` 和 broad-phase AABB；Tool 1 FK 对控制器 TCP 的 15/15 位置残差
   均不超过 1 mm，最大为 0.297713 mm；
4. P11 已知旧 joint 与 pose 相差 22.399515 mm，现会拒绝旧 joint，并引用已锁编译片段的
   `move_l` 软件求解终点；该值不是重新示教的真机 joint；
5. slot 4=500 mm 到 slot 5=600 mm 按 rig map `axis=[1,0,0], sign=-1` 产生
   `[-0.1,0,0] m` 位移；输出 frame 是 `ptlc.full-machine-gltf-z-up-candidate`，不是
   15 个静态代理所在的 `ptlc.rail_constraint_layout_v2`；
6. 14 个运动段中仅 4 个 `move_j/cp=0` 以最大单轴步长 5° 自适应离散采样；3 个带 CP
   的 `move_j` 和 7 个 `move_l` 明确排除，生成物为 `candidate-partial`，离散 AABB 并非
   连续扫掠体；
7. certificate v0 仍只绑定 lock/scene/motion 三摘要，所以不把新增 corridor 写成已绑定
   `candidate` 状态；reason code 明确记录“部分走廊未被 v0 证书绑定”和“两套 world 未注册”。

因此本轮是 FK、动态 link IR 和部分走廊的实现证据，不是 link-vs-environment 碰撞结果。

### 0.5 v6 SP4 离线 Workbench 审阅器回填

v6 把现有离线证据投影到正式 Theia Workbench，但没有改变资格边界：

1. `export_spatial_workbench_snapshot.py` 从 collision scene、link-state、partial corridor、
   certificate 和 decision 生成单一 canonical JSON；导出时校验样例、frame、摘要、状态数、
   段数和 `unknown / shadow / effect=none`，并支持 `--check` 字节一致性门禁；
2. 当前 EIT 快照写入 `pTLC_platformUI/.unilab/spatial-shadow/current.v0.json`，含 15 个状态、
   每态 7 个 link AABB、14 个运动段、4 个已采样候选段和 10 个未覆盖段；
3. 新增 `@unilab/spatial-diagnostics` 严格解析器和 React 审阅组件；解析器重新计算快照
   digest，拒绝 schema、计数或摘要不一致，不提供 demo fixture 回退；
4. Workbench 新增“空间约束”入口，显示四步计算说明、覆盖统计、XY/XZ AABB 投影、状态/
   运动段选择、未覆盖原因、证书边界和 TCP 残差；
5. UI 明示“结论未知：禁止据此放行”与“不是 WorkCellActivation”，且不调用 OS admission、
   不写 runtime claim、不改变调度；
6. 已完成包级 9/9、Theia 143/143、根仓 41/41、正式开发构建和专项 Playwright E2E
   1/1；截图经人工检查。该证据只证明离线审阅器真实可见，不证明 Pascal 3D overlay、
   动态碰撞、停止包络或硬件资格。

### 0.6 v7 连续候选、OS Shadow 准入与硬件互锁基础回填

v7 沿用 `unknown / shadow / effect=none`，新增的是三条可运行但仍未获硬件资格的纵切：

1. 新产物 `lab.continuous-collision-candidate/v0` 只处理 corridor 已允许的 4 个
   `move_j/cp=0` 段。每个 5° 上限子区间从起点 link AABB 出发，按所有上游关节的
   `半径上界 × |Δq|` 路程和做各向同性膨胀；该包络对声明的线性关节插值是保守上界，
   但控制器尚未验证会严格执行该插值。
2. 每段检查 15 对非相邻连杆。当前 4 段共 60 个 pair-segment 结果，其中 27 个
   `candidate-overlap`、33 个 `separated-by-conservative-aabb`。AABB overlap 只进入后续
   窄相候选，不等于真实碰撞；相邻连杆接触未评估。
3. 0.25° 细化 FK 回查已验证所有样本 AABB 均落在发布的保守包络内；跨 frame 输入会
   失败关闭。因为静态 proxy 与机器人仍未完成合格刚体注册，环境碰撞仍为
   `not-evaluated-frame-unregistered`，certificate v0 也没有绑定这份新产物。
4. Uni-Lab-OS 新增 `SpatialAdmissionGate`，由现有 `TaskSchedulerBridge` 在同步
   pre-dispatch 回调中调用。动作参数必须精确绑定 action contract、decision digest 和
   world snapshot；Shadow 证据漂移记录为 `unknown/effect=none` 后继续历史派发，任何
   `enforced` 请求均在标准派发意图和设备适配器之前拒绝。该端口可从 composition root
   注入，但当前没有正式 SQLite decision store、任务 attempt 绑定或生产默认配置。
5. `unilab_robot_template` 新增 `SpatiallyGuardedInterlockProvider`。它把既有运动互斥 PLC
   链与独立空间 PLC grant 做逻辑与，默认 `enabled=false`；字符串布尔、数字、读取异常、
   TTL 过期、非硬件来源或缺少 64 位资格摘要全部返回 UNKNOWN 并撤销 rail/arm 许可。
   只有两条经验证硬件链同时为真才保留相位许可；当前未配置现场变量，也未做停止距离、
   PLC 程序或真实设备试验。
6. Workbench 快照现在绑定第八份 continuous artifact，显示 4 个连续包络段、27 个聚合
   自碰撞候选对和橙色虚线保守包络。包级 9/9、Theia 143/143、根仓 43/43、OS 相关
   34/34、机器人安全相关 41/41、正式 Workbench 构建和 Chrome E2E 1/1 通过。截图：
   `output/spatial-shadow-workbench/eit-spatial-continuous-workbench.png`。

旧 v6 段落中的 41/41 与“连续碰撞未实现”是当时基线；以本 v7 回填和 §9.0 为当前状态。

### 0.7 v8 全轨迹播放、随动附件与环境代理碰撞回填

v8 完成用户要求的“离线空间约束计算结果查看器”下一纵切，但仍不把它称为完整物理
仿真器或真机安全求值器：

1. 新产物 `lab.spatial-playback-trajectory/v0` 把 tank1 的 14 个运动段编成 35.83 s、
   522 帧的统一离线时间轴。7 个 MoveL 段直接消费已锁 `compiled.moveLTrajectories`，
   共 318 个编译轨迹帧；7 个 MoveJ 段使用名义 joint 插值。4 个带 CP 的段可播放，但
   明确标记 `nominal-controller-unverified`，没有假装还原控制器 blend/wrap 语义。
2. `TOOL_SUCTION` 按 `physical_tool_mount` 随 Link6 运动；吸取动作之后，
   `deepwell_24_10ml` 尺寸的 plate payload 以 Tool 1 TCP 接触面候选姿态随动，共 238 个
   payload-attached 帧。两者都是诊断代理几何，不是现场标定后的 collision model。
3. 新产物 `lab.spatial-environment-collision/v0` 使用既有 rail L/N 拟合、slot 5=600 mm 与
   rail-top 接触建立 `candidate-relative-layout`。它把机器人、工具和 payload 变换到
   `ptlc.rail_constraint_layout_v2`，但 `world_rigid_transform_qualified=false`；配准不是
   测量/审核完成的世界刚体标定。
4. 522 个播放帧均计算 moving-object ↔ environment component 的 AABB 距离下界。10 类
   已锁生成盒体 STL 被拆为 61 个连通 component，并用机器人/附件三角形对盒体做 SAT
   精检；其余 4 个 shaped proxy component 只保留宽相，不把重叠写成确证碰撞。
5. 当前候选结果为 204 个 `proxy-mesh-contact` 帧、189 个
   `broad-phase-overlap-unresolved` 帧、129 个采样分离帧，共 220 个代理接触事件。首次
   代理接触位于 6.768636 s、segment 2/frame 14，`tool:TOOL_SUCTION` 对
   `ptlc.proxy:develop_tank_rack:component:7`，候选位置为
   `[0.790000, -0.223098, 1.599918] m`。这是候选配准和代理盒体下的诊断结果，不是“真机
   必撞”结论。
6. Workbench 快照现在绑定 playback 和 environment-collision 两份新产物，并把端点、
   播放帧、附件和 corridor AABB 统一投影到 proxy layout frame。UI 提供播放/暂停、时间
   拖动、0.5/1/2 倍速、MoveL/CP fidelity、逐帧距离、碰撞对象、首次接触时间/位置、红色
   接触高亮，以及随动工具/payload 图层。
7. 当前本地验证：空间定向/合同测试 18/18、空间前端包 9/9、Theia 143/143、正式
   Workbench build 0 errors、真实 Chrome 专项 E2E 1/1。E2E 验证播放时间前进、MoveL
   段可选、payload 图层存在、6.77 s 代理接触点可见，同时根元素保持
   `decision=unknown / mode=shadow / effect=none`。截图：
   `output/spatial-shadow-workbench/eit-spatial-playback-payload-workbench.png` 与
   `output/spatial-shadow-workbench/eit-spatial-playback-collision-workbench.png`。

旧 v7 及更早段落中的“MoveL/工具/payload/环境碰撞未实现”描述是当时基线；当前状态以
本 v8 回填、§9.0 和生成产物为准。合格配准、连续时间碰撞、原始 CAD/非盒体精检、停止
包络和硬件资格仍未完成。

## 1. 项目目标与非目标

### 1.1 总目标

建立一条证据驱动、格式中立、跨 Windows/Mac 可复现的通用资产管线。空间编译器消费的
是已编译产物，不是源 CAD 节点名或 Workbench GLB：

```text
CAD / URDF / 控制点表 / 标定 / operation / workflow
                         │
                         ▼
       SourceRelease + 稳定身份 + Canonical Mechanical IR
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
 FamilySimBundle   DeployManifest    MotionContract
          │         PointSet/          （通用合同 = v1 目标；
          │         ProgramSet          v0 仅为 pTLC 投影）
          └──────────────┴──────┬───────┘
                                ▼
                      WorkCellActivation
                                │
                    Spatial Certificate Compiler
                                │
          ┌─────────────────────┼────────────────────┐
          ▼                     ▼                    ▼
  Workbench 诊断投影     OS shadow/admission   可复现证据与回归
```

最终产品不是一个 GLB，而是三类可独立验收的产品：

1. **可复用机械资产**：渲染、拾取、机械拓扑、碰撞候选和稳定身份；
2. **可执行部署描述**：设备实例、安装关系、点表、工具、库位、标定和控制绑定；
3. **空间证据与准入**：运动走廊、停止/恢复包络、冲突约束和版本绑定的决定。

### 1.2 明确非目标

- 不从视觉网格自动猜测安全区、关节、TCP、物料身份或工艺因果；
- 不让前端、GLB 节点或动画播放器授予执行权；
- 不把离散关键帧无碰撞写成连续轨迹安全；
- 不把历史实机点表写成当前现场标定仍有效；
- 不用软件空间互锁替代 PLC、机器人控制器、急停和经过认证的硬安全链；
- 不把 pTLC operation YAML 或控制器原始六元组当成 Canonical IR 位姿；
- 不把 v0 shadow decision schema 扩成 `enforced`。

## 2. 两个纵向测试样例

### 2.1 样例 A：投料站——通用管线和失败关闭样例

当前可用证据：

- Windows P1 handoff 已由 Mac 独立验证为 `source-input-validated`；
- 2021 个 occurrence、25 个顶层根；
- Agent/编译器自动生成 53 条 decomposition 规则，达到 2021/2021 唯一覆盖；
- GCR5-910 SourceRelease、6 轴运动学 Provider 和 CAD comparison pose 已锁摘要；
- 正常 Workbench 主场景已显示整站、导轨、GCR5 运动层和 4 ml 演示瓶；
- 标准 WorkflowTask 六步模拟运行结果为 6/6 Job succeeded；
- 坐标合同已统一为源 CAD Z-up、GLB/Pascal Y-up、UniLab Material Graph Z-up。

权威证据见：

- [投料站 Workbench 验证报告](./2026-08-28-feeding-station-unilab-workbench-preview-report.md)
- [GCR5 自动分解报告](./2026-08-28-feeding-station-gcr5-automation-report.md)
- [投料站待决策台账](./2026-08-28-feeding-station-pending-decisions.md)

本样例的空间测试定位：

- **当前（SP0）**：只锁定 7 个输入并验证摘要漂移失败关闭；不生成 collision scene、
  MotionContract 或样例专属证书；
- **SP7 目标**：用**通用** MotionContract 编译 Demo 六步，得到 candidate 走廊和结构化
  `unknown`；不得依赖 pTLC 字段名。在通用合同 schema 正式提交前，SP7 不得提前关闭；
- 可展示的 Demo 走廊永远不得标记为碰撞合格；
- P2/W2、GCR5 厂家限位、TCP、真实轨迹和碰撞几何未批准前，决定只允许 `blocked` 候选
  或 `unknown`，不得出现 `allowed`；
- 后期用于验证从候选/影子模式升级到已批准部署时，摘要变化后的重新编译是否改变证书
  身份，以及运行时是否明确拒绝旧证书；后一个拒绝机制当前尚未实现。

### 2.2 样例 B：EIT pTLC——历史实机模型与空间算法黄金样例

当前可用证据：

- 74 条控制器原始点；239 个语义点，其中 235 个标记 `validated`、4 个 placeholder；
- 点表 SHA、CR5 运动学 commit、现场标定版本、地轨工位和工具变换闭合；
- 117 个 operation YAML，其中 28 个机器人操作；274 个动作/流程片段；
- `robot_tank_pick` 等脚本显式给出 `move_j/move_l`、点位、速度、加速度、CP、
  地轨和工具阶段；
- `parallel_v1` 提供 12 段 DAG、两个明确并行对和 `scrape-holder` 跨段占用；
- 已有 15 个 watertight 碰撞代理及静态布局 AABB QC，当前报告明确不是连续碰撞认证；
- 动作映射显式保留 8 个 unresolved action，可作为 `unknown` 失败关闭黄金样本。

关键输入：

- [机器人点表](./pTLC_platformUI/eit_ptlc/config/points/robot/robot_points.json)
- [语义点表](./pTLC_platformUI/eit_ptlc/three_d/generated/robot-points.json)
- [CR5 标定](./pTLC_platformUI/eit_ptlc/three_d/pipeline/calibration/cr5_ptlc_v1.yaml)
- [动作—机构映射](./pTLC_platformUI/eit_ptlc/three_d/generated/action-motion-map.json)
- [展缸取板脚本](./pTLC_platformUI/eit_ptlc/config/operation/06_robot/robot_tank_pick.yaml)
- [并行流程黄金样本](./pTLC_platformUI/eit_ptlc/config/recipes/parallel_v1.yaml)
- [现有静态布局 QC](./related/unilabSZlab/pTLC仿真资产/layout_collision_qc.json)

这些文件今天是离线编译器的 adapter 输入，**不是**运动权威。权威目标仍是部署层
PointSet/ProgramSet + 标定 + 厂家 URDF。没有独立 PointSet digest 时，MotionContract
必须保持 `unresolved`，不得把 YAML 点名写成已发布 PointSet。

本样例的空间测试定位：先实现和验证离线/影子空间编译器，再把通用实现应用到投料站。
历史点位和标定只构成 `historical-as-built-shadow`，不是当前硬件资格。

## 3. 权威分层与仓库职责

| 层 | 权威内容 | 主要仓库 |
|---|---|---|
| Source | CAD/URDF 原始文件、occurrence、摘要、许可来源 | 根仓 handoff、`vendor/`、SourceRelease |
| Family | 家族级 visual、link/joint、collision candidate、稳定 ID | 根仓管线、`unilab_robot_template` |
| Deployment | 设备实例、安装、PointSet、Tool/Payload、Site、标定 | `Uni-Lab-OS` 领域/工作区包 |
| Motion | 动作阶段、轨迹模板、控制参数和中断规则 | DeployManifest 的 PointSet/ProgramSet；通用 MotionContract 为 v1；pTLC operation YAML 只是 adapter |
| Spatial | 走廊、停止/恢复包络、冲突和证书 | 短期：根仓 `scripts/compile_spatial_shadow.py`；中期：管线包，只被 OS admission 与 Workbench 投影消费 |
| Runtime | WorkflowTask、attempt、Claim/Fence、世界快照、决定 | `Uni-Lab-OS` |
| Projection | 资产、遥测、回放和空间诊断显示 | `uni-lab-fe` Workbench，且只加载 `WorkCellActivation` |

不可变规则：

1. 家族资产不能包含部署实例的 base pose、现场 PointSet、TCP、`device_id`、Site UUID
   或物料占用事实；
2. visual mesh 默认不能充当合格 collision；
3. 机器人运动学只来自厂家 URDF/Xacro，禁止用手写 `rig_map` 或 SolidWorks mate 生成臂关节；
4. 示教点进 PointSet，程序号进 ProgramSet，现场关节进遥测；不得互相伪造；
5. motion preview 不是 RobotCommand，也不是执行许可；
6. 空间求值器只产生证据/ClaimIntent，OS 才能原子取得 JobExecutionClaim；
7. 正常 Workbench 主场景只加载 `WorkCellActivation`。空间图层只投影 activation 已引用
   的证书/走廊。没有 activation 时只允许离线审阅器，不得把散落 GLB 或证书路径送进主场景；
8. Workbench 只显示决定和证据，不改变决定，也不重新计算许可；
9. 任何已绑定输入摘要、frame graph 或 action revision 漂移都必须触发重新编译并产生
   新的证书身份；运行时选择器/验证器最终必须拒绝旧证书，当前 v0 尚未实现该拒绝机制；
10. 没有合格扫掠时空间互锁必须返回 `unknown`，禁止写成「未发现碰撞」。

### 3.1 相对 08-23 家族管线的 delta

08-23 文档仍是 SourceRelease、Canonical IR、FamilySimBundle、DeployManifest、
WorkCellActivation 的权威。本文只做这些增量，不另起一套家族包：

| 主题 | 08-23 | 本文 |
|---|---|---|
| Canonical IR | 已定义；单位米、弧度、四元数 | 沿用。本文不「新增 IR」，只要求空间产物引用 IR/bundle digest |
| FamilySimBundle 目录 | `collision-static.glb` / `collision-dynamic.glb` / `attachments.json` | 继续作为合格槽位。`collision-candidates/` 是未签署候选目录，**不得**占用合格槽位 |
| `capability.json` | 枚举 `visual-only` → `semantic-scene` → `kinematic-preview` → `collision-qualified`（执行另见资格记录） | 增加独立布尔项，必须能映射回枚举；布尔项不得单独升格 |
| 点位 | 部署层 PointSet/ProgramSet | 空间编译器最终只消费 PointSet/ProgramSet digest。v0 暂时从 pTLC YAML 投影，并保持 `unresolved` |
| Workbench | 只加载 WorkCellActivation | 重申；空间 overlay 同样受此约束 |
| 空间互锁 | 无合格扫掠则 `unknown` | 具体化为证书/decision 合同和 SP 关闭线 |

布尔项到枚举的映射：

```text
render                         ⊂ visual-only
render + picking               ⊂ semantic-scene
+ kinematic_preview            ⊂ kinematic-preview
collision_candidate            不等于 collision_qualified
collision_qualified            ⊂ 08-23 collision-qualified
spatial_shadow_eligible        新轴；candidate 几何也可为 true
spatial_interlock_enforced     独立于 collision_qualified；当前必须 false
hardware_execution             对应执行资格记录；当前必须 false
```

这些能力不得因 GLB 能显示而自动升级。`spatial_shadow_eligible=true` 只表示允许进入
离线/影子编译，不表示碰撞合格。

## 4. 项目级产物合同

### 4.1 SourceRelease 与 Canonical Mechanical IR

现有 SourceRelease/handoff 继续负责只读摄取、摘要、完整性和跨机交接。Canonical
Mechanical IR 以 08-23 为准，把 CAD、URDF、GLB 和后续 USD 的共同事实统一为：

- `entity_id / occurrence_id / link_id / joint_id / frame_id`；
- 父子层级、局部变换、单位和坐标约定；
- visual、collision candidate、reference-only、site candidate 等几何角色；
- 关节类型、轴、原点、限位和来源资格；
- 工具、载荷、attach frame 和允许接触对；
- 每一字段的来源、摘要、自动推断状态和人工批准状态。

位姿采用双轨，禁止混用：

1. **IR / 证书 / 走廊发布态**：必须带 `frame_id + convention + unit`；单位米、弧度、
   四元数；禁止跨产物传递无 frame 的裸 `[x,y,z]`；
2. **控制器审计态**：允许保留厂家原始 mm/deg 六元组，但必须留在明确命名的审计字段
   （例如 v0 的 `joint_deg`、`tcp_pose_controller`），并记录 `tool` / `user` 索引。
   审计字段不是 IR 位姿，FK/走廊计算前必须经已锁定运动学变到发布态。

v0 collision scene 的 `pose_world.xyz_m` + `rpy_deg` 依附场景级
`world_frame`（`frame_id`、`units=m`、`up_axis`、`handedness`）。这是场景发布态，
仍须带着 world frame；它不使控制器六元组合法化。

### 4.2 FamilySimBundle

沿用 08-23 家族包，至少包含：

```text
bundle.json
source.json
provenance.json
entity-registry.json
frame-graph.json
mechanics.json
geometry-roles.json
attachments.json          # 家族局部法兰/插槽帧，不含现场 TCP
render-lod0.glb
collision-static.glb      # 可空；缺则显式 missing，不得用 render mesh 填
collision-dynamic.glb     # 同上
collision-candidates/     # 未签署候选；空间 shadow 可引用
capability.json
reports/
```

禁止出现的字段仍是：`base_pose`、`tcp`、`point_table`、`device_id`、`site_uuid`、
`current_joints`。

### 4.3 DeployManifest / WorkCellActivation

部署层把家族绑定到真实或历史场景：

- device/site/material 稳定身份；
- 安装父 frame 和 base transform；
- PointSet/ProgramSet、rail target、tool/TCP、payload/CoM；
- calibration revision、controller/adapter revision；
- active collision revision 和现场忽略对；
- 当前允许的模式：preview、simulation、shadow 或 enforced。

`WorkCellActivation` 是 Workbench、空间互锁和真实执行的唯一场景入口。工作流任务提交
时冻结 activation ID。执行中禁止切到「最新资产」。空间编译器的中期目标是只消费
activation 已钉扎的 bundle/PointSet/collision/motion digest；v0 离线编译器暂从
TestLock 路径读取，这是过渡，不是目标架构。

### 4.4 MotionContract：通用目标 vs pTLC v0 投影

每个会产生机械运动的 action revision 必须是：

1. `resolved`：有可复算轨迹/状态序列；
2. `known-no-motion`：已证明无机械运动；
3. `unresolved`：缺参数、运行时生成或控制器内部路径，求值返回 `unknown`。

#### 4.4.1 通用合同（v1 目标，`design-intent` + candidate 字段表，schema 未提交）

工作术语仍叫 MotionContract。以下只是待审阅的 candidate 字段表，不是已冻结合同；
在对应 schema 正式提交并通过负向测试前，不得声称 `lab.motion-contract/v0` 已经实现它们：

```json
{
  "schema": "lab.motion-contract/v1",
  "action_contract_id": "robot.tank.pick",
  "revision": "sha256:...",
  "selector": {"tank_id": 1},
  "phases": ["approach", "acquire", "transfer", "release", "retreat"],
  "actors": ["robot-main", "rail-11y"],
  "tool_ref": {"family_attach_frame": "flange", "deploy_tool_context_digest": "..."},
  "payload_variants": ["empty", "plate"],
  "trajectory_source": {
    "kind": "pointset-sequence",
    "pointset_digest": "...",
    "operation_digest": "..."
  },
  "resolution": {"status": "unresolved"},
  "interrupt_policy": "hold-and-reconcile",
  "recovery_refs": []
}
```

每个 phase 可以切换工具/载荷几何、允许接触对和 Site/Material 业务足迹。投料站 Demo
六步必须能映射到这一形状，而不是 `move_j` / `rail_slot` / `joint_deg`。

#### 4.4.2 本地冻结、待提交的 v0：pTLC waypoint 投影

`lab.motion-contract/v0` Schema 当前是本地冻结草案，尚未被 Git 跟踪或提交。它是 pTLC
控制器脚本的确定性投影；当前本地生成实例为
`artifacts/spatial-shadow/v0/ptlc-tank1-motion-contract.json`。

首个生成实例 `robot.tank.pick(tank_id=1)`：14 个机器人 waypoint 和 2 个 tool-state
已解析，但因控制器插补、CP、连续碰撞和停止模型未闭合，合同整体仍为 `unresolved`。
这验证了投影器和解析器，不等于轨迹或走廊已经解析，也不等于通用合同已落地。

v0 实际形状（字段以 schema 为准）：

```json
{
  "schema": "lab.motion-contract/v0",
  "sample_id": "eit-ptlc-historical-v1",
  "action_contract_id": "robot.tank.pick",
  "selector": {"tank_id": 1},
  "mode": "shadow",
  "analysis_scope": "robot-arm-after-anchor-and-rail-settle",
  "source_digests": {
    "robot-calibration": "...",
    "robot-points": "...",
    "tank-pick-operation": "..."
  },
  "preconditions": [
    "robot-anchor:P1",
    "rail-slot:5-settled",
    "controller-tool:1",
    "operation-prologue-and-rail-motion-excluded-from-this-scope"
  ],
  "resolution": {
    "status": "unresolved",
    "waypoint_sequence_resolved": true,
    "unresolved_reasons": [
      "controller-interpolation-unresolved",
      "cp-blend-unresolved",
      "continuous-collision-not-computed",
      "stop-model-missing"
    ]
  },
  "steps": [],
  "terminal_facts": {
    "payload_state": "plate-attached",
    "robot_anchor_expected": "P1"
  }
}
```

`steps[]` 只有 `tool-state` 与 `robot-motion`。`robot-motion` 携带控制器审计量：
`joint_deg`（度）、`tcp_pose_controller`（毫米 + 度六元组）、`tool`、`user`、
`rail_slot`、`vel`、`acc`、`cp`。这些字段**没有** `frame_id + convention + unit`，
因此不得直接进入走廊几何。SP2 的 FK 必须用厂家 URDF + 标定把它们变到 IR 发布态。

v0 不能表达投料站 Demo 六步。SP7 的前置是 v1 通用 schema，或一条经测试的 v0→通用
映射层；在此之前投料站保持 lock-only。

### 4.5 Schema 版本与编译器归属

| 产物 | v0 能表达 | v0 不能表达 | 升级规则 |
|---|---|---|---|
| MotionContract | pTLC waypoint 投影、`mode=shadow` | 通用 actor/phase/PointSet 源、投料站 Demo | 并行提交 v1，不改 v0 const |
| CollisionScene | 静态/存储态 proxy AABB、`simulation-proxy-only` | 合格动态 link 窄相 | 合格几何另开 qualification，不把 proxy 升格 |
| LinkStateSequence | full-machine glTF-Z-up candidate frame 中的 7-link waypoint FK/AABB | 与 proxy world 的合格注册、动态工具/载荷、现场 CR5A 等价性 | 保持 `qualification=candidate`，跨 world 注册闭合前不做环境碰撞 |
| MotionCorridor | `move_j/cp=0` 离散自适应采样的 `candidate-partial` AABB union | `move_l`、CP、连续扫掠、工具/载荷、碰撞资格 | 未覆盖 segment 显式 `excluded-unresolved`，不得补伪轨迹 |
| Certificate | 三 digest + `qualification=candidate` + shadow 分析分类 + reason_codes；当前实例为 `unknown` | collision/hardware 资格；family/PointSet/uncertainty/stop/algo 独立绑定 | v0 qualification 固定为 `candidate`，不得升格；缺项用 reason_codes/`missing` 状态 |
| Decision | `mode=shadow`、`effect=none`、`allowed/blocked/unknown` 假设分类、`offline-lock:<digest>` | `enforced`、实际放行、真实 world snapshot | `allowed` 也只是无副作用的假设结果；**禁止**把 v0 const 改成 enforced；SP8 用新 schema |

短期编译器：根仓 `scripts/compile_spatial_shadow.py`，只写
`artifacts/spatial-shadow/v0/`。当前函数名为 `compile_ptlc_*`，这是诚实的实现状态。

中期归属：管线包内的 Spatial Certificate Compiler。OS admission 与 Workbench 投影
只消费其输出。前端不得重算走廊或许可。

## 5. 空间约束自动计算设计

### 5.1 输出术语

- **MotionCorridor**：名义轨迹的所有 link/tool/payload 扫掠体，加误差膨胀；
- **HoldEnvelope**：在已知静止状态下可能占据的空间；
- **StopEnvelope**：任一时刻请求停止后，在响应和制动上界内仍可能占据的空间；
- **RecoveryEnvelope**：从已证明停止状态到批准恢复状态的扫掠体；
- **SpatialOccupancyCertificate**：固定输入摘要和算法版本下的不可变空间证据；
- **SpatialClaimIntent**：一次具体 action attempt 请求的业务与空间占用；
- **SpatialInterlockDecision**：`allowed / blocked / unknown` 及可解释原因；
- **SpatialResource**：部署级稳定区域/通道/容量，不等同于 SiteOccupancy。

决定词只使用 `allowed` / `blocked` / `unknown`，不使用 `model_allowed`。shadow 模式允许
记录这三种**假设分类**，但 `effect` 必须恒为 `none`；其中 `allowed` 只表示“按本次 shadow
输入和算法未发现阻断条件”，绝不代表实际放行、调度许可、碰撞资格或真机安全资格。

### 5.2 输入资格

空间编译器**目标**上只接受摘要闭合的：

1. collision scene 与 geometry qualification；
2. frame graph 和 deployment calibration；
3. robot/axis kinematics；
4. MotionContract 和轨迹参数；
5. tool/payload variant；
6. uncertainty budget；
7. 可选 controller stop model；
8. 算法/引擎版本与确定性参数。

v0 **实际**接受的是 TestLock 内相对路径、角色/路径唯一、bytes/SHA、pTLC
点表—运动学—标定闭合、投料站 receipt 闭合，以及 pTLC 静态代理/QC/layout 一致性。
下列目标输入在 v0 中的状态必须显式为缺失，不能省略成「已经绑定」：

| 目标输入 | v0 状态 |
|---|---|
| 动态 link / 工具 / payload collision | 7 个 CR5 link 已在独立 candidate frame 发布 FK/AABB；尚未并入 scene，工具/payload 缺失 |
| PointSet 独立 digest | 缺失；只有 operation/points 源摘要，合同 `unresolved` |
| uncertainty 签署预算 | 缺失；scene 上的 `uncertainty_m_xyz` 只是诊断估计 |
| stop model | 缺失；`stop-model-missing` |
| 算法/后端版本 | 缺失；未写入证书 |

缺少 visual 不影响空间计算；缺少 collision、frame、trajectory 或摘要一致性必须
`unknown`，不能回退到屏幕中看起来相似的节点。候选 link-state 和部分走廊尚未被 v0
certificate 绑定，也未进入可放行计算；完整轨迹、uncertainty budget 和 stop model 仍缺失。

### 5.3 自动计算流水线

#### S1：场景规范化

当前状态：`partial` × `shadow-only`。已把 pTLC 15 个静态/存储态 simulation proxy 转为
right-handed Z-up meter 世界 AABB；另从锁定 URDF/mesh 发布 7 个 CR5 link 的候选
FK/AABB。两者所在 world 尚未完成刚体注册，不能相互碰撞；末端工具/载荷和 BVH/窄相
后端也未实现。

- 把所有 collision candidate 转到同一部署世界 frame；
- 检查 scale、镜像、NaN、非刚体变换、空网格和重复 stable ID；
- 为静态环境和动态 link 构建 BVH；
- 保留 `entity_id → mesh/component → frame` 的反查链。

#### S2：轨迹解析

当前状态：`partial` × `candidate-link-state-corridor-and-conservative-continuous-envelope`。已从
`robot_tank_pick(tank_id=1)` 提取 P1/rail 前提、14 个 `move_j/move_l` waypoint、2 个工具
状态和 payload phase；已执行 15 个 endpoint state 的 FK，并对 4 个 `move_j/cp=0` segment
按最大单轴 5° 采样。这 4 段还生成了逐区间的保守连续 link AABB，并完成非相邻连杆
self-collision broad phase；它是保守候选计算，不是精确 CCD。`move_l`、CP、控制器
wrap/实际插补、环境碰撞、narrow phase 和最小间隙仍未解析。

目标行为：

- `move_j`：按关节路径和限位解析，禁止只连接 TCP 两端点；
- `move_l`：按笛卡尔路径采样并通过已锁定 IK/FK 得到全链状态；
- 导轨、升降、门、抽屉：按各自 joint/state contract 解析；
- CP/blend：若无法重建控制器实际圆滑路径，诊断采样可以写出，但证书必须
  `unknown(cp-blend-unresolved)`，不得把诊断走廊标成 `resolved`；
- unresolved action：直接产生 `unknown(reason=trajectory-unresolved)`。

采样采用自适应细分：相邻状态的关节角、link 顶点位移或最小间隙变化超过阈值时继续
细分。第一版允许“离散采样 + 采样间保守膨胀”，报告必须写明不是精确 CCD；后续可替换
连续碰撞后端，但不得改变证书上记录的算法身份。

SP2 关闭线见 §7：只把 `move_j` FK 与自适应采样做成可测实现；`move_l`/CP 保持未知。

#### S3：名义运动走廊

当前状态：公式 `design-frozen`；实现 `not-started`；uncertainty 签署预算
`design-intent`。

对动作 `a`、动态实体 `l`：

```text
Corridor(a) = union over t,l of
  Transform(world <- l, q(t)) * CollisionGeometry(l)
  enlarged by Uncertainty(l,t)
```

误差预算目标上至少拆为：

```text
U_total = U_geometry + U_calibration + U_kinematics
        + U_tracking + U_payload + U_sampling
```

各项分别记录来源和批准状态，不能只留下一个无法解释的“安全 margin”。v0 没有该预算
对象；SP1/SP2 关闭不要求数值，但后续 schema 必须出现
`uncertainty_budget_status=missing` 字段或等价 reason_code，禁止静默当作零。

#### S4：停止包络

当前状态：`design-intent` / `not-implemented`。当前证书明确返回
`unknown(stop-model-missing)`。下列并集定义**不是**已冻结算法，只是意图：

```text
StopEnvelope = union of every possible stop trajectory
               from every sampled nominal state
               under max command latency + braking bound
```

有界离散化、延迟/制动单位、控制器字段和签署人未定。在独立算法立项前，v0 只冻结：

- shadow 模式可生成保守诊断，例如剩余名义走廊加大 margin；
- 决定仍为 `unknown(stop-model-missing)`；
- enforced 模式不得用该候选包络放行；
- 故障后相关 Claim/Fence 不得因“已发停止请求”自动释放。

#### S5：恢复包络

当前状态：`design-intent` / `not-implemented`。

恢复不是自动反向播放。只有当停止姿态、工具、载荷、Site/Material 和其他机构状态已
结算，且存在批准 recovery path 时才生成 RecoveryEnvelope；否则
`unknown(recovery-unresolved)` 并等待人工/控制层决定。v0 只冻结这条失败关闭，
不冻结恢复轨迹生成器。

#### S6：冲突与约束编译

当前状态：`design-frozen`（结果分类） / `not-implemented`。既有静态 AABB QC 只是输入
资格证据，不是本阶段的动作—环境或动作—动作求值结果。

宽相按走廊 AABB/BVH 筛选；窄相计算碰撞、最小距离、phase、实体对和时间区间。结果分为：

| 结果 | 处理 |
|---|---|
| 动作走廊撞静态机架 | 轨迹非法，`blocked`；不能靠锁机架放行 |
| 两个动作走廊相交 | 生成 `NoOverlap`、时序或条件约束 |
| 共享容量区域 | 生成 `Cumulative(capacity=n)` 候选 |
| 来源/目标 Site 和 Material | 合并到业务 Claim，不伪造 SiteOccupancy |
| 空 Site 的交互体被穿过 | 生成 SpatialResource/访问约束 |
| 缺建模软管、人工或运行期轨迹 | `unknown` 或人工门 |

离线输出包括：

```text
spatial/collision-scene.json
spatial/motion-contracts/<action>.json
spatial/corridors/<action>/<variant>.json|glb
spatial/stop-envelopes/<action>/<variant>.json|glb
spatial/certificates/<certificate-id>.json
spatial/action-conflict-matrix.json
spatial/reports/<run-id>.json
```

当前 v0 只写出 scene、单一 motion contract、certificate、decision 和 test lock。

### 5.4 证书与失效

`lab.spatial-occupancy-certificate/v0` 本地 Schema 草案和首个 pTLC shadow certificate
已实现但尚待提交。当前本地实例只绑定：

```text
input_digests.test_lock
input_digests.collision_scene
input_digests.motion_contract
```

并记录 `analysis.result=unknown`。没有最小距离、碰撞或走廊结论。`mode` 恒为
`shadow`。v0 Schema 将 `qualification` 固定为 `candidate`；即使未来某次 shadow 分析
分类为 `allowed` 或 `blocked`，也不能在 v0 内升格为 `collision-qualified` 或
`hardware-qualified`。

v0 **未建模**、因此不得写成「已经绑定」的项：

- asset/family/deployment revision（只间接存在于 test lock 输入集）；
- 独立的 kinematics / PointSet / tool-payload digest；
- uncertainty 和 stop model revision；
- 算法、容差、采样和碰撞后端版本；
- 最小间隙、豁免清单。

这些是 v1 目标绑定面。v0 用 `reason_codes` 声明缺失，例如
`collision-scene-simulation-proxy-only`、`stop-model-missing`、
`continuous-collision-not-computed`。

证书身份规则（`design-frozen`）：影响几何、坐标、关节、轨迹、工具、载荷、裕量或
控制器模型的任何已绑定变化，都必须重新编译。仅材质或不改变 collision/稳定 frame
的渲染 LOD 变化不应改变证书身份。当前 v0 已能证明 test lock / scene / motion 三个
digest 的变化会让重新编译结果产生不同证书身份；它尚无运行时证书选择器/验证器，
因此还不能声称旧证书会被运行时自动拒绝。更细的独立 digest 绑定等 v1。

### 5.5 运行时 shadow/admission

当前只有离线 `lab.spatial-interlock-decision/v0` 产物；当前生成实例固定为
`mode=shadow / decision=unknown / effect=none`。`world_snapshot_version` 的现行占位
语义冻结为 `offline-lock:<test_lock_digest>`。它尚未读取运行时世界状态，也没有写入
Uni-Lab-OS decision store 或参与 JobExecutionClaim。

v0 schema 把 `mode=shadow` 和 `effect=none` 写成 const，同时允许 decision 记录
`allowed / blocked / unknown` 三种无副作用的假设分类。这是有意的：v0 **不能**表示
enforced；即便 decision 为 `allowed`，也没有放行效果。SP8 必须并行提交新 schema，
禁止修改 v0 const 混用。

运行时目标流程（`design-intent`，待 OS 合同）：

```text
WorkflowNodeJobAttempt
  → resolve action + device + sites + material + tool/payload
  → select exact SpatialOccupancyCertificate from WorkCellActivation
  → read world_snapshot_version
  → merge business footprint + spatial footprint
  → evaluate against active claims / telemetry / obstacles
  → recheck same world_snapshot_version in transaction
  → create JobExecutionClaim + fencing token, or return blocked/unknown
```

shadow 模式只记录“如果启用会怎样”，不改变现有派发结果；它的 `allowed` 也不是许可。
enforced 模式下（仅未来 schema）：

- `allowed` 才可进入原子准入；
- `blocked` 给出冲突对象、动作阶段、最小距离和已有 claim；
- `unknown` 失败关闭；
- 快照变化触发 AdmissionRetry，而不是沿用旧决定；
- 取消/断流/重启后，在 PhysicalSettlement 前继续持有 Claim/Fence。

现有机器人模板已实现 SQLite 命令账本、`execution_unknown`、Fence 和显式物理结算；
它是运行时基础，但尚不是 OS 级 JobExecutionClaim，也尚未接入空间证书。两套 Fence
的映射未冻结，属于 SP6。

### 5.6 Workbench 空间诊断层

正常 Workbench 主场景只从 `WorkCellActivation` 投影。空间图层是同一 Pascal 场景中的
可开关 overlay，不建立第二套 renderer，也不从散落证书路径加载。

没有 activation 时，只允许独立离线审阅器读取 `artifacts/spatial-shadow/`；该审阅器
不是 Workbench 主场景，不得写入 runtime claim。

当前 v8 审阅器属于后一种情况：编译器先把八份 EIT 源产物导出为工作区内的
`.unilab/spatial-shadow/current.v0.json`，正式 Theia Workbench 再以严格摘要校验方式读取。
它使用通用 SVG XY/XZ 投影显示环境、逐帧 link/工具/payload AABB、已采样候选走廊、
距离下界、碰撞对象和接触点，并提供时间轴播放；当前不调用 Pascal，
也不假定尚不存在的 `WorkCellActivation`。这不是正常主场景 overlay 的替代品。

图层目标内容：

- 名义走廊、当前 HoldEnvelope、StopEnvelope 和 RecoveryEnvelope；
- 冲突实体高亮、最近点、距离、phase 和原因；
- `allowed / blocked / unknown`，并显示是 shadow 还是 enforced；
- 证书、资产、部署、动作和世界快照 revision；
- planned、commanded、observed、settled 四种状态分开显示。

前端不得：重新计算许可、因隐藏图层释放 claim、修改 GLB 节点后改变空间事实，或把
逻辑工作流连线/小球动画当成机器人轨迹。

SP4 只验收离线证书投影与 digest 追溯。刷新、断流、版本漂移不显示陈旧许可，是 SP5
在真实 `world_snapshot_version` 存在之后的通过标准。

## 6. 已完成、部分完成与计划实现

### 6.1 `implemented-and-tested`

| 能力 | 证据边界 |
|---|---|
| SourceRelease、SHA/bytes、handoff 与 decomposition 门禁 | 根仓测试及投料站真实 P1 验证 |
| 五类候选家族包和静态 Workbench 夹具 | 既有 e2e baseline；只证明 render/picking |
| CR5/FR5/GCR5 运动学 Provider 与预览 | 摘要锁定、本地 mock/kinematic-preview；非硬件 |
| 投料站 Z-up/GLB Y-up/Pascal Y-up 坐标链 | 主场景目视与数值配准通过 |
| 投料站 Demo WorkflowTask | 6 个 Job、21 个事件；进程内 visualization actions |
| pTLC 点表、标定、动作映射、operation 和并行配方 | 历史实机模型输入，可做 shadow 回放 |
| pTLC 15 个 collision proxy 和静态布局 AABB QC | 代理/静态宽相；不是连续机器人碰撞 |
| 机器人命令 `execution_unknown + Fence + settlement` | `unilab_robot_template` 已有持久账本/协调状态机 |
| 能力失败关闭 | 当前 preview 明确 `collision_qualified=false`、`spatial_interlock_enforced=false` |
| 十份 spatial v0 JSON Schema | 窄绑定面；生成物写盘前校验；qualification/mode/effect/path 负向测试 |
| 两样例确定性 TestLock | 38 个输入；pTLC 31 个、投料站 7 个；bytes/SHA 和样例摘要闭合 |
| pTLC Candidate Collision Scene | 15 个静态/存储态 proxy；Z-up 世界 AABB；`simulation-proxy-only` |
| `robot.tank.pick(tank_id=1)` pTLC v0 投影 | 14 个 waypoint、2 个 tool-state、payload phase；整体仍 `unresolved` |
| pTLC CR5 LinkStateSequence | P1 + 14 waypoint、每态 7-link FK/world AABB；15/15 TCP 位置残差 ≤1 mm；candidate frame |
| pTLC partial MotionCorridor | 4 个 `move_j/cp=0` segment 自适应采样；3 个 CP move_j + 7 个 move_l 显式排除 |
| pTLC continuous broad-phase candidate | 4 段保守连续 link AABB；60 个非相邻 pair-segment 结果，27 overlap candidate / 33 conservative separation；环境未评估 |
| pTLC diagnostic playback | 14 段、35.83 s、522 帧；7 段锁定编译 MoveL；工具全程随动、plate payload 238 帧；CP/MoveJ 控制器语义未验证 |
| pTLC sampled proxy environment collision | candidate L/N/Z 注册；522 帧 AABB 距离，61 个盒体 component SAT；204 接触帧、189 宽相未精检帧；非碰撞资格 |
| 初始 certificate + shadow decision | `unknown / effect=none`；`offline-lock:<digest>`；不改变派发 |
| OS 派发前 Shadow 空间准入 | 复用现有同步 pre-dispatch；强绑定 action/digest/world；v0 enforced 在设备适配器前拒绝；尚无正式持久 store |
| 空间硬件互锁适配器 | 默认关闭；独立 PLC grant 与既有运动互斥链逻辑与；类型/断连/TTL/资格故障均撤销许可；未接现场节点 |
| Workbench snapshot exporter | 八份空间源产物交叉校验、统一候选 frame、canonical JSON、原子写入和 `--check` 字节一致性 |
| 独立离线 Workbench Shadow 审阅器 | 正式 Theia 入口；轨迹播放、MoveL/CP fidelity、工具/payload、逐帧距离/碰撞对象/首次接触点、连续包络与 XY/XZ AABB；不进入 Pascal/Activation |
| 空间纵切定向与根仓回归 | 18/18 空间定向/合同测试、44/44 根仓 unittest；编译与导出 `--check` 通过 |
| 前端与可视验收 | `@unilab/spatial-diagnostics` 9/9、Theia 143/143、正式开发构建通过、专项 Playwright E2E 1/1 与两张截图人工检查 |

### 6.2 `design-frozen`，等待编码

- 失败关闭：缺资格 → `unknown`；已绑定摘要漂移 → 重新编译产生新证书身份；shadow 不改派发；
- 走廊名义扫掠公式（不含已签署 uncertainty 预算对象）；
- S6 冲突结果分类；
- Workbench 不计算许可、只投影 Activation 引用的证据；
- v0 schema 的 `mode/effect/qualification` const 与三 digest 绑定面。

### 6.3 `design-intent`，尚未冻成可实现算法或 schema

- 通用 MotionContract v1（当前仅 `design-intent` + candidate 字段表）及投料站 Demo 映射；
- 证书 v1 的独立 family/PointSet/uncertainty/stop/algo 绑定；
- 有界 StopEnvelope / RecoveryEnvelope 生成器；
- OS 持久 decision store、JobExecutionClaim 事务与 robot-template Fence 的映射；
- enforced decision schema。

### 6.4 当前缺失，禁止误报完成

- 动态工具/载荷 attach、两套 world 的合格注册和完整 Canonical Collision Scene；
- 通用连续轨迹、环境/窄相碰撞、最小距离和停止包络求值器；
- pTLC 选定动作的正式 sweep/最小距离报告；
- 投料站 collision-qualified 设备级几何和批准 P2/W2；
- 精确控制器 CP/插补与停止模型；
- OS 持久 JobExecutionClaim、world snapshot 事务复核和空间 Fence；
- `WorkCellActivation` 绑定的 Pascal corridor/stop/conflict overlay；当前独立离线审阅器
  不是这项能力；
- 任何现场强制模式验收；
- 通用 MotionContract schema；投料站样例专属证书。

## 7. 实施计划

阶段状态只使用 §0 的正交轴，不再发明第四套词。

### SP0——冻结合同与样例快照

状态：slice = `implemented-and-tested`；合同 = `schema-frozen-v0`（窄面）；
阶段 = `phase-not-closed`。

目标：防止实现过程中把输入漂移误判成算法变化。

已交付：

- 两样例 27 个输入的 `spatial-test-lock.json`；
- TestLock、pTLC MotionContract 投影、CollisionScene、LinkStateSequence、partial
  MotionCorridor、Certificate、Decision 七份 v0 JSON Schema；
- pTLC 静态 scene、tank1 投影、link-state、partial corridor、unknown certificate/decision
  共七个确定性生成物；
- 15 项空间定向/合同测试，覆盖真实样例、摘要漂移、路径/角色、Schema 正负例、Z-up
  AABB、CR5 FK/mesh/rail、P11 stale-joint、部分走廊边界和 Workbench 快照确定性。

关闭 SP0 尚需：

- 统一状态/错误码注册表；
- pTLC 首批动作和投料站 Demo 六步的正式固定清单；
- 本文 v6 已写明的 pTLC 投影 vs 通用合同分界，仍需专门测试或 schema 注释钉住，避免
  再次把 v0 当成通用合同。

当前 `unresolved reason_codes` 已结构化，但还不是完整错误码表。

通过标准：同一输入重复生成字节稳定；任一已绑定摘要变化后重新编译得到不同证书身份；
schema 负向测试通过。运行时拒绝旧证书不属于当前 v0 已实现能力。
**不**把通用 MotionContract 或 FK 列入 SP0 关闭条件。

### SP1——Canonical Collision Scene

状态：`partial`。已生成 pTLC 15 个静态/存储态 proxy 的 candidate scene，并从锁定 URDF/
mesh 生成 7 个 CR5 link 的动态候选 FK/AABB。静态 proxy 使用
`ptlc.rail_constraint_layout_v2`，动态 link 使用 `ptlc.full-machine-gltf-z-up-candidate`；
两者尚无合格刚体注册。末端工具、plate payload、BVH/窄相和投料站候选 scene 尚未完成。

目标：把 pTLC 代理、CR5 link collision、工具/载荷和静态环境编译成稳定空间场景。

首批范围：

- pTLC：machine deck、feed lift、photo/scrape、tank rack、rail、CR5、吸盘、样品板；
- 投料站：只导入候选几何并保持 `collision_qualified=false`，用于 unknown 回归。

通过标准：frame 闭合、稳定 ID 唯一、代理 watertight/预算报告、确定性摘要、可视调试导出。
CR5 动态 link 必须来自已锁厂家 URDF/mesh，不得从工位 CAD 重建关节。资格保持
`simulation-proxy-only` 或 `candidate`，不得升 `collision-qualified`。

### SP2——pTLC MotionContract 与走廊 MVP

状态：`partial`。tank1 pick 的 waypoint/tool/payload 序列保持 `unresolved`；P1 + 14
waypoint 的 7-link FK/transform 已生成，4 个 `move_j/cp=0` segment 已完成 5° 上限的
自适应离散采样，并生成第一个 `candidate-partial` MotionCorridor；同 4 段已有按关节弧长
上界膨胀的连续保守 link AABB 和自碰撞 broad-phase。`move_l`、CP、控制器 wrap、工具/板、
环境碰撞和窄相仍未完成。

首批动作：

1. `robot_tank_pick(tank_id=1)`；
2. 对应 tank put；
3. feed-lift pick/put；
4. 一条 spot/scrape 转运；
5. 至少一个 unresolved action。

关闭线（收紧后）：

- 对 tank1 的 14 个 waypoint 做 FK，输出 7 个 CR5 link 的确定性世界变换（IR 发布态）；
- 实现 `move_j` 自适应采样；
- `move_l` 与 CP 允许诊断采样，但证书/合同必须继续 `unknown`
  （`cp-blend-unresolved` / `controller-interpolation-unresolved`）；
- 第一个 MotionCorridor 标为 `candidate`/`candidate-partial`，不得标 `qualified` 或把合同改为 `resolved`；
- 走廊能反查每个 link/phase/source point；
- 点表/标定不闭合时 unknown；unresolved 不生成伪轨迹。

未列入本阶段关闭线：控制器精确插补、合格环境/窄相连续碰撞、stop model、通用 v1 schema。

### SP3——静态碰撞、动作冲突矩阵与黄金样本

状态：`partial-foundation`。已有 4 段非相邻连杆的连续保守 AABB broad-phase，但既有
15 个静态代理仍未与动态 link 注册到合格同一 world；没有环境碰撞、窄相、最小距离或
动作冲突矩阵。因此不能称 SP3 已实现。

目标：计算动作—环境和动作—动作约束，并与 pTLC 专家流程对照。

先冻结对照产物，再解释并行是否允许：

- 专家 DAG（`parallel_v1`）与空间冲突矩阵的并排报告；
- 报告硬碰撞、最近点和最小距离；
- 检查 `s2 || s3`、`s6 || s7` 是否在当前模型下允许或给出解释；不得先改专家依赖；
- 保留 `scrape-holder` 业务占用；
- 空间模型默认只增加约束，不自动删除专家工艺依赖；
- 8 个 unresolved action 必须为 unknown。

### SP4——Workbench 空间诊断

状态：`partial / independent-offline-reviewer-implemented-and-tested`；阶段仍为
`phase-not-closed`。

本阶段范围：从 `WorkCellActivation`（若尚无 pTLC activation，则只用独立离线审阅器，
不进入正常主场景）投影已有证书、candidate 走廊和 `unknown` 原因。

当前已交付：

- 工作区快照导出器与 `--check` 门禁；
- 正式 Theia Workbench 的“空间约束”入口；
- EIT tank1 的 15 状态、14 段覆盖、4 段连续保守包络、27 个聚合自碰撞候选对、
  XY/XZ AABB、原因码、digest 和 TCP 残差；
- 包级/宿主级单测、正式构建、专项 Playwright E2E 与可视截图。

当前未交付：pTLC `WorkCellActivation`、Pascal 同场景 3D overlay、certificate→输入摘要的
完整 UI drill-down、stop/conflict/min-distance 图层和投料站空间快照。因此 SP4 不能关闭。

通过标准：同一实体可从 UI 追溯到 certificate 和输入摘要；图层关闭不改变 runtime
状态；投料站样例能如实显示 unknown 原因。

**不**列入 SP4：刷新/断流后拒绝陈旧许可。该项依赖 SP5 的真实 world snapshot。

### SP5——Uni-Lab-OS shadow evaluator

状态：`partial / pre-dispatch-shadow-gate-implemented-and-tested`。当前 OS 已在既有
`TaskSchedulerBridge` 同步派发前边界消费显式空间绑定；Shadow 证据先输出 recorder，
再继续历史派发，v0 `enforced` 请求会在设备适配器前失败关闭。尚无正式 decision store、
attempt/certificate 持久关系、world snapshot 服务或默认生产装配。

目标：在不改变派发的情况下，对 WorkflowNodeJobAttempt 生成 shadow decision。

产物：decision store、world snapshot revision、可重放日志、业务/空间 footprint 合并器。
Decision 仍使用 shadow schema；不得写 `effect` 以外的放行副作用。

通过标准：同一快照重放一致；快照变化触发重算；blocked/unknown 不影响现有任务但完整
记录；任何 decision 可追溯到 task/job/attempt/certificate/revisions；断流后不得把旧的
shadow `allowed` 当作当前分类，更不得当作放行（v0 可以记录假设 `allowed`，但
`effect` 恒为 `none`）。

### SP6——停止/故障注入与 Claim/Fence 集成

状态：`partial-foundation`。StopEnvelope 生成器仍是 `design-intent`；robot-template 已有
Fence/PhysicalSettlement，且本轮空间硬件互锁适配器已经完成默认关闭、字符串/数字类型
漂移、读取失败、TTL 过期、空间明确拒绝和双硬件链同时许可的故障注入。它尚未与 OS
JobExecutionClaim、现场 PLC 节点或合格停止模型绑定。

本阶段先冻结 robot-template Fence 与未来 JobExecutionClaim 的映射，并注入：

- 路径每个 phase 停止；
- telemetry stale、断连、重启；
- tool/payload/site 不确定；
- rail 停止而 arm 状态未知，或相反；
- shadow decision 与派发之间 world snapshot 改变。

通过标准：未知执行保持 Claim/Fence；禁止自动重放；只有精确 PhysicalSettlement 解除。
候选 StopEnvelope 若出现，决定仍为 `unknown(stop-model-missing)`。

### SP7——投料站通用性迁移

状态：`lock-and-fail-closed-fixture-only`。投料站 7 个输入已冻结，尚未生成 corridor 或
collision scene。

前置：通用 MotionContract（v1 schema 或经测试的映射层）已经存在。在此之前不得把
pTLC v0 字段硬套到 Demo 六步上充作通用性证明。

前置满足后，在不写 pTLC 特例的前提下编译投料站 Demo 六步。当前应得到：

- 可展示的 candidate corridor；
- 因轨迹/碰撞/停止模型不足而产生的结构化 unknown；
- 摘要漂移后重新编译产生新证书身份；待 SP5 运行时选择器实现后，再验证旧证书被明确拒绝。

P2/W2、厂家数据和 PointSet 后续获批时，只替换输入和资格，不重写算法。

### SP8——有限强制模式（独立资格项目）

状态：`not-authorized` / `not-started`。使用新 decision schema，不修改 v0 const。

前置条件：collision、标定、轨迹、停止模型、现场障碍和控制适配器全部获批；shadow
误报/漏报分析、故障注入、回滚和机械/机器人/安全/流程联合评审通过。

首个 enforced 范围只允许封闭动作子集，仍保留底层硬安全链。未覆盖动作始终 unknown。

## 8. 两样例验收矩阵

| 检查 | pTLC 当前状态 | 投料站当前状态 |
|---|---|---|
| 输入/摘要闭合 | 31 个历史 point/calibration/rig/rail/model/action/clip/mesh 输入已锁 | 7 个 P1/P2 draft/GLB/demo receipt 输入已锁 |
| collision scene | 15 个静态/存储态 proxy + 7-link FK/AABB；候选 L/N/Z 注册、工具/payload 和生成盒体 SAT 已有，现场刚体/原始 CAD collision 资格未闭合 | 未输出；`collision_candidate=false` |
| 轨迹 | tank1 pick 14 段/522 帧；7 段锁定编译 MoveL；工具/payload 随动；CP/MoveJ 控制器实义仍 unresolved | 只有 Demo 目标状态；真实轨迹缺失 |
| 名义走廊 | 4/14 segment 的安全连续保守 link 包络/自碰撞 broad-phase；另有 522 帧环境代理距离/SAT，非连续环境资格 | 未生成；SP7 通用性/unknown 验证 |
| certificate/decision | `unknown / effect=none`；v0 未绑定新增 link-state/corridor | 尚无样例专属证书；由 TestLock 失败关闭（lock-only） |
| 停止包络 | 未生成；`stop-model-missing` | 未生成；无 stop model |
| 并行验证 | `parallel_v1` 黄金样本；对照产物未冻结 | 六步串行 Demo，后续扩展 |
| OS shadow | 派发前 Shadow gate 已实现；需动作显式绑定，结果尚无正式持久 store/attempt 关系 | 同一 gate 可注入，但当前样例无空间 decision；尚未验证 |
| Workbench | 独立离线 Shadow 审阅器已接入正式 Theia；播放、MoveL/CP fidelity、工具/payload、距离/首次接触点、15 状态/14 段/4 连续包络可见；未进入 Activation/Pascal 主场景 | 既有主场景可视化；尚无空间快照或 spatial 图层 |
| 强制资格 | 当前禁止 | 当前禁止 |
| 本轮空间产物对称性 | 有 scene/contract/certificate | 无；不要写成对称纵切 |

## 9. 测试策略与质量门禁

### 9.0 2026-08-30 已验证基线

本次更新已执行：

```bash
./.venv/bin/python scripts/compile_spatial_shadow.py --check
./.venv/bin/python scripts/export_spatial_workbench_snapshot.py --check
./.venv/bin/python -m unittest discover -s tests -v

PATH=/opt/homebrew/Cellar/node@22/22.23.2_1/bin:$PATH \
  pnpm --filter @unilab/spatial-diagnostics test
PATH=/opt/homebrew/Cellar/node@22/22.23.2_1/bin:$PATH \
  pnpm --filter @unilab/workbench-theia test
PATH=/opt/homebrew/Cellar/node@22/22.23.2_1/bin:$PATH \
  pnpm --filter @unilab/workbench build

# Uni-Lab-OS（已安装其测试依赖的 Python 3.13 隔离环境）
python -m pytest -q tests/workflow/test_device_action_run_bridge.py \
  tests/workflow/test_f05_task_scheduler_bridge.py \
  tests/workflow/test_f05_task_scheduler_bridge_failures.py \
  tests/workflow/test_f05_d1a_common_scheduler_bridge.py

# unilab_robot_template（项目 Python 3.13 隔离环境）
python -m pytest -q tests/test_spatial_hardware_interlock.py \
  tests/test_modular_robotics_architecture.py \
  tests/test_workcell_emergency_containment.py tests/test_runtime_factory.py
```

结果为 compile summary `validated=true / written=false / decision=unknown / effect=none`，
快照 `--check` 字节一致，以及 44/44 根仓 unittest 通过。其中 18 项为空间纵切/Workbench
快照定向合同测试，其余 26 项为既有 station handoff/decomposition/geometry 工具回归。
前端另有空间包 9/9、Theia 143/143 和正式 Workbench 开发构建通过；专项 Playwright E2E
使用本机 Chrome 打开 `pTLC_platformUI` 工作区，验证空间入口、`unknown / shadow /
effect=none`、播放时间推进、MoveL 段、payload、6.77 s 环境代理接触点、XY/XZ 图、
14 段交互和未覆盖原因，结果 1/1 通过并保存两张截图。
OS 派发桥相关回归 34/34 通过；机器人互锁/Fence/运行时相关回归 41/41 通过。

当前测试已覆盖 CR5 URDF/calibration 闭合、STL 米制 AABB、FK、P11 stale-joint、地轨位移、
部分 `move_j` 采样、0.25° 细化样本被连续保守包络包含、跨 frame 失败关闭、OS Shadow
派发前顺序、v0 enforced 拒绝、空间 PLC 许可默认关闭/类型漂移/过期/双链逻辑与、快照
防篡改、已编译 MoveL 离线轨迹、随动工具/payload、候选 frame 注册、逐帧 AABB 距离、
生成盒体 SAT 和独立 Workbench 投影；仍未覆盖 CP/MoveJ 控制器精确插补、合格世界注册、
原始 CAD/非盒体网格窄相、连续时间首次接触、StopEnvelope、OS 持久
decision store/JobExecutionClaim 或 Activation/Pascal 主场景集成，
因此不得据此提升资格。

### 9.1 单元与性质测试

- frame/单位/轴转换和 round-trip（IR 发布态 ↔ 控制器审计态）；
- stable ID、摘要和证书确定性；
- FK/IK、joint/Cartesian 采样和 phase 切换；
- 变换后的 AABB/BVH、最小距离和允许接触对；
- margin 单调性：增大不确定度不能减少冲突；
- 采样收敛：细化后不得把已发现碰撞变成无碰撞；
- unresolved/stale/digest mismatch 必须 unknown；
- v0 schema 负向样例：缺必填字段、绝对路径、重复 role、把 `mode` 写成 enforced、把
  certificate `qualification` 升为 collision/hardware 资格。

### 9.2 回归和变形测试

- 平移/旋转整个场景后，相对碰撞结果不变；
- 只改材质/视觉 LOD，空间证书保持有效；
- 改 collision/frame/trajectory 任一已绑定摘要，重新编译所得证书身份必须变化；
- 替换 tool/payload 后冲突集合只能按新几何重新计算；
- 同一输入在 Mac/Windows 输出的规范化产物语义一致；权威产物不得包含环境相关绝对路径。

### 9.3 性能指标

第一版不预设虚假的实时指标，先记录：

- 场景编译时间、峰值内存和缓存命中；
- 每动作采样数、动态实体数、宽相候选数和窄相次数；
- 证书大小、Workbench 加载时间；
- runtime shadow P50/P95/P99；
- blocked/unknown 比例及原因分布。

只有实测后才设硬预算。离线证书优先于运行时重复做昂贵几何计算。

### 9.4 大文件与 CI

投料站 `station.glb` 约 283,695,812 bytes，已锁入 TestLock 的 bytes/SHA。摘要锁可以
提交；大 GLB 留在 handoff / LFS / 外部交接，不把二进制当作 Git 权威源。CI 或本机
缺少该文件时，编译必须显式失败为 `missing-input`，禁止静默跳过并报告
`validated=true`。

## 10. 人工决策与自动化边界

Agent/编译器可以自动：

- 分析装配树并提出设备/link/joint/collision/site 候选；
- 编译 frame graph、轨迹、走廊、冲突矩阵和证书；
- 生成可视审阅、差异、失败原因和测试；
- 从专家配方提取黄金并行/互斥关系并做对照；
- 对摘要漂移和资格缺失失败关闭。

必须由负责人决定：

- 设备/family 边界和正式 deployment 身份；
- joint limit/zero/controller mapping、TCP、payload/CoM；
- 哪些几何可作 collision、允许接触对和安全 margin；
- stop model、人工进入区、软管/电缆策略；
- 哪些工艺依赖可被优化；
- shadow 升级 enforced 的范围和回滚条件；
- uncertainty 预算各分项的批准。

## 11. 推荐的当前执行顺序

1. 关闭 SP0 剩余项：错误码注册表、动作/Demo 固定清单，以及「v0 不是通用
   MotionContract」的专门测试钉；
2. 当前 candidate L/N/Z 配准只用于诊断；继续 SP1 时必须用独立测量锚点审核
   full-machine glTF-Z-up ↔ `rail_constraint_layout_v2` 刚体变换及不确定度，合格前不得把
   代理接触提升为现场碰撞结论；
3. 动态吸盘与 plate payload 候选随动已交付；下一步用正式 tool/payload collision mesh、
   attach/detach 事件和允许接触对替换盒体/TCP 接触面近似；
4. 7 个 `move_l` 已消费锁定编译轨迹做诊断回放；下一步验证 MoveJ timing/easing、CP blend
   和关节 wrap 的控制器实义，未闭合部分继续保持 `nominal-controller-unverified`；
5. 522 帧环境代理 AABB 距离与生成盒体 SAT 已交付；下一步接原始 CAD/非盒体 BVH 窄相、
   有符号距离与连续时间 TOI，并补允许接触对，保持 proxy overlap=候选；
6. SP4 的独立离线审阅器已交付；完成 SP3（含专家 DAG ↔ 空间矩阵对照产物）后，补齐
   `WorkCellActivation` 和 Pascal 主场景投影；SP5 把现有 pre-dispatch gate 接到正式
   decision store、真实 attempt 日志、world snapshot 重算和陈旧许可拒绝；
7. SP6 的默认关闭硬件适配器已交付；下一步冻结 OS JobExecutionClaim ↔ robot Fence 映射、
   建 StopEnvelope，再由现场联合评审单独配置 PLC 空间节点；通用 MotionContract schema
   就绪后再用投料站执行 SP7；
8. 机械/CAD/机器人审核可以继续，但不会自动提升 collision、stop 或硬件资格；
9. SP8 单独立项和新 schema，不因 Demo 漂亮或 shadow 结果稳定而自动启动。

本轮已达到的候选里程碑是：

> 对 `robot_tank_pick(tank1)` 输出 7 个 CR5 link 的 14 段、35.83 s、522 帧离线播放，
> 其中 7 段 MoveL 使用锁定编译轨迹；吸盘与 plate payload 随动。候选 L/N/Z 配准后，
> 所有帧都完成环境 AABB 距离检查，生成盒体 component 进入 SAT 精检，并在 Workbench
> 显示逐帧对象、距离、首次接触时间/位置和红色接触点。同时保留只覆盖 4 个
> `move_j/cp=0` segment 的安全连续包络/自碰撞 broad-phase。CP/控制器精确插补、合格
> 配准、非盒体/原始 CAD 窄相、连续 TOI 和 stop 仍使合同保持 `unresolved`；决定保持
> `unknown / shadow / effect=none`，入口不掌握调度许可。

近期下一个可验证里程碑应是：

> 用现场/独立锚点审核当前 candidate world 注册，以原始 CAD 或批准的非盒体 collision mesh
> 替换代理组件，并把采样帧检查升级为具有保守时间上界的连续 TOI/最小距离求解；再建立
> Stop/RecoveryEnvelope。完成前仍不提升 collision 或硬件资格。

其后的首个 Activation 绑定端到端里程碑是：

> 在已绑定 `WorkCellActivation` 的 UniLab Workbench 中选择 `robot_tank_pick(tank1)`，
> 显示分阶段机器人/工具/板 candidate MotionCorridor；再选择一个并行动作，显示
> `allowed / blocked / unknown`、冲突实体、最小距离、证书摘要和 shadow 标记。切换到
> 投料站 Demo 时，同一 UI 如实显示因 collision/stop/trajectory 资格不足而产生的
> unknown。若投料站尚无 activation，则该切换走离线审阅器，不进入未激活主场景。

这同时证明空间计算有实际输出、失败关闭有效、UI 不掌握许可，并且算法能跨两个样例复用。
跨样例复用的前提是通用 MotionContract 已存在；在那之前，投料站只证明 lock-only
失败关闭，不证明算法已通用。
