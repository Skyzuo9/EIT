# Windows + SOLIDWORKS 2025 资产管线调试环境指南

> 状态：候选调试指南（Candidate Debug Guide）  
> 目标系统：Windows 11 x64，已安装并激活 SOLIDWORKS 2025  
> 目标源码：`Uni-Lab-OS/pTLC_platformUI` 的 `codex/ui-upper-next-v2` 分支  
> 审计基线：`e6961f172926c5183fab19961635518f52bd7e47`  
> 编写日期：2026-08-21  
> 实机状态：本文尚未在目标 Windows 电脑上执行；命令来自固定提交源码与官方文档核对

## 0. 结论先行

这台电脑可以承担当前资产管线的完整 Windows 工作节点，但应分三步推进：

1. **先打通几何冒烟闭环**：完整 SOLIDWORKS 装配体 → XR 原生 GLB → Draco 转 Meshopt → 结构/预算报告。
2. **再复现 pTLC 清洗链**：补齐单件修复素材 → Blender `minimal/full` → glTF Transform → 严格门禁。
3. **最后接语义与运动链**：人工审查 `rig_map.yaml`、材质、候选关节/行程、库位与控制绑定，再生成 manifest 和 clips。

不要第一天就运行整条 `daily_authoring`。当前项目的 Blender 清洗依赖两类**未提交 pTLC Git 的素材**：一批要从完整 CAD 包重新导出的单件修复 GLB，以及固定提交的 DOBOT CR5 Xacro/STL。直接跳到 `03_clean_model.py` 会因素材缺失而硬失败，这是正确的失效保护。

推荐全部使用 **Windows 原生工具链**。SOLIDWORKS COM 是 Windows 进程内/本机会话能力，不建议让 WSL 直接承担 SOLIDWORKS 控制。Codex、Python、Node、Blender 和两个本地 MCP 服务均在原生 Windows 中运行，路径和进程边界最清楚。

## 1. Agent 执行合同

下面的 YAML 是给 Codex 等智能体读取的任务合同；人也可以把它当作验收清单。

```yaml
schema: unilab.asset_pipeline.windows_debug/v1
status: candidate
target:
  os: Windows 11 x64
  solidworks: "2025"
source:
  repository: https://github.com/Uni-Lab-OS/pTLC_platformUI.git
  branch: codex/ui-upper-next-v2
  commit: e6961f172926c5183fab19961635518f52bd7e47
execution:
  shell: PowerShell
  mode: native_windows
  initial_route: solidworks_xr_glb
  optional_route: step_ap214
  worktree_policy: dedicated_debug_clone
  source_cad_policy: read_only
  output_policy: never_overwrite_shared_models_during_debug
human_gates:
  - complete_pack_and_go_approved
  - assembly_configuration_and_display_state_approved
  - missing_and_lightweight_components_resolved
  - xr_export_visual_completeness_approved
  - rig_map_axes_travel_and_members_approved
  - final_geometry_and_materials_approved
stop_conditions:
  - solidworks_has_unsaved_user_documents
  - solidworks_modal_dialog_present
  - source_reference_missing_or_suppressed_unexpectedly
  - output_path_contains_non_ascii_characters
  - glb_missing_or_is_git_lfs_pointer
  - unexpected_empty_leaf_nodes
  - required_cr5_vendor_assets_missing_or_commit_mismatch
  - blender_traceback_even_when_process_exit_code_is_zero
  - report_gate_failed
  - source_commit_mismatch
known_debt:
  payload_pose_frame_mismatch: "105 个载荷中 44 个偏差 >1 mm；板类约 69.8 mm"
  safety_use: forbidden_until_fixed_and_revalidated
```

## 2. 这条管线真正需要什么输入

### 2.1 必需 CAD 输入不是一个孤立的 `.SLDASM`

应向 CAD 负责人取得一个 SOLIDWORKS **Pack and Go 完整包**，至少包含：

- 顶层装配体 `TLC设备总装.SLDASM`；
- 顶层装配引用到的全部子装配体 `.SLDASM`、零件 `.SLDPRT` 和外部引用；
- 使用的 SOLIDWORKS 配置、显示状态、抑制状态和材质/外观；
- 项目使用的纹理文件、自定义属性，以及必要的 Toolbox/供应商件副本；
- 可选但强烈建议：最新 AP214 STEP 快照，作为 XR 导出异常时的对照，而不是替代真源。

