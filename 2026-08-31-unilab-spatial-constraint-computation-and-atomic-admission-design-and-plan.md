# UniLab 空间干涉计算、动作约束编译与 OS 原子准入：Design & Plan

日期：2026-08-31

状态：`implementation-authority-draft/v1`

适用范围：EIT pTLC 黄金样例、投料站通用性样例、Uni-Lab-OS 本地工作流、UniLab Workbench 只读诊断

不适用范围：功能安全认证、PLC 安全程序替代、未经现场资格化的真机放行

本文是对以下两份文档的收敛和后续实施设计：

- [pTLC 三维资产、空间互锁与并行流程讨论归纳](./2026-08-21-ptlc-asset-pipeline-spatial-interlock-conversation-summary.md)
- [UniLab 通用资产管线与空间约束自动计算：项目级 Design & Plan](./2026-08-28-unilab-asset-pipeline-project-design-and-spatial-plan.md)

本文只聚焦三项近期目标：

1. 自动发现候选空间干涉；
2. 把空间证据编译成“哪些其他动作不能同时运行”的动作约束；
3. 把合格约束接入 Uni-Lab-OS，形成持久、可恢复、原子取得的作业执行占用。

---

## 0. 结论和本轮决策

当前项目已经有一条可运行的离线纵切：pTLC `robot.tank.pick` 可以生成 CR5 运动学、
14 段/522 帧播放、工具与 payload 随动、部分连续自碰撞候选、采样式环境代理碰撞，
并在 Workbench 中可视化。Uni-Lab-OS 也已经有一个同步 pre-dispatch Shadow 检查端口，
机器人模板已有 `execution_unknown`、Fence 和 PhysicalSettlement 的设备侧基础。

但是当前系统还不能权威回答“动作 A 运行时，哪些动作 B/C 不能运行”，原因不是缺一个
布尔碰撞函数，而是缺少以下中间层和持久边界：

```text
候选碰撞证据
  → 语义分类
  → 动作约束集合
  → 当前世界快照实例化
  → 与现有 Claim/Fence 合并
  → 事务内版本复核和原子 Claim
  → 派发、结果不明保留、物理结算后释放
```

本计划作出六项核心决策：

1. **证据和准入分离**：几何引擎只输出 `SpatialEvaluation`，不得直接输出“允许执行”。
2. **调用方不提交权威摘要**：业务动作只声明稳定的空间策略绑定；decision digest、世界
   快照和活动 Claim 由 OS 在派发时自行读取。
3. **昂贵计算在事务外，资格复核在事务内**：先针对世界版本 `V` 计算，再用短事务确认
   `V` 未变化并原子取得 Claim；若变化则返回 `retry_required`。
4. **持久 Claim 与工作流作业同库**：JobExecutionClaim 必须和 WorkflowNodeJob 位于同一
   SQLite 权威和事务边界，不能用第二个进程内锁或第二个数据库冒充原子性。
5. **动作约束优先保守、可解释**：第一版只自动生成可解释的 `invalid_action`、`mutex`、
   `requires_settlement`；`capacity`、`min_start_offset` 和优化建议在证据成熟后增加。
6. **软件准入不等于真机安全**：新增 `software_admission` 只控制 OS 是否派发，不替代
   PLC、安全控制器、围栏、急停、停止距离验证和现场验收。

### 0.1 目标完成口径

本项目不再用一个“完成/未完成”标签混合不同成熟度。每项能力必须同时声明：

| 轴 | 允许值 |
|---|---|
| 实现 | `not_started` / `partial` / `implemented_and_tested` |
| 证据资格 | `candidate_shadow` / `admission_qualified` / `hardware_qualified` |
| 运行效果 | `none` / `software_block` / `software_claim` / `hardware_enforced` |
| 发布 | `local_uncommitted` / `committed` / `released` |

当前最高只能达到：

```text
implemented_and_tested（部分纵切）
+ candidate_shadow
+ effect=none
+ local_uncommitted
```

本计划近期目标是：

```text
候选干涉与动作约束：implemented_and_tested + candidate_shadow
OS 持久原子准入：implemented_and_tested + admission_qualified + software_claim
真机互锁：保持 not_qualified，不在本轮升级
```

---

## 1. 当前实现审计

### 1.1 已有资产和算法

当前本地实现已经包括：

- 十份 v0 JSON Schema；
- 两个样例共 38 个输入的摘要锁；
- pTLC 15 个环境代理实体；
- `robot.tank.pick(tank_id=1)` 的候选 MotionContract；
- CR5 `base_link + Link1..Link6` 的 FK、矩阵和 AABB；
- 14 段、35.83 s、522 帧诊断轨迹；
- 7 段已编译 MoveL 的离线播放；
- 工具和 plate payload 随动；
- 4 个 `MoveJ/cp=0` 段的保守连续 link AABB；
- 27 个非相邻 link 自碰撞宽相候选；
- 522 个播放帧的环境 AABB 距离和部分生成盒体 SAT；
- 220 个候选代理接触事件；
- Workbench 独立诊断页与物料 3D 叠加的共享播放时间轴。

关键代码：

- `scripts/compile_spatial_shadow.py`
- `scripts/export_spatial_workbench_snapshot.py`
- `uni-lab-fe/packages/spatial-diagnostics/`
- `uni-lab-fe/packages/workbench-theia/src/browser/workbench-material-viewport.tsx`

### 1.2 已有 OS 和机器人运行时基础

Uni-Lab-OS 当前具备：

