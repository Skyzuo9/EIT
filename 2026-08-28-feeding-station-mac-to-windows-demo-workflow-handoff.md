# 投料站 Mac → Windows Demo Workflow 交接手册

日期：2026-08-28

对象：`feeding-station-20260827-win03`

最低根仓提交：`87b7ba727548c02dd6aae40d7ef7131883ac3642`

用途：在 Windows 的 UniLab Workbench 复现资产管线展示与模拟 WorkflowTask

资格：`demo-simulation / CAD-comparison-only / no hardware`

## 1. 本次交接完成了什么

Workbench 主场景包含完整投料站、独立模拟导轨、青色 GCR5 URDF comparison overlay
和一只 4 ml 演示瓶。标准 Uni-Lab OS WorkflowTask 会运行六个进程内可视动作，并保存
Task、6 个 Job 和 runtime events。

Mac 已复算并验证 frozen CAD 的 GCR5 六轴 comparison pose。J1–J6 的关节链残差接近
双精度数值下限；J0 CAD 与 URDF base mesh 的一轴 AABB 仍相差约 44.708 mm，所以不得
写成全网格完美配准、物理标定或部署 base pose。

本手册不授权 P2 approval、真实 W2、PLC/机器人连接、MoveIt、碰撞或空间互锁。

## 2. 更新仓库并检查提交

在 PowerShell 中设置实际仓库路径：

```powershell
$Repo = "E:\资产管线unilab\unilab-asset-pipeline"

git -C $Repo fetch --prune origin
git -C $Repo switch main
git -C $Repo pull --ff-only origin main
git -C $Repo submodule update --init --recursive

git -C $Repo merge-base --is-ancestor `
  87b7ba727548c02dd6aae40d7ef7131883ac3642 HEAD
if ($LASTEXITCODE -ne 0) {
  throw "缺少 feeding-station demo workflow 提交"
}

git -C $Repo status --short --branch
git -C $Repo submodule status --recursive
```

不要用 `git reset --hard` 清理未知本地改动。若主仓或 submodule 非预期脏，先另存证据并
停止；不要把本机修改混进本轮回执。

## 3. 准备运行环境

当前入口会编译 CR5、GCR5、FR5 三个只读 SourceRelease，所以三个 ZIP 都必须存在。
可使用已经下载且摘要一致的文件，或运行仓库下载器：

```powershell
$Python = "$Repo\.venv\Scripts\python.exe"
$env:EIT_ROBOT_CONTROL_ROOT = "$env:USERPROFILE\Downloads\机械臂control"
$env:EIT_ROBOT_SOURCE_MANIFEST = `
  "$Repo\config\robot-source-releases.json"
$env:EIT_ROBOT_SOURCE_CACHE = `
  "$Repo\cr5-telemetry-proof\.unilabos\cache\robot-source-releases"

& $Python "$Repo\scripts\fetch_robot_source_release.py" dobot_cr5
& $Python "$Repo\scripts\fetch_robot_source_release.py" duco_gcr5_910
& $Python "$Repo\scripts\fetch_robot_source_release.py" fairino_fr5
```

GCR5 关键预期值：

```text
archive sha256 = c91cd096d8c6acde34bb57c85d4b7916c6ab17dc22feff09c502f29256230612
URDF sha256    = 76e95464d07ec304bf9394b640540a87193fa977420486c348e578e9cbd38858
topology       = 583e2b65e6422a7fe0c9332f8172bd03c3da267ba66da853cb854650eb08ac48
```

配置 Python 路径：

```powershell
$env:PYTHONPATH = @(
  "$Repo\cr5-telemetry-proof",
  "$Repo\Uni-Lab-OS",
  "$Repo\dependencies\unilab_robot_template\packages\unilab-rail-linear\src"
) -join ";"
```

Windows 需要 Python 3.13 环境中的项目依赖，以及 Node 22 + pnpm。若现有 `.venv` 不属于
本机 Windows，不要复制 Mac venv；在 Windows 重新创建。

## 4. 先运行合同测试

```powershell
& $Python -m unittest discover `
  -s "$Repo\cr5-telemetry-proof\tests" `
  -p "test_station_preview.py" -v

& $Python -m unittest discover `
  -s "$Repo\cr5-telemetry-proof\tests" `
  -p "test_demo_workflow.py" -v
```

预期分别为 `2/2 passed`、`3/3 passed`。测试不通过时不要启动可见回执。

## 5. 启动后端与 Workbench

第一窗口：

```powershell
$StationRoot = "$Repo\feeding-station-20260827-win03"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$DemoEvidence = Join-Path $env:TEMP "feeding-station-demo-$RunStamp"
New-Item -ItemType Directory -Path $DemoEvidence -ErrorAction Stop | Out-Null

