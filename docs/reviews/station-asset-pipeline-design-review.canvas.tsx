import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Code,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  computeDAGLayout,
  useCanvasAction,
  useHostTheme,
} from "cursor/canvas";

const REVIEW_FILE =
  "/Users/newtides/EIT/2026-08-25-unilab-station-asset-pipeline-design-and-plan.md";

const FINDINGS = [
  {
    severity: "Critical",
    lines: "65, 104–110, 375–376",
    finding: "把 Provider 摘要校验等同于 WorkCellActivation",
    evidence:
      "Provider 只验证型号模型；不冻结 ToolContext、PointSet/ProgramSet、碰撞环境、资格与工作流 activation ID。",
    correction:
      "保留 ActivationCompiler；Workbench 可复用 Material/Pascal 投影，但场景必须由 active activation 投影。",
  },
  {
    severity: "Critical",
    lines: "33–67, 168–185",
    finding: "把 OS Provider 描述成通用 FamilySimBundle 消费器",
    evidence:
      "它实际动态调用 Python module:symbol，不读取 bundle.json/capability.json；纯 package_static 也不会进入前端 kinematic catalog。",
    correction:
      "新增明确的 Bundle→RuntimePublication bridge：静态 GLB 走 WorkspaceMaterialModelCatalog，运动 URDF 才走 Provider。",
  },
  {
    severity: "Critical",
    lines: "211–219, 331–348",
    finding: "工作流动作到关节目标之间缺少语义解析层",
    evidence:
      "joint limits 只能约束轨迹，不能给出目标；OS action_mode=simulate 只立即返回 mock result，不发布 JointState。",
    correction:
      "在运动里程碑前加入 ResolvedMotionIntent：动作+activation→关节/笛卡尔/PointSet/ProgramSet 意图，再交给真机或仿真执行器。",
  },
  {
    severity: "High",
    lines: "103–110, 321–329",
    finding: "DeployManifest、物理图与注册表职责混合",
    evidence:
      "注册表 model 是家族/类型级；物理图仅承载实例布局子集，缺 TCP、payload、标定、点集与签署摘要。",
    correction:
      "Manifest 保持独立签署资产；编译时只投影实例节点，引用既有家族注册定义，不按实例改写注册表。",
  },
  {
    severity: "High",
    lines: "47, 324",
    finding: "“臂挂导轨”存在执行与渲染双路径差异",
    evidence:
      "执行 URDF 会把唯一 world joint 改挂到 parent mount_link；前端路径则先合成世界位姿，再通过 Material parent_link 做动态挂载，尚未证明不会双变换。",
    correction:
      "冻结 parent-mounted ABI：父挂载时 render URDF 必须是局部模型；用生产 Material 图做 rail→carriage→robot 全链 E2E。",
  },
  {
    severity: "High",
    lines: "103, 164, 322",
    finding: "物理图旋转单位写错，Manifest 坐标 ABI 未冻结",
    evidence:
      "graph_pose 读取 pose/position.rotation 为度并转换成弧度；config.rotation 不是 package graph pose 真源。",
    correction:
      "Manifest 规范使用米+四元数；编译到物理图时明确转成毫米+度，只有 Provider 调用副本使用弧度。",
  },
  {
    severity: "High",
    lines: "141–164",
    finding: "station-decomposition 仍依赖不稳定的 occurrence 名称",
    evidence:
      "当前 SW Adapter 的 id 就是 Component2.Name2；prefix 不是稳定 CAD 身份，嵌套总装还可能重名。",
    correction:
      "先采集持久引用/完整 occurrence path/config；选择器按稳定 ID，alias 只作显示。允许显式 ignore/replaced，并对重叠与遗漏失败。",
  },
  {
    severity: "High",
    lines: "132, 315",
    finding: "把工站实例数等同于家族包数",
    evidence:
      "同型号设备的多个 occurrence 应共享一个家族 digest，只生成多个部署实例。",
    correction:
      "分解输出 FamilyExtractionSet + StationInstanceLayout；按源子装配/config/authoring patch 去重家族。",
  },
  {
    severity: "High",
    lines: "45, 171–183, 335",
    finding: "semantic-scene 与 package_static 的碰撞要求不相容",
    evidence:
      "当前 bundle 明示 qualified_collision 缺失；package_static 却要求 collision 并把它加入 ROS 静态碰撞树。",
    correction:
      "未合格资产只发布视觉 GLB；只有 collision-qualified 后才进 package_static，禁止拿 render mesh 冒充碰撞体。",
  },
  {
    severity: "High",
    lines: "141–164, 306–317",
    finding: "只有设备边界，没有机构语义创作层",
    evidence:
      "SW 分组不能生成 rigid groups、per-link mesh、关节、附着帧；pTLC 的语义重挂远不止 station patterns。",
    correction:
      "新增 family-mechanics-authoring.yaml：RigidGroup、候选 joint、geometry roles、attachments；人签后才能生成 joint_state_provider。",
  },
  {
    severity: "High",
    lines: "223, 258–278",
    finding: "遗漏 Site、工具、载荷与物料挂载",
    evidence:
      "Workbench 工作流转移依赖 Material/Site 图；只有设备 GLB 与关节无法支持取放和库位投影。",
    correction:
      "把 attachments.json 投影为 DomainPackage Resource/SiteDefinition；ToolContext/payload 留在 DeployManifest。",
  },
  {
    severity: "High",
    lines: "290–304",
    finding: "M1 指定 package_moveit，但点名的 Elite 资产不完整",
    evidence:
      "本库 Elite 目录有 xacro/DAE/参数 YAML，但没有 SRDF、ros2/moveit controller 配置；package_moveit 合同要求全部字段。",
    correction:
      "先冻结完整厂家 control release；若只做预览，先用无执行权的 joint-state 模型，不要伪造 MoveIt 配置。",
  },
  {
    severity: "High",
    lines: "31, 65–90, 258–278",
    finding: "遗漏库内已经存在的 pTLC→UniLab 领域包桥",
    evidence:
      "pTLC 的 unilab_domain 已注册真实 package_moveit Provider，并用共享 GLB + gltf_subtree selector 投影 15 个设备/物料到 Material Catalog，还给出本地 Theia 启动与验证路径。",
    correction:
      "先复现并审计这条现成纵切；把 ThreeDAssetFacade、共享 blob selector、Sites 和动作代理作为迁移基线，再抽象成通用 FamilyBundle 编译器。",
  },
  {
    severity: "High",
    lines: "286–288",
    finding: "M0 把列表加载写成五资产显示完成",
    evidence:
      "本机只证明 catalog、哈希、标签与列表拾取；五个几何在 3D 视口可见、尺度正确尚未通过。",
    correction:
      "把 M0 改为 PASS_WORKBENCH_BASELINE_ONLY，并保留 W2/W3-3D 为未完成。",
  },
  {
    severity: "Medium",
    lines: "201, 217, 338–341",
    finding: "频率与 stale 行为表述不准确",
    evidence:
      "Host timer 40Hz，但 JointStateProjector 默认最多发 20Hz；前端 stale 时保留最后姿态且静默忽略，不会自动复位。",
    correction:
      "写成「40Hz drain、≤20Hz emit」；stale 时保留 last-observed、停止更新并显示 stale/模拟来源。",
  },
];

