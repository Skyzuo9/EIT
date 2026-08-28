# 投料站 UniLab Workbench Demo Workflow 验证报告

日期：2026-08-28

Run ID：`feeding-station-20260827-win03`

实现提交：`87b7ba727548c02dd6aae40d7ef7131883ac3642`

坐标修正提交：`2432a0497171908f462231945cbab513b54371ab`

状态：`demo-workflow-verified / moving-link-registration-passed / base-mesh-not-exact`

## 1. 可展示结果

正常 UniLab Workbench 主场景现在通过标准 Material Graph 同时显示四个对象：

1. 摘要锁定的完整 P1 投料站 GLB；
2. 独立的单轴导轨仿真层；
3. 青色 DUCO GCR5-910 URDF 运动学比较层；
4. 由 P2 occurrence 候选实例化的 4 ml 演示瓶。

启动命令：

```bash
./scripts/run_mac_kinematic_preview.sh
```

主场景：

```text
http://127.0.0.1:5173/?backend=local-python&backendUrl=http%3A%2F%2F127.0.0.1%3A8002&section=scene
```

场景和任务均明确标记 `DEMO / DRAFT / NO HARDWARE`。这次成功只证明资产加载、
可视投影和 Uni-Lab OS WorkflowTask/Job/Event 合同能连通，不是 P2 批准、W2、
MoveIt、碰撞、空间互锁或硬件执行结果。

## 2. 坐标合同与 GCR5 配准

公开合同统一为：

```text
SolidWorks CAD source: Z-up
SOLIDWORKSGLTF exported GLB: Y-up, metre, quaternion_xyzw
UniLab Material Graph: Z-up, millimetre, intrinsic XYZ degree
Pascal renderer: Y-up, metre, radian, internal only
```

`SOLIDWORKSGLTF` 已在导出时把 CAD 换成标准 glTF Y-up，因此整站 GLB 在 Pascal
中的模型旋转为零；重复施加 `-π/2 X` 会把整站侧立。GLB 点/姿态进入公开
Material Graph 时转换为 UniLab Z-up，再由 Pascal 的内部换轴还原。GCR5 不再直接
使用总装 occurrence 的四元数，而是使用 GLB component frame、同源 URDF/STL 和
frozen joint chain 反解得到的 comparison pose。

反解六轴弧度为：

```text
[-0.0188806598031334, 0.237927598042834, 1.68890767618547,
 -0.356038947433420, -1.57079632679490, -1.58967698659804]
```

数值重构证据：

| 指标 | 结果 |
|---|---:|
| 最大逐关节平移残差 | `9.7746855e-9 m` |
| 最大整链 FK 平移残差 | `8.8682480e-9 m` |
| 最大旋转矩阵 Frobenius 残差 | `1.7361477e-14` |
| J1–J6 网格尺寸差 | `< 0.1 mm` |
| J0 与 URDF base mesh 的一轴 AABB 差 | `约 44.708 mm` |

因此准确结论是“frozen-snapshot kinematic-frame registration passed”；J1–J6 的青色
运动连杆在 Workbench 中基本被灰色 CAD 连杆遮住，只在轮廓/三角面边缘可见。J0
来自不同基座几何/revision，不能称为全网格 perfect alignment，也不能把 comparison
root pose 当作已标定的部署 `base_pose`。

comparison pose 摘要：

```text
73af6e122c0e28cf526e0aefd9e54d5cf396a5b30643a311473542d79e89b411
```

## 3. Demo WorkflowTask

后端复用真实 `WorkflowStore`、`TaskSchedulerBridge`、`EdgeScheduler`、
`WorkflowService` 和公开 workflow API。唯一 dispatcher 是进程内可视状态模拟器，
不会打开 PLC、ROS、MoveIt、机器人 controller 或硬件 transport。

六步演示顺序：

```text
rail_move_pick
→ gcr5_pick_pose
→ vial_4ml_attach
→ gcr5_carry_pose
→ vial_4ml_detach
→ robot_rail_reset
```

启动 token 必须 exact 匹配 station GLB、P2 layout、GCR5 topology 和 comparison pose
四个摘要，并强制：

```text
mode=demo-simulation
hardware_execution=false
publication_eligible=false
```

本轮真实 API 运行回执：

| 项目 | 结果 |
|---|---|
| WorkflowTask UUID | `9bb60e6c-6b24-4901-b099-acf375c73f69` |
| Task | `succeeded` |
| Jobs | `6/6 succeeded` |
| Runtime events | `21` |
| Validation | `demo-workflow-validated` |
| 终态 | rail reset；瓶在 synthetic destination；GCR5 回 comparison pose |
| 终态遥测 | `stale=false`，六轴 exact comparison values |

`succeeded` 仅表示六个进程内 visualization actions 被 OS store/scheduler 正常处理。

## 4. 摘要锁定资产

| 输入 | SHA-256 |
|---|---|
| P1 handoff | `0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9` |
| P2 decomposition | `725ca56250ca6d0c2f19d7ac0392ff40d91dd81a7776305a67929933ff8ebb8c` |
| P2 layout draft | `f33c32ff39d0c63bc14f0911053c54aebb8aac8b5212953fb03852d9830eb76e` |
| P2 coverage | `c33913fc97ec9d9bf0a4e0890869a6dca95a14fc4bfd32de953ee77fc4ccc27e` |
| P1 station GLB | `f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746` |
| GCR5 archive | `c91cd096d8c6acde34bb57c85d4b7916c6ab17dc22feff09c502f29256230612` |
| GCR5 URDF | `76e95464d07ec304bf9394b640540a87193fa977420486c348e578e9cbd38858` |

GLB 为 283,695,812 bytes，包含 1543 nodes、1396 meshes、1588 primitives、
4764 accessors 和 45 materials。后端启动前会校验 bytes/SHA-256、GLB v2 结构、
2021/2021 唯一覆盖、53 placements、唯一 GCR5 根、唯一 4 ml 代表几何和 visual
registration 边界；任一项漂移即失败关闭。

## 5. 回归与可见检查

| 检查 | 结果 |
|---|---:|
| 根仓资产管线合同 | `26/26 passed` |
| SourceRelease + station + demo workflow | `11/11 passed` |
| services 定向前端合同 | `16/16 passed` |
| Pascal units/joint/aggregate 定向合同 | `26/26 passed` |
| Material Graph | `4` 个节点 |
| 浏览器主场景 | 完整加载，Edge connected |
| 浏览器 console errors | `0` |

完整 `@unilab/services` 套件另有一个位于用户脏 submodule 的既有
`workflow-node-template-cursor.test.ts` 失败；本次未改该 submodule，也不把定向
`42/42` 写成全前端套件通过。

## 6. 保留边界

- 导轨几何、范围和安装关系仍是演示值，不是批准 ETH17 参数；
- 4 ml source 只是一条 P2 代表 occurrence，attached/destination 是 synthetic；
- GCR5 comparison pose 是 CAD/URDF 视觉配准，不是厂家控制器零位或实机测量；
- `hardware_execution=false`、`publication_eligible=false`、
  `collision_qualified=false`、`spatial_interlock_enforced=false`；
- 真实 W2 仍须等待机械/CAD、机器人、物料和碰撞审核。

开放决策见
[`2026-08-28-feeding-station-pending-decisions.md`](./2026-08-28-feeding-station-pending-decisions.md)，
Windows 复现步骤见
[`2026-08-28-feeding-station-mac-to-windows-demo-workflow-handoff.md`](./2026-08-28-feeding-station-mac-to-windows-demo-workflow-handoff.md)。
