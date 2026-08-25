# pTLC 仿真资产包

本目录是 `pTLC实验室仿真重建基线_2026-08-13.md` 的可执行资产输入。它遵循“外壳允许近似，交互点保持原始控制值”的原则。

## 文件

- `asset_manifest.json`：型号识别、尺寸估计、置信度、交互点映射和 Meshy 路线。
- `source_api_points_snapshot.json`：固定的 `/api/points` 原始只读响应，SHA-256 为 `cf6f12…a2b11c`。
- `proxies/*/visual.glb`：米制、Z-up、底面 `Z=0` 的轻量视觉代理。
- `proxies/*/collision.stl`：毫米制、Z-up；封闭设备可为保守实心体，开放工站为多闭合子体碰撞代理。
- `interaction_points.json`：网页快照中的全部 239 个机器人点与 16 个 PLC 语义点；独立于近似网格。
- `rail_frame_layout_analysis.json`：由同一暂存 A 槽的取/回两套点拟合得到的地轨约束坐标、点族包围与 U 形组合塔拓扑；不是实验室测量世界外参。
- `photo_layout_evidence.json`：现场照片 2/3/4 的邻接、观察面与设备对应证据。
- `proxy_build_report.json`：代理资产的实测包围盒。
- `collision_qc_report.json`：15 个碰撞 STL 的水密性、实际尺寸、连通壳数量与开放空腔检查。
- `layout_estimate.json`：照片推断的场景布局，单位米、右手系、Z-up；不包含控制器点到世界的伪外参。
- `lab_scene_approx.glb`：15 个代理资产与官方 CR5 暂定骨架的整场粗略装配。
- `lab_scene_approx_top.png`：场景俯视布局预览。
- `lab_scene_build_report.json`：场景几何数量、边界、源资产尺度和未映射点位检查。
- `meshy_connectivity_audit.json`：脱敏后的 Meshy DNS/任务/积分状态；不含 API key。
- `scripts/generate_proxy_assets.py`：确定性重建脚本。
- `scripts/assemble_lab_scene.py`：确定性场景装配与俯视预览脚本。
- `scripts/analyze_rail_frame_layout.py`：可重复运行的地轨/点位联合拟合脚本。

## 重要边界

`asset_manifest.json` 中的定制设备尺寸是照片/点位联合估计，不是现场尺量。由于用户明确说明无法现场确认，清单用 `uncertainty_mm` 表示布局误差。机器人交互点不得从代理网格反推，也不得为了“贴合外壳”改写。原始 API 快照的 239 条机器人记录全部没有 `rail` 字段；`rail_frame_layout_analysis.json` 中的地轨关联是来自操作流程语义的 sidecar，不是对原点位的回填。

CR5A 不走 Meshy。本地 `cr5_moveit/config/cr5_robot.urdf.xacro` 会引用 `dobot_rviz/urdf/cr5_robot.urdf`；本目录已从 DOBOT 官方 ROS2 仓库固定提交补齐 `dobot_rviz/meshes/cr5/*.STL`。它是 **CR5 仿真骨架**，现场照片则确认是 CR5A，二者几何/DH 未核验前不能称为完全等同。尤其不能用 `CR5AF` 代替：CR5AF 属于带力控的 CRAF 系列，不是 CR5A。

当前机器没有 ROS2、Xacro、MoveIt 或 `check_urdf`，所以只完成 XML、引用闭包、网格哈希和包围盒检查，尚未运行 RViz/规划。官方 CR5 URDF 没有地轨 joint、`tool0/flange/TCP` 固定帧；需要在仿真工程里另加，且真实 TCP 继续保持未知。官方 URDF 还把高面数 visual STL 直接复用于 collision；实验室场景规划应优先换用简化碰撞几何。公开再分发前需注意官方仓库根 MIT 与包级 BSD/TODO 元数据不一致，详见 `dobot_rviz/PROVENANCE.md`。

本资产包的开放式工站/货架碰撞 STL 已采用多闭合子体，避免单一 AABB 封死取放空腔；`collision_qc_report.json` 当前为 15/15 水密、15/15 尺寸匹配、8/8 预期空腔保留。若目标引擎会把整份 STL 自动凸包化，导入时必须按 connected shells 拆成 compound collision，否则空腔仍会被重新封闭。

`rear_chemistry_workstation` 按用户指定不纳入本次重建；旧代理已从活动 `proxies/` 目录移入 `excluded/proxies/` 可恢复归档，且不再由确定性脚本生成。

整场 GLB 是点位约束+照片邻接的 **layout v2**，不是现场测绘模型。`layout_collision_qc.json` 的组件级 AABB 检查当前没有非预期交叠；仅保留 3 组有意的载架/工装嵌套。这只是简化代理的静态布局检查，不等于网格精确碰撞、机器人连续轨迹检测或真机安全认证。

Meshy 首轮候选为 `photo_scrape_station`，只用于 visual 外观试验；collision 继续使用简化包围盒，交互点继续读取 `interaction_points.json`。当前只完成候选分析，未提交付费任务：本地 skill 要求用户给出明确的“单设备积分上限”，建议首轮上限 30 credits，且本次 Meshy API 连通性检查超时。脱敏证据见 `meshy_connectivity_audit.json`。

注意：当前 pipeline 工作簿/SQLite 中只有早期导入的 `DOBOT CR5A`，其研究状态为 `failed`，没有 approval、task ID 或 artifact；这不影响已补齐的官方 URDF/STL。不要为 CR5A 继续创建 Meshy 任务。PhotoScrape 必须先作为独立的“定制复合单元外观代理”建立证据记录，再经过身份/尺寸/积分审批。

## 重建

```bash
asset_pipeline/.venv/bin/python pTLC仿真资产/scripts/generate_proxy_assets.py
asset_pipeline/.venv/bin/python pTLC仿真资产/scripts/export_interaction_points.py pTLC仿真资产/source_api_points_snapshot.json
asset_pipeline/.venv/bin/python pTLC仿真资产/scripts/analyze_rail_frame_layout.py
asset_pipeline/.venv/bin/python pTLC仿真资产/scripts/assemble_lab_scene.py
```