& $Python -m cr5_telemetry_lab.preview_app `
  --host 127.0.0.1 `
  --port 8002 `
  --station-root $StationRoot `
  --station-receipt "$Repo\config\feeding-station-workbench-preview.json" `
  --demo-workflow-db "$DemoEvidence\workflow.db"
```

第二窗口：

```powershell
$env:UNILAB_BACKEND_PROXY_TARGET = "http://127.0.0.1:8002"
Set-Location "$Repo\uni-lab-fe"
pnpm --filter @unilab/kernel-web dev
```

浏览器打开：

```text
http://127.0.0.1:5173/?backend=local-python&backendUrl=http%3A%2F%2F127.0.0.1%3A8002&section=scene
```

## 6. 运行一次新的 Demo WorkflowTask

第三个 PowerShell 窗口：

```powershell
$Descriptor = Invoke-RestMethod `
  "http://127.0.0.1:8002/api/v1/demo-workflow/descriptor"
$Body = $Descriptor.required_activation | ConvertTo-Json -Depth 20

$Run = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8002/api/v1/demo-workflow/runs" `
  -ContentType "application/json" `
  -Body $Body

$TaskUuid = $Run.data.task.uuid
$Task = Invoke-RestMethod `
  "http://127.0.0.1:8002/api/v1/workflow-tasks/$TaskUuid"
$Jobs = Invoke-RestMethod `
  "http://127.0.0.1:8002/api/v1/workflow-tasks/$TaskUuid/jobs"
$Events = Invoke-RestMethod `
  "http://127.0.0.1:8002/api/v1/workflow-tasks/$TaskUuid/events"
$SceneState = Invoke-RestMethod `
  "http://127.0.0.1:8002/api/v1/demo-workflow/scene-state"
$Graph = Invoke-RestMethod `
  "http://127.0.0.1:8002/api/v1/materials/graph"

$Run.data.validation_status
$Task.data.status
$Jobs.data.Count
$Events.data.items.Count
$Graph.data.nodes.Count
```

预期：

```text
validation_status = demo-workflow-validated
task status       = succeeded
jobs              = 6，且全部 succeeded
events            = 21
Material nodes    = 4
hardware_execution=false
publication_eligible=false
```

激活 token 还应包含：

```text
station_geometry_sha256 = f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746
station_layout_sha256   = f33c32ff39d0c63bc14f0911053c54aebb8aac8b5212953fb03852d9830eb76e
cad_comparison_pose     = 73af6e122c0e28cf526e0aefd9e54d5cf396a5b30643a311473542d79e89b411
```

## 7. 可见检查

确认：

1. 页面显示 `4 个物料`，Edge 为已连接；
2. 投料站方向正确、落地且完整；公开 Material Graph 是 Z-up；原始
   `SOLIDWORKSGLTF` 模型已经是 glTF Y-up，Pascal 中的 `model.rotation` 必须为零，
   不得重复施加 `Rx(-90°)`；
3. 青色 GCR5 J1–J6 与灰色 CAD 连杆基本重合，只在轮廓/三角面边缘可见；
4. 不要求 J0 表面完全重合，因为两份 base mesh revision/几何不同；
5. 运行 Demo 后 GCR5 最终回 comparison pose，遥测不会一秒后回六轴零位；
6. 标签明确包含 `DEMO / DRAFT / NO HARDWARE`；
7. 浏览器 console 没有 GLB fetch/parse、URDF、SSE 或 WebGL error。

不要只写“通过”。回执中的视觉判定使用：

```text
visual_presence=passed|failed
moving_link_registration=passed|misaligned|unverified
base_mesh_registration=known-geometry-mismatch
```

## 8. Windows 返回回执

新建 `WINDOWS-DEMO-WORKFLOW-RECEIPT.md`，至少记录：

- 根仓 HEAD、全部 submodule HEAD 和 `git status --short`；
- Windows、Python、Node、pnpm、浏览器和 GPU 信息；
- station GLB、P2 layout、GCR5 archive/URDF/topology、comparison pose 摘要；
- WorkflowTask UUID、Task 状态、6 个 Job 状态、event 数；
- `hardware_execution=false`、`publication_eligible=false`；
- screenshot 文件名、SHA-256、分辨率和拍摄时间；
- 三项视觉判定和 console errors；
- 首次完整显示耗时、峰值内存/显存（若可取得）；
- `W2 Run ID=not-started`。

把 receipt 和截图放入新的非破坏性回传目录；不要覆盖 frozen win03 handoff，也不要把
本轮 workflow DB 当作跨机可移植的正式证据数据库。

## 9. 仍需人工决定

开放项目保存在
[`2026-08-28-feeding-station-pending-decisions.md`](./2026-08-28-feeding-station-pending-decisions.md)。
其中包括设备/family 边界、移动轴、机器人厂家参数、base/tool/TCP、J0 mesh revision、
collision、4 ml 物理槽位和第三方许可。它们不阻塞本 Demo，但继续阻塞真实 W2 与硬件。
