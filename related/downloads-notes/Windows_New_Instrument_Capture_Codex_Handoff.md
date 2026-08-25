# Windows 端新仪器采集与建模交接说明

> 用途：把这份文件发送给 Windows 电脑上的 Codex，让它知道如何协助完成一个**全新实验室仪器**的采集、D435i 录制、质检和后续建模准备。
>
> 关键原则：这不是继续某个旧仪器，而是从零开始采集一个新仪器。当前路线暂不引入 Hunyuan3D，目标是得到真实尺度、粗几何、规则几何代理、语义部件和机器人可用资产卡。

## 0. 给 Windows 端 Codex 的首条消息

请把下面这段直接发给 Windows 端 Codex：

```text
我现在要在 Windows 电脑上用 D435i、手机相机、ArUco/ChArUco 标定码，为一个新的实验室仪器完整采集一遍建模数据。

请你按这份交接说明协助我完成：
1. 新仪器 asset_id 命名和文件夹创建；
2. ArUco/ChArUco 摆放检查；
3. 手机视频/照片采集指导；
4. Intel RealSense D435i 在 Windows 上的实时预览、.bag 录制和抽样检查；
5. 采集后 QC；
6. 整理回传文件，进入后续 metric-semantic asset 建模流程。

注意：
- 这是一个全新的仪器，不要沿用旧资产的名称或文件。
- 当前不使用 Hunyuan3D。
- D435i 主要用于真实尺度、桌面平面、粗点云和外形包围盒，不要求生成精细 mesh。
- 我使用的是 DICT_5X5 的 ArUco，独立大 ArUco ID 为 0-7；还有同字典的 ChArUco 板，后处理时要注意大 ArUco 和 ChArUco 小码 ID 可能重复，需要按尺寸/ROI 区分。
- 请每一步都帮我判断“是否可以进入下一步”，不确定时先做短采集和抽样检查。
```

## 1. 项目目标

新仪器采集的目标不是直接得到漂亮模型，而是建立机器人可用的 metric-semantic asset：

```text
手机/相机 RGB 视频 + ArUco/ChArUco + D435i RGB-D + 手工尺寸
→ marker 检测与尺度恢复
→ 桌面坐标系
→ D435i 粗点云/桌面分割/外形包围盒
→ primitive proxy 几何代理
→ semantic_parts.json / affordance.json / safety_constraints.json / asset_card.json
```

建模完成后，资产至少要能回答：

- 仪器在桌面坐标系中的位置和朝向；
- 仪器真实尺寸和空间占据；
- 哪些部位可接触、可抓取、需避障；
- 哪些部位是显示、按钮、旋钮、接口、盖子、透明件、危险区域；
- 机器人执行任务时如何把它作为可查询、可避障、可操作的对象。

## 2. Windows 端准备

### 2.1 必备硬件

- Windows 电脑。
- Intel RealSense D435i。
- 支持 USB3 的数据线，优先 D435i 原装线。
- 手机或相机，尽量使用原始视频文件，不要微信压缩版。
- ArUco 大码：`DICT_5X5`，ID `0-7`。
- ChArUco 板：同字典。
- 尺子或卡尺。
- 胶带、纸箱/硬纸板/支架，用于固定竖直 marker。

### 2.2 必备软件

Windows 端优先使用：

- Intel RealSense Viewer，用于实时看 Color/Depth/IR，并录制 `.bag`。
- Python 3。
- OpenCV Python，最好包含 `cv2.aruco`。
- 可选：Git / VS Code / 7-Zip。

Windows Codex 应先帮用户确认：

```powershell
python --version
python - << "PY"
import cv2
print(cv2.__version__)
print(hasattr(cv2, "aruco"))
PY
```

如果 OpenCV 没有 `aruco`，再安装或调整包。不要在用户急着采集时陷入复杂环境配置；D435i `.bag` 和手机原始视频优先。

## 3. 新仪器命名

Windows Codex 应先问用户三个短问题：

1. 这个仪器大概是什么？如果不知道，就用 `unknown_lab_device`。
2. 仪器当前状态是什么？如 `closed`、`open`、`powered_off`、`standard_state`。
3. 希望 asset_id 叫什么？如果用户不确定，按下面规则生成。

命名规则：

```text
asset_id = <简短类别>_<三位编号>
```

例子：

```text
mini_centrifuge_001
pipette_holder_001
unknown_lab_device_001
```

