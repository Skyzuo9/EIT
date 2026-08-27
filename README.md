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

## Mac 本地 CR5 / FR5 运动预览

```bash
./scripts/run_mac_kinematic_preview.sh
```

真实工站结果回传后，先执行：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/<station>/station-handoff.json
```

检查通过只说明输入完整，仍需人签工站分解与部署清单。

## 大文件

GLB、SolidWorks、STEP、STL 等二进制资产由 Git LFS 管理。原始 CAD 及厂家包可能受各自许可约束；本仓保持私有，仅用于本项目研发和验证。