- `SpatialAdmissionPort` / `SpatialAdmissionGate`；
- `TaskSchedulerBridge._on_job_pre_dispatch` 的同步派发前接缝；
- WorkflowTask、WorkflowNodeJob、attempt、调试 Admission Hold 的 SQLite 权威；
- 物料准入重试和作业派发意图投影的既有生命周期。

机器人模板当前具备：

- `RobotCommand.command_id` 和请求 fingerprint；
- `CommandState.EXECUTION_UNKNOWN`；
- SQLite CommandJournal；
- Fence 在重启或派发结果不明后继续保持；
- `PhysicalSettlementEvidence` 只能用明确物理见证解除 Fence；
- 默认关闭的 `SpatiallyGuardedInterlockProvider`。

### 1.3 当前接口为什么不能直接扩展成正式准入

当前 `spatial_admission` 请求由动作参数携带四个字段：

```text
policy
action_contract_id
decision_digest
world_snapshot_version
```

该接口适合验证 Shadow 接缝，不适合作为正式权威接口：

1. 调用方可以选择 decision digest 和 world snapshot 字符串；
2. `MappingSpatialDecisionProvider` 只是启动时内存映射；
3. recorder 是可选回调，不是 attempt 级持久事实；
4. 没有活动 Claim 查询和原子竞争；
5. 没有把 evaluation、claim、job attempt 和设备 command 关联；
6. `enforced` 当前只能全部拒绝；
7. v0 certificate 没有绑定 playback、corridor、continuous 和 environment collision；
8. Workbench 直接读取工作区快照，不是 OS 运行事实的只读投影。

因此 v0 保留为迁移输入和失败关闭夹具，不在其上继续堆叠正式运行语义。

### 1.4 当前交付门禁问题

在 2026-08-31 的复查中：

- `compile_spatial_shadow.py --check` 通过；
- 18 个空间 Python 测试通过；
- `export_spatial_workbench_snapshot.py --check` 因浮点末位漂移失败；
- 2,766 个浮点叶值变化，最大绝对差为 `1.11e-16`；
- 当前 Homebrew Node 缺少 `libsimdjson.31.dylib`，前端不能从新进程复测；
- 空间文件和多个子仓改动仍是本地未提交状态。

这些问题不改变算法语义判断，但必须作为新开发的入口门修复，否则同事无法复现。

---

## 2. 范围与非目标

### 2.1 本轮必须交付

1. 通用、可导入的空间合同包，而不是继续由单一脚本内部字典充当接口；
2. 候选环境碰撞、动作—动作冲突和未知覆盖的统一 `SpatialEvaluation`；
3. 从 evaluation 编译 `SpatialConstraintSet`；
4. pTLC `robot.tank.pick` 与至少一组 `parallel_v1` 动作的冲突矩阵黄金样例；
5. 持久 `WorldSnapshot`、`SpatialAdmissionAttempt`、`JobExecutionClaim`、Fence 关联和
   PhysicalSettlement 投影；
6. 同一工作流数据库中的原子 Claim 竞争；
7. 供同事使用的 Python Protocol、JSON Schema、REST 只读投影、TypeScript 类型和示例；
8. Workbench 从 OS 读取运行时结果，但继续保持只读，不在浏览器重算许可。

### 2.2 本轮不交付

- 不把候选代理碰撞升级为硬件安全结论；
- 不实现任意多机器人在线轨迹规划器；
- 不由 3D 自动修改 SiteOccupancy、Material 身份或库存事实；
- 不自动改写工艺专家冻结的 `parallel_v1`；
- 不把软件 Claim 当作安全 PLC 的替代品；
- 不允许前端直接调用“授予执行许可”接口；
- 不在高频渲染循环中运行几何求值器；
- 不创建第二套工作流调度器、Material store 或 Pascal scene。

---

## 3. 目标架构与仓库职责

```text
pTLC / 投料站领域仓
  动作、点位、工具、payload、Site、业务资源
                 │
                 ▼
Spatial Domain Adapter
  只做领域事实 → 通用合同投影
                 │
                 ▼
Spatial Compiler Core（无副作用）
  Scene + ActionContract + Trajectory + uncertainty
  → Evaluation + ConstraintSet + immutable artifacts
                 │
                 ▼
Uni-Lab-OS Spatial Authority
  ArtifactStore + WorldSnapshotStore + AdmissionStore
  + Claim/Fence/Settlement + Scheduler bridge
                 │
        ┌────────┴────────┐
        ▼                 ▼
设备/机器人执行边界       Workbench 只读诊断
Command + Claim token     REST/SSE → services port → Pascal
```

### 3.1 单一职责分配

| 仓库 | 负责 | 禁止负责 |
|---|---|---|
| EIT 根仓 | 跨仓合同审阅、黄金夹具、集成测试、迁移脚本 | 生产运行时权威 |
| pTLC / 投料站领域仓 | Action/Site/Material/点位/工具/payload 的领域绑定 | 直接授予 OS 许可 |
| Uni-Lab-OS | v1 运行时合同权威、世界快照、持久 evaluation/claim/fence/settlement、原子准入 | 重算 CAD 几何或替代设备安全链 |
| unilab_robot_template | RobotCommand、设备 command journal、execution_unknown、设备 Fence、物理见证 | Site/Material 业务事实和跨动作调度 |
| uni-lab-fe | 只读诊断端口、状态解释、Workbench/Pascal 投影 | 自己计算 collision/decision 或写 Claim |

### 3.2 推荐模块边界

Uni-Lab-OS 新增以下逻辑模块，名称可在实现前按仓库规范调整：

