# SwExactSubtreeExporter dry-run 与碰撞候选生成器

## 安全边界

`scripts/sw_exact_subtree_exporter.py` 只读取已经捕获的 occurrence snapshot，并对 P2
审批产物进行重编译校验。它不导入 COM、不启动或连接 SolidWorks、不导出几何；唯一可选
副作用是写一份 JSON receipt。请求只允许 `mode=dry-run`，任何 draft P2、摘要漂移、模糊根、
重复根或批准子树集合不一致都会失败关闭。receipt 必须保持：

- `effect=none`
- `w2_export_started=false`
- `solidworks_api_calls=0`
- `source_mutations=0`

Windows 入口为 `windows/Invoke-SwExactSubtreeDryRun.ps1`。真正的 W2 导出仍需单独批准，
不由该入口执行。

## 碰撞候选层级

`scripts/generate_collision_candidates.py` 将几何统一成米，并生成：

- L0：`aabb.glb` 与 `obb.glb`，用于宽相位。
- L1：最小体积的 box/sphere/cylinder 基本体，以及整物体 convex hull。
- L1 multi-sphere：每个连通分量生成一个解析球体，并同时输出 JSON 运行时参数与 GLB
  预览。球体必须通过漏包络、尺寸和空腔过填充门，不能只因为“包住了”就自动选中。
- L2 compound convex：对每个连通分量单独生成 convex hull。它保留分离分量之间的空隙，
  但不能保证保留单个连通分量内部的凹槽，所以报告必须结合 cavity QC 使用。
- L2 simplified static mesh：对碎片数过多的静态 CAD tessellation 做 quadric decimation；它不
  提供保守包络保证，报告使用抽样 source-to-candidate vertex distance 显式量化漏包络风险。

每个候选都输出 AABB/OBB 尺寸误差、确定性抽样顶点的漏包络半空间误差、体积型空腔保留
判断、连通 component 数、watertight/边界边/非流形边统计。

L2 还输出米制 binary STL 运行时几何和显式 `component_triangle_counts`。该分段元数据避免
STL 丢失组件名称后把互相接触但语义独立的凸体错误合并成一个非凸体。

## 候选选择与空间计算接入

`config/ptlc-collision-candidate-selection.v1.json` 是显式选择策略，Schema 为
`schemas/collision-candidate-selection-v1.schema.json`。Manifest 编译器会逐项校验：

- report / generator / runtime artifact SHA-256；
- AABB 相对尺寸误差和漏包络上限；
- watertight、空腔保留和 component 数；
- runtime STL 的 triangle 总数与组件分段。

pTLC `develop_tank_rack` 当前选择 40-component compound convex。空间计算先做 AABB 宽相，
然后将机器人三角形裁剪到每个凸体的半空间，输出
`triangle-vs-compound-convex-clipping` 接触。Workbench 快照同时携带模型来源、模式和 40 个
组件包围盒；3D/二维诊断层按组件显示，不再把整个罐架画成一个外包长方体。

STEP 输入会绑定原始 STEP 的 SHA-256，但当前版本要求同时提供明确的 GLB tessellation。
报告写明 `direct_brep_parsed=false` 和 `geometry_basis=explicit-step-tessellation-glb`；这避免在
没有 B-rep 内核时把网格适配冒充为 STEP 精确解析。后续可在相同 request/report 合同下增加
OCCT/CadQuery 后端。

## 执行

```bash
uv run --project related/unilabSZlab/asset_pipeline --with scipy \
  --with fast-simplification \
  python scripts/generate_collision_candidates.py \
  --request config/collision-candidate-develop-tank-rack.v1.json \
  --output-dir artifacts/collision-candidates/v3/develop-tank-rack
```

这些输出仅为 `offline-collision-candidate`，不能直接用于 OS 自动准入、连续碰撞判断、真机
执行或硬件安全互锁。
