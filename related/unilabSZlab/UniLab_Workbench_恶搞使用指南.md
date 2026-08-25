# 《别让机械臂先发现你不会用》

## UniLab Workbench 恶搞但保命的使用指南

> 适用对象：第一次打开 UniLab Workbench，看到一排按钮后产生“都点一遍不就会了吗”这种危险思想的人。
>
> 本文可以恶搞，机械臂不可以。涉及真实设备时，请把幽默感留在文档里，把手留在安全区外。

---

## 0. 先认识这位选手

UniLab Workbench 不是一个“大号启动按钮”，而是一个把以下角色关在同一间办公室里的 UniLab OS 开发与调试工作台：

- Theia IDE：写代码、看文件、搜全局、用 Git、跑测试和开终端。
- UniLab Runtime：提供当前工作区运行 UniLab OS 所需的 Python 环境。
- UniLab OS：加载设备图、设备、Action、Resource、Site 和 Workflow。
- PLC-Sim：让 PLC 协议和变量表先在虚拟世界里挨打。
- UniLab Agent：在当前项目里读代码、改代码、调用项目级 Skill。
- 仪器、物料和工作流视图：让人类不用盯着 JSON 修仙。

当前已检查的安装版本：

| 项目 | 当前值 |
|---|---|
| Workbench | `0.1.0` |
| 内置 Runtime | `0.11.3` |
| Theia | `1.74.1` |
| 支持平台 | macOS ARM64，macOS 13 或更高 |
| 默认部署方式 | Managed Local，本机托管 |

一句话总结：

> 它既是实验室软件的驾驶舱，也是事故调查委员会的会议室。

---

## 1. 开机前的灵魂三问

点击任何“启动”或“运行”之前，先回答：

1. 我打开的是一个真正的 UniLab 领域仓库，还是一个装了照片和愿望的普通文件夹？
2. 我现在是 `Dry-run`、`PLC-Sim`，还是可能碰到真实硬件的“正常运行”？
3. 如果设备真的动了，现场急停在哪里，谁在看着它？

如果第三题的答案是“应该在某个角落”，请停止答题并离开运行按钮。

### 合格工作区大致长这样

```text
<workspace>/
├── pyproject.toml
├── package.yaml
├── deployment/
│   └── graphs/
│       └── <device-graph>.json
├── <python_package>/
│   ├── devices/
│   ├── resources/
│   ├── workflows/
│   ├── config/
│   └── assets/
├── tests/
└── .agents/
    └── skills/
```

文件夹名字叫 `sZLAB` 并不会自动赋予它实验室操作系统之力，就像把空纸箱写成“反应釜”也不会让它开始控温。

---

## 2. 当前 `unilabSZlab` 的实际状态

本次只读检查中，Workbench 可以正常打开，内置 Runtime 和 Agent 均已就绪。但工作区根目录当前还没有发现完整领域包所需的：

- 根级 `pyproject.toml`；
- `package.yaml`；
- 实际存在的 `deployment/graphs/szlab-local-debug.json`；
- 完整的设备、资源和 Workflow Python 包。

因此当前状态应该理解为：

> 驾驶舱通电了，副驾驶 Agent 也来上班了，但飞机还没有装发动机清单和航线文件。

建议打开的工作区是：

```text
/Users/newtides/unilabSZlab
```

最近使用列表中的子目录：

```text
/Users/newtides/unilabSZlab/sZLAB
```

目前主要是 Workbench 生成的状态目录和 Skill 副本，不应把“能打开”误认为“领域仓库已经建好”。

---

## 3. 欢迎页：请选择你的副本

欢迎页有两个主要按钮：

### 打开工作区

用于选择已有项目目录。

正确用法：选择包含代码、配置、设备图和 `package.yaml` 的仓库根目录。

错误用法：选择 Downloads、桌面、整个用户目录，或者“这里东西最多，应该最完整”的任意文件夹。

### 新建工作区

创建一个新目录并打开。

它做的是“创建目录”，不是“凭空生成完整实验室”。新工作区仍需要领域包结构、设备定义、资源、Workflow、设备图和测试。

### 最近使用

这里记录的是“你开过什么”，不是“什么已经通过验收”。

---

## 4. 主界面的门派分布

### 4.1 仪器设备：单动作试胆大会

用途：

