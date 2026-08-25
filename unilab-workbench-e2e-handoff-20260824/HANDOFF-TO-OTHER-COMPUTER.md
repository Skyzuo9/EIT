# 给另一台电脑上执行 Agent 的交接任务

## 目标

在安装了 UniLab Workbench 及相关仓库的 Windows 电脑上，用本交接包完成一次可审计的端到端候选测试：重新编译五类资产、验证发布门禁、通过隔离静态夹具接入 Workbench、确认显示与稳定拾取，并形成可回传证据。

## 开始前必须记录

1. 本交接包的绝对路径。
2. UniLab Workbench 权威仓库的绝对路径、当前分支、`git rev-parse HEAD` 和 `git status --short`。
3. 相关 pTLC 或硬件仓库的绝对路径与提交（如果此次确实使用）。
4. Python、Blender、SOLIDWORKS、Node 和包管理器版本。

保留目标仓库中已有的未提交修改。不要清理、reset 或覆盖与本测试无关的文件。

## 执行顺序

1. 完整阅读 `README-FIRST.md`、本文件和 `WORKBENCH-TEST-PLAN.md`。
2. 运行 `scripts/Verify-Handoff.ps1`，传输哈希必须全部通过。
3. 运行 `scripts/00-preflight.ps1`。若失败，记录缺项；安装依赖属于操作者决定，不要静默变更全局环境。
4. 关闭已有 SOLIDWORKS，运行 `scripts/01-run-pipeline.ps1`。
5. 运行 `scripts/02-verify-output.ps1`，严格模式必须通过；`-AllowPartial` 只能用于诊断，不能算全流程通过。
6. 检查目标 Workbench 仓库，确认现有 renderer、场景运行时、静态资源服务路径和测试命令。优先复用现有 Pascal/Workbench renderer，不引入第二套 renderer。
7. 用 `scripts/03-stage-workbench-fixture.ps1` 把夹具放进独立的 `__asset_pipeline_e2e__/<RunId>/` 命名空间。不要覆盖生产模型或改名伪装现有资产。
8. 若仓库已有候选 `LabSceneRuntime`/activation loader，为测试夹具加最薄的开发态 Adapter；若还没有，只增加明确标注的测试页或开发入口。不要把 `scene-catalog.json` 宣称为 WorkCellActivation。
9. 跑目标仓库原有测试、构建和本轮 Workbench 用例；截图并记录浏览器控制台、网络错误和性能数据。
10. 填写 `templates/TEST-RESULTS.md`，运行 `scripts/04-collect-results.ps1` 生成回传 ZIP。

## Workbench 侧允许的最小改动

- 增加测试专用静态 catalog 读取 Adapter。
- 通过现有 renderer 加载 catalog 内的五个 `render-lod0.glb`。
- 把 GLB 节点/primitive 映射到 bundle 内的 `entity-registry.json` 或源 extras，支持选择后显示 family、revision、entity ID。
- 在 UI 中显示候选资格和明显的“仅显示/拾取，不可运动/互锁/执行”标识。
- 增加自动化测试或开发态路由，且默认生产入口不加载该夹具。

## 禁止事项

- 不修改或替换现有生产 `machine*.glb`。
- 不把 `previewTransform` 写成设备安装位姿或现场标定。
- 不从 STEP、包围盒、legacy URDF 或 GLB 节点名推断机械臂正式关节。
- 不生成虚构 PointSet、ProgramSet、DeployManifest 或 activation。
- 不让 Workbench 签发执行许可，不打开强制空间互锁。
- 不因前端“能动”就把能力提升为 `kinematic-preview` 或更高等级。

## 必须交付的证据

- `preflight.json`、`environment.json`、`run-summary.json`、`gate-report.json`、`REPORT.md`。
- 5 张管线预览 PNG；Workbench 中五类资产同时加载的截图。
- 至少一张拾取详情截图，能看到稳定实体或明确记录当前映射缺口。
- Workbench 仓库提交、分支、改动文件清单、执行命令及测试结果。
- 失败用例结果：无效 catalog / 缺 GLB / 能力禁止项至少各一项。
- 未完成项与下一步，不得把诊断性 partial pass 写成全流程通过。

## 成功定义

只有以下条件同时成立才记为“本轮全流程通过”：

- 交接哈希、预检和严格输出验证通过。
- 五个 family bundle 均通过 artifact hash 与 family gate。
- Workbench 从隔离 URL 加载五个 GLB，无空模型、明显异常尺度或控制台未处理异常。
- 显示与拾取符合 catalog 预期；刷新后仍加载相同 revision。
- UI 和运行时都没有启用运动、强制互锁或执行。
- 目标仓库原有测试/构建没有因本轮改动失败。

机械臂运动、真实工作流投影和空间互锁不属于这次成功定义；它们需要厂家 URDF/Xacro、部署/标定、点位/程序及碰撞资格齐全后的下一轮交接。