```text
unilabos/spatial/
  contracts.py              # 轻量 dataclass/Pydantic 合同
  schemas/v1/               # v1 JSON Schema 唯一权威源
  canonical_json.py         # 唯一摘要和浮点规范化
  artifact_store.py         # 不可变 artifact 元数据/CAS 引用
  world_snapshot.py         # 权威快照构造与版本
  evaluator_port.py         # 纯证据 provider protocol
  constraint_compiler.py    # evidence → constraints
  admission_store.py        # SQLite evaluation/claim/fence/settlement
  admission_coordinator.py  # 乐观求值 + 短事务原子 Claim
  projection.py             # REST/SSE/Workbench 只读投影
```

`Uni-Lab-OS/unilabos/spatial/schemas/v1/` 是 v1 合同的唯一权威位置。EIT 根仓只保留
黄金 fixture、迁移样例和跨仓合同测试；Python 合同与前端 TypeScript 类型由该 Schema
生成或做逐字段一致性校验，不允许各仓各自维护一份同名 Schema。

几何算法实现必须只依赖通用合同，不 import WorkflowStore 或设备适配器。当前 pTLC 专用
逻辑先通过 adapter 包装；达到两个样例后再决定是否抽成独立 Python distribution。

### 3.3 Spatial-ready Asset Gate

资产管线和空间计算共享同一份机械事实，但消费不同几何表达。资产进入空间编译器前必须
通过 Spatial-ready Asset Gate，不允许空间编译器临时从任意 STEP/GLB 猜测碰撞体：

```text
SourceRelease（STEP/SLDASM/厂家 URDF；GLB 仅作候选回退）
  → Canonical Mechanical IR（稳定实体、link、frame、单位、局部变换）
  → render LOD
  → broad-phase AABB/OBB
  → narrow-phase compound convex / simplified static mesh
  → CollisionGeometryManifest + QC + qualification
  → FamilySimBundle
  → WorkCellActivation 钉扎 collision revision
  → SpatialEvaluation
```

Gate 必须保证：

- visual 和 collision 分槽，visual mesh 默认不能占用合格 collision 槽；
- 碰撞体与源几何的单位、frame、外包围尺寸和来源摘要可追溯；
- 开放货架、槽位和可进入工位保留关键空腔，不能用整机 AABB 进行窄相；
- 动态机器人按 link 拆分，工具和 payload 带 attach frame/phase；
- 名义几何与 CAD 简化、安装、标定和运行时不确定度分开记录；
- STEP/B-rep 是优先源；仅有 GLB 时最多生成 `collision-candidate`；
- 候选资产可进入 offline/Shadow，只有获批误差与现场注册的 revision 才能进入
  `collision-qualified`；
- 缺碰撞资产、frame、误差报告或 qualification 时，软件准入必须得到 unknown。

v1 新增 `CollisionGeometryManifest` 作为资产管线到空间计算的唯一碰撞几何交接合同。
第一纵切把现有 pTLC 15 个 proxy 编译为 candidate manifest；第二纵切在批准 P2/W2 后
处理投料站设备级 STEP/SolidWorks/GLB，不把整站展示 GLB直接升级为碰撞资格。

---

## 4. 合同设计

### 4.1 版本、摘要和规范化

所有 v1 合同遵循：

- UTF-8、LF、key 排序、禁止 NaN/Infinity；
- 路径只允许相对 artifact ref 或稳定 URI，不允许环境绝对路径；
- 矩阵、米、弧度统一量化到 `1e-12`，`-0.0` 规范为 `0.0`；
- 时间戳不进入内容摘要，或使用单独的 identity payload；
- 未知 enum、缺摘要、缺资格、版本不支持均失败关闭；
- v1 内只允许向后兼容的可选字段；破坏性变化发布 v2；
- Python 和 TypeScript 类型必须从同一 JSON Schema 生成或通过合同测试锁定；
- reason code 由单一注册表管理，不允许各仓自由拼接近义字符串。

### 4.2 `SpatialActionBinding/v1`

这是领域动作与空间合同的稳定绑定。业务同事只需要维护该层，不提交运行时 decision。

```yaml
schema: lab.spatial-action-binding/v1
action_name: robot.tank.pick
contract_ref: spatial-action-contract:robot.tank.pick/v1
selector_mapping:
  tank_id: resolved_args.tank_id
tool_profile_ref: ptlc.tool.suction/v1
payload_profile_rule: ptlc.tank-pick-payload/v1
admission_policy: shadow
required_qualification: candidate_shadow
binding_digest: <sha256>
```

约束：

- 只声明稳定引用和参数映射；
- 不允许携带 `decision_digest`、`world_snapshot_version` 或 `claim_id`；
- 同一 action template 和 binding generation 唯一；
- selector 无法解析时返回 unknown，不使用默认点位猜测。

### 4.3 `SpatialActionContract/v1`

替代当前 pTLC 专用 waypoint 投影，至少包含：

- contract id/version/digest；
- executor、selector 和适用 WorkCell；
- `approach/acquire/transfer/release/retreat` 阶段；
- 每阶段轨迹引用和控制器插补 profile；
- 工具/payload attach/detach 事件；
- 前置/后置事实；
- 业务 read/write/occupy/release 集合；
- allowed contact pairs，且必须带 phase；
- cancellation/stop/recovery 策略；
- uncertainty profile 和资格引用；
- 不支持能力与 unresolved reason。

合同允许 partial，但 partial 只能进入 Shadow。

### 4.4 `SpatialWorldSnapshot/v1`

世界快照是 OS 权威事实，不由前端或动作参数构造：

