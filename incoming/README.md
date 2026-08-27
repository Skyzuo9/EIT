# Windows 工站结果回传区

投料站 P0–P1 的 Windows 命令、交接字段和 Mac 验收状态词见
[`../2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md`](../2026-08-27-feeding-station-windows-mac-p0-p1-runbook.md)。

把 Windows/SolidWorks 生成机导出的**完整工站结果目录**放在这里，例如：

```text
incoming/
  station-a-20260826/
    station-handoff.json
    capture/
    source-release/
    geometry/
```

目录默认被 Git 忽略，因为其中可能包含受许可约束的 SolidWorks、GLB、STEP、
STL 和厂家文件。不要只复制截图或单一整机 GLB；至少需要
`assembly.snapshot.json`、`capture-report.json`、`source.json`、
`files.sha256`、可读取的 GLB，以及厂家机械臂 Provider 或 URDF/Xacro 真源。

复制完成后运行：

```bash
./.venv/bin/python scripts/verify_station_handoff.py \
  incoming/station-a-20260826/station-handoff.json
```

通过该检查只表示“Mac 后半段具备可消费输入”，不表示已经完成人签工站分解、
部署标定、空间互锁或执行资格。

校验通过后，复制 `config/station-decomposition.template.yaml`，按 SolidWorks
occurrence 身份完成人审归属，并运行：

```bash
./.venv/bin/python scripts/compile_station_decomposition.py \
  incoming/station-a-20260826/station-handoff.json \
  incoming/station-a-20260826/station-decomposition.yaml \
  --output incoming/station-a-20260826/station-layout.json
```

编译器要求所有 occurrence 恰好归属一个设备或机械臂替换子树；未分配、重复
归属、摘要漂移和锚点歧义都会失败关闭。输出仍只是部署位姿候选。
