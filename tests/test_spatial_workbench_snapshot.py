"""Workbench projection tests for the EIT spatial-shadow vertical slice."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "export_spatial_workbench_snapshot.py"
SPEC = importlib.util.spec_from_file_location("export_spatial_workbench_snapshot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SpatialWorkbenchSnapshotTest(unittest.TestCase):
    def test_current_eit_snapshot_matches_compiler_artifacts(self) -> None:
        source = ROOT / "artifacts" / "spatial-shadow" / "v0"
        snapshot = MODULE.build_snapshot(source)

        self.assertEqual(snapshot["schema"], "unilab.spatial-shadow-workbench/v0")
        self.assertEqual(snapshot["sample_id"], "eit-ptlc-historical-v1")
        self.assertEqual(snapshot["action_contract_id"], "robot.tank.pick")
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertEqual(snapshot["decision"], "unknown")
        self.assertEqual(snapshot["effect"], "none")
        self.assertTrue(snapshot["not_workcell_activation"])
        self.assertEqual(
            snapshot["summary"],
            {
                "environment_entity_count": 15,
                "state_count": 15,
                "link_count": 7,
                "segment_count": 14,
                "sampled_segment_count": 4,
                "excluded_segment_count": 10,
                "continuous_evaluated_segment_count": 4,
                "self_collision_candidate_pair_count": 27,
                "playable_segment_count": 14,
                "playback_frame_count": 522,
                "attachment_model_count": 2,
                "environment_exact_contact_frame_count": 212,
                "environment_broad_only_frame_count": 189,
                "environment_exact_contact_event_count": 257,
            },
        )
        self.assertEqual(
            [item["segment_index"] for item in snapshot["segments"] if item["world_aabb"]],
            [0, 1, 11, 12],
        )
        self.assertEqual(
            [
                item["segment_index"]
                for item in snapshot["segments"]
                if item["continuous_world_aabb"]
            ],
            [0, 1, 11, 12],
        )
        self.assertEqual(
            snapshot["continuous_analysis"]["environment_collision_status"],
            "not-evaluated-frame-unregistered",
        )
        self.assertEqual(
            snapshot["world_frame"]["frame_id"], "ptlc.rail_constraint_layout_v2"
        )
        self.assertEqual(
            snapshot["registration"]["status"], "candidate-relative-layout"
        )
        self.assertFalse(
            snapshot["registration"]["world_rigid_transform_qualified"]
        )
        self.assertEqual(
            snapshot["environment_collision"]["qualification"],
            "candidate-proxy-sampled",
        )
        self.assertEqual(
            snapshot["environment_collision"]["coverage"][
                "evaluated_frame_count"
            ],
            522,
        )
        self.assertEqual(
            snapshot["environment_collision"]["summary"]["first_contact"][
                "time_s"
            ],
            6.768636363636,
        )
        rack = next(
            item
            for item in snapshot["environment_entities"]
            if item["entity_id"] == "ptlc.proxy:develop_tank_rack"
        )
        self.assertEqual(rack["collision_mode"], "compound-convex")
        self.assertEqual(rack["component_count"], 40)
        self.assertEqual(rack["geometry_unit"], "m")
        self.assertIn("compound-convex.runtime.stl", rack["geometry_path"])
        self.assertEqual(
            len(snapshot["environment_collision"]["frames"]), 522
        )
        self.assertTrue(all(len(state["links"]) == 7 for state in snapshot["states"]))
        self.assertEqual(snapshot["playback"]["duration_s"], 35.83)
        self.assertEqual(len(snapshot["playback"]["segments"]), 14)
        self.assertEqual(
            snapshot["playback"]["kinematics"],
            {
                "model_id": "dobot-cr5",
                "joint_ids": ["J1", "J2", "J3", "J4", "J5", "J6"],
                "position_unit": "rad",
                "source": "controller-to-model-calibration",
            },
        )
        playback_frames = [
            frame
            for segment in snapshot["playback"]["segments"]
            for frame in segment["frames"]
        ]
        self.assertEqual(len(playback_frames), 522)
        self.assertTrue(
            all(
                len(frame["joint_positions_rad"]) == 6
                and all(math.isfinite(value) for value in frame["joint_positions_rad"])
                and len(frame["links"]) == 7
                and all(
                    len(link["matrix_link_to_world"]) == 4
                    and all(len(row) == 4 for row in link["matrix_link_to_world"])
                    for link in frame["links"]
                )
                and all(
                    len(attachment["matrix_attachment_to_world"]) == 4
                    and all(
                        len(row) == 4
                        for row in attachment["matrix_attachment_to_world"]
                    )
                    for attachment in frame["attachments"]
                )
                for frame in playback_frames
            )
        )
        first_controller_joint_deg = -154.523621
        first_zero_offset_deg = 0.14688754
        self.assertAlmostEqual(
            playback_frames[0]["joint_positions_rad"][0],
            math.radians(first_controller_joint_deg + first_zero_offset_deg),
            places=12,
        )
        self.assertEqual(
            len(snapshot["playback"]["segments"][3]["frames"]),
            70,
        )
        self.assertEqual(
            [
                item["attachment_id"]
                for item in snapshot["playback"]["segments"][7]["frames"][0][
                    "attachments"
                ]
            ],
            ["tool:TOOL_SUCTION", "payload:plate"],
        )
        self.assertIn(
            "environment_collision", snapshot["source"]["artifacts"]
        )

    def test_export_is_deterministic_and_contains_no_absolute_paths(self) -> None:
        source = ROOT / "artifacts" / "spatial-shadow" / "v0"
        first = MODULE.build_snapshot(source)
        second = MODULE.build_snapshot(source)
        self.assertEqual(first, second)
        encoded = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(str(ROOT), encoded)
        self.assertNotIn("/Users/", encoded)

        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "current.v0.json"
            MODULE._atomic_write(output, MODULE._canonical_bytes(first, pretty=True))
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                first,
            )

    def test_float_normalization_removes_binary_tail_and_rejects_non_finite(self) -> None:
        self.assertEqual(
            MODULE._normalize_json_numbers(
                {"sum": 0.1 + 0.2, "negative_zero": -0.0, "nested": [1.0000000000004]}
            ),
            {"sum": 0.3, "negative_zero": 0.0, "nested": [1.0]},
        )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(MODULE.SpatialWorkbenchExportError):
                    MODULE._normalize_json_numbers(value)


if __name__ == "__main__":
    unittest.main()
