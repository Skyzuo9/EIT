# 投料站 P0–P1：Windows / Mac 协同运行手册

日期：2026-08-27
状态：可执行；Windows 先做 P0–P1，Mac 负责独立验收
上位计划：[`2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md`](./2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md)
win02 精确哈希、Mac 命令和回执格式：
[`2026-08-27-feeding-station-win02-mac-handoff.md`](./2026-08-27-feeding-station-win02-mac-handoff.md)

本手册只覆盖当前第一步：Windows 对真实 SolidWorks 总装完成输入冻结和只读
W1 采集，Mac 验证 handoff。P0–P1 通过不代表已经完成人签分解、家族包、碰撞、
互锁、工作流或真机执行。

## 1. 先说结论：谁做什么

| 阶段 | Windows / SolidWorks 生成机 | Mac / EIT 开发机 | 谁判定通过 |
|---|---|---|---|
| 同步 | 克隆本仓、固定提交、拉 submodule/LFS | 发布工具和文档 | Git 提交一致 |
| P0-W | 找到唯一输入根、确认顶层总装、生成两次清单/摘要、检查 SW 占用 | 不改输入 | Windows 先判 `ready` |
| P0-M | 传回清单，确认原始 CAD 未进入 Git | 复核清单与忽略规则 | Mac 接受后 P0 完成 |
| P1-W | 只读打开总装、采 occurrence/mate 候选、导 native GLB、前后复算摘要 | 不做 CAD 推断 | Windows 先判 `ready-for-mac-validation` |
| P1-M | 校验路径、摘要、snapshot、GLB 和机器人 Provider | 保存验证报告 | Mac 返回 `passed=true` 后 P1 完成 |
| P2 | 提供 occurrence 解释和机械审核人 | 起草 decomposition | 人工批准 |

关键边界：Windows 对 SolidWorks occurrence、配置和原生几何负责；Mac 对数据合同、
家族/部署分层、Provider、Workbench 和工作流负责；候选关节、设备归属和忽略项的
最终决定权属于人工审核人。

## 2. 两条传输通道，不要混用

### 2.1 GitHub 通道：代码和小型、可审计文本

可以进入 Git：

- 本仓脚本、配置、测试和 Markdown；
- 不含受限绝对路径/凭据的小型清单、验证报告和人工批准记录；
- 后续已批准的 IR、FamilySimBundle 清单、部署清单和 activation 摘要。

不要进入 Git：

- `.SLDASM/.SLDPRT/.x_t/STEP/STL/GLB` 原始交接包；
- 厂家 ZIP、控制器导出、点表、标定和现场凭据；
- `incoming/<run-id>/` 的实际内容；
- `.env`、token、许可证和机器私有配置。

### 2.2 Handoff 通道：完整 P1 目录

使用受控 SMB、移动硬盘或团队批准的文件传输方式，把完整目录原样交给 Mac。
不要求压缩；若传输工具会改文件名、mtime 或 Unicode 路径，换用不会改写内容的
方式。Mac 不相信“复制成功”的提示，而是重新验证 `files.sha256`。

```text
feeding-station-<run-id>/
  station-handoff.json
  P1-REPORT.md
  capture/
    assembly.snapshot.json
    capture-report.json
    source.json
    files.sha256
  source-release/
    投料站方案模拟1.1.SLDASM
    ...完整 Pack and Go 依赖...
  geometry/
    station.glb
  audit/
    p0-a/
    p0-b/
    console/
```

## 3. Windows 一次性准备

在专用工作目录中克隆，不要在唯一 CAD 源目录中运行脚本：

```powershell
$Repo = "D:\unilab\unilab-asset-pipeline"
git clone --recurse-submodules https://github.com/Skyzuo9/unilab-asset-pipeline.git $Repo
git -C $Repo lfs pull
git -C $Repo submodule update --init --recursive
git -C $Repo status --short --branch
git -C $Repo rev-parse HEAD
```

安装 Python 3.11/3.12 与 `pywin32`。SolidWorks 2025 默认 ProgID 是
`SldWorks.Application.33`；若本机不同，以实际安装版本为准并记录到报告。

```powershell
$Python = "C:\ProgramData\miniforge3\python.exe"
& $Python --version
& $Python -m pip install "pywin32==312"
Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue
```

如果最后一条有输出，停止自动采集。保存并由用户自己关闭文档后再开始；脚本不得
接管或关闭原先存在的 SolidWorks 进程。

## 4. P0-W：输入冻结

### 4.1 定义本次唯一边界

以下路径仅是示例，按 Windows 实际位置修改。`$RunRoot` 必须在 `$Source` 之外。

```powershell
$Source = "D:\eit-cad\投料站"
$TopAssembly = "投料站方案模拟1.1.SLDASM"
$RunId = "feeding-station-20260827-win01"
$RunRoot = "D:\unilab-handoff\$RunId"

Test-Path (Join-Path $Source $TopAssembly)
New-Item -ItemType Directory -Force -Path "$RunRoot\audit\p0-a", "$RunRoot\audit\p0-b" | Out-Null
```