不要使用空格、中文、括号。文件名全部用英文小写、数字和下划线。

## 4. 文件夹结构

建议在 Windows 上创建：

```text
<PROJECT_ROOT>\captures\<asset_id>\
├── 00_manifest\
├── 01_reference_measurements\
├── 02_rgb_videos\
├── 02_rgb_photos\
├── 03_d435i_raw\
├── 04_d435i_qc_exports\
├── 07_metric_geometry\
├── 08_primitive_proxy\
├── 09_semantic_affordance\
└── 10_reports\
```

如果 Windows 电脑上没有完整项目仓库，也可以只创建：

```text
<asset_id>_capture_package\
├── manifest\
├── rgb_videos\
├── rgb_photos\
├── d435i_bag\
├── d435i_qc_exports\
├── measurements\
└── notes\
```

Windows Codex 应生成一个 `manifest\capture_manifest.md`，至少包含：

```text
asset_id:
asset_type:
state:
capture_date:
operator:
location:
aruco_dictionary: DICT_5X5
large_aruco_ids: 0,1,2,3,4,5,6,7
large_aruco_black_square_size_mm:
charuco_present: yes/no
d435i_serial:
d435i_firmware:
notes:
```

## 5. Marker 摆放规范

推荐布局：

```text
       竖直 ArUco        竖直 ArUco

              ArUco       ArUco

     ArUco        新仪器        ArUco

              ArUco       ArUco

                  ChArUco
```

要求：

- 仪器和所有 marker 全程固定，不要中途挪动。
- 大 ArUco 围绕仪器，尽量让任意视角中至少 3 个大码可见。
- ChArUco 放在前方桌面/地面上，用于尺度和标定辅助。
- 竖直 ArUco 固定在纸箱、硬纸板或支架上，提供非共面约束。
- 大 ArUco 不要离仪器太远，推荐离仪器边缘 `10-30 cm`，大型仪器可适当扩大。
- 必须量并记录大 ArUco 的**黑色方块边长**，不是外面白纸边长。

特别注意：

- 大 ArUco 和 ChArUco 小码可能来自同一 `DICT_5X5` 字典，ID 会重复。
- 后处理时大码与小码必须按像素尺寸、物理尺寸或 ROI 分开。

## 6. 手机/相机采集

### 6.1 必拍视频

全部尽量保存原始文件，不要只保存微信/飞书压缩版。

#### 01_overview_marker_check.mp4

目的：检查摆放、marker、整体视野。

要求：

- `10-20 s`。
- 仪器、ChArUco、大 ArUco、竖直 ArUco 尽量同框。
- 开头静止 `2-3 s`。
- 抽样帧中最好能看到 5 个以上大 ArUco。

#### 02_low_ring.mp4

目的：底座侧面、底部边缘、桌面接触边界。

要求：

- `45-60 s`。
- 低角度绕仪器一圈。
- 仪器完整入镜。
- 多数画面至少 3 个大 ArUco 同框。

#### 03_mid_ring.mp4

目的：仪器主体轮廓、侧面结构、部件相对位置。

要求：

- `45-60 s`。
- 中等俯角绕一圈。
- 每一面停留 `1-2 s`。
- 不要长时间只拍局部。

#### 04_high_ring.mp4

目的：顶部结构、占地轮廓、整体布局。

要求：

- `40-60 s`。
- 高角度或俯视绕一圈。
- ChArUco 和多个大 ArUco 应多次入镜。

#### 05_details_geometry_or_panels.mp4

目的：语义细节和精细几何。

如果仪器有显示屏、按钮、旋钮、接口、标签：

- 每个部件近景停留 `2-3 s`；
- 拍清屏幕/按钮/旋钮/接口/标签文字；
- 画面边缘尽量保留 1 个大 ArUco 或其他尺度参照。

如果仪器没有这些交互部件：

- 改拍外壳边缘、盖子、孔洞、透明件、内部结构、底部接触面；
- 文件仍命名为 `05_details_geometry.mp4`。

### 6.2 必拍照片

带 marker 的尺度照片：

- 正面 + marker；
- 左侧 + marker；
- 右侧 + marker；
- 背面 + marker；
- 顶部 + ChArUco；
- 尺子/卡尺和仪器同框。

干净外观照片：

- 正面、左侧、右侧、背面、顶部；
- 45 度角 4 张；
- 关键部件近景；
- 如果有透明件、黑色件、反光件，额外拍近景。

