import {
  Callout,
  Card,
  CardBody,
  CardHeader,
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
  useHostTheme,
} from "cursor/canvas";

const PIPELINE_NODES = [
  { id: "urdf" },
  { id: "sw" },
  { id: "glb" },
  { id: "ir" },
  { id: "family" },
  { id: "ctrl" },
  { id: "manifest" },
  { id: "activation" },
  { id: "wb" },
  { id: "lock" },
  { id: "run" },
];

const PIPELINE_EDGES = [
  { from: "urdf", to: "ir" },
  { from: "sw", to: "ir" },
  { from: "glb", to: "ir" },
  { from: "ir", to: "family" },
  { from: "family", to: "activation" },
  { from: "ctrl", to: "manifest" },
  { from: "manifest", to: "activation" },
  { from: "activation", to: "wb" },
  { from: "activation", to: "lock" },
  { from: "activation", to: "run" },
];

const NODE_LABEL: Record<string, string> = {
  urdf: "厂家 URDF",
  sw: "SW + STEP",
  glb: "GLB-only",
  ir: "规范 IR",
  family: "家族仿真包",
  ctrl: "控制器点表",
  manifest: "部署 Manifest",
  activation: "单元激活快照",
  wb: "Workbench",
  lock: "空间互锁",
  run: "真实执行",
};

export default function LabAssetPipelineCanvas() {
  const theme = useHostTheme();
  const layout = computeDAGLayout({
    nodes: PIPELINE_NODES,
    edges: PIPELINE_EDGES,
    direction: "horizontal",
    nodeWidth: 128,
    nodeHeight: 36,
    rankGap: 56,
    nodeGap: 28,
    padding: 8,
  });

  return (
    <Stack gap={28}>
      <Stack gap={8}>
        <H1>实验室设备家族资产管线</H1>
        <Text tone="secondary">
          家族包只证明设备类型。点位、TCP、基座和 UUID 只进入实例部署层。Workbench
          只加载激活快照。
        </Text>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat value="URDF" label="手臂运动学真源" />
        <Stat value="SW/STEP" label="仪器与货架主源" />
        <Stat value="GLB" label="默认仅视觉" />
        <Stat value="控制器" label="点位在部署层" />
      </Grid>

      <Callout tone="warning" title="越权禁止">
        PLC / 示教点、现场基座、TCP、负载、device_id、Site UUID
        不得写入通用机械臂 URDF，也不得写入仪器或货架家族包。
      </Callout>

      <H2>编译图</H2>
      <Text tone="secondary" size="small">
        上支是设备家族链，下支是部署与控制链，只在激活快照汇合。
      </Text>
      <svg
        width="100%"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        style={{ maxWidth: 960 }}
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
        {layout.nodes.map((node) => (
          <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
            <rect
              width={128}
              height={36}
              rx={6}
              fill={
                node.id === "activation" ? theme.fill.secondary : theme.bg.elevated
              }
              stroke={
                node.id === "activation" ? theme.accent.primary : theme.stroke.primary
              }
            />
            <text
              x={64}
              y={23}
              textAnchor="middle"
              fill={theme.text.primary}
              fontSize={11}
            >
              {NODE_LABEL[node.id]}
            </text>
          </g>
        ))}
      </svg>

      <H2>输入与 Adapter</H2>
      <Table
        headers={["输入", "Adapter", "进入哪一层", "默认资格"]}
        rows={[
          [
            "厂家 URDF / Xacro",
            "RobotUrdfAdapter",
            "家族包",
            "运动学预览；无现场点位",
          ],
          [
            "Pack and Go + STEP",
            "SwPackAndGoAdapter",
            "家族包",
            "装配快照；关节需人签",
          ],
          ["仅 GLB", "GlbVisualAdapter", "家族包", "visual-only"],
          [
            "臂控制器示教点",
            "RobotControllerPointAdapter",
            "该 device_id 的 Manifest",
            "PointSet 或 ProgramSet",
          ],
          [
            "工位 PLC（如有）",
            "CellPlcAdapter",
            "仪器实例 Manifest",
            "不得写入手臂 URDF",
          ],
        ]}
        rowTone={["success", "success", "warning", "info", "info"]}
        striped
      />

      <H2>点位必须拆三类</H2>
      <Grid columns={3} gap={12}>
        <Card>
          <CardHeader trailing={<Pill tone="success" size="sm">A</Pill>}>
            PointSet
          </CardHeader>
          <CardBody>
            <Text size="small">
              可导出的 TCP / 关节目标。用家族 URDF 做 FK 校验。同时给了关节和 TCP
              却超差则失败。
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="warning" size="sm">B</Pill>}>
            ProgramSet
          </CardHeader>
          <CardBody>
            <Text size="small">
              只有程序号时禁止伪造 PointSet。无合格扫掠则互锁为 unknown，禁止画直线。
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="neutral" size="sm">C</Pill>}>
            遥测
          </CardHeader>
          <CardBody>
            <Text size="small">
              当前关节只驱动 observed 姿态。不进 PointSet、ProgramSet、URDF 或调度写模型。
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <H2>GLB 资格阶梯</H2>
      <Table
        headers={["等级", "允许", "禁止"]}
        rows={[
          ["visual-only", "显示、缩略图", "运动、互锁、执行"],
          ["semantic-scene", "稳定拾取、部件映射", "当关节用"],
          ["kinematic-preview", "人工补关节后的预演", "当作已验证碰撞"],
          ["collision-qualified", "已验证碰撞与裕量", "当作现场可执行"],
          ["execution-qualified", "点位、标定、资格闭合", "无证据时宣称安全"],
        ]}
        rowTone={["neutral", "info", "warning", "warning", "success"]}
      />

      <Divider />

      <H3>相对 pTLC 的拆分</H3>
      <Row gap={8} wrap>
        <Pill tone="warning">停止整机 GLB 携带点表</Pill>
        <Pill tone="warning">停止手写臂关节</Pill>
        <Pill tone="success">CR5 / Elite xacro 钉扎可保留</Pill>
        <Pill tone="success">SW 清洗脚本降为 Adapter 细节</Pill>
      </Row>
      <Text tone="secondary" size="small">
        完整条文见仓库根目录 2026-08-23-lab-device-family-asset-pipeline.md。本轮是架构，不开始改 three_d 产物。
      </Text>
    </Stack>
  );
}
