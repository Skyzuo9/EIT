# 投料站：Mac → Windows 下一轮交接与 W2 开发手册

日期：2026-08-27
对象：Windows / SolidWorks / CAD 负责人
当前状态：`ready-for-mac-validation`；尚未取得真实 win02 的 Mac 独立通过回执

本文承接两份既有文档：

- Windows 采集与封装总流程：
  [`2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](./2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)
- win02 的不可变文件数、字节数和哈希：
  [`2026-08-27-feeding-station-win02-mac-handoff.md`](./2026-08-27-feeding-station-win02-mac-handoff.md)

本手册不要求重做 win02。它说明 Mac 已新增哪些门禁、Windows 现在应交什么、
如何参与 P2 人审，以及什么条件满足后才可开始 W2 设备级几何开发。

## 1. 当前结论和证据边界

Mac 已在提交 `839419b` 完成并用合成夹具验证：

- P1 验证器会独立检查源文件清单、聚合摘要、occurrence 父图/根集合/环、两次
  snapshot、capture component count、GLB 2.0 结构/几何统计和绝对路径边界；
- 两份 GLB 字节不同时，会独立复算
  `solidworks-gltf-scene-geometry-payload/v2` 语义签名并核对诊断文件绑定哈希；
- P2 分解只接受 snapshot 中精确的 `subtree_root`，支持同 family 多实例，并生成
  `station-layout.json`、`coverage-report.json` 和 `DECOMPOSITION-REVIEW.md`；
- Mac 根目录测试 17/17、既有 CR5/FR5 回归 6/6 通过。

以上是软件/夹具证据。当前 Mac 仓库的 `incoming/` 中没有完整的真实 win02，故尚未
产生真实 `mac-validation.json passed=true`，也没有已批准的真实 decomposition。
远端文档中的 666 个文件、870477910 字节和 2021 个 occurrence 是 Windows 产出记录，
仍须通过完整非 Git 传输后由 Mac 独立复算。

本轮没有证明 collision、空间互锁、现场点位、标定、工作流执行或真机资格。

## 2. Windows 先同步 GitHub

在代码仓库执行，不要在 CAD 源目录执行：

```powershell
$Repo = "D:\unilab\unilab-asset-pipeline"
$RequiredCommit = "839419b"

git -C $Repo fetch --prune origin
git -C $Repo switch main
git -C $Repo pull --ff-only
git -C $Repo merge-base --is-ancestor $RequiredCommit HEAD
if ($LASTEXITCODE -ne 0) { throw "仓库缺少 Mac P1/P2 门禁提交 $RequiredCommit" }

git -C $Repo submodule update --init --recursive
git -C $Repo lfs pull
git -C $Repo rev-parse HEAD
git -C $Repo status --short --branch
```

如果是专用干净 checkout，`status --short` 应无本地修改。不要用 `reset --hard` 清理
未知改动；先保留状态输出并确认所有权。

可在没有 SolidWorks 的情况下先跑平台无关测试：

```powershell
$Python = "$Repo\.venv\Scripts\python.exe"
& $Python -m unittest discover -s "$Repo\tests" -v
if ($LASTEXITCODE -ne 0) { throw "工站合同测试失败" }
```

当前基线预期为 17 个测试通过。若环境还没有 `.venv`，沿既有运行手册安装 Python
与仓库依赖；不要为了得到“通过”而跳过失败测试。

## 3. 第一优先级：原样交付不可变 win02

Windows 上的唯一交付源应为：

```text
feeding-station-20260827-win02/
```

交付前只读核对，不再运行 exporter、finalizer 或修改任何 JSON：

```powershell
$RunId = "feeding-station-20260827-win02"
$RunRoot = "D:\unilab-handoff\$RunId"
$ExpectedManifest = "0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9"

$Files = Get-ChildItem $RunRoot -Recurse -File
if ($Files.Count -ne 666) { throw "win02 文件数变化：$($Files.Count)" }
$Bytes = [int64](($Files | Measure-Object Length -Sum).Sum)
if ($Bytes -ne 870477910) { throw "win02 总字节数变化：$Bytes" }

$ManifestHash = (Get-FileHash "$RunRoot\station-handoff.json" -Algorithm SHA256).Hash.ToLower()
if ($ManifestHash -ne $ExpectedManifest) { throw "station-handoff.json 哈希变化" }
```

随后通过移动硬盘、受控 SMB 或团队批准的非 Git 通道，把整个目录复制到 Mac：

```text
<mac-repo>/incoming/feeding-station-20260827-win02/
```

不要把 handoff、CAD 或 GLB 提交到 GitHub；不要压缩后只传部分文件；不要在传输失败
后原地补写 win02。若传输副本不完整，删除接收端副本并从同一个不可变源重新复制。

Windows 发出的状态只能是：

```text
ready-for-mac-validation
```

在收到 Mac 回执前，不得写成 `source-input-validated`。

## 4. Mac 必须返回的 P1 回执

Mac 会运行：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/feeding-station-20260827-win02/station-handoff.json \
  --output incoming/feeding-station-20260827-win02/mac-validation.json
```

Windows/CAD 负责人应收到并留存以下回执文本；`mac-validation.json` 本身仍经非 Git
通道传回：

```text
Run ID: feeding-station-20260827-win02
Mac Git HEAD:
station-handoff.json SHA-256:
mac-validation.json SHA-256:
passed:
qualification:
errors:
warnings / open_warnings=2 解释:
验收人和时间:
```

进入 P2 的唯一允许组合是：

```text
passed=true
qualification=source-input-validated
errors=[]
```

`open_warnings=2` 必须在回执中保留并解释，不能静默删除。若前置哈希正确但 verifier
失败，Windows 状态改为 `needs-windows-recapture`：保留 win02 和失败报告，用新 RunId
重新采集；不得修改 win02 使其“通过”。

## 5. Windows/CAD 参与 P2 人审

Mac 验证通过后才会基于真实 occurrence 起草
`lab.station_decomposition/v1`。Mac 应把以下四个文本产物经评审通道交给 Windows：

```text
station-decomposition.yaml
station-layout.json
coverage-report.json
DECOMPOSITION-REVIEW.md
```

Windows/CAD 负责人逐条核对：

1. 每个 `subtree_root` 是 snapshot 中完整、精确的 occurrence ID；
2. 根的全部后代只属于一个设备，不把相邻设备或站体误包进去；
3. 重复料架、导轨和同型号设备均按真实实例分别列出；
4. 机器人子树只替换为 `robot-family:dobot.cr5`，SolidWorks 几何保持
   `comparison_only`；
5. 隐藏、抑制和虚拟组件均有明确处置；
6. `unassigned_occurrences=[]`，coverage 无重复归属；
7. `source_handoff_digest` 与 win02 的 `station-handoff.json` 字节哈希一致；
8. 没有把 `device_id`、base pose、TCP、payload、点表或标定写进分解表。

发现边界错误时，返回精确 occurrence ID 和理由，由 Mac 修改 YAML 并重新编译；不要
直接手改 `station-layout.json` 或 `coverage-report.json`。批准记录必须填写真实审核人、
ISO-8601 时间和说明。只有重新编译后同时出现以下结果才可回到 Windows：

```text
approval.status=approved
human_reviewed=true
publication_eligible=true
qualification=station-layout-candidate
unassigned_occurrences=[]
```

此时双方状态才可变为 `approved-for-w2-geometry-export`。它仍不是 DeployManifest、
WorkCellActivation、碰撞资格或执行许可。

## 6. W2 设备级几何开发合同

当前仓库尚无已验收的 Windows W2 设备级 exporter；因此收到 P2 批准前不要开始真实
W2 导出，收到后也应先实现/测试合同，再生成正式 handoff。禁止用显示名或前缀搜索
代替已批准的 exact occurrence roots。

W2 使用新 RunId，例如 `feeding-station-20260828-win03-w2`，不得覆盖 win02。目标目录：

```text
feeding-station-<date>-<run>-w2/
  geometry-handoff.json
  approval/
    station-decomposition.yaml
    station-layout.json
    coverage-report.json
    DECOMPOSITION-REVIEW.md
  devices/
    <device-instance>/
      render.glb
      entity-map.json
      export-report.json
      files.sha256
```

第一条纵切至少覆盖：料架、导轨外壳、CR5 CAD 对照几何和 4 ml 瓶。每个输出必须：

- 绑定 win02 handoff SHA-256 与批准后的 decomposition SHA-256；
- 记录 exact `subtree_root`、SolidWorks 版本、配置、单位、导出器版本和只读事实；
- 在 `entity-map.json` 中把每个 GLB node 对齐到精确 occurrence ID；无法映射时只能标
  `visual-only`，不能标 `semantic-scene`；
- 记录 bytes、nodes、meshes、primitives、vertices、triangles、包围盒与材质统计；
- 两次独立导出的 entity 集合和语义几何签名一致；
- 对 4 ml 瓶显式声明 `source_unit=mm`；
- 对机器人明确 `comparison_only=true`，正式运动学仍来自厂家 CR5 Provider；
- 找不到 exact root、混入其他设备、单位不明、摘要漂移或两次语义不一致时失败关闭。

不要把 `render.glb` 能显示当作碰撞或运动学通过。W2 完整目录仍走非 Git 通道；Git
只提交 exporter、schema、测试、小型审计文本和批准记录。

## 7. 下一轮 Windows 回执模板

```text
Git HEAD:
Run ID:
上游 win02 station-handoff SHA-256:
批准 decomposition SHA-256:
exact subtree roots:
W2 文件数 / 总字节数:
geometry-handoff.json SHA-256:
两次导出语义一致性:
机器人 comparison_only:
4 ml 瓶 source_unit:
SolidWorks 版本 / 配置:
Windows 测试结果:
传输方式:
负责人和时间:
当前状态: ready-for-mac-w2-validation
```

任何一项未知就写 `unknown` 并停止在对应门禁，不要用 `passed` 代替缺失证据。

## 8. 强制停止条件

- Mac 尚未返回真实 win02 的 `source-input-validated`；
- P2 仍是 draft、coverage 有未分配/重叠，或审核身份/时间缺失；
- Windows checkout 不包含提交 `839419b`；
- 需要修改 win02、CAD 唯一源或已批准编译产物才能继续；
- W2 只能靠显示名猜根、node 无 occurrence 映射或单位不明；
- 任一摘要、文件数、父图、component count、GLB 结构或重复采集语义不一致；
- 需要把 collision、interlock 或 execution 写成通过才能推进。

遇到停止条件时保留原 RunId、日志和失败报告，修复后用新 RunId 重跑。
