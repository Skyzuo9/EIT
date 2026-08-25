# UniLab Workbench 资产管线端到端测试交接包

这是一个可直接复制到另一台 Windows 电脑的自包含测试文件夹。它包含昨天试跑使用的五类最小输入、资产管线代码、已通过家族门禁的基线输出、Workbench 静态测试夹具、校验脚本和测试记录模板。

本轮“全流程”指：

```text
SolidWorks / STEP / legacy URDF 输入
  → 家族候选包与 GLB
  → 哈希、能力和内容门禁
  → Workbench 隔离测试夹具
  → 静态加载、显示、拾取和错误边界验证
```

它不包括机械臂运动、真实工作流驱动、强制空间互锁或设备执行。当前没有厂家机械臂 URDF/Xacro、合格碰撞体、现场部署绑定和 WorkCellActivation；脚本与夹具都明确禁止把这次静态测试提升为执行资格。

## 在另一台电脑上开始

建议把整个文件夹解压到短、稳定、非同步盘路径，例如：

```text
C:\unilab\unilab-workbench-e2e-handoff-20260824
```

在 PowerShell 中进入该目录，然后依次运行：

```powershell
.\scripts\Verify-Handoff.ps1
.\scripts\00-preflight.ps1
.\scripts\01-run-pipeline.ps1
.\scripts\02-verify-output.ps1
```

若 Python 或 Blender 未被自动识别，请显式传路径：

```powershell
.\scripts\00-preflight.ps1 `
  -PythonPath 'C:\ProgramData\miniforge3\python.exe' `
  -BlenderPath 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'

.\scripts\01-run-pipeline.ps1 `
  -PythonPath 'C:\ProgramData\miniforge3\python.exe' `
  -BlenderPath 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
```

缺 Python 依赖时由操作者确认后安装：

```powershell
& 'C:\ProgramData\miniforge3\python.exe' -m pip install -r .\requirements.txt
```

运行资产管线前必须关闭已有的 SOLIDWORKS。适配器只读打开指定的小装配，只终止由本次探针创建的 SOLIDWORKS 进程。

## 接入 Workbench

先阅读 [HANDOFF-TO-OTHER-COMPUTER.md](./HANDOFF-TO-OTHER-COMPUTER.md) 和 [WORKBENCH-TEST-PLAN.md](./WORKBENCH-TEST-PLAN.md)。在目标仓库中确认真正的静态资源目录后，把它作为参数传给脚本；脚本只会创建隔离命名空间，不会覆盖现有模型：

```powershell
.\scripts\03-stage-workbench-fixture.ps1 `
  -WorkbenchPublicDir 'D:\path\to\uni-lab-fe\apps\kernel-web\public'
```

如果新电脑还没跑通 SolidWorks/Blender，可以先验证 Workbench 加载链：

```powershell
.\scripts\03-stage-workbench-fixture.ps1 `
  -WorkbenchPublicDir 'D:\path\to\actual\public' `
  -UseBaseline
```

脚本会输出唯一的 `scene-catalog.json` URL。不要猜测或直接套用上面的示例 public 路径；应以目标仓库实际结构和开发服务器行为为准。

测试完可生成回传包：

```powershell
.\scripts\04-collect-results.ps1 `
  -WorkbenchRepo 'D:\path\to\uni-lab-fe' `
  -ScreenshotPath 'D:\screenshots\workbench-assets.png'
```

## 两种输入模式

- `workspace/work/asset-pipeline-trial/`：在另一台电脑重新生成的结果，严格验证时应有 5 个 bundle、5 张预览图且 SolidWorks capture 为 `passed`。
- `workbench-fixture-baseline/`：昨天已经通过家族门禁的静态 Workbench 夹具，用于隔离前端加载问题；其中 provenance 仍会记录原始机器路径，这是审计信息，不是运行路径。

## 安全边界

- 不覆盖现有 `machine.glb`、生产模型、点表、部署文件或 activation。
- 不把预览位姿当 `base_pose`，不把 legacy URDF 关节当正式运动学。
- 不启用运动、空间互锁或执行。
- 这个文件夹包含内部 CAD/网格数据，仅在获准的内部设备间传输，不上传公开仓库或公共网盘。
