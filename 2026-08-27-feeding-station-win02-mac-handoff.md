# 投料站 win02：Windows → Mac P1 交接手册

本文只适用于 Run ID `feeding-station-20260827-win02`。它把 Windows 已完成的
P0-W/P1-W 只读采集交给 Mac 做独立 P1-M 验收。Mac 返回 `passed=true` 之前，
P1 不算完成；不得提前进入 P2 人签 decomposition。

## 1. 固定边界

- GitHub 仓库：`Skyzuo9/unilab-asset-pipeline`
- 分支：`main`
- 本轮语义门禁实现基线：
  `38d729b2fc87f3a8d8af9845b55fea82bb7b08da`
- Run ID：`feeding-station-20260827-win02`
- Windows handoff 文件数：666
- Windows handoff 总字节数：870477910
- `station-handoff.json` SHA-256：
  `0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9`

完整 handoff 目录必须通过移动硬盘、SMB 或等价的非 Git 通道传输。不要提交
`incoming/`、CAD、GLB 或完整 handoff 到 GitHub。

## 2. Windows 已完成的事实

- P0 前两次和采集后第三次 `files.sha256` 完全一致；
- 原始源共有 639 个文件，其中 CAD/中立几何文件 447 个；
- 源发布聚合摘要为
  `f82f6c5298e7e6605d48e75c783a614d1d654482455ae4c7acccf0fea6c8f63d`；
- 两次独立 SolidWorks 2025 SP5.0 只读采集均为 `status=passed`、
  `source_read_only=true`、`open_errors=0`；
- `open_warnings=2` 是本轮已记录的只读打开 warning 位，不是缺引用或修复提示；
- 两次均采得 2021 个 occurrence、0 个 mate candidate；
- 两份 snapshot 字节一致，15 个 SolidWorks 虚拟文档临时目录已规范化为
  `swx<PID>`；
- 两份 GLB 字节不同，但完整静态场景语义签名一致，差异分类为
  `component_traversal_order_only`。

这不证明碰撞、空间互锁、点位、运动学预览或执行资格。

## 3. 关键文件哈希

Mac 在运行任何脚本前至少核对以下 SHA-256：

| 相对 handoff 路径 | 字节数 | SHA-256 |
|---|---:|---|
| `station-handoff.json` | 981 | `0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9` |
| `P1-REPORT.md` | 821 | `d1396afe524c6b9668c6921658c657005fdf74227785ad1fccddf7ec0bfadd37` |
| `capture/files.sha256` | 76329 | `54e9158e5b42ec0a75c1db6e0b6771c5d0c9d11cdf7f16f4f7a4a574a16609db` |
| `capture/assembly.snapshot.json` | 2656123 | `63f66cfd7b20c56edab72365eec890fba10558f53998502f84b318f14b50df80` |
| `geometry/station.glb` | 283695712 | `6ae6789e3c4a5ccbd89a12bf11ead6ee4bb428f2a6de6df94234297fc5dd4b96` |
| `audit/repeat/assembly.snapshot.json` | 2656123 | `63f66cfd7b20c56edab72365eec890fba10558f53998502f84b318f14b50df80` |
| `audit/repeat/station.glb` | 283695792 | `ad38a9f80dcf481d8793cd5fb962604d2c8a6e5c912f51ad70d9d8f509c9c85a` |
| `audit/glb-semantic-diagnosis.json` | 1173 | `6a9f34150c1729a628238e556ae60decc24fa573d6106bbd9a1bf9f9a45b0b` |
| `audit/reproducibility-report.json` | 678 | `769c3a705ac6732c7bc278c1f57a60d444113e22f3e56c96d5450d5992aa045d` |

GLB 语义算法必须是
`solidworks-gltf-scene-geometry-payload/v2`，两份语义 SHA-256 都必须是
`226e6dc7cf274878d3bb54da2e4eaebc27fd605b9f739827d344ae05c1797b5c`。

## 4. Mac 准备仓库和 Python

下面假设仓库位于 `/Users/newtides/EIT`。如实际位置不同，
只修改 `REPO`，不要修改 Run ID 或 handoff 内容。

```bash
set -euo pipefail

REPO=/Users/newtides/EIT
CORE_COMMIT=38d729b2fc87f3a8d8af9845b55fea82bb7b08da

cd "$REPO"
git fetch origin main
git switch main
git pull --ff-only
git merge-base --is-ancestor "$CORE_COMMIT" HEAD
git submodule update --init --recursive

python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install \
  -e dependencies/unilab_robot_template/packages/unilab-robot-contracts \
  -e dependencies/unilab_robot_template/packages/unilab-arm-cr5
```

