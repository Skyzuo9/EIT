# 资产管线 UniLab

GitHub 仓库名是 `unilab-asset-pipeline`（GitHub 仓库名只能用 ASCII）；显示名与说明为 **资产管线unilab**。这是 UniLab 工站资产管线的私有总仓。它保存设计、可移植端到端交接包、测试资产、架构审阅，以及组成当前验证环境的精确代码版本。

## 仓库内容

- `2026-08-*.md`：资产管线设计、Windows 生成说明与项目讨论结论。
- `unilab-workbench-e2e-handoff-20260824/`：五类最小输入、候选家族包、静态 Workbench 夹具和验证脚本。
- `docs/reviews/`：架构审阅 Canvas 源文件。
- `related/`：本机其他与资产管线相关的快照（深圳实验室流水线、pTLC 仿真资产、domain 构建器）。详见 `related/README.md`。
- `Uni-Lab-OS/`：OS 固定版本（Git submodule）。
- `uni-lab-fe/`：Workbench 前端固定版本（Git submodule）。
- `pTLC_platformUI/`：pTLC 资产编译及 UniLab domain 桥固定版本（Git submodule）。
- `dependencies/unilab_robot_template/`：机器人领域包，包括 `unilab_arm_cr5` Provider（Git submodule）。
- `vendor/DOBOT_6Axis_ROS2_V4/`：Dobot 官方 URDF、mesh 与 MoveIt 配置，固定到审计提交（Git submodule）。
- `overlays/`：上述 submodule 在本机尚未提交的工作树改动；不会改写原仓库历史。
- `cr5-telemetry-proof/`：Mac 本地 CR5/FR5 `kinematic-preview` 证明服务；把
  `机械臂control` 中的只读厂家 ZIP 编译为摘要锁定 Provider，复用 OS 遥测合同
  与现有 Workbench renderer，不授予真机执行资格。
- `incoming/`：Windows/SolidWorks 工站结果的本地回传区；二进制内容默认不进 Git。

