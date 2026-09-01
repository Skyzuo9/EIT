# 2026-08-31 SwExactSubtreeExporter 与碰撞候选生成开发测试报告

## 结论

本轮完成了两个可执行纵切：

1. Windows `SwExactSubtreeExporter` 的只读 dry-run。它只解析经过 P2 审批且与摘要绑定的
   exact occurrence roots，不调用 SolidWorks API，不启动 W2，不写源 CAD。
2. 通用 GLB / STEP+tessellation 碰撞候选生成。它输出 L0 AABB/OBB、L1 基本体/凸包、
   L2 compound convex 或 simplified static mesh，以及尺寸、漏包络、空腔、component、
   watertight QC。

这两部分均仍处于离线候选资格，不能用于 OS 自动准入、真机执行或安全互锁。pTLC
罐架候选已接入 sampled-frame 环境窄相，但这不等于连续碰撞资格。

## 只读 Windows dry-run

- Windows 11 隔离 worktree：
  `E:\资产管线unilab\worktrees\unilab-spatial-assets-ad0-20260831`
- PowerShell 入口：`windows/Invoke-SwExactSubtreeDryRun.ps1`
- 合成批准夹具解析 4 个 exact roots：`RACK-1`、`RAIL-1`、`CR5-1`、
  `BOTTLE-4ML-1`。
- Mac/Windows 的 `selection_sha256` 完全相同：
  `e326806bfd19a3171d7b6794e33a0c09c5044dccda4cd9573cb82e3455241d8b`。
- Windows receipt 明确记录：`effect=none`、`w2_export_started=false`、
  `solidworks_api_calls=0`、`source_mutations=0`。
- 对真实 `feeding-station-20260827-win03` draft P2 执行时，审批门拒绝解析，且
  `current-draft-denial-receipt.json` 不存在。当前真实 P2 因此没有被升级成 W2。

证据：

- `output/sw-exact-dry-run-approved-fixture/mac-dry-run-receipt.json`
- `output/sw-exact-dry-run-approved-fixture/windows-dry-run-receipt.json`
- `output/sw-exact-dry-run-current-draft-denial/request.json`

## 真实几何案例

### pTLC develop tank rack（GLB -> compound convex）

- 源：320 vertices / 480 triangles / 40 components，watertight=true。
- L2：320 vertices / 480 triangles / 40 components，watertight=true。
- AABB 最大相对尺寸误差：0。
- 抽样漏包络误差：0 m。
- 空腔：preserved；新增填充比例约 `4.35e-17`。
- Mac/Windows L2 GLB SHA-256 完全一致：
  `cde229cfc53c56251bdb4b2a080f36d811387ca0c7caa600bc5141b46d9c40c2`。

证据：

- `artifacts/collision-candidates/v1/develop-tank-rack/collision-candidate-report.json`
- `output/windows-collision-candidates/develop-tank-rack/cross-platform-comparison.json`

### pTLC 运行时接入补充

- 生成器 v3 额外输出 multi-sphere、米制 runtime STL 与
  `component_triangle_counts`。
- 40 球候选的漏包络约 `2.78e-17 m`，但新增填充比例约 `9.56`，空腔判定
  `not-preserved`，因此选择器明确拒绝它。
- 40-component compound convex 的尺寸误差为 0、漏包络为 0、空腔保留，已由
  `config/ptlc-collision-candidate-selection.v1.json` 绑定到 CollisionGeometryManifest。
- pTLC 522 个播放帧已用混合 box + compound-convex 窄相重算；首次接触仍为
  `6.768636363636 s`，方法升级为 `triangle-vs-compound-convex-clipping`。
- Workbench 快照导出 40 个罐架组件用于 3D/二维碰撞层显示，不再只显示单一罐架外包盒。

新增证据：

- `artifacts/collision-candidates/v3/develop-tank-rack/collision-candidate-report.json`
- `artifacts/collision-assets/v1/ptlc-collision-geometry-manifest.json`
- `artifacts/spatial-shadow/v0/ptlc-tank1-environment-collision.json`
- `pTLC_platformUI/.unilab/spatial-shadow/current.v0.json`

### BigClaw（STEP + 明确 GLB tessellation -> simplified static mesh）

- 原始 STEP 与 tessellation 分别绑定 SHA-256；报告明确
  `direct_brep_parsed=false`，没有冒充 B-rep 精确解析。
- 源 tessellation：166544 vertices / 238174 triangles / 2660 components，
  watertight=false。
- Mac L2：42677 vertices / 59543 triangles / 4759 components。
- Windows L2：42578 vertices / 59544 triangles / 4799 components。
- AABB 最大相对尺寸误差约 `1.10e-5`。
- 10000 个确定性样本的 source-to-candidate vertex distance 最大约
  `0.004315 m`。该指标不提供包含保证。
- 因源与候选均非 watertight，空腔状态为 `not-measurable`，不得用于自动准入。
- 平台间 L2 不字节一致；顶点、三角形、component 相对差分别约 0.232%、
  0.00168%、0.834%，在显式比较阈值内，报告状态为
  `cross-platform-qc-equivalent`，而不是 exact match。

证据：

- `artifacts/collision-candidates/v1/bigclaw-step-reference/collision-candidate-report.json`
- `output/windows-collision-candidates/bigclaw-step-reference/cross-platform-comparison.json`

## 测试结果

- Mac 根环境回归：65 tests，60 passed，5 skipped。5 个 skip 是根环境未安装几何 extras；
  同一 5 个几何测试在专用环境全部通过。
- Mac 专用几何环境：5/5 passed。
- Windows 只读 exporter 单测：3 passed，1 skipped；skip 为隔离 worktree 未复制真实 draft。
  真实 Windows draft 拒绝另行实际执行并确认无 receipt。
- Windows 专用几何环境：5/5 passed。
- 跨平台比较器：2/2 passed。
- JSON Schema：9 个 request / receipt / report / comparison 实例全部通过 Draft 2020-12
  校验。

## 尚未完成的资格门

- 尚无获得审批的真实 feeding-station exact roots，因此不能执行真实 W2。
- STEP 当前通过显式 tessellation 适配，不是 OCCT/CadQuery B-rep 直接解析。
- BigClaw 简化候选非 watertight、漏包络近似约 4.3 mm，不是可准入碰撞体。
- 尚未把环境 compound-convex 纳入段内连续碰撞求解；当前仍是 sampled-frame 精检。
- 尚未接入 OS 原子准入或真机安全互锁。
