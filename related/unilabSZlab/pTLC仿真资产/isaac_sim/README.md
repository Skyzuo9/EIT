# pTLC Isaac Sim 离线复现

本目录把现有 pTLC 近似实验室、CR5 关节模型和控制器点位转换为可审计的
Isaac Sim 6.0.1 场景与最小关节回放。它从不连接 ROS、PLC、真实机械臂、相机或
其他硬件接口。

## 证据边界

- 仪器外壳是照片/点位约束下的布局代理，不是现场测绘 CAD。
- `dobot_rviz` 中的 CR5 是现场 CR5A 的暂定运动学骨架，几何和动力学未等同验证。
- 原始 `pose=[x,y,z,rx,ry,rz]` 永久保留，但在 DOBOT 欧拉角顺序和 Tool 1 TCP
  未确认前不用于 IK。
- 首条轨迹使用同一工位、同一 User 0/Tool 1 的原始关节记录
  `P63 -> P76 -> P63` 做平滑关节空间插值。它不是 MoveL 复现。
- 碰撞结果只适用于当前近似代理、当前 CR5 骨架和当前插值，不是真机安全认证。

## 本地输入门禁

```bash
source /Users/newtides/unilabSZlab/asset_pipeline/.venv/bin/activate
python pTLC仿真资产/isaac_sim/validate_replay_inputs.py \
  --workspace /Users/newtides/unilabSZlab \
  --output /tmp/ptlc_input_validation.json
```

门禁核对 239 个机器人点、74 个原始关节记录、165 个派生点、4 个禁止规划的
占位点、16 个 PLC 语义点、15 个场景代理、碰撞 QC、输入哈希和回放关节限位。

## 远端批处理

`ptlc_isaac_replay.py` 必须在 Isaac Sim Python 3.12 环境中执行。为避免 Isaac
为 GPU 0 创建次要 CUDA 上下文，令 `CUDA_VISIBLE_DEVICES=1`；Vulkan 仍使用
物理编号 `activeGpu=1`，CUDA/PhysX 则使用可见设备中的逻辑编号 0。脚本会核对
本进程的 `nvidia-smi` UUID，拒绝落到未授权 GPU。

```bash
CUDA_VISIBLE_DEVICES=1 OMNI_KIT_ACCEPT_EULA=YES \
/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1/bin/python \
  pTLC仿真资产/isaac_sim/ptlc_isaac_replay.py \
  --workspace "$PWD" \
  --output "$PWD/isaac_output" \
  --gpu-index 1
```

运行输出包括输入门禁报告、派生 URDF、CR5 USD、整场 USD、关节回放报告、
关键帧图像和 Isaac 日志。脚本会拒绝未显式接受 EULA、非 GPU 1 运行、占位点、
缺失资产和关节越限。

## Isaac Sim Client 可视化

先用 USD Python 生成包含时间轴的 Client 场景。时间轴是
`P63 -> P76 -> P63` 的平滑关节目标插值。P76 有明确的轨道槽 2 空间绑定，会显示
加大的端点标记；P63 没有显式空间绑定，只参与关节回放，不虚构其世界坐标或 TCP 线。

```bash
/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1/bin/python \
  pTLC仿真资产/isaac_sim/make_client_scene.py \
  --input-scene "$PWD/isaac_output/ptlc_scene.usda" \
  --input-validation "$PWD/isaac_output/input_validation.json" \
  --output-scene "$PWD/isaac_output/ptlc_client_scene.usda"
```

确认 GPU 1 空闲后启动独立 Streaming 会话：

```bash
OMNI_KIT_ACCEPT_EULA=YES \
  pTLC仿真资产/isaac_sim/start_client_stream.sh
```

在 Isaac Sim WebRTC Streaming Client 中填写：

- Server：`222.29.40.109`
- Signaling port：`49100/TCP`（原生 Client 默认端口）
- Media/stream port：`47998/UDP`（原生 Client 默认端口）

连接后按时间轴 Play；打开 Loop 可连续观察 P63/P76 往返。启动器会在 GPU 1
已被任何其他进程占用，或 49100/47998 已绑定时拒绝启动；它不会终止别人的进程。

## 离线运动视频

当 WebRTC 不可用时，可用 `capture_motion_frames.py` 在 GPU 1 离线渲染
`P63 -> P76 -> P63` 的清晰 PNG 序列。脚本对记录关节角做 smoothstep 关节空间
插值，并直接更新导入 CR5 的几何层级；它关闭运动模糊、使用 FXAA，并在每次写盘
前等待渲染稳定。这个结果不是物理控制轨迹、MoveL、碰撞通过或真机验证。

```bash
CUDA_VISIBLE_DEVICES=1 OMNI_KIT_ACCEPT_EULA=YES \
/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1/bin/python \
  pTLC仿真资产/isaac_sim/capture_motion_frames.py \
  --scene isaac_output/ptlc_client_scene.usda \
  --input-validation isaac_output/input_validation.json \
  --output isaac_output/motion_final \
  --fps 12 --hold-seconds 0.75 --move-seconds 2.5 \
  --width 960 --height 540 --rt-subframes 1 --settle-updates 8
```

## Uni-Lab Robotics 控制链验证

`run_unilab_isaac_validation.py` 复用
`/Users/newtides/unilab_robot/unilab_robot_template` 中的 CR5 型号、v2 PointSet
解析器、`RuntimeBinding`/维护会话、`MoveTargetCommand` 和
`MoveItCommissioningAdapter`，再把唯一的运动传输端口替换为 Isaac 几何渲染端口。
它按 `ptlc.P63 -> ptlc.P76 -> ptlc.P63` 派发三条低速、具名、版本化命令；每条
命令只有在对应帧全部写盘后才返回 `completed=true`。

这条路径属于模板定义的 maintenance/simulation 表面，不把任意点位运动注册为
生产 `pick/place`。当前本机 `asset_pipeline/.venv` 没有安装 `unilabos`，因此本节
验证的是 Uni-Lab Robotics 运行时合同，不是 UniLab OS Registry/Workbench 注册。

```bash
CUDA_VISIBLE_DEVICES=1 OMNI_KIT_ACCEPT_EULA=YES \
/home/tyzuo/.conda/envs/active-perception-isaac-6.0.1/bin/python \
  pTLC仿真资产/isaac_sim/run_unilab_isaac_validation.py \
  --scene isaac_output/ptlc_client_scene.usda \
  --point-set pTLC仿真资产/isaac_sim/config/cr5_ptlc_points.v2.json \
  --template-root unilab_robot_template \
  --template-revision e8964842c4da3d123323cc46cfa565678c909849 \
  --output isaac_output/unilab_motion \
  --fps 12 --hold-seconds 0.75 --move-seconds 2.5 \
  --width 960 --height 540 --rt-subframes 1 --settle-updates 8
```

输出 `unilab_isaac_validation.json` 包含模板版本、输入 SHA-256、三条命令的规范
payload/指纹、完成回执、每帧所属命令以及最终 P63 状态。它仍然只是几何驱动的
Isaac 验证，不覆盖 MoveIt 规划、刚体动力学、碰撞通过、夹爪/仪器交互或真机安全。
