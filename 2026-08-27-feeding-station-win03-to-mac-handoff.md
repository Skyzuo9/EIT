# 投料站 win03：Windows → Mac W1 语义诊断交接手册

日期：2026-08-27

Run ID：`feeding-station-20260827-win03`

原始接收状态：`ready-for-mac-glb-semantic-diagnosis`

Mac 已完成状态：`approved-for-p1-packaging`

禁止状态：尚未封装，不是 `source-input-validated`

本文只处理 win03 两次 SolidWorks W1 采集的 GLB 字节差异。Mac 必须先独立运行
平台无关的语义诊断，把与本轮两个 SHA-256 精确绑定的 JSON 通过非 Git 通道返回
Windows；Windows 封装后，Mac 再对完整 handoff 做 P1 独立验收。

2026-08-27 Mac 真实诊断已通过。Windows 现在应按
[`2026-08-27-feeding-station-win03-mac-to-windows-p1-packaging-handoff.md`](./2026-08-27-feeding-station-win03-mac-to-windows-p1-packaging-handoff.md)
核对诊断 SHA-256、执行 finalizer 并返回完整 win03。

总流程仍以
[`2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](./2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)
为准。win02 已被 win03 替代，不要修改、补写或继续验收 win02。

## 1. Windows 已完成的事实

Windows 使用更新后的 `SwPackAndGoAdapter/trial-v2-exact-parent`，在两个全新的
SOLIDWORKS Premium 2025 SP5.0 进程中，对只读 SourceRelease 独立采集两次。

| 检查项 | 结果 |
|---|---:|
| SourceRelease 文件数 | 639 |
| CAD 文件数 | 447 |
| SourceRelease 总字节数 | 296,937,067 |
| `source_files_digest` | `f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d` |
| P0-A / P0-B / P0-after `files.sha256` 字节哈希 | `54e9158e5b42ec0a75c1db6e0b6771c5d0c9d11cdf7f16f4f7a4a574a16609db` |
| 顶层装配 | `投料站方案模拟1.1.SLDASM` |
| 顶层装配 SHA-256 | `59d3974bf6b6466a0b6b2e945f1a891515cab719e463e72cdfaecbf0cadc4cdd` |
| 两次 instance 数 | 2021 / 2021 |
| 两次真实根数 | 25 / 25 |
| 两次精确 `Name2` 父关系恢复数 | 1996 / 1996 |
| 两次 `open_errors` | 0 / 0 |
| 两次 `open_warnings` | 2 / 2，必须保留到最终回执 |
| 两次 snapshot 字节 SHA-256 | `aeb869a6b2da85125d0c7def63056595826a6abfe0962ff45ea36a52d8d0eb2d` |
| 首采耗时 | 3087.190 秒 |
| 复采耗时 | 1939.776 秒 |

P0-A、P0-B、P0-after 和独立 SourceRelease 复算结果完全一致；639 个 release 文件
全部是只读。两份 snapshot 也字节级一致。当前唯一未通过字节级重复性门禁的是两份
GLB，因此 Windows 没有运行 finalizer，也没有生成 `station-handoff.json`。

## 2. Mac 接收边界与不可变哈希

Windows 发送源目录：

```text
E:\资产管线unilab\handoff\feeding-station-20260827-win03\
  audit\pending-glb-semantic-diagnosis\
    station.glb
    station-repeat.glb
```

必须通过移动硬盘、受控 SMB 或团队批准的其他非 Git 通道传输；不要提交 CAD、GLB、
handoff 或诊断结果到 GitHub。Mac 建议接收到：

```text
<mac-repo>/incoming/feeding-station-20260827-win03-glb-diagnosis/
  station.glb
  station-repeat.glb
```

Mac 在运行任何脚本前执行：

```bash
cd <mac-repo>
shasum -a 256 \
  incoming/feeding-station-20260827-win03-glb-diagnosis/station.glb \
  incoming/feeding-station-20260827-win03-glb-diagnosis/station-repeat.glb
wc -c \
  incoming/feeding-station-20260827-win03-glb-diagnosis/station.glb \
  incoming/feeding-station-20260827-win03-glb-diagnosis/station-repeat.glb
```

只接受以下精确结果：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `station.glb` | 283,695,812 | `f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746` |
| `station-repeat.glb` | 283,695,632 | `fc4891a53de809140c48fa8827c93d94853a2ecd71d8354750c309b753802768` |

任一字节数或哈希不符时停止，不要运行诊断，也不要重命名某个旧文件冒充本轮文件；
删除 Mac 上的不完整接收副本，再从同一个 Windows pending 目录重新复制。

## 3. Mac 同步代码并运行语义诊断

在 Mac 的代码仓库执行：

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
git status --short --branch

./.venv/bin/python -m unittest discover -s tests -v

./.venv/bin/python scripts/diagnose_station_glb_semantics.py \
  incoming/feeding-station-20260827-win03-glb-diagnosis/station.glb \
  incoming/feeding-station-20260827-win03-glb-diagnosis/station-repeat.glb \
  --output incoming/feeding-station-20260827-win03-glb-diagnosis/glb-semantic-diagnosis.json
```

诊断器必须由 Mac 本机仓库代码重新解析两份 GLB；不得接受 Windows 手写的
`passed`，不得只比较 nodes/meshes/primitives 数量，也不得因为肉眼显示相似而通过。

## 4. 语义诊断的唯一通过组合

Mac 打开 `glb-semantic-diagnosis.json`，只在以下条件全部满足时返回 Windows：

```text
schema=lab.station_glb_semantic_diagnosis/v0
status=passed
validator_role=mac-p1-semantic-diagnostics
exact_glb_match=false
normalized_glb_semantic_match=true
difference_class=component_traversal_order_only
approved_for_p1_packaging=true
primary_glb.sha256=f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746
repeat_glb.sha256=fc4891a53de809140c48fa8827c93d94853a2ecd71d8354750c309b753802768
primary_semantic_sha256=repeat_semantic_sha256
```

如果命令返回非零，或出现
`difference_class=semantic_difference_requires_investigation`，Mac 应保留原始 GLB 与失败
JSON，返回 `needs-windows-recapture`。不得修改 JSON、重排 GLB 或放宽算法后使其通过。

## 5. Mac 返回给 Windows 的第一阶段回执

通过非 Git 通道返回原始 `glb-semantic-diagnosis.json`，并同时发送以下文本：

```text
Run ID: feeding-station-20260827-win03
Mac Git HEAD:
station.glb SHA-256:
station-repeat.glb SHA-256:
glb-semantic-diagnosis.json SHA-256:
status:
normalized_glb_semantic_match:
difference_class:
approved_for_p1_packaging:
诊断人和 ISO-8601 时间:
```

Mac 此时只批准或拒绝 Windows 的 P1 封装资格；不要在 Mac 上生成
`station-handoff.json`，也不要把状态写成 `source-input-validated`。

## 6. Windows 收到通过诊断后的封装命令

此节用于双方核对下一步，不授权 Mac 代替 Windows 封装。Windows 把 Mac 原始 JSON
保存为新文件，例如：

```text
E:\资产管线unilab\handoff\feeding-station-20260827-win03\audit\incoming-mac\glb-semantic-diagnosis.json
```

然后运行：

```powershell
$Repo = "E:\资产管线unilab\unilab-asset-pipeline"
$RunRoot = "E:\资产管线unilab\handoff\feeding-station-20260827-win03"
$Pending = "$RunRoot\audit\pending-glb-semantic-diagnosis"
$Diagnosis = "$RunRoot\audit\incoming-mac\glb-semantic-diagnosis.json"
$Python = "C:\Program Files\Python311\python.exe"

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

finalizer 会再次检查诊断 schema、算法、通过状态、差异分类和两个 GLB 绑定哈希；任一
不符都会失败关闭。

## 7. Mac 对完整 win03 做最终 P1 验收

Windows 成功封装后，才把完整且不可变的
`feeding-station-20260827-win03/` 通过非 Git 通道交回 Mac。Mac 接收到：

```text
<mac-repo>/incoming/feeding-station-20260827-win03/
```

然后运行：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/feeding-station-20260827-win03/station-handoff.json \
  --output incoming/feeding-station-20260827-win03/mac-validation.json
```

最终进入 P2 的唯一允许组合是：

```text
passed=true
qualification=source-input-validated
errors=[]
```

`open_warnings=2` 仍必须出现在回执和人工解释中。Mac 独立验收通过前，不得开始真实
P2 批准或 W2 设备级几何导出。

## 8. 强制停止条件

- 任一接收文件的字节数或 SHA-256 与本文不一致；
- Mac checkout 不包含本手册及 `solidworks-gltf-scene-geometry-payload/v2` 实现；
- 诊断不是 Mac 本机从两份原始 GLB 重新生成；
- 语义哈希不同、difference class 不是 `component_traversal_order_only`；
- Windows finalizer 拒绝诊断绑定或 P0/父图/snapshot 门禁；
- 完整 handoff 的 Mac verifier 没有得到 `source-input-validated`；
- 有人要求把显示成功等同于 collision、interlock、kinematics 或 execution 通过。

遇到任一停止条件时，保留 win03、两份原始 GLB、日志和失败 JSON。需要重新采集时使用
新的 Run ID，不得修改 win03 使其“通过”。
