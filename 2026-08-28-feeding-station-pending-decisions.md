# 投料站待决策台账

日期：2026-08-28

对象：`feeding-station-20260827-win03`

台账状态：`open-for-review`

当前允许：Mac 上加载摘要锁定的 P1 GLB，显示 P2 自动分解草案及其覆盖凭据。

当前禁止：把草案批准为正式 P2、启动真实 W2、发布部署清单、执行碰撞/空间互锁结论或连接真实机器人。

## 决策与门禁

| ID | 状态 | 决策人 | 待确认事项 | 阻止事项 | 不受阻的安全工作 |
|---|---|---|---|---|---|
| CAD-001 | open | 机械/CAD 审核人 | 审核 53 条规则中的设备根、父装配壳减子设备边界及正式 family 名称 | P2 approval、真实 W2 | P1 整站静态显示、2021/2021 coverage 回归、API/前端测试 |
| CAD-002 | open | 机械/CAD + 机器人负责人 | 确认 GCR5 根、安装板、移动轴、夹爪/末端工具是否按当前 proposal 分离 | 正式机器人替换、基座/工具链部署 | 显示 SolidWorks 比较几何；独立 GCR5 URDF 受限运动学预览 |
| ROB-001 | open | 机器人负责人/厂家资料审核人 | 提供并批准 GCR5 厂家关节类型、限位、速度/力矩、零位、轴向和控制器 joint 映射 | 真机运动、MoveIt 规划资格、碰撞/互锁 | 当前 `project-cad-export` 静态或 mock 预览 |
| ROB-002 | open | 机器人 + 工艺负责人 | 确认机器人 base 安装变换、工具链、TCP、payload/CoM 和标定方法 | 点表、轨迹、抓取、真实 W2 | 整站视觉检查和坐标审计 |
| CAD-003 | open | 机械/CAD 审核人 | 确认 ETH17/移动轴关节范围、零位、正方向、安装关系和受控轴身份 | 移动轴运动与联合规划 | 静态外壳显示 |
| CAD-004 | open | 机械/CAD + 安全审核人 | 指定哪些几何是合格 collision，给出间隙、忽略对和安全裕量 | 碰撞检查、空间互锁、部署资格 | visual GLB、拾取和包围盒检查 |
| MAT-001 | open | 工艺/物料负责人 | 当前自然序首个 4 ml 有盖瓶是否只作代表几何；若要运行，需给出物理槽位、site 身份和装载政策 | 4 ml 运行时实例、库位占用与工艺执行 | 代表几何显示和分类审核 |
| GOV-001 | open | 项目/法务负责人 | `robot_dc` 根目录无 LICENSE；确认 URDF/STL 的再分发和部署使用边界 | 向本仓或发布包重新分发第三方 mesh | 记录 URL、commit、摘要并从原来源本地获取 |
| DATA-001 | open | 数据管理员 | P1 冻结 handoff 的历史机器人字段仍为 Dobot CR5；决定是否以新 Run ID 重采 P1 | 把旧 P1 字段当作当前机器人身份 | P2 以 occurrence/URDF 证据识别 `duco.gcr5_910`；旧证据保持不可变 |
| ENG-001 | monitor | 前端/资产管线负责人 | 283,695,812-byte 整站 GLB 的加载时延、显存和交互是否需要 LOD/分包 | 大模型生产性能门禁 | 本机完整 GLB 首次可见性验收；后续只在有测量证据时优化 |
| SW-001 | closed-explained | SolidWorks 操作人 | 两次 `open_warnings=2` 均为 `swFileLoadWarning_ReadOnly`，且 `open_errors=0` | 无新增阻止项；解释须保留 | 所有已授权静态预览与草案编译 |

## 允许继续的验收合同

Workbench 静态预览必须同时满足：

1. `station-handoff.json`、decomposition、layout、coverage 和 GLB 均通过 receipt 中的 SHA-256/bytes 校验；
2. P2 保持 `human_reviewed=false`、`publication_eligible=false`；
3. coverage 保持 2021/2021、0 unassigned、0 overlap、53 placements；
4. Material Graph 只暴露 `display=true`，并明确 `hardware_execution=false`、`collision_qualified=false`、`w2_eligible=false`；
5. Workbench 中显示的是完整 P1 GLB。P2 在本阶段只提供分类、GCR5 根和 4 ml 代表几何的草案凭据，不声称已把 GLB 拆成获批的可部署设备资产。

任何摘要、计数或资格字段不符合时，预览后端必须启动失败，不得回退到未验证文件。

## 关闭顺序

建议按 `CAD-001 → CAD-002/CAD-003 → ROB-001/ROB-002 → CAD-004 → MAT-001 → GOV-001/DATA-001` 审核。只有相关 open 项被签署、P2 重新编译为 `publication_eligible=true` 且覆盖仍精确，才能为真实 W2 创建新的 Run ID。
