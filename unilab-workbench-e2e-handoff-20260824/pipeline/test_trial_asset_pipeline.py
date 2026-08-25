from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("trial_asset_pipeline.py")
HANDOFF_ROOT = MODULE_PATH.parent.parent
SPEC = importlib.util.spec_from_file_location("trial_asset_pipeline", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TrialAssetPipelineTests(unittest.TestCase):
    def test_legacy_urdf_is_structurally_valid_but_unproven(self) -> None:
        path = (
            HANDOFF_ROOT
            / "workspace"
            / "inputs"
            / "legacy-urdf"
            / "拧盖夹爪组件.urdf"
            / "urdf"
            / "拧盖夹爪组件.urdf.urdf"
        )
        parsed = MODULE.parse_urdf(path)
        self.assertTrue(parsed["is_solidworks_exporter"])
        self.assertEqual(parsed["root_links"], ["base_link"])
        self.assertEqual(len(parsed["links"]), 6)
        self.assertEqual(len(parsed["candidates"]), 5)
        self.assertFalse(parsed["missing_meshes"])
        self.assertTrue(all(item["status"] == "unproven" for item in parsed["candidates"]))

    def test_forbidden_keys_are_found_recursively(self) -> None:
        value = {"safe": [{"device_id": "must-not-enter-family"}]}
        hits = MODULE.find_forbidden(value, {"device_id"})
        self.assertEqual(hits, ["$.safe[0].device_id"])

    def test_identity_matrix_round_trip(self) -> None:
        matrix = MODULE.mat_identity()
        self.assertEqual(MODULE.mat_multiply(matrix, matrix), matrix)
        quaternion = MODULE.matrix_quaternion(matrix)
        for actual, expected in zip(quaternion, [0.0, 0.0, 0.0, 1.0]):
            self.assertAlmostEqual(actual, expected)

    def test_snapshot_normalization_removes_only_traversal_order(self) -> None:
        first = {
            "instances": [{"id": "b"}, {"id": "a"}],
            "mates_candidate": [{"id": "m2"}, {"id": "m1"}],
            "root_occurrences": ["b", "a"],
        }
        second = {
            "instances": [{"id": "a"}, {"id": "b"}],
            "mates_candidate": [{"id": "m1"}, {"id": "m2"}],
            "root_occurrences": ["a", "b"],
        }
        self.assertEqual(
            MODULE.normalized_assembly_snapshot(first),
            MODULE.normalized_assembly_snapshot(second),
        )

    def test_generated_family_gate_when_trial_exists(self) -> None:
        output = HANDOFF_ROOT / "workspace" / "work" / "asset-pipeline-trial"
        gate_path = output / "gate-report.json"
        if not gate_path.exists():
            self.skipTest("trial output has not been generated")
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        self.assertTrue(gate["passed"], gate["failures"])


if __name__ == "__main__":
    unittest.main()
