# 投料站 GCR5-910：Mac → Windows P2 审核与 W2 准备手册

日期：2026-08-28

Run ID：`feeding-station-20260827-win03`

Mac 当前状态：`p2-draft-generated`

允许的 Windows 下一步：复算 proposal、机械/CAD 审核、签署 P2；只有签署后的
compiler 输出保持 2021/2021 唯一覆盖，才可启动新的 W2 Run ID。

禁止状态：当前不是 `approved-for-w2-geometry-export`，不得把 draft、URDF 能运动或
GLB 能显示当作真实 W2、碰撞或执行许可。

本手册替代较早文档中针对投料站的 Dobot CR5 假设。真实 win03 occurrence 和固定
GitHub URDF 已证明总装机器人是 **DUCO GCR5-910**。

前置报告：

- [`2026-08-28-feeding-station-gcr5-automation-report.md`](./2026-08-28-feeding-station-gcr5-automation-report.md)
- [`2026-08-28-feeding-station-pending-decisions.md`](./2026-08-28-feeding-station-pending-decisions.md)
- [`2026-08-28-feeding-station-unilab-workbench-preview-report.md`](./2026-08-28-feeding-station-unilab-workbench-preview-report.md)
- [`2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md`](./2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md)
- [`2026-08-28-feeding-station-win03-windows-to-mac-p1-validation-handoff.md`](./2026-08-28-feeding-station-win03-windows-to-mac-p1-validation-handoff.md)

## 1. Mac 已完成的结果

| 项目 | 结果 |
|---|---|
| P1 | `passed=true`、`source-input-validated`、`errors=[]` |
| snapshot | 2021 occurrence、25 roots |
| legacy URDF CSV | 19 包、49/49 `SW Components` 匹配 |
| GCR5 CSV | 7/7 link 组件匹配 |
| 自动 decomposition | 53 条规则 |
| draft compiler | 2021/2021、未分配 0、重叠 0 |
| approval | `draft` |
| publication eligible | `false` |
| 根仓测试 | 26/26 |
| SourceRelease + 投料站预览测试 | 8/8 |
| Pascal glTF/Material Graph 回归 | 66/66 |
| Mac Workbench Material Graph | 1 个投料站节点，`format=gltf` |

机器人 exact root：

```text
机器人移动轴模组(默认-_flexible1)-1/机器人_GCR5-910_新松(默认-_flexible1)(默认-_flexible1)-1
```

机器人 replacement：

```text
robot-family:duco.gcr5_910
```

4 ml 有盖瓶首条代表几何：

```text
投料站料架-1/4ml玻璃瓶料架.SLDPRT-1/4ml玻璃瓶(Default_按加工_)-1
```

Mac 已增加摘要锁定的整站 Workbench 静态预览。它使用 P1 完整 GLB 和 P2 draft
coverage receipt，不等于已批准的设备级 W2。Windows 审核前可把该画面作为边界检查
参考，但不得从画面反推碰撞、TCP、槽位或执行资格。

## 2. Windows 同步 GitHub

在代码 checkout 执行，不要在 CAD 唯一源目录执行：

```powershell
$Repo = "E:\资产管线unilab\unilab-asset-pipeline"
$RequiredCommit = "8dfcdf435543930197011f320868c7ab234c3d4a"

git -C $Repo fetch --prune origin
git -C $Repo switch main
git -C $Repo pull --ff-only origin main
git -C $Repo merge-base --is-ancestor $RequiredCommit HEAD
if ($LASTEXITCODE -ne 0) { throw "缺少 GCR5/P2 自动化提交" }

git -C $Repo rev-parse HEAD
git -C $Repo status --short --branch
```

不要使用 `reset --hard` 清理未知改动。若 status 不干净，先记录并确认所有权。

## 3. 自动取得固定 GCR5 SourceRelease

代码只记录 GitHub URL、commit 和摘要，不把第三方 ZIP/STL 提交到本仓。Windows 用
仓库虚拟环境下载：