不要同时把根目录 `投料站-urdf` 和 `投料站\投料站-urdf` 当成两个输入；P0–P1 的
SolidWorks 主源只有 `$Source`。Legacy URDF 的去重审计由 Mac 后续单独完成。

### 4.2 连续生成两份清单

```powershell
& $Python "$Repo\scripts\inventory_station_source.py" `
  --source-root $Source `
  --top-assembly $TopAssembly `
  --output-dir "$RunRoot\audit\p0-a"

& $Python "$Repo\scripts\inventory_station_source.py" `
  --source-root $Source `
  --top-assembly $TopAssembly `
  --output-dir "$RunRoot\audit\p0-b"

$A = Get-FileHash "$RunRoot\audit\p0-a\files.sha256" -Algorithm SHA256
$B = Get-FileHash "$RunRoot\audit\p0-b\files.sha256" -Algorithm SHA256
if ($A.Hash -ne $B.Hash) { throw "P0 失败：两次输入清单不一致" }
```

人工补记：SolidWorks 完整版本/SP、顶层配置、Pack and Go 来源/修订、输入负责人、
已知缺失或抑制例外。`P0-REPORT.md` 中“Pack and Go 引用完整性”仍是未验证，直到
P1 真正只读打开总装且无缺引用错误。

### 4.3 P0-W 停止条件

出现任一情况就停止，不进入 P1：

- 顶层总装不存在或打开时要求修复/另存；
- 两次 `files.sha256` 不一致；
- 有他人的 SolidWorks 会话或未保存文档；
- Pack and Go 缺依赖、配置不明确或源修订仍在变化；
- `$RunRoot` 位于 `$Source` 内；
- 需要用改名、压缩替代或跳过缺件才能继续。

## 5. P1-W：真实总装只读 W1 采集

### 5.1 建立独立、只读 SourceRelease

```powershell
$Release = "$RunRoot\source-release"
if (Test-Path $Release) { throw "为避免混入旧结果，请使用新的 RunId" }

robocopy $Source $Release /E /COPY:DAT /DCOPY:T /R:2 /W:1
if ($LASTEXITCODE -gt 7) { throw "robocopy 失败：$LASTEXITCODE" }

Get-ChildItem $Release -Recurse -File | ForEach-Object { $_.IsReadOnly = $true }
```

不要在 `$Source` 上直接运行 exporter。只读属性是附加门禁；真正的 API 打开模式仍
必须是 `OpenDoc6(silent + read-only)`。

### 5.2 运行现有只读 Adapter

SolidWorks GLB 输出先写 ASCII 临时路径，避免 XR/SaveAs 对中文输出路径兼容性不稳。

```powershell
$Adapter = "$Repo\unilab-workbench-e2e-handoff-20260824\pipeline\trial_sw_adapter.py"
$AsciiTemp = "C:\unilab-tmp\$RunId"
New-Item -ItemType Directory -Force -Path "$RunRoot\capture", "$RunRoot\geometry", "$RunRoot\audit\console", "$RunRoot\audit\repeat", $AsciiTemp | Out-Null

& $Python $Adapter `
  --assembly (Join-Path $Release $TopAssembly) `
  --snapshot "$RunRoot\capture\assembly.snapshot.json" `
  --report "$RunRoot\capture\capture-report.json" `
  --glb-ascii "$AsciiTemp\station.glb" `
  --progid "SldWorks.Application.33" `
  --visible 2>&1 | Tee-Object "$RunRoot\audit\console\solidworks-capture.log"

if ($LASTEXITCODE -ne 0) { throw "P1 SolidWorks capture 失败" }

& $Python $Adapter `
  --assembly (Join-Path $Release $TopAssembly) `
  --snapshot "$RunRoot\audit\repeat\assembly.snapshot.json" `
  --report "$RunRoot\audit\repeat\capture-report.json" `
  --glb-ascii "$AsciiTemp\station-repeat.glb" `
  --progid "SldWorks.Application.33" `
  --visible 2>&1 | Tee-Object "$RunRoot\audit\console\solidworks-capture-repeat.log"

if ($LASTEXITCODE -ne 0) { throw "P1 第二次 SolidWorks capture 失败" }
```

Adapter 必须自己启动 SolidWorks、只关闭自己打开的文档并退出自己创建的进程。
不要在采集中操作 GUI，不要并发运行第二个 COM/MCP 导出。

### 5.3 封装 handoff，并绑定 P0 摘要

先比较两次 GLB。若 SHA-256 不同，Windows 暂停封装，把两份 GLB 通过非 Git
通道交给 Mac。Mac 在相同仓库提交上运行平台无关的语义诊断：

```bash
./.venv/bin/python scripts/diagnose_station_glb_semantics.py \
  /path/to/station.glb \
  /path/to/station-repeat.glb \
  --output /path/to/glb-semantic-diagnosis.json
```

只有诊断返回 `status=passed`、`normalized_glb_semantic_match=true`、
`difference_class=component_traversal_order_only`，且报告中的两份 SHA-256 与待封装
GLB 精确绑定时，才把该 JSON 通过非 Git 通道交回 Windows。任何语义差异都进入
`needs-windows-recapture`，不能人工改写诊断。两次 GLB 字节一致时不需要诊断文件。

