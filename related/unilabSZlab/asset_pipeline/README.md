# 实验室 3D 资产自动化流水线

从设备工作簿导入“准备中”记录，自动完成图片研究、候选图核对、Meshy
多图生成、GLB 尺度归一化和 PBR 质检。流水线在图片、生成预算和最终
模型三个节点等待人工批准。

## 快速开始

```bash
cp .env.example .env
# 在 .env 中填写 MESHY_API_KEY 和 GEMINI_API_KEY；
# BRAVE_SEARCH_API_KEY、CURSOR_API_KEY 可选。

uv sync
uv run asset-pipeline bootstrap
uv run asset-pipeline dashboard
```

团队空白工作包优先读取工作区根目录的
`待生成3D资产仪器清单.xlsx`。该表只有“仪器名称”必填，每行一台仪器；
官网、宽/深/高、尺寸来源和备注均为可选字段。若不存在该简表，流水线继续
读取原有的 `硬件规格清单_设备结构化.xlsx`，保持向后兼容。

图片检索会先从工作簿中的厂家官网提取产品图；配置 Brave 时优先使用
Brave Image Search，不可用或缺少结果时自动回退到无需 API Key 的 DDGS。
Gemini 根据实际像素评估精确型号、视角和 3D 重建适用度；单图走
Image-to-3D，多角度一致图片才走 Multi-Image-to-3D。

审批台默认由 Streamlit 打开本地浏览器。也可以完全通过 CLI 操作：

```bash
uv run asset-pipeline list
uv run asset-pipeline research --pilot
uv run asset-pipeline approve-research <device-id>
uv run asset-pipeline approve-generation <device-id>
uv run asset-pipeline generate <device-id>
uv run asset-pipeline approve-final <device-id>
uv run asset-pipeline export
```

`advance` 会执行所有无需人工确认的阶段，并在下一个审批闸门停止：

```bash
uv run asset-pipeline advance
```

## Codex 视觉质检

默认使用本机已登录的 Codex CLI 对批准参考图与前、右、后、左四张模型预览
进行只读视觉比较。Codex 输出由 JSON Schema 约束，审查请求、结果、运行摘要、
模型名称、证据路径和提示词版本记录在设备的 `output/visual-qc/` 目录及 QC
manifest 中。Codex 不可用、预览不完整或输出无效时默认关闭通过门禁，不会静默
退回为“已通过”。

```bash
uv run asset-pipeline visual-qc <device-id>
uv run asset-pipeline visual-qc-request <device-id>
uv run asset-pipeline record-visual-qc <device-id> /path/to/result.json
```

设置 `VISUAL_QC_PROVIDER=gemini` 可显式使用原 Gemini 审查器；仅在测试或明确
人工流程中才应设置 `VISUAL_QC_REQUIRED=false`。

## 输出

每台设备的所有材料位于 `assets/<device-id>/`：

- `candidates/`：候选参考图；
- `evidence/`：可下载的 PDF 规格证据；
- `research.json`、`agent-input.json`：可审计的研究包；
- `output/source.glb`：Meshy 原始输出；
- `output/final.glb`：尺寸校准后的内部模型；
- `manifest.json`：来源、审批、credits 和质检记录。

最终审批后运行 `export`，会在源工作簿旁生成
`硬件规格清单_设备结构化_资产结果.xlsx`。源工作簿不会被覆盖。
发布文件位于 `模型资产/`：GLB 为米制、PBR、Z-up，STL 为毫米制、
Z-up；两者均以占地中心为原点且底面 `Z=0`。

运行 `uv run asset-pipeline catalog` 会生成
`模型资产/asset-catalog.json`，记录文件哈希、来源、生成任务、credits、QC、
审批和许可证缺口。未确认的再分发许可证明确记录为 `not_recorded`。

## 安全与费用控制

- API 密钥仅从 `.env` 或环境变量读取，日志和工作簿不保存密钥。
- 未通过审批 2 不会提交 Meshy。
- 每个 Meshy-6 带贴图任务按 30 credits 预算；批次上限和单设备重试次数可配置。
- `task_id` 持久化到 SQLite，进程重启后继续轮询，不重复创建任务。
- Gemini 会比较生成后的四向预览和参考图；视觉不一致或比例误差超过
  15% 时禁止自动发布。
