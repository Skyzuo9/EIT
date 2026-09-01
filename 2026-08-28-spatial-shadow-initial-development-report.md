# 空间约束自动计算：初步开发与测试报告

日期：2026-08-28
更新：2026-08-30
状态：`sp0-slice-implemented-and-tested / sp1-sp2-playback-and-sampled-proxy-collision-partial / sp4-offline-reviewer-implemented-and-tested / sp5-pre-dispatch-shadow-partial / sp6-hardware-guard-foundation / shadow-only`
权威设计：[项目级 Design & Plan v8](./2026-08-28-unilab-asset-pipeline-project-design-and-spatial-plan.md)

v0 `lab.motion-contract` 是 pTLC waypoint 投影，不是通用合同。投料站本轮只锁定输入。

## 1. 本轮结论

空间约束链已经从“只有设计”推进到一个可重复运行的离线纵切：编译器冻结两样例输入
摘要，生成 pTLC 候选 collision scene，解析 `robot_tank_pick(tank_id=1)`，发布 7 个 CR5
link 在 P1 + 14 waypoint 的候选 FK/AABB，并生成 14 段、35.83 s、522 帧的诊断播放；
7 个 MoveL 段消费锁定编译轨迹，吸盘和 plate payload 随动。候选 L/N/Z 配准后，522 帧
均计算环境 AABB 距离，生成盒体进入三角形 SAT 精检。同时，4 个 `move_j/cp=0` segment
仍保留 `candidate-partial` corridor、连续保守 link 包络与自碰撞 broad-phase。
最终仍发行失败关闭的 `unknown / effect=none` shadow decision。当前共生成十份空间产物，
其中八份源产物会导出为工作区冻结快照，并在正式 Theia Workbench 的“空间约束”入口中显示动画、距离、首次
代理接触时间/位置、工具/payload、15 个状态、14 段覆盖、4 段连续包络、27 个聚合
自碰撞候选对和 XY/XZ AABB 投影。投料站没有
scene/contract/certificate，只承担 lock-only 失败关闭。

本轮没有计算**合格且连续**的完整 MotionCorridor、原始 CAD/非盒体窄相或 StopEnvelope。
当前环境结果是候选配准、历史 proxy 和离散播放帧下的诊断，不是现场碰撞资格。OS 已接入现有
同步派发前 Shadow gate，但没有正式 decision store/JobExecutionClaim；机器人模板已有
默认关闭的空间 PLC 硬件许可夹层，但没有接现场节点或真实设备。尚未接入
`WorkCellActivation` 或 Pascal 主场景 overlay。动态 link 与 proxy scene 只有
`candidate-relative-layout`，没有现场审核的刚体资格；工具和 plate payload 使用候选代理
几何。因此它证明的是合同、摘要、FK、诊断播放、采样式代理碰撞、部分连续宽相候选、派发前失败关闭、离线可视审阅和
互锁适配器纪律，不是空间安全结果。

## 2. 新增实现

入口：

```bash
./.venv/bin/python scripts/compile_spatial_shadow.py
```

只检查、不写输出：

```bash
./.venv/bin/python scripts/compile_spatial_shadow.py --check
```

新增内容：

