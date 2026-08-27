# 投料站 win03：Mac → Windows P1 封装返还手册

日期：2026-08-27

Run ID：`feeding-station-20260827-win03`

当前状态：`approved-for-p1-packaging`

禁止状态：尚未封装或完成 Mac P1 验收，不是 `source-input-validated`

本手册记录 Mac 已完成的 win03 GLB 语义诊断，并给出 Windows 将原始
诊断 JSON 绑定到两份 GLB、运行 P1 finalizer、自检和将完整交接包返回
Mac 的唯一允许流程。

前置文档：

- win03 Windows → Mac 原始诊断合同：
  [`2026-08-27-feeding-station-win03-to-mac-handoff.md`](./2026-08-27-feeding-station-win03-to-mac-handoff.md)
- P0–P1 总流程：
  [`2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](./2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)
- design/plan 及资格边界：
  [`2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md`](./2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md)

## 1. Mac 已完成的真实验证

Mac 在 Git HEAD `f3ea4c44b8537668318c7720de3b5ec0f9014dd2`、macOS 26.2
arm64、Python 3.13.12 上独立复算：

| 检查项 | 结果 |
|---|---|
| `station.glb` | 283,695,812 bytes，SHA-256 `f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746` |
| `station-repeat.glb` | 283,695,632 bytes，SHA-256 `fc4891a53de809140c48fa8827c93d94853a2ecd71d8354750c309b753802768` |
| 字节一致 | `false` |
| 规范化语义一致 | `true` |
| 差异分类 | `component_traversal_order_only` |
| 两份语义 SHA-256 | `226e6dc7cf274878d3bb54da2e4eaebc27fd605b9f739827d344ae05c1797b5c` |
| 两份 GLB 结构 | 1543 nodes、1396 meshes、1588 primitives、4764 accessors、45 materials |
| 两份 snapshot | 字节一致；2021 occurrences、25 roots、1996 条非空 parent |
| SourceRelease | 639 个文件全部逐文件 SHA-256 通过 |
| 规范化 `source_files_digest` | `f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d` |
| 工站合同测试 | 23/23 通过 |
| Mac CR5/FR5 回归 | 6/6 通过 |

Mac 生成的原始诊断文件：

| 文件 | bytes | SHA-256 | 传输 |
|---|---:|---|---|
| `glb-semantic-diagnosis.json` | 1137 | `f61da2e59a0d561f82f1f21bdab655453d12dd172a892c14f6471772a220460c` | 必须走非 Git 通道 |

诊断内必须同时为：

```text
schema=lab.station_glb_semantic_diagnosis/v0
status=passed
validator_role=mac-p1-semantic-diagnostics
algorithm=solidworks-gltf-scene-geometry-payload/v2
exact_glb_match=false
normalized_glb_semantic_match=true
difference_class=component_traversal_order_only
approved_for_p1_packaging=true
```

此结果只批准 Windows 执行 P1 封装。它不批准 P2、W2、kinematic preview、
collision、spatial interlock 或 execution。

## 2. Windows 同步 GitHub

在代码仓库执行，不要在 CAD 唯一源目录执行：

```powershell
$Repo = "E:\资产管线unilab\unilab-asset-pipeline"
$RequiredCommit = "f3ea4c44b8537668318c7720de3b5ec0f9014dd2"

git -C $Repo fetch --prune origin
git -C $Repo switch main
git -C $Repo pull --ff-only origin main
git -C $Repo merge-base --is-ancestor $RequiredCommit HEAD
if ($LASTEXITCODE -ne 0) { throw "仓库缺少 win03 父图与语义门禁提交" }

git -C $Repo rev-parse HEAD
git -C $Repo status --short --branch
```

不得使用旧 finalizer、手写诊断 JSON，也不得通过 `reset --hard` 清理
未确认所有权的本地改动。

## 3. 接收并固定 Mac 原始诊断

用移动硬盘、受控 SMB 或团队批准的非 Git 通道接收
`glb-semantic-diagnosis.json`。假设临时接收位置为：

```powershell
$MacDrop = "F:\win03-mac-return\glb-semantic-diagnosis.json"
$ExpectedDiagnosis = "f61da2e59a0d561f82f1f21bdab655453d12dd172a892c14f6471772a220460c"

if (-not (Test-Path $MacDrop -PathType Leaf)) { throw "缺少 Mac 诊断 JSON" }
if ((Get-Item $MacDrop).Length -ne 1137) { throw "Mac 诊断 JSON 字节数错误" }
$ReceivedHash = (Get-FileHash $MacDrop -Algorithm SHA256).Hash.ToLower()
if ($ReceivedHash -ne $ExpectedDiagnosis) { throw "Mac 诊断 JSON 哈希错误" }
```

将其作为新文件放入 win03，不覆盖 pending GLB 或任何已有审计文件：

```powershell
$RunRoot = "E:\资产管线unilab\handoff\feeding-station-20260827-win03"
$IncomingMac = "$RunRoot\audit\incoming-mac"
$Diagnosis = "$IncomingMac\glb-semantic-diagnosis.json"

if (Test-Path $Diagnosis) { throw "win03 已有诊断文件；不要覆盖" }
New-Item -ItemType Directory -Force -Path $IncomingMac | Out-Null
Copy-Item -LiteralPath $MacDrop -Destination $Diagnosis

if ((Get-FileHash $Diagnosis -Algorithm SHA256).Hash.ToLower() -ne $ExpectedDiagnosis) {
  throw "复制后诊断哈希变化"
}
```

不要将诊断 JSON、GLB、CAD 或完整 handoff 提交到 GitHub。

## 4. 封装前不可变检查

```powershell
$Pending = "$RunRoot\audit\pending-glb-semantic-diagnosis"

$PrimaryExpected = "f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746"
$RepeatExpected = "fc4891a53de809140c48fa8827c93d94853a2ecd71d8354750c309b753802768"
$SnapshotExpected = "aeb869a6b2da85125d0c7def63056595826a6abfe0962ff45ea36a52d8d0eb2d"
$P0Expected = "54e9158e5b42ec0a75c1db6e0b6771c5d0c9d11cdf7f16f4f7a4a574a16609db"

if ((Get-FileHash "$Pending\station.glb" -Algorithm SHA256).Hash.ToLower() -ne $PrimaryExpected) {
  throw "主 GLB 变化"
}
if ((Get-FileHash "$Pending\station-repeat.glb" -Algorithm SHA256).Hash.ToLower() -ne $RepeatExpected) {
  throw "重复 GLB 变化"
}
if ((Get-FileHash "$RunRoot\capture\assembly.snapshot.json" -Algorithm SHA256).Hash.ToLower() -ne $SnapshotExpected) {
  throw "主 snapshot 变化"
}
if ((Get-FileHash "$RunRoot\audit\repeat\assembly.snapshot.json" -Algorithm SHA256).Hash.ToLower() -ne $SnapshotExpected) {
  throw "重复 snapshot 变化"
}

foreach ($P0 in @("p0-a", "p0-b", "p0-after", "release-check")) {
  $Actual = (Get-FileHash "$RunRoot\audit\$P0\files.sha256" -Algorithm SHA256).Hash.ToLower()
  if ($Actual -ne $P0Expected) { throw "$P0 files.sha256 变化" }
}

foreach ($Unexpected in @(
  "$RunRoot\station-handoff.json",
  "$RunRoot\geometry\station.glb",
  "$RunRoot\audit\glb-semantic-diagnosis.json"
)) {
  if (Test-Path $Unexpected) { throw "win03 已有部分封装输出：$Unexpected" }
}
```

win03 的 P0 `files.sha256` 原始字节是 Windows CRLF。finalizer 以标准文本
换行读取它，再从 639 个真实 SourceRelease 文件重新计算内容和路径，
最终写出 UTF-8 + LF 的 `capture/files.sha256`。这只消除跨平台换行差异；
任一文件摘要、路径或集合变化仍会失败关闭。

## 5. Windows 运行 P1 finalizer

使用仓库虚拟环境。finalizer 本身不实例化机器人 Provider，但封装后 verifier
会导入 `unilab_arm_cr5`；因此两步必须统一使用能够加载仓库领域包的 `.venv`，
不能改用只安装了基础依赖的系统 Python：

```powershell
$Python = "$Repo\.venv\Scripts\python.exe"

if (-not (Test-Path $Python -PathType Leaf)) { throw "缺少仓库 Python 环境" }
& $Python -c "import unilab_arm_cr5; print(unilab_arm_cr5.__file__)"
if ($LASTEXITCODE -ne 0) { throw "仓库环境无法加载 unilab_arm_cr5 Provider" }

& $Python "$Repo\scripts\finalize_station_handoff.py" `
  --output-root $RunRoot `
  --source-release-root "$RunRoot\source-release" `
  --snapshot "$RunRoot\capture\assembly.snapshot.json" `
  --capture-report "$RunRoot\capture\capture-report.json" `
  --render-glb "$Pending\station.glb" `
  --repeat-snapshot "$RunRoot\audit\repeat\assembly.snapshot.json" `
  --repeat-capture-report "$RunRoot\audit\repeat\capture-report.json" `
  --repeat-render-glb "$Pending\station-repeat.glb" `
  --p0-files-sha256 "$RunRoot\audit\p0-a\files.sha256" `
  --glb-semantic-diagnosis $Diagnosis `
  --station "eit.feeding-station"

if ($LASTEXITCODE -ne 0) { throw "win03 P1 封装失败" }
```

不得为了通过而删除 `--p0-files-sha256`、交换两份 GLB、修改诊断 JSON
或手工生成 `station-handoff.json`。

## 6. Windows 封装后自检

以下文件必须全部存在：

```powershell
$Required = @(
  "$RunRoot\station-handoff.json",
  "$RunRoot\P1-REPORT.md",
  "$RunRoot\capture\files.sha256",
  "$RunRoot\capture\source.json",
  "$RunRoot\geometry\station.glb",
  "$RunRoot\audit\repeat\station.glb",
  "$RunRoot\audit\glb-semantic-diagnosis.json",
  "$RunRoot\audit\reproducibility-report.json"
)
foreach ($Path in $Required) {
  if (-not (Test-Path $Path -PathType Leaf)) { throw "封装缺少：$Path" }
}

& $Python "$Repo\scripts\verify_station_handoff.py" `
  "$RunRoot\station-handoff.json" `
  --output "$RunRoot\audit\windows-preflight-validation.json"
if ($LASTEXITCODE -ne 0) { throw "Windows 封装后 verifier 失败" }

$Validation = Get-Content "$RunRoot\audit\windows-preflight-validation.json" -Raw | ConvertFrom-Json
if (-not $Validation.passed) { throw ($Validation.errors -join "; ") }
if ($Validation.qualification -ne "source-input-validated") {
  throw "Windows preflight qualification 错误"
}
```

Windows 自检通过只能把状态写成 `ready-for-mac-validation`；不能代替
Mac 独立 P1 验收。`open_warnings=2` 必须保留在报告和人工解释中。

## 7. Windows 返回完整 win03

冻结封装成功后的整个
`feeding-station-20260827-win03/`，通过非 Git 通道原样返回 Mac。
不要只传 `station-handoff.json` 或两份 GLB。

返回前生成以下回执：

```text
Run ID: feeding-station-20260827-win03
Windows Git HEAD:
Mac diagnosis SHA-256: f61da2e59a0d561f82f1f21bdab655453d12dd172a892c14f6471772a220460c
station-handoff.json SHA-256:
capture/files.sha256 SHA-256:
source_files_digest:
P1-REPORT.md SHA-256:
Windows preflight passed:
Windows preflight qualification:
open_warnings=2 解释:
完整目录文件数 / 总字节数:
传输方式:
封装人和 ISO-8601 时间:
当前状态: ready-for-mac-validation
```

Mac 收到后会再独立运行：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/feeding-station-20260827-win03/station-handoff.json \
  --output incoming/feeding-station-20260827-win03/mac-validation.json
```

只有以下组合才能开始真实 P2 decomposition：

```text
passed=true
qualification=source-input-validated
errors=[]
```

## 8. 强制停止条件

- Mac 诊断 JSON 字节数或 SHA-256 不匹配；
- 两份 pending GLB、snapshot 或四份 P0 清单任一哈希变化；
- win03 已有不完整或来源不明的封装输出；
- finalizer 或 Windows verifier 返回非零；
- `source_files_digest`、父图、component count 或重复采集门禁失败；
- 需要修改 win03 原始证据、手改验证报告或降级语义算法才能继续；
- 有人要求把 GLB 可显示或 Windows preflight 等同于 Mac P1、P2、W2、
  collision、interlock 或 execution 通过。

任一停止条件命中时，保留 win03、原始诊断、日志和失败报告。如必须重采，
使用新 Run ID，不得原地修改 win03 使其“通过”。
