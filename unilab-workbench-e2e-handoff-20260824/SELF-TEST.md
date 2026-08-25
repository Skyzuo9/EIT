# 交接包自测记录

日期：2026-08-24  
机器：原资产管线 Windows 生成机  
目的：验证交接包在脱离原目录绝对路径后仍能独立运行。

## 结果

- PowerShell 6 个脚本：语法解析通过。
- Python：3.13.5；PyYAML 6.0.2；cascadio 0.1.1。
- Blender：5.2.0 LTS。
- SOLIDWORKS COM：`SldWorks.Application.33` 注册并完成只读 capture。
- Python 单元测试：5 项通过（首次运行前，生成物门禁测试按设计 skip）。
- 端到端生成：退出码 0，耗时约 79 秒。
- 家族包：5 个；预览 PNG：5 张。
- family gate：通过，失败项 0。
- 严格交接验证：`passed: true`。
- SolidWorks capture：`passed`；装配组件 4，mate 候选 14。
- Workbench fixture smoke test：catalog 5 项，全部 bundle/GLB 相对 URL 可解析；motion/interlock/execution 均为 false。
- 基线 fixture stage smoke test：通过。

## 已知且预期的状态

总结果仍标为 `partial-pass`，因为 Slice A 缺厂家机械臂 URDF/Xacro；这不是脚本错误。SolidWorks 两次导出的 GLB 字节不同，但规范化语义和装配 snapshot 一致，差异类为 `component_traversal_order_only`，因此仍阻塞正式不可变发布。静态 Workbench 显示/拾取候选不因此失败。

自测生成的 `workspace/work/asset-pipeline-trial` 和 smoke staging 目录在打包前已清除，只保留轻量记录和 `baseline/asset-pipeline-trial`。这样目标电脑会从空的本地 work 区重新生成，避免把原机器绝对路径误当成新结果。