## 7. D435i Windows 采集

D435i 只负责真实尺度、桌面平面、粗点云和外形包围盒。不要期待它能完整恢复透明、黑色、反光或细小结构。

### 7.1 RealSense Viewer 检查

Windows Codex 应指导用户打开 RealSense Viewer，然后确认：

- 设备识别为 D435i；
- USB 显示为 USB3；
- Color stream 正常；
- Depth stream 正常；
- IR stream 可选；
- 画面中仪器和 marker 能看到；
- Depth 画面里桌面、纸质 marker、仪器主体有有效深度。

如果只有 RGB 没有 Depth：

- 换 USB3 线；
- 换 USB3 口；
- 避免低质量扩展坞；
- 关闭占用相机的软件；
- 重启 RealSense Viewer。

### 7.2 推荐 D435i 录制文件

建议录 4 条 `.bag`：

```text
03_d435i_raw\d435i_01_static_overview.bag
03_d435i_raw\d435i_02_mid_orbit.bag
03_d435i_raw\d435i_03_high_sweep.bag
03_d435i_raw\d435i_04_close_reference.bag
```

#### d435i_01_static_overview.bag

- `15 s`
- 固定不动。
- 仪器、ChArUco、至少 4-5 个大 ArUco 入镜。
- 用来确认整体布局和流可读。

#### d435i_02_mid_orbit.bag

- `50-70 s`
- D435i 中角度慢速绕仪器一圈。
- 每一面停顿。
- 尽量保留 2-3 个大 ArUco 入镜。

#### d435i_03_high_sweep.bag

- `35-50 s`
- 偏高角度扫一圈。
- 重点补顶部、整体占地轮廓、ChArUco 关系。

#### d435i_04_close_reference.bag

- `20-30 s`
- 近距离拍关键部件。
- 画面边缘尽量保留至少 1 个大 ArUco。
- 不要低于 D435i 稳定近距离，通常不要低于 `0.3 m`。

### 7.3 录制时的动作要求

- 先固定短录 15 秒，再录绕拍。
- 绕拍时相机慢，宁可慢一点。
- 仪器始终在画面中心附近。
- 不要边录边移动 marker。
- 透明/反光表面不要强光直射。
- 如果 depth 大面积空洞，调整角度、距离、光照后重试。

### 7.4 Windows 端命令行可选检查

如果安装了 RealSense SDK 命令行工具，Windows Codex 可尝试：

```powershell
rs-enumerate-devices.exe
```

如果能用命令行录制，也可以使用 `rs-record.exe`。但优先使用 RealSense Viewer，因为可实时看画面，适合现场判断。

## 8. 采集期间的实时判断标准

Windows Codex 应在每一步帮用户判断：

### Marker 是否合格

合格：

- 大 ArUco 0-7 至少多数出现；
- 任意主要视角至少 3 个大码可见；
- 码没有严重反光、遮挡、弯曲；
- ChArUco 清晰，至少在 overview/high angle 中出现。

需要调整：

- 只有 0-1 个大码入镜；
- ChArUco 太远太小；
- marker 贴在会晃动的纸箱/袋子上；
- marker 被仪器或手遮挡。

### D435i 是否合格

合格：

- Color 和 Depth 都有流；
- 文件是 `.bag`；
- 桌面、marker、仪器主体能看到深度；
- 文件能重新打开或抽样查看。

需要重录：

- 只有 RGB，没有 Depth；
- 录制中途掉线；
- 仪器主体大部分不在画面；
- 相机移动太快，画面模糊或点云破碎；
- 文件极小或 RealSense Viewer 无法打开。

## 9. 采集后 QC

如果 Windows 上有 Python/OpenCV，Windows Codex 可做：

- 用 OpenCV 抽样视频帧；
- 检测 `DICT_5X5` ArUco；
- 统计每段视频大 ArUco 可见数量；
- 保存 contact sheet；
- 抽取 D435i `.bag` 中的 color/depth 样帧；
- 写 `10_reports\qc_report.md`。

建议 QC 报告包含：

```text
asset_id:
date:
rgb_video_count:
d435i_bag_count:
marker_dictionary:
large_aruco_ids_seen:
overview_status: pass/warn/fail
low_ring_status: pass/warn/fail
mid_ring_status: pass/warn/fail
high_ring_status: pass/warn/fail
details_status: pass/warn/fail
d435i_status: pass/warn/fail
main_warnings:
recommended_retake:
```

