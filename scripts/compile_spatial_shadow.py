#!/usr/bin/env python3
"""Compile deterministic SP0/SP1 shadow inputs without granting interlock authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


LOCK_SCHEMA = "lab.spatial-test-lock/v0"
SCENE_SCHEMA = "lab.spatial-collision-scene/v0"
MOTION_SCHEMA = "lab.motion-contract/v0"
LINK_STATE_SCHEMA = "lab.spatial-link-state-sequence/v0"
PLAYBACK_SCHEMA = "lab.spatial-playback-trajectory/v0"
ENVIRONMENT_COLLISION_SCHEMA = "lab.spatial-environment-collision/v0"
CORRIDOR_SCHEMA = "lab.motion-corridor/v0"
CONTINUOUS_COLLISION_SCHEMA = "lab.continuous-collision-candidate/v0"
CERTIFICATE_SCHEMA = "lab.spatial-occupancy-certificate/v0"
DECISION_SCHEMA = "lab.spatial-interlock-decision/v0"
CONFIG_SCHEMA = "lab.spatial-shadow-samples/v0"


_ENVIRONMENT_COLLISION_CACHE: dict[
    tuple[str, str, str, str, str, str], dict[str, Any]
] = {}


class SpatialCompileError(ValueError):
    """A shadow artifact cannot be compiled without guessing or weakening evidence."""


def compile_shadow(
    repo_root: Path,
    config_path: Path,
) -> dict[str, dict[str, Any]]:
    """Compile the frozen sample lock and the first pTLC shadow vertical slice."""

    root = repo_root.resolve()
    config_file = _repo_file(root, config_path)
    config = _mapping(_read_yaml(config_file), "config")
    if config.get("schema") != CONFIG_SCHEMA:
        raise SpatialCompileError(f"config.schema 必须是 {CONFIG_SCHEMA}")
    lock = compile_test_lock(root, config_file, config)
    _validate_cross_evidence(root, lock)
    scene = compile_ptlc_collision_scene(root, lock, config)
    motion = compile_ptlc_tank1_motion_contract(root, lock, config)
    link_states = compile_ptlc_tank1_link_states(root, lock, motion, config)
    playback = compile_ptlc_tank1_playback(root, lock, motion, link_states, config)
    environment_collision = compile_ptlc_tank1_environment_collision(
        root, lock, scene, link_states, playback, config
    )
    corridor = compile_ptlc_tank1_motion_corridor(root, lock, motion, link_states, config)
    continuous_collision = compile_ptlc_tank1_continuous_collision_candidate(
        root, lock, motion, link_states, corridor, config
    )
    certificate = compile_initial_certificate(lock, scene, motion, config)
    decision = compile_initial_decision(certificate, config)
    return {
        "spatial-test-lock.json": lock,
        "ptlc-collision-scene.json": scene,
        "ptlc-tank1-motion-contract.json": motion,
        "ptlc-tank1-link-states.json": link_states,
        "ptlc-tank1-playback.json": playback,
        "ptlc-tank1-environment-collision.json": environment_collision,
        "ptlc-tank1-motion-corridor.json": corridor,
        "ptlc-tank1-continuous-collision.json": continuous_collision,
        "ptlc-tank1-spatial-certificate.json": certificate,
        "ptlc-tank1-shadow-decision.json": decision,
    }


def compile_test_lock(
    repo_root: Path,
    config_path: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Hash every declared input into a deterministic, path-safe two-sample lock."""

    raw_samples = config.get("samples")
    if not isinstance(raw_samples, Sequence) or isinstance(raw_samples, (str, bytes)):
        raise SpatialCompileError("config.samples 必须是非空数组")
    samples: list[dict[str, Any]] = []
    seen_sample_ids: set[str] = set()
    for index, raw_sample in enumerate(raw_samples):
        sample = _mapping(raw_sample, f"samples[{index}]")
        sample_id = _text(sample.get("sample_id"), f"samples[{index}].sample_id")
        if sample_id in seen_sample_ids:
            raise SpatialCompileError(f"sample_id 重复: {sample_id}")
        seen_sample_ids.add(sample_id)
        raw_inputs = sample.get("inputs")
        if not isinstance(raw_inputs, Sequence) or isinstance(raw_inputs, (str, bytes)):
            raise SpatialCompileError(f"{sample_id}.inputs 必须是非空数组")
        inputs: list[dict[str, Any]] = []
        roles: set[str] = set()
        paths: set[str] = set()
        for input_index, raw_input in enumerate(raw_inputs):
            item = _mapping(raw_input, f"{sample_id}.inputs[{input_index}]")
            role = _text(item.get("role"), f"{sample_id}.inputs[{input_index}].role")
            relative = _relative_path(item.get("path"), f"{sample_id}.{role}.path")
            if role in roles:
                raise SpatialCompileError(f"{sample_id} input role 重复: {role}")
            if relative in paths:
                raise SpatialCompileError(f"{sample_id} input path 重复: {relative}")
            roles.add(role)
            paths.add(relative)
            path = _repo_file(repo_root, relative)
            size = path.stat().st_size
            if size <= 0:
                raise SpatialCompileError(f"输入为空文件: {relative}")
            inputs.append(
                {
                    "role": role,
                    "path": relative,
                    "bytes": size,
                    "sha256": _sha256(path),
                }
            )
        capabilities = _mapping(sample.get("capabilities"), f"{sample_id}.capabilities")
        required_capabilities = {
            "render",
            "motion_waypoints",
            "collision_candidate",
            "collision_qualified",
            "stop_model_qualified",
            "spatial_interlock_enforced",
            "hardware_execution",
        }
        if set(capabilities) != required_capabilities:
            raise SpatialCompileError(
                f"{sample_id}.capabilities 必须精确包含 {sorted(required_capabilities)}"
            )
        if any(not isinstance(value, bool) for value in capabilities.values()):
            raise SpatialCompileError(f"{sample_id}.capabilities 只能是布尔值")
        locked_sample: dict[str, Any] = {
            "sample_id": sample_id,
            "label": _text(sample.get("label"), f"{sample_id}.label"),
            "qualification": _text(
                sample.get("qualification"), f"{sample_id}.qualification"
            ),
            "capabilities": dict(sorted(capabilities.items())),
            "not_qualified_for": sorted(
                _text_list(sample.get("not_qualified_for"), f"{sample_id}.not_qualified_for")
            ),
            "inputs": sorted(inputs, key=lambda value: value["role"]),
        }
        locked_sample["sample_digest"] = _document_digest(locked_sample)
        samples.append(locked_sample)
    if not samples:
        raise SpatialCompileError("config.samples 不能为空")
    lock: dict[str, Any] = {
        "schema": LOCK_SCHEMA,
        "config_sha256": _sha256(config_path),
        "samples": sorted(samples, key=lambda value: value["sample_id"]),
    }
    lock["lock_digest"] = _document_digest(lock)
    return lock


def _validate_collision_geometry_manifest(
    repo_root: Path,
    manifest: Mapping[str, Any],
    expected_sample_id: str,
) -> dict[str, Mapping[str, Any]]:
    """Verify the transitive asset bytes before using the manifest as a scene input."""

    if manifest.get("schema") != "lab.collision-geometry-manifest/v1":
        raise SpatialCompileError("collision geometry manifest schema/version 无效")
    if manifest.get("sample_id") != expected_sample_id:
        raise SpatialCompileError("collision geometry manifest sample_id 与场景不一致")
    if manifest.get("qualification") != "collision-candidate":
        raise SpatialCompileError("pTLC shadow 只接受 collision-candidate manifest")
    uses = _text_list(manifest.get("allowed_uses"), "collision manifest.allowed_uses")
    if "shadow" not in uses or "software-admission" in uses:
        raise SpatialCompileError("candidate collision manifest 只能用于 offline/shadow")
    capabilities = _mapping(manifest.get("capabilities"), "collision manifest.capabilities")
    if capabilities.get("collision_qualified") is not False:
        raise SpatialCompileError("candidate collision manifest 不能声明 collision_qualified")
    if capabilities.get("broad_phase") is not True or capabilities.get("narrow_phase") is not True:
        raise SpatialCompileError("collision manifest 缺少 broad/narrow phase capability")

    supplied_digest = _text(manifest.get("manifest_digest"), "manifest.manifest_digest")
    digest_input = dict(manifest)
    digest_input.pop("manifest_digest", None)
    if supplied_digest != _document_digest(digest_input):
        raise SpatialCompileError("collision geometry manifest_digest 与内容不一致")

    def verify_ref(
        value: Mapping[str, Any],
        *,
        path_key: str,
        digest_key: str,
        mode_key: str | None = None,
        label: str,
    ) -> None:
        relative = _relative_path(value.get(path_key), f"{label}.{path_key}")
        path = _repo_file(repo_root, relative)
        expected = _text(value.get(digest_key), f"{label}.{digest_key}")
        mode = (
            _text(value.get(mode_key), f"{label}.{mode_key}")
            if mode_key is not None
            else "raw-bytes"
        )
        if _artifact_digest(path, mode) != expected:
            raise SpatialCompileError(f"{label} artifact 摘要漂移: {relative}")

    source_artifacts = _index_by_id(
        manifest.get("source_artifacts"), "role", "collision manifest.source_artifacts"
    )
    for role, source in source_artifacts.items():
        verify_ref(
            source,
            path_key="path",
            digest_key="sha256",
            mode_key="digest_mode",
            label=f"source[{role}]",
        )
    generator = _mapping(manifest.get("generator"), "collision manifest.generator")
    verify_ref(
        generator,
        path_key="implementation_path",
        digest_key="implementation_sha256",
        mode_key="implementation_digest_mode",
        label="collision manifest.generator",
    )

    assets = _index_by_id(manifest.get("assets"), "asset_id", "collision manifest.assets")
    entity_ids: set[str] = set()
    for asset_id, asset in assets.items():
        if asset.get("qualification") != "collision-candidate":
            raise SpatialCompileError(f"{asset_id} 不是 collision-candidate")
        entity_id = _text(asset.get("entity_id"), f"{asset_id}.entity_id")
        if entity_id in entity_ids:
            raise SpatialCompileError(f"collision manifest entity_id 重复: {entity_id}")
        entity_ids.add(entity_id)
        role = _text(asset.get("role"), f"{asset_id}.role")
        if role not in {"static-environment", "stored-tool"}:
            raise SpatialCompileError(f"pTLC 静态场景不接受 {asset_id}.role={role}")
        frame = _mapping(asset.get("frame"), f"{asset_id}.frame")
        if (
            frame.get("unit") != "m"
            or frame.get("up_axis") != "+Z"
            or frame.get("handedness") != "right-handed"
        ):
            raise SpatialCompileError(f"{asset_id} frame 不是统一米制 Z-up 右手系")

        source = _mapping(asset.get("source"), f"{asset_id}.source")
        verify_ref(
            source,
            path_key="artifact_ref",
            digest_key="artifact_sha256",
            mode_key="artifact_digest_mode",
            label=f"{asset_id}.source",
        )
        visual = _mapping(asset.get("visual"), f"{asset_id}.visual")
        verify_ref(visual, path_key="path", digest_key="sha256", label=f"{asset_id}.visual")
        narrow = _mapping(asset.get("narrow_phase"), f"{asset_id}.narrow_phase")
        verify_ref(
            narrow,
            path_key="path",
            digest_key="sha256",
            label=f"{asset_id}.narrow_phase",
        )
        if narrow.get("watertight") is not True:
            raise SpatialCompileError(f"{asset_id} narrow-phase geometry 不是 watertight")
        derivation = _mapping(asset.get("derivation"), f"{asset_id}.derivation")
        verify_ref(
            derivation,
            path_key="generator_ref",
            digest_key="generator_sha256",
            mode_key="generator_digest_mode",
            label=f"{asset_id}.derivation",
        )
        qc = _mapping(asset.get("qc"), f"{asset_id}.qc")
        if qc.get("bounds_match_nominal") is not True:
            raise SpatialCompileError(f"{asset_id} nominal bounds QC 未通过")
        if qc.get("open_cavity_expected") is True and qc.get("open_cavity_preserved") is not True:
            raise SpatialCompileError(f"{asset_id} 开放空腔 QC 未通过")
    return assets