- 查看 Edge 是否连接；
- 查看设备在线或离线；
- 查看设备 ID、命名空间和所属机器；
- 浏览设备公开的 Action；
- 根据 Action Schema 填写类型化参数；
- 运行或取消单个 Action；
- 查看动作是否被占用；
- 在满足现场安全条件后进行受控解锁。

推荐第一次只选非运动、只读或低风险 Action，例如状态读取。

不要第一次就选择：

```text
move_everything_to_somewhere_final_v7
```

特别提醒：强制解锁不是“按钮灰了的修复方法”。只有在现场确认设备已停止、无人操作、相关 Workflow 不会继续发动作时，才能处理锁状态。

### 4.2 物料：瓶瓶罐罐的族谱管理

用途：

- 查看物料列表和层级关系；
- 查看 Warehouse、挂载位置和 Site；
- 查看库位是否占用；
- 在实验室视图中显示物料位置；
- 切换分屏和场景图层；
- 显示或隐藏库位、点位和转运路径；
- 从资源模板创建物料（前提是当前服务支持）；
- 观察 Workflow 派生出的只读转运路线。

Workbench 展示的是 OS/Inventory 的物料身份和位置投影。屏幕上一只瓶子“看起来在这里”，不等于现实中的瓶子没有被同事拿去洗了。

对物料身份的正确理解：

- Template UUID：它是什么类型；
- Material UUID：它具体是哪一个实物；
- Site：它应该在哪个稳定位置；
- 历史日志里的 UUID：它曾经是谁，不保证现在仍然有效。

### 4.3 工作流：画布不是连连看

用途：

- 查看已发布 Workflow；
- 在代码模式和画布模式之间切换；
- 编辑 Action 节点和参数；
- 配置 Workflow 根输入和 `ResourceSlot`；
- 保存 Workflow；
- 正常运行、单步运行或单节点调试；
- 在节点前设置断点；
- 暂停、继续、单步和停止；
- 从指定节点开始调试；
- 查看节点运行状态；
- 查看 Electron 与 UniLab OS 上报的 Trace 和 Span。

Workflow Python 是人类维护的源代码，画布是它的投影。拖动节点可以改善布局，但不能靠拖得更漂亮来修复数据依赖。

正确语义应能通过：

```text
Python → AST → Graph → Python → Graph
```

语义固定点检查。保存成功只表示文件写出去了，不表示宇宙认可了你的 DAG。

### 4.4 Agent：会说话的项目同事

Agent 可以：

- 阅读当前工作区；
- 修改和生成项目文件；
- 使用项目中的 `.agents/skills`；
- 调查错误、运行测试和解释代码；
- 帮助建设设备、资源、Workflow 和领域包。

推荐提示词：

```text
使用 $unilab-domain-repo-builder，检查当前目录距离一个可运行的
UniLab OS domain package 还缺什么。先只读检查，不启动 OS、PLC-Sim
或真实设备，并按 Package、Registry、Catalog、Authoring、Simulation、
Workbench、Hardware 七个 Gate 报告。
```

不推荐提示词：

```text
都帮我弄好，能动就行。
```

因为“都”和“能动”是实验室事故报告里最有潜力的两个词。

### 4.5 IDE：它真的也是个 IDE

内置视图包括：

- 资源管理器；
- 全局搜索；
- Git 源代码管理；
- 调试器；
- 扩展管理；
- 测试资源管理器；
- 终端、问题和日志面板。

你可以像使用 VS Code/Theia 一样编辑 Python，但领域契约仍应由 UniLab 的 Registry、Catalog 和 Workflow 校验负责，不能只依赖“编辑器没出现红线”。

---

## 5. 环境管理：按钮最多，也最值得慢一点

### UniLab Runtime

当前安装显示内置 Runtime `0.11.3` 为 `READY`。Workbench 会优先使用这个应用私有环境。

需要确认的不是“电脑上某处装过 unilabos”，而是 Workbench 实际运行的 Python：

```bash
python -c 'import sys, unilabos; print(sys.executable); print(unilabos.__file__)'
python -m pip show unilabos
```

兄弟目录里的另一个虚拟环境不能通过亲属关系自动获得运行资格。

### OS

OS 面板可以：

