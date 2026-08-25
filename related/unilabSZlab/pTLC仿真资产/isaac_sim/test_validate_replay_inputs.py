from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("validate_replay_inputs.py")
SPEC = importlib.util.spec_from_file_location("validate_replay_inputs", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ValidateReplayInputsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(__file__).resolve().parents[2]

    def test_default_replay_contract(self) -> None:
        report = MODULE.validate_inputs(self.workspace)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["counts"]["robot_total"], 239)
        self.assertEqual(report["counts"]["robot_base_with_joint"], 74)
        self.assertEqual(report["counts"]["robot_derived"], 165)
        self.assertEqual(report["blocked_placeholder_points"], ["P24", "P41", "P42", "P6"])
        self.assertEqual(
            [record["point"] for record in report["replay"]["points"]],
            ["P63", "P76", "P63"],
        )
        self.assertEqual(report["replay"]["rail_slot"], 2)

    def test_placeholder_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not validated"):
            MODULE.validate_inputs(self.workspace, ("P6", "P24"))


if __name__ == "__main__":
    unittest.main()
