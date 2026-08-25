# 本机生成区

此目录在交接时保持为空。运行 `scripts/00-preflight.ps1` 和 `scripts/01-run-pipeline.ps1` 后，会在这里生成：

- `preflight.json`
- `pipeline.local.yaml`
- `asset-pipeline-trial/`
- 可选的 `return-package-*`

这些是目标电脑的本机产物，不应与 `baseline/` 混淆。
