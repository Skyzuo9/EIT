"""Tests for the template-backed pTLC Uni-Lab commissioning adapter."""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path


ISAAC_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ISAAC_DIR / "unilab_control.py"
TEMPLATE_ROOT = Path("/Users/newtides/unilab_robot/unilab_robot_template")
POINT_SET_PATH = ISAAC_DIR / "config/cr5_ptlc_points.v2.json"
MULTI_POINT_SET_PATH = ISAAC_DIR / "config/cr5_ptlc_area7_points.v1.json"
MULTI_POINT_SEQUENCE = (
    "ptlc.P45",
    "ptlc.P46",
    "ptlc.P47",
    "ptlc.P48",
    "ptlc.P80",
    "ptlc.P79",
    "ptlc.P78",
    "ptlc.P45",
    "ptlc.P49",
    "ptlc.P50",
    "ptlc.P51",
    "ptlc.P83",
    "ptlc.P82",
    "ptlc.P81",
    "ptlc.P45",
)

SPEC = importlib.util.spec_from_file_location("ptlc_unilab_control", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CONTROL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONTROL
SPEC.loader.exec_module(CONTROL)


class UniLabControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        CONTROL.configure_template_imports(TEMPLATE_ROOT)
        cls.point_set = CONTROL.load_json_document(POINT_SET_PATH)
        cls.multi_point_set = CONTROL.load_json_document(MULTI_POINT_SET_PATH)

    def test_point_set_resolves_against_exact_cr5_model(self) -> None:
        from unilab_arm_cr5 import MODEL_DESCRIPTOR
        from unilab_robot_contracts import MotionTargetResolver, RigidTransform, ToolContext

        tool_document = CONTROL.tool_context_document()
        resolver = MotionTargetResolver(
            self.point_set,
            model=MODEL_DESCRIPTOR,
            tool_context=ToolContext(
                context_id=tool_document["context_id"],
                digest=CONTROL.canonical_digest(tool_document),
                mount_to_tcp=RigidTransform.identity(),
                attachment_generation=1,
            ),
        )
        targets = resolver.resolve_all()
        self.assertEqual(set(targets), {"ptlc.P63", "ptlc.P76"})
        self.assertAlmostEqual(
            math.degrees(targets["ptlc.P76"].joint_positions[0]),
            -144.7277,
            places=4,
        )

    def test_sequence_uses_runtime_session_and_completes_three_commands(self) -> None:
        transitions: list[tuple[str, str]] = []

        def render_transition(before, target, command_id, target_ref):
            self.assertEqual(len(before), 6)
            self.assertEqual(len(target), 6)
            transitions.append((command_id, target_ref))
            return {"frame_count": 1, "settlement": "unit-test"}

        trace = CONTROL.execute_point_sequence(
            point_set=self.point_set,
            render_transition=render_transition,
            target_refs=("ptlc.P63", "ptlc.P76", "ptlc.P63"),
        )

        self.assertTrue(trace["all_commands_succeeded"])
        self.assertEqual(
            [target_ref for _, target_ref in transitions],
            ["ptlc.P63", "ptlc.P76", "ptlc.P63"],
        )
        self.assertEqual(
            [record["result"]["state"] for record in trace["commands"]],
            ["succeeded", "succeeded", "succeeded"],
        )
        self.assertTrue(
            all(
                record["post_snapshot"]["idle"] is True
                and record["post_snapshot"]["execution_fenced"] is False
                for record in trace["commands"]
            )
        )

    def test_unlisted_joint_target_is_rejected_before_render(self) -> None:
        from unilab_arm_cr5 import MODEL_DESCRIPTOR
        from unilab_robot_contracts import MotionTargetResolver, RigidTransform, ToolContext

        tool_document = CONTROL.tool_context_document()
        tool_context = ToolContext(
            context_id=tool_document["context_id"],
            digest=CONTROL.canonical_digest(tool_document),
            mount_to_tcp=RigidTransform.identity(),
            attachment_generation=1,
        )
        targets = MotionTargetResolver(
            self.point_set,
            model=MODEL_DESCRIPTOR,
            tool_context=tool_context,
        ).resolve_all()
        called = False

        def render_transition(*_):
            nonlocal called
            called = True
            return {}

        port = CONTROL.IsaacGeometryPort(
            model=MODEL_DESCRIPTOR,
            tool_context=tool_context,
            targets=targets,
            initial_target_ref="ptlc.P63",
            render_transition=render_transition,
        )
        with self.assertRaisesRegex(ValueError, "active PointSet"):
            port.execute_joint_target(
                group_name=MODEL_DESCRIPTOR.planning_group,
                joint_names=MODEL_DESCRIPTOR.joint_names,
                target=[0.0] * 6,
                command_id="bad-target",
                parameters={
                    "speed": 0.1,
                    "acceleration": 0.1,
                    "motion_profile_ref": "test",
                },
            )
        self.assertFalse(called)

    def test_area7_multi_point_sequence_completes_fifteen_commands(self) -> None:
        transitions: list[str] = []

        def render_transition(before, target, command_id, target_ref):
            self.assertEqual(len(before), 6)
            self.assertEqual(len(target), 6)
            transitions.append(target_ref)
            return {"frame_count": 1, "settlement": "unit-test"}

        trace = CONTROL.execute_point_sequence(
            point_set=self.multi_point_set,
            render_transition=render_transition,
            target_refs=MULTI_POINT_SEQUENCE,
        )
        self.assertTrue(trace["all_commands_succeeded"])
        self.assertEqual(tuple(transitions), MULTI_POINT_SEQUENCE)
        self.assertEqual(len(set(transitions)), 13)
        self.assertEqual(
            trace["final_joint_positions_si"],
            self.multi_point_set["targets"]["ptlc"]["waypoints"]["P45"]["value"],
        )


if __name__ == "__main__":
    unittest.main()
