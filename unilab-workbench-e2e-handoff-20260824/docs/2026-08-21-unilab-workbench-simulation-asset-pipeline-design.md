# UniLab Workbench 仿真资产管线设计：从 SolidWorks 装配体到工作流运动与空间互锁

日期：2026-08-21  
状态：候选设计（Candidate Design），用于后续架构讨论，不表示已实现或已接受  
研究基线：`Uni-Lab-OS/pTLC_platformUI` 分支 `codex/ui-upper-next-v2` 固定提交 `e6961f172926c5183fab19961635518f52bd7e47`；`Uni-Lab-OS/uni-lab-fe` 最新 Workbench 权威同步候选分支 `feat/local-296-workbench-authority-sync` 固定提交 `7124549b2cbada95faffb90645487903db136bbc`  
输入假设：项目起点通常是已装配、可在 SolidWorks 2025 中正常解析的顶层 `.SLDASM`

全文状态边界：

| 内容 | 状态 |
|---|---|
| pTLC 固定提交的 GLB、manifest、clip、前端投影和构建行为 | 当前实现（Current Implementation），有源码证据 |
| UniLab 的资产包、部署、运行时投影和空间互锁合同 | 候选设计（Candidate Design），待结合 Uni-Lab-FE/Core 定案 |
| 工作流、执行计划、作业执行占用、库位占用等术语 | 已接受领域语言；本报告不改变其定义 |

## 1. 结论先行

为了同时满足 Uni-Lab-FE Workbench 可见、工作流下发后可动，以及未来空间互锁三个目标，最终交付物不能只是一个 `.glb`。建议把系统拆成三个产品和四层数据：

1. **离线资产编译器**：从完整 SolidWorks 装配发布包生成可复现、可审计的机械仿真资产包。
2. **Workbench 场景运行时**：加载资产包与部署绑定，把预演、执行事件和设备遥测投影为三维状态。
3. **调度侧空间互锁求值器**：消费经解析的运动意图、碰撞体、扫掠包络、现场观测和作业执行占用（JobExecutionClaim），给出允许、冲突或未知；前端只展示，不授予执行权。

四层数据必须分开：

```text
SolidWorks 源发布包
        │
        ▼
机械仿真资产包（可复用、不可变）
        │
        ├── + 实验室场景部署（设备/库位/标定绑定）
        │          │
        │          ▼
        │    Workbench 场景发布
        │
        └── + 运行时事实（任务、作业尝试、遥测、占用、观测）
                   │
                   ├── 三维投影
                   └── 空间互锁求值
```

这里最重要的架构边界是：

- `.SLDASM` 是设计源，XR GLB 是几何快照；GLB 不是机械约束、控制或调度真相。
- 机械资产包描述“它是什么、怎么动、会占哪里”；部署绑定描述“实验室里的哪台设备、哪个库位使用它”；运行时描述“这一次工作流正在发生什么”。
- 工作流（Workflow）和动作（Action）不应直接靠前端猜节点名；后端应发送带版本身份的运动意图或执行投影，资产包提供确定性解析规则。
- 所谓“空间锁”不应实现成前端状态或另一个无栅栏的内存锁。候选空间互锁决定应依附于作业执行占用（JobExecutionClaim）及其栅栏语义，并且状态未知时失败关闭。
- 三维软件互锁不是机器人安全控制器、PLC 安全回路或安全认证的替代品。

## 2. 从 pTLC 学到的真实架构

### 2.1 值得保留的分离

pTLC 的最终 `machine*.glb` 明确没有 animation 和 skin；Blender 导出时设置 `export_animations=false`、`export_skins=false`，运动来自外部 manifest、点表和 clips。这种“几何与运动合同分离”适合 UniLab，因为同一几何可以被实时遥测、离线预演、工作流回放和空间计算共同使用。[`blender_clean.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/blender_clean.py#L8327-L8343)

pTLC 实际有三条汇合的编译线：

```text
几何：SLDASM → XR GLB（或 STEP 回退）→ Blender 语义重组 → 优化 GLB
绑定：rig_map + 控制配置 + 场景结构 + 标定 → device-manifest.json
运动：operation + 动作映射 + 点表 + 运动学 + 标定 → clips / indices / motion-map
```

固定提交的正式 manifest 含 13 个 stations、8 个 tanks、11 个 axes、6 个机器人关节、3 个工具、9 个 actuators、11 个 linkages、29 个 attachments 和 101 个可见状态；它把控制概念映射到具体场景节点。前端源码把 manifest 称为三维模型与上位机实时数据之间的唯一绑定契约，并在获取不到动作映射时选择不动，而不是猜测。[`device-manifest.json`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/models/device-manifest.json)、[`manifest.js`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/twin/manifest.js)、[`motionMap.js`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/demo/motionMap.js)

### 2.2 pTLC 已经证明了哪些工程方法有效

- SolidWorks 2025 XR 原生 GLB 作为首选几何入口，保留装配实例名、层级、求解后的局部变换、网格、PBR 外观与自定义属性；STEP AP214 只作回退。[`00_export_gltf.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/00_export_gltf.py)、[`pipeline.yaml`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/pipeline.yaml)
- 保留 raw、full、optimized 三类产物，既方便追溯原始装配，又让正式模型满足 Web 预算。
- `rig_map.yaml` 让工程师显式声明轴、机构、工具、载荷、工位和抓取/停放参考，而不是声称从网格自动理解机械语义。[`rig_map.yaml`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/rig_map.yaml)
- `action-motion-map.json` 由 Python 真源生成，前端只读，避免 Python/JS 各维护一份动作表。[`clip_compiler.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/clip_compiler.py#L984-L1065)
- clip 带点表哈希、机器人运动学提交、标定版本和地轨标定；浏览器校验这些指纹后才播放，说明动画也应是版本化编译结果，不是临时拼接。[`sync_ptlc_robot.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/sync_ptlc_robot.py)、[`clipSchema.js`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/anim/clipSchema.js)
- 运行时采用“连接时播种快照，随后消费增量事件”，并让实时、仿真和回放注入不同 transport/seeder/clock。这是 UniLab Workbench 复用同一投影器的重要样板。[`eventStream.js`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/twin/bindings/eventStream.js)、[`TwinFeed.js`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/twin/bindings/TwinFeed.js)
- 构建后检查体积、draw calls、三角形数和 manifest 引用节点存活，证明“能导出”与“能发布”必须分开。[`05_report.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/05_report.py)

### 2.3 不能原样复制的地方

1. **节点名充当主键。** pTLC 的清洗、材质、rig 和 manifest 大量依赖中文名称、实例后缀、路径和 Blender `.001` 后缀。名字适合显示和诊断，不适合跨 CAD 重构、LOD、合并和重新导出的稳定身份。
2. **资产与部署混在一起。** `rig_map` 同时包含机械拓扑、现场工位、库存占位、机器人型号、控制点位和 pTLC 专用标定，导致同一设备家族难以复用。
3. **无通用碰撞/物理合同。** 当前 GLB/manifest 没有通用质量、惯量、碰撞组、动态障碍或扫掠包络，不能直接用于空间互锁。
4. **动作绑定仍高度项目硬编码。** `clip_compiler.py` 内含 pTLC 工具号、动作名、站点、地轨/板点和机构常量；换项目不能只替换配置。
5. **存在坐标帧债务。** `payload-poses.json` 默认从未量化 `machine.full.glb` 求局部中心，而运行期用优化后的 `machine.official-cr5.glb`；源码审计发现 105 个载荷中 44 个偏差超过 1 mm，样品板可达约 69.8 mm。只靠“同名节点”不能保证不同产物中的局部坐标仍相同。[`export_payload_poses.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/export_payload_poses.py)
6. **门禁可被弱化。** `05_report.py` 默认可以硬失败，但 pTLC 的日常重建入口以 `--no-fail` 调用；通用发布链不能让红色报告仍进入正式发布。

