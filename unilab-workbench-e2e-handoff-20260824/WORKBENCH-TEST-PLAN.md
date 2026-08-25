# Workbench 端到端测试计划

## 测试对象

| ID | Family | 来源 | 当前能力 |
|---|---|---|---|
| A1 | `instrument.square-tactile` | SolidWorks 小装配 | `semantic-scene` |
| A2 | `instrument.bigclaw.step-reference` | STEP | `semantic-scene` |
| A3 | `synthesis.250ml-reagent-tray` | legacy SW URDF | `semantic-scene` |
| A4 | `synthesis.ptb22-linear-guide` | legacy SW URDF | `semantic-scene` |
| A5 | `synthesis.capping-gripper` | legacy SW URDF | `semantic-scene` |

五项均只允许 `workbench_display` 和 `stable_picking`，明确禁止 `motion`、`spatial_interlock_enforced` 和 `execution`。

## 用例与通过标准

| 用例 | 操作 | 通过标准 | 证据 |
|---|---|---|---|
| P0 传输完整性 | 运行 `Verify-Handoff.ps1` | 所有 manifest 文件大小和 SHA-256 一致 | 控制台输出 |
| P1 环境预检 | 运行 `00-preflight.ps1` | Python/PyYAML/cascadio、Blender、SW COM 和输入齐全；SW 未预先运行 | `preflight.json` |
| P2 重新编译 | 运行 `01-run-pipeline.ps1` | 退出码 0；生成 5 bundles 与 5 previews | `run-summary.json`、PNG |
| P3 严格门禁 | 运行 `02-verify-output.ps1` | strict-full-flow `passed: true` | 控制台输出、`gate-report.json` |
| W1 静态服务 | stage 后请求 catalog 和 5 个 GLB | HTTP 200；无路径穿越；GLB 非空 | Network 记录 |
| W2 场景显示 | Workbench 加载 catalog | 五项都可见；无空几何、NaN、明显离群 | 全景截图 |
| W3 拾取 | 分别点击至少三个不同 family | 选中项可反查 family/revision/entity；不会随机漂移 | 详情截图/测试日志 |
| W4 版本固定 | 刷新并重复加载 | catalog、bundle revision 和哈希不变，不加载“latest” | Network/日志 |
| W5 能力边界 | 查看 UI/运行时状态 | 明示 candidate；没有运动/互锁/执行入口被激活 | UI 截图 |
| W6 回归 | 执行目标仓库既有 lint/test/build | 与本轮前基线相比无新增失败 | 命令与日志 |
| N1 无效 catalog | 在测试中注入错误 schema | 明确拒绝或显示受控错误，不白屏 | 自动化测试/截图 |
| N2 缺失 GLB | 测试 URL 返回 404 | 其余场景不崩溃；错误能定位具体 asset | Console/测试 |
| N3 哈希漂移 | 测试中篡改一份临时 artifact | loader 拒绝；若当前尚无哈希校验，记录为阻塞缺口 | 测试日志 |
| N4 禁止能力 | 尝试请求 motion/interlock | 必须拒绝或保持 unavailable | 自动化测试/日志 |

## 推荐观测项

- 首次加载与热缓存加载耗时。
- 五个 GLB 的请求大小、解析时间、渲染首帧时间。
- draw call、triangle、GPU memory（若现有 Workbench 调试层可取）。
- Console error/warning 数量。
- 选中实体 ID 在刷新前后是否一致。

性能数据用于建立基线，本轮不据此授予更高能力等级。

## 故障定位顺序

1. P0 失败：重新传文件，不继续。
2. P1/P2 失败而基线夹具可在 Workbench 加载：问题在生成机环境或编译链。
3. P2/P3 通过而基线与新产物都加载失败：问题在静态服务、URL、loader 或 renderer。
4. 只有新产物失败：比较 catalog、bundle、GLB 响应头、大小与哈希。
5. 显示正常但拾取失败：检查 extras/entity registry 到 renderer 对象的映射，不从显示名称猜现场身份。

## 结果分级

- `PASS_STATIC_E2E`：上述本轮静态全流程全部通过。
- `PASS_WORKBENCH_BASELINE_ONLY`：仅基线夹具接入通过，生成链未通过。
- `PARTIAL_PIPELINE_ONLY`：生成与门禁通过，Workbench 接入未完成。
- `FAIL_INTEGRITY_OR_GATE`：传输或硬门禁失败，禁止继续作为候选发布。

这些等级都不等于 execution-qualified。
