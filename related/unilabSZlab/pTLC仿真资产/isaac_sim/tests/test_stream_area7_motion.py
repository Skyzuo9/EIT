"""Pure-Python checks for the area-7 live-stream motion schedule."""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import numpy as np


ISAAC_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ISAAC_DIR / "stream_area7_motion.py"
POINT_SET = ISAAC_DIR / "config/cr5_ptlc_area7_points.v1.json"
VALIDATION_REPORT = (
    ISAAC_DIR
    / "output/area7_multipt_video_20260814/unilab_isaac_validation.json"
)
SPEC = importlib.util.spec_from_file_location("ptlc_stream_area7_motion", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StreamArea7MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.targets, cls.sequence, _ = MODULE.load_validated_playback(
            POINT_SET, VALIDATION_REPORT
        )
        cls.segments = MODULE.build_segments(
            cls.targets,
            cls.sequence,
            move_seconds=1.5,
            hold_seconds=0.25,
        )

    def test_exact_validated_sequence_and_duration(self) -> None:
        self.assertEqual(self.sequence, MODULE.EXPECTED_SEQUENCE)
        self.assertEqual(len(set(self.sequence)), 13)
        self.assertEqual(len(self.sequence), 15)
        self.assertEqual(len(self.segments), 29)
        self.assertTrue(
            math.isclose(
                sum(segment.duration_seconds for segment in self.segments),
                24.75,
                abs_tol=1e-12,
            )
        )

    def test_cycle_starts_and_ends_at_p45(self) -> None:
        _, first_segment, _, first = MODULE.sample_cycle(self.segments, 0.0)
        _, last_segment, _, last = MODULE.sample_cycle(self.segments, 24.749999)
        self.assertEqual(first_segment.target_ref, "ptlc.P45")
        self.assertEqual(last_segment.target_ref, "ptlc.P45")
        np.testing.assert_allclose(first, self.targets["ptlc.P45"])
        np.testing.assert_allclose(last, self.targets["ptlc.P45"], atol=1e-5)

    def test_mid_transition_is_between_adjacent_targets(self) -> None:
        _, segment, progress, joints = MODULE.sample_cycle(self.segments, 1.0)
        self.assertEqual(segment.phase, "move_to_P46")
        self.assertGreater(progress, 0.0)
        self.assertLess(progress, 1.0)
        low = np.minimum(self.targets["ptlc.P45"], self.targets["ptlc.P46"])
        high = np.maximum(self.targets["ptlc.P45"], self.targets["ptlc.P46"])
        self.assertTrue(np.all(joints >= low))
        self.assertTrue(np.all(joints <= high))


if __name__ == "__main__":
    unittest.main()
