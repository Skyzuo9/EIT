# 包内容

```text
README-FIRST.md                         从这里开始
HANDOFF-TO-OTHER-COMPUTER.md            给目标电脑 Agent 的任务书
WORKBENCH-TEST-PLAN.md                  用例、通过标准和故障定位
HANDOFF-MANIFEST.json                   全包文件大小与 SHA-256
requirements.txt                        Python 最小依赖
config/pipeline.template.yaml           可移植配置模板
pipeline/                               昨天的管线、SW/Blender Adapter 与校验器
scripts/                                预检、运行、验证、stage、回传脚本
workspace/inputs/                       5 类最小源输入
workspace/work/                         目标电脑的本地生成区
baseline/asset-pipeline-trial/          昨天的完整候选输出与报告
workbench-fixture-baseline/             从基线输出构建的静态 Workbench 夹具
templates/TEST-RESULTS.md               结果记录模板
docs/                                   架构设计、Windows 交接和安装背景材料
```

预计传输体积约 70 MB（压缩前，最终以 `HANDOFF-MANIFEST.json` 为准）。`workspace/work` 运行后会增加本机产物。

源输入的选择是有意的：一个 SolidWorks 小装配、一个 STEP 几何参考，以及静态/单轴/复合机构三类 legacy URDF。它们足以覆盖昨天已实现的路径，又避免传输整个硬件资产库。
