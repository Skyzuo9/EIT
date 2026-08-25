# pTLC 三维资产、空间互锁与并行流程讨论归纳

日期：2026-08-21

对话研究对象：[`Uni-Lab-OS/pTLC_platformUI`](https://github.com/Uni-Lab-OS/pTLC_platformUI/tree/codex/ui-upper-next-v2)

源码审计固定版本：[`e6961f172926c5183fab19961635518f52bd7e47`](https://github.com/Uni-Lab-OS/pTLC_platformUI/commit/e6961f172926c5183fab19961635518f52bd7e47)

> 本文是本次对话的结构化归纳，不是逐字聊天记录。内容明确区分当前实现（Current Implementation）、已接受决策（Accepted Decision）和候选设计（Candidate Design）。机械资产领域尚未进入根词汇表的名称均标为候选，不据此建立新的规范术语。

## 1. 对话要解决的问题

本次讨论逐步聚焦到四个相互关联的问题：

1. pTLC 如何把原始 SolidWorks 装配体处理成浏览器可用的三维资产，并补出候选零件（Part）、候选连杆（Link）、候选关节（Joint）、候选点位（Point）和动作（Action）。
2. 这条资产管线建设了多久、经历了哪些阶段，以及当前能力是否能够复用到其他机械单元。
3. 排除展示效果后，三维仿真的工程价值是什么；能否根据名义轨迹、中断停止轨迹与恢复轨迹，推导库位（Site）、物料（Material）和其他机械的空间不可用约束。
4. pTLC 的 `operation` 在整个执行期间共同占用全部根资源，而专家又把完整流程拆成 `11_parallel` 的嵌套并行组合。这个结果能否由动作（Action）业务逻辑与三维空间互锁统一覆盖。

## 2. 总结论

结论可以压缩为五句话：

1. pTLC 已经形成一条有效的“CAD 几何摄取 → 人工机械语义补全 → Web 资产与动作片段编译 → 质量门禁”管线，但它不是从 SolidWorks 自动恢复完整机械模型。
2. 当前方法具有复用价值，当前制品却仍与 pTLC 的名称、工位、CR5、控制配置和动作语言强耦合；综合通用性约为 `2/5`。
3. 三维仿真的核心价值不是动画，而是生成可复核的空间证据：连续碰撞、最小间隙、名义运动走廊、中断停止包络、恢复包络和并发约束。
4. `11_parallel` 可以由“动作业务合同 + 三维空间证书 + 专家工艺裁决 + 调度器（Scheduler）原子准入”的统一框架覆盖，但不能由 3D 单独自动推出。
5. 当前 pTLC 尚无持久、带栅栏的作业执行占用（JobExecutionClaim）和物理结算（PhysicalSettlement），因此不能把现有进程内资源锁或动画预演称为安全中断覆盖。

## 3. pTLC 当前三维资产管线

### 3.1 端到端流程

```text
外部只读 SolidWorks 候选装配体（Assembly）
  ├─首选：SolidWorks 2025 XR → machine.native.glb
  └─回退：STEP 名称修复 → cascadio/OpenCascade 或 FreeCAD → machine.raw.glb
                         │
                         ▼
      Blender 清洗、裁剪、材质、站点重组与机械语义补全
      rig_map.yaml + prune_list.yaml + materials.yaml
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
 raw/minimal/full GLB       structure.json / merge-members.json
          │                             │
          └──────────────┬──────────────┘
                         ▼
  device-manifest + PointRegistry + operation/action + 固定 CR5 模型
                         │
                         ▼
  robot-points + action-motion-map + ptlc.clip/v3 动作片段
                         │
                         ▼
     glTF 优化、引用完整性/预算/帧率门禁 → Web 部署
```

### 3.2 原始装配体如何拆成零件、连杆和关节

当前 SolidWorks XR 导出的 GLB 保留实例名称、层级、局部变换、网格、PBR 材质和自定义属性，但不提供 SolidWorks mate、质量、惯量、碰撞体或控制语义。

因此实际拆解过程是：

1. 候选零件（Part）首先来自 CAD/GLB 节点；STEP 回退路径会修复乱码名称并建立可审计名称映射。
2. `rig_map.yaml` 用名称规则、精确成员、包围盒和装配关系，把节点重新归入工位、运动部件和候选刚体组（RigidGroup）。
3. `blender_clean.py` 在 Blender 中保持世界变换，重建轴滑台、执行机构、枢轴和层级。
4. 候选连杆（Link）与候选关节（Joint）是配置和工程判断的结果，不是从 GLB 自动提取的结果。
5. CR5 机械臂不直接采用 CAD 里的臂运动层级，而是使用固定版本 Dobot xacro、网格和标定数据重建六关节链。

需要特别注意：`device-manifest` 的 `linkages[]` 表示联动机构分组，并不等价于 URDF 的 `link`。

### 3.3 点位和动作来自哪里

- 候选点位（Point）来自控制仓库中的 `PointRegistry`，而不是根据三维网格自动猜测。
- 动作（Action）来自 `operation`/`action` YAML，经 `flow_discovery.py`、`clip_compiler.py` 和 `sync_ptlc_robot.py` 编译。
- `ptlc.clip/v3` 用于离线预演、回放和前端沙箱；它不构成动作（Action）授权、机器人指令（RobotCommand）或物理执行许可。
- 目标 GLB 实测不含原生 animation 或 skin；运动表达独立存在于清单与动作片段中。

### 3.4 当前生成物规模

固定版本的最终清单包含：

- 13 个工位；
- 11 条已 rig 的设备轴；
- 6 个 CR5 关节；
- 9 个执行机构；
- 11 个联动机构组；
- 29 个附件；
- 101 个状态定义；
- 7 类库存（Inventory）表现；
- 1 个主轴和 2 盏灯。

清单共引用 79 个 GLB 节点，实际 LFS 模型交叉校验为 0 个缺失引用。

## 4. 处理脚本与软件

仓库管线共清点到 40 个 Python 脚本和 4 个 MJS 脚本。以下是主链和关键工具，不重复详细报告里的逐文件清单。

| 工具或脚本 | 功能 |
|---|---|
| SolidWorks 2025 XR、`00_export_gltf.py` | 从只读 SolidWorks 装配体导出原生 GLB，并检查节点、网格、材质和异常空节点。 |
| `01_fix_step_names.py` | 修复 STEP 中的 CP936 名称，沿产品/实例关系恢复名称并生成映射报告。 |
| cascadio/OpenCascade、FreeCAD、`02_convert_step.py` | 把修复后的 STEP 转成 GLB；OpenCascade 为首选，FreeCAD 为回退。 |
| `03_clean_model.py` | 编译 Blender 作业、管理 raw/minimal/full 阶段、计算变化戳并对异常日志失败关闭。 |
| `blender_clean.py` | 执行几何清洗、裁剪、材质、站点重组、轴/枢轴/机构构建、机器人替换和结构导出。 |
| `gen_twin_manifest.py` | 从清洗后的节点树与语义配置生成 `device-manifest`。 |
| `sync_ptlc_robot.py` | 同步 CR5、点位和动作映射，校验来源摘要与运动学约束。 |
| `flow_discovery.py`、`clip_compiler.py` | 展开 `operation`/`action` 配置并编译 `ptlc.clip/v3`。 |
| `04_optimize.mjs` | 使用 glTF Transform、Draco 和 meshoptimizer 优化 Web 交付模型。 |
| `05_report.py` | 汇总几何、语义、大小和预算检查，生成验收报告。 |
| `06_hires_swap.mjs` | 在需要时替换高精度几何，同时保持语义绑定。 |

创作端还提供六个工作台：`workbench`、`materials`、`motion`、`demo`、`live`、`sim`；有 13 个 MCP 工具，其中 8 个面向 SolidWorks、5 个面向 Blender。`PartIndex` 用于零件查询和审阅，`rigPatch` 用于受控调整 rig 配置，创作后端使用白名单限制可执行操作。

主要依赖包括 SolidWorks 2025、Blender 5.2、Miniforge/Python、PyYAML、NumPy/SciPy、trimesh、cascadio/OpenCascade、pywin32/pythoncom、MCP SDK、glTF Transform 4.4.2、draco3d 1.5.7 和 meshoptimizer 1.2.0。Python 依赖尚未全部统一锁定，这是当前可复现性缺口。

## 5. 建设时间、过程与通用性

### 5.1 时间口径

- 目标提交共有 558 个可达提交；全仓历史跨 126 天，但这不是三维资产工期。
- 严格三维路径命中 29 个提交；加入 MCP、LFS、依赖和保真度支撑后为 33 个。
- Git 中直接可见的三维建设跨度是 2026-08-03 至 2026-08-17，共 `14 天 00:27:30`，但只有 5 个实际提交日。
- 首次直接提交一次导入 198 个既有文件、69,878 行、91 个前端源文件和 31 个离线测试，证明大量工作早于首次入 Git。
- 日期化文档把可证明窗口前推到 2026-07-30；现有证据只支持“至少覆盖 7 月 30 日至 8 月 17 日这 19 个日历日期”，不能据此推算人时、团队规模或真实开工日。

### 5.2 建设阶段

1. 7 月 30 日至 8 月 2 日：Git 前史，完成 STEP 名称修复、OpenCascade 转换、Blender 清理、meshopt、预算门禁、工位语义、实时绑定、UI 和 CR5/动作规划。
2. 8 月 3 日：把既有三维子系统整体落入 Git，随后开展画质和 WebGPU 试验。
3. 8 月 7 日：资产工程化，加入 SolidWorks/Blender MCP、Git LFS、清单/片段重编、动作编译、几何验证和材质能力。
4. 8 月 10 日：建立 `SimStack` 行为沙箱，并接入虚拟轴、泵、PLC 语义和物料（Material）表现。
5. 8 月 15 日至 17 日：完成观测、DVR、物料（Material）状态、机器人安全运维界面和实时/回放边界。

### 5.3 是否通用

结论是“机制可复用，设备数据和当前制品不可开箱通用”：

| 复用层 | 当前判断 |
|---|---:|
| CAD/GLB 摄取、优化、预算和浏览器检查 | `3.5/5` |
| 零件审阅、材质、候选刚体组（RigidGroup）/轴/执行器创作 | `3/5` |
| 机器人、候选点位（Point）和动作（Action）编译 | `1.5/5` |
| 实时、沙箱、DVR 和运维 UI | `2/5` |

按设备范围看，同一装配体修订复用性高，同系列设备为中，任意机械单元为低。主要耦合点是名称/路径、13 个工位、CR5/Dobot 模型、pTLC `PointRegistry`、`operation` DSL、PLC 地址和现场物料（Material）模型。

## 6. 与 SolidWorks→URDF 和 USD 管线的对比

| 能力 | pTLC GLB + manifest | SolidWorks→URDF | OpenUSD/Isaac Sim |
|---|---|---|---|
| 几何与材质 | 强，面向 Web | 强，面向机器人描述 | 强，支持多 CAD 与组合 |
| 候选连杆（Link）/候选关节（Joint） | `rig_map` + Blender 人工补全 | 用户分组组件，可结合 mate/剩余自由度配置 | 显式刚体、关节、限制、驱动和 articulation schema |
| 质量、惯量、碰撞 | 通用主链缺失 | 可从 SolidWorks body 计算和导出 | 原生物理 schema，但仍需生成、补全和验证 |
| 组合、引用、变体、延迟加载 | 能力有限，主要是整包 GLB | 非主要目标 | layer/reference/payload/variant 是核心能力 |
| 库位（Site）、物料（Material）、候选点位（Point）、动作（Action） | pTLC 最强项 | 不负责 | 可扩展表达，但不是开箱业务语义 |
| Web 交付 | 最成熟 | 需二次转换 | 需 Web 适配或流式客户端 |
| ROS 2 互操作 | 当前没有统一导出 | 原生目标 | 可导入 URDF 或建立 bridge |

三条管线不是互相替代关系：

- pTLC 提供现场语义、Web 交付、点位和动作映射；
- SolidWorks→URDF 提供机器人树、关节和物理属性的成熟导出路径；
- OpenUSD 提供大型场景组合、变体和物理场景承载能力。

推荐以格式中立的候选机械资产图（MechanicalAssetGraph，译名待对齐）为唯一编译中间表示，再分别生成 Web GLB、ROS 2 URDF/Xacro 和 OpenUSD 配置档；三个输出都不应独占事实权威。

## 7. 排除展示后的三维仿真价值

三维仿真应被拆成不同可信度的工程能力：

- 几何和坐标验证：发现单位、坐标帧、轴、枢轴、工具和载荷错误；
- 运动学验证：检查点位可达、关节限位、奇异位形和姿态；
- 连续碰撞与最小距离：发现关键帧之间的薄障碍穿透；
- 空间并发分析：计算多个动作（Action）的互斥、容量、先后和时间间隔；
- 中断与恢复分析：估计停止后仍可能扫过的空间，并建立恢复屏障；
- 标定与漂移诊断：比较 CAD、示教点、关节反馈和视觉观测；
- 回归与发布门禁：判断资产、控制器或动作（Action）版本是否扩大风险。

它输出的是模型假设内的空间证据，不是功能安全认证，也不是动作（Action）许可。

## 8. 候选三维空间互锁框架

### 8.1 基本边界

候选设计的首要原则是：几何/物理引擎只产生证据和候选占用意图（ClaimIntent），调度器（Scheduler）才有权原子取得和释放作业执行占用（JobExecutionClaim）。三维计算不得直接：

- 修改库位占用（SiteOccupancy）；
- 猜测物料（Material）身份或归属；
- 发出机器人指令（RobotCommand）；
- 宣布安全停止（Safe Stop）或物理结算（PhysicalSettlement）。

### 8.2 候选模型

以下术语均为候选，尚未进入规范词汇：

- 候选运动合同（MotionContract）：动作阶段、轨迹、工具/载荷、前后置事实、中断和恢复规则。
- 候选运动走廊（MotionCorridor）：名义轨迹扫掠体加几何、标定、跟踪和载荷误差。
- 候选停止包络（StopEnvelope）：任意时刻提出停止后，在最大响应延迟和经验证制动模型下仍可能占据的空间。
- 候选恢复包络（RecoveryEnvelope）：从已证明停止状态沿经验证并批准的恢复路径到安全状态的扫掠空间。
- 候选空间占用证书（SpatialOccupancyCertificate）：固定场景、轨迹、误差、算法、语义映射和约束结果的不可变制品。
- 候选空间资源（SpatialResource）：具有稳定部署身份的互斥区域、通道或容量区域。

动作（Action）至少应拆为：

```text
approach → acquire → transfer → release → retreat
```

取起前后的工具/载荷几何不同，允许接触对也必须按阶段生效。中断不能默认原路返回；载荷、门、库位占用（SiteOccupancy）或其他机构状态变化后，逆轨迹可能已经失效。

### 8.3 从轨迹生成约束

```text
离线：资产 + 标定 + 动作合同 + 控制器停止模型
  → 名义/停止/恢复包络模板
  → 碰撞对象稳定身份与语义映射
  → 候选空间占用证书

运行时：执行器 + 来源/目标库位 + 物料 + 工具/载荷 + 世界快照
  → 宽相筛选
  → 连续窄相碰撞与最小距离
  → 稀疏冲突超图
  → 业务占用与空间占用合并
  → 事务内复核 world_snapshot_version
  → 原子取得完整 JobExecutionClaim + Fence
```

如果分析后的世界快照或冲突已经变化，当前乐观结果作废，同一工作流节点作业尝试（WorkflowNodeJobAttempt）执行准入重试（AdmissionRetry）。

可生成的约束包括：互斥、前置、条件、容量、时间间隔和恢复屏障。约束求解器中可分别映射为 `NoOverlap`、`Cumulative`、前置不等式和可选路线；求解结果仍须基于最新快照重新准入。

### 8.4 “干涉”不能一律转成锁

- 名义轨迹与静态机架或旁观物料（Material）硬碰撞：轨迹非法，应拒绝，不能靠锁住碰撞对象继续执行。
- 来源/目标库位（Site）和被搬运物料（Material）：动作（Action）会改变事实，应进入完整作业执行占用（JobExecutionClaim）。
- 空库位（Site）的交互体被路径穿过：只表示暂时不能由其他动作进入，可映射为候选空间资源（SpatialResource）或访问键；不得伪造库位占用（SiteOccupancy）。
- 另一可运动机械的未来轨迹：形成互斥、容量或时序约束。
- 电缆、软管、液体等未建模对象：应失败关闭或转人工批准，不能当作无碰撞。

### 8.5 中断时的资源生命周期

收到取消请求不等于安全停止（Safe Stop）。若停止延迟和制动距离没有经过验证的上界，候选停止包络（StopEnvelope）必须保守扩大到整个受影响区域。

设备中断后，相关作业执行占用（JobExecutionClaim）、栅栏及空间影响必须继续保持；当物理结果不确定时进入 `execution_unknown`，禁止盲目物理重放。只有获得停止、物料（Material）、库位（Site）和设备状态证据并完成物理结算（PhysicalSettlement）后，才能释放或重新分配资源。

## 9. pTLC `operation` 与 `11_parallel` 审计

### 9.1 当前资源语义

固定版本共清点到 103 份 `operation` YAML、20 份 `action` YAML 和 93 个动作（Action）定义。`11_parallel` 含 15 份 `operation` YAML，其中 12 个生产段为 `af0 + s1..s11`，另有 3 个冒烟段。

`operation` 是一棵 mini-VM 节点树。解释器在进入根 `body` 前一次取得根 `resources`，直到整棵树正常、失败或取消退出时才释放。`run_script` 只递归执行子 `body`，不会另取子脚本根资源；因此根资源必须覆盖所有后代动作，`flowspec` 的 `R1` 会递归检查这一闭合关系。

所以用户的观察成立：`10_demo/single_sample_demo.yaml` 和 `09_full/ptlc_full_v2.yaml` 都把 13 个根资源在整个 VM 生命周期共同持有，其中包括长等待和人工门。

### 9.2 `11_parallel` 的真实结构

`11_parallel` 不是“一个 operation 内自动并行”，而是流程专家把完整流程改写成 12 个独立执行段，再由配方（Recipe）组成有向无环图：

```text
af0 -> s1 -> +-> s2 -> s4 -+-> s5 -> +-> s6 -> s8 -+-> s9 -> s10 -> s11
             \-> s3 -------/         \-> s7 -------/
```

明确的并行分支为 `s2 || s3` 和 `s6 || s7`。每段仍在整个段生命周期持有自己的根资源，但分段把长流程的大范围占用缩小成了边界清楚的小范围占用。

典型设计包括：

- `s2` 只占点样工位，`s3` 只占展开工位，二者可并行；
- `s6` 根资源为空，在长液位等待期间不占工位，只在排液分支通过 `with_resources: [station:develop]` 短时取得资源；
- `s7` 用 `occupy: [scrape-holder]` 建立跨段占位，直到 `s10` 执行 `release`；
- `flow.from/to`、`inputs/outputs` 和配方依赖保存段间的物料位置与上下文。

同一组 wrapper 也能由 `serial_v1` 串行编排，说明并行关系属于配方（Recipe）的业务决策，不是脚本语法的必然推论。

### 9.3 能否被“3D 互锁 + 动作业务逻辑”覆盖

答案是：**架构上可以覆盖，当前系统尚未覆盖，而且 3D 不能单独覆盖。**

统一的候选占用意图可表达为：

```text
ClaimIntent
  = 动作业务足迹
  ∪ 后代资源闭包
  ∪ 名义/停止/恢复空间足迹
  ∪ 执行器、物料、来源/目标库位成员
```

三维证据默认只应增加约束，不能自动删减业务声明的资源。系统需要区分三种生命周期：

1. 段根资源：覆盖整次 `operation`；
2. 词法短取资源：覆盖 `with_resources` 代码块；
3. 跨段持久物理状态：例如 `scrape-holder` 的实体占位，应由权威库位占用（SiteOccupancy）/物料（Material）事实或单独接受的持久合同表达，不能只靠临时内存锁。

三维和结构化动作（Action）合同可以推导或验证：

- 机器人、地轨、工位和交互空间冲突；
- 来源/目标库位（Site）变化和取放后的工具/载荷几何；
- `s2 || s3`、`s6 || s7` 的候选并行安全性；
- 动作段之间的互斥、容量、时间间隔和停止/恢复屏障。

它们不能独立推出：

- `s7 → s9` 的粉末去向和工艺因果；
- 化学配比、浸泡/排液时限、液位和人工决策门；
- 物料（Material）UUID、归属和库存（Inventory）事实；
- 幂等、重试、补偿和恢复授权；
- 哪些专家规则可以因吞吐优化而被改写。

流程专家仍是工艺因果规则的权威。候选编译器可以建议切点、并行边和冲突解释，但不能静默修改已冻结的执行计划（ExecutionPlan）。

### 9.4 当前 pTLC 的差距

- 资源门和派发账主要是进程内状态；
- VM 正常、失败或取消离开上下文时都会释放根资源；
- 中止会较早释放物料预留，缸和跨段占位留待人工核对；
- 当前恢复是从 YAML AID 继续的段级策略，不是经过候选停止包络（StopEnvelope）证明的物理恢复；
- 尚无持久作业执行占用（JobExecutionClaim）、栅栏和物理结算（PhysicalSettlement）。

因此 `11_parallel` 最适合作为未来候选操作分段编译器（OperationSegmentationCompiler）的人工黄金样本：编译器从全流程提出候选切点和约束，再逐条解释专家版依赖来自业务因果、空间证书、容量还是保守未知。

## 10. 候选通用机械仿真、调试与部署工具

推荐把能力组织为一个格式中立、证据驱动的编译与运行框架：

```text
CAD / URDF / USD / 控制配置 / 标定 / operation
                         │
                         ▼
 候选机械资产图 + 稳定身份 + 坐标帧 + 刚体/关节 + 物理属性
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
       Web 配置档    ROS 2 配置档   USD 配置档
       GLB+manifest  URDF/Xacro     layers/physics
             └───────────┬───────────┘
                         ▼
 动作业务合同 + 轨迹规划 + 空间约束编译 + 分段/DAG 候选生成
                         │
                         ▼
 影子分析 → 调度准入 → 硬件在环 → ROS 2 端到端 → 现场验收
```

这个工具至少需要以下边界：

- 稳定 ID 与显示名、CAD 名、GLB 路径分离；
- 视觉网格、碰撞几何、质量/惯量和控制绑定分层；
- 资产、标定、动作（Action）、轨迹和控制器停止模型均带版本与内容摘要；
- Web、URDF 和 USD 都是同一中间模型的输出配置档；
- 三维分析无副作用，只生成证书、差异和候选占用意图；
- 调度器（Scheduler）在事务内复核现场快照并取得完整、持久、带栅栏的执行权；
- 预演、运动学仿真、刚体物理仿真、影子验证、硬件在环和现场验收在产品界面中明确分级。

## 11. 建议实施顺序

1. 冻结当前三套 GLB、清单、点位、动作映射、片段索引和 `10_demo`/`11_parallel` 为黄金样本。
2. 建立稳定身份映射，停止把名称或节点路径当永久主键。
3. 为原子动作（Action）补结构化业务合同：前置/后置、读写集、效果、幂等、中断、恢复和允许接触。
4. 抽取格式中立的候选机械资产图，先保持现有 Web 输出完全一致。
5. 增加碰撞几何、质量/惯量、误差预算和控制器停止模型。
6. 以影子模式生成名义/停止/恢复空间证书，不改变当前调度结果，收集误报和漏报。
7. 把空间证据接入持久作业执行占用（JobExecutionClaim）、栅栏、`execution_unknown` 和物理结算（PhysicalSettlement）。
8. 构建候选操作分段编译器，以 `parallel_v1` 为专家黄金对照，输出“可推导、需专家裁决、无法证明”三类结果。
9. 完成失败注入、硬件在环、SZLab 原生 ROS 2 端到端门禁和现场安全验收。

## 12. 安全边界

三维分析只能证明“在给定模型、误差和场景快照内未发现空间冲突”。它不能替代安全 PLC/控制器、机械限位、围栏/门锁、急停、速度与力限制、整机风险评估、功能安全认证和现场验收。

责任链应保持为：

```text
三维分析：提供空间证据
调度器（Scheduler）：原子取得完整作业执行占用与栅栏
设备控制器：校验命令世代、范围和互锁
独立安全系统：限制或停止危险运动
物理核对：确认停止、物料和库位事实并完成结算
```

任何一层缺少证据都应失败关闭，后层不能拿前层的绿色状态替代自身责任。

## 13. 详细报告与主要证据

### 13.1 本地详细报告

- [pTLC 三维资产管线、SolidWorks→URDF 与 USD 管线研究](./2026-08-18-ptlc-asset-pipeline-urdf-usd-research.md)
- [三维空间干涉到动作约束的候选框架](./2026-08-20-spatial-interference-action-constraints-design.md)

### 13.2 pTLC 固定版本源码

- [三维目录 README](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/README.md)
- [主管线配置 `pipeline.yaml`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/pipeline.yaml)
- [机械语义配置 `rig_map.yaml`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/rig_map.yaml)
- [Blender 清洗和重组脚本](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/blender_clean.py)
- [点位/动作同步编译器](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/sync_ptlc_robot.py)
- [`single_sample_demo` 根资源](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/config/operation/10_demo/single_sample_demo.yaml#L94-L108)
- [`parallel_v1` 配方 DAG](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/config/recipes/parallel_v1.yaml#L22-L113)
- [`operation` VM 根资源生命周期](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/operation/vm/thread.py#L114-L166)
- [`flowspec` 递归资源闭合检查](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/operation/flowspec.py#L140-L187)
- [配方运行时准入检查](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/operation/scheduler.py#L778-L851)

### 13.3 对比资料

- [ROS SolidWorks→URDF Exporter 固定版本源码](https://github.com/ros/solidworks_urdf_exporter/tree/7f85cfef146e2441b380dc9975b461732bf95f84)
- [ROS 2 URDF 文档](https://docs.ros.org/en/rolling/Tutorials/Intermediate/URDF/URDF-Main.html)
- [OpenUSD Physics Schema](https://openusd.org/release/api/usd_physics_page_front.html)
- [NVIDIA Omniverse CAD Converter](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.converter.cad/207.0.10/Overview.html)
- [NVIDIA Isaac Sim URDF Importer](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/ext_isaacsim_asset_importer_urdf.html)
