# 本机相关快照

从这台电脑上、EIT 工作区之外、且与 UniLab 资产管线直接相关的文件复制而来。不含密钥、虚拟环境和已有独立 Git 远程的超大重复克隆。

## 已纳入

- `unilabSZlab/`：深圳实验室 3D 资产流水线源码、CR5/Dobot 辅助目录、pTLC 仿真资产与现场照片。已排除 `.env`、`.venv`、SQLite 运行库、`.unilabos`。
- `unilab-domain-repo-builder/`：本机 Downloads 中的 UniLab domain 包构建器。
- `downloads-notes/`：Windows 仪器采集交接与 MoveIt 笔记（Downloads 中与管线相关、且 EIT 根目录没有的副本）。

## 有意未纳入（仍在本机）

这些目录体积大、已有独立仓库，或属于另一条采集线，不适合整包推进本仓：

| 本机路径 | 原因 |
|---|---|
| `/Users/newtides/uni-lab-assets`（约 8.9G） | 已有 `git.dp.tech:lab/uni-lab-assets.git` |
| `/Users/newtides/lab_asset_mvp_001`（约 2.3G） | RealSense 原始深度/RGB 采集 |
| `/Users/newtides/3D_asset_chem`（约 2.7G） | ICRA 化学资产伴生项目 |
| `/Users/newtides/Robo-UniLabOS`（约 779M） | 文献与旁路集成笔记 |
| `/Users/newtides/pTLC_platformUI` | 与本仓 `pTLC_platformUI` submodule 重复，且分支更旧 |
| `/Users/newtides/unilabSZlab/ptlc_unilab_sim`（约 1.4G） | 含 `.unilabos` 运行时 |
| `Downloads/*.dmg` | Workbench 安装包，不是源码 |

若需要把其中某一份也做成 submodule 或 LFS 快照，可以指定路径后再加。