def compile_ptlc_collision_scene(
    repo_root: Path,
    lock: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the existing photo/layout proxies into a traceable candidate scene."""

    product = _product(config, "ptlc_collision_scene")
    sample_id = _text(product.get("sample_id"), "ptlc_collision_scene.sample_id")
    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    collision_manifest = _mapping(
        _read_json(_repo_file(repo_root, by_role["collision-geometry-manifest"]["path"])),
        "collision geometry manifest",
    )
    collision_schema = _mapping(
        _read_json(_repo_file(repo_root, by_role["collision-geometry-schema"]["path"])),
        "collision geometry schema",
    )
    Draft202012Validator.check_schema(collision_schema)
    collision_validator = Draft202012Validator(collision_schema)
    collision_errors = sorted(
        collision_validator.iter_errors(collision_manifest), key=lambda item: list(item.path)
    )
    if collision_errors:
        messages = [f"{list(error.path)}: {error.message}" for error in collision_errors]
        raise SpatialCompileError(
            f"collision geometry manifest schema 校验失败: {'; '.join(messages)}"
        )
    collision_assets = _validate_collision_geometry_manifest(
        repo_root, collision_manifest, sample_id
    )
    layout = _mapping(
        _read_json(_repo_file(repo_root, by_role["proxy-layout"]["path"])),
        "proxy layout",
    )
    layout_qc = _mapping(
        _read_json(_repo_file(repo_root, by_role["proxy-layout-qc"]["path"])),
        "proxy layout QC",
    )
    if layout_qc.get("status") != "passed" or int(
        layout_qc.get("unexpected_component_overlap_count", -1)
    ) != 0:
        raise SpatialCompileError("pTLC proxy layout QC 未通过或存在意外重叠")

    placements = _index_by_id(layout.get("placements"), "asset_id", "layout.placements")
    expected_ids = set(collision_assets)
    if set(placements) != expected_ids:
        raise SpatialCompileError("collision geometry manifest 与 layout 的 asset_id 集合不一致")
    if int(layout_qc.get("placed_asset_count", -1)) != len(expected_ids):
        raise SpatialCompileError("layout_qc.placed_asset_count 与 asset 数不一致")

    entities: list[dict[str, Any]] = []
    for asset_id in sorted(expected_ids):
        asset = collision_assets[asset_id]
        placement = placements[asset_id]
        narrow_phase = _mapping(asset.get("narrow_phase"), f"{asset_id}.narrow_phase")
        local_aabb = _mapping(
            narrow_phase.get("local_aabb_m"), f"{asset_id}.narrow_phase.local_aabb_m"
        )
        local_min = _vec3(local_aabb.get("min_m"), f"{asset_id}.local_aabb.min_m")
        local_max = _vec3(local_aabb.get("max_m"), f"{asset_id}.local_aabb.max_m")
        if any(left > right for left, right in zip(local_min, local_max)):
            raise SpatialCompileError(f"{asset_id} local_aabb min 不能大于 max")
        xyz = _vec3(placement.get("position_m"), f"{asset_id}.position_m")
        rpy = _vec3(placement.get("rpy_deg"), f"{asset_id}.rpy_deg")
        world_min, world_max = _transformed_aabb(local_min, local_max, xyz, rpy)
        uncertainty = _vec3(asset.get("uncertainty_m_xyz"), f"{asset_id}.uncertainty_m_xyz")
        if any(value < 0 for value in uncertainty):
            raise SpatialCompileError(f"{asset_id}.uncertainty_m_xyz 不能为负")
        geometry_relative = _relative_path(
            narrow_phase.get("path"), f"{asset_id}.narrow_phase.path"
        )
        component_world_aabbs: list[dict[str, list[float]]] = []
        if narrow_phase.get("representation") == "compound-convex":
            unit = _text(narrow_phase.get("source_unit"), f"{asset_id}.source_unit")
            scale = 1.0 if unit == "m" else 0.001 if unit == "mm" else None
            if scale is None:
                raise SpatialCompileError(f"{asset_id} compound-convex unit 不支持")
            local_components = _split_triangles_by_counts(
                _binary_stl_triangles(_repo_file(repo_root, geometry_relative), scale=scale),
                narrow_phase.get("component_triangle_counts"),
            )
            pose_matrix = _transform_matrix(
                xyz, [math.radians(value) for value in rpy]
            )
            component_world_aabbs = [
                _triangle_bounds(
                    [
                        [_transform_point(pose_matrix, point) for point in triangle]
                        for triangle in component
                    ]
                )
                for component in local_components
            ]
        entities.append(
            {
                "entity_id": _text(asset.get("entity_id"), f"{asset_id}.entity_id"),
                "role": _text(asset.get("role"), f"{asset_id}.role"),
                "dynamic": False,
                "geometry_path": geometry_relative,
                "geometry_sha256": _text(
                    narrow_phase.get("sha256"), f"{asset_id}.narrow_phase.sha256"
                ),
                "geometry_format": _text(
                    narrow_phase.get("format"), f"{asset_id}.narrow_phase.format"
                ),
                "geometry_unit": _text(
                    narrow_phase.get("source_unit"), f"{asset_id}.narrow_phase.source_unit"
                ),
                "collision_mode": _text(
                    narrow_phase.get("representation"),
                    f"{asset_id}.narrow_phase.representation",
                ),
                "component_count": int(narrow_phase.get("component_count", 0)),
                **(
                    {
                        "component_triangle_counts": [
                            int(value)
                            for value in _sequence(
                                narrow_phase.get("component_triangle_counts"),
                                f"{asset_id}.narrow_phase.component_triangle_counts",
                            )
                        ]
                    }
                    if narrow_phase.get("component_triangle_counts") is not None
                    else {}
                ),
                "component_world_aabbs": component_world_aabbs,
                "pose_world": {"xyz_m": xyz, "rpy_deg": rpy},
                "local_aabb": {"min_m": local_min, "max_m": local_max},
                "world_aabb": {"min_m": world_min, "max_m": world_max},
                "uncertainty_m_xyz": uncertainty,
                "qualification": "simulation-proxy-only",
            }
        )
    allowed_raw = layout.get("allowed_component_overlaps")
    if not isinstance(allowed_raw, Sequence) or isinstance(allowed_raw, (str, bytes)):
        raise SpatialCompileError("layout.allowed_component_overlaps 必须是数组")
    allowed: list[dict[str, Any]] = []
    for index, raw in enumerate(allowed_raw):
        overlap = _mapping(raw, f"allowed_component_overlaps[{index}]")
        assets = sorted(_text_list(overlap.get("assets"), f"allowed overlap {index}.assets"))
        if len(assets) != 2 or any(asset_id not in expected_ids for asset_id in assets):
            raise SpatialCompileError(f"allowed overlap {index} 必须引用两个已知 asset")
        allowed.append(
            {
                "entity_ids": [f"ptlc.proxy:{asset_id}" for asset_id in assets],
                "reason": _text(overlap.get("reason"), f"allowed overlap {index}.reason"),
                "approval": "source-layout-candidate",
            }
        )
    scene: dict[str, Any] = {
        "schema": SCENE_SCHEMA,
        "sample_id": sample_id,
        "mode": "shadow",
        "qualification": "simulation-proxy-only",
        "world_frame": {
            "frame_id": "ptlc.rail_constraint_layout_v2",
            "units": "m",
            "up_axis": "+Z",
            "handedness": "right-handed",
        },
        "source_digests": {
            role: by_role[role]["sha256"]
            for role in (
                "collision-geometry-manifest",
                "collision-geometry-schema",
                "proxy-layout",
                "proxy-layout-qc",
            )
        },
        "entities": entities,
        "allowed_overlaps": sorted(allowed, key=lambda item: item["entity_ids"]),
        "limitations": [
            "photo-and-point-derived-layout-not-surveyed-world-geometry",
            "spatial-ready-manifest-candidate-not-collision-qualified",
            "robot-links-not-yet-instantiated-in-collision-scene",
            "tool-proxies-represent-storage-poses-not-attached-motion",
            "collision-qualified-false",
        ],
    }
    scene["scene_digest"] = _document_digest(scene)
    return scene


def compile_ptlc_tank1_motion_contract(
    repo_root: Path,
    lock: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract the tank-1 robot waypoint sequence while preserving unresolved controller motion."""

    product = _product(config, "ptlc_tank1_motion_contract")
    sample_id = _text(product.get("sample_id"), "motion product.sample_id")
    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    operation_role = _text(product.get("operation_input_role"), "operation_input_role")
    operation = _mapping(
        _read_yaml(_repo_file(repo_root, by_role[operation_role]["path"])),
        "tank pick operation",
    )
    points_document = _mapping(
        _read_json(_repo_file(repo_root, by_role["robot-points"]["path"])),
        "robot points",
    )
    calibration = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["robot-calibration"]["path"])),
        "robot calibration",
    )
    compiled_clip = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["tank1-pick-compiled-clip"]["path"])),
        "tank1 compiled clip",
    )
    if operation.get("schema") != "ptlc.script/v1" or operation.get("name") != "robot_tank_pick":
        raise SpatialCompileError("tank-pick-operation 不是预期的 robot_tank_pick")
    selector = _mapping(product.get("selector"), "motion selector")
    tank_id = selector.get("tank_id")
    if not isinstance(tank_id, int):
        raise SpatialCompileError("selector.tank_id 必须是整数")
    branch = _select_operation_branch(operation, "tank_id", tank_id)
    clip_move_l_endpoints, stale_clip_points = _compiled_move_l_endpoints(
        compiled_clip,
        points_document,
        calibration,
    )
    points = _mapping(points_document.get("points"), "robot-points.points")
    semantic_points: dict[str, Mapping[str, Any]] = {}
    robot_name_points: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for semantic_id, raw_point in points.items():
        point = _mapping(raw_point, f"points.{semantic_id}")
        semantic_points[str(semantic_id)] = point
        robot_name = _text(point.get("robotName"), f"points.{semantic_id}.robotName")
        if robot_name in robot_name_points:
            raise SpatialCompileError(f"robotName 重复，无法稳定解析: {robot_name}")
        robot_name_points[robot_name] = (str(semantic_id), point)

    anchor: str | None = None
    rail_slot: int | None = None
    after_rail_settle = False
    payload_state = "empty"
    steps: list[dict[str, Any]] = []
    for raw_step in branch:
        step = _mapping(raw_step, "operation branch step")
        if step.get("op") != "call":
            continue
        action = step.get("action")
        args = _mapping(step.get("args", {}), f"{action}.args")
        if action == "robot.require_anchor":
            anchor = _literal_text(args.get("point_id"), "require_anchor.point_id")
            continue
        if action == "rail.ensure":
            target = _literal(args.get("Rail_Target_Position"), "rail target")
            if not isinstance(target, int):
                raise SpatialCompileError("rail target 必须是整数槽位")
            rail_slot = target
            after_rail_settle = True
            continue
        if not after_rail_settle:
            continue
        if action == "robot.tool_action":
            tool_action = _literal_text(args.get("action"), "tool_action.action")
            before = payload_state
            phase = "approach"
            if tool_action == "suction-on":
                phase = "acquire"
                payload_state = "plate-attached"
            elif tool_action in {"suction-off", "release"}:
                phase = "release"
                payload_state = "empty"
            steps.append(
                {
                    "index": len(steps),
                    "kind": "tool-state",
                    "phase": phase,
                    "payload_state_before": before,
                    "payload_state_after": payload_state,
                    "tool_action": tool_action,
                }
            )
            continue
        if action != "robot.move_to_point":
            continue
        point_ref = _literal_text(
            args.get("point_id_or_robot_name"), "move_to_point.point_id_or_robot_name"
        )
        if point_ref in semantic_points:
            semantic_id = point_ref
            point = semantic_points[point_ref]
        elif point_ref in robot_name_points:
            semantic_id, point = robot_name_points[point_ref]
        else:
            raise SpatialCompileError(f"机器人点不存在: {point_ref}")
        status = _text(point.get("status"), f"point {point_ref}.status")
        if status != "validated":
            raise SpatialCompileError(f"机器人点不是 validated: {point_ref} ({status})")
        motion = _literal_text(args.get("motion"), f"{point_ref}.motion")
        allowed_motion = _text_list(point.get("allowedMotion"), f"{point_ref}.allowedMotion")
        if motion not in allowed_motion:
            raise SpatialCompileError(f"{point_ref} 不允许 {motion}")
        pose = _vec6(point.get("pose"), f"{point_ref}.pose")
        raw_joint = point.get("joint")
        joint_source = "joint"
        resolution_note = "measured-joint"
        stored_residual_mm: float | None = None
        if raw_joint is not None:
            stored_joint = _vec6(raw_joint, f"{point_ref}.joint")
            stored_residual_mm = _tcp_position_residual_mm(
                stored_joint,
                pose,
                calibration,
                int(point.get("tool")),
            )
            if motion == "move_l" and stored_residual_mm > 1.0:
                if semantic_id not in stale_clip_points:
                    raise SpatialCompileError(
                        f"{point_ref} move_l joint/pose 相差 {stored_residual_mm:.3f}mm，"
                        "但编译片段未登记 staleJointPoints"
                    )
                if semantic_id not in clip_move_l_endpoints:
                    raise SpatialCompileError(f"{point_ref} 缺少已编译 move_l 终点")
                raw_joint = clip_move_l_endpoints[semantic_id]
                joint_source = "compiledMoveLTrajectory"
                resolution_note = "stale-measured-joint-rejected"
        else:
            raw_joint = point.get("jointSolved")
            joint_source = "jointSolved"
            resolution_note = "software-derived-point-joint"
        joint = _vec6(raw_joint, f"{point_ref}.{joint_source}")
        selected_residual_mm = _tcp_position_residual_mm(
            joint,
            pose,
            calibration,
            int(point.get("tool")),
        )
        if motion == "move_l" and selected_residual_mm > 1.0:
            raise SpatialCompileError(
                f"{point_ref} move_l 选定关节终点与 pose 相差 {selected_residual_mm:.3f}mm"
            )
        phase = "approach" if payload_state == "empty" else "transfer"
        steps.append(
            {
                "index": len(steps),
                "kind": "robot-motion",
                "phase": phase,
                "payload_state_before": payload_state,
                "payload_state_after": payload_state,
                "motion": motion,
                "point_ref": point_ref,
                "semantic_point_id": semantic_id,
                "point_status": status,
                "joint_source": joint_source,
                "joint_deg": joint,
                "joint_resolution_note": resolution_note,
                "stored_joint_pose_residual_mm": (
                    None if stored_residual_mm is None else _clean_float(stored_residual_mm)
                ),
                "selected_joint_pose_residual_mm": _clean_float(selected_residual_mm),
                "tcp_pose_controller": pose,
                "tool": int(point.get("tool")),
                "user": int(point.get("user")),
                "rail_slot": point.get("rail"),
                "acc": float(_literal(args.get("acc"), f"{point_ref}.acc")),
                "vel": float(_literal(args.get("vel"), f"{point_ref}.vel")),
                "cp": float(_literal(args.get("cp"), f"{point_ref}.cp")),
            }
        )
    motion_steps = [step for step in steps if step["kind"] == "robot-motion"]
    if anchor != "P1" or rail_slot != 5:
        raise SpatialCompileError(
            f"tank1 分支安全前提漂移: anchor={anchor!r}, rail_slot={rail_slot!r}"
        )
    if len(motion_steps) != 14:
        raise SpatialCompileError(f"tank1 预期 14 个机器人 waypoint，实际 {len(motion_steps)}")
    if motion_steps[0]["point_ref"] != "P75" or motion_steps[-1]["point_ref"] != "P1":
        raise SpatialCompileError("tank1 waypoint 首尾锚点漂移")
    if not any(step.get("tool_action") == "suction-on" for step in steps):
        raise SpatialCompileError("tank1 分支缺少 suction-on acquire 阶段")
    contract: dict[str, Any] = {
        "schema": MOTION_SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": _text(
            product.get("action_contract_id"), "motion product.action_contract_id"
        ),
        "selector": {"tank_id": tank_id},
        "mode": "shadow",
        "analysis_scope": _text(product.get("analysis_scope"), "analysis_scope"),
        "source_digests": {
            role: by_role[role]["sha256"]
            for role in (
                operation_role,
                "robot-points",
                "robot-calibration",
                "tank1-pick-compiled-clip",
            )
        },
        "preconditions": [
            "robot-anchor:P1",
            "rail-slot:5-settled",
            "controller-tool:1",
            "operation-prologue-and-rail-motion-excluded-from-this-scope",
        ],
        "resolution": {
            "status": "unresolved",
            "waypoint_sequence_resolved": True,
            "unresolved_reasons": [
                "controller-interpolation-unresolved",
                "cp-blend-unresolved",
                "continuous-collision-not-computed",
                "stop-model-missing",
            ],
        },
        "steps": steps,
        "terminal_facts": {
            "payload_state": payload_state,
            "robot_anchor_expected": "P1",
        },
    }
    contract["contract_digest"] = _document_digest(contract)
    return contract


