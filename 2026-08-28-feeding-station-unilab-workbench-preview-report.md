# 投料站 UniLab Workbench 资产管线预览报告

日期：2026-08-28

Run ID：`feeding-station-20260827-win03`

状态：`api-and-render-contract-verified / visual-review-pending`

## 1. 已完成

正常 UniLab Workbench 的 Material Graph 已可加载一个投料站主节点：

```text
投料站（P1 几何 + P2 草案）
```

该节点使用完整 P1 `geometry/station.glb`，并把 P2 自动分解结果作为只读草案凭据。
它不是把未审核的 53 条规则冒充为已批准设备包，也不授予真实 W2、碰撞、空间互锁
或硬件执行资格。

启动命令：

```bash
./scripts/run_mac_kinematic_preview.sh
```

正常主场景 URL：

```text
http://127.0.0.1:5173/?backend=local-python&backendUrl=http%3A%2F%2F127.0.0.1%3A8002&section=scene
```

## 2. 资产 receipt

`config/feeding-station-workbench-preview.json` 锁定以下输入：

| 输入 | SHA-256 |
|---|---|
| P1 handoff | `0cb3c3703c41f95ba7d569927939191944c7d5242c40b68b152523d3c71473f9` |
| P2 decomposition | `725ca56250ca6d0c2f19d7ac0392ff40d91dd81a7776305a67929933ff8ebb8c` |
| P2 layout draft | `f33c32ff39d0c63bc14f0911053c54aebb8aac8b5212953fb03852d9830eb76e` |
| P2 coverage | `c33913fc97ec9d9bf0a4e0890869a6dca95a14fc4bfd32de953ee77fc4ccc27e` |
| P1 station GLB | `f0d1afd67f2e09a048ba4ddc1c1959c61459cc7a922f0db9ad310db16c124746` |

GLB 为 283,695,812 bytes，包含 1543 nodes、1396 meshes、1588 primitives、
4764 accessors 和 45 materials。审计包围盒为
`2.401884 × 1.007715 × 1.200000 m`。

Workbench 使用 Y-up；源 SolidWorks GLB 为 Z-up。预览合同显式应用 `-π/2` X 轴旋转，
并以审计包围盒把模型水平居中、最低 Z 落到场景地面。尺寸投影为：

```text
[width, height, depth] = [2401.884, 1200.000, 1007.715] mm
```

## 3. Fail-closed 边界

预览后端启动前会验证五个文件的 bytes 和 SHA-256、GLB v2 header/JSON 几何计数、
P2 草案资格、2021/2021 唯一覆盖、53 placements、0 unassigned、0 overlap，以及唯一
GCR5 根和唯一 4 ml 代表几何。任一项漂移都启动失败。

Material capability 固定为：

```text
display=true
motion_preview=false
hardware_execution=false
spatial_interlock_enforced=false
collision_qualified=false
w2_eligible=false
```

完整待决策项见
[`2026-08-28-feeding-station-pending-decisions.md`](./2026-08-28-feeding-station-pending-decisions.md)。

## 4. 验证证据

| 检查 | 结果 |
|---|---:|
| 根仓工站合同 | 26/26 passed |
| SourceRelease + station preview 合同 | 8/8 passed |
| Pascal glTF/Material Graph 前端回归 | 66/66 passed |
| Material Graph | 1 个投料站节点、`format=gltf` |
| GLB HTTP Range | `206 Partial Content`，`0-31/283695812` |
| GLB magic | `glTF` |
| CORS / health | passed |

本次本地服务已成功启动，后端和 Vite 前端均无启动错误。当前自动化环境没有可用的
可见浏览器实例，所以不能把 API/加载合同通过写成“已完成目视验收”，也没有截图证据。

## 5. 仍需一次可见验收

运行启动脚本后，在主场景确认：

1. 场景中只有一个投料站主节点，不出现三个独立机器人占位；
2. 投料站直立、落地且水平居中，没有侧躺或悬空；
3. 机架、手套箱/外壳、料架和总装内 GCR5 比较几何可见；
4. 标签为“投料站（P1 几何 + P2 草案）”；
5. 浏览器控制台没有 GLB fetch/parse、WebGL out-of-memory 或材质错误；
6. 记录首次完整出现耗时和峰值内存，再决定 `ENG-001` 是否需要 LOD/分包。

若模型方向错误，只允许修正 preview receipt/模型基准变换；不得修改冻结 GLB。若 283.7
MB 导致浏览器不可接受，只能建立可复算的 LOD/分包派生物并保留原 GLB 摘要，不得用
未经记录的手工减面文件替换。