准备先在 Windows 完成投料站 P0–P1 时，从
[`2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](./2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)
开始。该手册给出 Windows 只读采集、非 Git handoff、Mac 独立验收和双方状态词。
Windows 已生成 win02、准备把完整交接包送回 Mac，或准备下一轮 P2/W2 协同时，使用
[`2026-08-27-feeding-station-mac-to-windows-next-handoff.md`](./2026-08-27-feeding-station-mac-to-windows-next-handoff.md)。

## 克隆

```bash
git clone --recurse-submodules https://github.com/Skyzuo9/unilab-asset-pipeline.git
cd unilab-asset-pipeline
git lfs pull
```

如果首次克隆时没有拉 submodule：

```bash
git submodule update --init --recursive
```

## 恢复本机未提交改动

先确认各 submodule 位于本仓锁定的提交，再按需应用：

```bash
git -C Uni-Lab-OS apply ../overlays/Uni-Lab-OS.patch
git -C pTLC_platformUI apply ../overlays/pTLC_platformUI.patch
git -C uni-lab-fe apply ../overlays/uni-lab-fe.patch
```

详见 `overlays/README.md`。这些 patch 是审计快照，不会在克隆后自动应用。

## 安全边界

- 家族资产证明设备类型；部署资产证明实例如何安装。
- 机械臂运动学只来自厂家 URDF/Xacro。
- `device_id`、基座位姿、TCP、payload、PointSet/ProgramSet 属于部署层。
- 静态夹具不是 `WorkCellActivation`，不授予运动、互锁或执行资格。
- 未经碰撞与部署资格验证的模型不得作为强制空间互锁依据。

## Mac 本地投料站与机器人预览

```bash
./scripts/run_mac_kinematic_preview.sh
```

当 `feeding-station-20260827-win03` 完整 handoff 在仓库根目录存在时，该命令的
正常 Workbench 主场景显示摘要锁定的完整投料站、独立模拟导轨、GCR5 CAD comparison
运动学层和 4 ml 演示瓶；CR5/GCR5/FR5 单体保留为诊断夹具。主场景公开资产合同是
UniLab Z-up，Pascal Y-up 只属于渲染内部实现。`SOLIDWORKSGLTF` 已把源 CAD 的
Z-up 转成标准 glTF Y-up，因此 GLB 在 Pascal 中保持零模型旋转；只有位置/姿态进入
Material Graph 时才转换为公开的 UniLab Z-up，禁止再对 GLB 重复施加 `Rx(-90°)`。

Demo 激活 token 从后端 descriptor 取得并原样提交：

```bash
curl -fsS http://127.0.0.1:8002/api/v1/demo-workflow/descriptor \
  | jq -c '.required_activation' \
  | curl -fsS -H 'Content-Type: application/json' --data-binary @- \
      http://127.0.0.1:8002/api/v1/demo-workflow/runs
```

该任务只运行进程内 visualization actions；Task/Job `succeeded` 不表示 PLC、ROS、
MoveIt、机器人或现场动作成功，且始终
`hardware_execution=false`、`publication_eligible=false`。

投料站 receipt、验证结果和目视验收边界见
[`2026-08-28-feeding-station-unilab-workbench-preview-report.md`](./2026-08-28-feeding-station-unilab-workbench-preview-report.md)，
尚待机械/CAD/机器人/物料负责人决定的项目见
[`2026-08-28-feeding-station-pending-decisions.md`](./2026-08-28-feeding-station-pending-decisions.md)。
Windows 复现 Demo、生成新 Task UUID 并回传截图/回执时使用
[`2026-08-28-feeding-station-mac-to-windows-demo-workflow-handoff.md`](./2026-08-28-feeding-station-mac-to-windows-demo-workflow-handoff.md)。

真实工站结果回传后，先执行：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/<station>/station-handoff.json
```

检查通过只说明输入完整，仍需人签工站分解与部署清单。

复制 `config/station-decomposition.template.yaml`，用精确 SolidWorks occurrence
`subtree_root` 完成人审后运行：

```bash
./.venv/bin/python scripts/compile_station_decomposition.py \
  incoming/<station>/station-handoff.json \
  incoming/<station>/station-decomposition.yaml \
  --output incoming/<station>/station-layout.json
```

命令同时写出 `coverage-report.json` 和 `DECOMPOSITION-REVIEW.md`。未批准草稿只可
显式加 `--allow-draft` 生成不可发布预览。

Mac 侧 P1/P2 门禁的当前实现与测试边界见
[`2026-08-27-mac-station-handoff-decomposition-v1-report.md`](./2026-08-27-mac-station-handoff-decomposition-v1-report.md)。
win03 的 Windows W1 复采结果、不可变 GLB 哈希和 Mac 两阶段验收步骤见
[`2026-08-27-feeding-station-win03-to-mac-handoff.md`](./2026-08-27-feeding-station-win03-to-mac-handoff.md)。
win03 的 Mac GLB 真实诊断已通过；Windows 封装、自检和返回完整目录时使用
[`2026-08-27-feeding-station-win03-mac-to-windows-p1-packaging-handoff.md`](./2026-08-27-feeding-station-win03-mac-to-windows-p1-packaging-handoff.md)。

Windows W2 设备级几何必须等待真实 P1 验证和 P2 人签完成。批准后复制
`config/station-geometry-export-plan.template.json`，只填写批准 layout 中的精确
`subtree_root`，准备两次独立导出的 GLB 与 node/occurrence map，再运行：

```powershell
& .\.venv\Scripts\python.exe scripts\finalize_station_geometry_handoff.py `
  --plan <staging>\geometry-export-plan.json `
  --output-root <handoff>\feeding-station-<date>-<run>-w2 `
  --station-handoff <approved-w1>\station-handoff.json `
  --decomposition <approval>\station-decomposition.yaml `
  --station-layout <approval>\station-layout.json `
  --coverage-report <approval>\coverage-report.json `
  --review <approval>\DECOMPOSITION-REVIEW.md
```

该命令重编译批准产物，并对四个首批纵切执行精确 occurrence、entity map、双导出
语义签名、单位、包围盒和硬预算门禁。Windows 当前实现状态及 win02 父图诊断见
[`2026-08-27-windows-w2-contract-development-report.md`](./2026-08-27-windows-w2-contract-development-report.md)。

## 大文件

GLB、SolidWorks、STEP、STL 等二进制资产由 Git LFS 管理。原始 CAD 及厂家包可能受各自许可约束；本仓保持私有，仅用于本项目研发和验证。