def compile_ptlc_tank1_link_states(
    repo_root: Path,
    lock: Mapping[str, Any],
    motion: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish deterministic CR5 link poses without claiming proxy-scene registration."""

    product = _product(config, "ptlc_tank1_link_states")
    sample_id = _text(product.get("sample_id"), "link-state product.sample_id")
    if sample_id != motion["sample_id"]:
        raise SpatialCompileError("link-state sample 与 MotionContract sample 不一致")
    target_rail_slot = product.get("target_rail_slot")
    if not isinstance(target_rail_slot, int):
        raise SpatialCompileError("ptlc_tank1_link_states.target_rail_slot 必须是整数")
    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    calibration = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["robot-calibration"]["path"])),
        "robot calibration",
    )
    rig_map = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["robot-rig-map"]["path"])),
        "robot rig map",
    )
    rail_points = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["rail-points"]["path"])),
        "rail points",
    )
    points_document = _mapping(
        _read_json(_repo_file(repo_root, by_role["robot-points"]["path"])),
        "robot points",
    )
    chain, geometry = _load_cr5_chain_and_geometry(
        repo_root,
        by_role,
        calibration,
    )
    base_registration = _candidate_robot_base_registration(
        calibration,
        rig_map,
        rail_points,
        target_rail_slot,
    )
    base_world = base_registration["matrix_robot_base_to_world"]

    raw_points = _mapping(points_document.get("points"), "robot-points.points")
    anchor_matches = [
        _mapping(point, f"points.{semantic_id}")
        for semantic_id, point in raw_points.items()
        if isinstance(point, Mapping) and point.get("robotName") == "P1"
    ]
    if len(anchor_matches) != 1:
        raise SpatialCompileError(f"P1 anchor 必须唯一，实际 {len(anchor_matches)}")
    anchor = anchor_matches[0]
    anchor_joint = _vec6(anchor.get("joint"), "P1.joint")
    anchor_pose = _vec6(anchor.get("pose"), "P1.pose")
    states = [
        _compile_link_state(
            state_id="anchor:P1",
            source_kind="anchor",
            step_index=None,
            point_ref="P1",
            phase="precondition",
            payload_state="empty",
            controller_joint_deg=anchor_joint,
            controller_pose=anchor_pose,
            tool=1,
            calibration=calibration,
            chain=chain,
            geometry=geometry,
            base_world=base_world,
        )
    ]
    for step in motion["steps"]:
        if step["kind"] != "robot-motion":
            continue
        states.append(
            _compile_link_state(
                state_id=_waypoint_state_id(step),
                source_kind="waypoint",
                step_index=int(step["index"]),
                point_ref=_text(step.get("point_ref"), "motion step.point_ref"),
                phase=_text(step.get("phase"), "motion step.phase"),
                payload_state=_text(
                    step.get("payload_state_after"), "motion step.payload_state_after"
                ),
                controller_joint_deg=_vec6(step.get("joint_deg"), "motion step.joint_deg"),
                controller_pose=_vec6(
                    step.get("tcp_pose_controller"), "motion step.tcp_pose_controller"
                ),
                tool=int(step["tool"]),
                calibration=calibration,
                chain=chain,
                geometry=geometry,
                base_world=base_world,
            )
        )
    if len(states) != 15:
        raise SpatialCompileError(f"link-state 序列预期 P1 + 14 waypoint，实际 {len(states)}")
    residual_limit_mm = 1.0
    observed_outliers = [
        {
            "state_id": state["state_id"],
            "point_ref": state["point_ref"],
            "position_residual_mm": state["tool_1_tcp_validation"]["position_residual_mm"],
        }
        for state in states
        if state["tool_1_tcp_validation"]["position_residual_mm"] > residual_limit_mm
    ]
    nominal_residuals = [
        state["tool_1_tcp_validation"]["position_residual_mm"]
        for state in states
        if state["tool_1_tcp_validation"]["position_residual_mm"] <= residual_limit_mm
    ]
    link_order = ["base_link", *(f"Link{index}" for index in range(1, 7))]
    sequence: dict[str, Any] = {
        "schema": LINK_STATE_SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": motion["action_contract_id"],
        "mode": "shadow",
        "qualification": "candidate",
        "world_frame": {
            "frame_id": "ptlc.full-machine-gltf-z-up-candidate",
            "units": "m",
            "up_axis": "+Z",
            "handedness": "right-handed",
        },
        "source_digests": {
            **{
                role: by_role[role]["sha256"]
                for role in (
                    "robot-points",
                    "robot-calibration",
                    "robot-rig-map",
                    "rail-points",
                    "tank1-pick-compiled-clip",
                    "cr5-urdf",
                    "cr5-base-collision",
                    "cr5-j1-collision",
                    "cr5-j2-collision",
                    "cr5-j3-collision",
                    "cr5-j4-collision",
                    "cr5-j5-collision",
                    "cr5-j6-collision",
                )
            },
            "motion-contract": motion["contract_digest"],
        },
        "kinematic_model": {
            "model_id": "dobot-cr5",
            "root_link": "base_link",
            "link_order": link_order,
            "joint_ids": [_text(item.get("id"), "calibration joint.id") for item in chain],
            "controller_to_model": {
                "equation": "q_model_deg=sign*q_controller_deg+zero_offset_deg",
                "sign": [float(item["sign"]) for item in chain],
                "zero_offset_deg": [float(item["zero_offset_deg"]) for item in chain],
            },
            "base_registration": base_registration,
        },
        "geometry": geometry,
        "states": states,
        "validation": {
            "method": "tool-1-fk-vs-controller-tcp-position",
            "position_residual_threshold_mm": residual_limit_mm,
            "evaluated_state_count": len(states),
            "within_threshold_count": len(nominal_residuals),
            "observed_outliers": observed_outliers,
            "max_residual_excluding_observed_outliers_mm": _clean_float(
                max(nominal_residuals, default=0.0)
            ),
        },
        "limitations": [
            "full-machine-gltf-registration-not-proxy-collision-scene-frame",
            "rail-slot-shift-is-candidate-unqualified-registration",
            "cr5-skeleton-not-verified-equivalent-to-field-cr5a",
            "dynamic-tool-geometry-missing",
            "payload-attachment-geometry-missing",
            "tool-rotary-kinematics-missing",
            "compiled-move-l-terminal-is-software-derived-not-refreshed-hardware-joint",
            "collision-qualified-false",
        ],
    }
    sequence["sequence_digest"] = _document_digest(sequence)
    return sequence


def compile_ptlc_tank1_playback(
    repo_root: Path,
    lock: Mapping[str, Any],
    motion: Mapping[str, Any],
    link_states: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile a deterministic, diagnostic-only playback timeline for Workbench.

    MoveL samples come from the already locked pTLC clip compiler output. MoveJ
    samples are an explicit nominal interpolation for visualization. CP/blend
    segments remain playable, but are labelled unresolved and can never be used
    as controller-faithful or collision-qualified evidence.
    """

    product = _product(config, "ptlc_tank1_playback")
    sample_id = _text(product.get("sample_id"), "playback product.sample_id")
    if sample_id != motion["sample_id"] or sample_id != link_states["sample_id"]:
        raise SpatialCompileError("playback sample 与输入产物 sample 不一致")
    frame_rate_hz = product.get("frame_rate_hz")
    if (
        not isinstance(frame_rate_hz, (int, float))
        or isinstance(frame_rate_hz, bool)
        or not math.isfinite(frame_rate_hz)
        or frame_rate_hz <= 0
    ):
        raise SpatialCompileError("playback.frame_rate_hz 必须是正有限数")
    frame_rate_hz = float(frame_rate_hz)

    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    calibration = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["robot-calibration"]["path"])),
        "robot calibration",
    )
    clip = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["tank1-pick-compiled-clip"]["path"])),
        "tank1 compiled clip",
    )
    asset_manifest = _mapping(
        _read_json(_repo_file(repo_root, by_role["proxy-asset-manifest"]["path"])),
        "proxy asset manifest",
    )
    device_manifest = _mapping(
        _read_json(_repo_file(repo_root, by_role["device-manifest"]["path"])),
        "device manifest",
    )
    chain, parsed_geometry = _load_cr5_chain_and_geometry(
        repo_root, by_role, calibration
    )
    geometry = {item["link_id"]: item for item in parsed_geometry}
    link_order = ("base_link", *(f"Link{index}" for index in range(1, 7)))
    base_world = _matrix4(
        link_states["kinematic_model"]["base_registration"][
            "matrix_robot_base_to_world"
        ],
        "playback base registration",
    )

    raw_clip_steps = clip.get("steps")
    if not isinstance(raw_clip_steps, Sequence) or isinstance(
        raw_clip_steps, (str, bytes)
    ):
        raise SpatialCompileError("compiled clip.steps 必须是数组")
    clip_motion_steps: list[tuple[int, Mapping[str, Any], Mapping[str, Any]]] = []
    for clip_index, raw_clip_step in enumerate(raw_clip_steps):
        clip_step = _mapping(raw_clip_step, f"compiled clip.steps[{clip_index}]")
        command = _mapping(clip_step.get("do"), f"compiled clip.steps[{clip_index}].do")
        raw_robot_point = command.get("robot_point")
        if raw_robot_point is None:
            continue
        robot_point = _mapping(
            raw_robot_point, f"compiled clip.steps[{clip_index}].do.robot_point"
        )
        clip_motion_steps.append((clip_index, clip_step, robot_point))

    motion_steps = [step for step in motion["steps"] if step["kind"] == "robot-motion"]
    if len(clip_motion_steps) != len(motion_steps):
        raise SpatialCompileError(
            "compiled clip 与 MotionContract 机器人运动段数不一致"
        )
    compiled = _mapping(clip.get("compiled"), "compiled clip.compiled")
    raw_move_l_paths = _mapping(
        compiled.get("moveLTrajectories"), "compiled.moveLTrajectories"
    )
    move_l_paths: dict[int, list[list[float]]] = {}
    for raw_index, raw_path in raw_move_l_paths.items():
        try:
            clip_index = int(raw_index)
        except (TypeError, ValueError) as error:
            raise SpatialCompileError(
                f"moveLTrajectories key 非整数: {raw_index!r}"
            ) from error
        if not isinstance(raw_path, Sequence) or isinstance(raw_path, (str, bytes)):
            raise SpatialCompileError(f"moveLTrajectories[{clip_index}] 必须是数组")
        move_l_paths[clip_index] = [
            _vec6(value, f"moveLTrajectories[{clip_index}][{index}]")
            for index, value in enumerate(raw_path)
        ]

    tool_specs = _index_by_id(
        asset_manifest.get("tool_proxies"), "asset_id", "asset_manifest.tool_proxies"
    )
    suction_spec = tool_specs.get("tool_suction")
    if suction_spec is None:
        raise SpatialCompileError("proxy asset manifest 缺 tool_suction")
    tool_dimensions = [
        value / 1000.0
        for value in _number_vector(
            suction_spec.get("dimensions_mm"), 3, "tool_suction.dimensions_mm"
        )
    ]
    physical_mount = _mapping(
        calibration.get("physical_tool_mount"), "physical_tool_mount"
    )
    if physical_mount.get("status") != "fitted-from-three-cad-docks":
        raise SpatialCompileError("physical_tool_mount 尚未达到预期 fitted 状态")
    mount_matrix = _transform_matrix(
        _vec3(physical_mount.get("translation_m"), "physical_tool_mount.translation_m"),
        [
            math.radians(value)
            for value in _vec3(
                physical_mount.get("rpy_deg"), "physical_tool_mount.rpy_deg"
            )
        ],
    )
    tool_local_aabb = {
        "min_m": [-tool_dimensions[0] / 2.0, -tool_dimensions[1] / 2.0, -tool_dimensions[2]],
        "max_m": [tool_dimensions[0] / 2.0, tool_dimensions[1] / 2.0, 0.0],
    }
    tool_transform_spec = _mapping(
        _mapping(calibration.get("tool_transforms"), "tool_transforms").get("1"),
        "tool_transforms.1",
    )
    tcp_matrix = _transform_matrix(
        _vec3(tool_transform_spec.get("translation_m"), "tool 1 translation"),
        [
            math.radians(value)
            for value in _vec3(tool_transform_spec.get("rpy_deg"), "tool 1 rpy")
        ],
    )
    inventory = _mapping(device_manifest.get("inventory"), "device_manifest.inventory")
    plate_spec = _mapping(
        inventory.get("samplePlateSpec"), "inventory.samplePlateSpec"
    )
    footprint_mm = _number_vector(
        plate_spec.get("footprintMm"), 2, "samplePlateSpec.footprintMm"
    )
    plate_height_mm = plate_spec.get("heightMm")
    if (
        not isinstance(plate_height_mm, (int, float))
        or isinstance(plate_height_mm, bool)
        or plate_height_mm <= 0
    ):
        raise SpatialCompileError("samplePlateSpec.heightMm 必须是正数")
    payload_dimensions = [
        footprint_mm[0] / 1000.0,
        footprint_mm[1] / 1000.0,
        float(plate_height_mm) / 1000.0,
    ]
    payload_local_aabb = {
        "min_m": [
            -payload_dimensions[0] / 2.0,
            -payload_dimensions[1] / 2.0,
            -payload_dimensions[2],
        ],
        "max_m": [payload_dimensions[0] / 2.0, payload_dimensions[1] / 2.0, 0.0],
    }

    endpoint_states = {state["state_id"]: state for state in link_states["states"]}
    source_state = endpoint_states["anchor:P1"]
    timeline_s = 0.0
    segments: list[dict[str, Any]] = []
    total_frame_count = 0
    move_l_frame_count = 0
    cp_segment_count = 0
    attachment_frame_count = 0
    for segment_index, (motion_step, clip_tuple) in enumerate(
        zip(motion_steps, clip_motion_steps, strict=True)
    ):
        clip_index, clip_step, robot_point = clip_tuple
        target_state = endpoint_states[_waypoint_state_id(motion_step)]
        clip_point_id = _text(robot_point.get("id"), f"clip step {clip_index}.point id")
        if clip_point_id != motion_step["semantic_point_id"]:
            raise SpatialCompileError(
                f"segment {segment_index} clip/MotionContract 点不一致: "
                f"{clip_point_id} != {motion_step['semantic_point_id']}"
            )
        clip_motion = _text(
            robot_point.get("motion"), f"clip step {clip_index}.motion"
        )
        if clip_motion != motion_step["motion"]:
            raise SpatialCompileError(
                f"segment {segment_index} clip/MotionContract motion 不一致"
            )
        duration = clip_step.get("dur")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise SpatialCompileError(f"clip step {clip_index}.dur 必须是正有限数")
        duration = float(duration)
        ease = _text(clip_step.get("ease"), f"clip step {clip_index}.ease")
        start_joint = _vec6(
            source_state["controller_joint_deg"], f"segment {segment_index}.start_joint"
        )
        target_joint = _vec6(
            target_state["controller_joint_deg"], f"segment {segment_index}.target_joint"
        )
        cp = float(motion_step["cp"])
        if motion_step["motion"] == "move_l":
            path = move_l_paths.get(clip_index)
            if path is None or len(path) < 2:
                raise SpatialCompileError(
                    f"MoveL clip step {clip_index} 缺少已编译逐帧轨迹"
                )
            interpolation = "compiled-move-l-joint-trajectory"
            move_l_frame_count += len(path)
        else:
            maximum_delta = max(
                abs(end - begin)
                for begin, end in zip(start_joint, target_joint, strict=True)
            )
            interval_count = max(
                1,
                int(math.ceil(duration * frame_rate_hz)),
                int(math.ceil(maximum_delta / 5.0)),
            )
            path = []
            for index in range(interval_count + 1):
                linear = index / interval_count
                fraction = linear
                if ease == "inout":
                    fraction = linear * linear * (3.0 - 2.0 * linear)
                path.append(
                    [
                        begin + (end - begin) * fraction
                        for begin, end in zip(start_joint, target_joint, strict=True)
                    ]
                )
            interpolation = (
                "nominal-unblended-move-j"
                if abs(cp) > 1e-12
                else "nominal-move-j"
            )
        for label, actual, expected in (
            ("start", path[0], start_joint),
            ("target", path[-1], target_joint),
        ):
            if max(abs(a - b) for a, b in zip(actual, expected, strict=True)) > 1e-3:
                raise SpatialCompileError(
                    f"segment {segment_index} playback {label} 与端点关节不一致"
                )
        if abs(cp) > 1e-12:
            cp_segment_count += 1

        frames: list[dict[str, Any]] = []
        for frame_index, joints in enumerate(path):
            progress = frame_index / (len(path) - 1)
            matrices, _ = _fk_link_matrices(
                joints, calibration, chain, base_world
            )
            links = []
            for link_id in link_order:
                local = geometry[link_id]["local_aabb"]
                links.append(
                    {
                        "link_id": link_id,
                        "matrix_link_to_world": _clean_matrix(matrices[link_id]),
                        "world_aabb": _matrix_transformed_aabb(
                            local["min_m"], local["max_m"], matrices[link_id]
                        ),
                    }
                )
            attachment_matrix = _matmul4(matrices["Link6"], mount_matrix)
            attachments = [
                {
                    "attachment_id": "tool:TOOL_SUCTION",
                    "kind": "tool",
                    "geometry_source": "proxy:tool_suction",
                    "matrix_attachment_to_world": _clean_matrix(attachment_matrix),
                    "world_aabb": _matrix_transformed_aabb(
                        tool_local_aabb["min_m"],
                        tool_local_aabb["max_m"],
                        attachment_matrix,
                    ),
                }
            ]
            if motion_step["payload_state_after"] == "plate-attached":
                payload_matrix = _matmul4(matrices["Link6"], tcp_matrix)
                attachments.append(
                    {
                        "attachment_id": "payload:plate",
                        "kind": "payload",
                        "geometry_source": f"device-manifest:{plate_spec['installed']}",
                        "matrix_attachment_to_world": _clean_matrix(payload_matrix),
                        "world_aabb": _matrix_transformed_aabb(
                            payload_local_aabb["min_m"],
                            payload_local_aabb["max_m"],
                            payload_matrix,
                        ),
                    }
                )
                attachment_frame_count += 1
            frames.append(
                {
                    "frame_index": frame_index,
                    "time_s": _clean_float(timeline_s + duration * progress),
                    "segment_time_s": _clean_float(duration * progress),
                    "progress": _clean_float(progress),
                    "controller_joint_deg": [_clean_float(value) for value in joints],
                    "links": links,
                    "attachments": attachments,
                }
            )
        segment: dict[str, Any] = {
            "segment_index": segment_index,
            "source_state_id": source_state["state_id"],
            "target_state_id": target_state["state_id"],
            "target_step_index": int(motion_step["index"]),
            "source_clip_step_index": clip_index,
            "point_ref": motion_step["point_ref"],
            "motion": motion_step["motion"],
            "cp": cp,
            "phase": motion_step["phase"],
            "payload_state": motion_step["payload_state_after"],
            "duration_s": _clean_float(duration),
            "start_time_s": _clean_float(timeline_s),
            "end_time_s": _clean_float(timeline_s + duration),
            "timing_source": "compiled-clip-duration",
            "interpolation": interpolation,
            "controller_fidelity": (
                "diagnostic-compiled-move-l"
                if motion_step["motion"] == "move_l" and abs(cp) <= 1e-12
                else "nominal-controller-unverified"
            ),
            "reason_codes": (
                ["cp-blend-controller-semantics-unresolved"]
                if abs(cp) > 1e-12
                else ["diagnostic-playback-not-controller-execution"]
            ),
            "frames": frames,
        }
        segments.append(segment)
        total_frame_count += len(frames)
        timeline_s += duration
        source_state = target_state

    playback: dict[str, Any] = {
        "schema": PLAYBACK_SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": motion["action_contract_id"],
        "mode": "shadow",
        "effect": "none",
        "qualification": "diagnostic-playback",
        "world_frame": dict(link_states["world_frame"]),
        "source_digests": {
            "motion_contract": motion["contract_digest"],
            "link_state_sequence": link_states["sequence_digest"],
            "compiled_clip": by_role["tank1-pick-compiled-clip"]["sha256"],
            "proxy_asset_manifest": by_role["proxy-asset-manifest"]["sha256"],
            "device_manifest": by_role["device-manifest"]["sha256"],
        },
        "timing": {
            "duration_s": _clean_float(timeline_s),
            "nominal_frame_rate_hz": frame_rate_hz,
            "clock": "offline-compiled-relative-time",
        },
        "coverage": {
            "total_motion_segments": len(segments),
            "playable_segments": len(segments),
            "compiled_move_l_segments": sum(
                segment["motion"] == "move_l" for segment in segments
            ),
            "nominal_move_j_segments": sum(
                segment["motion"] == "move_j" for segment in segments
            ),
            "cp_unresolved_playable_segments": cp_segment_count,
            "total_frame_count": total_frame_count,
            "compiled_move_l_frame_count": move_l_frame_count,
            "payload_attached_frame_count": attachment_frame_count,
        },
        "attachment_models": [
            {
                "attachment_id": "tool:TOOL_SUCTION",
                "kind": "tool",
                "geometry_source": "proxy:tool_suction",
                "dimensions_m": [_clean_float(value) for value in tool_dimensions],
                "placement_source": "calibration.physical_tool_mount",
            },
            {
                "attachment_id": "payload:plate",
                "kind": "payload",
                "geometry_source": f"device-manifest:{plate_spec['installed']}",
                "dimensions_m": [_clean_float(value) for value in payload_dimensions],
                "placement_source": "controller-tool-1-tcp-contact-plane-candidate",
            },
        ],
        "segments": segments,
        "limitations": [
            "offline-playback-not-live-controller-state",
            "move-j-timing-and-easing-are-visualization-approximations",
            "cp-blend-controller-semantics-unresolved",
            "controller-joint-wrap-selection-unresolved",
            "tool-proxy-mounted-from-candidate-calibration-not-field-collision-model",
            "payload-pose-uses-tool-tcp-contact-plane-candidate",
            "tool-rotary-actuator-fixed-at-compiled-clip-home-state",
            "collision-and-stop-qualification-false",
        ],
    }
    playback["playback_digest"] = _document_digest(playback)
    return playback