## 10. 手工尺寸表

必须建立：

```text
01_reference_measurements\measurements.csv
```

模板：

```csv
item,value_mm,method,notes
overall_width,,ruler_or_caliper,
overall_depth,,ruler_or_caliper,
overall_height,,ruler_or_caliper,
base_width_or_diameter,,ruler_or_caliper,
base_height,,ruler_or_caliper,
main_body_width,,ruler_or_caliper,
main_body_depth,,ruler_or_caliper,
main_body_height,,ruler_or_caliper,
display_width,,ruler_or_caliper,if present
display_height,,ruler_or_caliper,if present
button_diameter,,ruler_or_caliper,if present
knob_diameter,,ruler_or_caliper,if present
port_width,,ruler_or_caliper,if present
port_height,,ruler_or_caliper,if present
lid_or_cover_height,,ruler_or_caliper,if present
aruco_black_square_size,,ruler,measure black square not paper border
charuco_square_size,,ruler,if known
important_note,,text,
```

如果仪器是不规则形状，至少测最大长、宽、高和主要可接触部件尺寸。

## 11. 回传文件清单

采集完成后，打包：

```text
<asset_id>_capture_package\
├── manifest\
│   └── capture_manifest.md
├── measurements\
│   └── measurements.csv
├── rgb_videos\
│   ├── 01_overview_marker_check.mp4
│   ├── 02_low_ring.mp4
│   ├── 03_mid_ring.mp4
│   ├── 04_high_ring.mp4
│   └── 05_details_geometry_or_panels.mp4
├── rgb_photos\
│   ├── marker_scale_photos\
│   └── clean_reference_photos\
├── d435i_bag\
│   ├── d435i_01_static_overview.bag
│   ├── d435i_02_mid_orbit.bag
│   ├── d435i_03_high_sweep.bag
│   └── d435i_04_close_reference.bag
├── d435i_qc_exports\
│   ├── color_sample.png
│   ├── depth_sample.png
│   └── notes.md
└── notes\
    ├── capture_log.md
    └── qc_report.md
```

`.bag` 文件可能很大，不要用微信直接传。优先使用移动硬盘、网盘或局域网传输。

## 12. 当前 Ubuntu 后处理电脑信息

当前已有一台 Ubuntu 后处理电脑，之前用于开放数据集和 LabUtopia / Lingbot-Map 相关资产处理。Windows 电脑主要负责采集；采集完成后，可以把完整采集包传到这台 Ubuntu 机器上做后处理、点云检查、资产卡生成和后续建模。

### 12.1 连接方式

已记录的连接信息：

```text
host: 172.20.0.39
user: ubuntu
ssh:  ssh ubuntu@172.20.0.39
```

注意：`172.20.0.39` 是局域网地址，换网络后可能会变化。Windows Codex 不应默认它一定可用，应该先做连通性检查：

```powershell
ssh ubuntu@172.20.0.39 "hostname && pwd && nvidia-smi"
```

如果连不上，先让用户确认 Ubuntu 电脑是否开机、是否在同一局域网、当前 IP 是否变化。

### 12.2 Ubuntu 上已有的重要目录

已知的 Ubuntu 工作目录：

```text
/home/ubuntu/workspace/chem_lab_modeling/
```

之前使用过的子目录包括：

```text
/home/ubuntu/workspace/chem_lab_modeling/transferred_from_mac/
/home/ubuntu/workspace/chem_lab_modeling/open_datasets/chem25_figshare/
/home/ubuntu/workspace/chem_lab_modeling/lingbot-map/
/home/ubuntu/workspace/chem_lab_modeling/checkpoints/lingbot-map-long.pt
/home/ubuntu/workspace/chem_lab_modeling/LabUtopia/
/home/ubuntu/workspace/chem_lab_modeling/outputs/labutopia_lab001/
/home/ubuntu/workspace/chem_lab_modeling/tools/inspect_usd_assets.py
/home/ubuntu/workspace/chem_lab_modeling/tools/build_asset_cards_from_usd_inventory.py
```

其中 `transferred_from_mac/` 是历史传输目录，`lingbot-map/`、`LabUtopia/` 和 `outputs/` 是之前开放数据集/仿真资产流程使用过的位置。不要随意删除这些目录。

### 12.3 新仪器采集包建议放置位置

对这次 Windows 采集的新仪器，建议在 Ubuntu 上新建独立目录：