```text
snapshot_id
revision（单调递增）
snapshot_digest
captured_at / max_age
workcell_generation + activation_digest
frame_graph_digest + calibration_digest
site/material occupancy revisions
device settled state refs
fresh joint/tool/payload observations
active claim revision
active fence refs
artifact generation
```

规则：

- 高频 joint frame 不要求全部写数据库，但被用于准入的帧必须持久化其摘要、时间和来源；
- 快照只描述事实，不提前包含“允许执行”；
- 任何依赖 revision 改变都会使旧 evaluation 失效；
- 活动 Claim 或 Fence 不因模型/Activation 更新自动释放；
- 有活动 Fence 时禁止切换相关 WorkCellActivation。

### 4.5 `SpatialEvaluation/v1`

纯求值器输出，必须无副作用：

```text
evaluation_id / evaluation_digest
action_instance_fingerprint
world_snapshot_ref + digest
qualification
classification:
  no_conflict_observed | conflict_observed | unknown
coverage
environment_contacts[]
self_contacts[]
action_conflicts[]
minimum_clearance
first_contact
evidence_refs[]
reason_codes[]
```

禁止使用 `allowed` 表示调度许可。`no_conflict_observed` 只代表在已声明模型和覆盖范围内
未发现冲突，仍需 AdmissionCoordinator 复核版本和取得 Claim。

### 4.6 `SpatialConstraintSet/v1`

把几何结果翻译成可解释调度约束：

```text
constraint_set_id / digest
participants[]
constraints[]:
  invalid_action
  mutex
  requires_settlement
  capacity              # 第二阶段
  precedence            # 第二阶段
  min_start_offset      # 第二阶段
source_evaluation_refs[]
coverage / qualification / reason_codes
```

分类规则：

| 证据 | 编译结果 |
|---|---|
| 动作与静态机架硬碰撞 | `invalid_action`，不能靠锁机架解决 |
| 两动作运动/停止包络相交 | `mutex` 或 `min_start_offset` |
| 空 Site 访问体被穿过 | 稳定 SpatialResource 的 `mutex/capacity` |
| 来源/目标 Site、Material 改变 | 合并进业务 Claim member，不伪造 SiteOccupancy |
| allowed contact pair 且 phase 匹配 | 记录解释，不生成冲突 |
| 软管、液体、未注册 frame 等未知 | `unknown`，software admission 下阻断 |
| execution_unknown 或未结算 Fence | `requires_settlement` |

第一版必须输出 pairwise conflict matrix；稀疏超图只作为后续优化，不阻塞可用接口。

### 4.7 `SpatialAdmissionRequest/Outcome/v1`

内部请求由 OS 根据 WorkflowNodeJob 构造，不作为前端写接口：

```text
request_id / idempotency_key
task_uuid / job_uuid / attempt
action_binding_ref
resolved_action_fingerprint
policy: shadow | software_admission
```

OS 补齐：

```text
current_world_snapshot
current_active_claims
artifact generation
qualification policy
```

Outcome：

```text
status:
  observed
  blocked
  claim_acquired
  retry_required
  evidence_invalid
  settlement_required
effect:
  none | software_block | software_claim
evaluation_ref
constraint_set_ref
claim_ref?
reason_codes[]
```

`shadow` 永远 `effect=none`。`software_admission` 中 unknown、证据不合格或冲突均阻止派发；
只有 `no_conflict_observed` 且原子 Claim 成功才返回 `claim_acquired`。

### 4.8 `JobExecutionClaim/Fence/PhysicalSettlement/v1`

Claim 是 OS 持久事实，不能用几何 artifact 或内存锁替代。

Claim 至少包含：

```text
claim_id / claim_digest
task_uuid / job_uuid / attempt
action_instance_fingerprint
world_snapshot_ref
evaluation_ref / constraint_set_ref
fence_generation
status: active | settlement_required | released
members[]:
  device | site | material | business_resource | spatial_resource
acquired_at / released_at
```

Fence 至少包含：

```text
fence_id / generation
claim_id
device_command_id?
reason: dispatch_unknown | cancel_unknown | device_restart | witness_missing
status: active | settled
```

PhysicalSettlement 至少包含：

```text
settlement_id / idempotency_key
claim_id / fence_id / device_command_id
terminal_state
witness_id / source / evidence_digest
observed material/site/device facts
settled_at
```

OS Claim 与机器人 CommandJournal 不合并成一个表。两者通过
`job_uuid + attempt + claim_id + device_command_id + fence_generation` 关联：

- OS 负责跨动作、Site、Material 和空间资源；
- 机器人 journal 负责设备命令幂等、执行结果和设备 Fence；
- 任一侧未知都不能释放 OS Claim；
- 只有合格 PhysicalSettlement 同时满足两侧合同才释放。

---

## 5. 候选干涉与动作约束算法

### 5.1 离线模板编译

```text
ActionContract
+ controller interpolation profile
+ qualified collision geometry
+ tool/payload phase models
+ frame/calibration
+ uncertainty profile
+ stop/recovery model
  → nominal envelope template
  → stop envelope template
  → recovery envelope template
  → stable SpatialResource candidates
  → immutable artifact manifest
```

允许按 selector、rail slot、tool profile、payload profile 建立有限模板组合。组合爆炸时必须
明确 unsupported/unknown，不能回退到忽略工具或 payload。

### 5.2 运行时实例化

```text
resolved action instance
+ current SpatialWorldSnapshot V
+ active Claim/Fence set
  → instantiate transforms and phases
  → broad phase
  → continuous narrow phase / signed distance / TOI
  → semantic classification
  → SpatialEvaluation(V)
  → SpatialConstraintSet(V)
```