`git merge-base --is-ancestor` 非零退出时立即停止：当前 Mac 仓库不包含本轮 v2
语义门禁，不得用旧 verifier 验收。

## 5. 接收并核对 handoff

把 Windows 的完整目录复制为：

```text
<repo>/incoming/feeding-station-20260827-win02/
```

复制后、运行 verifier 前执行：

```bash
set -euo pipefail

REPO=/Users/newtides/EIT
RUN_ID=feeding-station-20260827-win02
HANDOFF="$REPO/incoming/$RUN_ID"

test -f "$HANDOFF/station-handoff.json"
test "$(find "$HANDOFF" -type f | wc -l | tr -d ' ')" = 666

test "$(shasum -a 256 "$HANDOFF/station-handoff.json" | awk '{print $1}')" = \
  0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9
test "$(shasum -a 256 "$HANDOFF/capture/files.sha256" | awk '{print $1}')" = \
  54e9158e5b42ec0a75c1db6e0b6771c5d0c9d11cdf7f16f4f7a4a574a16609db
test "$(shasum -a 256 "$HANDOFF/geometry/station.glb" | awk '{print $1}')" = \
  6ae6789e3c4a5ccbd89a12bf11ead6ee4bb428f2a6de6df94234297fc5dd4b96
test "$(shasum -a 256 "$HANDOFF/audit/repeat/station.glb" | awk '{print $1}')" = \
  ad38a9f80dcf481d8793cd5fb962604d2c8a6e5c912f51ad70d9d8f509c9c85a
test "$(shasum -a 256 "$HANDOFF/audit/glb-semantic-diagnosis.json" | awk '{print $1}')" = \
  6a9f34150c1729a628238e556ae60decc24fa573d6106bbd9a1bf9f9a45b0b
```

任一检查失败都先按“传输损坏”处理：删除 Mac 上的不完整副本，再从 Windows
不可变 win02 目录重新复制。不要在 Mac 或 Windows 上原地补写 win02 文件。

## 6. 运行 P1-M 独立验收

```bash
set -euo pipefail

cd "$REPO"
./.venv/bin/python scripts/verify_station_handoff.py \
  "$HANDOFF/station-handoff.json" \
  --output "$HANDOFF/mac-validation.json"

./.venv/bin/python - "$HANDOFF/mac-validation.json" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report["passed"] is True, report["errors"]
assert report["qualification"] == "source-input-validated"
repro = report["details"]["reproducibility"]
assert repro["normalized_snapshot_match"] is True
assert repro["exact_glb_match"] is False
assert repro["normalized_glb_semantic_match"] is True
assert repro["difference_class"] == "component_traversal_order_only"
assert {
    "collision",
    "spatial-interlock-enforced",
    "execution",
}.issubset(report["not_qualified_for"])
print("P1-M passed: source-input-validated")
PY
```

验证器会在 Mac 上重新完成以下工作，而不是信任 Windows 报告中的布尔值：

1. 校验 handoff 内所有相对路径没有越界；
2. 对 639 个 SourceRelease 文件逐个复算 SHA-256；
3. 复算两份规范化 snapshot；
4. 复算两份 GLB 的完整静态场景、层级、变换、accessor 和 bufferView 载荷签名；
5. 核对诊断算法、差异分类及两份 GLB 的绑定哈希；
6. 实例化 Dobot CR5 厂家 Provider 并核对 source digest、关节和 mesh。

## 7. 通过与失败判据

只有以下条件同时满足才可把 P1 标记为完成：

```text
passed=true
qualification=source-input-validated
errors=[]
normalized_snapshot_match=true
normalized_glb_semantic_match=true
difference_class=component_traversal_order_only
```

处理规则：

- 传输前置哈希不符：重新复制同一个不可变 win02，不修改它；
- 在前置哈希正确的情况下 verifier 失败：状态记为
  `needs-windows-recapture`，保留 win02 和失败报告，Windows 必须使用新 RunId；
- 不得手工把 `mac-validation.json`、诊断 JSON 或 reproducibility 报告改成通过；
- 不得因 GLB 能显示就授予碰撞、互锁或执行资格；
- `passed=true` 后才可复制 `config/station-decomposition.template.yaml` 开始 P2，
  且 P2 必须由人工批准。

## 8. Mac 回执

Mac 把以下信息回传给 Windows/CAD 负责人；`mac-validation.json` 留在 handoff
目录中，不提交 Git：

```text
Run ID: feeding-station-20260827-win02
Mac 仓库 HEAD:
核心实现提交: 38d729b2fc87f3a8d8af9845b55fea82bb7b08da
station-handoff.json SHA-256: 0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9
mac-validation.json SHA-256:
passed:
qualification:
Mac 型号 / macOS 版本 / Python 版本:
传输方式:
验收人和时间:
```