```text
/home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/
├── raw_package/
├── processing/
├── outputs/
└── logs/
```

`<asset_id>` 使用本文件第 1 节定义的资产编号，例如 `mini_centrifuge_001` 或 `new_instrument_001`。

Windows Codex 可以先在 Ubuntu 上创建目录：

```powershell
ssh ubuntu@172.20.0.39 "mkdir -p /home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/raw_package /home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/processing /home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/outputs /home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/logs"
```

然后把 Windows 采集包传过去：

```powershell
scp -r .\<asset_id>_capture_package ubuntu@172.20.0.39:/home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/raw_package/
```

如果 Windows 上有 Git Bash、WSL 或 rsync，也可以使用：

```bash
rsync -avP ./<asset_id>_capture_package/ ubuntu@172.20.0.39:/home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/raw_package/<asset_id>_capture_package/
```

### 12.4 传输后检查

传完后，Windows Codex 应至少检查文件数量和关键文件是否存在：

```powershell
ssh ubuntu@172.20.0.39 "find /home/ubuntu/workspace/chem_lab_modeling/real_captures/<asset_id>/raw_package -maxdepth 4 -type f | sed -n '1,120p'"
```

重点确认：

```text
capture_manifest.md
measurements.csv
01_overview_marker_check.mp4
02_low_ring.mp4
03_mid_ring.mp4
04_high_ring.mp4
05_details_geometry_or_panels.mp4
d435i_01_static_overview.bag
d435i_02_mid_orbit.bag
d435i_03_high_sweep.bag
d435i_04_close_reference.bag
qc_report.md
```

如果 `.bag` 文件很大，优先使用移动硬盘或局域网传输；不要通过微信直接发送。

### 12.5 Mac 本地参考位置

这份交接文档在当前 Mac 上的位置：

```text
/Users/newtides/3D_asset_chem/docs/research/Windows_New_Instrument_Capture_Codex_Handoff.md
/Users/newtides/Downloads/Windows_New_Instrument_Capture_Codex_Handoff.md
```

Mac 上当前项目根目录：

```text
/Users/newtides/3D_asset_chem/
```

Windows Codex 如果需要理解项目背景，可以把这份文档作为第一入口；不要要求采集同学去操作 Blender / FreeCAD。

## 13. Windows Codex 的工作方式

Windows Codex 应尽量主动做这些事：

1. 帮用户确定 `asset_id` 和文件夹。
2. 检查 D435i 是否被 Windows/RealSense Viewer 识别。
3. 指导用户摆 marker，并要求用户拍一张 overview 照片或短视频供检查。
4. 对用户拍的视频进行抽帧和 marker 检测。
5. 判断每段是否通过，不通过就说明怎么重拍。
6. 指导 RealSense Viewer 录 `.bag`。
7. 抽样检查 `.bag` 的 color/depth。
8. 生成 `capture_manifest.md`、`measurements.csv`、`capture_log.md`、`qc_report.md`。
9. 最后确认数据是否足够进入后端建模。

不要让用户操作 Blender / FreeCAD。学生端只负责采集、尺寸、语义说明和回传原始数据。

## 14. 后端建模预期

这套数据后续会进入：

```text
marker/scale recovery
table frame estimation
D435i point cloud / table segmentation
primitive proxy fitting
semantic part annotation
affordance and safety schema
asset card generation
```

输出目标：

```text
07_metric_geometry\
├── tabletop_plane.json
├── device_segmented_point_cloud.ply
├── device_bbox_metric.json
└── scale_check.json

08_primitive_proxy\
├── primitive_proxy.json
├── collision_proxy.glb
└── visual_proxy.glb

09_semantic_affordance\
├── semantic_parts.json
├── affordance_schema.json
├── safety_constraints.json
└── asset_card.json
```

## 15. 重要提醒

- 采集质量比后处理技巧更重要。
- D435i 的价值是 metric geometry，不是漂亮视觉纹理。
- 手机/相机视频的价值是视觉细节和 marker 检测。
- 手工尺寸是关键校验，不能省略。
- 透明、黑色、反光、细缝、玻璃件都可能让 D435i 深度失败，这是正常现象。
- 不要因为 D435i 点云不完整就停止；只要桌面、主体和尺度够用，就可以进入 primitive proxy 建模。
- 只要每段视频和 `.bag` 都能解释清楚“它补了哪类信息”，这套采集就是有效的。