第一版动作—动作分析采用保守时间无关包络交集生成 `mutex`。只有经过验证的分阶段时间窗口
才能生成 `min_start_offset`，不得根据动画帧率推导控制器时间。

### 5.3 pTLC 第一黄金矩阵

第一轮不直接覆盖全部 93 个动作。选取能覆盖关键语义的一组：

1. `robot.tank.pick(tank_id=1)`；
2. 同一机器人上的另一个取放动作；
3. 只占点样工位的 `pf_s2_spot`；
4. 缸准备 `pf_s3_tank_prep`；
5. 长等待且根资源为空的 `pf_s6_develop_wait`；
6. 跨段占用 `scrape-holder` 的 `pf_s7_consumables`；
7. 刮取 `pf_s9_scrape`；
8. 收集并 release 的 `pf_s10_collect`。

输出矩阵每个单元必须说明来源：

```text
business_dependency
business_resource
spatial_mutex
capacity
requires_settlement
unknown
no_constraint_observed
```

目标不是让编译器复制 `parallel_v1`，而是解释：

- `s2 || s3` 中哪些来自不同业务资源，哪些有空间证据；
- `s6 || s7` 中长等待为何不持有机器空间 Claim；
- `s7 → s9 → s10` 哪些是工艺因果，哪些是 `scrape-holder` 持久占用；
- 3D 不能推出的依赖继续由专家黄金计划保留。

### 5.4 qualification 门

一个 action instance 只有满足全部条件才可进入 `software_admission`：

- frame/world registration 已批准；
- collision geometry 和 allowed contacts 已批准；
- 所有实际执行 segment 覆盖连续碰撞；
- 工具和 payload phase 完整；
- controller interpolation/wrap/CP 语义已验证；
- uncertainty budget 已签署；
- stop envelope 已存在；
- certificate v1 绑定所有上述 artifact digest；
- world snapshot 和传感观测新鲜；
- 无未结算 Fence。

缺任一项仍可 Shadow，但不得 software claim。

---

## 6. OS 持久化与原子准入

### 6.1 数据库归属

新增表进入现有 `workflow_history.db` 和 WorkflowStore migration，不创建独立 spatial DB：

```text
spatial_world_snapshot_v1
spatial_evaluation_v1
spatial_constraint_set_v1
spatial_admission_attempt_v1
job_execution_claim_v1
job_execution_claim_member_v1
execution_fence_v1
physical_settlement_v1
```

大体积 geometry/playback 不写 SQLite；数据库只写 immutable ref、digest、资格、摘要和运行事实。

关键唯一约束：

- `(workflow_node_job_uuid, attempt)` 只有一个有效 AdmissionAttempt；
- 同一 idempotency key 不能绑定不同请求 fingerprint；
- active Claim member 必须可按 resource key 和 claim status 查询；
- PhysicalSettlement idempotency key 唯一；
- release 必须引用 active/settlement_required Claim，禁止无条件删除。

### 6.2 乐观求值、短事务 Claim

```text
1. Scheduler 发现 job ready
2. OS 读取世界快照 V 和活动 Claim revision C
3. 事务外运行 evaluator，得到 Evaluation(V,C)
4. 编译 ConstraintSet(V,C)
5. BEGIN IMMEDIATE
6. 复核当前 world revision==V、claim revision==C、job attempt 未变化
7. 复核 evaluation digest、资格和当前活动 Claim 冲突
8. 原子写 AdmissionAttempt + Claim + ClaimMembers + Fence generation
9. COMMIT
10. 持久 project_pre_dispatch
11. 携带 DispatchAuthority 调用设备适配器
```

第 6–8 步任一失败：

- world/claim 变化：`retry_required`，不写 Claim；
- 冲突：`blocked`，等待相关 Claim 释放事件后 AdmissionRetry；
- unknown/资格不足：software admission 下 `evidence_invalid` 并阻断；
- 数据库或审计失败：阻断，不能像 Shadow recorder 一样只记日志继续。

### 6.3 派发边界和释放规则

| 情况 | Claim/Fence 行为 |
|---|---|
| Claim 后、设备适配器调用前确定失败 | 原子标记 released，可重试 |
| 已调用设备且明确 rejected、无物理效果 | 记录见证后 released |
| running/succeeded 且物理事实明确 | 完成 PhysicalSettlement 后 released |
| cancel/timeout/断线/重启后结果不明 | `settlement_required`，Fence 保持 |
| Workbench、进程或 OS 重启 | Claim/Fence 从 SQLite 恢复，不自动释放 |
| artifact/Activation 更新 | 旧 Claim 保持；新派发重新求值 |

不得因为 VM/任务退出、UI 关闭或用户再次点击取消而释放物理占用。

### 6.4 `TaskSchedulerBridge` 迁移

当前调用顺序是：

```text
SpatialAdmissionGate.evaluate()
→ project_pre_dispatch()
```

目标改为：

```text
SpatialAdmissionCoordinator.admit(job_uuid, attempt, resolved_args)
→ 返回 claim_acquired/observed 或阻断/重试
→ project_pre_dispatch(..., dispatch_authority)
```

迁移期：

- v0 `SpatialAdmissionGate` 继续支持 `shadow`，标记 deprecated；
- v1 binding 存在时禁止同时传 v0 `spatial_admission`；
- software admission 必须使用 v1 coordinator；
- 生产 composition 默认仍关闭，直到 AD4 gate 全部通过。

---

## 7. 供同事集成的接口

### 7.1 Python Protocol

