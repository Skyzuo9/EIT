# 投料站 win03：Windows → Mac P1 独立验收交接手册

日期：2026-08-28

Run ID：`feeding-station-20260827-win03`

Windows 当前状态：`ready-for-mac-validation`

Mac 验收目标：仅当 Mac 独立复算得到
`passed=true`、`qualification=source-input-validated`、`errors=[]` 时，P1 才完成
双方验收。

本手册交接 Windows 已完成封装的真实 win03 目录，指导 Mac 在不信任 Windows
校验结论的前提下重新核对接收字节、Git/Provider 环境、639 个 SourceRelease
文件、occurrence 父图、两份 GLB 的语义复现性和 CR5 厂家 Provider。

它不批准 P2 分解结果、Windows W2 设备级几何导出、kinematic preview、
collision、spatial interlock 或 execution。

前置文档：

- Windows P1 封装流程：
  [`2026-08-27-feeding-station-win03-mac-to-windows-p1-packaging-handoff.md`](./2026-08-27-feeding-station-win03-mac-to-windows-p1-packaging-handoff.md)
- win03 原始采集交接合同：
  [`2026-08-27-feeding-station-win03-to-mac-handoff.md`](./2026-08-27-feeding-station-win03-to-mac-handoff.md)
- P0–P1 总流程：
  [`2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](./2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)
- design/plan 及 P1/P2/W2 资格边界：
  [`2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md`](./2026-08-26-feeding-station-full-asset-pipeline-development-and-test-design.md)

## 1. Windows 已完成的真实封装

Windows 在 Git HEAD `9b4fc34741f895ff6b972aa98dca3f8c8a87818a` 上接收并固定
Mac 原始语义诊断，运行 P1 finalizer，再使用仓库
`.venv\Scripts\python.exe` 独立运行 verifier。

最终结果：

| 检查项 | 结果 |
|---|---|
| `station-handoff.json` SHA-256 | `0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9` |
| Mac diagnosis SHA-256 | `f61da2e59a0d561f82f1f21bdab655453d12dd172a892c14f6471772a220460c` |
| `capture/files.sha256` SHA-256 | `f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d` |
| `source_files_digest` | `f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d` |
| `P1-REPORT.md` SHA-256 | `107bb1fec793c0655f40018881cb53cc8b85f0ddf50ee4c842e16055d7870784` |
| Windows validation SHA-256 | `f1f1387a0d805566d36f41a32132d28c7537b27e2846d1c9d51c8521384d3ee6` |
| Windows validation | `passed=true`、`qualification=source-input-validated`、`errors=[]` |
| 完整目录（Mac 写入验收报告前） | 674 个文件，1,438,155,885 bytes |
| Windows 封装状态 | `ready-for-mac-validation` |

Windows verifier 复算结果还包括：

| 内容 | 结果 |
|---|---|
| occurrence / 真实根 | 2021 / 25 |
| SourceRelease | 639 个文件逐文件通过 |
| 两份规范化 snapshot | 一致 |
| primary GLB | 283,695,812 bytes；SHA-256 `f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746` |
| repeat GLB | SHA-256 `fc4891a53de809140c48fa8827c93d94853a2ecd71d8354750c309b753802768` |
| GLB 字节一致 | `false` |
| GLB 规范化语义一致 | `true` |
| 差异分类 | `component_traversal_order_only` |
| GLB 结构 | 1543 nodes、1396 meshes、1588 primitives、4764 accessors |
| CR5 Provider | Dobot CR5；source digest `8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2`；6 joints、7 meshes |

### Windows 环境审计说明

Windows 第一次按旧手册示例使用系统 Python 3.11 运行 verifier 时，资产、摘要、
父图和 GLB 检查均已通过，但环境无法导入 `unilab_arm_cr5`，所以 verifier 正确
失败关闭。该原始失败报告保存在：

```text
audit/windows-preflight-validation.system-python-failed.json
SHA-256=f841a4204272381ce2dd7231ba1dbbf9ae859575e1f7092d02083ece1f7ac19e
```

随后没有修改任何诊断、GLB、snapshot、SourceRelease 或 handoff 清单，只切换到
仓库 `.venv` 重跑同一个 verifier，得到上表的通过报告。Windows 封装手册已同步
修正为先验证 Provider 可导入，再执行 finalizer/verifier。

## 2. 通过非 Git 通道接收完整目录

Windows 必须返回整个：

```text
feeding-station-20260827-win03/
```

可以使用受控移动硬盘、受控 SMB 或团队批准的其他非 Git 通道。不要只接收
`station-handoff.json`、GLB 或 validation JSON，也不要把该目录、CAD、GLB 或
Mac diagnosis 提交到 GitHub。

假设 Mac 接收位置为：

```bash
export REPO="/path/to/unilab-asset-pipeline"
export INCOMING="$REPO/incoming/feeding-station-20260827-win03"

test -d "$INCOMING" || { echo "缺少完整 win03 目录" >&2; exit 1; }
```

接收目录先保持只读审计状态。Mac verifier 输出前，不要编辑、格式化、重命名或
删除其中任何 Windows 文件。

## 3. Mac 同步 GitHub 与 Provider 环境

Mac 在代码仓库执行：

```bash
cd "$REPO"
git fetch --prune origin
git switch main
git pull --ff-only origin main

required_commit="9b4fc34741f895ff6b972aa98dca3f8c8a87818a"
git merge-base --is-ancestor "$required_commit" HEAD || {
  echo "仓库缺少 win03 finalizer/verifier 提交" >&2
  exit 1
}

git submodule update --init --recursive
git rev-parse HEAD
git status --short --branch
```

必须使用仓库虚拟环境，而不是不能加载领域 Provider 的裸系统 Python：

```bash
test -x "$REPO/.venv/bin/python" || {
  echo "缺少仓库 .venv" >&2
  exit 1
}

"$REPO/.venv/bin/python" - <<'PY'
import unilab_arm_cr5
print(unilab_arm_cr5.__file__)
PY
```

如果 Provider 无法导入，先恢复仓库锁定的 submodule/虚拟环境；不得跳过机器人
验证或修改 `station-handoff.json` 使其通过。

## 4. 写入任何 Mac 报告前核对接收字节

```bash
expect_sha() {
  expected="$1"
  path="$2"
  test -f "$path" || { echo "缺少文件: $path" >&2; exit 1; }
  actual="$(shasum -a 256 "$path" | awk '{print $1}')"
  test "$actual" = "$expected" || {
    echo "SHA-256 不匹配: $path" >&2
    echo "expected=$expected" >&2
    echo "actual=$actual" >&2
    exit 1
  }
}

expect_sha \
  0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9 \
  "$INCOMING/station-handoff.json"
expect_sha \
  f61da2e59a0d561f82f1f21bdab655453d12dd172a892c14f6471772a220460c \
  "$INCOMING/audit/incoming-mac/glb-semantic-diagnosis.json"
expect_sha \
  f61da2e59a0d561f82f1f21bdab655453d12dd172a892c14f6471772a220460c \
  "$INCOMING/audit/glb-semantic-diagnosis.json"
expect_sha \
  f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746 \
  "$INCOMING/geometry/station.glb"
expect_sha \
  fc4891a53de809140c48fa8827c93d94853a2ecd71d8354750c309b753802768 \
  "$INCOMING/audit/repeat/station.glb"
expect_sha \
  aeb869a6b2da85125d0c7def63056595826a6abfe0962ff45ea36a52d8d0eb2d \
  "$INCOMING/capture/assembly.snapshot.json"
expect_sha \
  aeb869a6b2da85125d0c7def63056595826a6abfe0962ff45ea36a52d8d0eb2d \
  "$INCOMING/audit/repeat/assembly.snapshot.json"
expect_sha \
  f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d \
  "$INCOMING/capture/files.sha256"
expect_sha \
  107bb1fec793c0655f40018881cb53cc8b85f0ddf50ee4c842e16055d7870784 \
  "$INCOMING/P1-REPORT.md"
expect_sha \
  f1f1387a0d805566d36f41a32132d28c7537b27e2846d1c9d51c8521384d3ee6 \
  "$INCOMING/audit/windows-preflight-validation.json"
```

核对 Windows 冻结时的完整目录规模：

```bash
file_count="$(find "$INCOMING" -type f | wc -l | tr -d ' ')"
total_bytes="$(find "$INCOMING" -type f -exec stat -f '%z' {} + | \
  awk '{sum += $1} END {printf "%.0f\n", sum}')"

test "$file_count" = "674" || {
  echo "接收文件数不匹配: $file_count" >&2
  exit 1
}
test "$total_bytes" = "1438155885" || {
  echo "接收总字节数不匹配: $total_bytes" >&2
  exit 1
}
```

以上计数发生在 Mac 新建 `mac-validation.json` 之前。Mac 验收报告写入后目录自然
增加一个文件，不应再拿 674 作为封装后计数。

## 5. Mac 独立运行 P1 verifier

Mac 必须从收到的 `station-handoff.json` 独立读取并复算，不能把 Windows
`windows-preflight-validation.json` 当作 Mac 验收结果：

```bash
"$REPO/.venv/bin/python" \
  "$REPO/scripts/verify_station_handoff.py" \
  "$INCOMING/station-handoff.json" \
  --output "$INCOMING/mac-validation.json"

test "$?" -eq 0 || {
  echo "Mac P1 verifier 失败；保留目录和报告" >&2
  exit 1
}
```

再以机器可读方式检查唯一允许的验收组合：

```bash
"$REPO/.venv/bin/python" - "$INCOMING/mac-validation.json" <<'PY'
import json
import pathlib
import sys

report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report.get("passed") is True, report.get("errors")
assert report.get("qualification") == "source-input-validated", report
assert report.get("errors") == [], report.get("errors")
assert report["details"]["source_files_verified"] == 639
assert report["details"]["source_files_digest"] == (
    "f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d"
)
assert report["details"]["instance_count"] == 2021
assert report["details"]["root_occurrence_count"] == 25
assert report["details"]["robot"]["joint_count"] == 6
assert report["details"]["robot"]["mesh_count"] == 7
assert report["details"]["reproducibility"]["normalized_snapshot_match"] is True
assert report["details"]["reproducibility"]["exact_glb_match"] is False
assert report["details"]["reproducibility"]["normalized_glb_semantic_match"] is True
assert report["details"]["reproducibility"]["difference_class"] == (
    "component_traversal_order_only"
)
print("Mac P1 validation passed")
PY
```

## 6. `open_warnings=2` 的人工解释

主采集和重复采集均为：

```text
open_errors=0
open_warnings=2 (0x2)
```

SolidWorks `swFileLoadWarning_e` 中 `0x2` 是
`swFileLoadWarning_ReadOnly`。本轮合同要求 SourceRelease 和顶层装配只读打开，
因此两次采集都稳定记录该 warning。它不是缺引用、内部 ID 不匹配、共享冲突、
自动修复或需要重建；不能从报告里静默删除，也不能把 warning 写成 error。

## 7. Mac 验收回执

验收完成后回传以下内容；`mac-validation.json` 走非 Git 通道随 win03 返回，回执
文本可以进入 Git：

```text
Run ID: feeding-station-20260827-win03
Mac Git HEAD:
接收 station-handoff.json SHA-256: 0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9
mac-validation.json SHA-256:
passed:
qualification:
errors:
warnings:
source_files_verified:
source_files_digest:
instance_count / root_occurrence_count:
GLB normalized semantic match / difference class:
CR5 source digest / joint count / mesh count:
open_warnings=2 解释: 两次均为 swFileLoadWarning_ReadOnly；open_errors=0
验收人和 ISO-8601 时间:
当前状态: source-input-validated（仅在唯一允许组合全部满足时填写）
```

## 8. P1 通过后的唯一下一步

Mac verifier 通过只完成真实 P1 输入资格。随后可以在 Mac 开始 P2 M1：

1. 基于 2021 个真实 occurrence 和 25 个真实根创建/审阅精确
   `station-decomposition.yaml`；
2. 运行 `compile_station_decomposition.py` 生成 layout 和 coverage；
3. 由机械/自动化负责人签署设备边界、重复实例、机器人替换子树、设备锚点以及
   隐藏/抑制 occurrence 的处置；
4. 只有批准后的 decomposition 才能生成新的 W2 Run ID 并交回 Windows。

Mac P1 通过不直接批准 Windows W2。W2 仍必须等待 P2 人签 decomposition，且不得
从显示名模糊搜索、旧 win02、fixture 或未经批准的候选根启动。

## 9. 强制停止条件

- 接收文件数、总字节数或任一锚点 SHA-256 不匹配；
- Mac 使用的 Git 不包含 required commit；
- 仓库 `.venv` 或 `unilab_arm_cr5` Provider 无法加载；
- verifier 返回非零、`passed=false`、qualification 不是
  `source-input-validated` 或 `errors` 非空；
- 639 个 SourceRelease 文件、source digest、2021 occurrence、25 roots、
  两份 snapshot 或 GLB 语义复现性任一不一致；
- 需要修改收到的 JSON、GLB、snapshot、SourceRelease、路径或报告才能通过；
- 有人要求把 Windows preflight、GLB 可显示或 Mac P1 等同于 P2/W2、碰撞、互锁
  或执行资格。

任一停止条件命中时，保留完整原始 win03 和失败的 `mac-validation.json`，报告实际
错误并请求 Windows 重传或按新 Run ID 处理；不得原地修改 win03 使其“通过”。