| 内容 | 路径 |
|---|---|
| 两样例输入与产品选择 | `config/spatial-shadow-samples.v0.yaml` |
| 编译器 | `scripts/compile_spatial_shadow.py` |
| TestLock schema | `schemas/spatial-test-lock-v0.schema.json` |
| CollisionScene schema | `schemas/spatial-collision-scene-v0.schema.json` |
| MotionContract schema | `schemas/motion-contract-v0.schema.json` |
| LinkStateSequence schema | `schemas/spatial-link-state-sequence-v0.schema.json` |
| PlaybackTrajectory schema | `schemas/spatial-playback-trajectory-v0.schema.json` |
| EnvironmentCollision schema | `schemas/spatial-environment-collision-v0.schema.json` |
| ContinuousCollisionCandidate schema | `schemas/continuous-collision-candidate-v0.schema.json` |
| partial MotionCorridor schema | `schemas/motion-corridor-v0.schema.json` |
| Certificate schema | `schemas/spatial-occupancy-certificate-v0.schema.json` |
| Decision schema | `schemas/spatial-interlock-decision-v0.schema.json` |
| 定向测试 | `tests/test_spatial_shadow.py` |
| 生成物 | `artifacts/spatial-shadow/v0/` |
| Workbench 快照导出器 | `scripts/export_spatial_workbench_snapshot.py` |
| 快照定向测试 | `tests/test_spatial_workbench_snapshot.py` |
| EIT 工作区快照 | `pTLC_platformUI/.unilab/spatial-shadow/current.v0.json` |
| 空间诊断前端包 | `uni-lab-fe/packages/spatial-diagnostics/` |
| Theia 快照数据源 | `uni-lab-fe/packages/workbench-theia/src/browser/workbench-spatial-shadow-source.ts` |

编译器具有以下失败关闭行为：

- 所有输入必须是仓库内相对路径，禁止 `..` 和绝对路径；
- sample、input role 和 input path 必须唯一；
- 对每个输入记录 bytes 和 SHA-256；
- pTLC 点表 hash、运动学 commit 和 calibration 必须闭合；
- 投料站 receipt 中的 bytes/SHA 必须与本地 handoff、layout、coverage、GLB 一致；
- pTLC proxy manifest、collision QC 和 layout 的 15 个 asset ID 必须精确一致；
- collision QC 必须全部通过且 layout 不得有 unexpected overlap；
- tank1 必须保持 P1 锚点、rail slot 5、14 个 waypoint、P75 首点、P1 终点和
  `suction-on` acquire；
- point 必须为 `validated`，所用 `move_j/move_l` 必须属于该点 allowedMotion；
- `move_l` 的实测 joint 若与 pose 相差超过 1 mm，必须在已锁编译片段中有 stale 记录和
  软件求解终点，否则拒绝；
- CR5 URDF 的 8 link/7 joint 拓扑、6 轴 origin/axis 与 calibration 必须闭合；
- 7 个 binary STL 必须满足确定长度、有限顶点、米制无 scale，并绑定 SHA；
- rail slot 4→5 必须由已锁 rig map/rail 点表解析，不能猜方向；
- 所有输出在写盘前通过本地冻结、待提交的 JSON Schema；
- 输出采用 canonical JSON 摘要和原子替换。

## 3. 两样例冻结结果

### 3.1 pTLC

- sample：`eit-ptlc-historical-v1`；
- qualification：`historical-as-built-shadow`；
- 输入：31 个（新增 rail-frame 分析与 10 个锁定环境碰撞代理 STL）；
- `collision_candidate=true`；
- `collision_qualified=false`；
- `spatial_interlock_enforced=false`；
- `hardware_execution=false`。

### 3.2 投料站

- sample：`eit-feeding-station-demo-v1`；
- qualification：`demo-simulation-cad-comparison-only`；
- 输入：7 个；
- 冻结了 P1 handoff、Mac validation、P2 draft、coverage、Workbench receipt 和
  283,695,812-byte station GLB；
- `collision_candidate=false`；
- `collision_qualified=false`；
- `spatial_interlock_enforced=false`；
- `hardware_execution=false`。

投料站在本轮只承担摘要漂移与 unknown 失败关闭样例，不生成空间放行结果。

## 4. pTLC 初始产物

### 4.1 Candidate Collision Scene

输出：`artifacts/spatial-shadow/v0/ptlc-collision-scene.json`

- 15 个实体；
- 世界坐标为 right-handed、Z-up、meter；
- 每个实体绑定 STL path/SHA、局部 AABB、layout pose、世界 AABB、误差估计和
  `simulation-proxy-only` qualification；
- 14 个 source layout allowed-overlap 被保留为候选解释；
- 本 scene 中工具仍是工具站存储姿态；播放/碰撞编译阶段会移除该存储实体，并按
  `physical_tool_mount` 生成末端随动工具；
