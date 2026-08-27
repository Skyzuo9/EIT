#!/usr/bin/env python3
"""对两次 SolidWorks 原生 GLB 运行平台无关的 Mac P1 语义差异诊断。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from station_glb_semantics import diagnose_glb_pair
except ModuleNotFoundError:  # 允许从仓库根目录作为模块加载
    from scripts.station_glb_semantics import diagnose_glb_pair


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary_glb", type=Path)
    parser.add_argument("repeat_glb", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = diagnose_glb_pair(args.primary_glb, args.repeat_glb)
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
        sys.stderr.write(f"GLB semantic diagnosis failed: {error}\n")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