```powershell
$FinalizeArgs = @(
  "--output-root", $RunRoot,
  "--source-release-root", $Release,
  "--snapshot", "$RunRoot\capture\assembly.snapshot.json",
  "--capture-report", "$RunRoot\capture\capture-report.json",
  "--render-glb", "$AsciiTemp\station.glb",
  "--repeat-snapshot", "$RunRoot\audit\repeat\assembly.snapshot.json",
  "--repeat-capture-report", "$RunRoot\audit\repeat\capture-report.json",
  "--repeat-render-glb", "$AsciiTemp\station-repeat.glb",
  "--p0-files-sha256", "$RunRoot\audit\p0-a\files.sha256",
  "--station", "eit.feeding-station"
)

# 仅在 Mac 已返回与本轮两份 GLB 哈希绑定的通过报告时设置。
if ($SemanticDiagnosis) {
  $FinalizeArgs += @("--glb-semantic-diagnosis", $SemanticDiagnosis)
}

& $Python "$Repo\scripts\finalize_station_handoff.py" @FinalizeArgs

if ($LASTEXITCODE -ne 0) { throw "P1 handoff 封装失败" }
```

`finalize_station_handoff.py` 会拒绝：SourceRelease 与 P0 清单不一致、snapshot/report
数量不一致、非只读/失败报告、空 occurrence、缺失或非法 GLB、两次规范化 snapshot
不一致，或未附 Mac 通过报告的 GLB 字节摘要不一致。GLB 摘要不一致时必须由 Mac
判断是否只是 exporter 遍历顺序差异；Windows 不自行降级门禁。通过报告会被复制为
`audit/glb-semantic-diagnosis.json`，并由最终 Mac 验收再次独立复算。

### 5.4 Windows 自检与人工复核

```powershell
Get-Content "$RunRoot\P1-REPORT.md"
Get-Content "$RunRoot\capture\capture-report.json"
Get-Content "$RunRoot\station-handoff.json"
git -C $Repo status --short
```

人工确认：

- `status=passed`、`source_read_only=true`；
- `open_errors/open_warnings` 已解释，不能把非零位掩码静默写成通过；
- `component_count` 等于 snapshot 的 occurrence 数量；
- 无 unresolved/lightweight/rebuild 异常；
- `geometry/station.glb` 可打开且不只是截图或旧 `machine.glb`；
- mate 仅为 `candidate/unproven`；
- 采集前后原始 `$Source` 的 `files.sha256` 仍一致。

为验证最后一条，再对原始 `$Source` 运行第三次 P0 inventory，并与 `p0-a` 比较。

## 6. Windows → Mac 交接

Windows 把整个 `$RunRoot` 通过 handoff 通道传给 Mac。不要把它 `git add -f` 到仓库。
同时把以下短信息发给 Mac：

```text
Run ID:
Windows 仓库提交:
SolidWorks 版本/SP:
顶层总装与配置:
P0 files.sha256 的 SHA-256:
P1 station-handoff.json 的 SHA-256:
已知 warning/例外:
传输方式:
```

## 7. P1-M：Mac 独立验收

Mac 先把交接目录放入被 Git 忽略的 `incoming/`，再运行：

```bash
cd /Users/newtides/EIT
git pull --ff-only
git submodule update --init --recursive

./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/<run-id>/station-handoff.json \
  --output incoming/<run-id>/mac-validation.json
```

只有同时出现以下结果，P1 才算双方完成：

```text
passed: true
qualification: source-input-validated
not_qualified_for: 仍包含 collision / spatial-interlock-enforced / execution
```

Mac 验证器会复核 `audit/reproducibility-report.json` 和两次采集；若 GLB 字节不同，
还会重新计算两份 GLB 的语义签名，并核对 `audit/glb-semantic-diagnosis.json` 的算法、
分类和文件哈希。缺第二次采集、缺诊断或复算不一致时，P1 直接不通过。P2 由 Mac 起草
`station-decomposition.yaml`，Windows/CAD 负责人解释 occurrence，最终由人工审核人
批准。批准前不回到 Windows 做设备级 W2 导出。

## 8. 每轮交接状态词

| 状态 | 含义 | 下一方动作 |
|---|---|---|
| `p0-w-ready` | Windows 两次清单一致 | Mac 复核仓库卫生 |
| `ready-for-mac-validation` | Windows 已封装 P1 | 传完整 handoff |
| `source-input-validated` | Mac 门禁通过 | 开始 P2 草稿 |
| `needs-windows-recapture` | 摘要/路径/snapshot/GLB 门禁失败 | Windows 新建 RunId 重采，不能原地补文件 |
| `decomposition-awaiting-human-approval` | P2 草稿无覆盖错误 | 人工决定归属/忽略/替换 |
| `approved-for-w2-geometry-export` | P2 已人签 | Windows 才开始 P3/W2 |

每次失败保留原 RunId 和报告；修复后新建 RunId。不得把失败目录原地修成“通过”，
否则无法审计输入是否变化。