def compile_ptlc_tank1_environment_collision(
    repo_root: Path,
    lock: Mapping[str, Any],
    scene: Mapping[str, Any],
    link_states: Mapping[str, Any],
    playback: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate sampled robot/tool/payload geometry against proxy components.

    The calculation uses an evidence-derived candidate transform from the CR5
    full-machine frame into the historical L/N/Z proxy layout. Generated box
    components receive triangle-vs-box narrow phase. Shaped proxy components
    remain broad-phase only. The result is diagnostic and has no runtime effect.
    """

    product = _product(config, "ptlc_tank1_environment_collision")
    sample_id = _text(
        product.get("sample_id"), "environment collision product.sample_id"
    )
    if (
        sample_id != scene["sample_id"]
        or sample_id != link_states["sample_id"]
        or sample_id != playback["sample_id"]
    ):
        raise SpatialCompileError("environment collision sample 与输入产物不一致")
    exact_box_assets = set(
        _text_list(product.get("exact_box_assets"), "exact_box_assets")
    )
    compound_convex_assets = set(
        _text_list(product.get("compound_convex_assets"), "compound_convex_assets")
    )
    cache_key = (
        str(repo_root),
        _text(lock.get("lock_digest"), "lock_digest"),
        _text(scene.get("scene_digest"), "scene_digest"),
        _text(link_states.get("sequence_digest"), "sequence_digest"),
        _text(playback.get("playback_digest"), "playback_digest"),
        _document_digest(dict(product)),
    )
    cached = _ENVIRONMENT_COLLISION_CACHE.get(cache_key)
    if cached is not None:
        return deepcopy(cached)
    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    rail_analysis = _mapping(
        _read_json(_repo_file(repo_root, by_role["rail-frame-layout-analysis"]["path"])),
        "rail frame layout analysis",
    )
    rail_fit = _mapping(rail_analysis.get("rail_fit"), "rail_analysis.rail_fit")
    common = _mapping(
        rail_fit.get("common_frame_equation"), "rail_fit.common_frame_equation"
    )
    l_axis = _vec3(rail_fit.get("l_axis_unit_in_controller_xyz"), "rail l axis")
    n_axis = _vec3(rail_fit.get("n_axis_unit_in_controller_xyz"), "rail n axis")
    if abs(sum(a * b for a, b in zip(l_axis, n_axis, strict=True))) > 1e-6:
        raise SpatialCompileError("rail L/N 轴不正交")
    scale = rail_fit.get("fitted_scale_mm_translation_per_mm_command")
    reference_q = common.get("reference_q_mm")
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in (scale, reference_q)
    ):
        raise SpatialCompileError("rail common frame 参数无效")
    base_registration = _mapping(
        link_states["kinematic_model"]["base_registration"], "base registration"
    )
    target_q = base_registration.get("target_rail_position_mm")
    if not isinstance(target_q, (int, float)) or isinstance(target_q, bool):
        raise SpatialCompileError("base registration target rail position 无效")
    base_matrix = _matrix4(
        base_registration.get("matrix_robot_base_to_world"), "base registration matrix"
    )
    if any(
        abs(base_matrix[row][column] - (1.0 if row == column else 0.0)) > 1e-9
        for row in range(3)
        for column in range(3)
    ):
        raise SpatialCompileError("v0 environment registration 仅支持当前无旋转 robot base")
    rail_entity = next(
        (
            entity
            for entity in scene["entities"]
            if entity.get("entity_id") == "ptlc.proxy:rail_11y"
        ),
        None,
    )
    if not isinstance(rail_entity, Mapping):
        raise SpatialCompileError("collision scene 缺 ptlc.proxy:rail_11y")
    rail_top_z = _vec3(
        _mapping(rail_entity.get("world_aabb"), "rail world aabb").get("max_m"),
        "rail world aabb.max_m",
    )[2]
    rail_delta_m = float(scale) * (float(target_q) - float(reference_q)) / 1000.0
    rotation = [
        [l_axis[0], l_axis[1], 0.0],
        [n_axis[0], n_axis[1], 0.0],
        [0.0, 0.0, 1.0],
    ]
    base_xyz = [base_matrix[index][3] for index in range(3)]
    translation = [
        rail_delta_m - rotation[0][0] * base_xyz[0] - rotation[0][1] * base_xyz[1],
        -rotation[1][0] * base_xyz[0] - rotation[1][1] * base_xyz[1],
        rail_top_z - base_xyz[2],
    ]
    registration_matrix = [
        [*rotation[0], translation[0]],
        [*rotation[1], translation[1]],
        [*rotation[2], translation[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]

    expected_exact_assets = {
        "machine_deck",
        "rail_11y",
        "tool_station",
        "feed_lift",
        "sampling_station",
        "photo_scrape_station",
        "group_rack_4x3",
        "staging_a_6slot",
        "staging_b_6slot",
    }
    if exact_box_assets != expected_exact_assets:
        raise SpatialCompileError("exact_box_assets 必须精确匹配 v0 box 白名单")
    if compound_convex_assets != {"develop_tank_rack"}:
        raise SpatialCompileError("compound_convex_assets 必须精确匹配 v0 凸体白名单")
    if exact_box_assets & compound_convex_assets:
        raise SpatialCompileError("box 与 compound-convex 白名单不能重叠")
    environment_components: list[dict[str, Any]] = []
    exact_box_component_count = 0
    compound_convex_component_count = 0
    broad_only_component_count = 0
    for entity in scene["entities"]:
        if not isinstance(entity, Mapping):
            raise SpatialCompileError("collision scene entity 必须是对象")
        entity_id = _text(entity.get("entity_id"), "scene entity_id")
        asset_id = entity_id.removeprefix("ptlc.proxy:")
        if asset_id == "tool_suction":
            continue
        pose = _mapping(entity.get("pose_world"), f"{entity_id}.pose_world")
        pose_matrix = _transform_matrix(
            _vec3(pose.get("xyz_m"), f"{entity_id}.pose xyz"),
            [
                math.radians(value)
                for value in _vec3(pose.get("rpy_deg"), f"{entity_id}.pose rpy")
            ],
        )
        if asset_id in exact_box_assets:
            geometry_path = _relative_path(
                entity.get("geometry_path"), f"{entity_id}.geometry_path"
            )
            geometry = _repo_file(repo_root, geometry_path)
            if _sha256(geometry) != entity.get("geometry_sha256"):
                raise SpatialCompileError(f"{entity_id} collision mesh digest 不一致")
            if entity.get("geometry_format") != "stl" or entity.get("geometry_unit") != "mm":
                raise SpatialCompileError(f"{entity_id} box collision geometry 必须是毫米制 STL")
            triangles = _binary_stl_triangles(geometry, scale=0.001)
            component_bounds = _connected_triangle_component_aabbs(triangles)
            if len(component_bounds) != int(entity.get("component_count", -1)):
                raise SpatialCompileError(
                    f"{entity_id} component 数与 scene/QC 不一致"
                )
            for component_index, bounds in enumerate(component_bounds):
                world_aabb = _matrix_transformed_aabb(
                    bounds["min_m"], bounds["max_m"], pose_matrix
                )
                environment_components.append(
                    {
                        "component_id": f"{entity_id}:component:{component_index}",
                        "entity_id": entity_id,
                        "asset_id": asset_id,
                        "narrow_phase": "triangle-vs-generated-box",
                        "world_aabb": world_aabb,
                    }
                )
                exact_box_component_count += 1
        elif asset_id in compound_convex_assets:
            if entity.get("collision_mode") != "compound-convex":
                raise SpatialCompileError(f"{entity_id} 未绑定 compound-convex representation")
            if entity.get("geometry_format") != "stl" or entity.get("geometry_unit") != "m":
                raise SpatialCompileError(f"{entity_id} compound-convex 必须是米制 STL")
            geometry_path = _relative_path(
                entity.get("geometry_path"), f"{entity_id}.geometry_path"
            )
            geometry = _repo_file(repo_root, geometry_path)
            if _sha256(geometry) != entity.get("geometry_sha256"):
                raise SpatialCompileError(f"{entity_id} collision mesh digest 不一致")
            local_components = _split_triangles_by_counts(
                _binary_stl_triangles(geometry, scale=1.0),
                entity.get("component_triangle_counts"),
            )
            if len(local_components) != int(entity.get("component_count", -1)):
                raise SpatialCompileError(
                    f"{entity_id} compound-convex component 数与 scene/QC 不一致"
                )
            for component_index, local_triangles in enumerate(local_components):
                world_triangles = [
                    [_transform_point(pose_matrix, point) for point in triangle]
                    for triangle in local_triangles
                ]
                environment_components.append(
                    {
                        "component_id": f"{entity_id}:component:{component_index}",
                        "entity_id": entity_id,
                        "asset_id": asset_id,
                        "narrow_phase": "triangle-vs-compound-convex",
                        "world_aabb": _triangle_bounds(world_triangles),
                        "convex_planes": _convex_component_planes(world_triangles),
                    }
                )
                compound_convex_component_count += 1
        else:
            environment_components.append(
                {
                    "component_id": f"{entity_id}:broad-phase",
                    "entity_id": entity_id,
                    "asset_id": asset_id,
                    "narrow_phase": "unsupported-shaped-proxy",
                    "world_aabb": dict(entity["world_aabb"]),
                }
            )
            broad_only_component_count += 1

    link_triangles = {
        item["link_id"]: _binary_stl_triangles(
            _repo_file(repo_root, item["geometry_path"]), scale=1.0
        )
        for item in link_states["geometry"]
    }
    attachment_models = {
        item["attachment_id"]: item for item in playback["attachment_models"]
    }
    tool_dimensions = _vec3(
        attachment_models["tool:TOOL_SUCTION"]["dimensions_m"], "tool dimensions"
    )
    payload_dimensions = _vec3(
        attachment_models["payload:plate"]["dimensions_m"], "payload dimensions"
    )
    attachment_triangles = {
        "tool:TOOL_SUCTION": _box_triangles(
            [-tool_dimensions[0] / 2.0, -tool_dimensions[1] / 2.0, -tool_dimensions[2]],
            [tool_dimensions[0] / 2.0, tool_dimensions[1] / 2.0, 0.0],
        ),
        "payload:plate": _box_triangles(
            [-payload_dimensions[0] / 2.0, -payload_dimensions[1] / 2.0, -payload_dimensions[2]],
            [payload_dimensions[0] / 2.0, payload_dimensions[1] / 2.0, 0.0],
        ),
    }

    frame_results: list[dict[str, Any]] = []
    exact_contact_frame_count = 0
    broad_only_frame_count = 0
    event_count = 0
    first_event: dict[str, Any] | None = None
    global_min_clearance = math.inf
    structural_exclusions = {
        ("base_link", "machine_deck"),
        ("base_link", "rail_11y"),
    }
    for segment in playback["segments"]:
        segment_index = int(segment["segment_index"])
        for frame in segment["frames"]:
            moving: list[dict[str, Any]] = []
            for link in frame["links"]:
                link_id = _text(link.get("link_id"), "playback link_id")
                matrix = _matmul4(
                    registration_matrix,
                    _matrix4(link["matrix_link_to_world"], f"{link_id} playback matrix"),
                )
                geometry_item = next(
                    item for item in link_states["geometry"] if item["link_id"] == link_id
                )
                local = geometry_item["local_aabb"]
                moving.append(
                    {
                        "object_id": link_id,
                        "kind": "robot-link",
                        "matrix": matrix,
                        "world_aabb": _matrix_transformed_aabb(
                            local["min_m"], local["max_m"], matrix
                        ),
                        "triangles": link_triangles[link_id],
                    }
                )
            for attachment in frame["attachments"]:
                attachment_id = _text(
                    attachment.get("attachment_id"), "playback attachment_id"
                )
                matrix = _matmul4(
                    registration_matrix,
                    _matrix4(
                        attachment["matrix_attachment_to_world"],
                        f"{attachment_id} playback matrix",
                    ),
                )
                triangles = attachment_triangles[attachment_id]
                moving.append(
                    {
                        "object_id": attachment_id,
                        "kind": attachment["kind"],
                        "matrix": matrix,
                        "world_aabb": _triangle_bounds(
                            [
                                [_transform_point(matrix, point) for point in triangle]
                                for triangle in triangles
                            ]
                        ),
                        "triangles": triangles,
                    }
                )

            minimum_clearance = math.inf
            closest_pair: dict[str, Any] | None = None
            broad_overlaps: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for moving_object in moving:
                for component in environment_components:
                    if (
                        moving_object["object_id"], component["asset_id"]
                    ) in structural_exclusions:
                        continue
                    clearance = _aabb_distance(
                        moving_object["world_aabb"], component["world_aabb"]
                    )
                    if clearance < minimum_clearance:
                        minimum_clearance = clearance
                        closest_pair = {
                            "moving_object_id": moving_object["object_id"],
                            "environment_component_id": component["component_id"],
                        }
                    if clearance <= 1e-12:
                        broad_overlaps.append((moving_object, component))
            if not math.isfinite(minimum_clearance) or closest_pair is None:
                raise SpatialCompileError("environment collision frame 没有可评估 pair")
            global_min_clearance = min(global_min_clearance, minimum_clearance)

            exact_contacts: list[dict[str, Any]] = []
            transformed_cache: dict[str, list[list[list[float]]]] = {}
            unresolved_overlap_count = 0
            for moving_object, component in broad_overlaps:
                if component["narrow_phase"] == "unsupported-shaped-proxy":
                    unresolved_overlap_count += 1
                    continue
                object_id = moving_object["object_id"]
                transformed = transformed_cache.get(object_id)
                if transformed is None:
                    transformed = [
                        [
                            _transform_point(moving_object["matrix"], point)
                            for point in triangle
                        ]
                        for triangle in moving_object["triangles"]
                    ]
                    transformed_cache[object_id] = transformed
                contact_point: list[float] | None = None
                contact_method: str
                for triangle in transformed:
                    if not _triangle_aabb_overlaps(triangle, component["world_aabb"]):
                        continue
                    if component["narrow_phase"] == "triangle-vs-generated-box" and _triangle_intersects_aabb(
                        triangle, component["world_aabb"]
                    ):
                        centroid = [
                            sum(point[axis] for point in triangle) / 3.0
                            for axis in range(3)
                        ]
                        contact_point = _clamp_point_to_aabb(
                            centroid, component["world_aabb"]
                        )
                        contact_method = "triangle-vs-generated-box-sat"
                        break
                    if component["narrow_phase"] == "triangle-vs-compound-convex":
                        contact_point = _triangle_intersects_convex_polyhedron(
                            triangle, component["convex_planes"]
                        )
                        if contact_point is not None:
                            contact_method = "triangle-vs-compound-convex-clipping"
                            break
                    elif component["narrow_phase"] != "triangle-vs-generated-box":
                        raise SpatialCompileError(
                            f"未知 environment narrow phase: {component['narrow_phase']}"
                        )
                if contact_point is not None:
                    contact = {
                        "moving_object_id": object_id,
                        "moving_kind": moving_object["kind"],
                        "environment_entity_id": component["entity_id"],
                        "environment_component_id": component["component_id"],
                        "position_m": [_clean_float(value) for value in contact_point],
                        "method": contact_method,
                    }
                    exact_contacts.append(contact)
                    event_count += 1
            if exact_contacts:
                status = "proxy-mesh-contact"
                exact_contact_frame_count += 1
            elif broad_overlaps:
                status = "broad-phase-overlap-unresolved"
                broad_only_frame_count += 1
            else:
                status = "separated-at-sampled-frame"
            result = {
                "segment_index": segment_index,
                "frame_index": int(frame["frame_index"]),
                "time_s": float(frame["time_s"]),
                "status": status,
                "minimum_aabb_clearance_m": _clean_float(minimum_clearance),
                "closest_pair": closest_pair,
                "broad_overlap_pair_count": len(broad_overlaps),
                "unresolved_shaped_overlap_pair_count": unresolved_overlap_count,
                "exact_contacts": exact_contacts,
            }
            frame_results.append(result)
            if first_event is None and exact_contacts:
                first_event = {
                    "segment_index": segment_index,
                    "frame_index": int(frame["frame_index"]),
                    "time_s": float(frame["time_s"]),
                    **exact_contacts[0],
                }

    collision: dict[str, Any] = {
        "schema": ENVIRONMENT_COLLISION_SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": playback["action_contract_id"],
        "mode": "shadow",
        "effect": "none",
        "qualification": "candidate-proxy-sampled",
        "world_frame": dict(scene["world_frame"]),
        "source_digests": {
            "test_lock": lock["lock_digest"],
            "collision_scene": scene["scene_digest"],
            "link_state_sequence": link_states["sequence_digest"],
            "playback": playback["playback_digest"],
            "rail_frame_layout_analysis": by_role["rail-frame-layout-analysis"]["sha256"],
        },
        "registration": {
            "status": "candidate-relative-layout",
            "source_frame_id": link_states["world_frame"]["frame_id"],
            "target_frame_id": scene["world_frame"]["frame_id"],
            "method": "rail-lnz-fit-plus-rail-top-contact",
            "matrix_source_to_target": _clean_matrix(registration_matrix),
            "rail_fit_xy_rms_mm": float(rail_fit["fit_residuals"]["xy_rms_mm"]),
            "rail_fit_xy_max_mm": float(rail_fit["fit_residuals"]["xy_max_mm"]),
            "world_rigid_transform_qualified": False,
        },
        "method": {
            "broad_phase": "sampled-frame-aabb-distance",
            "narrow_phase": "robot-triangle-vs-mixed-box-and-compound-convex",
            "unsupported_proxy_policy": "retain-broad-phase-unresolved",
            "structural_exclusions": [
                "base_link-vs-machine_deck",
                "base_link-vs-rail_11y",
                "mounted-tool_suction-removed-from-storage-pose",
            ],
        },
        "coverage": {
            "segment_count": len(playback["segments"]),
            "evaluated_frame_count": len(frame_results),
            "environment_component_count": len(environment_components),
            "exact_box_component_count": exact_box_component_count,
            "compound_convex_component_count": compound_convex_component_count,
            "broad_only_component_count": broad_only_component_count,
            "exact_contact_frame_count": exact_contact_frame_count,
            "broad_only_overlap_frame_count": broad_only_frame_count,
            "exact_contact_event_count": event_count,
        },
        "summary": {
            "result": "proxy-contact-observed" if first_event else "no-proxy-contact-at-samples",
            "minimum_aabb_clearance_m": _clean_float(global_min_clearance),
            "first_contact": first_event,
        },
        "frames": frame_results,
        "limitations": [
            "candidate-registration-world-rigid-transform-not-surveyed",
            "historical-photo-and-point-derived-environment-proxies",
            "mixed-parametric-box-and-source-glb-compound-convex-narrow-phase",
            "compound-convex-surface-test-does-not-detect-full-containment-without-surface-crossing",
            "shaped-environment-proxies-remain-broad-phase-only",
            "sampled-frame-collision-can-miss-between-frame-contact",
            "cp-and-controller-interpolation-unverified",
            "tool-and-payload-collision-geometries-are-candidate-proxies",
            "stop-and-recovery-envelopes-missing",
            "collision-qualified-false",
        ],
    }
    collision["collision_digest"] = _document_digest(collision)
    _ENVIRONMENT_COLLISION_CACHE[cache_key] = deepcopy(collision)
    return collision


def compile_ptlc_tank1_motion_corridor(
    repo_root: Path,
    lock: Mapping[str, Any],
    motion: Mapping[str, Any],
    link_states: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Sample only unblended move_j segments into a partial diagnostic AABB corridor."""

    product = _product(config, "ptlc_tank1_motion_corridor")
    sample_id = _text(product.get("sample_id"), "corridor product.sample_id")
    if sample_id != motion["sample_id"] or sample_id != link_states["sample_id"]:
        raise SpatialCompileError("corridor sample 与输入产物 sample 不一致")
    max_joint_delta_deg = product.get("max_joint_delta_deg")
    if (
        not isinstance(max_joint_delta_deg, (int, float))
        or isinstance(max_joint_delta_deg, bool)
        or not math.isfinite(max_joint_delta_deg)
        or max_joint_delta_deg <= 0
    ):
        raise SpatialCompileError("max_joint_delta_deg 必须是正有限数")
    max_joint_delta_deg = float(max_joint_delta_deg)
    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    calibration = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["robot-calibration"]["path"])),
        "robot calibration",
    )
    chain, parsed_geometry = _load_cr5_chain_and_geometry(repo_root, by_role, calibration)
    geometry = {item["link_id"]: item for item in parsed_geometry}
    base_world = _matrix4(
        link_states["kinematic_model"]["base_registration"]["matrix_robot_base_to_world"],
        "link-state base registration",
    )
    endpoint_states = {state["state_id"]: state for state in link_states["states"]}
    source_state = endpoint_states["anchor:P1"]
    segments: list[dict[str, Any]] = []
    sampled_world_aabbs: list[dict[str, list[float]]] = []
    sampled_count = 0
    excluded_cp_count = 0
    excluded_move_l_count = 0
    for step in motion["steps"]:
        if step["kind"] != "robot-motion":
            continue
        target_state = endpoint_states[_waypoint_state_id(step)]
        segment: dict[str, Any] = {
            "segment_index": len(segments),
            "source_state_id": source_state["state_id"],
            "target_state_id": target_state["state_id"],
            "target_step_index": int(step["index"]),
            "phase": step["phase"],
            "payload_state": step["payload_state_after"],
            "motion": step["motion"],
            "cp": float(step["cp"]),
        }
        if step["motion"] == "move_l":
            segment.update(
                {
                    "status": "excluded-unresolved",
                    "reason_codes": ["controller-cartesian-interpolation-unresolved"],
                }
            )
            excluded_move_l_count += 1
        elif abs(float(step["cp"])) > 1e-12:
            segment.update(
                {
                    "status": "excluded-unresolved",
                    "reason_codes": ["cp-blend-unresolved"],
                }
            )
            excluded_cp_count += 1
        else:
            start_joint = _vec6(
                source_state["controller_joint_deg"], "corridor source joint"
            )
            target_joint = _vec6(
                target_state["controller_joint_deg"], "corridor target joint"
            )
            maximum_delta = max(
                abs(end - start) for start, end in zip(start_joint, target_joint, strict=True)
            )
            interval_count = max(1, int(math.ceil(maximum_delta / max_joint_delta_deg)))
            parameters = [index / interval_count for index in range(interval_count + 1)]
            per_link_aabbs: dict[str, list[dict[str, list[float]]]] = {
                link_id: [] for link_id in geometry
            }
            for fraction in parameters:
                joints = [
                    start + (end - start) * fraction
                    for start, end in zip(start_joint, target_joint, strict=True)
                ]
                matrices, _ = _fk_link_matrices(joints, calibration, chain, base_world)
                for link_id, matrix in matrices.items():
                    local = geometry[link_id]["local_aabb"]
                    per_link_aabbs[link_id].append(
                        _matrix_transformed_aabb(local["min_m"], local["max_m"], matrix)
                    )
            link_corridors = [
                {
                    "link_id": link_id,
                    "sampled_aabb_union": _union_aabbs(per_link_aabbs[link_id]),
                }
                for link_id in ("base_link", *(f"Link{index}" for index in range(1, 7)))
            ]
            segment_aabb = _union_aabbs(
                [item["sampled_aabb_union"] for item in link_corridors]
            )
            sampled_world_aabbs.append(segment_aabb)
            segment.update(
                {
                    "status": "sampled-candidate",
                    "reason_codes": ["discrete-aabb-union-candidate-only"],
                    "sample_count": len(parameters),
                    "sample_parameters": [_clean_float(value) for value in parameters],
                    "max_joint_delta_observed_deg": _clean_float(
                        maximum_delta / interval_count
                    ),
                    "link_corridors": link_corridors,
                    "segment_world_aabb": segment_aabb,
                }
            )
            sampled_count += 1
        segments.append(segment)
        source_state = target_state
    if sampled_count == 0:
        raise SpatialCompileError("corridor 没有可采样的 move_j/cp=0 segment")
    corridor: dict[str, Any] = {
        "schema": CORRIDOR_SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": motion["action_contract_id"],
        "mode": "shadow",
        "qualification": "candidate-partial",
        "world_frame": dict(link_states["world_frame"]),
        "source_digests": {
            "motion_contract": motion["contract_digest"],
            "link_state_sequence": link_states["sequence_digest"],
        },
        "sampling": {
            "method": "adaptive-linear-joint-space-by-max-joint-delta",
            "max_joint_delta_deg": max_joint_delta_deg,
            "endpoint_policy": "include-both",
            "eligible_segment_rule": "move_j-and-cp-equals-zero",
        },
        "coverage": {
            "total_motion_segments": len(segments),
            "sampled_move_j_segments": sampled_count,
            "excluded_move_j_cp_segments": excluded_cp_count,
            "excluded_move_l_segments": excluded_move_l_count,
        },
        "segments": segments,
        "partial_world_aabb": _union_aabbs(sampled_world_aabbs),
        "limitations": [
            "partial-corridor-excludes-move-l-and-cp-segments",
            "discrete-aabb-union-is-not-continuous-swept-volume",
            "controller-joint-wrap-selection-unresolved",
            "full-machine-gltf-registration-not-proxy-collision-scene-frame",
            "dynamic-tool-and-payload-geometry-missing",
            "continuous-collision-published-as-separate-candidate-artifact",
            "stop-model-missing",
            "qualification-candidate-partial-only",
        ],
    }
    corridor["corridor_digest"] = _document_digest(corridor)
    return corridor