- 机器人 link 原始发布在独立 full-machine glTF-Z-up candidate frame；后续环境碰撞产物
  已生成 `candidate-relative-layout` 变换，但尚未获得现场刚体注册资格；
- 本 scene 自身只提供 AABB/proxy QC；采样式代理碰撞与生成盒体 SAT 见 §4.4.3，不是
  原始 CAD 连续碰撞。

### 4.2 Tank1 MotionContract

输出：`artifacts/spatial-shadow/v0/ptlc-tank1-motion-contract.json`

- action：`robot.tank.pick`；selector：`tank_id=1`；
- scope：`robot-arm-after-anchor-and-rail-settle`；
- 前提：P1、rail slot 5 settled、controller tool 1；
- 14 个 robot-motion waypoint；
- 2 个 tool-state：`rotary-down`、`suction-on`；
- payload 从 `empty` 切换为 `plate-attached`，终态回到 P1 但仍携带板；
- `move_j` 使用有效实测 joint；派生 `move_l` 点使用 `jointSolved`；
- P11 的旧 joint 与 pose 相差 22.399515 mm，已按已锁片段的 stale ledger 拒绝，并使用
  `compiledMoveLTrajectory` 软件终点；该终点不是重新示教的硬件 joint；
- waypoint sequence 已解析，但合同整体保持 `unresolved`。
- 本文件是 pTLC v0 投影，不能当作通用 MotionContract 已落地。

未解析原因：

- `controller-interpolation-unresolved`；
- `cp-blend-unresolved`；
- `continuous-collision-not-computed`；
- `stop-model-missing`。

### 4.3 CR5 LinkStateSequence

输出：`artifacts/spatial-shadow/v0/ptlc-tank1-link-states.json`

- 7 个 collision link：`base_link` + `Link1..Link6`；
- 7 个 binary STL 共 40,764 triangles，顶点单位按 URDF 原生 meter 读取；
- P1 anchor + 14 waypoint 共 15 个 state，每态含 7-link 世界矩阵和 broad-phase AABB；
- controller→model 使用 `q_model=sign*q_controller+zero_offset`；
- slot 4=500 mm 到 slot 5=600 mm 按 rig map `sign=-1`，世界 X 平移 `-0.1 m`；
- 15/15 个 Tool 1 TCP 位置残差不超过 1 mm，最大 0.297713 mm；
- frame 为 `ptlc.full-machine-gltf-z-up-candidate`，不是静态 proxy scene 的 frame；
- qualification 保持 `candidate`，CR5 skeleton 与现场 CR5A 的几何等价性未获批。

### 4.4 Partial MotionCorridor

输出：`artifacts/spatial-shadow/v0/ptlc-tank1-motion-corridor.json`

- 共 14 个 motion segment；
- 4 个 `move_j/cp=0` segment 以最大单轴步长 5° 自适应采样；
- 3 个带 CP 的 `move_j` 以 `cp-blend-unresolved` 排除；
- 7 个 `move_l` 以 `controller-cartesian-interpolation-unresolved` 排除；
- 每个已采样 segment 可反查 source/target state、phase、payload 和 7-link AABB union；
- 结果是离散 `candidate-partial` broad-phase 诊断，不是连续保守扫掠或碰撞结论。

### 4.4.1 Continuous Collision Candidate（2026-08-30）

输出：`artifacts/spatial-shadow/v0/ptlc-tank1-continuous-collision.json`

- 只继承 4 个 `move_j/cp=0` eligible segment，10 个 MoveL/CP 段继续排除；
- 每个采样子区间把起点 link AABB 按上游关节 `半径上界 × |Δq|` 路程和膨胀，得到对
  线性关节插值保守的连续包络；
- 0.25° 细化 FK 样本全部被发布包络包含，跨 world frame 输入失败关闭；
- 每段检查 15 对非相邻连杆，共 60 个 pair-segment 结果：27 个 overlap candidate、
  33 个 conservative separation；overlap 不是确证碰撞；