const ARCH_NODES = [
  { id: "sources" },
  { id: "ir" },
  { id: "bundle" },
  { id: "visual" },
  { id: "provider" },
  { id: "deploy" },
  { id: "activation" },
  { id: "projection" },
  { id: "material" },
  { id: "kinematic" },
  { id: "workbench" },
  { id: "workflow" },
  { id: "intent" },
  { id: "executor" },
  { id: "telemetry" },
];

const ARCH_EDGES = [
  { from: "sources", to: "ir" },
  { from: "ir", to: "bundle" },
  { from: "bundle", to: "visual" },
  { from: "bundle", to: "provider" },
  { from: "bundle", to: "activation" },
  { from: "deploy", to: "activation" },
  { from: "activation", to: "projection" },
  { from: "projection", to: "material" },
  { from: "projection", to: "kinematic" },
  { from: "material", to: "workbench" },
  { from: "kinematic", to: "workbench" },
  { from: "workflow", to: "intent" },
  { from: "activation", to: "intent" },
  { from: "intent", to: "executor" },
  { from: "executor", to: "telemetry" },
  { from: "telemetry", to: "workbench" },
];

const ARCH_LABELS: Record<string, string> = {
  sources: "SW + 厂家 URDF",
  ir: "Canonical IR",
  bundle: "FamilySimBundle",
  visual: "视觉发布 GLB",
  provider: "运动 Provider",
  deploy: "DeployManifest",
  activation: "WorkCellActivation",
  projection: "Activation Projection",
  material: "Material / Site 图",
  kinematic: "Kinematic API",
  workbench: "Pascal Workbench",
  workflow: "工作流动作",
  intent: "ResolvedMotionIntent",
  executor: "真机 / 仿真执行器",
  telemetry: "Joint telemetry",
};

