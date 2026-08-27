# 投料站 GCR5-910 自动分解与 Mac 验证报告

日期：2026-08-28  
Run ID：`feeding-station-20260827-win03`  
状态：`p2-draft-generated`  
发布资格：`false`

## 1. 结论

用户提供的 GitHub URDF 与 win03 SolidWorks occurrence 已形成可复算的同一性证据：

- GitHub 固定 commit：`94d4030db170edaa986b8d1243fd8ae27d45cffd`；
- ZIP SHA-256：`c91cd096d8c6acde34bb57c85d4b7916c6ab17dc22feff09c502f29256230612`；
- URDF SHA-256：`76e95464d07ec304bf9394b640540a87193fa977420486c348e578e9cbd38858`；
- `duco_gcr5_910_urdf.csv` 的 `GCR5-J0_1` 至 `GCR5-J6_1` 全部匹配 win03；
- 唯一机器人根为：
  `机器人移动轴模组(默认-_flexible1)-1/机器人_GCR5-910_新松(默认-_flexible1)(默认-_flexible1)-1`；
- replacement 已改为 `robot-family:duco.gcr5_910`，不再沿用不符合总装事实的
  `robot-family:dobot.cr5`。

这使设备边界、机器人替换和 4 ml 代表几何可以由 Agent 自动生成候选并由编译器
证明全覆盖；剩余人工工作从“逐个划分 2021 occurrence”缩减为“审核 53 条规则并
签署批准”。

## 2. SourceRelease 与资格边界

`robot_dc` 仓库未声明 GitHub 根许可证；包内 `package.xml` 写有 BSD，但没有随仓
根 LICENSE。当前实现只记录 URL、commit 和摘要，由下载器从原 GitHub 取回，不把
ZIP 或 mesh 提交到本仓。

该 URDF 是 SolidWorks 导出：

- 6 个 joint 均为 `continuous` 且没有厂家 limit；
- visual 与 collision 共用相同 STL；
- 当前清单注入的 `±π`、`effort=1`、`velocity=0.5` 仅限制本地 mock 预览；
- source authority 为 `project-cad-export`；
- qualification 为 `kinematic-preview-only`。

因此它不证明厂家关节限位、零位、控制器映射、TCP、基座标定、碰撞、空间互锁或
真机执行。

## 3. 自动生成结果

输入：

- P1 已验证 handoff：`feeding-station-20260827-win03/station-handoff.json`；
- 2021 occurrence、25 个顶层根；
- SourceRelease 内 19 个 legacy URDF companion CSV；
- 固定 GitHub ZIP 内 1 个 GCR5 companion CSV。

结果：

| 指标 | 结果 |
|---|---:|
| URDF/机器人包 | 20 |
| legacy `SW Components` token | 49/49 匹配 |
| GCR5 token | 7/7 匹配 |
| 自动规则 | 53 |
| occurrence 唯一覆盖 | 2021/2021 |
| 未分配 | 0 |
| 重叠 | 0 |
| approval | `draft` |
| publication eligible | `false` |

4 ml 有盖瓶代表几何由自然序确定为：

```text
投料站料架-1/4ml玻璃瓶料架.SLDPRT-1/4ml玻璃瓶(Default_按加工_)-1
```

该选择只回答首条 standalone geometry 纵切使用哪个代表 occurrence，不授予物理
槽位或运行时 site 身份。

生成物位于非 Git handoff 目录：

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `p2-auto/station-decomposition.proposal.yaml` | 16,144 | `725ca56250ca6d0c2f19d7ac0392ff40d91dd81a7776305a67929933ff8ebb8c` |
| `p2-auto/urdf-occurrence-evidence.json` | 30,604 | `2dd2483c63e9ebb8aa9c1efb5a4710e1f37c0ff99482e120316243cfd14b3a3f` |
| `p2-auto/URDF-OCCURRENCE-REVIEW.md` | 8,549 | `61f04cf49a7d04bdf23eefc8d4fdca290bbc46c9565df947b3583f8f122140e7` |
| `p2-auto/station-layout.draft.json` | 1,134,320 | `f33c32ff39d0c63bc14f0911053c54aebb8aac8b5212953fb03852d9830eb76e` |
| `p2-auto/coverage-report.json` | 860,434 | `c33913fc97ec9d9bf0a4e0890869a6dca95a14fc4bfd32de953ee77fc4ccc27e` |
| `p2-auto/DECOMPOSITION-REVIEW.md` | 9,385 | `0bbb039df15c3695318ece8a2bd8561b932f90024b3d0782bb04c6fbd6c679c4` |

前三份生成物在同一 Mac 的第二个临时目录重新生成后字节摘要一致。evidence 中记录
绝对本地路径，所以不要求 Windows 与 Mac 的 evidence JSON 字节哈希相同；跨平台
应核对输入摘要、token 覆盖、规则集合和 2021/2021 coverage。

## 4. 本次实现

- `decomposition/v1.1` 新增 `exclude_subtree_roots`，严格表达父装配壳减去子设备；
- 编译器校验排除根存在、属于严格后代、无嵌套冗余，最终仍要求零遗漏和零重叠；
- 新增 URDF CSV → occurrence 自动 proposal/evidence/review 生成器；
- 新增固定 GitHub SourceRelease 下载器，下载完成后先校验 SHA-256 再原子安装；
- 新增 DUCO GCR5-910 `package_moveit` Provider 和 Workbench 第三个预览模型；
- W2 finalizer 从硬编码 Dobot CR5 改为校验批准 layout 中任意一致的
  `robot-family:*` replacement；
- W2 template 已切换到 `robot-family:duco.gcr5_910`。

GCR5 Provider 的 Mac 复算结果：

```text
qualified joints: 6
managed meshes: 7
topology digest: fa2b94a11749a7dbb863ab5881ee67419868001e51daa05414d8178881a4d857
hardware execution: false
spatial interlock enforced: false
```

## 5. 测试与回归

- 根仓工站合同：26/26 通过；
- CR5/GCR5/FR5 SourceRelease 预览：6/6 通过；
- decomposition v1 旧输入继续通过；
- v1.1 父减子覆盖、旧 v1 排除字段、非法排除根均有负向测试；
- GCR5 模型 API、7 个 mesh、完整 6 轴遥测、并发拒绝和摘要不变测试通过；
- win03 P1 verifier 复跑仍为
  `passed=true`、`qualification=source-input-validated`、`errors=[]`。

P1 verifier 仍会读到历史 `station-handoff.json` 中的 Dobot CR5 Provider。该 handoff
作为已冻结的 P1 输入证据不原地改写；P2/W2 的投料站机器人身份由本次新证据和
最终批准的 decomposition 决定。

## 6. 仍需机械/CAD 审核的最小集合

1. 审核机器人、ETH17、安装板、夹爪/末端工具是否按 proposal 的精确根分离；
2. 审核 generic `station-assembly-shell:*` 是否需要改为更正式的 family 名称；
3. 确认 4 ml occurrence 仅是代表几何，或提供明确物理槽位政策；
4. 确认 GCR5 关节轴和零位可用于视觉预览；厂家 limit 未提供时不得升格；
5. 填写真实审核人、ISO-8601 时间和说明，再把 `approval.status` 改为 `approved`；
6. 重新运行 compiler，只有 `publication_eligible=true` 且 2021/2021 coverage 保持
   无重叠，才允许 Windows 启动新的 W2 Run ID。

`open_warnings=2` 已有确定解释：两次采集均为
`swFileLoadWarning_ReadOnly`，`open_errors=0`。它不再是自动化未知项，但必须保留在
审核记录中。
