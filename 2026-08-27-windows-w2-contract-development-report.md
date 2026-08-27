# Windows 父图加固与 W2 几何合同开发报告

日期：2026-08-27
主机：Windows
状态：`fixture-tested`；未生成真实 W2 handoff

## 结论

本轮依据《投料站：Mac → Windows 下一轮交接与 W2 开发手册》和工站资产管线
design/plan，完成了收到 P2 批准前允许开发的软件合同：

1. Windows SolidWorks adapter 会校验 `IComponent2::GetParent`，并仅在 COM 返回空时，
   从 `Name2` 的完整层级路径解析“仓库中确实存在的精确父 occurrence”；不使用显示名、
   前缀猜测或模糊搜索。
2. P1 finalizer 与 Mac verifier 会拒绝 `Name2` 明确包含层级、但 `parent` 被拍平成空的
   snapshot。
3. 新增 W2 原子封装器、export plan/entity map/handoff v1 schema 和四纵切合成测试。
4. Windows 写出的 `files.sha256` 固定为 UTF-8 + LF，消除 `\r\n` 导致的跨平台聚合
   摘要漂移。

这些结果不表示真实投料站已经取得 `source-input-validated`、P2 人签或
`ready-for-mac-w2-validation`，也不授予 collision、kinematics、interlock 或 execution
资格。

## win02 只读诊断

未修改目录 `feeding-station-20260827-win02`。只读检查其
`capture/assembly.snapshot.json`（SHA-256
`63f66cfd7b20c56edab72365eec890fba10558f53998502f84b318f14b50df80`）得到：

| 项目 | 数值 |
|---|---:|
| occurrence | 2021 |
| `parent` 非空 | 0 |
| `root_occurrences` | 2021 |
| `id` 含 `/` 层级 | 1996 |
| 能找到精确已存在 Name2 父路径 | 1996 |

因此 win02 的文件和哈希仍是不可变证据，但该父图无法支持 design/plan 要求的“按精确
`subtree_root` 展开全部后代”。更新后的门禁会把它判为 `needs-windows-recapture`；不得
原地修改 win02。修复后必须使用新 RunId、两次独立 SolidWorks 会话重新采集，并重新走
Mac P1 与 P2 人签。

使用更新后的 verifier 对 win02 做只读复算，结果为：

| 项目 | 结果 |
|---|---:|
| `passed` / `qualification` | `false` / `rejected` |
| 父图退化关系 | 3992（主/重复 snapshot 各 1996；verifier 汇总为 2 条错误） |
| 其他错误 | 1：`source_files_digest` 与 `files.sha256` 字节摘要不一致 |
| warnings | 2：两次 `open_warnings=2`，仍须人工解释 |
| 已逐文件复核的 SourceRelease 文件 | 639 |

第二类错误来自旧 Windows 文本写入路径的换行字节差异；本轮 finalizer 已把
`files.sha256` 固定为 UTF-8 + LF。它与父图错误都只能在新 RunId 中修复，不能回写
win02。

SOLIDWORKS 官方 API 说明与本次修复一致：`IComponent2::GetParent` 返回直接父组件，
顶层组件才返回空；`IComponent2::Name2` 对子装配成员返回带 `/` 的完整层级路径。

## W2 合同实现

入口：`scripts/finalize_station_geometry_handoff.py`

封装器在写任何正式目录前完成以下失败关闭检查：

- 以 W1 handoff + approved decomposition 重新运行 P2 编译，并逐对象比较
  `station-layout.json`、`coverage-report.json` 与人审 Markdown，拒绝手改产物；
- 要求 `human_reviewed=true`、`publication_eligible=true`、精确 coverage、无未分配或
  重叠 occurrence；
- W2 使用新 `*-w2` RunId，输出目录必须不存在；
- 第一纵切必须覆盖料架、导轨外壳、CR5 CAD 对照和 4 ml 瓶；
- 每个设备根必须精确等于批准 layout 的一个 placement；
- 每个主/重复 GLB node 都必须由 `entity-map.json` 映射到该批准子树内的精确
  occurrence；两次 entity 集合必须一致；
- 两次 GLB 使用 `solidworks-gltf-scene-geometry-payload/v2` 语义签名比较；
- 记录 bytes、nodes、meshes、primitives、vertices、triangles、材质和世界包围盒；
- 执行 25 MB、500 primitives、3,000,000 triangles 硬预算；
- 导轨和 4 ml 瓶必须提供已审包围盒预期；4 ml 瓶强制 `source_unit=mm`；
- 机器人强制 `comparison_only=true` 且运动学绑定
  `robot-family:dobot.cr5`；
- 主/重复采集的源摘要前后均必须等于 W1 `source_files_digest`；
- 全部验证通过后才原子生成 `geometry-handoff.json`、批准产物副本、设备目录与
  `files.sha256`。

相关 schema：

- `schemas/station-geometry-export-plan-v1.schema.json`
- `schemas/station-geometry-entity-map-v1.schema.json`
- `schemas/station-geometry-handoff-v1.schema.json`
- `config/station-geometry-export-plan.template.json`

## 当前验证

Windows 主仓测试 `23/23` 通过。测试覆盖正常四纵切封装，以及 draft P2、
手改批准产物、非精确根、跨子树 occurrence、重复导出语义漂移、4 ml 单位错误、预算
超限和 adapter 父图冲突等负向路径。

既有 CR5/FR5 预览回归在本机已完成 Python/OS 依赖装载，但 6 项测试都按设计停在只读
SourceRelease ZIP 缺失：本机不存在
`C:\Users\NewTi\Downloads\机械臂control\DOBOT_CR_CRA\ros\DOBOT_6Axis_ROS2_V4-37730d08.zip`
及对应 FR5 ZIP，工作区内也未找到副本。未伪造或重建厂家归档，因此该组回归记为
`environment-blocked`，不是通过，也没有出现本轮 W2 代码断言失败。

真实 W2 的下一允许顺序仍是：

```text
保留 win02
  → 新 RunId 用父图修复后的 adapter 重新 W1 采集
  → Mac 独立返回 source-input-validated
  → 真实 decomposition 人签并重编译通过
  → Windows 填写 export plan、执行两次设备级导出
  → W2 finalizer 生成 ready-for-mac-w2-validation 候选
```
