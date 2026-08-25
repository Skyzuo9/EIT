# photo_scrape_station Meshy 输入证据包

本包从 `现场照片/现场照片4.jpg` 做确定性裁剪，源图 SHA-256 为
`1146ec111f9c8e36b37a53b4ba2df7c0785d5a9c6e57842a644c6874fe6abf05`。
原图坐标约定是左上为原点，裁剪区为 `[300, 200, 1750, 2300)`，输出
1450 × 2100 px。

- `photo4_crop_x300-1750_y200-2300.png`：无损审计裁剪，保留全部原始像素。
- `photo4_crop_x300-1750_y200-2300_q98.jpg`：高质量 JPEG 兼容版。
- `photo4_subject_manual_transparent.png`：建议的 Meshy 试验输入；仅用手工多边形 alpha 蒙版去背景，没有补画或生成像素。
- `photo4_subject_manual_mask.png`：上述 alpha 蒙版。
- `evidence_audit.json`：坐标、hash、包含/排除对象、用途和风险。
- `prepare_evidence.py`：可重复执行的非生成式制作脚本。

范围只是布局级的定制拍照/刮板工站候选代理。由于只有一个斜视角、设备边界模糊、遮挡严重且无标定尺度，单视图风险为高；不可用于制造、精密碰撞或隐藏面几何的真值声明。

只读管线检查（2026-08-13）：`DOBOT CR5A` 记录状态为 `failed/needs_generation`，Meshy key 在本地已配置（未读取或输出值），SQLite 中有 0 条 Meshy 任务、0 条审批；本任务没有提交 API 请求，没有消耗 credits。
