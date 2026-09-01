"""Contract tests for bounded cross-platform collision candidate comparison."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script("compare_collision_candidate_reports")


class CollisionCandidateCrossPlatformTest(unittest.TestCase):
    def test_simplified_accepts_bounded_topology_variation_but_records_sha_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            left = self._report("simplified_static_mesh")
            right = copy.deepcopy(left)
            right["levels"]["l2"]["simplified_static_mesh"]["sha256"] = "b" * 64
            right["levels"]["l2"]["simplified_static_mesh"]["geometry"]["vertices"] = 995
            right["levels"]["l2"]["simplified_static_mesh"]["geometry"]["component_count"] = 101
            right["files"][-1]["sha256"] = "b" * 64
            a, b = self._write(root, left, right)
            result = MODULE.compare(a, b)
            self.assertTrue(result["passed"])
            self.assertFalse(result["l2_comparison"]["exact_sha256_match"])
            self.assertEqual(result["l2_comparison"]["mode"], "bounded-qc-simplified-static-mesh")

    def test_compound_requires_exact_l2_and_simplified_rejects_excess_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            left = self._report("compound_convex")
            right = copy.deepcopy(left)
            right["levels"]["l2"]["compound_convex"]["sha256"] = "b" * 64
            a, b = self._write(root, left, right)
            self.assertFalse(MODULE.compare(a, b)["passed"])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            left = self._report("simplified_static_mesh")
            right = copy.deepcopy(left)
            right["levels"]["l2"]["simplified_static_mesh"]["geometry"]["vertices"] = 800
            a, b = self._write(root, left, right)
            self.assertFalse(MODULE.compare(a, b)["passed"])

    @staticmethod
    def _write(root, left, right):
        a, b = root / "left.json", root / "right.json"
        a.write_text(json.dumps(left), encoding="utf-8")
        b.write_text(json.dumps(right), encoding="utf-8")
        return a, b

    @staticmethod
    def _report(key):
        candidate = {
            "method": "connected-component-convex-hulls" if key == "compound_convex" else "quadric-decimation-static-mesh",
            "sha256": "a" * 64,
            "geometry": {
                "vertices": 1000,
                "triangles": 2000,
                "component_count": 100,
                "bounds": {"size_m": [1.0, 2.0, 3.0]},
            },
            "missed_envelope": {"maximum_missed_envelope_m": 0.001},
            "cavity_preservation": {"status": "not-measurable"},
        }
        return {
            "schema": "lab.collision_candidate_report/v1",
            "asset_id": "fixture",
            "source": {
                "kind": "glb",
                "source_sha256": "c" * 64,
                "geometry_sha256": "c" * 64,
                "geometry_basis": "source-glb",
            },
            "policy": {"l2_mode": "compound-convex" if key == "compound_convex" else "simplified-static-mesh"},
            "files": [{"path": "l2/x.glb", "sha256": "a" * 64}],
            "levels": {"l2": {key: candidate}},
        }


if __name__ == "__main__":
    unittest.main()
