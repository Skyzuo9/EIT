# 本机未提交改动

这些 patch 记录审计时各 submodule 工作树相对锁定提交的差异。克隆后不会自动应用。

```bash
git -C Uni-Lab-OS apply ../overlays/Uni-Lab-OS.patch
git -C pTLC_platformUI apply ../overlays/pTLC_platformUI.patch
git -C uni-lab-fe apply ../overlays/uni-lab-fe.patch
git -C dependencies/unilab_robot_template apply ../../overlays/unilab_robot_template.patch
```

| 文件 | 内容 |
|---|---|
| `Uni-Lab-OS.patch` | Python 编译器/发现层的本机小改 |
| `pTLC_platformUI.patch` | `package-lock.json` 本机差异 |
| `uni-lab-fe.patch` | Workbench 静态夹具页（`?asset-pipeline-e2e=1`） |
| `unilab_robot_template.patch` | 把 GitHub 分支尖端还原到本机当时使用的提交（本机落后 origin 3 个提交） |