- 指定设备图路径；
- 保存设备图设置；
- 在正常运行和 Dry-run 之间切换；
- 启动或停止 UniLab OS；
- 查看 PID、API、Python 和启动状态。

当前界面填写的是：

```text
deployment/graphs/szlab-local-debug.json
```

但本次检查未找到这个文件。在文件真正存在并通过校验前，不要对着输入框进行信仰启动。

### PLC-Sim

PLC-Sim 面板可以：

- 选择 PLC-Sim 项目目录；
- 选择或填写 CSV 变量表；
- 刷新当前项目推荐的 CSV；
- 选择握手器，当前界面提供 `SZLab`；
- 启动或停止模拟器；
- 访问模拟 GUI 和 OPC UA 服务。

当前默认端点：

```text
GUI:    http://127.0.0.1:18765
OPC UA: opc.tcp://127.0.0.1:4855
```

### Agent

可以查看工作目录、数据目录和 PID，并重启或停止工作区 Agent。

Agent `READY` 表示它能上班，不表示领域包已经建好，更不表示机械臂已经同意你的 Workflow。

### 远程访问

默认关闭，此时 Theia 和 OS 仅接受本机连接。开启远程访问会扩大访问范围，应确认网络、有效期和共享对象。

“给同事看一下”与“把控制面暴露给整个网络”之间，只差一个没有认真读的按钮。

### 日志尾部

可按来源查看：

- OS 日志；
- PLC-Sim 日志；
- Agent 日志。

遇到故障时先选择正确来源再刷新。对着 Agent 日志寻找 OPC UA 握手失败，效果类似在咖啡机说明书里查机械臂奇异点。

---

## 6. 三种模式，三种完全不同的“成功”

| 模式 | 它证明什么 | 它不证明什么 |
|---|---|---|
| Dry-run | OS、任务和界面基本链路可走通；Action 可模拟返回 | PLC 协议正确、真实设备会执行、现场安全 |
| PLC-Sim | 变量表、握手、协议和部分时序可在模拟器工作 | 真实 PLC 接线、驱动、机械动作和工艺效果 |
| 正常运行 | OS 可能向配置的真实设备发送动作 | 设备一定安全、工艺一定正确、无人站在工作区 |

记忆口诀：

> Dry-run 是彩排，PLC-Sim 是替身，正常运行才可能让演员本人从舞台上冲下来。

---

## 7. 第一次正确启动：七步保住周末

### 第一步：先完成 Package Gate

确认可编辑安装、导入和包数据正常：

```bash
python -m pip install -e '.[dev]'
pytest -q
```

### 第二步：完成 Registry Gate

```bash
unilab --check_mode --devices ./<import_package> --external_devices_only
```

检查设备、Action、Resource Schema 是否与代码签名一致。

### 第三步：完成 Catalog Gate

确认：

- `package.yaml` 中的 Workflow UUID 与装饰器一致；
- 节点 UUID 稳定；
- 组合 Workflow 的子依赖先于父项发现；
- 干净状态扫描能够达到确定的固定点。

### 第四步：完成 Authoring Gate

验证 Python、AST 和 Graph 往返语义一致。不要用 magic comment、空 `pass` 并行块或假 Fork/Join 节点蒙混过关。

### 第五步：Workbench 选择 Dry-run

打开“环境管理”，切换到 `Dry-run`，核对设备图路径，然后启动 OS。

界面若提示类似：

```text
动作不会发送给设备
```

这才是第一次调试时最动听的一句话。

### 第六步：先跑一个最小 Action

进入“仪器设备”：

1. 确认 Edge 已连接；
2. 确认目标设备在线；
3. 选择只读或低风险 Action；
4. 核对参数名、类型、单位和默认值；
5. 运行并观察返回值；
6. 查看日志和任务状态。

### 第七步：再跑最小叶子 Workflow

进入“工作流”：

1. 选择最小叶子 Workflow；
2. 检查根输入和物料选择；
3. 使用默认值前先读懂默认值；
4. 运行；
5. 尝试断点、暂停、单步和继续；
6. 查看 Trace；
7. 确认节点状态和日志一致。

完成以上步骤后，才轮到组合 Workflow、PLC-Sim 和正常运行。

---

## 8. Workflow 调试器的人话翻译

