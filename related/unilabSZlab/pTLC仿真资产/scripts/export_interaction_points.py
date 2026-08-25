from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "pTLC仿真资产" / "interaction_points.json"
EXPECTED_SOURCE_SHA256 = "cf6f12f1db259d80b0777664391a9a17459f8b0af8f43b5b0e62128506a2b11c"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_interaction_points.py INPUT_POINTS_JSON")

    source = Path(sys.argv[1]).resolve()
    raw = source.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != EXPECTED_SOURCE_SHA256:
        raise SystemExit(
            f"source SHA-256 mismatch: expected {EXPECTED_SOURCE_SHA256}, got {source_sha256}"
        )
    data = json.loads(raw)
    robot_points = [point for group in data["robot"]["groups"] for point in group["points"]]
    plc_points = [point for group in data["plc_servo"]["groups"] for point in group["points"]]
    payload = {
        "schema_version": "0.1",
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "source": {
            "api": "http://zhlg1509460.bohrium.tech:50001/api/points",
            "local_snapshot": str(source),
            "sha256": source_sha256,
            "coordinate_rule": "Preserve pose/joint/user/tool/rail values exactly; dimensions of visual proxies never modify these records.",
        },
        "counts": {
            "robot_total": len(robot_points),
            "robot_base": sum(not point.get("is_derived", False) for point in robot_points),
            "robot_derived": sum(bool(point.get("is_derived", False)) for point in robot_points),
            "plc_semantic_points": len(plc_points),
        },
        "data": data,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "counts": payload["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