固定提交的 `SOURCE_ASSETS.yaml` 只声明了顶层装配和旧 STEP 文件名；实际导出仍要求 SOLIDWORKS 能解析整棵引用树。XR GLB 保存的是**当前求解后的渲染装配快照**，包括实例层级、名称、变换、网格和外观；它不保存可编辑 mate、B-rep、质量/惯量、碰撞体或 UniLab 控制语义。[SOLIDWORKS XR 导出说明](https://help.solidworks.com/2025/english/SolidWorks/Sldworks/t_export_using_extended_reality.htm)

### 2.2 必须由人确认的 CAD 状态

在自动化第一次运行前，CAD 工程师必须在 SOLIDWORKS GUI 中：

1. 打开顶层装配，完成重建，确认没有缺失引用；
2. 确认正确的配置和显示状态，不把需要的模块意外抑制/隐藏；
3. 将需导出的轻化组件解析为完整状态；
4. 关闭保存、重建、缺字体、缺纹理、许可等模态对话框；
5. 手工另存一次 `.glb`，确认 XR 导出功能可用；
6. 记录装配修订、配置、显示状态、文件哈希和人工批准人。

### 2.3 非 CAD 的必需输入

运行 `03_clean_model.py --stage full` 还需要：

- `pipeline/calibration/cr5_ptlc_v1.yaml`：已在固定提交中；
- `vendor/dobot-cr5-37730d08-full/cra_description/...`：不在 pTLC Git 中，必须从 DOBOT 官方 ROS2 仓库的固定提交 `37730d08b08c74061ae10d4fa5565b4c4c914885` 获取；
- `rig_map.yaml`、`materials.yaml`、`prune_list.yaml`：已在固定提交中，但仍需机械/视觉人员审查其适用性；
- motion/manifest 完整链还需要控制点表和运行时节点注册信息；几何链未跑绿前先不接入。

## 3. 软件清单与官方下载

| 软件 | 首轮是否必需 | 建议 | 用途/注意事项 |
|---|---:|---|---|
| SOLIDWORKS 2025 | 已安装 | 最新 2025 Service Pack；Windows 11 x64 优先 | CAD 真源、XR GLB、AP214；[系统要求](https://www.solidworks.com/support/system-requirements) |
| Git for Windows | 是 | 当前维护版 | 克隆固定提交；[官方下载](https://git-scm.com/install/windows) |
| Git LFS | 是 | 当前安全版本 | 拉取仓库内最终 GLB；[安装说明](https://git-lfs.com/) |
| Miniforge3 | 是 | 安装到纯 ASCII、无空格或少空格路径 | 隔离 Python；[官方项目](https://github.com/conda-forge/miniforge) |
| Python | 是 | 新环境固定 3.12.x | 项目声明 `>=3.10`；3.12 是本指南的兼容性基线，不代表原机确切版本 |
| Blender | 是 | **5.2 LTS 的固定补丁版** | 固定提交配置即指向 5.2；当前官方提供 5.2 LTS；[下载](https://www.blender.org/releases/5-2/) |
| Node.js | 是 | 先用 22 LTS；通过后再评估 24 LTS | 仓库无 `engines` 约束，项目依赖由 `package-lock.json` 锁定；[下载](https://nodejs.org/en/download) |
| Codex CLI | 推荐 | Windows 官方独立安装器 | 编排命令、代码/报告审查、连接本地 MCP；[官方仓库](https://github.com/openai/codex/blob/main/README.md?plain=1) |
| cascadio | STEP 路径才需要 | 首轮安装 `0.1.1` 后冻结 | STEP→GLB，Windows wheel 自带 OCCT；[项目页](https://pypi.org/project/cascadio/) |
| FreeCAD | 否 | 仅作 STEP 对照回退 | cascadio 结果异常时对照；[下载](https://www.freecad.org/downloads.php) |
| Khronos glTF Validator | 推荐 | 固定一个发布版本 | 独立格式门禁；[官方项目](https://github.com/KhronosGroup/glTF-Validator) |

不要全局安装 glTF Transform。固定提交的 `pipeline/package-lock.json` 已锁定 `@gltf-transform/* 4.4.2`、`meshoptimizer 1.2.0` 和 `draco3d 1.5.7`，应在管线目录运行 `npm ci`。

## 4. 目录规划

建议把工具、源码、中间产物放在纯 ASCII 路径；CAD 文件本身可保留原中文文件名，不要为了 ASCII 约束破坏 SOLIDWORKS 引用。

```text
C:\unilab\
├─ src\pTLC_platformUI\             # 独立调试 clone
├─ envs\ptlc-asset\                 # Python 环境
├─ tools\miniforge3\                # Miniforge
└─ records\                          # 本机版本/哈希/运行记录

D:\unilab-cad\eit_ptlc_station\    # Pack and Go 完整 CAD 包，只读
```

以下命令均在 **64 位 PowerShell** 执行。先定义本机变量；不要把示例路径原样照搬到不对应的磁盘。

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$AssetRoot  = "C:\unilab"
$RepoRoot   = "C:\unilab\src\pTLC_platformUI"
$EnvRoot    = "C:\unilab\envs\ptlc-asset"
$RecordRoot = "C:\unilab\records"
$CadRoot    = "D:\unilab-cad\eit_ptlc_station"
$ThreeD     = Join-Path $RepoRoot "eit_ptlc\three_d"
$Pipeline   = Join-Path $ThreeD "pipeline"
$Config     = Join-Path $Pipeline "pipeline.yaml"
$PythonExe  = Join-Path $EnvRoot "python.exe"
$BlenderExe = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

New-Item -ItemType Directory -Force -Path $AssetRoot, $RecordRoot | Out-Null
```

禁止把源码/中间目录放在 OneDrive、企业网盘同步目录或含中文的用户目录下。源码已经记录：OCCT/cascadio 的 Windows 层无法可靠打开中文中间路径，SOLIDWORKS SaveAs 对非 ASCII 输出路径还可能返回成功却不生成文件。

## 5. 安装与冻结环境

### 5.1 Git、LFS 与固定提交

安装 Git 后重新打开 PowerShell：

```powershell
git --version
git lfs version
git lfs install

git clone --branch codex/ui-upper-next-v2 --single-branch `
  https://github.com/Uni-Lab-OS/pTLC_platformUI.git $RepoRoot
git -C $RepoRoot checkout --detach e6961f172926c5183fab19961635518f52bd7e47
git -C $RepoRoot lfs pull

$ActualCommit = git -C $RepoRoot rev-parse HEAD
if ($ActualCommit -ne "e6961f172926c5183fab19961635518f52bd7e47") {
  throw "源码提交不匹配: $ActualCommit"
}
git -C $RepoRoot status --short
```

抽查 Git LFS 产物不是指针文件：

```powershell
$KnownGlb = Join-Path $ThreeD "models\machine.glb"
$Magic = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($KnownGlb), 0, 4)
if ($Magic -ne "glTF") { throw "GLB 无效或仍是 Git LFS 指针: $KnownGlb" }
```

### 5.2 Miniforge 与 Python

从 Miniforge 官方 Release 下载 `Miniforge3-Windows-x86_64.exe`，安装到 `C:\unilab\tools\miniforge3`。不要求把 conda 写入系统 PATH；脚本始终使用绝对路径。

```powershell
$CondaExe = "C:\unilab\tools\miniforge3\Scripts\conda.exe"
& $CondaExe create --prefix $EnvRoot python=3.12 pip -y
& $PythonExe -m pip install --upgrade pip

& $PythonExe -m pip install `
  "PyYAML>=6,<7" `
  "numpy>=1.26,<3" `
  "scipy>=1.12,<2" `
  "trimesh>=4,<5" `
  "pygltflib>=1.16,<2" `
  "pypinyin>=0.50,<1" `
  "pywin32==312" `
  "mcp==2.0.0" `
  "Pillow>=10,<13" `
  "pytest>=8,<10"
```

说明：固定提交没有 Python lock 文件，这意味着无法仅凭仓库精确复原合作方 Python 环境。上面是可验证的候选约束；`mcp==2.0.0` 是当前稳定 v2，源码使用的正是 v2 `MCPServer` API。[MCP Python SDK](https://pypi.org/project/mcp/) 若导入仍失败，应停止并记录实际版本，不要让智能体擅自重写 MCP 服务。STEP 回退需要时再安装：

```powershell
& $PythonExe -m pip install "cascadio==0.1.1"
```

由于 cascadio 的维护者提示旧的大体积 wheel 未来可能从 PyPI 移除，首次跑绿后应把本机 wheel 一并归档：

```powershell
& $PythonExe -m pip download --only-binary=:all: `
  --dest (Join-Path $RecordRoot "python-wheels") `
  "pywin32==312" "mcp==2.0.0" "cascadio==0.1.1"
```

### 5.3 Node 与仓库依赖

安装 Node 22 LTS 的 x64 MSI，重新打开 PowerShell：

```powershell
node --version
npm --version
Push-Location $Pipeline
npm ci
Pop-Location
```

`npm ci` 会按 `package-lock.json` 重建依赖；不要把 `npm install` 造成的锁文件变化混入本次环境调试。[npm ci 官方说明](https://docs.npmjs.com/cli/commands/npm-ci/)

### 5.4 Blender 5.2 LTS

安装 Blender 5.2 LTS 到上面的路径，或使用官方 portable ZIP 并把 `$BlenderExe` 指向实际文件。固定具体补丁版，不使用自动漂移的每日构建。

```powershell
& $BlenderExe --version
$env:BLENDER_EXE = $BlenderExe
& $PythonExe (Join-Path $ThreeD "mcp_servers\blender_mcp\selftest.py")
```

Blender 自检必须能以 `--background --factory-startup` 启动并回传结构化结果；用户插件和偏好不会参与管线。

### 5.5 Codex（推荐，不是几何转换硬依赖）

优先使用 OpenAI 官方 Windows 独立安装器，以免 Codex 与本项目 Node 版本绑死：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
codex --version
codex
```

首次运行按提示登录。Codex 能读取仓库、调用本机已安装的命令，并用 `codex exec` 编排可重复流程；它不会凭空获得 SOLIDWORKS 机械语义。[Codex CLI](https://learn.chatgpt.com/docs/codex/cli)

## 6. 将固定配置改成本机配置

先备份 `pipeline.yaml`，再只在这个**专用调试 clone**中替换三类绝对路径。全局替换旧 CAD 根目录会同时更新 `restore_geometry[].source_part`，不能只改顶层装配路径。

```powershell
Copy-Item $Config "$Config.agent-backup"

$Text = [IO.File]::ReadAllText($Config)
$Text = $Text.Replace(
  "C:/ProgramData/miniforge3/python.exe",
  $PythonExe.Replace("\", "/")
)
$Text = $Text.Replace(
  "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe",
  $BlenderExe.Replace("\", "/")
)
$Text = $Text.Replace(
  "E:/eit_lab/eit_lab_hardware/eit_ptlc_station",
  $CadRoot.Replace("\", "/")
)
[IO.File]::WriteAllText($Config, $Text, [Text.UTF8Encoding]::new($false))
```

人工复核以下键：

```yaml
paths:
  python: C:/unilab/envs/ptlc-asset/python.exe
  blender: C:/Program Files/Blender Foundation/Blender 5.2/blender.exe
  cad_root: D:/unilab-cad/eit_ptlc_station
sources:
  full_assembly: D:/unilab-cad/eit_ptlc_station/TLC设备总装.SLDASM
  native_glb: ../exports/TLC_full_native.glb
  legacy_full_step: D:/unilab-cad/eit_ptlc_station/TLC设备总装.STEP
  fresh_full_step: ../exports/TLC_full_AP214.STEP
model_source: native_glb
```

建立输出目录，并确认顶层装配存在：

```powershell
New-Item -ItemType Directory -Force -Path `
  (Join-Path $ThreeD "exports"), `
  (Join-Path $ThreeD "exports\parts"), `
  (Join-Path $ThreeD "work\debug") | Out-Null

$Assembly = Join-Path $CadRoot "TLC设备总装.SLDASM"
if (-not (Test-Path $Assembly)) { throw "缺少顶层装配: $Assembly" }
```

## 7. SOLIDWORKS COM 与 XR 导出预检

### 7.1 安全边界

- 先关闭或保存用户自己打开的文档；自动化不得替用户保存原 CAD。
- 首次调试保持 SOLIDWORKS 窗口可见，观察模态对话框和解析状态。
- 同一时刻只允许一个进程驱动同一个 SOLIDWORKS 实例。
- 脚本只读打开源文件，只关闭本次会话自己打开的文档。
- AP214 导出会涉及用户首选项；如改选项，必须在 `finally` 中恢复旧值。

### 7.2 生成 pywin32 早期绑定

必须在首次 `Dispatch("SldWorks.Application")` 前生成 `sldworks.tlb` 和 `swconst.tlb` 包装：

```powershell
$SwMcp = Join-Path $ThreeD "mcp_servers\sw_mcp"
& $PythonExe (Join-Path $SwMcp "ensure_typelib.py")
& $PythonExe (Join-Path $SwMcp "sw_core.py") info
& $PythonExe (Join-Path $ThreeD "mcp_servers\selftest_mcp.py")
```

预期结果：能够定位 SOLIDWORKS 安装目录，`GetFirstDocument2`、`GetDocuments`、`ActiveDoc`、`RevisionNumber` 均可见，MCP 两个服务能静态加载并列出工具。

若失败，可在关闭所有相关 Python/Codex 进程后运行一次：

```powershell
& $PythonExe (Join-Path $SwMcp "ensure_typelib.py") --force
```

## 8. 路径 A：XR GLB 最小调试闭环

### 8.1 导出并执行源码门禁

```powershell
Push-Location $Pipeline
& $PythonExe .\00_export_gltf.py `
  --input $Assembly `
  --output ..\exports\TLC_full_native.glb
Pop-Location
```

该步骤应生成：

- `three_d/exports/TLC_full_native.glb`；
- `three_d/work/00_export_gltf.report.json`；
- 节点、网格、材质、空叶节点统计。

不要在首轮使用 `--no-gate`。出现非白名单空叶时，先在 GUI 中定位缺失零件；不能为了“跑通”就把节点加进白名单。

### 8.2 不依赖单件素材的转码冒烟测试

原生 XR GLB 使用 Draco，而目标前端按当前实现需要 Meshopt。先用 passthrough 模式证明 Node/Draco/Meshopt 链可工作，不修改几何与层级：

```powershell
$NativeGlb = Join-Path $ThreeD "exports\TLC_full_native.glb"
$SmokeGlb  = Join-Path $ThreeD "work\debug\TLC_full_meshopt_smoke.glb"
Push-Location $Pipeline
node .\04_optimize.mjs --input $NativeGlb --output $SmokeGlb --passthrough
& $PythonExe .\05_report.py --input $SmokeGlb --no-fail
Pop-Location
```

这里允许 `--no-fail` 仅因为它是**未清洗原始模型的诊断**。必须阅读输出中的失败项，不能把退出码 0 当作发布通过。

### 8.3 人工检查点

至少比较 SOLIDWORKS GUI、原生 GLB 和转码 GLB：

- 顶层模块数量和相对位置；
- 机械臂、门、滑台、传送、泵、塔灯等大件是否缺失；
- 透明件、金属件、颜色和纹理是否合理；
- 原点、单位、朝向、包围盒和异常远离主体的游离几何；
- 实例名称与层级是否仍可用于后续绑定。

## 9. 路径 A2：复现 Blender 清洗链

### 9.1 先生成缺件修复素材

固定配置的 `restore_geometry` 含多条 `source_part → exports/parts/*.glb` 规则，输出文件必须是 ASCII 名。先列出清单：

```powershell
Push-Location $Pipeline
& $PythonExe .\export_part_assets.py --list
& $PythonExe .\export_part_assets.py
Pop-Location
```

任何 `source_part` 不存在都说明 Pack and Go 不完整或路径替换错误，应停止。CAD 修订变化后才使用 `--force` 全量重导。

### 9.2 获取固定版本的 CR5 官方模型

`rig_map.yaml` 明确指定了 [DOBOT 官方 ROS2 仓库](https://github.com/Dobot-Arm/DOBOT_6Axis_ROS2_V4)及提交。用独立 clone 取出 `cra_description`，不要下载来历不明的 STL，也不要用其他版本覆盖：

```powershell
$RobotRepo = "C:\unilab\src\DOBOT_6Axis_ROS2_V4"
$RobotCommit = "37730d08b08c74061ae10d4fa5565b4c4c914885"
$RobotVendor = Join-Path $ThreeD "vendor\dobot-cr5-37730d08-full"

git clone https://github.com/Dobot-Arm/DOBOT_6Axis_ROS2_V4.git $RobotRepo
git -C $RobotRepo checkout --detach $RobotCommit
if ((git -C $RobotRepo rev-parse HEAD) -ne $RobotCommit) {
  throw "DOBOT 机器人源码提交不匹配"
}

New-Item -ItemType Directory -Force -Path $RobotVendor | Out-Null
Copy-Item (Join-Path $RobotRepo "cra_description") $RobotVendor -Recurse

$RobotXacro = Join-Path $RobotVendor "cra_description\urdf\cr5_robot.xacro"
$RobotMeshes = Join-Path $RobotVendor "cra_description\meshes\cr5"
if (-not (Test-Path $RobotXacro)) { throw "缺少 CR5 xacro: $RobotXacro" }
if ((Get-ChildItem $RobotMeshes -Filter *.STL -File).Count -lt 7) {
  throw "CR5 STL 不完整: $RobotMeshes"
}
```

复制后的 `vendor` 是可再生本机输入，不要直接提交 pTLC。证据包应记录 DOBOT 提交号和七个 STL 的 SHA-256。

### 9.3 清洗、优化、严格门禁

先使用独立 debug 名称，不覆盖仓库中的 `models/machine.glb`：

```powershell
$CleanGlb = Join-Path $ThreeD "work\debug\machine.full.clean.glb"
$FinalGlb = Join-Path $ThreeD "work\debug\machine.full.optimized.glb"

Push-Location $Pipeline
& $PythonExe .\03_clean_model.py `
  --stage full `
  --input ..\exports\TLC_full_native.glb `
  --output $CleanGlb
node .\04_optimize.mjs `
  --input $CleanGlb `
  --output $FinalGlb `
  --no-join
& $PythonExe .\05_report.py --input $FinalGlb
Pop-Location
```

本次严格验收**不得**加 `--no-fail`。此外，`03_clean_model.py` 已专门检查一种 Blender 异常：Blender 进程退出码可能为 0，但控制台含 Python traceback；这种情况仍算失败。

`--no-join` 是调试期保守选择，用于最大程度保留节点。确认 manifest 需要的执行器节点都存活后，再按正式构建参数评估是否合并。

## 10. 路径 B：STEP/AP214 回退

只有 XR 导出不可用、层级/外观异常，或需要独立 CAD 交换对照时启用 STEP。AP214 不是 XR GLB 的等价替代，也不会恢复 mate、惯量、碰撞和控制语义。

```powershell
$StepOut   = Join-Path $ThreeD "exports\TLC_full_AP214.STEP"
$NamedStep = Join-Path $ThreeD "work\debug\TLC_full_AP214_named.STEP"
$RawGlb    = Join-Path $ThreeD "work\debug\TLC_full_AP214_named.raw.glb"

& $PythonExe (Join-Path $SwMcp "export_ap214.py") `
  --input $Assembly `
  --name "TLC_full_AP214.STEP" `
  --ap 214

Push-Location $Pipeline
& $PythonExe .\01_fix_step_names.py `
  --input $StepOut `
  --output $NamedStep
& $PythonExe .\02_convert_step.py `
  --input $NamedStep `
  --output $RawGlb `
  --engine cascadio
Pop-Location
```

关键限制：

- `01` 修复 STEP 内可能以 cp936 写入的中文，并把产品名回填到装配实例；
- `02` 的输入、输出、中间目录都必须是 ASCII 路径；
- 旧 AP203 STEP 已知无颜色且缺总成，不能用来判断 XR 输出是否正确；
- fresh AP214 与 XR 路径应分别保留报告，不要覆盖同名产物。

## 11. 让 Codex/Agent 控制工具

### 11.1 能自动化什么

Codex 可以通过命令行和仓库自带 MCP 服务完成：

- 检查版本、路径、Git 提交、LFS 和依赖；
- 只读检查装配树，调用 XR GLB/AP214 导出；
- 启动无头 Blender，检查模型、渲染预览、执行清洗；
- 运行 glTF Transform、报告、测试、哈希和环境冻结；
- 比较各阶段节点/三角形/材质/尺寸变化并整理失败证据。

### 11.2 不应授权什么

- 任意 COM/eval 或未经审查的 Blender Python；
- 保存/覆盖源 CAD；
- 自动关闭用户原先打开的文档；
- 自动把空叶加入白名单；
- 自动决定候选关节轴、行程、刚体成员和碰撞安全；
- 在门禁失败时发布到共享 `models/`。

### 11.3 配置本地 MCP

Codex 支持本地 STDIO MCP，也支持在项目 `.codex/config.toml` 中配置服务器；项目配置只会在受信任项目中生效。[Codex MCP 官方说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

在 Windows 原生 Codex 中执行：

```powershell
$SwServer = Join-Path $ThreeD "mcp_servers\sw_mcp\server.py"
$BlenderServer = Join-Path $ThreeD "mcp_servers\blender_mcp\server.py"

codex mcp add ptlc-solidworks -- $PythonExe $SwServer
codex mcp add ptlc-blender -- $PythonExe $BlenderServer
codex mcp list
```

然后在 Codex 内运行 `/mcp` 检查工具。初始策略应为每次写操作提示批准，SOLIDWORKS MCP 超时至少 3600 秒；COM 操作由服务端单线程串行执行，不要并发调用。

建议 Agent 首条指令：

```text
工作目录是固定提交 e6961f... 的专用调试 clone。
源 CAD 只读；不得保存或覆盖任何 SLDASM/SLDPRT。
先检查 git、LFS、Python、Node、Blender、SOLIDWORKS COM 和当前打开文档。
若有未保存用户文档、模态对话框、缺失引用、提交不匹配或非 ASCII 输出路径，立即停止。
第一次只运行 XR → GLB → passthrough Meshopt → report 的冒烟闭环；
所有输出写 three_d/work/debug 或 three_d/exports，不覆盖 models。
每一步回报命令、退出码、产物路径、文件大小、SHA-256 和门禁结果。
```

## 12. 哪些内容必须人工补充

| 内容 | 为什么 Agent/CAD 不能可靠推断 | 人工输出 |
|---|---|---|
| 装配修订、配置、显示状态 | 多个状态都可能技术上可导出 | 经批准的 CAD 输入记录 |
| 缺失/抑制/轻化零件裁决 | “没显示”不等于“不需要” | 完整性清单和例外理由 |
| `rig_map.yaml` | GLB 没有可编辑 mate/控制语义 | 候选刚体成员、轴、枢轴、行程、home |
| 材质与透明度 | CAD 外观不等于浏览器视觉意图 | 材质规则和视觉批准 |
| 候选碰撞/简化几何 | 渲染网格不等于安全碰撞模型 | 保守碰撞体及工程审查 |
| 库位/控制绑定 | 节点名不能证明业务身份 | 库位控制绑定（SiteControlBinding） |
| 设备状态与动作 | GLB 本身 0 animation/skin | 设备遥测投影、动作/clip 映射 |
| 机械臂标定 | CAD 坐标不等于实机坐标 | 基座、工具中心点、法兰和工位标定 |
| 最终验收 | 自动报告无法证明机械真实性 | CAD/机械/软件三方签字 |

这里的 `rig_map`、机械资产包和资产编译器仍是候选术语；UniLab 已接受的运行时语言应使用设备遥测投影（DeviceTelemetryProjection）、机器人指令（RobotCommand）、库位控制绑定（SiteControlBinding）等规范名称。

## 13. 环境冻结与证据包

第一条路径跑绿后立即生成本机证据，不要等环境自动升级：

```powershell
New-Item -ItemType Directory -Force -Path $RecordRoot | Out-Null

git -C $RepoRoot rev-parse HEAD |
  Set-Content (Join-Path $RecordRoot "source-commit.txt")
git --version | Set-Content (Join-Path $RecordRoot "git-version.txt")
git lfs version | Set-Content (Join-Path $RecordRoot "git-lfs-version.txt")
node --version | Set-Content (Join-Path $RecordRoot "node-version.txt")
npm --version | Set-Content (Join-Path $RecordRoot "npm-version.txt")
& $PythonExe --version 2>&1 |
  Set-Content (Join-Path $RecordRoot "python-version.txt")
& $PythonExe -m pip freeze |
  Set-Content (Join-Path $RecordRoot "requirements-lock.txt")
& $BlenderExe --version |
  Set-Content (Join-Path $RecordRoot "blender-version.txt")

Get-FileHash $Assembly -Algorithm SHA256 |
  Format-List | Out-File (Join-Path $RecordRoot "cad-top-level-sha256.txt")
Get-FileHash (Join-Path $ThreeD "exports\TLC_full_native.glb") -Algorithm SHA256 |
  Format-List | Out-File (Join-Path $RecordRoot "native-glb-sha256.txt")
```

还应保存：

- SOLIDWORKS 完整版本和 Service Pack；
- Pack and Go 文件清单及哈希；
- `pipeline.yaml` 本机差异；
- `00/03/04/05` 的 JSON 报告和控制台日志；
- 原生/清洗/优化三个 GLB；
- 人工截图、缺件清单、例外和批准记录。

## 14. 验收顺序

| Gate | 通过标准 | 失败时动作 |
|---|---|---|
| G0 工具 | 版本可执行、固定提交正确、LFS 是真实 GLB | 修环境，不动业务规则 |
| G1 COM | typelib 早期绑定成功，SW 信息可读，无用户文档风险 | 清缓存/处理 GUI，不导出 |
| G2 XR | GLB 生成，报告无意外空叶，人工大件完整 | 查配置、引用和缺失素材 |
| G3 转码 | passthrough 后层级/名字/几何数量合理 | 查 Draco/glTF Transform 依赖 |
| G4 清洗 | 单件素材齐全，Blender 无 traceback | 修素材或规则，不跳过 |
| G5 预算 | `05_report.py` 不带 `--no-fail` 返回成功 | 调整有证据的清洗/预算 |
| G6 语义 | manifest 节点全部存活，人工批准 rig/材质/库位 | 回到语义绑定，不改 CAD 猜答案 |
| G7 运动 | 标定、点表、clip、碰撞和落位验证通过 | 禁止用于实机安全结论 |

## 15. 当前已知风险

1. **full→optimized 载荷局部坐标帧错配**：源码自述的检测结果为 105 个载荷中 44 个偏差超过 1 mm，板类约 69.8 mm。修复并复验前，动作落位和夹持动画不能作为实机或安全依据。
2. **日报可能不阻断**：既有 authoring 编排会给 `05_report.py` 传 `--no-fail`。正式包装器必须读取报告中的失败状态并真正阻止发布。
3. **XR/STEP 都不是机械语义真源**：GLB 没有动画和 skin；当前运动来自 manifest 和 clips，候选刚体/关节来自人工规则。
4. **原生导出可能静默不完整**：轻化、缺引用、抑制、错误配置、曲面零件和模态对话框都可能造成“API 成功但资产缺件”。
5. **不要并行驱动 SOLIDWORKS**：COM apartment 和全局导出设置要求串行；服务端虽然做了专用线程，调用方仍不应并发发起导出。

## 16. 故障定位速查

| 现象 | 优先检查 |
|---|---|
| `python` 打开 Microsoft Store | 不用 PATH，始终调用 `$PythonExe` |
| `GetFirstDocument2` 等不可见 | 先运行 `ensure_typelib.py --force`，再启动会话 |
| 导出返回成功但没有文件 | 输出路径必须 ASCII；检查 SaveAs 错误位和目录权限 |
| XR GLB 有空叶/缺件 | GUI 中解析完整装配；必要时运行单件素材导出 |
| `03` 报补几何素材不存在 | 先跑 `export_part_assets.py --list` 和无参数导出 |
| `03` 报官方机器人网格缺失 | 获取固定 DOBOT 提交，核对 `vendor/.../meshes/cr5` 的 7 个 STL |
| Blender 退出码 0 但无产物 | 查 `03_*.console.log` 的 Python traceback |
| Node 读不进 XR GLB | 确认 `npm ci` 完成并注册 `draco3d` 解码器 |
| 优化后机构不动 | 检查节点名、`--no-join`、manifest 执行器节点门禁 |
| STEP 打开失败 | 输入/输出/工作目录改为 ASCII；确认 cp936 名称修复 |
| MCP 启动失败 | 核对同一个 `$PythonExe`、`mcp` 2.x 导入和 `cwd` |

## 17. 资料与源码依据

项目内分析：

- `docs/research/2026-08-21-ptlc-asset-pipeline-input-output-contracts.md`
- `docs/research/2026-08-18-ptlc-asset-pipeline-urdf-usd-research.md`
- `docs/research/2026-08-20-ptlc-new-project-manual-work-matrix.md`

固定提交关键入口：

- [`three_d/README.md`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/README.md)
- [`pipeline/pipeline.yaml`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/pipeline.yaml)
- [`00_export_gltf.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/00_export_gltf.py)
- [`03_clean_model.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/03_clean_model.py)
- [`04_optimize.mjs`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/04_optimize.mjs)
- [`05_report.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/05_report.py)
- [`export_part_assets.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/pipeline/export_part_assets.py)
- [`sw_mcp/sw_core.py`](https://github.com/Uni-Lab-OS/pTLC_platformUI/blob/e6961f172926c5183fab19961635518f52bd7e47/eit_ptlc/three_d/mcp_servers/sw_mcp/sw_core.py)

本文的核心边界是：**Agent 可以可靠编排软件和验证文件合同，但不能替代 CAD/机械工程师声明机械真相。**
