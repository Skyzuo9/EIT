"""Initial spatial shadow contracts, deterministic compilation, and fail-closed tests."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "compile_spatial_shadow.py"
SPEC = importlib.util.spec_from_file_location("compile_spatial_shadow", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SpatialShadowTest(unittest.TestCase):
    def test_compound_convex_triangle_clipping_and_component_boundaries(self) -> None:
        box = MODULE._box_triangles([-0.5, -0.5, -0.5], [0.5, 0.5, 0.5])
        planes = MODULE._convex_component_planes(box)
        contact = MODULE._triangle_intersects_convex_polyhedron(
            [[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            planes,
        )
        self.assertIsNotNone(contact)
        self.assertIsNone(
            MODULE._triangle_intersects_convex_polyhedron(
                [[2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [2.0, 0.0, 1.0]],
                planes,
            )
        )
        components = MODULE._split_triangles_by_counts([*box, *box], [12, 12])
        self.assertEqual([len(component) for component in components], [12, 12])
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "triangle 总数"):
            MODULE._split_triangles_by_counts(box, [11])

    def test_current_samples_compile_deterministically_and_fail_closed(self) -> None:
        config = Path("config/spatial-shadow-samples.v0.yaml")
        first = MODULE.compile_shadow(ROOT, config)
        second = MODULE.compile_shadow(ROOT, config)
        self.assertEqual(first, second)
        MODULE.validate_artifacts(ROOT, first)

        lock = first["spatial-test-lock.json"]
        self.assertEqual(len(lock["samples"]), 2)
        by_sample = {sample["sample_id"]: sample for sample in lock["samples"]}
        self.assertFalse(
            by_sample["eit-ptlc-historical-v1"]["capabilities"]["collision_qualified"]
        )
        self.assertFalse(
            by_sample["eit-feeding-station-demo-v1"]["capabilities"]
            ["spatial_interlock_enforced"]
        )

        scene = first["ptlc-collision-scene.json"]
        self.assertEqual(scene["qualification"], "simulation-proxy-only")
        self.assertEqual(len(scene["entities"]), 15)
        self.assertTrue(all(not entity["dynamic"] for entity in scene["entities"]))
        self.assertEqual(
            set(scene["source_digests"]),
            {
                "collision-geometry-manifest",
                "collision-geometry-schema",
                "proxy-layout",
                "proxy-layout-qc",
            },
        )
        ptlc_input_roles = {
            item["role"] for item in by_sample["eit-ptlc-historical-v1"]["inputs"]
        }
        self.assertIn("collision-geometry-manifest", ptlc_input_roles)
        self.assertIn("collision-geometry-schema", ptlc_input_roles)
        self.assertFalse(
            any(role.startswith("proxy-collision-") for role in ptlc_input_roles)
        )

        motion = first["ptlc-tank1-motion-contract.json"]
        robot_steps = [step for step in motion["steps"] if step["kind"] == "robot-motion"]
        self.assertEqual(len(robot_steps), 14)
        self.assertEqual(robot_steps[0]["point_ref"], "P75")
        self.assertEqual(robot_steps[-1]["point_ref"], "P1")
        self.assertEqual(motion["resolution"]["status"], "unresolved")
        self.assertTrue(motion["resolution"]["waypoint_sequence_resolved"])
        self.assertEqual(motion["terminal_facts"]["payload_state"], "plate-attached")

        link_states = first["ptlc-tank1-link-states.json"]
        self.assertEqual(link_states["qualification"], "candidate")
        self.assertEqual(len(link_states["geometry"]), 7)
        self.assertEqual(len(link_states["states"]), 15)
        self.assertEqual(link_states["validation"]["within_threshold_count"], 15)
        self.assertEqual(link_states["validation"]["observed_outliers"], [])

        playback = first["ptlc-tank1-playback.json"]
        self.assertEqual(playback["qualification"], "diagnostic-playback")
        self.assertEqual(playback["effect"], "none")
        self.assertEqual(
            playback["coverage"],
            {
                "total_motion_segments": 14,
                "playable_segments": 14,
                "compiled_move_l_segments": 7,
                "nominal_move_j_segments": 7,
                "cp_unresolved_playable_segments": 4,
                "total_frame_count": 522,
                "compiled_move_l_frame_count": 318,
                "payload_attached_frame_count": 238,
            },
        )
        self.assertEqual(playback["timing"]["duration_s"], 35.83)
        self.assertEqual(len(playback["segments"]), 14)
        self.assertTrue(all(len(segment["frames"]) >= 2 for segment in playback["segments"]))
        self.assertTrue(
            all(
                frame["attachments"][0]["attachment_id"] == "tool:TOOL_SUCTION"
                for segment in playback["segments"]
                for frame in segment["frames"]
            )
        )

        environment_collision = first["ptlc-tank1-environment-collision.json"]
        self.assertEqual(
            environment_collision["qualification"], "candidate-proxy-sampled"
        )
        self.assertEqual(environment_collision["effect"], "none")
        self.assertFalse(
            environment_collision["registration"][
                "world_rigid_transform_qualified"
            ]
        )
        self.assertEqual(
            environment_collision["coverage"],
            {
                "segment_count": 14,
                "evaluated_frame_count": 522,
                "environment_component_count": 89,
                "exact_box_component_count": 45,
                "compound_convex_component_count": 40,
                "broad_only_component_count": 4,
                "exact_contact_frame_count": 212,
                "broad_only_overlap_frame_count": 189,
                "exact_contact_event_count": 257,
            },
        )
        self.assertEqual(
            environment_collision["summary"]["result"],
            "proxy-contact-observed",
        )
        self.assertEqual(
            environment_collision["summary"]["first_contact"],
            {
                "segment_index": 2,
                "frame_index": 14,
                "time_s": 6.768636363636,
                "moving_object_id": "tool:TOOL_SUCTION",
                "moving_kind": "tool",
                "environment_entity_id": "ptlc.proxy:develop_tank_rack",
                "environment_component_id": "ptlc.proxy:develop_tank_rack:component:36",
                "position_m": [0.790757797964, -0.222992271981, 1.599989517332],
                "method": "triangle-vs-compound-convex-clipping",
            },
        )

        corridor = first["ptlc-tank1-motion-corridor.json"]
        self.assertEqual(corridor["qualification"], "candidate-partial")
        self.assertEqual(
            corridor["coverage"],
            {
                "total_motion_segments": 14,
                "sampled_move_j_segments": 4,
                "excluded_move_j_cp_segments": 3,
                "excluded_move_l_segments": 7,
            },
        )

        continuous = first["ptlc-tank1-continuous-collision.json"]
        self.assertEqual(continuous["qualification"], "candidate-partial")
        self.assertEqual(
            continuous["coverage"],
            {
                "total_motion_segments": 14,
                "continuous_evaluated_move_j_segments": 4,
                "excluded_move_j_cp_segments": 3,
                "excluded_move_l_segments": 7,
            },
        )
        self.assertEqual(continuous["analysis"]["overall_result"], "unknown")
        self.assertEqual(
            continuous["analysis"]["environment_collision_status"],
            "not-evaluated-frame-unregistered",
        )

        certificate = first["ptlc-tank1-spatial-certificate.json"]
        decision = first["ptlc-tank1-shadow-decision.json"]
        self.assertEqual(certificate["analysis"]["result"], "unknown")
        self.assertEqual(decision["decision"], "unknown")
        self.assertEqual(decision["effect"], "none")
        self.assertEqual(decision["certificate_ref"], certificate["certificate_id"])

    def test_stale_p11_joint_is_rejected_for_move_l_endpoint(self) -> None:
        artifacts = MODULE.compile_shadow(
            ROOT, Path("config/spatial-shadow-samples.v0.yaml")
        )
        motion = artifacts["ptlc-tank1-motion-contract.json"]
        p11 = next(step for step in motion["steps"] if step.get("point_ref") == "P11")
        self.assertEqual(p11["joint_source"], "compiledMoveLTrajectory")
        self.assertEqual(p11["joint_resolution_note"], "stale-measured-joint-rejected")
        self.assertGreater(p11["stored_joint_pose_residual_mm"], 22.0)
        self.assertLess(p11["selected_joint_pose_residual_mm"], 0.001)
        self.assertEqual(
            p11["joint_deg"],
            [
                2.07307192,
                37.20467624,
                106.7679667,
                -54.96167228,
                -89.55397517,
                -65.89499757,
            ],
        )

    def test_cr5_geometry_is_metre_scale_and_rail_shift_uses_negative_x(self) -> None:
        artifacts = MODULE.compile_shadow(
            ROOT, Path("config/spatial-shadow-samples.v0.yaml")
        )
        link_states = artifacts["ptlc-tank1-link-states.json"]
        registration = link_states["kinematic_model"]["base_registration"]
        self.assertEqual(registration["reference_rail_position_mm"], 500.0)
        self.assertEqual(registration["target_rail_position_mm"], 600.0)
        self.assertEqual(registration["relative_rail_shift_m"], [-0.1, 0.0, 0.0])
        self.assertEqual(
            registration["matrix_robot_base_to_world"],
            [
                [1.0, 0.0, 0.0, -0.331431147],
                [0.0, 1.0, 0.0, -0.001677236],
                [0.0, 0.0, 1.0, 0.178497249],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )
        by_link = {item["link_id"]: item for item in link_states["geometry"]}
        self.assertEqual(sum(item["triangle_count"] for item in by_link.values()), 40764)
        self.assertEqual(by_link["base_link"]["triangle_count"], 3752)
        self.assertAlmostEqual(by_link["Link2"]["local_aabb"]["min_m"][0], -0.488410830498)
        self.assertLess(by_link["Link2"]["local_aabb"]["max_m"][2], 0.231)

    def test_partial_corridor_samples_only_unblended_move_j(self) -> None:
        artifacts = MODULE.compile_shadow(
            ROOT, Path("config/spatial-shadow-samples.v0.yaml")
        )
        corridor = artifacts["ptlc-tank1-motion-corridor.json"]
        sampled = [
            segment
            for segment in corridor["segments"]
            if segment["status"] == "sampled-candidate"
        ]
        excluded = [
            segment
            for segment in corridor["segments"]
            if segment["status"] == "excluded-unresolved"
        ]
        self.assertEqual([segment["segment_index"] for segment in sampled], [0, 1, 11, 12])
        self.assertTrue(all(segment["motion"] == "move_j" for segment in sampled))
        self.assertTrue(all(segment["cp"] == 0.0 for segment in sampled))
        self.assertTrue(
            all(segment["max_joint_delta_observed_deg"] <= 5.0 for segment in sampled)
        )
        self.assertEqual(len(excluded), 10)
        self.assertIn(
            "full-machine-gltf-registration-not-proxy-collision-scene-frame",
            corridor["limitations"],
        )
        self.assertIn(
            "continuous-collision-published-as-separate-candidate-artifact",
            corridor["limitations"],
        )

    def test_continuous_bounds_contain_finer_joint_samples(self) -> None:
        """保守连续包络必须覆盖远细于发布步长的 FK AABB 样本。"""

        config_path = Path("config/spatial-shadow-samples.v0.yaml")
        artifacts = MODULE.compile_shadow(ROOT, config_path)
        continuous = artifacts["ptlc-tank1-continuous-collision.json"]
        link_states = artifacts["ptlc-tank1-link-states.json"]
        lock = artifacts["spatial-test-lock.json"]
        locked = MODULE._locked_sample(lock, continuous["sample_id"])  # noqa: SLF001
        by_role = MODULE._inputs_by_role(locked)  # noqa: SLF001
        calibration = MODULE._mapping(  # noqa: SLF001
            MODULE._read_yaml(ROOT / by_role["robot-calibration"]["path"]),  # noqa: SLF001
            "calibration",
        )
        chain, parsed_geometry = MODULE._load_cr5_chain_and_geometry(  # noqa: SLF001
            ROOT, by_role, calibration
        )
        geometry = {item["link_id"]: item for item in parsed_geometry}
        base_world = link_states["kinematic_model"]["base_registration"][
            "matrix_robot_base_to_world"
        ]
        states = {state["state_id"]: state for state in link_states["states"]}
        evaluated = [
            segment
            for segment in continuous["segments"]
            if segment["status"] == "continuous-broad-phase-candidate"
        ]
        self.assertEqual([segment["segment_index"] for segment in evaluated], [0, 1, 11, 12])
        for segment in evaluated:
            start = states[segment["source_state_id"]]["controller_joint_deg"]
            target = states[segment["target_state_id"]]["controller_joint_deg"]
            maximum_delta = max(
                abs(end - begin) for begin, end in zip(start, target, strict=True)
            )
            fine_interval_count = max(1, int(MODULE.math.ceil(maximum_delta / 0.25)))
            envelopes = {
                item["link_id"]: item["conservative_aabb_union"]
                for item in segment["link_envelopes"]
            }
            for index in range(fine_interval_count + 1):
                fraction = index / fine_interval_count
                joints = [
                    begin + (end - begin) * fraction
                    for begin, end in zip(start, target, strict=True)
                ]
                matrices, _ = MODULE._fk_link_matrices(  # noqa: SLF001
                    joints, calibration, chain, base_world
                )
                for link_id, matrix in matrices.items():
                    local = geometry[link_id]["local_aabb"]
                    sampled_aabb = MODULE._matrix_transformed_aabb(  # noqa: SLF001
                        local["min_m"], local["max_m"], matrix
                    )
                    envelope = envelopes[link_id]
                    for axis in range(3):
                        self.assertGreaterEqual(
                            sampled_aabb["min_m"][axis] + 1e-9,
                            envelope["min_m"][axis],
                        )
                        self.assertLessEqual(
                            sampled_aabb["max_m"][axis] - 1e-9,
                            envelope["max_m"][axis],
                        )
            self.assertTrue(
                all(
                    pair["link_a"] != pair["link_b"]
                    for pair in segment["self_collision"]["pairs"]
                )
            )
            self.assertEqual(segment["self_collision"]["evaluated_pair_count"], 15)

    def test_continuous_candidate_rejects_cross_frame_inputs(self) -> None:
        config_path = Path("config/spatial-shadow-samples.v0.yaml")
        artifacts = MODULE.compile_shadow(ROOT, config_path)
        link_states = deepcopy(artifacts["ptlc-tank1-link-states.json"])
        link_states["world_frame"]["frame_id"] = "different-world"
        config = MODULE._mapping(  # noqa: SLF001
            MODULE._read_yaml(ROOT / config_path), "config"  # noqa: SLF001
        )
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "world_frame"):
            MODULE.compile_ptlc_tank1_continuous_collision_candidate(
                ROOT,
                artifacts["spatial-test-lock.json"],
                artifacts["ptlc-tank1-motion-contract.json"],
                link_states,
                artifacts["ptlc-tank1-motion-corridor.json"],
                config,
            )

    def test_new_spatial_schemas_reject_absolute_path_and_qualification_upgrade(self) -> None:
        artifacts = MODULE.compile_shadow(
            ROOT, Path("config/spatial-shadow-samples.v0.yaml")
        )
        absolute_path = deepcopy(artifacts)
        absolute_path["ptlc-tank1-link-states.json"]["geometry"][0][
            "geometry_path"
        ] = "/tmp/base_link.STL"
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "schema 校验失败"):
            MODULE.validate_artifacts(ROOT, absolute_path)

        upgraded = deepcopy(artifacts)
        upgraded["ptlc-tank1-motion-corridor.json"]["qualification"] = "qualified"
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "schema 校验失败"):
            MODULE.validate_artifacts(ROOT, upgraded)

        continuous_upgrade = deepcopy(artifacts)
        continuous_upgrade["ptlc-tank1-continuous-collision.json"][
            "qualification"
        ] = "collision-qualified"
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "schema 校验失败"):
            MODULE.validate_artifacts(ROOT, continuous_upgrade)

        playback_upgrade = deepcopy(artifacts)
        playback_upgrade["ptlc-tank1-playback.json"]["effect"] = "allow"
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "schema 校验失败"):
            MODULE.validate_artifacts(ROOT, playback_upgrade)

        environment_upgrade = deepcopy(artifacts)
        environment_upgrade["ptlc-tank1-environment-collision.json"][
            "effect"
        ] = "allow"
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "schema 校验失败"):
            MODULE.validate_artifacts(ROOT, environment_upgrade)

        registration_upgrade = deepcopy(artifacts)
        registration_upgrade["ptlc-tank1-environment-collision.json"][
            "registration"
        ]["world_rigid_transform_qualified"] = True
        with self.assertRaisesRegex(MODULE.SpatialCompileError, "schema 校验失败"):
            MODULE.validate_artifacts(ROOT, registration_upgrade)

    def test_lock_digest_changes_when_an_input_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "input.json"
            input_path.write_text('{"value":1}\n', encoding="utf-8")
            config_path = root / "config.yaml"
            config_path.write_text("schema: fixture\n", encoding="utf-8")
            config = self._minimal_config("input.json")
            first = MODULE.compile_test_lock(root, config_path, config)
            input_path.write_text('{"value":2}\n', encoding="utf-8")
            second = MODULE.compile_test_lock(root, config_path, config)
            self.assertNotEqual(first["lock_digest"], second["lock_digest"])
            self.assertNotEqual(
                first["samples"][0]["sample_digest"],
                second["samples"][0]["sample_digest"],
            )

    def test_lock_rejects_path_escape_and_duplicate_role(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "config.yaml").write_text("schema: fixture\n", encoding="utf-8")
            config = self._minimal_config("../outside.json")
            with self.assertRaisesRegex(MODULE.SpatialCompileError, "仓库内相对路径"):
                MODULE.compile_test_lock(root, root / "config.yaml", config)

            (root / "input.json").write_text("{}\n", encoding="utf-8")
            config = self._minimal_config("input.json")
            config["samples"][0]["inputs"].append(
                {"role": "fixture", "path": "input.json"}
            )
            with self.assertRaisesRegex(MODULE.SpatialCompileError, "input role 重复"):
                MODULE.compile_test_lock(root, root / "config.yaml", config)

    def test_world_aabb_respects_z_up_yaw_and_translation(self) -> None:
        low, high = MODULE._transformed_aabb(  # noqa: SLF001
            [0.0, 0.0, 0.0],
            [2.0, 1.0, 1.0],
            [1.0, 2.0, 3.0],
            [0.0, 0.0, 90.0],
        )
        self.assertEqual(low, [0.0, 2.0, 3.0])
        self.assertEqual(high, [1.0, 4.0, 4.0])

    def test_triangle_box_sat_separates_and_detects_contact(self) -> None:
        box = {"min_m": [0.0, 0.0, 0.0], "max_m": [1.0, 1.0, 1.0]}
        self.assertTrue(
            MODULE._triangle_intersects_aabb(  # noqa: SLF001
                [[0.2, 0.2, 0.2], [0.8, 0.2, 0.2], [0.2, 0.8, 0.2]],
                box,
            )
        )
        self.assertTrue(
            MODULE._triangle_intersects_aabb(  # noqa: SLF001
                [[1.0, 0.2, 0.2], [1.0, 0.8, 0.2], [1.0, 0.2, 0.8]],
                box,
            )
        )
        self.assertFalse(
            MODULE._triangle_intersects_aabb(  # noqa: SLF001
                [[1.1, 0.2, 0.2], [1.1, 0.8, 0.2], [1.1, 0.2, 0.8]],
                box,
            )
        )

    @staticmethod
    def _minimal_config(input_path: str) -> dict[str, object]:
        return {
            "samples": [
                {
                    "sample_id": "fixture-sample",
                    "label": "fixture",
                    "qualification": "shadow",
                    "capabilities": {
                        "render": False,
                        "motion_waypoints": False,
                        "collision_candidate": False,
                        "collision_qualified": False,
                        "stop_model_qualified": False,
                        "spatial_interlock_enforced": False,
                        "hardware_execution": False,
                    },
                    "not_qualified_for": ["everything"],
                    "inputs": [{"role": "fixture", "path": input_path}],
                }
            ]
        }


if __name__ == "__main__":
    unittest.main()