稳定公开面只暴露合同和 Protocol，不要求业务代码 import evaluator 内部实现：

```python
class SpatialWorldSnapshotProvider(Protocol):
    def capture(self, request: SpatialSnapshotRequest) -> SpatialWorldSnapshot: ...

class SpatialEvidenceProvider(Protocol):
    def evaluate(
        self,
        action: SpatialActionInstance,
        snapshot: SpatialWorldSnapshot,
    ) -> SpatialEvaluation: ...

class SpatialConstraintCompiler(Protocol):
    def compile(self, evaluation: SpatialEvaluation) -> SpatialConstraintSet: ...

class SpatialAdmissionCoordinator(Protocol):
    def admit(self, request: SpatialAdmissionRequest) -> SpatialAdmissionOutcome: ...
```

测试替身必须显式命名 `FakeSpatialEvidenceProvider`，只用于 unit test；产品装配不得 silent fallback。

### 7.2 REST 只读和预览接口

建议 v1 表面：

```text
POST /api/v1/spatial/evaluations:preview
GET  /api/v1/spatial/evaluations/{evaluation_id}
GET  /api/v1/workflow-node-jobs/{job_uuid}/spatial-admission
GET  /api/v1/spatial/claims?status=active
GET  /api/v1/spatial/artifacts/{artifact_id}
```

约束：

- preview 永远 `effect=none`；
- 没有公开 `POST /claims` 或“允许执行”接口；
- Claim 只能由调度器内部 coordinator 创建；
- settlement 写接口推迟到 witness/权限/idempotency 合同冻结后；
- 错误使用 RFC 9457 Problem Details，并带稳定 reason code；
- 大 artifact 允许返回签名/受控下载引用，不把 5–50 MB JSON 塞入任务聚合。

### 7.3 SSE 和前端 services port

SSE 只发送 invalidation：

```text
event: spatial.admission.changed
data: {workflow_node_job_uuid, attempt}
```

前端在 `packages/services` 新增 `SpatialDiagnosticsPort`：

```text
getJobSpatialAdmission(jobUuid)
getSpatialEvaluation(evaluationId)
listActiveSpatialClaims()
getSpatialArtifact(artifactId)
```

Workbench 规则：

- 不直接 fetch OS/backend；
- 不根据颜色或碰撞框自行推导许可；
- 同一 MaterialAggregate/Pascal scene 叠加诊断；
- 运行时结果以 job/attempt 为入口，不再以工作区 `current.v0.json` 作为唯一权威；
- 离线文件查看器继续保留，但明显标记 offline/shadow；
- UI 显示 classification、admission status、qualification、world revision、claim/fence 和 reason。

### 7.4 同事交付包

每个可集成版本必须同时交付：

```text
contracts/spatial/v1/*.schema.json
docs/spatial-integration/quickstart.md
docs/spatial-integration/reason-codes.md
docs/spatial-integration/versioning.md
examples/ptlc-tank1/
examples/minimal-static-device/
tests/contract/spatial-v1-positive/
tests/contract/spatial-v1-negative/
```

并提供单命令合同检查：

```text
unilab spatial validate <artifact-or-binding>
unilab spatial explain <evaluation-or-admission>
```

Quickstart 必须分别给出：领域动作接入、OS provider 接入、Workbench 只读展示三条最小路径。

---

## 8. 实施阶段

### AD0——可重复基线和合同冻结

工作：

1. 修复浮点规范化，使 snapshot `--check` 跨重复运行一致；
2. 锁定 Node/pnpm 和 Python 3.11+/3.13 测试环境；
3. 把当前空间 Schema、脚本、测试、产物按仓库职责提交；
4. 冻结 v1 命名、qualification、classification、reason code；
5. 建立 JSON Schema → Python/TS 合同一致性测试。

关闭条件：

- Mac 连续三次编译字节一致；
- Windows 规范化语义一致；
- 根仓、OS、robot、FE 测试均可从干净环境运行；
- 不再存在 untracked 权威 Schema。

### AD1——通用 Evaluation 与完整 pTLC 候选干涉

工作：

1. 把单体脚本拆成 domain adapter、compiler core、artifact writer；
2. 发布 SpatialActionContract/WorldSnapshot/Evaluation v1；
3. 完成 pTLC 14 段的控制器语义台账；
4. 对可验证 MoveL/MoveJ/CP 实现连续碰撞、signed distance 和 TOI；
5. 工具、payload、allowed contact、uncertainty 进入同一评价；
6. 未覆盖部分明确 unknown。

关闭条件：

- 14 段逐段有 `evaluated` 或稳定 unknown reason；
- 不能用 sampled playback 冒充 continuous；
- 细化采样不能推翻已发现碰撞；
- 增大 uncertainty 不能减少 conflict；
- Evaluation 不含运行时 effect。

### AD2——动作冲突矩阵与 ConstraintSet

工作：

1. 建立动作实例 fingerprint；
2. 编译环境 invalid_action、动作 mutex、requires_settlement；
3. 生成 pTLC 第一黄金矩阵；
4. 与 `parallel_v1` 的业务依赖和资源声明逐格对照；
5. 输出可解释的 no-constraint/unknown，不把“没算到”写成可并行。

关闭条件：

- 每个矩阵单元可追溯到 evidence 或业务规则；
- `s2 || s3`、`s6 || s7` 的解释与专家黄金一致或明确列出分歧；
- 不自动删除专家资源；
- 变更 tool/payload/frame digest 后相关矩阵必定失效。

### AD3——WorldSnapshot 和持久 Admission Store

工作：