```powershell
$Python = "$Repo\.venv\Scripts\python.exe"

& $Python "$Repo\scripts\fetch_robot_source_release.py" duco_gcr5_910
if ($LASTEXITCODE -ne 0) { throw "GCR5 SourceRelease 下载/摘要校验失败" }

$Gcr5Zip = "$HOME\Downloads\机械臂control\DUCO_GCR5\robot_dc-94d4030db170edaa986b8d1243fd8ae27d45cffd.zip"
$ExpectedZip = "c91cd096d8c6acde34bb57c85d4b7916c6ab17dc22feff09c502f29256230612"
$ActualZip = (Get-FileHash $Gcr5Zip -Algorithm SHA256).Hash.ToLower()
if ($ActualZip -ne $ExpectedZip) { throw "GCR5 ZIP SHA-256 不匹配" }
```

固定源：

```text
repository=https://github.com/yizhongzhang1989/robot_dc
commit=94d4030db170edaa986b8d1243fd8ae27d45cffd
zip_sha256=c91cd096d8c6acde34bb57c85d4b7916c6ab17dc22feff09c502f29256230612
urdf_sha256=76e95464d07ec304bf9394b640540a87193fa977420486c348e578e9cbd38858
authority=project-cad-export
qualification=kinematic-preview-only
```

上游仓库无根许可证；`package.xml` 虽声明 BSD，仍不得把本地 ZIP/mesh 重新提交到
GitHub。若组织要再分发这些文件，先由许可证负责人确认。

## 4. Windows 独立复算 P2 proposal

使用完整、不可变的 win03：

```powershell
$RunRoot = "E:\资产管线unilab\handoff\feeding-station-20260827-win03"
$P2 = "$RunRoot\p2-auto"

& $Python "$Repo\scripts\propose_station_decomposition_from_urdf.py" `
  "$RunRoot\station-handoff.json" `
  --legacy-urdf-root "$RunRoot\source-release\投料站-urdf" `
  --output-dir $P2
if ($LASTEXITCODE -ne 0) { throw "P2 proposal 自动生成失败" }

& $Python "$Repo\scripts\compile_station_decomposition.py" `
  "$RunRoot\station-handoff.json" `
  "$P2\station-decomposition.proposal.yaml" `
  --allow-draft `
  --output "$P2\station-layout.draft.json"
if ($LASTEXITCODE -ne 0) { throw "P2 draft 编译失败" }
```

必须同时检查：

```powershell
$Evidence = Get-Content "$P2\urdf-occurrence-evidence.json" -Raw | ConvertFrom-Json
$Layout = Get-Content "$P2\station-layout.draft.json" -Raw | ConvertFrom-Json

if ($Evidence.snapshot_occurrence_count -ne 2021) { throw "snapshot 数量错误" }
if ($Evidence.package_count -ne 20) { throw "URDF package 数量错误" }
if ($Evidence.selected_rule_count -ne 53) { throw "自动规则数量漂移" }
if ($Evidence.robot_occurrence_roots.Count -ne 1) { throw "机器人根不唯一" }
if ($Layout.occurrence_coverage.Count -ne 2021) { throw "coverage 不是 2021" }
if ($Layout.unassigned_occurrences.Count -ne 0) { throw "存在未分配 occurrence" }
if ($Layout.publication_eligible) { throw "draft 不应可发布" }
```

Mac 核心 proposal SHA-256 是：

```text
station-decomposition.proposal.yaml
725ca56250ca6d0c2f19d7ac0392ff40d91dd81a7776305a67929933ff8ebb8c
```

若 Windows 使用相同 win03 和仓库版本，proposal 应一致。evidence JSON 包含绝对本地
路径，Windows 与 Mac 的 evidence 文件字节摘要可以不同；应比较 token、candidate
roots、规则和 coverage，不以绝对路径差异判失败。

## 5. 机械/CAD 审核清单

审核人打开：

```text
p2-auto/URDF-OCCURRENCE-REVIEW.md
p2-auto/station-decomposition.proposal.yaml
p2-auto/DECOMPOSITION-REVIEW.md
```

只需要集中审核以下边界：

1. GCR5 exact root 是否只含 J0–J6 本体；
2. ETH17 根、机器人安装板、NMR 夹爪和其他末端工具是否正确分离；
3. `station-assembly-shell:*` 兜底组是否需要改为正式 family 名；
4. 4 ml 有盖瓶是否仅作为代表几何；若要求物理实例，必须补槽位/编号政策；
5. 隐藏、抑制、虚拟组件是否允许保留在所属父壳；
6. 机器人 CAD 始终为 `comparison_only`；
7. `open_warnings=2` 保留解释为两次 `swFileLoadWarning_ReadOnly`，且
   `open_errors=0`。

GCR5 URDF 的六轴没有厂家 limit。清单注入的 `±π`、`effort=1`、`velocity=0.5`
只能用于本地预览；审核人不能据此批准真机限位、碰撞或执行。

## 6. 签署并重新编译

把 proposal 复制为正式待签文件，不要手改 layout/coverage：

```powershell
$Approved = "$P2\station-decomposition.yaml"
if (Test-Path $Approved) { throw "正式待签文件已存在；不要覆盖" }
Copy-Item "$P2\station-decomposition.proposal.yaml" $Approved
```

机械/CAD 审核人可以修正 exact roots、family 和 review note，然后仅填写：

```yaml
approval:
  status: approved
  reviewed_by: <真实姓名或团队身份>
  reviewed_at: <ISO-8601 含时区>
  notes: <GCR5/ETH17/4ml/warning 审核说明>