### 2.4 Uni-Lab-FE 当前已经有的接缝与真实缺口

本节固定检查 `uni-lab-fe@7124549b2cbada95faffb90645487903db136bbc`。它不是要推翻当前 Workbench，而是说明新资产管线应落在哪些既有接缝上。

| 当前代码事实 | 应保留 | 还缺什么 |
|---|---|---|
| `SceneWorkbench` 从同一物料（Material）聚合取得设备模型、库位（Site）、选择和工作流转运路线，再交给同一个 Pascal 场景 | 物料聚合仍是位置/归属投影来源；不建立第二个 Material store 或第二套 renderer | 场景发布引用、资产包加载、设备机构状态和空间诊断应通过窄接口注入，而不是继续扩充页面组件 |
| `materialRenderingSnapshot` 目前只读取 `model.path/format/meshDir/macro` 等单模型字段 | 保留现有 GLB/Xacro/URDF 作为兼容输入 | 增加内容寻址的资产包/部署修订引用；`model.path` 不能继续承担机械语义、动作和碰撞合同 |
| `modelRuntime` 能加载 Xacro、URDF、GLB、STL、FBX、OBJ；GLB 路径只返回加载后的 Three.js 对象 | 复用现有加载器和 Pascal renderer | 缺稳定实体/候选连杆/候选关节绑定、绝对状态施加、clip、工具/载荷附着、碰撞和版本核验 |
| 工作流投影已经从任务冻结快照与工作流节点作业（WorkflowNodeJob）得到转运状态 | 继续复用工作流任务（WorkflowTask）/作业/反馈的权威补水链 | 不能把逻辑路线状态等同于机械轨迹；还需动作合同和部署绑定解析出的运动意图 |
| 当前转运路线由源/目标点生成固定抬高 `0.38 m` 的正交折线；`running` 时只是按页面 clock 循环移动一个小球 | 保留为“逻辑路线/流程解释”图层 | 机械臂、滑台、门和工具必须由资产机构状态驱动；小球动画不能作为观测、轨迹或空间证据 |
| 工作流实时链使用全局 SSE 失效通知后补读 Task/Jobs/feedback；设备状态通道仍是约 `1 Hz` 的 WebSocket | 工作流 SSE 继续只做低频失效通知，不塞关节帧 | 新增独立高频设备遥测投影通道，带设备/关节身份、序号、时间、新鲜度和启动世代 |