1. 在 WorkflowStore migration 中新增 v1 表；
2. 建立 world revision 和 active claim revision；
3. 持久 evaluation、constraint set、admission attempt；
4. 实现重启恢复和 stale/unknown 处理；
5. 增加只读 REST/SSE 投影。

关闭条件：

- job/attempt/evaluation/world revision 可完整追溯；
- 重启后仍能解释上一 attempt；
- DB 写失败不越过派发边界；
- Shadow sink 失败保持无副作用，software admission store 失败则阻断。

### AD4——原子 JobExecutionClaim

工作：

1. 实现事务外求值、事务内版本复核和 Claim；
2. 活动 Claim 冲突查询和 AdmissionRetry；
3. `project_pre_dispatch` 绑定 DispatchAuthority；
4. 调度器内部启用 `software_admission`；
5. 保留 v0 shadow 兼容但禁止混用。

关闭条件：

- 两个竞争同一 mutex resource 的 job 并发时恰好一个取得 Claim；
- world revision 在求值后变化时零 Claim、返回 retry；
- 同一 job/attempt 重试幂等；
- Claim 提交前设备适配器绝不被调用；
- unknown/conflict/DB failure 均阻止 software admission。

### AD5——Fence 与 PhysicalSettlement 跨层关联

工作：

1. 定义 DispatchAuthority 与 RobotCommand 的关联字段；
2. OS Claim 和设备 CommandJournal 建立 job/attempt/command 关联；
3. dispatch_unknown/cancel_unknown/restart 转 settlement_required；
4. witness 驱动的 PhysicalSettlement 同时解除设备 Fence 和 OS Claim；
5. WorkCellActivation 切换检查活动 Claim/Fence。

关闭条件：

- kill -9/restart 后 Claim/Fence 不丢；
- 结果不明不自动重放；
- 重复 settlement 幂等；
- 错 witness、错 command、错 generation 全部拒绝；
- UI/任务退出不能释放 Claim。

### AD6——同事 SDK、Workbench 与第二样例

工作：

1. 发布 Quickstart、reason code、示例和 contract test kit；
2. FE services port 接入 OS 只读投影；
3. Workbench 显示 job/attempt/evaluation/claim/fence；
4. 投料站至少实现一个与 pTLC 同合同的动作样例；
5. 做一次由非作者同事完成的集成演练并记录问题。

关闭条件：

- 同事只阅读 Quickstart 即可接入一个新 action binding；
- Python/TS schema conformance 全绿；
- 两个样例使用同一 evaluator/constraint/admission 接口；
- Workbench 不读取第二份运行时事实或重算许可。

### AD7——Admission Qualification 和硬件项目交接

工作：

1. 对拟启用 software admission 的有限动作完成资格清单；
2. 统计 shadow false positive/false negative、unknown 和性能；
3. 形成 admission-qualified 审批记录；
4. 输出给 PLC/安全/HIL 项目的接口和未闭合风险。

关闭条件：

- 仅白名单动作可启用 software admission；
- 回滚开关和审计完整；
- hardware_enforced 仍默认关闭；
- 没有现场证据时不生成 hardware-qualified。

---

## 9. 测试矩阵

### 9.1 合同和确定性

- Schema 正负例；
- Python/TS round-trip；
- unknown enum、绝对路径、NaN、摘要漂移失败关闭；
- `-0.0`、科学计数、浮点末位在 Mac/Windows 规范一致；
- reason code 注册表无重复和孤儿；
- v0/v1 混用拒绝。

### 9.2 几何与约束

- FK/IK、frame round-trip；
- continuous collision 与高密度采样交叉验证；
- signed distance/TOI 金样；
- allowed contact 只在声明 phase 生效；
- tool/payload attach/detach 变形测试；
- uncertainty 单调性；
- 整体刚体变换后相对结果不变；
- action matrix 对称性和有向约束例外；
- `invalid_action` 不被转换成 mutex。

### 9.3 原子性和并发

- 同资源双 job 竞争；
- 多资源获取顺序和无死锁；
- capacity N 的 N+1 竞争；
- world version race；
- claim revision race；
- DB busy/commit failure；
- evaluator timeout；
- AdmissionRetry 风暴去重；
- 同 job/attempt 幂等；
- crash/restart 恢复。

### 9.4 Fence 和结算

- adapter 调用前失败可释放；
- adapter 调用后超时必须 settlement_required；
- OS restart、设备 restart、网络断开保持 Fence；
- 错误 witness 不释放；
- Site/Material 事实不确定时不释放；
- 明确 PhysicalSettlement 后两层一致释放；
- 禁止盲目重放相同物理动作。

### 9.5 API 和 Workbench

- preview 永远无 effect；
- 前端无 Claim 写入口；
- SSE 断线后按 REST 重读；
- evaluation 大文件采用 artifact ref；
- offline 与 runtime 状态明确区分；
- 3D 只显示服务返回事实；
- console.error/pageerror、全黑截图、空场景均使 E2E 失败。

---

## 10. 交付、兼容与协作规则

### 10.1 Pull Request 拆分

建议按以下独立 PR，避免一个跨五仓巨型变更：

1. `contracts-v1`：Schema、reason code、canonical JSON、fixtures；
2. `evaluation-v1`：通用 evaluator port 和 pTLC adapter；
3. `constraints-v1`：冲突矩阵和 `parallel_v1` 对照；
4. `os-spatial-store`：migration、store、projection；
5. `os-atomic-admission`：coordinator、Claim、race tests；
6. `robot-fence-link`：DispatchAuthority 和 settlement 关联；
7. `fe-spatial-runtime`：services port 和 Workbench 只读投影；
8. `feeding-station-sample`：第二样例。