- 本连续安全包络产物里的环境碰撞仍保持 `not-evaluated-frame-unregistered`；另有的播放
  采样帧环境代理检查见 §4.4.3，不等于连续包络、合格 BVH/窄相或 StopEnvelope；
- certificate v0 没有绑定该新产物，结果仍为 `unknown / effect=none`。

### 4.4.2 全轨迹诊断播放（2026-08-30）

输出：`artifacts/spatial-shadow/v0/ptlc-tank1-playback.json`

- 14/14 motion segment 可播放，统一时间轴为 35.83 s、522 帧；
- 7 个 MoveL 段直接使用锁定 `compiled.moveLTrajectories`，共 318 帧，标记
  `diagnostic-compiled-move-l`；
- 7 个 MoveJ 段使用名义 joint 插值；4 个带 CP 段允许诊断播放，但标记
  `nominal-controller-unverified`，不声称复现控制器 blend/wrap；
- `TOOL_SUCTION` 按 `physical_tool_mount` 随 Link6 运动；suction acquire 后挂接 plate
  payload，共 238 个 payload-attached 帧；
- 工具与 payload 均为候选盒体/TCP 接触面模型，不是现场合格 collision geometry。

### 4.4.3 采样式环境代理碰撞（2026-08-30）

输出：`artifacts/spatial-shadow/v0/ptlc-tank1-environment-collision.json`

- 以 rail L/N 拟合、slot 5=600 mm 和 rail-top 接触建立
  `candidate-relative-layout`；`world_rigid_transform_qualified=false`；
- 522 个播放帧都计算机器人 link、工具、payload 对环境 component 的 AABB 距离下界；
- 10 类锁定生成盒体 STL 被拆为 61 个 component，并用 moving triangle ↔ box SAT 精检；
  4 个 shaped proxy component 只做宽相；
- 结果：204 个代理精检接触帧、189 个宽相未精检帧、129 个采样分离帧、220 个接触事件；
- 首次代理接触：6.768636 s，segment 2/frame 14，`tool:TOOL_SUCTION` ↔
  `ptlc.proxy:develop_tank_rack:component:7`，候选位置
  `[0.790000, -0.223098, 1.599918] m`；
- 该结果可能反映真实风险，也可能来自候选配准或代理几何偏差；没有现场审核前，不得写成
  真机碰撞结论，更不能用于自动准入。

### 4.5 Certificate 与 Shadow Decision

输出：

- `ptlc-tank1-spatial-certificate.json`；
- `ptlc-tank1-shadow-decision.json`。

结果固定为：

```text
mode     = shadow
decision = unknown
effect   = none
```

这表示即使运行时消费当前结果，也不得据此改变派发或授予执行许可。

Certificate v0 仍只绑定 TestLock、CollisionScene、MotionContract 三个摘要，未绑定新增
link-state/corridor；reason code 显式记录该边界和两套 world 尚未注册。

### 4.6 Workbench 冻结快照与离线审阅器

导出：

```bash
./.venv/bin/python scripts/export_spatial_workbench_snapshot.py
./.venv/bin/python scripts/export_spatial_workbench_snapshot.py --check
```

当前输出：`pTLC_platformUI/.unilab/spatial-shadow/current.v0.json`。

- 导出器同时读取 collision scene、link-state、playback、sampled environment collision、
  partial corridor、continuous candidate、certificate 和 decision，
  校验样例、frame、摘要、状态/段计数及 `unknown / shadow / effect=none`；
- 输出为 canonical JSON，使用原子替换；`--check` 要求磁盘文件与重算结果逐字节一致；
- 快照不含环境相关绝对路径，digest 为
  `fc9498dc2b806169a6650a75c358091f5f4e7a5047d57863141dba03bd497d47`；
- `@unilab/spatial-diagnostics` 重新计算 digest 并严格解析，不提供 fixture/demo 回退；
- 正式 Theia Workbench 的“空间约束”入口展示播放/暂停、全局时间拖动、0.5/1/2 倍速、
  15 个状态、14 个运动段、522 个播放帧、工具/payload、4 个连续候选、27 个聚合
  自碰撞候选对、204 个代理接触帧、189 个待精检帧、每态 7 个 link AABB、环境 AABB、
  逐帧距离/对象/接触点、首次接触时间/位置、XY/XZ 投影、原因码和 TCP 残差；
