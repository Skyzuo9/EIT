# Mac 工站 Handoff 加固与 Decomposition v1 实施报告

日期：2026-08-27  
主机：macOS 26.2（arm64）  
Python：3.13.12  
基线提交：`524405edf2d90e411ee563c2b9e529590ff43cce`  
状态：`fixture-tested`；真实 Windows W1 handoff 尚未回传

## 本轮结论

Mac 侧 P2 工具已经完成两个可独立验证的增量：

1. `verify_station_handoff.py` 不再只检查路径、hash 和 GLB magic，而会验证
   occurrence 父图、根集合、组件数、源清单聚合摘要、GLB v2 结构与几何统计、
   两次独立采集复现性，以及绝对路径审计边界。
2. `compile_station_decomposition.py` 已升级为
   `lab.station_decomposition/v1`：只接受精确 `subtree_root`，沿 snapshot 的
   `parent` 图展开子树，支持同 family 和机器人多实例，并同时生成 layout、
   occurrence coverage JSON 与人审 Markdown。

这些结果只由确定性合成 occurrence/GLB 夹具和既有 CR5/FR5 软件服务证明。
`incoming/` 中没有真实 W1 目录，因此没有形成真实投料站的
`source-input-validated`、人工批准 decomposition 或 W2 导出许可。

## 实现内容

### P1-M handoff 门禁

- 要求 handoff 显式引用主/重复 snapshot、capture report、GLB 和复现性报告；
- 校验每个 parent 存在、禁止自引用和环，并要求 `root_occurrences` 精确等于
  parent 为空的 occurrence 集合；
- 要求 capture `component_count` 与 snapshot occurrence 数量一致；
- 固定 `source_files_digest = sha256(utf8(files.sha256))`，并校验清单路径有序、
  唯一、使用规范 POSIX 相对路径且逐文件摘要一致；
- 解析 GLB 2.0 header/chunk/JSON，验证非空 node、mesh、primitive、accessor、
  POSITION accessor，并把文件统计与 capture report 比对；
- 校验两次规范化 snapshot、两次 GLB 字节摘要及复现性报告中的四个文件摘要；
- 非零 `open_errors` 失败；非零 `open_warnings` 必须有明确说明；
- Windows 绝对路径只允许留在 `source_document`/组件 `document` 等审计字段。

### P2 decomposition v1

- 删除 `occurrence_prefix` 模糊匹配入口；每条规则只接受一个精确
  `subtree_root`；
- 一个根生成一个 placement，同 family 可用多条规则形成多个实例；
- 嵌套根导致重复归属时失败，缺根、未分配和 handoff 摘要漂移也失败；
- 机械臂子树固定输出 `comparison_only`，运动学仍指向 `robot-family:*`；
- draft 只有 `--allow-draft` 才能生成，且写明
  `publication_eligible=false` / `decomposition-draft-preview`；
- 默认附带输出 `coverage-report.json` 和 `DECOMPOSITION-REVIEW.md`。

## 验证结果

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest discover -s tests -v
```

结果：`13 tests passed`。覆盖有效 handoff、父引用/父环/根集合、组件数、源摘要、
路径越界、无效 GLB、重复采集漂移、未解释 warning、精确子树、多料架/双 CR5、
重叠/未分配/无效根、旧 v0 前缀拒绝、draft 禁发布，以及 CLI 三份产物写出。

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest discover \
  -s cr5-telemetry-proof/tests -v
```

结果：`6 tests passed`。CR5/FR5 摘要锁定 Provider、Material Graph 投影、完整
关节帧、SourceRelease 不可变性、并发拒绝和错误摘要失败关闭均未回归。测试输出有
一条 Starlette/httpx 依赖弃用警告，不影响本轮断言。

以下检查也通过：

```bash
./.venv/bin/python -m py_compile \
  scripts/verify_station_handoff.py \
  scripts/compile_station_decomposition.py \
  scripts/finalize_station_handoff.py
git diff --check
```

本轮主要产物 SHA-256：

| 产物 | SHA-256 |
|---|---|
| `scripts/verify_station_handoff.py` | `590c9eb8d2d3722adcd8d1a9b38ef44c00c23b1b832afd85f2112f144551ad20` |
| `scripts/compile_station_decomposition.py` | `212374624c1afd69b19caa4af0585243a4c7318e2bf3e92d30aa453e3a789729` |
| `scripts/finalize_station_handoff.py` | `24eed21ff9e9b46acfd48c552f9ca92462823d86909818d4446450ce692795a1` |
| `config/station-decomposition.template.yaml` | `9315b092d425f44bdcf97a42d4766f637009e5ef95558f74c5334a0034a1d21a` |
| `config/station-handoff.template.json` | `6cee63c1af3a8697a403ef1a32fc46dec2907cfcf42170eafa79ad89d6c0d9f3` |

## 资格与停止边界

| 能力/阶段 | 当前状态 |
|---|---|
| P1/P2 代码与失败关闭夹具 | `fixture-tested` |
| CR5/FR5 既有 Mac 预览回归 | `software-tested`（单测） |
| 真实 Windows W1 handoff | 未收到 |
| 真实投料站 `source-input-validated` | 未验证 |
| 真实 occurrence decomposition | 未起草、未人签 |
| W2 设备级几何导出 | 未授权开始 |
| FamilySimBundle / DeployManifest / activation | 未开始本轮真实工站实现 |
| collision / interlock / execution | 明确不具备资格 |

下一步仍是把 Windows 生成的完整 RunId 目录原样放入 `incoming/`，运行 Mac 验证器；
通过后才能用真实 occurrence 起草四个纵切资产的 decomposition，并交机械/自动化
负责人批准。失败目录必须保留，修复后由 Windows 使用新 RunId 重采。