每个 PR 必须声明：输入摘要、Schema 版本、effect、资格、测试环境、未覆盖 reason 和回滚方式。

### 10.2 兼容策略

- v0 artifact 继续可被离线 Workbench 读取；
- v0 `SpatialAdmissionGate` 只保留 Shadow；
- v1 发布后不自动把 v0 certificate 升级；
- 同一 job 禁止同时使用 v0 request 和 v1 binding；
- FE 先支持 v0 offline + v1 runtime 双读，状态必须明确；
- 删除 v0 前至少完成一个发布周期和迁移报告。

### 10.3 同事集成检查单

领域同事：

- [ ] action_name 和 selector mapping 稳定；
- [ ] tool/payload/profile 有 digest；
- [ ] phase 和 allowed contact 完整；
- [ ] unsupported 能力明确 unknown；
- [ ] contract tests 通过。

OS 同事：

- [ ] 不信任调用方提交的 decision/world version；
- [ ] evaluation 在事务外；
- [ ] version/claim 复核与 Claim 同事务；
- [ ] DB/unknown/conflict 失败关闭；
- [ ] Claim/Fence 重启恢复。

前端同事：

- [ ] 只通过 services port；
- [ ] 不计算许可；
- [ ] 显示 job/attempt/world revision/qualification；
- [ ] offline/runtime 明确区分；
- [ ] 不创建第二 scene/store。

设备同事：

- [ ] command 关联 claim/fence generation；
- [ ] 结果不明进入 execution_unknown；
- [ ] 不因重复请求重放物理动作；
- [ ] 只有物理见证解除 Fence；
- [ ] hardware_enforced 默认关闭。

---

## 11. 风险与失败关闭规则

| 风险 | 失败关闭行为 |
|---|---|
| frame 未注册或 calibration 漂移 | unknown，software admission 阻断 |
| 轨迹/CP/controller 语义未覆盖 | 对该 segment unknown，不跳过 |
| 工具/payload 不明 | unknown，不假设 empty |
| evaluation 超时或崩溃 | 无 Claim、阻断/重试 |
| world snapshot 在求值后变化 | retry_required |
| Claim 竞争 | blocked/waiting，不抢占物理执行 |
| DB 写失败 | 不派发 |
| 设备派发结果不明 | settlement_required + Fence |
| OS/设备重启 | 恢复 Claim/Fence，禁止盲目重放 |
| Workbench 不可用 | 不影响权威；不能据 UI 状态释放 Claim |
| artifact 更新 | 旧 Claim 保持，新 job 重新求值 |

---

## 12. 推荐立即开始的工作

第一轮只启动 AD0 和 AD1 的前半，不同时修改调度、机器人和前端：

1. 修复 snapshot 浮点规范化与当前 Node/Python 可复测环境；
2. 冻结 `CollisionGeometryManifest/v1`、classification、qualification、reason code 和
   canonical JSON；
3. 新建碰撞资产与空间合同正负 fixture、Python/TS conformance；
4. 把 pTLC proxy 编译成带来源、误差、空腔 QC 和 qualification 的 candidate manifest；
5. 把 `compile_spatial_shadow.py` 拆成可 import 的纯函数 core 与 pTLC adapter，并改为消费
   manifest，而不是自行拼接 `collision.stl` 路径；
6. 先生成 `SpatialEvaluation/v1`，保持 `effect=none`；
7. 为 pTLC 黄金动作建立 pairwise conflict matrix 的数据结构和解释格式；
8. 在上述合同稳定后，才开始 WorkflowStore migration 和原子 Claim。

最早可以并行的工作只有：合同/fixture、算法模块化、OS migration 设计和 FE 只读类型生成。
在 classification、digest 和 reason code 冻结前，不应并行实现多个互不兼容的 runtime API。

---

## 13. 2026-08-31 第一轮实施记录

本轮已落地 Spatial-ready Asset Gate 的 pTLC candidate 纵切：

- 新增 `lab.collision-geometry-manifest/v1` Schema；
- 新增 `compile_collision_geometry_manifest.py`，绑定 15 个资产的 visual GLB、collision
  STL、frame、尺寸、空腔 QC、不确定度、来源与生成器摘要；
- JSON 来源使用 `canonical-json-v1` 摘要，Python 生成器使用 `utf8-lf-v1`，GLB/STL
  继续使用 `raw-bytes`；
- `compile_spatial_shadow.py` 已改为消费 Manifest 并复核所有传递引用，不再自行拼接
  环境 collision mesh 路径；
- Workbench snapshot 的派生浮点统一量化到 `1e-12`，当前 `--check` 可重复通过；
- Mac 目标回归 28/28 通过；Windows 在独立 detached worktree 中两次重算与 Mac
  交付件字节一致，文件 SHA-256 为
  `ca819428b95d31cb4678d34bca67d7a8e9e9245ebab4fe46994eb52aa038c1d4`；
- Manifest 内容摘要为
  `8abdc1ca14cdd771f2b35a5a420b09901b79ee3eab12d7ae7f19fc4605bc081f`。

边界保持不变：当前 15 个 pTLC 几何仍是 `collision-candidate`、允许
`offline-review/shadow`，不允许 `software-admission`。STEP/GLB 自动简化器、误差度量、
投料站 P2 人工批准与 W2 设备级导出仍待后续实施，因此 AD0 只完成资产合同与跨平台
确定性子门，不代表整个 AD0 或 AD1 关闭。