def compile_ptlc_tank1_continuous_collision_candidate(
    repo_root: Path,
    lock: Mapping[str, Any],
    motion: Mapping[str, Any],
    link_states: Mapping[str, Any],
    corridor: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Bound continuous link motion for the already eligible linear joint segments.

    The bound is deliberately conservative.  For every sampling subinterval, the
    start AABB is expanded by a configuration-independent upper bound on every
    point's travel.  It can prove broad-phase separation, while overlap remains a
    candidate and never becomes a collision or hardware-safety claim.
    """

    product = _product(config, "ptlc_tank1_motion_corridor")
    sample_id = _text(product.get("sample_id"), "continuous product.sample_id")
    if (
        sample_id != motion["sample_id"]
        or sample_id != link_states["sample_id"]
        or sample_id != corridor["sample_id"]
    ):
        raise SpatialCompileError("continuous collision sample 与输入产物 sample 不一致")
    if corridor.get("world_frame") != link_states.get("world_frame"):
        raise SpatialCompileError("continuous collision 输入 world_frame 不一致")

    locked = _locked_sample(lock, sample_id)
    by_role = _inputs_by_role(locked)
    calibration = _mapping(
        _read_yaml(_repo_file(repo_root, by_role["robot-calibration"]["path"])),
        "robot calibration",
    )
    chain, parsed_geometry = _load_cr5_chain_and_geometry(
        repo_root, by_role, calibration
    )
    geometry = {item["link_id"]: item for item in parsed_geometry}
    base_world = _matrix4(
        link_states["kinematic_model"]["base_registration"][
            "matrix_robot_base_to_world"
        ],
        "continuous collision base registration",
    )
    endpoint_states = {state["state_id"]: state for state in link_states["states"]}
    source_state = endpoint_states["anchor:P1"]
    corridor_segments = {
        int(segment["segment_index"]): segment for segment in corridor["segments"]
    }
    link_order = ("base_link", *(f"Link{index}" for index in range(1, 7)))
    evaluated_world_aabbs: list[dict[str, list[float]]] = []
    segments: list[dict[str, Any]] = []
    evaluated_count = 0
    excluded_cp_count = 0
    excluded_move_l_count = 0
    candidate_pair_total = 0

    for step in motion["steps"]:
        if step["kind"] != "robot-motion":
            continue
        target_state = endpoint_states[_waypoint_state_id(step)]
        segment_index = len(segments)
        corridor_segment = corridor_segments.get(segment_index)
        if corridor_segment is None:
            raise SpatialCompileError(
                f"continuous collision 缺少 corridor segment: {segment_index}"
            )
        segment: dict[str, Any] = {
            "segment_index": segment_index,
            "source_state_id": source_state["state_id"],
            "target_state_id": target_state["state_id"],
            "target_step_index": int(step["index"]),
            "phase": step["phase"],
            "payload_state": step["payload_state_after"],
            "motion": step["motion"],
            "cp": float(step["cp"]),
        }
        if corridor_segment.get("status") != "sampled-candidate":
            reasons = list(corridor_segment.get("reason_codes", []))
            if step["motion"] == "move_l":
                excluded_move_l_count += 1
            else:
                excluded_cp_count += 1
            segment.update(
                {
                    "status": "excluded-unresolved",
                    "reason_codes": reasons,
                }
            )
        else:
            parameters = _number_vector(
                corridor_segment.get("sample_parameters"),
                int(corridor_segment["sample_count"]),
                f"corridor segment {segment_index} sample_parameters",
            )
            if parameters[0] != 0.0 or parameters[-1] != 1.0 or any(
                right <= left for left, right in zip(parameters, parameters[1:])
            ):
                raise SpatialCompileError(
                    f"corridor segment {segment_index} sample_parameters 必须从 0 严格递增到 1"
                )
            start_joint = _vec6(
                source_state["controller_joint_deg"], "continuous source joint"
            )
            target_joint = _vec6(
                target_state["controller_joint_deg"], "continuous target joint"
            )
            interval_bounds = _continuous_interval_link_bounds(
                start_joint=start_joint,
                target_joint=target_joint,
                parameters=parameters,
                calibration=calibration,
                chain=chain,
                geometry=geometry,
                base_world=base_world,
            )
            link_envelopes: list[dict[str, Any]] = []
            for link_id in link_order:
                link_bounds = [interval[link_id]["aabb"] for interval in interval_bounds]
                link_envelopes.append(
                    {
                        "link_id": link_id,
                        "conservative_aabb_union": _union_aabbs(link_bounds),
                        "max_subinterval_displacement_bound_m": _clean_float(
                            max(
                                interval[link_id]["displacement_bound_m"]
                                for interval in interval_bounds
                            )
                        ),
                    }
                )
            pair_results: list[dict[str, Any]] = []
            for left_index, left_id in enumerate(link_order):
                for right_index in range(left_index + 2, len(link_order)):
                    right_id = link_order[right_index]
                    candidate_intervals = [
                        interval_index
                        for interval_index, interval in enumerate(interval_bounds)
                        if _aabb_overlaps(
                            interval[left_id]["aabb"], interval[right_id]["aabb"]
                        )
                    ]
                    result = (
                        "candidate-overlap"
                        if candidate_intervals
                        else "separated-by-conservative-aabb"
                    )
                    if candidate_intervals:
                        candidate_pair_total += 1
                    pair_results.append(
                        {
                            "link_a": left_id,
                            "link_b": right_id,
                            "result": result,
                            "candidate_interval_indices": candidate_intervals,
                        }
                    )
            segment_world_aabb = _union_aabbs(
                [item["conservative_aabb_union"] for item in link_envelopes]
            )
            evaluated_world_aabbs.append(segment_world_aabb)
            candidate_count = sum(
                item["result"] == "candidate-overlap" for item in pair_results
            )
            segment.update(
                {
                    "status": "continuous-broad-phase-candidate",
                    "reason_codes": sorted(
                        {
                            "linear-joint-interpolation-conservative-bound",
                            "self-collision-broad-phase-only",
                            *(
                                ["self-collision-candidate-overlap"]
                                if candidate_count
                                else []
                            ),
                        }
                    ),
                    "interval_count": len(interval_bounds),
                    "link_envelopes": link_envelopes,
                    "self_collision": {
                        "evaluated_pair_count": len(pair_results),
                        "separated_pair_count": len(pair_results) - candidate_count,
                        "candidate_overlap_pair_count": candidate_count,
                        "pairs": pair_results,
                    },
                    "segment_world_aabb": segment_world_aabb,
                }
            )
            evaluated_count += 1
        segments.append(segment)
        source_state = target_state

    if evaluated_count == 0:
        raise SpatialCompileError("continuous collision 没有可评估 segment")
    candidate: dict[str, Any] = {
        "schema": CONTINUOUS_COLLISION_SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": motion["action_contract_id"],
        "mode": "shadow",
        "qualification": "candidate-partial",
        "world_frame": dict(link_states["world_frame"]),
        "source_digests": {
            "motion_contract": motion["contract_digest"],
            "link_state_sequence": link_states["sequence_digest"],
            "motion_corridor": corridor["corridor_digest"],
        },
        "method": {
            "interpolation_assumption": "linear-controller-joint-space",
            "bound": "per-subinterval-link-aabb-expanded-by-summed-joint-arc-length",
            "eligible_segment_rule": "move_j-and-cp-equals-zero",
            "self_collision_pair_rule": "exclude-identical-and-adjacent-links",
        },
        "coverage": {
            "total_motion_segments": len(segments),
            "continuous_evaluated_move_j_segments": evaluated_count,
            "excluded_move_j_cp_segments": excluded_cp_count,
            "excluded_move_l_segments": excluded_move_l_count,
        },
        "segments": segments,
        "partial_world_aabb": _union_aabbs(evaluated_world_aabbs),
        "analysis": {
            "continuous_link_bound_status": "computed-conservative-partial",
            "self_collision_status": (
                "candidate-overlap" if candidate_pair_total else "broad-phase-separated"
            ),
            "environment_collision_status": "not-evaluated-frame-unregistered",
            "overall_result": "unknown",
        },
        "limitations": [
            "partial-analysis-excludes-move-l-and-cp-segments",
            "controller-interpolation-assumption-not-verified-on-hardware",
            "aabb-overlap-is-candidate-not-exact-collision",
            "adjacent-link-collision-not-evaluated",
            "environment-frame-registration-unqualified",
            "dynamic-tool-and-payload-geometry-missing",
            "stop-and-recovery-envelopes-missing",
            "not-bound-into-v0-occupancy-certificate",
            "qualification-candidate-partial-only",
        ],
    }
    candidate["candidate_digest"] = _document_digest(candidate)
    return candidate


def _continuous_interval_link_bounds(
    *,
    start_joint: Sequence[float],
    target_joint: Sequence[float],
    parameters: Sequence[float],
    calibration: Mapping[str, Any],
    chain: Sequence[Mapping[str, Any]],
    geometry: Mapping[str, Mapping[str, Any]],
    base_world: Sequence[Sequence[float]],
) -> list[dict[str, dict[str, Any]]]:
    """Return conservative per-link AABBs for each linear joint subinterval."""

    start = _vec6(start_joint, "continuous interval start")
    target = _vec6(target_joint, "continuous interval target")
    values = _number_vector(parameters, len(parameters), "continuous parameters")
    if len(values) < 2:
        raise SpatialCompileError("continuous parameters 至少需要两个端点")
    origin_lengths = [
        math.sqrt(
            sum(
                value * value
                for value in _vec3(spec.get("origin_xyz_m"), "joint origin")
            )
        )
        for spec in chain
    ]
    local_radii: dict[str, float] = {}
    for link_id, item in geometry.items():
        local = _mapping(item.get("local_aabb"), f"{link_id}.local_aabb")
        low = _vec3(local.get("min_m"), f"{link_id}.local_aabb.min_m")
        high = _vec3(local.get("max_m"), f"{link_id}.local_aabb.max_m")
        local_radii[link_id] = max(
            math.sqrt(x * x + y * y + z * z)
            for x in (low[0], high[0])
            for y in (low[1], high[1])
            for z in (low[2], high[2])
        )

    intervals: list[dict[str, dict[str, Any]]] = []
    for left, right in zip(values, values[1:]):
        left_joint = [
            begin + (end - begin) * left
            for begin, end in zip(start, target, strict=True)
        ]
        right_joint = [
            begin + (end - begin) * right
            for begin, end in zip(start, target, strict=True)
        ]
        matrices, _ = _fk_link_matrices(left_joint, calibration, chain, base_world)
        interval: dict[str, dict[str, Any]] = {}
        for link_index, link_id in enumerate(
            ("base_link", *(f"Link{index}" for index in range(1, 7)))
        ):
            local = geometry[link_id]["local_aabb"]
            start_aabb = _matrix_transformed_aabb(
                local["min_m"], local["max_m"], matrices[link_id]
            )
            displacement = 0.0
            if link_index > 0:
                for joint_index in range(link_index):
                    radius = local_radii[link_id] + sum(
                        origin_lengths[joint_index + 1 : link_index]
                    )
                    displacement += radius * math.radians(
                        abs(right_joint[joint_index] - left_joint[joint_index])
                    )
            interval[link_id] = {
                "aabb": _expand_aabb(start_aabb, displacement),
                "displacement_bound_m": _clean_float(displacement),
            }
        intervals.append(interval)
    return intervals


def compile_initial_certificate(
    lock: Mapping[str, Any],
    scene: Mapping[str, Any],
    motion: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Issue a useful unknown certificate rather than fabricating a safe corridor."""

    product = _product(config, "initial_shadow_decision")
    reason_codes = sorted(_text_list(product.get("reason_codes"), "reason_codes"))
    seed: dict[str, Any] = {
        "schema": CERTIFICATE_SCHEMA,
        "sample_id": motion["sample_id"],
        "action_contract_id": motion["action_contract_id"],
        "mode": "shadow",
        "qualification": "candidate",
        "input_digests": {
            "test_lock": lock["lock_digest"],
            "collision_scene": scene["scene_digest"],
            "motion_contract": motion["contract_digest"],
        },
        "analysis": {
            "motion_corridor_status": "not-computed",
            "continuous_collision_status": "not-computed",
            "stop_envelope_status": "unknown",
            "recovery_envelope_status": "unknown",
            "result": _text(product.get("decision"), "initial decision"),
            "reason_codes": reason_codes,
        },
    }
    identity = _document_digest(seed)
    certificate = {**seed, "certificate_id": f"spatial-cert:{identity}"}
    certificate["certificate_digest"] = _document_digest(certificate)
    return certificate


def compile_initial_decision(
    certificate: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a no-effect offline shadow decision bound to the candidate certificate."""

    product = _product(config, "initial_shadow_decision")
    seed: dict[str, Any] = {
        "schema": DECISION_SCHEMA,
        "mode": "shadow",
        "effect": "none",
        "sample_id": certificate["sample_id"],
        "action_contract_id": certificate["action_contract_id"],
        "certificate_ref": certificate["certificate_id"],
        "world_snapshot_version": f"offline-lock:{certificate['input_digests']['test_lock']}",
        "decision": _text(product.get("decision"), "initial decision"),
        "reason_codes": sorted(_text_list(product.get("reason_codes"), "reason_codes")),
    }
    identity = _document_digest(seed)
    decision = {**seed, "decision_id": f"spatial-decision:{identity}"}
    decision["decision_digest"] = _document_digest(decision)
    return decision


def validate_artifacts(repo_root: Path, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate every emitted document with the checked-in v0 JSON Schema."""

    schemas = {
        "spatial-test-lock.json": "spatial-test-lock-v0.schema.json",
        "ptlc-collision-scene.json": "spatial-collision-scene-v0.schema.json",
        "ptlc-tank1-motion-contract.json": "motion-contract-v0.schema.json",
        "ptlc-tank1-link-states.json": "spatial-link-state-sequence-v0.schema.json",
        "ptlc-tank1-playback.json": "spatial-playback-trajectory-v0.schema.json",
        "ptlc-tank1-environment-collision.json": "spatial-environment-collision-v0.schema.json",
        "ptlc-tank1-motion-corridor.json": "motion-corridor-v0.schema.json",
        "ptlc-tank1-continuous-collision.json": "continuous-collision-candidate-v0.schema.json",
        "ptlc-tank1-spatial-certificate.json": "spatial-occupancy-certificate-v0.schema.json",
        "ptlc-tank1-shadow-decision.json": "spatial-interlock-decision-v0.schema.json",
    }
    for filename, schema_name in schemas.items():
        schema = _read_json(repo_root / "schemas" / schema_name)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(artifacts[filename]), key=lambda item: list(item.path))
        if errors:
            messages = [f"{list(error.path)}: {error.message}" for error in errors]
            raise SpatialCompileError(f"{filename} schema 校验失败: {'; '.join(messages)}")


def write_artifacts(output_dir: Path, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    """Atomically publish deterministic JSON artifacts after all validation succeeds."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, document in artifacts.items():
        _atomic_write(output_dir / filename, _canonical_json_bytes(document, pretty=True))


def _validate_cross_evidence(repo_root: Path, lock: Mapping[str, Any]) -> None:
    """Check the most important existing cross-file hashes and qualification boundaries."""

    ptlc = _locked_sample(lock, "eit-ptlc-historical-v1")
    ptlc_inputs = _inputs_by_role(ptlc)
    points = _mapping(
        _read_json(_repo_file(repo_root, ptlc_inputs["robot-points"]["path"])),
        "robot points",
    )
    calibration = _mapping(
        _read_yaml(_repo_file(repo_root, ptlc_inputs["robot-calibration"]["path"])),
        "robot calibration",
    )
    reference = _mapping(calibration.get("reference_points"), "calibration.reference_points")
    if points.get("referencePointHash") != reference.get("sha256"):
        raise SpatialCompileError("pTLC robot-points referencePointHash 与 calibration 不一致")
    source_point_path = repo_root / "pTLC_platformUI" / "eit_ptlc" / str(reference.get("file"))
    if _sha256(source_point_path) != reference.get("sha256"):
        raise SpatialCompileError("pTLC 原始控制器点表摘要与 calibration 不一致")
    kinematics = _mapping(calibration.get("kinematics_source"), "kinematics_source")
    if points.get("kinematicsCommit") != kinematics.get("commit"):
        raise SpatialCompileError("pTLC robot-points 与 calibration 的运动学提交不一致")
    action_map = _mapping(
        _read_json(_repo_file(repo_root, ptlc_inputs["action-motion-map"]["path"])),
        "action motion map",
    )
    unresolved = action_map.get("unresolvedActions")
    if not isinstance(unresolved, Mapping) or not unresolved:
        raise SpatialCompileError("pTLC action-motion-map 必须保留 unresolvedActions")

    feeding = _locked_sample(lock, "eit-feeding-station-demo-v1")
    feeding_inputs = _inputs_by_role(feeding)
    receipt = _mapping(
        _read_json(_repo_file(repo_root, feeding_inputs["workbench-preview-receipt"]["path"])),
        "feeding preview receipt",
    )
    receipt_files = _mapping(receipt.get("files"), "feeding receipt.files")
    role_to_receipt = {
        "station-handoff": "station_handoff",
        "decomposition-proposal": "decomposition",
        "station-layout-draft": "layout",
        "coverage-report": "coverage",
        "station-geometry": "geometry",
    }
    for role, receipt_key in role_to_receipt.items():
        declared = _mapping(receipt_files.get(receipt_key), f"receipt.files.{receipt_key}")
        locked_input = feeding_inputs[role]
        if declared.get("sha256") != locked_input["sha256"] or int(
            declared.get("bytes", -1)
        ) != locked_input["bytes"]:
            raise SpatialCompileError(f"feeding receipt 与本地输入漂移: {role}")
    validation = _mapping(
        _read_json(_repo_file(repo_root, feeding_inputs["mac-validation"]["path"])),
        "feeding Mac validation",
    )
    if validation.get("passed") is not True or validation.get("qualification") != "source-input-validated":
        raise SpatialCompileError("feeding Mac P1 validation 未通过")
    if "collision" not in _text_list(
        validation.get("not_qualified_for"), "Mac validation.not_qualified_for"
    ):
        raise SpatialCompileError("feeding Mac validation 必须明确排除 collision")


def _compiled_move_l_endpoints(
    clip: Mapping[str, Any],
    points_document: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> tuple[dict[str, list[float]], set[str]]:
    """Read already compiled move_l endpoints and its explicit stale-joint ledger."""

    if clip.get("schema") != "ptlc.clip/v3" or clip.get("name") != "plate.tank1_pick":
        raise SpatialCompileError("tank1 compiled clip 不是预期的 plate.tank1_pick/v3")
    operation = _mapping(clip.get("operation"), "compiled clip.operation")
    if operation.get("name") != "robot_tank_pick" or _mapping(
        operation.get("inputs"), "compiled clip.operation.inputs"
    ).get("tank_id") != 1:
        raise SpatialCompileError("tank1 compiled clip operation/selector 漂移")
    source = _mapping(clip.get("source"), "compiled clip.source")
    if source.get("referencePointHash") != points_document.get("referencePointHash"):
        raise SpatialCompileError("compiled clip 与 robot-points referencePointHash 不一致")
    kinematics = _mapping(calibration.get("kinematics_source"), "kinematics_source")
    if source.get("kinematicsCommit") != kinematics.get("commit"):
        raise SpatialCompileError("compiled clip 与 calibration kinematics commit 不一致")
    if source.get("calibrationVersion") != calibration.get("version"):
        raise SpatialCompileError("compiled clip 与 calibration version 不一致")
    steps = clip.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        raise SpatialCompileError("compiled clip.steps 必须是数组")
    compiled = _mapping(clip.get("compiled"), "compiled clip.compiled")
    raw_trajectories = _mapping(
        compiled.get("moveLTrajectories"), "compiled clip.moveLTrajectories"
    )
    endpoints: dict[str, list[float]] = {}
    for raw_index, raw_path in raw_trajectories.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError) as error:
            raise SpatialCompileError(f"moveLTrajectories key 非整数: {raw_index!r}") from error
        if index < 0 or index >= len(steps):
            raise SpatialCompileError(f"moveLTrajectories step 越界: {index}")
        if not isinstance(raw_path, Sequence) or isinstance(raw_path, (str, bytes)) or not raw_path:
            raise SpatialCompileError(f"moveLTrajectories[{index}] 必须是非空数组")
        step = _mapping(steps[index], f"compiled clip.steps[{index}]")
        command = _mapping(step.get("do"), f"compiled clip.steps[{index}].do")
        robot_point = _mapping(
            command.get("robot_point"), f"compiled clip.steps[{index}].robot_point"
        )
        if robot_point.get("motion") != "move_l":
            raise SpatialCompileError(f"moveLTrajectories[{index}] 未对应 move_l step")
        point_id = _text(robot_point.get("id"), f"compiled clip.steps[{index}].point id")
        endpoint = _vec6(raw_path[-1], f"moveLTrajectories[{index}].endpoint")
        previous = endpoints.get(point_id)
        if previous is not None and any(
            abs(left - right) > 1e-6 for left, right in zip(previous, endpoint, strict=True)
        ):
            raise SpatialCompileError(f"compiled clip 同一点终点不一致: {point_id}")
        endpoints[point_id] = endpoint
    raw_stale = compiled.get("staleJointPoints", [])
    if not isinstance(raw_stale, Sequence) or isinstance(raw_stale, (str, bytes)):
        raise SpatialCompileError("compiled clip.staleJointPoints 必须是数组")
    stale: set[str] = set()
    for index, raw in enumerate(raw_stale):
        item = _mapping(raw, f"staleJointPoints[{index}]")
        point_id = _text(item.get("point"), f"staleJointPoints[{index}].point")
        residual = item.get("poseVsJointMm")
        if not isinstance(residual, (int, float)) or residual <= 1.0:
            raise SpatialCompileError(f"staleJointPoints[{index}] 残差必须大于 1mm")
        stale.add(point_id)
    return endpoints, stale


def _load_cr5_chain_and_geometry(
    repo_root: Path,
    by_role: Mapping[str, Mapping[str, Any]],
    calibration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Verify the locked URDF/calibration topology and read metre-scale STL bounds."""

    urdf_path = _repo_file(repo_root, by_role["cr5-urdf"]["path"])
    try:
        root = ET.fromstring(urdf_path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise SpatialCompileError(f"无法解析 CR5 URDF: {error}") from error
    links = root.findall("link")
    joints = root.findall("joint")
    if len(links) != 8 or len(joints) != 7:
        raise SpatialCompileError(f"CR5 URDF 拓扑漂移: links={len(links)}, joints={len(joints)}")
    dummy = root.find("joint[@name='dummy_joint']")
    if dummy is None or dummy.get("type") != "fixed" or dummy.find("mimic") is not None:
        raise SpatialCompileError("CR5 dummy_joint 必须是无 mimic 的 fixed joint")
    calibration_joints = calibration.get("joints")
    if not isinstance(calibration_joints, Sequence) or isinstance(
        calibration_joints, (str, bytes)
    ) or len(calibration_joints) != 6:
        raise SpatialCompileError("robot calibration 必须包含 6 个 joints")
    chain: list[dict[str, Any]] = []
    expected_parent = "base_link"
    for index, raw_calibration in enumerate(calibration_joints, start=1):
        spec = dict(_mapping(raw_calibration, f"calibration.joints[{index - 1}]"))
        element = root.find(f"joint[@name='joint{index}']")
        if element is None or element.get("type") != "revolute" or element.find("mimic") is not None:
            raise SpatialCompileError(f"CR5 joint{index} 必须是无 mimic 的 revolute joint")
        parent = element.find("parent")
        child = element.find("child")
        if parent is None or child is None:
            raise SpatialCompileError(f"CR5 joint{index} 缺 parent/child")
        expected_child = f"Link{index}"
        if parent.get("link") != expected_parent or child.get("link") != expected_child:
            raise SpatialCompileError(f"CR5 joint{index} 父子拓扑漂移")
        origin = element.find("origin")
        axis = element.find("axis")
        origin_xyz = _xml_vec3(origin, "xyz", [0.0, 0.0, 0.0], f"joint{index}.origin.xyz")
        origin_rpy = _xml_vec3(origin, "rpy", [0.0, 0.0, 0.0], f"joint{index}.origin.rpy")
        axis_xyz = _xml_vec3(axis, "xyz", [0.0, 0.0, 1.0], f"joint{index}.axis")
        if spec.get("id") != f"J{index}":
            raise SpatialCompileError(f"calibration joint id 漂移: {spec.get('id')!r}")
        _assert_close_vector(origin_xyz, _vec3(spec.get("origin_xyz_m"), "origin_xyz_m"), f"J{index} origin_xyz")
        _assert_close_vector(origin_rpy, _vec3(spec.get("origin_rpy_rad"), "origin_rpy_rad"), f"J{index} origin_rpy")
        _assert_close_vector(axis_xyz, _vec3(spec.get("axis"), "axis"), f"J{index} axis")
        spec["parent_link"] = expected_parent
        spec["child_link"] = expected_child
        chain.append(spec)
        expected_parent = expected_child

    link_roles = {
        "base_link": ("cr5-base-collision", "base_link.STL"),
        **{
            f"Link{index}": (f"cr5-j{index}-collision", f"J{index}.STL")
            for index in range(1, 7)
        },
    }
    geometry: list[dict[str, Any]] = []
    for link_id in ("base_link", *(f"Link{index}" for index in range(1, 7))):
        link = root.find(f"link[@name='{link_id}']")
        if link is None:
            raise SpatialCompileError(f"CR5 URDF 缺 link: {link_id}")
        collisions = link.findall("collision")
        if len(collisions) != 1:
            raise SpatialCompileError(f"{link_id} 必须正好一个 collision")
        collision = collisions[0]
        collision_origin = collision.find("origin")
        if collision_origin is not None:
            _assert_close_vector(
                _xml_vec3(collision_origin, "xyz", [0.0, 0.0, 0.0], f"{link_id}.collision.xyz"),
                [0.0, 0.0, 0.0],
                f"{link_id} collision xyz",
            )
            _assert_close_vector(
                _xml_vec3(collision_origin, "rpy", [0.0, 0.0, 0.0], f"{link_id}.collision.rpy"),
                [0.0, 0.0, 0.0],
                f"{link_id} collision rpy",
            )
        mesh = collision.find("geometry/mesh")
        if mesh is None or mesh.get("scale") is not None:
            raise SpatialCompileError(f"{link_id} collision 必须是无 scale 的单一 mesh")
        role, expected_name = link_roles[link_id]
        filename = _text(mesh.get("filename"), f"{link_id}.mesh.filename")
        if Path(filename).name != expected_name:
            raise SpatialCompileError(f"{link_id} mesh 映射漂移: {filename}")
        locked_input = by_role[role]
        path = _repo_file(repo_root, locked_input["path"])
        triangle_count, low, high = _binary_stl_bounds(path)
        geometry.append(
            {
                "link_id": link_id,
                "geometry_path": locked_input["path"],
                "geometry_sha256": locked_input["sha256"],
                "triangle_count": triangle_count,
                "local_aabb": {"min_m": low, "max_m": high},
            }
        )
    return chain, geometry


def _candidate_robot_base_registration(
    calibration: Mapping[str, Any],
    rig_map: Mapping[str, Any],
    rail_points: Mapping[str, Any],
    target_slot: int,
) -> dict[str, Any]:
    """Shift the calibrated slot-4 full-machine base to a target rail slot, then make Z-up."""

    scene_registration = _mapping(calibration.get("scene_registration"), "scene_registration")
    reference = _mapping(scene_registration.get("reference_rail"), "reference_rail")
    reference_slot = reference.get("slot")
    reference_position_mm = reference.get("position_mm")
    if not isinstance(reference_slot, int) or not isinstance(reference_position_mm, (int, float)):
        raise SpatialCompileError("calibration reference_rail 无效")
    raw_axes = rig_map.get("axes")
    if not isinstance(raw_axes, Sequence) or isinstance(raw_axes, (str, bytes)):
        raise SpatialCompileError("rig_map.axes 必须是数组")
    matches = [
        _mapping(item, "rig_map axis")
        for item in raw_axes
        if isinstance(item, Mapping) and item.get("id") == "axis_11y"
    ]
    if len(matches) != 1:
        raise SpatialCompileError(f"rig_map axis_11y 必须唯一，实际 {len(matches)}")
    axis_spec = matches[0]
    axis = _vec3(axis_spec.get("axis"), "axis_11y.axis")
    sign = axis_spec.get("sign")
    zero_offset_mm = axis_spec.get("zero_offset_mm")
    if not isinstance(sign, (int, float)) or not isinstance(zero_offset_mm, (int, float)):
        raise SpatialCompileError("axis_11y sign/zero_offset_mm 无效")
    if abs(float(zero_offset_mm) - float(reference_position_mm)) > 1e-9:
        raise SpatialCompileError("rig_map rail zero 与 calibration reference rail 不一致")
    raw_positions = rail_points.get("plc_servo")
    if not isinstance(raw_positions, Sequence) or isinstance(raw_positions, (str, bytes)):
        raise SpatialCompileError("rail_points.plc_servo 必须是数组")
    positions: dict[int, float] = {}
    for raw in raw_positions:
        item = _mapping(raw, "rail point")
        slot = item.get("slot")
        value = item.get("value")
        if not isinstance(slot, int) or not isinstance(value, (int, float)):
            raise SpatialCompileError("rail point slot/value 无效")
        positions[slot] = float(value)
    if positions.get(reference_slot) != float(reference_position_mm) or target_slot not in positions:
        raise SpatialCompileError("rail point 表缺 calibration reference 或 target slot")
    base_gltf = _matrix4(
        _mapping(
            scene_registration.get("base_transform_at_reference_rail"),
            "base_transform_at_reference_rail",
        ).get("matrix"),
        "base_transform_at_reference_rail.matrix",
    )
    target_position_mm = positions[target_slot]
    delta_scalar_m = (
        (target_position_mm - float(reference_position_mm)) * float(sign) * 0.001
    )
    shift_gltf = [value * delta_scalar_m for value in axis]
    shifted_gltf = [row[:] for row in base_gltf]
    for index in range(3):
        shifted_gltf[index][3] += shift_gltf[index]
    gltf_to_zup = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    base_zup = _matmul4(gltf_to_zup, shifted_gltf)
    shift_zup = _transform_direction(gltf_to_zup, shift_gltf)
    return {
        "status": "candidate-unqualified",
        "source": "calibration-gltf-reference-plus-rigged-rail-shift",
        "reference_rail_slot": reference_slot,
        "target_rail_slot": target_slot,
        "reference_rail_position_mm": float(reference_position_mm),
        "target_rail_position_mm": target_position_mm,
        "relative_rail_shift_m": [_clean_float(value) for value in shift_zup],
        "matrix_robot_base_to_world": _clean_matrix(base_zup),
    }


def _compile_link_state(
    *,
    state_id: str,
    source_kind: str,
    step_index: int | None,
    point_ref: str,
    phase: str,
    payload_state: str,
    controller_joint_deg: list[float],
    controller_pose: list[float],
    tool: int,
    calibration: Mapping[str, Any],
    chain: Sequence[Mapping[str, Any]],
    geometry: Sequence[Mapping[str, Any]],
    base_world: Sequence[Sequence[float]],
) -> dict[str, Any]:
    world_matrices, model_joint_deg = _fk_link_matrices(
        controller_joint_deg, calibration, chain, base_world
    )
    base_matrices, _ = _fk_link_matrices(
        controller_joint_deg, calibration, chain, _identity4()
    )
    tool_spec = _mapping(
        _mapping(calibration.get("tool_transforms"), "tool_transforms").get(str(tool)),
        f"tool_transforms.{tool}",
    )
    tool_matrix = _transform_matrix(
        _vec3(tool_spec.get("translation_m"), f"tool {tool}.translation"),
        [math.radians(value) for value in _vec3(tool_spec.get("rpy_deg"), f"tool {tool}.rpy")],
    )
    tcp_base = _matmul4(base_matrices["Link6"], tool_matrix)
    controller_position = [value / 1000.0 for value in controller_pose[:3]]
    residual_mm = math.dist([tcp_base[index][3] for index in range(3)], controller_position) * 1000.0
    geometry_by_link = {item["link_id"]: item for item in geometry}
    links = []
    for link_id in ("base_link", *(f"Link{index}" for index in range(1, 7))):
        local = geometry_by_link[link_id]["local_aabb"]
        links.append(
            {
                "link_id": link_id,
                "matrix_link_to_world": _clean_matrix(world_matrices[link_id]),
                "world_aabb": _matrix_transformed_aabb(
                    local["min_m"], local["max_m"], world_matrices[link_id]
                ),
            }
        )
    return {
        "state_id": state_id,
        "source_kind": source_kind,
        "step_index": step_index,
        "point_ref": point_ref,
        "phase": phase,
        "payload_state": payload_state,
        "controller_joint_deg": controller_joint_deg,
        "model_joint_deg": model_joint_deg,
        "tool_1_tcp_validation": {
            "fk_position_base_m": [_clean_float(tcp_base[index][3]) for index in range(3)],
            "controller_position_base_m": [_clean_float(value) for value in controller_position],
            "position_residual_mm": _clean_float(residual_mm),
        },
        "links": links,
    }


def _tcp_position_residual_mm(
    controller_joint_deg: Sequence[float],
    controller_pose: Sequence[float],
    calibration: Mapping[str, Any],
    tool: int,
) -> float:
    calibration_joints = [
        _mapping(item, "calibration joint") for item in calibration.get("joints", [])
    ]
    matrices, _ = _fk_link_matrices(
        controller_joint_deg,
        calibration,
        calibration_joints,
        _identity4(),
    )
    tool_spec = _mapping(
        _mapping(calibration.get("tool_transforms"), "tool_transforms").get(str(tool)),
        f"tool_transforms.{tool}",
    )
    tool_matrix = _transform_matrix(
        _vec3(tool_spec.get("translation_m"), f"tool {tool}.translation"),
        [math.radians(value) for value in _vec3(tool_spec.get("rpy_deg"), f"tool {tool}.rpy")],
    )
    tcp = _matmul4(matrices["Link6"], tool_matrix)
    return math.dist(
        [tcp[index][3] for index in range(3)],
        [float(value) / 1000.0 for value in controller_pose[:3]],
    ) * 1000.0


def _fk_link_matrices(
    controller_joint_deg: Sequence[float],
    calibration: Mapping[str, Any],
    chain: Sequence[Mapping[str, Any]],
    robot_base_to_world: Sequence[Sequence[float]],
) -> tuple[dict[str, list[list[float]]], list[float]]:
    values = _number_vector(controller_joint_deg, 6, "controller joint")
    if len(chain) != 6:
        raise SpatialCompileError("CR5 FK chain 必须有 6 个关节")
    base_transform = _mapping(calibration.get("base_transform"), "base_transform")
    current = _matmul4(
        _matrix4(robot_base_to_world, "robot_base_to_world"),
        _transform_matrix(
            _vec3(base_transform.get("translation_m"), "base_transform.translation_m"),
            [
                math.radians(value)
                for value in _vec3(base_transform.get("rpy_deg"), "base_transform.rpy_deg")
            ],
        ),
    )
    matrices = {"base_link": current}
    model_joint_deg: list[float] = []
    for index, (controller_value, raw_spec) in enumerate(
        zip(values, chain, strict=True), start=1
    ):
        spec = _mapping(raw_spec, f"FK joint {index}")
        sign = float(spec.get("sign", 1.0))
        offset = float(spec.get("zero_offset_deg", 0.0))
        model_value = sign * controller_value + offset
        model_joint_deg.append(_clean_float(model_value))
        origin = _transform_matrix(
            _vec3(spec.get("origin_xyz_m"), f"J{index}.origin_xyz_m"),
            _vec3(spec.get("origin_rpy_rad"), f"J{index}.origin_rpy_rad"),
        )
        rotation = _axis_angle_matrix(
            _vec3(spec.get("axis"), f"J{index}.axis"), math.radians(model_value)
        )
        current = _matmul4(_matmul4(current, origin), rotation)
        matrices[f"Link{index}"] = current
    return matrices, model_joint_deg


def _waypoint_state_id(step: Mapping[str, Any]) -> str:
    return f"step:{int(step['index'])}:{_text(step.get('point_ref'), 'step.point_ref')}"


def _binary_stl_bounds(path: Path) -> tuple[int, list[float], list[float]]:
    payload = path.read_bytes()
    if len(payload) < 84:
        raise SpatialCompileError(f"STL 太短: {path}")
    triangle_count = struct.unpack_from("<I", payload, 80)[0]
    if len(payload) != 84 + triangle_count * 50:
        raise SpatialCompileError(f"STL 不是确定的 binary STL: {path}")
    low = [math.inf, math.inf, math.inf]
    high = [-math.inf, -math.inf, -math.inf]
    for index in range(triangle_count):
        values = struct.unpack_from("<9f", payload, 84 + index * 50 + 12)
        if any(not math.isfinite(value) for value in values):
            raise SpatialCompileError(f"STL 含非有限顶点: {path}")
        for vertex in range(3):
            for axis in range(3):
                value = float(values[vertex * 3 + axis])
                low[axis] = min(low[axis], value)
                high[axis] = max(high[axis], value)
    return triangle_count, [_clean_float(value) for value in low], [
        _clean_float(value) for value in high
    ]


def _binary_stl_triangles(
    path: Path, *, scale: float
) -> list[list[list[float]]]:
    if not math.isfinite(scale) or scale <= 0:
        raise SpatialCompileError("STL scale 必须是正有限数")
    payload = path.read_bytes()
    if len(payload) < 84:
        raise SpatialCompileError(f"STL 太短: {path}")
    triangle_count = struct.unpack_from("<I", payload, 80)[0]
    if len(payload) != 84 + triangle_count * 50:
        raise SpatialCompileError(f"STL 不是确定的 binary STL: {path}")
    triangles: list[list[list[float]]] = []
    for index in range(triangle_count):
        values = struct.unpack_from("<9f", payload, 84 + index * 50 + 12)
        if any(not math.isfinite(value) for value in values):
            raise SpatialCompileError(f"STL 含非有限顶点: {path}")
        triangles.append(
            [
                [float(values[vertex * 3 + axis]) * scale for axis in range(3)]
                for vertex in range(3)
            ]
        )
    return triangles


def _triangle_bounds(
    triangles: Sequence[Sequence[Sequence[float]]],
) -> dict[str, list[float]]:
    if not triangles:
        raise SpatialCompileError("triangle 集合不能为空")
    points = [point for triangle in triangles for point in triangle]
    return {
        "min_m": [
            _clean_float(min(float(point[axis]) for point in points))
            for axis in range(3)
        ],
        "max_m": [
            _clean_float(max(float(point[axis]) for point in points))
            for axis in range(3)
        ],
    }


def _connected_triangle_components(
    triangles: Sequence[Sequence[Sequence[float]]],
) -> list[list[Sequence[Sequence[float]]]]:
    """Split deterministic generated STL bodies by shared vertices."""

    if not triangles:
        raise SpatialCompileError("STL triangle 集合不能为空")
    parent = list(range(len(triangles)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[tuple[float, float, float], int] = {}
    for triangle_index, triangle in enumerate(triangles):
        for point in triangle:
            key = tuple(round(float(value), 9) for value in point)
            previous = owners.get(key)
            if previous is None:
                owners[key] = triangle_index
            else:
                union(triangle_index, previous)
    grouped: dict[int, list[Sequence[Sequence[float]]]] = {}
    for index, triangle in enumerate(triangles):
        grouped.setdefault(find(index), []).append(triangle)
    components = list(grouped.values())
    return sorted(
        components,
        key=lambda item: tuple(
            _triangle_bounds(item)["min_m"] + _triangle_bounds(item)["max_m"]
        ),
    )


def _connected_triangle_component_aabbs(
    triangles: Sequence[Sequence[Sequence[float]]],
) -> list[dict[str, list[float]]]:
    return [_triangle_bounds(group) for group in _connected_triangle_components(triangles)]


def _split_triangles_by_counts(
    triangles: Sequence[Sequence[Sequence[float]]], counts_value: Any
) -> list[list[Sequence[Sequence[float]]]]:
    """Restore component boundaries explicitly recorded by the generator."""

    counts: list[int] = []
    for index, value in enumerate(_sequence(counts_value, "component_triangle_counts")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 4:
            raise SpatialCompileError(
                f"component_triangle_counts[{index}] 必须是至少 4 个 triangle"
            )
        counts.append(value)
    if not counts or sum(counts) != len(triangles):
        raise SpatialCompileError("component_triangle_counts 与 STL triangle 总数不一致")
    components: list[list[Sequence[Sequence[float]]]] = []
    cursor = 0
    for count in counts:
        components.append(list(triangles[cursor : cursor + count]))
        cursor += count
    return components


def _transform_point(
    matrix: Sequence[Sequence[float]], point: Sequence[float]
) -> list[float]:
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix) or len(point) != 3:
        raise SpatialCompileError("point transform 必须是 4x4 matrix 与 vec3")
    return [
        sum(float(matrix[row][column]) * float(point[column]) for column in range(3))
        + float(matrix[row][3])
        for row in range(3)
    ]


def _aabb_distance(
    left: Mapping[str, Sequence[float]], right: Mapping[str, Sequence[float]]
) -> float:
    left_low = _vec3(left.get("min_m"), "left aabb min")
    left_high = _vec3(left.get("max_m"), "left aabb max")
    right_low = _vec3(right.get("min_m"), "right aabb min")
    right_high = _vec3(right.get("max_m"), "right aabb max")
    squared = 0.0
    for axis in range(3):
        if left_high[axis] < right_low[axis]:
            gap = right_low[axis] - left_high[axis]
        elif right_high[axis] < left_low[axis]:
            gap = left_low[axis] - right_high[axis]
        else:
            gap = 0.0
        squared += gap * gap
    return math.sqrt(squared)


def _triangle_intersects_aabb(
    triangle: Sequence[Sequence[float]],
    aabb: Mapping[str, Sequence[float]],
    *,
    tolerance: float = 1e-10,
) -> bool:
    """Triangle/AABB SAT test used for generated box proxy narrow phase."""

    if len(triangle) != 3:
        raise SpatialCompileError("triangle 必须有三个顶点")
    low = _vec3(aabb.get("min_m"), "triangle test aabb min")
    high = _vec3(aabb.get("max_m"), "triangle test aabb max")
    center = [(low[axis] + high[axis]) / 2.0 for axis in range(3)]
    half = [(high[axis] - low[axis]) / 2.0 for axis in range(3)]
    vertices = [
        [float(point[axis]) - center[axis] for axis in range(3)]
        for point in triangle
    ]
    edges = [
        [vertices[(index + 1) % 3][axis] - vertices[index][axis] for axis in range(3)]
        for index in range(3)
    ]

    def cross(left: Sequence[float], right: Sequence[float]) -> list[float]:
        return [
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        ]

    box_axes = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
    axes: list[Sequence[float]] = [*box_axes, cross(edges[0], edges[1])]
    axes.extend(cross(edge, axis) for edge in edges for axis in box_axes)
    for axis in axes:
        squared_norm = sum(float(value) * float(value) for value in axis)
        if squared_norm <= 1e-24:
            continue
        projections = [
            sum(vertex[index] * float(axis[index]) for index in range(3))
            for vertex in vertices
        ]
        radius = sum(half[index] * abs(float(axis[index])) for index in range(3))
        if min(projections) > radius + tolerance or max(projections) < -radius - tolerance:
            return False
    return True


def _triangle_aabb_overlaps(
    triangle: Sequence[Sequence[float]],
    aabb: Mapping[str, Sequence[float]],
    *,
    tolerance: float = 1e-10,
) -> bool:
    if len(triangle) != 3:
        raise SpatialCompileError("triangle 必须有三个顶点")
    low = _vec3(aabb.get("min_m"), "triangle overlap aabb min")
    high = _vec3(aabb.get("max_m"), "triangle overlap aabb max")
    return all(
        max(float(point[axis]) for point in triangle) >= low[axis] - tolerance
        and min(float(point[axis]) for point in triangle) <= high[axis] + tolerance
        for axis in range(3)
    )


def _convex_component_planes(
    triangles: Sequence[Sequence[Sequence[float]]],
) -> list[dict[str, Any]]:
    """Build deterministic outward half-spaces for a closed convex component."""

    if not triangles:
        raise SpatialCompileError("convex component triangle 集合不能为空")
    unique_points = {
        tuple(round(float(value), 12) for value in point)
        for triangle in triangles
        for point in triangle
    }
    centroid = [
        sum(point[axis] for point in unique_points) / len(unique_points)
        for axis in range(3)
    ]
    planes: dict[tuple[float, float, float, float], dict[str, Any]] = {}
    for triangle in triangles:
        first, second, third = triangle
        left = [float(second[axis]) - float(first[axis]) for axis in range(3)]
        right = [float(third[axis]) - float(first[axis]) for axis in range(3)]
        normal = [
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        ]
        norm = math.sqrt(sum(value * value for value in normal))
        if norm <= 1e-15:
            raise SpatialCompileError("compound-convex 含退化 triangle")
        normal = [value / norm for value in normal]
        if sum(
            normal[axis] * (centroid[axis] - float(first[axis]))
            for axis in range(3)
        ) > 0:
            normal = [-value for value in normal]
        offset = sum(normal[axis] * float(first[axis]) for axis in range(3))
        key_values = [0.0 if abs(value) < 5e-13 else value for value in (*normal, offset)]
        key = tuple(round(value, 10) for value in key_values)
        planes[key] = {
            "normal": [_clean_float(value) for value in normal],
            "offset": _clean_float(offset),
        }
    if len(planes) < 4:
        raise SpatialCompileError("compound-convex component 的有效平面不足")
    return [planes[key] for key in sorted(planes)]


def _triangle_intersects_convex_polyhedron(
    triangle: Sequence[Sequence[float]],
    planes: Sequence[Mapping[str, Any]],
    *,
    tolerance: float = 1e-10,
) -> list[float] | None:
    """Clip a triangle against convex half-spaces and return one contact point."""

    if len(triangle) != 3:
        raise SpatialCompileError("triangle 必须有三个顶点")
    polygon = [[float(value) for value in point] for point in triangle]
    for raw_plane in planes:
        normal = _vec3(raw_plane.get("normal"), "convex plane normal")
        raw_offset = raw_plane.get("offset")
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, (int, float)):
            raise SpatialCompileError("convex plane offset 必须是数值")
        offset = float(raw_offset)
        clipped: list[list[float]] = []
        for index, start in enumerate(polygon):
            end = polygon[(index + 1) % len(polygon)]
            start_distance = sum(normal[axis] * start[axis] for axis in range(3)) - offset
            end_distance = sum(normal[axis] * end[axis] for axis in range(3)) - offset
            start_inside = start_distance <= tolerance
            end_inside = end_distance <= tolerance
            if start_inside:
                clipped.append(start)
            if start_inside != end_inside:
                denominator = start_distance - end_distance
                if abs(denominator) <= 1e-18:
                    continue
                ratio = start_distance / denominator
                clipped.append(
                    [start[axis] + ratio * (end[axis] - start[axis]) for axis in range(3)]
                )
        polygon = clipped
        if not polygon:
            return None
    return [
        _clean_float(sum(point[axis] for point in polygon) / len(polygon))
        for axis in range(3)
    ]


def _clamp_point_to_aabb(
    point: Sequence[float], aabb: Mapping[str, Sequence[float]]
) -> list[float]:
    value = _vec3(point, "contact point")
    low = _vec3(aabb.get("min_m"), "contact aabb min")
    high = _vec3(aabb.get("max_m"), "contact aabb max")
    return [min(max(value[axis], low[axis]), high[axis]) for axis in range(3)]


def _box_triangles(
    low: Sequence[float], high: Sequence[float]
) -> list[list[list[float]]]:
    minimum = _vec3(low, "box min")
    maximum = _vec3(high, "box max")
    if any(minimum[axis] >= maximum[axis] for axis in range(3)):
        raise SpatialCompileError("box min 必须严格小于 max")
    vertices = [
        [x, y, z]
        for x in (minimum[0], maximum[0])
        for y in (minimum[1], maximum[1])
        for z in (minimum[2], maximum[2])
    ]
    faces = (
        (0, 1, 3), (0, 3, 2),
        (4, 6, 7), (4, 7, 5),
        (0, 4, 5), (0, 5, 1),
        (2, 3, 7), (2, 7, 6),
        (0, 2, 6), (0, 6, 4),
        (1, 5, 7), (1, 7, 3),
    )
    return [[vertices[index] for index in face] for face in faces]


def _xml_vec3(
    element: ET.Element | None,
    attribute: str,
    default: list[float],
    label: str,
) -> list[float]:
    if element is None or element.get(attribute) is None:
        return default[:]
    try:
        values = [float(value) for value in str(element.get(attribute)).split()]
    except ValueError as error:
        raise SpatialCompileError(f"{label} 含非数值") from error
    return _vec3(values, label)


def _assert_close_vector(
    actual: Sequence[float], expected: Sequence[float], label: str, tolerance: float = 1e-9
) -> None:
    if any(
        abs(float(left) - float(right)) > tolerance
        for left, right in zip(actual, expected, strict=True)
    ):
        raise SpatialCompileError(f"{label} 与锁定标定不一致: {actual} != {expected}")


def _identity4() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _matrix4(raw: Any, label: str) -> list[list[float]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 4:
        raise SpatialCompileError(f"{label} 必须是 4x4 数值矩阵")
    return [_number_vector(row, 4, f"{label}[{index}]") for index, row in enumerate(raw)]


def _matmul4(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> list[list[float]]:
    a = _matrix4(left, "matrix left")
    b = _matrix4(right, "matrix right")
    return [
        [sum(a[row][inner] * b[inner][column] for inner in range(4)) for column in range(4)]
        for row in range(4)
    ]


def _transform_matrix(xyz: Sequence[float], rpy_rad: Sequence[float]) -> list[list[float]]:
    x, y, z = _number_vector(xyz, 3, "transform xyz")
    roll, pitch, yaw = _number_vector(rpy_rad, 3, "transform rpy")
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y],
        [-sp, cp * sr, cp * cr, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _axis_angle_matrix(axis: Sequence[float], angle_rad: float) -> list[list[float]]:
    x, y, z = _number_vector(axis, 3, "axis")
    norm = math.sqrt(x * x + y * y + z * z)
    if norm <= 0:
        raise SpatialCompileError("rotation axis 不能为零")
    x, y, z = x / norm, y / norm, z / norm
    cosine, sine = math.cos(angle_rad), math.sin(angle_rad)
    complement = 1.0 - cosine
    return [
        [cosine + x * x * complement, x * y * complement - z * sine, x * z * complement + y * sine, 0.0],
        [y * x * complement + z * sine, cosine + y * y * complement, y * z * complement - x * sine, 0.0],
        [z * x * complement - y * sine, z * y * complement + x * sine, cosine + z * z * complement, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _transform_direction(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    transform = _matrix4(matrix, "direction transform")
    values = _number_vector(vector, 3, "direction")
    return [sum(transform[row][column] * values[column] for column in range(3)) for row in range(3)]


def _matrix_transformed_aabb(
    local_min: Sequence[float],
    local_max: Sequence[float],
    matrix: Sequence[Sequence[float]],
) -> dict[str, list[float]]:
    low, high = _bounds([local_min, local_max], "local AABB")
    transform = _matrix4(matrix, "AABB transform")
    points: list[list[float]] = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                local = [x, y, z, 1.0]
                points.append(
                    [
                        sum(transform[row][column] * local[column] for column in range(4))
                        for row in range(3)
                    ]
                )
    return {
        "min_m": [_clean_float(min(point[index] for point in points)) for index in range(3)],
        "max_m": [_clean_float(max(point[index] for point in points)) for index in range(3)],
    }


def _union_aabbs(raw_aabbs: Sequence[Mapping[str, Sequence[float]]]) -> dict[str, list[float]]:
    if not raw_aabbs:
        raise SpatialCompileError("AABB union 不能为空")
    bounds = [
        _bounds([item.get("min_m"), item.get("max_m")], "AABB union item")
        for item in raw_aabbs
    ]
    return {
        "min_m": [_clean_float(min(item[0][axis] for item in bounds)) for axis in range(3)],
        "max_m": [_clean_float(max(item[1][axis] for item in bounds)) for axis in range(3)],
    }


def _expand_aabb(
    raw_aabb: Mapping[str, Sequence[float]], distance_m: float
) -> dict[str, list[float]]:
    """Inflate an AABB isotropically by a non-negative finite distance."""

    if (
        not isinstance(distance_m, (int, float))
        or isinstance(distance_m, bool)
        or not math.isfinite(distance_m)
        or distance_m < 0
    ):
        raise SpatialCompileError("AABB expansion distance 必须是非负有限数")
    low, high = _bounds(
        [raw_aabb.get("min_m"), raw_aabb.get("max_m")], "AABB expansion"
    )
    distance = float(distance_m)
    return {
        "min_m": [_clean_float(value - distance) for value in low],
        "max_m": [_clean_float(value + distance) for value in high],
    }


def _aabb_overlaps(
    left: Mapping[str, Sequence[float]], right: Mapping[str, Sequence[float]]
) -> bool:
    """Return whether two closed AABBs overlap on all three axes."""

    left_low, left_high = _bounds(
        [left.get("min_m"), left.get("max_m")], "left overlap AABB"
    )
    right_low, right_high = _bounds(
        [right.get("min_m"), right.get("max_m")], "right overlap AABB"
    )
    return all(
        left_low[axis] <= right_high[axis]
        and right_low[axis] <= left_high[axis]
        for axis in range(3)
    )


def _clean_matrix(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[_clean_float(value) for value in row] for row in _matrix4(matrix, "matrix")]


def _select_operation_branch(
    operation: Mapping[str, Any], variable: str, expected: Any
) -> list[Mapping[str, Any]]:
    body = operation.get("body")
    if not isinstance(body, Sequence) or isinstance(body, (str, bytes)):
        raise SpatialCompileError("operation.body 必须是数组")
    for raw in body:
        node = _mapping(raw, "operation.body node")
        if node.get("op") != "if":
            continue
        choices: list[tuple[Mapping[str, Any], Any]] = []
        choices.append((node, node.get("then")))
        elifs = node.get("elifs", [])
        if not isinstance(elifs, Sequence) or isinstance(elifs, (str, bytes)):
            raise SpatialCompileError("operation if.elifs 必须是数组")
        for raw_elif in elifs:
            elif_node = _mapping(raw_elif, "operation elif")
            choices.append((elif_node, elif_node.get("body")))
        for choice, raw_branch in choices:
            cond = _mapping(choice.get("cond"), "operation branch cond")
            if cond.get("binop") != "==":
                continue
            left = _mapping(cond.get("left"), "operation cond.left")
            right = _mapping(cond.get("right"), "operation cond.right")
            if left.get("var") == variable and right.get("lit") == expected:
                if not isinstance(raw_branch, Sequence) or isinstance(raw_branch, (str, bytes)):
                    raise SpatialCompileError("selected operation branch 必须是数组")
                return [_mapping(item, "selected branch step") for item in raw_branch]
    raise SpatialCompileError(f"operation 没有 {variable}={expected!r} 分支")


def _product(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    products = _mapping(config.get("products"), "config.products")
    return _mapping(products.get(name), f"products.{name}")


def _locked_sample(lock: Mapping[str, Any], sample_id: str) -> Mapping[str, Any]:
    samples = lock.get("samples")
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        raise SpatialCompileError("lock.samples 无效")
    matches = [
        _mapping(sample, "locked sample")
        for sample in samples
        if isinstance(sample, Mapping) and sample.get("sample_id") == sample_id
    ]
    if len(matches) != 1:
        raise SpatialCompileError(f"lock 中 sample_id 必须唯一存在: {sample_id}")
    return matches[0]


def _inputs_by_role(sample: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_inputs = sample.get("inputs")
    if not isinstance(raw_inputs, Sequence) or isinstance(raw_inputs, (str, bytes)):
        raise SpatialCompileError("locked sample.inputs 无效")
    return {
        _text(_mapping(item, "locked input").get("role"), "locked input.role"): _mapping(
            item, "locked input"
        )
        for item in raw_inputs
    }


def _index_by_id(raw: Any, key: str, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise SpatialCompileError(f"{label} 必须是数组")
    result: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(raw):
        value = _mapping(item, f"{label}[{index}]")
        identity = _text(value.get(key), f"{label}[{index}].{key}")
        if identity in result:
            raise SpatialCompileError(f"{label} 身份重复: {identity}")
        result[identity] = value
    return result


def _transformed_aabb(
    local_min: Sequence[float],
    local_max: Sequence[float],
    xyz: Sequence[float],
    rpy_deg: Sequence[float],
) -> tuple[list[float], list[float]]:
    roll, pitch, yaw = [math.radians(value) for value in rpy_deg]
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rotation = (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )
    transformed: list[list[float]] = []
    for x in (local_min[0], local_max[0]):
        for y in (local_min[1], local_max[1]):
            for z in (local_min[2], local_max[2]):
                local = (x, y, z)
                transformed.append(
                    [
                        sum(rotation[row][column] * local[column] for column in range(3))
                        + xyz[row]
                        for row in range(3)
                    ]
                )
    world_min = [min(point[index] for point in transformed) for index in range(3)]
    world_max = [max(point[index] for point in transformed) for index in range(3)]
    return [_clean_float(value) for value in world_min], [
        _clean_float(value) for value in world_max
    ]


def _clean_float(value: float) -> float:
    rounded = round(float(value), 12)
    return 0.0 if rounded == -0.0 else rounded


def _bounds(raw: Any, label: str) -> tuple[list[float], list[float]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
        raise SpatialCompileError(f"{label} 必须是 [min,max]")
    low = _vec3(raw[0], f"{label}.min")
    high = _vec3(raw[1], f"{label}.max")
    if any(low[index] > high[index] for index in range(3)):
        raise SpatialCompileError(f"{label} min 不能大于 max")
    return low, high


def _vec3(raw: Any, label: str) -> list[float]:
    return _number_vector(raw, 3, label)


def _vec6(raw: Any, label: str) -> list[float]:
    return _number_vector(raw, 6, label)


def _number_vector(raw: Any, length: int, label: str) -> list[float]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != length:
        raise SpatialCompileError(f"{label} 必须是 {length} 维数值数组")
    values: list[float] = []
    for value in raw:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise SpatialCompileError(f"{label} 含非有限数值")
        values.append(float(value))
    return values


def _literal(raw: Any, label: str) -> Any:
    value = _mapping(raw, label)
    if set(value) != {"lit"}:
        raise SpatialCompileError(f"{label} 必须是单一 lit")
    return value["lit"]


def _literal_text(raw: Any, label: str) -> str:
    return _text(_literal(raw, label), label)


def _mapping(raw: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise SpatialCompileError(f"{label} 必须是对象")
    return raw


def _sequence(raw: Any, label: str) -> Sequence[Any]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise SpatialCompileError(f"{label} 必须是数组")
    return raw


def _text(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SpatialCompileError(f"{label} 必须是非空字符串")
    return raw.strip()


def _text_list(raw: Any, label: str) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise SpatialCompileError(f"{label} 必须是字符串数组")
    result = [_text(item, f"{label}[]") for item in raw]
    if not result:
        raise SpatialCompileError(f"{label} 不能为空")
    if len(result) != len(set(result)):
        raise SpatialCompileError(f"{label} 不能重复")
    return result


def _relative_path(raw: Any, label: str) -> str:
    text = _text(raw, label).replace("\\", "/")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise SpatialCompileError(f"{label} 必须是仓库内相对路径")
    return path.as_posix()


def _repo_file(repo_root: Path, raw: str | Path) -> Path:
    repo_root = repo_root.resolve()
    relative = _relative_path(str(raw), "repository path")
    path = (repo_root / relative).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as error:
        raise SpatialCompileError(f"路径逃逸仓库: {relative}") from error
    if not path.is_file():
        raise SpatialCompileError(f"输入文件不存在: {relative}")
    return path


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SpatialCompileError(f"无法读取 JSON: {path}: {error}") from error


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise SpatialCompileError(f"无法读取 YAML: {path}: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_digest(path: Path, mode: str) -> str:
    if mode == "raw-bytes":
        return _sha256(path)
    if mode == "utf8-lf-v1":
        try:
            normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeError) as error:
            raise SpatialCompileError(f"无法规范化文本摘要: {path}: {error}") from error
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if mode == "canonical-json-v1":
        value = _read_json(path)
        return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()
    raise SpatialCompileError(f"不支持的 artifact digest mode: {mode}")


def _canonical_json_bytes(document: Mapping[str, Any], *, pretty: bool = False) -> bytes:
    if pretty:
        text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.encode("utf-8")


def _document_digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(document)).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile deterministic offline spatial shadow inputs and an initial unknown decision."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--config", type=Path, default=Path("config/spatial-shadow-samples.v0.yaml")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/spatial-shadow/v0")
    )
    parser.add_argument("--check", action="store_true", help="validate without writing output")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    artifacts = compile_shadow(repo_root, args.config)
    validate_artifacts(repo_root, artifacts)
    if not args.check:
        output_dir = args.output_dir
        if not output_dir.is_absolute():
            output_dir = repo_root / output_dir
        write_artifacts(output_dir, artifacts)
    summary = {
        "schema": "lab.spatial-shadow-compile-summary/v0",
        "validated": True,
        "written": not args.check,
        "artifacts": {
            name: _document_digest(document) for name, document in sorted(artifacts.items())
        },
        "decision": artifacts["ptlc-tank1-shadow-decision.json"]["decision"],
        "effect": artifacts["ptlc-tank1-shadow-decision.json"]["effect"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