| 按钮/状态 | 人话 |
|---|---|
| 正常运行 | 从入口按依赖关系执行，不等于真实设备模式 |
| 单步模式 | 每次只放行下一步，适合观察状态变化 |
| 单节点调试 | 只测试选定节点，但仍需满足其输入契约 |
| 断点 | 在节点派发前暂停，不是在动作执行一半时急停 |
| 暂停 | 请求在安全边界暂停，不保证物理设备瞬间冻结 |
| 继续 | 从当前暂停点继续到完成或下一个断点 |
| 单步 | 执行当前暂停节点，再在下一边界暂停 |
| 停止 | 取消剩余节点作业；不能代替硬件急停 |
| Trace | 查看 Electron 和 OS 上报的运行链路与 Span |

### 一个非常严肃的区别

Workbench 的“停止”是软件层任务控制。

它不是：

- 机械臂硬件急停；
- PLC 安全回路；
- 断电开关；
- 安全门；
- 现场操作员的判断。

如果发生真实危险，按现场 SOP 使用硬件安全措施，不要等待网页按钮加载动画结束。

---

## 9. 物料输入：不要拿昨天的 UUID 冒充今天的瓶子

当 Workflow 从中间节点开始，或者禁用一个上游生产者时，下游所需输入不会因为你很着急就自动出现。

必须明确绑定：

- Workflow 根输入；
- 当前 Inventory 中可选择的真实物料；
- 符合类型约束的明确值。

尤其禁止：

- 从上一次运行历史中偷一个 Material UUID；
- 用 Template UUID 代替 Material UUID；
- 用位置、标签或运输编号冒充物料身份；
- 一个物料输出未经 Split 就分给两个物理消费者。

昨天的瓶子 UUID 也许还在日志里，但昨天的瓶子本人可能已经进入了清洗机、废液桶或某位同学的论文补实验。

---

## 10. 常见故障与民间偏方辟谣

### “尚未启动 Uni-Lab OS”

检查：

- 工作区是否是真正的 domain package；
- Python 环境是否能导入 `unilabos`；
- 设备图路径是否存在；
- `package.yaml` 是否存在且合法；
- OS 日志中最早的错误是什么。

无效偏方：连续点击“校验并启动”，希望第五次时软件被你的毅力感动。

### 设备页空白

检查：

- OS 是否运行；
- Edge 是否连接；
- Registry 是否发现设备；
- 设备图是否引用正确设备；
- 设备是否上报 Action Catalog。

无效偏方：刷新页面直到设备从量子真空中产生。

### Action 按钮不可用

检查：

- 设备是否离线；
- Action 是否被锁；
- Action Catalog 是否加载失败；
- 是否已有任务运行；
- 参数是否满足 Schema；
- 当前连接是否允许任务运行。

无效偏方：强制解锁所有东西，然后宣布“锁的问题解决了”。

### Workflow 不能保存

检查：

- 当前是否为可写模式；
- 是否存在未处理确认框或远端冲突；
- 图是否能由结构化 Python 表达；
- 节点 UUID、句柄和物料身份是否稳定；
- 原文件是否有写权限。

无效偏方：添加 `# trust_me` 注释。

### PLC-Sim 启动按钮是灰色

检查：

- 是否选择了 PLC-Sim 项目目录；
- CSV 变量表是否存在；
- 握手器是否正确；
- 配置是否已保存。

无效偏方：把鼠标在灰色按钮上多停一会儿，让它反省。

### 界面成功，但硬件没动

先确认你是否仍在 Dry-run。如果是，恭喜：软件正在严格履行“不碰设备”的承诺。

如果是正常运行，再按设备、传输、PLC、安全联锁和现场 SOP 分层诊断，不要直接重复下发动作。

---

## 11. 七级证据阶梯：禁止越级吹牛

| Gate | 可以说什么 | 不可以说什么 |
|---|---|---|
| Package | 可以安装和导入 | 系统已经能运行 |
| Registry | 设备/Action/Resource 被正确发现 | 设备已经在线 |
| Catalog | ID、依赖和清单一致 | Workflow 一定可执行 |
| Authoring | Python/Graph 往返语义成立 | 调度和设备一定正确 |
| Dry-run | 软件任务链路可模拟走通 | PLC 或硬件已验证 |
| PLC-Sim | 协议/变量/握手仿真通过 | 真实硬件已验证 |
| Hardware | 有现场见证的真实执行结果 | 可以自动推广到所有设备和工况 |

