# pTLC 仿真场景端到端验证报告

- 验证时间：2026-08-14（Asia/Shanghai）
- 场景：`ptlc_client_scene.usda`
- 机械臂：CR5，6 轴
- 审核轨迹：`P63 -> P76 -> P63`
- 运行边界：只有仿真；没有连接真实机械臂、PLC、夹爪或仪器
- 授权资源：服务器 `tyzuo@222.29.40.109` 的物理 GPU 1

## 结论

| Gate | 状态 | 直接证据 | 边界 |
|---|---|---|---|
| UniLab OS Registry | PASS | `unilab package inspect` 发现 1 个设备、2 个 typed Actions 和 1 个 workflow；归档 SHA-256 `a3320a0df8be65254138b352b8226c3d1ec0317b65631ddf2dccd1743c31858e` | 注册的是仿真远程适配器，不是真机驱动 |
| UniLab Workbench | PASS | Workbench 实际实例化 `ptlc_cr5_isaac_1`，调度 1 节点 `read_health`；log 记录 `success=True`，UI 显示“执行成功” | 本次执行是只读远程健康检查，返回 `Busy` |
| WebRTC 黑屏修复 | BLOCKED | 启动脚本语法通过，渲染与窗口统一为 1280×720，`allowDynamicResize=false`；在 GPU 被占时正确以退出码 3 拒绝启动 | 未能在本 pTLC 场景连接 Isaac Client，因此不能将“黑屏已消失”判为 PASS |
| MoveIt 2 / OMPL 规划 | PASS | ROS 2 Jazzy + MoveIt 2.12.4 + OMPL 1.7.0 真实加载 `ompl_interface/OMPLPlanner` / `RRTConnectkConfigDefault`；往返各 34 个轨迹点 | 使用精确的 vendored CR5 URDF；实验室外界碰撞由 Isaac PhysX 单独验证 |
| 碰撞安全 | PARTIAL | MoveIt 对 68 个轨迹点的自碰撞检查为 0；USD 结构中已有 15 个实验室 collider | 还没有 PhysX 时间步轨迹的机械臂—环境 contact report，不能宣称环境碰撞安全通过 |
| 刚体动力学 | BLOCKED | 静态盘点确认 1 个 articulation root、7 个 rigid bodies、6 个 revolute joints、36 个 drive attributes | 静态 USD 盘点不是动力学证据；等 GPU 空闲后才能执行 drive + `World.step()` |
| 夹爪与仪器交互 | BLOCKED | 已准备 contact-gated 两指夹持、刚体转运、重力释放、receiver 接触/稳定 Gate | 尚未执行；模型也只是代表性仿真 fixture，不是某个真实夹爪/仪器的标定实体 |

## 已通过证据

### 1. Registry / Workbench

- 安装的 UniLab OS runtime：`0.11.3`。
- 设备 FQID：`community.ptlc_unilab_sim.ptlc_isaac_cr5_sim`。
- typed Actions：`read_health`、`run_point_sequence`。
- `run_point_sequence` 只接受经审核的 `P63_P76_P63`，只允许物理 GPU 1，并且先读 GPU 健康门。
- 单元测试：`5 passed in 0.05s`。
- Workbench scheduler 实际调用记录：
  - workflow `8b2f0986-5bb2-4e02-80f9-8efa3f715fa0`
  - node `1c9f882d-c8a1-4597-b228-4a499e61e2d2`
  - action `ptlc_cr5_isaac_1/read_health`
  - 最终 `success=True`

可审计文件：

- `ptlc_unilab_sim/build/inspect/package.catalog.json`
- `ptlc_unilab_sim/build/inspect/package_info.json`
- `ptlc_unilab_sim/build/workbench_health_success.png`
- `ptlc_unilab_sim/.unilabos/logs/workbench/a1249c6f-6f52-4fa2-a491-be4a238f0796.log`

### 2. MoveIt 规划

| 轨迹段 | 轨迹点 | 时间参数化 | 终点最大误差 | 自碰撞点 |
|---|---:|---:|---:|---:|
| P63 -> P76 | 34 | 3.215631581 s | `4.440892098500626e-16 rad` | 0 |
| P76 -> P63 | 34 | 3.215631581 s | `2.220446049250313e-16 rad` | 0 |

报告 SHA-256：`01a36eeab28366fcfb9e47374c5baa5a7f458e2a5aa615b3284dd4998d88fcf1`。

可审计文件：

- `pTLC仿真资产/isaac_sim/output/moveit_validation_20260814/moveit_plan_report.json`
- `pTLC仿真资产/isaac_sim/output/moveit_validation_20260814/cr5_moveit.urdf`
- `pTLC仿真资产/isaac_sim/output/moveit_validation_20260814/cr5_moveit.srdf`

MoveIt 的官方 Python API 文档明确覆盖 `MoveItPy`、named states、planning scene 和 state collision checks：<https://moveit.picknik.ai/main/doc/examples/motion_planning_python_api/motion_planning_python_api_tutorial.html>。

### 3. 已有的近似点位可视化

已有 87 帧、960×540、12 fps、7.25 s 的 H.264 视频，覆盖 `P63 -> P76 -> P63`，并完成解码帧数验证。

- 视频：`pTLC仿真资产/isaac_sim/output/unilab_motion_v2/ptlc_unilab_P63_P76_P63.mp4`
- SHA-256：`e31336d81407e1b20cd7b16c3669aecb1db9f7690ee285a0de466ea2f13d6540`

重要边界：这段视频是几何关节动画，可以证明场景、CR5 和点位对应可视化，但不是 PhysX drive、碰撞安全或抓取成功证据。

## 阻塞证据与已准备的复验

2026-08-14 12:03:47 CST 的最终复查显示，GPU 1 上仍存在其他 Isaac 进程：

- PID `2498151`，`active_perception.franka_stream`，同时占用 WebRTC `49100/tcp` 和 `47998/udp`。
- PID `2608759`，用户 `spacexplore` 的 Isaac Python。

因此没有终止这些进程，也没有在共享 GPU 上叠加启动本项目的 Isaac。已同步的复验程序是：

- `start_client_stream.sh`：验证 1280×720 WebRTC 串流，并检查 log 中不再出现 `NVST_R_INVALID_STATE`。
- `validate_articulation_dynamics.py`：逐点跟踪 MoveIt 轨迹，通过 articulation controller + `World.step()` 记录关节位置/速度与 PhysX contact report。
- `validate_gripper_instrument_interaction.py`：要求先出现夹指—样品接触，才允许附着转运，然后重力释放并在 instrument receiver 中接触、稳定。

## 判定规则

- `PASS`：已在当前环境中直接执行，并产生可读取证据。
- `PARTIAL`：只有子 Gate 通过，不得代替整体 Gate。
- `BLOCKED`：复验程序已就绪，但共享 GPU/端口安全门禁止当次启动。