const PHASES = [
  [
    "R0",
    "复现现有 pTLC 纵切并冻结契约",
    "先跑 unilab_domain 本地 Theia；随后冻结 FamilyBundle v1、digest、DomainPackage、Deploy/Activation schema",
  ],
  [
    "R1",
    "单臂纵切验证",
    "完整厂家 release → Provider/视觉模型 → Material 图 → Theia Workbench → 直接关节遥测",
  ],
  [
    "R2",
    "工站分解与家族创作",
    "稳定 occurrence ID、家族去重、显式 ignore/replaced、机构 authoring、Sites/attachments",
  ],
  [
    "R3",
    "部署与激活主干",
    "Manifest → ActivationCompiler → active projection；工作流任务冻结 activation ID",
  ],
  [
    "R4",
    "工作流运动",
    "ResolvedMotionIntent → 实机/仿真执行器 → 带来源的 telemetry；取消/失败/断流闭环",
  ],
  [
    "R5",
    "点位、工具与物料",
    "PointSet/ProgramSet、ToolContext、payload、Material/Site 父子变化",
  ],
  [
    "R6",
    "碰撞与互锁",
    "collision-qualified 后才进 package_static；shadow → 合格后强制",
  ],
];

function ArchitectureGraph() {
  const theme = useHostTheme();
  const layout = computeDAGLayout({
    nodes: ARCH_NODES,
    edges: ARCH_EDGES,
    direction: "horizontal",
    nodeWidth: 126,
    nodeHeight: 38,
    rankGap: 48,
    nodeGap: 24,
    padding: 10,
  });

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      style={{ maxWidth: 1280 }}
      aria-label="修正后的资产与运动运行时架构"
    >
      {layout.edges.map((edge) => (
        <line
          key={`${edge.from}-${edge.to}`}
          x1={edge.sourceX}
          y1={edge.sourceY}
          x2={edge.targetX}
          y2={edge.targetY}
          stroke={theme.stroke.secondary}
          strokeWidth={1.5}
        />
      ))}
      {layout.nodes.map((node) => {
        const highlighted = node.id === "activation" || node.id === "intent";
        return (
          <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
            <rect
              width={126}
              height={38}
              rx={6}
              fill={highlighted ? theme.fill.secondary : theme.bg.elevated}
              stroke={
                highlighted ? theme.accent.primary : theme.stroke.primary
              }
            />
            <text
              x={63}
              y={24}
              textAnchor="middle"
              fill={theme.text.primary}
              fontSize={10.5}
            >
              {ARCH_LABELS[node.id]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function StationAssetPipelineDesignReview() {
  const dispatch = useCanvasAction();
  const criticalCount = FINDINGS.filter(
    (finding) => finding.severity === "Critical",
  ).length;
  const highCount = FINDINGS.filter(
    (finding) => finding.severity === "High",
  ).length;

  return (
    <Stack gap={28}>
      <Stack gap={8}>
        <Row align="center" justify="space-between" wrap>
          <H1>工站资产管线设计审阅</H1>
          <Button
            variant="secondary"
            onClick={() => dispatch({ type: "openFile", path: REVIEW_FILE })}
          >
            打开原文
          </Button>
        </Row>
        <Text tone="secondary">
          审阅范围：Uni-Lab-OS、uni-lab-fe、pTLC_platformUI、2026-08-24
          交接管线及上位分层规范。
        </Text>
      </Stack>

      <Callout tone="danger" title="结论：方向正确，但当前版本不能直接进入实施">
        三个核心快捷结论不成立：Provider 不能替代 WorkCellActivation；现有
        Provider 不是 FamilySimBundle 通用加载器；工作流动作到 JointState
        之间仍缺少 ResolvedMotionIntent。先修设计，再按新里程碑实施。
      </Callout>

      <Grid columns="1.4fr 1fr" gap={20} align="start">
        <Stack gap={12}>
          <H2>保留的正确决策</H2>
          <Row gap={8} wrap>
            <Pill>厂家 URDF 是机械臂真源</Pill>
            <Pill>家族 / 部署严格分层</Pill>
            <Pill>复用单一 telemetry 渲染链</Pill>
            <Pill>不复制 pTLC 整机 GLB 发布形态</Pill>
            <Pill>失败关闭与内容摘要</Pill>
            <Pill>pTLC 节点保留和预算门禁</Pill>
          </Row>
        </Stack>
        <Card>
          <CardHeader>审阅分级</CardHeader>
          <CardBody>
            <Row gap={28}>
              <Stat value={criticalCount} label="阻塞实施" tone="danger" />
              <Stat value={highCount} label="高优先级修订" tone="warning" />
              <Stat
                value={FINDINGS.length}
                label="主要发现"
                tone="info"
              />
            </Row>
          </CardBody>
        </Card>
      </Grid>

      <H2>主要发现</H2>
      <Table
        headers={["级别", "原文行", "发现", "证据 / 影响", "精确修正"]}
        rows={FINDINGS.map((finding) => [
          <Code>{finding.severity}</Code>,
          finding.lines,
          finding.finding,
          finding.evidence,
          finding.correction,
        ])}
        rowTone={FINDINGS.map((finding) =>
          finding.severity === "Critical"
            ? "danger"
            : finding.severity === "High"
              ? "warning"
              : "info",
        )}
        striped
        stickyHeader
      />

      <Divider />

      <Stack gap={8}>
        <H2>修正后的架构</H2>
        <Text tone="secondary" size="small">
          Provider 是 Activation 的一个运行时投影，不是 Activation
          本身。静态视觉与运动学发布分开，最后在 active activation 中汇合。
        </Text>
        <ArchitectureGraph />
      </Stack>

      <Grid columns={2} gap={18} align="start">
        <Card>
          <CardHeader>资产平面</CardHeader>
          <CardBody>
            <Stack gap={8}>
              <Text>
                <Code>FamilySimBundle</Code> 同时可产生：
              </Text>
              <Text size="small">
                1. Workspace Material Model（GLB，显示/拾取）
              </Text>
              <Text size="small">
                2. Kinematic Provider（URDF，仅有正式关节时）
              </Text>
              <Text size="small">
                3. collision publication（只有 collision-qualified 时）
              </Text>
            </Stack>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>运行平面</CardHeader>
          <CardBody>
            <Stack gap={8}>
              <Text size="small">
                DeployManifest + Family digests → WorkCellActivation
              </Text>
              <Text size="small">
                Activation → Material/Site 图 + Kinematic API
              </Text>
              <Text size="small">
                Workflow + Activation → ResolvedMotionIntent → 真机/仿真
              </Text>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <H2>建议替换的里程碑</H2>
      <Table
        headers={["阶段", "主题", "完成定义"]}
        rows={PHASES}
        rowTone={[
          "danger",
          "info",
          "info",
          "warning",
          "warning",
          "neutral",
          "neutral",
        ]}
        striped
      />

      <Callout tone="warning" title="第一条纵切的正确边界">
        先证明「一个完整厂家机械臂 release → DomainPackage → 生产 Material 图 →
        Theia Workbench → 直接遥测」；不要先声称 package_moveit 可用，也不要用
        kernel-web 静态夹具替代正式 Workbench 验收。
      </Callout>

      <H3>下一步文档动作</H3>
      <Text tone="secondary">
        把原文状态从“可落地版”改为“需要修订”，逐条修复 Critical/High
        发现后，再冻结 schema 与实施仓库归属。
      </Text>
    </Stack>
  );
}