实验室最昂贵的一句话通常不是“买这个设备”，而是：

> 模拟都过了，真机应该没问题，直接跑吧。

---

## 12. 正常运行前检查单

只有每项都能明确回答，才考虑切换到正常运行：

- [ ] 当前打开的是正确仓库和正确版本。
- [ ] Git 工作区中的未提交修改已知且在范围内。
- [ ] 设备图和现场设备配置版本一致。
- [ ] Runtime 和 UniLab OS 版本已确认。
- [ ] Package、Registry、Catalog 和 Authoring Gate 已通过。
- [ ] Dry-run 已通过。
- [ ] PLC-Sim 或等价模拟证据已通过。
- [ ] 单个低风险 Action 已验证。
- [ ] 最小叶子 Workflow 已验证。
- [ ] 设备周围无人，障碍物和耗材状态已检查。
- [ ] 操作员知道硬件急停位置。
- [ ] 安全门、限位、联锁和现场 SOP 有效。
- [ ] 有人负责观察日志，有人负责观察设备。
- [ ] 已明确本次测试的终止条件。

如果最后一项写的是“出问题就停”，请补充：谁判断、怎么停、停哪一层。

---

## 13. 推荐的 Agent 指令套餐

### 建设仓库

```text
使用 $unilab-domain-repo-builder，把当前工作区建设为可安装的 UniLab OS
领域包。先盘点现有文件和用户修改，按 Package → Resources/Sites →
Devices/Actions → Leaf Workflows → Composites → Simulation → Workbench
的顺序实施。不要启动真实设备。
```

### 调查启动失败

```text
使用 $unilab-domain-repo-builder，只读诊断 Workbench 的“校验并启动”
失败。先确认实际 Python、unilabos 路径、设备图、package.yaml、Registry
和最早错误。不要为了绕过前层错误而修改后层界面，也不要启动真实设备。
```

### 检查 Workflow

```text
使用 $unilab-domain-repo-builder，检查这个 Workflow 的 UUID、类型化输入、
ResourceSlot、物料流、group/parallel 结构和 Python → AST → Graph → Python
→ Graph 固定点。只做软件测试，不把成功描述为硬件验证。
```

### 准备 Workbench 验收

```text
使用 $unilab-domain-repo-builder，为当前领域包生成 Workbench E2E 清单，
覆盖工作区选择、OS 生命周期、编辑/保存、运行、暂停、继续、单步、停止、
日志和图状态。分别记录 Dry-run、PLC-Sim 和硬件证据，不合并结论。
```

---

## 14. 一张能贴在显示器旁边的速查表

```text
先选对仓库
    ↓
确认 Python / Runtime
    ↓
Package / Registry / Catalog / Authoring
    ↓
Dry-run：动作不发给设备
    ↓
单个低风险 Action
    ↓
最小叶子 Workflow + Trace
    ↓
PLC-Sim：协议与握手仿真
    ↓
组合 Workflow
    ↓
现场安全检查
    ↓
正常运行 / 真实硬件
```

任何人提出“中间几步能不能跳过”，都可以礼貌地问：

> 可以。那事故复盘 PPT 由谁来做？

---

## 15. 结语

UniLab Workbench 的最佳使用方式不是“把所有按钮都点亮”，而是让每一层证据都能回答一个明确问题：

- 包能不能装？
- Registry 能不能发现？
- Catalog 是否一致？
- Workflow 是否可往返？
- Dry-run 是否走通？
- PLC-Sim 是否握手？
- Workbench 是否可控、可停、可追踪？
- 真机是否有现场证据？

当这些问题都有答案时，Workbench 是驾驶舱。

当这些问题都没有答案但你仍然点击“正常运行”时，Workbench 是抽奖机，而奖品由安全委员会颁发。

---

## 文档证据边界

本文依据当前安装的 UniLab Workbench `0.1.0`、实际可见界面、安装包内置兼容性信息，以及项目级 `unilab-domain-repo-builder` Skill 编写。

本次检查仅验证：应用启动、欢迎页、工作区 UI、环境管理入口、IDE/Agent 和安装包中声明的功能。没有启动 UniLab OS、PLC-Sim 或任何真实设备；没有形成硬件验证结论。