- UI 固定展示“结论未知：禁止据此放行”和“不是 WorkCellActivation”，不写 runtime
  claim，也不改变调度。

这是一套独立离线审阅器，不是 Pascal 3D 同场景叠加。当前 Uni-Lab-OS 尚未发布
`WorkCellActivation` 或空间 artifact binding，因此不能把快照旁路接入正常主场景。

### 4.7 Uni-Lab-OS 派发前 Shadow 准入

- 新增 `unilabos.workflow.spatial_admission.SpatialAdmissionGate`；
- 由现有 `TaskSchedulerBridge._on_job_pre_dispatch` 同步调用，不创建第二套调度器；
- 动作必须精确绑定 `action_contract_id`、`decision_digest`、`world_snapshot_version`；
- Shadow 完整证据先输出审计 outcome 再派发；摘要漂移降为 `unknown/effect=none`，不改变
  现有派发；
- v0 `enforced` 即使摘要完整也在设备 dispatcher 前失败关闭并取消未派发内存运行；
- composition root 可以显式注入该端口，但正式 SQLite decision store、attempt 关系、
  world snapshot 服务和生产默认装配尚未完成。

### 4.8 默认关闭的空间硬件互锁适配器

- `SpatiallyGuardedInterlockProvider` 把既有运动互斥 PLC 观测与独立空间 PLC grant 做逻辑与；
- `SpatialInterlockBinding.enabled` 默认 false，关闭时不读取 PLC 且返回 UNKNOWN/无运动许可；
- 启用必须同时声明硬件强制来源与 64 位小写资格摘要；
- 字符串布尔、数字、读取异常、基础互锁过期、非硬件来源和空间明确拒绝均失败关闭；
- 只有两个经验证硬件 grant 同时为真才保留 rail/arm 当前相位许可；
- 当前只完成适配器和故障注入，没有现场 PLC 变量、停止距离、控制器程序或真实设备证据。

## 5. 测试结果

空间定向/合同测试：

```text
18/18 passed
```

覆盖：

1. 当前两个真实样例重复编译字典完全一致、所有 schema 通过；
2. Certificate qualification、Decision mode/effect 的正负例；
3. 输入字节漂移会改变 sample digest 和 lock digest；
4. 路径逃逸、重复 input role 和新 link-state 绝对路径失败关闭；
5. Z-up yaw/AABB、CR5 mesh 米制边界和 rail `-0.1 m` 位移；
6. P11 stale measured joint 被拒绝，软件求解终点通过 FK 门；
7. 14 段中只采样 4 个 `move_j/cp=0`，步长不超过 5°；
8. partial corridor 禁止 qualification 升级；
9. Workbench 快照导出确定、无绝对路径，`--check` 可发现内容漂移；
10. 快照摘要、样例、frame、计数和失败关闭字段与八份源产物一致；
11. 0.25° 细化 FK 样本均被连续保守包络包含，连续 schema 禁止资格升级；
12. corridor/continuous world frame 不一致时失败关闭，Workbench 严格绑定全部源产物；
13. playback 为 14 段/522 帧，MoveL 编译轨迹、工具/payload attach 和时间轴交叉一致；
14. 环境碰撞 effect/配准资格不能升级，逐帧计数、首次接触及 triangle-box SAT 正负例通过。

根仓完整 unittest 回归：

```text
44/44 passed
```

测试期间发现 macOS 临时目录可能以 `/var/...` 进入、解析后变为 `/private/var/...`。
路径边界检查现统一先解析 repo root，避免把合法仓库内临时文件误判为路径逃逸。

前端和正式 Workbench：