源码证据：[`SceneWorkbench.tsx`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/apps/kernel-web/src/integrations/lab-workbench/SceneWorkbench.tsx#L19-L170)、[`materialRenderingSnapshot.ts`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/pascal-lab-plugin/src/materialRenderingSnapshot.ts#L18-L63)、[`modelRuntime.ts`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/pascal-lab-plugin/src/modelRuntime.ts#L365-L445)、[`workflowMaterialTransferScene.ts`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/workflow-editor/src/utils/workflowMaterialTransferScene.ts#L44-L160)、[`materialTransferScene.ts`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/pascal-lab-plugin/src/materialTransferScene.ts#L97-L114)、[`MaterialTransferLayerRenderer.tsx`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/pascal-lab-plugin/src/renderers/MaterialTransferLayerRenderer.tsx#L277-L299)、[`WorkflowTaskController.ts`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/workflow-editor/src/runtime/WorkflowTaskController.ts#L16-L114)、[`realtime.ts`](https://github.com/Uni-Lab-OS/uni-lab-fe/blob/7124549b2cbada95faffb90645487903db136bbc/packages/services/src/realtime.ts#L1-L10)。

因此，UniLab 首版不应复制 pTLC 的独立 Three.js 页面，也不应再做一个隐藏场景。正确落点是：让现有 `SceneWorkbench → PascalLabWorkbench → Pascal/Three` 渲染链消费新的场景会话；现有工作流路线仍是一个可开关的解释图层，新的机构运动和空间诊断是另外两个运行时图层。

## 3. 建议的四层合同

### 3.1 机械仿真资产包（Mechanical Simulation Asset Bundle，候选名）

这是设备家族级、内容寻址、不可变的发布物，回答：

- 有哪些可见实体、候选刚体组（RigidGroup）、候选连杆（Link）、候选关节（Joint）和候选坐标帧（Frame）；
- 关节如何运动、限制是什么；
- 工具、载荷和停放座如何连接；
- 哪些动作合同可以映射为运动；
- 静态/动态碰撞体和候选扫掠包络是什么；
- 所有结论来自哪份 CAD、标定、控制合同和工具版本。

资产包不含具体部署的数据库 UUID、当前库位占用、当前工作流状态或执行许可。

### 3.2 实验室场景部署（Lab Scene Deployment，候选名）

这是实验室/设备实例级配置，回答：

- 资产包中的 `device_binding_key` 对应哪一个 UniLab 设备 UUID；
- 资产包中的 `site_binding_key` 对应哪一个稳定库位（Site）UUID；
- 设备基座、实验室世界坐标、机器人基座、TCP、工具和库位坐标之间的实测变换；
- 遥测通道、动作合同版本、控制 Adapter 和库位控制绑定（SiteControlBinding）是什么；
- 本部署启用了哪些工具、载荷、LOD、碰撞裕量和安全/互锁策略档。

部署可以升级标定而不重新制作全部网格，但必须生成新的不可变部署修订。

### 3.3 Workbench 场景发布（Workbench Scene Release，候选名）

它只做引用和钉版本：

```json
{
  "schema": "unilab.workbench-scene-release/v1",
  "sceneReleaseId": "sha256:...",
  "assetBundle": {"id": "ptlc-cell", "revision": "sha256:..."},
  "deployment": {"id": "lab-a/ptlc-01", "revision": "sha256:..."},
  "requiredRuntime": ">=1.0.0",
  "capabilities": ["render", "picking", "motion-preview", "telemetry-projection", "spatial-debug"]
}
```

Workbench 永远通过这个发布引用加载，不通过“某个服务器目录下最新的 machine.glb”加载。

### 3.4 运行时投影合同

运行时事件只描述本次执行，不改写资产定义：

- 工作流任务（WorkflowTask）、计划工作流节点（Planned Workflow Node）和工作流节点作业尝试（WorkflowNodeJobAttempt）的身份；
- 动作合同身份、规范化参数、设备身份、阶段、时间戳和结果；
- 设备遥测投影（DeviceTelemetryProjection）的观测值、新鲜度和来源；
- 作业执行占用（JobExecutionClaim）及空间互锁诊断引用；
- 库位占用（SiteOccupancy）、物料（Material）和物理结算（PhysicalSettlement）的权威结果。

动画、设备遥测投影或拾取操作都不能写回库位占用或替代执行权威。

## 4. 从完整 SolidWorks 装配体开始的逐阶段管线

### 阶段 A0：CAD 源发布入库

**必须输入：**

- 通过 SolidWorks Pack and Go 或等价方式收齐的顶层 `.SLDASM`、所有子装配 `.SLDASM`、零件 `.SLDPRT`、贴图/外观和引用文件；
- 指定的配置、显示状态、版本/修订、单位、抑制/隐藏策略和顶层基准坐标系；
- 人工确认的资产边界：哪些顶层实例属于静态环境、独立设备、设备内部动态机构、可换工具或可搬运载荷；
- 项目 ID、设备家族 ID、许可/保密级别和责任人；
- 可选但强烈建议：工程图、物料清单、质量属性、运动算例、控制点表和安全说明，作为后续人工审查证据。

**输出：`source-release/`**，其中包含 `source.json`（项目、修订、配置、单位、坐标、责任人）、`files.sha256`、完整 Pack and Go `cad/`、固定视角/关键机构姿态截图和机械负责人批准引用。

**硬门禁：**引用缺失、配置不明确、单位不明、轻量化组件未解析、未预期的抑制/隐藏件或源文件哈希不稳定均停止。pTLC 的老 AP203 缺三个总成，说明“能打开一个 STEP”不等于源发布完整。

这里不能默认“一份顶层装配体 = 一个运行时对象”。若输入是单台设备总装，内部可动总成应编译成该资产的候选连杆（Link）；若输入是整条产线或实验室总装，静态环境和各独立设备应编译成多个可复用资产，再由实验室场景部署组合。资产边界可以由 Agent 根据装配树、运动和命名提出候选，但最终必须由机械/系统负责人确认，否则一个巨型 GLB 会同时破坏设备复用、独立更新、选择、LOD 和空间占用生命周期。

### 阶段 A1：SolidWorks 结构与几何摄取

**输入：**A0 完整源发布、指定配置与显示状态。

**自动输出：**

1. `cad.visual.glb`：SolidWorks XR 原生导出的装配网格快照，含实例层级、求解后变换、网格、PBR 外观和可得自定义属性。
2. `assembly.snapshot.json`：不能只从 GLB 反推，应由 SolidWorks/PDM Adapter 单独提取：
   - 组件实例路径、父实例、源文档逻辑身份和配置；
   - 抑制、隐藏、轻量化/已解析状态；
   - 求解后的局部变换与单位；
   - 可获得的零件号、版本、自定义属性、材料和质量属性；
   - 可获得的 mate/自由度记录作为候选机械语义证据，但不能直接视为发布关节。
3. `cad.ap214.step`：可选审计/回退 B-rep，保留产品结构、放置和可用颜色；不作为首选 Web 几何。
4. `capture.report.json`：导出器版本、耗时、节点/网格/材质统计、空叶、未解析引用和失败清单。

**硬门禁：**每个装配实例必须进入“有网格、确认仅语义/参考、确认隐藏/抑制、单件补回、待处理”之一；待处理数必须为 0。pTLC 的 `00_export_gltf.py` 已证明空叶节点需要显式白名单和报告，不能静默丢件。

### 阶段 A2：稳定身份登记与坐标归一

**输入：**`assembly.snapshot.json`、`cad.visual.glb`、源发布哈希。

**输出：**

- `entity-registry.json`：建立不同身份空间之间的显式映射；
- `scene.source.glb`：统一为米，并保留每个实体的稳定 `scene_entity_id`；
- `frame-graph.source.json`：显式记录 CAD 世界、设备基座和 Web/glTF 根变换；
- `identity.report.json`：重复、丢失、合并、拆分和别名报告。

建议至少区分：

| 身份 | 作用 | 是否可作跨版本主键 |
|---|---|---|
| `cad_document_id` | 零件/子装配文档身份 | 有条件；需结合 PDM/修订 |
| `cad_occurrence_id` | 顶层配置中的组件实例 | 是，主来源；须验证重排/另存后的稳定性 |
| `scene_entity_id` | 可渲染/可拾取场景实体 | 是，由编译器分配并写入 GLB extras |
| `link_id` / `joint_id` / `frame_id` | 机械语义身份 | 是，人工审定后稳定 |
| 节点 `name` / path | 人类显示、规则迁移和诊断 | 否；只能作为别名 |
| `device_uuid` / `site_uuid` | UniLab 部署域身份 | 只存在于部署绑定，不进可复用资产 |

**关键规则：**LOD 简化、静态合并、Blender 重命名和 glTF 优化不得改变稳定 ID；若一个场景实体被合并，必须保留 `source_entity_ids[]` 反查，不能只留下名称和包围盒。

### 阶段 A3：几何清洗与角色分类

**输入：**`scene.source.glb`、实体登记、剪枝/补件/材质规则。

**输出：**

- `scene.cleaned.glb`：修复缺件、法线、材质、重复/无效几何后的完整场景；
- `geometry-roles.json`：每个实体被分类为 `visual`、`selection`、`collision-candidate`、`reference-only`、`flexible-unmodeled`、`excluded` 等；
- `source-to-clean.map.json`：所有源实例到清洗后实体的一对一/一对多/多对一关系；
- `clean.report.json`：删除原因、补件来源、单位修正、包围盒差和三角形差。

**人工门：**工程师审查所有删除、合并、柔性件、线缆/软管和透明/薄壁件。视觉上“不重要”的零件可能对碰撞重要，不能让渲染剪枝规则同时删除碰撞证据。

### 阶段 A4：机械拓扑与候选坐标帧创作

**输入：**清洗几何、SolidWorks 组件/mate/质量证据、设备说明、控制轴与现场标定。

**输出：`mechanics.json`**

- 候选刚体组（RigidGroup）和候选连杆（Link）的实体成员；
- 候选关节（Joint）的 parent/child、类型、轴、原点、零位、上下限、速度/加速度候选约束、mimic/耦合和闭环说明；
- `lab_world`、设备基座、机器人基座、法兰、TCP、工具安装、载荷抓取、库位停放等候选坐标帧（Frame）；
- 执行器、联动机构、工具、载荷和可附着点；
- 数据来源、拟合残差、不确定度、人工批准人和批准版本。

**不得自动定案的内容：**刚体归属、真实关节类型/轴、极限、失电行为、工具/TCP、柔性件、闭环和安全裕量。工具可以由 mate、圆柱面、组件运动和包围盒生成候选，但必须由机械/控制负责人批准。

**硬门禁：**每个动态实体只属于一个刚体；关节图连通且闭环显式；轴/枢轴和基准态残差在项目阈值内；全行程不脱离导轨；同一 `frame_id` 只有一个父坐标帧。

### 阶段 A5：Workbench 渲染与交互资产编译

**输入：**清洗几何、稳定实体、机械拓扑、材质和 Workbench 预算。

**输出：**近景 `render-lod0.glb`、Workbench 默认 `render-lod1.glb`、远景 `render-lod2.glb`、较粗的 `selection.glb`、标准缩略图、`render-map.json`（稳定实体到各 LOD 节点/primitive）和 `render.report.json`（体积、draw calls、三角形、显存估算、ID 存活）。

渲染 GLB 只负责视觉、节点层级和静态变换；运动仍由 runtime 驱动。建议继续采用 pTLC 的 `keepNamed/keepLeaves` 思路，但真正的保留条件应是稳定 ID/语义引用，而不是“有名字”。pTLC 当前预算 `≤25 MB / ≤500 primitives / ≤3,000,000 triangles` 可作为单设备第一版基准，之后应按 Uni-Lab-FE 的真实场景和目标设备重新测量。[`04_optimize.mjs`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/04_optimize.mjs)、[`05_report.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/05_report.py)

### 阶段 A6：碰撞与空间语义编译

**输入：**清洗几何、机械拓扑、工具/载荷、实验室布局候选、安全/互锁配置档。

**输出：**`collision-static.glb`、按动态 link/tool/payload 分组的 `collision-dynamic.glb`、`collision-map.json`、具名空间 `zones.json`、离散状态 `occupancy-shapes.json`、误差膨胀 `uncertainty.json` 和包含近似方法/穿透/豁免的 `collision.report.json`。

动态候选连杆（Link）优先使用凸包、凸分解、盒或胶囊；高三角网格只适合静态环境或离线精查。碰撞体必须与渲染体分离，因为渲染减面追求画质/性能，碰撞近似追求保守、稳定和可解释。

空间区不能只有一个名字。至少要记录：稳定 `zone_id`、父 `frame_id`、形状、边界包含规则、用途、允许的主体类别、默认裕量、来源和批准版本。安全区/互锁规则由安全负责人批准，CAD 自动生成只能作为候选。

### 阶段 A7：动作—运动合同与 clip 编译

**输入：**

- 已版本化的动作（Action）合同：动作身份/修订/指纹、类型化参数、设备类型、物理效果、超时与结果；
- `mechanics.json`、机器人/机构运动学、控制点表和部署标定；
- 工作流模板或执行计划的只读编译视图；
- 工具、载荷、来源/目标库位等前置状态。

**输出：**`action-motion-profile.json`（动作合同指纹到运动/无运动/未知原因）、`primitives/*.json`、确定性 `clips/*.json`、参数域和适用状态 `clip-index.json`、可选稠密/二进制 `trajectories/`，以及动作覆盖率、点表/标定哈希、IK/限位/残差 `motion.report.json`。

与 pTLC 相比，需要把“动作名字符串”升级为 `action_contract_id + revision/fingerprint`；显示名称可以改，合同指纹不匹配时必须拒绝播放。每个可能产生机械运动的动作必须属于以下三类之一：

1. 有经过验证的运动模板/clip；
2. 明确声明无三维机械运动；
3. 明确不支持并给出原因，例如目标由运行期视觉决定。

不能留第四类“前端按动作名或参数猜一根轴”。pTLC 的 `planSimulation()` 已采用正式 clip 优先、已知无运动、映射动作、未知不动的阶梯，这个失败纪律应保留。[`actionSim.js`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/demo/actionSim.js)

### 阶段 A8：扫掠包络编译

**输入：**A6 动态碰撞体、A7 运动轨迹/模板、工具和载荷状态、停止/回撤假设、不确定度。

**输出：**每个 `motion-profile-id` 生成调试用 `swept-volume.glb`、求值器用体素/凸集合/BVH 等 `swept-volume.bin`、分段时空占用 `footprint.json`，以及采样间隔、保守膨胀、连续碰撞和遗漏上界 `report.json`。

`footprint.json` 至少应包含：

- `motion_profile_id`、动作合同指纹和轨迹哈希；
- 适用的参数域、工具、载荷和起手态；
- 每一时段占用哪些 `zone_id`，以及 link/tool/payload 的扫掠形状引用；
- 轨迹采样或连续碰撞算法、位置/角度分辨率；
- CAD、安装、标定、跟踪误差和制动距离如何膨胀；
- `validated_for = preview | shadow-interlock | enforced-interlock`；
- 负责人、批准时间和过期/失效条件。

连续参数不能暴力预编所有组合时，有两条合法路径：运行时用确定性运动生成器计算并缓存，或发布覆盖整个参数域的保守包络。不得拿最接近的 clip 代替未知参数。

### 阶段 A9：部署绑定与现场标定

**输入：**机械仿真资产包候选、UniLab 设备/库位身份、控制 Adapter、现场测量和传感配置。

**输出：`scene-deployment.json`**

```json
{
  "schema": "unilab.lab-scene-deployment/v1",
  "deploymentId": "lab-a/ptlc-01",
  "assetRevision": "sha256:...",
  "frames": {
    "lab_world_to_device_base": {
      "translationM": [0.0, 0.0, 0.0],
      "quaternionXyzw": [0.0, 0.0, 0.0, 1.0],
      "evidence": "survey-2026-08-21"
    }
  },
  "devices": [{
    "bindingKey": "robot-main",
    "deviceUuid": "...",
    "actionContractSet": "sha256:...",
    "telemetryAdapter": "unilab-cr5/v1"
  }],
  "sites": [{
    "bindingKey": "rack:collector:1",
    "siteUuid": "...",
    "frameId": "site/rack/collector/1"
  }],
  "calibrationRevision": "sha256:..."
}
```

库位控制绑定（SiteControlBinding）是稳定库位到已验证控制参数的部署绑定；库位占用（SiteOccupancy）是运行时物理放置事实。两者都不应被三维资产中的默认可见状态覆盖。

**硬门禁：**资产修订、动作合同、点表、运动学、现场标定和控制 Adapter 的哈希闭合；设备/库位一一对应；坐标残差和实机低速抽验通过；部署未验证的动作只能预览，不能进入空间互锁强制模式。

### 阶段 A10：不可变打包与发布

建议最终资产包结构为：

```text
asset-bundle/
  bundle.json
  geometry/
    render-lod0.glb
    render-lod1.glb
    render-lod2.glb
    selection.glb
  semantics/
    entity-registry.json
    frame-graph.json
    mechanics.json
    attachments.json
  motion/
    action-motion-profile.json
    clip-index.json
    clips/
    trajectories/
  spatial/
    collision-static.glb
    collision-dynamic.glb
    collision-map.json
    zones.json
    occupancy-shapes.json
    motions/
  provenance/
    source.json
    files.sha256
    toolchain.lock.json
    approvals.json
  reports/
    capture.json
    identity.json
    geometry.json
    mechanics.json
    rendering.json
    motion.json
    collision.json
    spatial.json
    release.json
```

`bundle.json` 只索引版本化产物、哈希、坐标/单位和能力，不复制各子文件全部内容：

```json
{
  "schema": "unilab.sim-asset-bundle/v1",
  "assetFamilyId": "ptlc-cell",
  "revision": "sha256:...",
  "units": "m",
  "engineeringFrame": "lab_world",
  "renderFrame": "gltf_root",
  "capabilities": {
    "render": true,
    "motionPreview": true,
    "telemetryProjection": true,
    "collisionDebug": true,
    "spatialInterlockLevel": "shadow"
  },
  "artifacts": [{"role": "render-lod1", "path": "geometry/render-lod1.glb", "sha256": "..."}],
  "reports": [{"gate": "release", "path": "reports/release.json", "passed": true}]
}
```

发布服务必须使用不可变 URL/内容哈希和原子切换；不得覆盖同名 GLB 后让浏览器缓存与 manifest 进入半新半旧状态。

## 5. 坐标系合同：为运动和空间互锁先消灭裸数组

建议工程计算统一采用右手、米制、Z 轴向上的 `lab_world`；Web glTF 保持右手、米制、Y 轴向上，但必须在 `frame-graph.json` 中显式保存 `T_gltf_root_from_lab_world`。这不是要求所有工具内部都用同一上轴，而是要求每次跨工具都可复算。

任何位姿均使用带父/子帧的结构：

```json
{
  "parentFrame": "device/ptlc-01/base",
  "childFrame": "robot-main/base",
  "translationM": [0.123, 0.456, 0.789],
  "quaternionXyzw": [0.0, 0.0, 0.0, 1.0],
  "source": "survey",
  "uncertainty": {"translationMm": 0.8, "rotationDeg": 0.15}
}
```

禁止无帧的 `position: [x,y,z]` 在不同中间产物之间传递。每个派生结果必须记录它在哪个模型修订和哪个 frame 中计算；若优化器改变局部原点/scale，重新映射必须通过稳定 ID 和世界变换验证。这正是 pTLC 载荷参考帧偏差暴露出的根因。

## 6. Workbench 场景运行时应是一个深模块

Uni-Lab-FE 不应在页面组件中分别解析 GLB、mechanics、manifest、clips、碰撞和部署 YAML。建议只暴露一个很小的场景会话接口，模块内部吸收格式、缓存、LOD、绑定、插值、附着、拾取和失效处理复杂度：

```ts
interface LabSceneRuntime {
  load(release: WorkbenchSceneReleaseRef): Promise<LabSceneSession>
}

interface LabSceneSession {
  applySnapshot(snapshot: LabExecutionProjection): void
  applyEvent(event: LabExecutionProjectionEvent): void
  preview(intent: ResolvedMotionIntent): Promise<MotionPreviewResult>
  resolvePick(sceneEntityId: string): DomainReference | null
  setDebugLayer(layer: 'collision' | 'swept-volume' | 'claims' | 'uncertainty', on: boolean): void
  dispose(): void
}
```

这条接口是一处真正的模块（Module）/接口（Interface）/接缝（Seam）：

- 页面只知道“加载哪一版场景、投影什么事件、展示什么诊断”；
- Three.js/glTF、Meshopt、轨迹插值、节点绑定、工具挂载、LOD 和缓存都留在模块内部；
- 实时、仿真和回放只替换事件 transport 与 clock，沿用同一投影器；
- 未来若引入 USD/服务端碰撞，不迫使 Workbench 页面理解另一套资产细节。

只有出现真实替代实现时才再抽 `AssetResolver`、`MotionEvaluator`、`SpatialDebugProvider` 等 Port；第一版不要为每个 JSON 文件都造一个接口。

建议按现有仓库边界放置责任：

- `packages/services` 只负责取得场景发布、运行快照和实时/仿真/回放事件，不持有 Three.js 对象；
- `packages/pascal-lab-plugin` 内的场景运行时负责资产包加载、稳定实体绑定、绝对姿态、插值、附着、拾取与调试图层；它继续使用现有 Pascal renderer，不成为第二个 renderer；
- `apps/kernel-web/src/integrations/lab-workbench` 只组合物料、工作流、场景会话、选择和图层开关；
- `packages/material` 继续拥有物料聚合及静态放置，不接收高频关节帧，也不因动画改写库位（Site）或相对位置。

工作流 Task/Jobs/feedback 与高频机械状态也应保持两条数据面：前者通过现有全局 SSE 失效通知和 REST 补水形成低频运行投影；后者通过独立实时通道直接进入场景运行时。两条数据在候选已解析运动意图（`ResolvedMotionIntent`）和设备身份处关联，但不能把高频 pose 塞入工作流全局 store。

## 7. 工作流下发后，三维到底怎样运动

### 7.1 不要让前端从工作流结构猜运动

推荐链路：

```text
工作流任务
  → 计划工作流节点
  → 工作流节点作业尝试
  → 解析动作合同 + 规范化参数 + 设备/工具/载荷/库位绑定
  → ResolvedMotionIntent
       ├── Workbench 预演/执行投影
       └── 空间互锁求值
```

候选 `ResolvedMotionIntent` 至少携带：

```json
{
  "schema": "unilab.resolved-motion-intent/v1",
  "workflowTaskUuid": "...",
  "workflowNodeJobUuid": "...",
  "attempt": 2,
  "deviceUuid": "...",
  "actionContract": {"id": "robot.move", "revision": 4, "fingerprint": "sha256:..."},
  "normalizedInputs": {"targetSiteUuid": "...", "tool": "plate96"},
  "motionProfileId": "robot.move/site-transfer/v3",
  "assetRevision": "sha256:...",
  "deploymentRevision": "sha256:...",
  "expectedStartState": "sha256:..."
}
```

它是三维/空间解析输入，不是机器人指令（RobotCommand），也不是执行许可。

### 7.2 Workbench 应同时区分四种状态

| 状态 | 来源 | 画面用途 | 权威限制 |
|---|---|---|---|
| `planned` 计划态 | 编辑器/调度预演 | 工作流提交前预览、冲突说明 | 不表示会执行 |
| `commanded` 指令估计态 | 作业尝试已开始、动作事件 | 缺少高频遥测时按已验证 clip 估计进度 | 必须标“估计”，不可写库存 |
| `observed` 观测态 | 设备遥测投影 | 有新鲜遥测时驱动真实轴/关节 | 遥测是只读投影，不授予执行权 |
| `settled` 结算态 | 作业结果、库位占用、物理结算 | 更新物料/库位最终事实 | 不由动画末帧推断 |

优先级建议：新鲜高频遥测 > 动作包络估计 > 最近一次已知观测。遥测陈旧时冻结并显示未知，不继续把动画播到成功末帧；失败、取消或连接中断时保留最后观测/估计和不确定标记，不自动回 home。物料从一个库位转到另一个库位，只有库存/库位权威结算成功后才更新最终归属。

### 7.3 快照 + 可续传事件

Workbench 首次进入或重连应先取与一个 cursor/revision 对齐的场景执行快照，再从该 cursor 消费增量。事件至少包含任务/作业尝试身份、阶段、设备、动作合同指纹、时间戳、序号和资产/部署修订。只订阅 WebSocket 而没有快照会丢失页面打开前的姿态；只拉快照又没有可续传 cursor 会在重连边界重复或漏事件。pTLC 的“连接沿播种节点/物料快照，然后订阅宿主增量”可作为第一版结构，但 UniLab 应把 cursor 和任务身份做成正式合同。

## 8. 面向未来空间互锁的设计

### 8.1 先澄清术语和权威

“空间锁”目前更适合作为讨论用语。为了避免它与数据库行锁、进程锁和作业执行占用混淆，建议后续从下面两个候选术语中定案：

- **空间占用意图（SpatialClaimIntent，候选术语）**：某个已解析运动在一段时间内可能占用哪些空间资源；
- **空间互锁决定（SpatialInterlockDecision，候选术语）**：求值器基于资产、部署、当前观测和已有占用返回的允许/冲突/未知结果。

这两个术语尚未写入 UniLab 领域词汇表。无论最终命名如何，空间互锁不应另建一套与作业执行占用竞争的执行权威。更稳妥的做法是：调度器在取得/续期 JobExecutionClaim 时附带空间占用证据或引用，互锁决定绑定该 claim、attempt、资产/部署修订和 fencing token。

### 8.2 空间互锁求值器的输入/输出

```text
输入
  ResolvedMotionIntent
  + asset collision/swept-volume revision
  + deployment calibration revision
  + 当前工具/载荷/库位占用
  + 新鲜设备/环境观测
  + 活跃 JobExecutionClaim / 空间占用意图
  + 互锁策略与裕量

输出
  admitted | blocked | unknown
  + 冲突主体/zone/时间区间
  + 使用的全部版本、观测时间与不确定度
  + 对应 claim/attempt/fence
  + 可供 Workbench 展示的证明摘要
```

**失败关闭条件：**资产/部署哈希不匹配、运动动作无 footprint、工具/载荷未知、当前姿态陈旧、动态障碍观测陈旧、参数超出发布域、标定过期、求值超时或结果无法证明时返回 `unknown`，不得降级为“没有发现冲突”。

### 8.3 三维前端在空间互锁中的职责

Workbench 可以显示：

- 动态 link、工具和载荷的当前碰撞体；
- 计划轨迹与保守扫掠体；
- 已占、申请中、冲突、未知的空间区；
- 冲突对应的工作流任务、作业尝试、设备和时间段；
- 资产/标定/遥测的新鲜度与不确定膨胀；
- 互锁为何阻止或为何无法判断。

Workbench 不可以：

- 仅凭画面不相交就签发执行许可；
- 修改 GLB 节点后直接改变空间占用事实；
- 用动画末帧替代实际姿态、库位占用或物理结算；
- 绕过 PLC/机器人控制器内的硬限位、急停、速度/力限制和安全区域。

### 8.4 空间资产的版本失效规则

以下任一变化都应让旧 footprint 失效并重新编译/批准：

- 动态碰撞体、候选关节（Joint）轴/极限、机器人运动学或基座标定改变；
- 工具/TCP、载荷形状、抓取姿态或停放坐标改变；
- 动作合同、点表、运动轨迹、速度/停止模型改变；
- 安全裕量、区域形状、动态障碍策略或传感器新鲜度规则改变。

仅改变材质或不影响几何的 LOD，不应迫使重做空间资产；这要求空间合同引用稳定 `link_id/frame_id`，而不是渲染 primitive。

## 9. 发布门禁

建议形成一张机器可读的 release gate 矩阵，任何 error 都阻止正式发布：

| 门禁 | 必须证明的内容 |
|---|---|
| 源完整性 | CAD/PDM 修订、配置、依赖、单位、哈希、许可完整 |
| 实例身份 | 100% 源 occurrence 有稳定身份和明确处置；无重复/悬空映射 |
| 几何完整性 | 无意外空叶/缺件；补件和剪枝可追溯；包围盒/标准截图差异可解释 |
| 机械拓扑 | 动态实体唯一归属；关节父子、轴、零位、极限、耦合/闭环经批准 |
| 坐标链 | CAD、lab、device、robot、TCP、tool、payload、site 变换闭合且残差合格 |
| 渲染预算 | 体积、draw calls、三角形、加载时间、GPU 内存、目标 FPS 合格；稳定 ID 全存活 |
| 碰撞 | 每个动态 link/tool/payload 有碰撞体或明确豁免；静态穿透/自碰撞规则通过 |
| 动作覆盖 | 每个可能运动的动作映射、明确无运动或明确不支持；无静默未知 |
| 轨迹 | 点表/运动学/标定哈希匹配；关节限位、IK、速度和关键净空通过 |
| 扫掠 | 参数域、工具/载荷、采样/连续检查、误差膨胀和失效条件齐全 |
| 部署 | UniLab 设备/库位/控制 Adapter 一一绑定；现场低速抽验通过 |
| Workbench | 静态加载、拾取、预演、遥测、断流、失败/取消、重连和版本漂移测试通过 |
| 空间互锁 | shadow 模式样本、误报/漏报分析、未知失败关闭和 claim/fence 集成通过 |
| 可复现发布 | 干净环境重建；工具锁、全部输入/输出哈希、报告、批准和回滚版本完整 |

正式发布不得使用 `--no-fail` 类开关。允许生成“失败但可供诊断”的候选资产，但它必须存放在非正式命名空间并标明不可加载/不可互锁。

## 10. Agent 能自动做什么，必须由谁补充什么

### 10.1 适合自动化/Agent 编排

- 通过受控 Adapter 调用 SolidWorks 导出 XR GLB/AP214、遍历组件、提取属性和截图；
- 运行 Blender/OCCT/glTF Transform 完成补件、材质、LOD、稳定 ID 注入和报告；
- 从几何与 mate 生成候选刚体/关节/轴/枢轴并计算拟合残差；
- 生成凸包、凸分解、盒/胶囊碰撞候选和 swept volume；
- 从动作 schema、点表、运动学和部署标定编译 clips/footprints；
- 校验哈希、单位、坐标、关节图、IK、限位、碰撞、预算和跨产物身份；
- 在 Workbench 自动跑标准视角截图、动作回放、断流、重连和空间冲突回归。

所有自动产物都应带输入哈希、算法/工具版本、误差和可重放命令。

### 10.2 必须人工定案

| 角色 | 必须定案的事实 |
|---|---|
| 机械负责人 | 源修订/配置、刚体归属、关节/极限、柔性件、工具/载荷、碰撞近似可接受性 |
| 控制负责人 | 设备 Adapter、动作合同、轴符号/零点、反馈、TCP/工具号、点表、停止/回撤语义 |
| 流程负责人 | 工作流原子边界、物料前后态、来源/目标库位、失败/恢复和真正的业务资源 |
| 安全/互锁负责人 | 空间区、裕量、制动/下落包络、动态障碍策略、未知处理和强制模式批准 |
| 实验室管理员 | 设备/库位身份、现场布局、部署修订、资产启用/回滚与责任审批 |

Agent 不能仅凭“看起来像导轨”批准关节，也不能仅凭无碰撞仿真批准实机运动。

## 11. 建议落地顺序

### Phase 0：先冻结合同，不重做全部资产

- 定义 `bundle.json`、稳定身份、frame graph、mechanics、deployment 和 runtime event v1；
- 写 Uni-Lab-FE 的单一 `LabSceneRuntime` 加载接口；
- 做内容寻址和 schema/哈希门禁；
- 把 pTLC 现有 GLB/manifest/clips 通过临时 Adapter 包成 v1 bundle，验证接口而不是立即重建全部模型。

**完成标准：**Workbench 能按固定 revision 加载静态场景、拾取实体并反查 UniLab 设备/库位，且版本不闭合时拒绝加载。

### Phase 1：工作流驱动运动投影

- 建 `ResolvedMotionIntent` 和任务/作业尝试事件合同；
- 迁移 pTLC 的 manifest/clip/transport/clock 思路；
- 明确 planned/commanded/observed/settled 四态和遥测陈旧策略；
- 只做可视化/预演，不用于空间放行。

**完成标准：**同一工作流在预演、真实执行投影和回放中使用同一运动解析；失败/取消/断流不会假装成功或自动回 home。

### Phase 2：稳定身份和坐标链反向补齐

- 让 SolidWorks Adapter 输出组件快照与稳定 occurrence；
- 将 pTLC 名称规则迁移为稳定 ID + alias；
- 修复所有中间产物的 frame/局部坐标歧义；
- 建资产与部署两层修订。

**完成标准：**CAD 小改、LOD、合并、优化后，机械/动作/拾取引用仍闭合；跨 raw/full/optimized 的关键位姿在阈值内。

### Phase 3：碰撞与空间调试层

- 制作静态/动态碰撞体、zone、工具/载荷状态和不确定度；
- 为有限动作集编译 swept volume；
- Workbench 展示碰撞、扫掠、占用和未知原因；
- 只运行离线/影子检查。

**完成标准：**选定的机器人搬运动作可解释地显示扫掠区域；缺资产/遥测/参数时明确 unknown。

### Phase 4：调度器空间互锁 shadow mode

- 将空间占用意图接入作业执行占用及其 fencing；
- 记录“如果强制会阻止什么”，但暂不改变生产调度；
- 对照真实执行、人工复核和传感观测统计误报/漏报。

**完成标准：**互锁决定可追溯到任务、attempt、claim、资产/部署/动作版本和观测；重放可复现。

### Phase 5：有限范围强制

- 只对已批准的设备、动作、工具、载荷和部署开启 enforced；
- 其他组合继续 `preview` 或 `shadow`；
- 未知一律阻止并进入人工处置/物理结算。

**完成标准：**通过安全/控制/机械/流程联合评审、故障注入、回滚和现场验收；仍保留底层硬安全系统。

## 12. 需要后续讨论并定案的关键决策

1. Uni-Lab-FE 首版只支持 Web GLB，还是同时把 USD/URDF 作为同一中间事实的输出配置档（Profile）。
2. `lab_world` 是否正式采用 Z-up；若已有 UniLab 坐标约定，应以现有约定为准并只保留显式 frame graph 原则。
3. 动作合同身份/指纹由 Uni-Lab-Core 哪一层发布，怎样与执行计划（ExecutionPlan）和设备 Adapter 版本闭合。
4. 候选“空间占用意图/空间互锁决定”是否接受为领域术语；若接受，再更新 `CONTEXT.md`，当前报告不擅自写入。
5. 空间互锁第一批只覆盖机械臂 + 工具 + 载荷，还是同时覆盖滑台、门、抽屉和人工进入区。
6. Workbench 的场景快照、增量事件、cursor 和资产分发 API 应由 Uni-Lab-Core 还是独立资产服务承载。

## 13. 证据与复核命令

### 固定源码

- [pTLC 固定提交](https://github.com/Uni-Lab-OS/pTLC_platformUI/tree/e6961f172926c5183fab19961635518f52bd7e47)
- [三维资产管线配置](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/pipeline.yaml)
- [SolidWorks XR 导出](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/00_export_gltf.py)
- [Blender 清洗/语义节点/GLB 导出](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/blender_clean.py)
- [glTF 优化](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/04_optimize.mjs)
- [发布预算与绑定节点门禁](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/05_report.py)
- [设备 manifest 编译](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/gen_twin_manifest.py)
- [动作/流程 clip 编译](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/clip_compiler.py)
- [机器人点表/clip/索引同步](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/sync_ptlc_robot.py)
- [pTLC 前端 manifest 绑定](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/twin/manifest.js)
- [pTLC 前端事件流适配](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/twin/bindings/eventStream.js)
- [pTLC 动作预演解析](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/web/src/three-d/demo/actionSim.js)

本地复核使用 `git rev-parse` 锁定提交，以 `rg` 检查 Blender/glTF 导出和优化参数，并以 Python 标准库读取 manifest、motion-map、robot-points 和 flow-index。结果确认了 `ptlc.action-motion-map/v1`、`ptlc.robot-points/v1`、`ptlc.flow-index/v1`，以及 GLB 无 animation/skin、优化器保留具名叶节点的当前事实。
