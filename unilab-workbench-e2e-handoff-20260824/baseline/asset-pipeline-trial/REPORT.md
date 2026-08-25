# 资产管线初步测试报告

日期：2026-08-24  
状态：候选试验；不得用于执行或强制空间互锁

## 结论

当前文件夹已完成可重复的资产盘点、SolidWorks 装配摄取、STEP 几何回退、三类 legacy SolidWorks URDF 迁移夹具编译、GLB 输出和家族层硬门禁。厂家机械臂 URDF/Xacro 与控制器导出缺失，因此没有伪造 Robot FamilySimBundle、PointSet 或 ProgramSet。SolidWorks 2025 已只读提取真实组件快照并导出非空 XR GLB；打开警告 34 被解释为只读与需要重建，已保留在 provenance，未因此提升运动或碰撞资格。

## 本机环境

- Python：`C:\ProgramData\anaconda3\python.exe`，`3.13.5`
- Blender：`Blender 5.2.0 LTS`
- SolidWorks COM：版本探测 `33.5.0`；文档打开状态 `passed`
- 配置与交接说明不一致项：Python 与 SolidWorks 安装路径已在本地 `pipeline.yaml` 中显式覆盖；原 pTLC 仓库不存在，本试验输出改在当前工作区。

## 输入盘点

- URDF `82` 份，全部可解析 `82` 份；SolidWorks Exporter 输出 `82` 份。
- URDF 候选活动机构 `27` 份、候选关节 `74` 个、缺失 mesh 引用 `0` 个。
- Visual 与 collision 指向同一 mesh 的 link `156` 个，均未获得碰撞资格。
- `.SLDASM` `5`、`.SLDPRT` `32`、`.STEP/.STP` `4`、`.STL` `180`。

## Slice A — 机械臂家族

状态：**阻塞且未伪造**。当前无厂家 Xacro；82 份 URDF 均是 SolidWorks 导出，不满足机器人运动学真源要求。五轴机械臂 CAD/STEP 只进入输入盘点与几何审计，不生成正式机器人 mechanics。

## Slice B — 装配与视觉资产

- SolidWorks 小装配源发布：`captures/solidworks/square-tactile/`；状态 `passed`。文件哈希已冻结，COM 失败原文保存在 capture report 与 console log。
- STEP 回退：1 个代表资产通过，生成 `assembly.snapshot.json` 与 `render-lod0.glb`；资格不高于 `semantic-scene`。
- Legacy 迁移夹具：3 个代表资产通过，包括静态托盘、单轴导轨和复合拧盖夹爪。正式 `joints` 均为空，保留 legacy 关节候选 `6` 个；SolidWorks mate 候选 `14` 个；合计 `unproven` `20` 个。

## Slice C — 控制器点表

状态：**接口完成、数据未发布**。当前 CSV 是 SolidWorks URDF Exporter 元数据，不是控制器导出。已生成 Adapter 合同、原始快照夹具 schema 和遥测 schema；未生成 PointSet、ProgramSet，也未把当前关节伪装成目标点。

## 门禁

- 家族 JSON/GLB 检查数：`51`
- 家族 JSON：`46`；GLB：`5`
- 禁止字段、点表文本、嵌入动画/skin、25 MB 预算与 artifact 哈希：**通过**
- 失败项：`0`

## 视觉 QA

- Blender 5.2 以固定视角重载并渲染 `5` 个 GLB；每个预览都同时检查退出码、traceback 文本、PNG 与结构化报告。
- 预览总三角形数：`419174`；所有资产均有非零 mesh 和合理有限包围盒。
- 标准图位于 `previews/`，用于发现空几何、异常尺度、错位和离群部件；本轮人工目视未见明显缺失或离群。

## 可复现性

- SolidWorks 同一源装配隔离重导：`warning`。
- GLB 字节完全一致：`False`；规范化 GLB JSON 一致：`False`；装配 snapshot 一致：`True`。
- 按组件名、变换、accessor 元数据及二进制 payload 哈希归一后，GLB 语义一致：`True`；排序后的装配 snapshot 一致：`True`；差异分类：`component_traversal_order_only`。
- 正式发布许可：`False`。若字节不一致，当前候选仍可用于视觉测试，但必须先定位 XR/Draco 非确定性来源，不能宣称可复现正式发布。

## 需要人工确认的 unproven 项

- legacy URDF 中所有候选关节的方向、父空间轴向、行程、速度、驱动方式和失电状态。
- STEP/GLB 的工程 Z-up 到 glTF 根坐标变换与稳定实例身份。
- visual mesh 是否可以派生独立保守碰撞体；当前不得用于空间互锁。
- 方形视触觉 Pack and Go 的配置、显示状态、引用完整性，以及 SolidWorks COM/RPC 失败原因。
- 真实 RobotController 点表、程序修订、标定和工具上下文。

## 未做项

- 未发布机器人 FamilySimBundle：缺厂家 URDF/Xacro。
- SolidWorks 原生 snapshot/XR GLB 已发布为试验候选；mate 仍全部待人工确认。
- 未发布 collision GLB、PointSet、ProgramSet、DeployManifest 或 activation：证据不足。
- 未修改 Workbench、生产模型或任何原始 CAD/URDF/STL。