```text
@unilab/spatial-diagnostics: 9/9 passed
@unilab/workbench-theia: 143/143 passed
@unilab/workbench-theia typecheck: passed
@unilab/workbench development build: passed, 0 errors
spatial-shadow Playwright E2E: 1/1 passed
Uni-Lab-OS 派发桥相关回归: 34/34 passed
robot-template 空间互锁/Fence/运行时相关回归: 41/41 passed
```

专项 E2E 使用本机 Google Chrome 打开正式 Theia Workbench 与 EIT `pTLC_platformUI`
工作区，点击“空间约束”，验证：

- 快照进入 `ready`；
- 根元素保持 `decision=unknown / mode=shadow / effect=none`；
- XY/XZ 两个投影可见，当前状态的 7 个 link 在两图中共 14 个投影框；
- 播放后时间轴确实前进；14 个运动段均可选择，MoveL 段显示编译轨迹来源；
- plate attach 后 payload 图层在 XY/XZ 两图均存在；
- 拖动到 6.77 s 后显示 `proxy-mesh-contact`、最近对象、距离 0、候选接触位置和红色接触点；
- 选择连续包络未覆盖段会如实提示它只可离线播放；
- 截图已保存并人工检查：
  `output/spatial-shadow-workbench/eit-spatial-playback-payload-workbench.png`、
  `output/spatial-shadow-workbench/eit-spatial-playback-collision-workbench.png`。

第一次 E2E 尝试暴露两项环境/断言问题：Playwright 自带 Chromium 未下载，随后明确使用
本机 Chrome；测试最初按旧动作显示名 `robot_tank_pick(tank1)` 断言，而冻结快照的正式
`action_contract_id` 是 `robot.tank.pick`，修正为合同 ID 后通过。两者都没有掩盖为成功。

## 6. 当前没有完成的部分

1. full-machine glTF-Z-up 与 `rail_constraint_layout_v2` 的现场审核合格刚体注册；当前只有
   rail L/N/Z 证据导出的 candidate transform；
2. 正式工具/payload collision mesh、完整 rotary/attach/detach 状态和允许接触对；当前为
   `physical_tool_mount` + Tool 1 TCP 接触面候选；
3. MoveJ timing/easing、CP blend 和 joint-wrap 的控制器精确语义；MoveL 仅证明已编译轨迹
   可以离线回放；
4. 把当前 4 段安全连续保守包络扩展到经验证的 MoveL/CP、工具和 payload；
5. 原始 CAD/非盒体环境 mesh 的 BVH 窄相、有符号距离与连续时间首次接触 TOI；当前只有
   播放采样帧 AABB 距离、生成盒体 SAT 和 shaped proxy 宽相；
6. StopEnvelope/RecoveryEnvelope；
7. 动作—动作冲突矩阵和 `parallel_v1` 对照；
8. Uni-Lab-OS 正式 decision store、world snapshot、attempt 绑定和 JobExecutionClaim；
9. `WorkCellActivation` 绑定的 Pascal corridor/stop/conflict overlay；当前独立离线
   Workbench 审阅器不等于该能力；
10. 投料站空间快照和同一 UI 的跨样例验证。

## 7. 下一步建议

下一轮继续进入 SP1/SP2 的闭环部分，并为后续 Activation 绑定准备：

1. 用独立/现场锚点审核当前 candidate world 注册并签署不确定度；
2. 用批准的工具、payload 与环境 collision mesh 替换盒体/历史 proxy 近似；
3. 闭合 MoveJ timing/easing、CP blend 和 joint-wrap 的控制器实义；
4. 把采样式代理检查升级为原始 mesh BVH、有符号距离和连续 TOI，并补允许接触对；
5. 只有上述边界和 StopEnvelope 闭合后，才开始输出 candidate blocked；在此之前继续保持 unknown；
6. 把现有 OS pre-dispatch gate 接入正式 decision store/world snapshot/attempt 审计；在
   Uni-Lab-OS 冻结 `WorkCellActivation` 与 spatial artifact binding 后，把同一快照投影
   接入已有 Pascal 场景；不创建第二套 renderer/store，也不让 UI 重新计算许可。