```

重新编译，不使用 `--allow-draft`：

```powershell
& $Python "$Repo\scripts\compile_station_decomposition.py" `
  "$RunRoot\station-handoff.json" `
  $Approved `
  --output "$P2\station-layout.json"
if ($LASTEXITCODE -ne 0) { throw "批准后的 P2 编译失败" }

$ApprovedLayout = Get-Content "$P2\station-layout.json" -Raw | ConvertFrom-Json
if (-not $ApprovedLayout.human_reviewed) { throw "human_reviewed 不是 true" }
if (-not $ApprovedLayout.publication_eligible) { throw "publication_eligible 不是 true" }
if ($ApprovedLayout.qualification -ne "station-layout-candidate") { throw "qualification 错误" }
if ($ApprovedLayout.occurrence_coverage.Count -ne 2021) { throw "批准后 coverage 漂移" }
```

只有这一步成功后，状态才可写为：

```text
approved-for-w2-geometry-export
```

## 7. W2 准备

使用新的、以 `-w2` 结尾的 Run ID，不覆盖 win03。基于：

```text
config/station-geometry-export-plan.template.json
```

第一条纵切仍至少包含 rack、ETH17 rail shell、GCR5 CAD comparison 和 4 ml bottle。
模板和 finalizer 已支持 `robot-family:duco.gcr5_910`；机器人纵切必须：

```text
slice_role=robot-cad-comparison
qualification=comparison-only
comparison_only=true
family=robot-family:duco.gcr5_910
subtree_root=<批准的 exact GCR5 root>
```

不要修改冻结的 P1 `station-handoff.json`。其中 Dobot CR5 字段是机器人身份修正前的
历史输入记录；P2/W2 以本次固定 GCR5 SourceRelease、批准 decomposition 和 layout
为准。若后续需要完全消除该历史字段，应建立新的 handoff Run ID，不能原地改 win03。

## 8. Windows 回执模板

```text
Git HEAD:
GCR5 ZIP SHA-256:
P2 proposal SHA-256:
URDF packages / matched tokens:
机器人 exact root:
ETH17 exact root:
4 ml 代表 occurrence:
审核人 / ISO-8601 时间:
approved decomposition SHA-256:
approved layout SHA-256:
coverage assigned / total:
unassigned / overlap:
open_warnings=2 解释:
新 W2 Run ID（未批准则写 not-started）:
当前状态:
```

## 9. 强制停止条件

- Git 不包含 required commit 或 GCR5 ZIP/URDF 摘要不匹配；
- 不是完整的已验证 win03，或 snapshot 不再是 2021 occurrence / 25 roots；
- 56 个 SW Components token 任一无法匹配，机器人根不唯一；
- proposal/compiler 出现未分配、重叠、非法排除根或 coverage 不是 2021/2021；
- 审核人、时间、GCR5/ETH17/4 ml/warning 说明缺失；
- 要求把项目 CAD URDF 当作厂家 joint limit、qualified collision 或真机执行证据；
- 需要修改冻结 win03、手改 layout/coverage 或跳过 compiler 才能继续；
- 上游许可证不允许所计划的再分发方式。

命中任一条件时保留 proposal、evidence、日志和原 win03，状态保持 draft；不得启动
真实 W2。
