#!/usr/bin/env python3
"""Export a compact, hash-bound EIT spatial-shadow snapshot for Workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "unilab.spatial-shadow-workbench/v0"
DEFAULT_SOURCE = Path("artifacts/spatial-shadow/v0")
DEFAULT_OUTPUT = Path(
    "pTLC_platformUI/.unilab/spatial-shadow/current.v0.json"
)
SOURCE_FILES = {
    "collision_scene": "ptlc-collision-scene.json",
    "environment_collision": "ptlc-tank1-environment-collision.json",
    "link_states": "ptlc-tank1-link-states.json",
    "playback": "ptlc-tank1-playback.json",
    "motion_corridor": "ptlc-tank1-motion-corridor.json",
    "continuous_collision": "ptlc-tank1-continuous-collision.json",
    "certificate": "ptlc-tank1-spatial-certificate.json",
    "decision": "ptlc-tank1-shadow-decision.json",
}


class SpatialWorkbenchExportError(RuntimeError):
    """Raised when the source artifacts cannot form one honest snapshot."""


def _canonical_bytes(document: Mapping[str, Any], *, pretty: bool) -> bytes:
    if pretty:
        text = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    else:
        text = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return f"{text}\n".encode("utf-8")


def _document_digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(document, pretty=False)).hexdigest()


def _normalize_json_numbers(value: Any) -> Any:
    """Quantize derived floats so repeated/cross-platform exports are byte stable."""

    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpatialWorkbenchExportError("Workbench snapshot 含 NaN/Infinity")
        rounded = round(value, 12)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    raise SpatialWorkbenchExportError(
        f"Workbench snapshot 含不可规范化类型: {type(value).__name__}"
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpatialWorkbenchExportError(f"无法读取空间产物 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpatialWorkbenchExportError(f"空间产物必须是 JSON object: {path}")
    return value


def _require_same(
    documents: Mapping[str, Mapping[str, Any]], field: str
) -> Any:
    values = {name: document.get(field) for name, document in documents.items()}
    unique = {json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values.values()}
    if len(unique) != 1:
        raise SpatialWorkbenchExportError(f"源产物 {field} 不一致: {values}")
    return next(iter(values.values()))


def _compact_aabb(value: Any, label: str) -> dict[str, list[float]]:
    if not isinstance(value, dict):
        raise SpatialWorkbenchExportError(f"{label} 缺少 AABB")
    minimum = value.get("min_m")
    maximum = value.get("max_m")
    if not (
        isinstance(minimum, list)
        and isinstance(maximum, list)
        and len(minimum) == 3
        and len(maximum) == 3
        and all(isinstance(item, (int, float)) for item in minimum + maximum)
        and all(float(low) <= float(high) for low, high in zip(minimum, maximum))
    ):
        raise SpatialWorkbenchExportError(f"{label} AABB 非法")
    return {
        "min_m": [float(item) for item in minimum],
        "max_m": [float(item) for item in maximum],
    }


def _matrix4(value: Any, label: str) -> list[list[float]]:
    if not (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(row, list) and len(row) == 4 for row in value)
        and all(
            isinstance(item, (int, float))
            for row in value
            for item in row
        )
    ):
        raise SpatialWorkbenchExportError(f"{label} 必须是 4x4 数值矩阵")
    return [[float(item) for item in row] for row in value]


def _multiply_matrix4(
    left: list[list[float]], right: list[list[float]]
) -> list[list[float]]:
    return [
        [
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        ]
        for row in range(4)
    ]


def _vec6(value: Any, label: str) -> list[float]:
    if not (
        isinstance(value, list)
        and len(value) == 6
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            for item in value
        )
    ):
        raise SpatialWorkbenchExportError(f"{label} 必须是 6 个有限数值")
    return [float(item) for item in value]


def _transform_aabb(
    value: Any, matrix: list[list[float]], label: str
) -> dict[str, list[float]]:
    source = _compact_aabb(value, label)
    corners = [
        [x, y, z]
        for x in (source["min_m"][0], source["max_m"][0])
        for y in (source["min_m"][1], source["max_m"][1])
        for z in (source["min_m"][2], source["max_m"][2])
    ]
    transformed = [
        [
            sum(matrix[row][column] * point[column] for column in range(3))
            + matrix[row][3]
            for row in range(3)
        ]
        for point in corners
    ]
    return {
        "min_m": [min(point[axis] for point in transformed) for axis in range(3)],
        "max_m": [max(point[axis] for point in transformed) for axis in range(3)],
    }


def _union_aabbs(values: list[dict[str, list[float]]], label: str) -> dict[str, list[float]]:
    if not values:
        raise SpatialWorkbenchExportError(f"{label} 缺少可合并 AABB")
    return {
        "min_m": [min(value["min_m"][axis] for value in values) for axis in range(3)],
        "max_m": [max(value["max_m"][axis] for value in values) for axis in range(3)],
    }


def build_snapshot(source_dir: Path) -> dict[str, Any]:
    """Build the compact Workbench projection from compiler-owned artifacts."""
    documents = {
        name: _read_json(source_dir / filename)
        for name, filename in SOURCE_FILES.items()
    }
    sample_id = _require_same(documents, "sample_id")
    action_contract_id = _require_same(
        {
            name: document
            for name, document in documents.items()
            if name != "collision_scene"
        },
        "action_contract_id",
    )
    mode = _require_same(documents, "mode")
    if mode != "shadow":
        raise SpatialWorkbenchExportError("Workbench v0 只接受 shadow 产物")

    scene = documents["collision_scene"]
    environment_collision = documents["environment_collision"]
    link_states = documents["link_states"]
    playback = documents["playback"]
    corridor = documents["motion_corridor"]
    continuous = documents["continuous_collision"]
    certificate = documents["certificate"]
    decision = documents["decision"]
    if decision.get("effect") != "none":
        raise SpatialWorkbenchExportError("离线 Workbench 快照必须 effect=none")
    if decision.get("certificate_ref") != certificate.get("certificate_id"):
        raise SpatialWorkbenchExportError("decision 与 certificate 引用不一致")
    collision_sources = environment_collision.get("source_digests")
    if not isinstance(collision_sources, dict) or (
        collision_sources.get("collision_scene") != scene.get("scene_digest")
        or collision_sources.get("link_state_sequence")
        != link_states.get("sequence_digest")
        or collision_sources.get("playback") != playback.get("playback_digest")
    ):
        raise SpatialWorkbenchExportError("environment collision 未绑定当前场景/轨迹")
    if environment_collision.get("effect") != "none":
        raise SpatialWorkbenchExportError("环境碰撞诊断必须 effect=none")
    registration = environment_collision.get("registration")
    if not isinstance(registration, dict):
        raise SpatialWorkbenchExportError("environment collision 缺少 registration")
    registration_matrix = _matrix4(
        registration.get("matrix_source_to_target"),
        "registration.matrix_source_to_target",
    )
    if registration.get("world_rigid_transform_qualified") is not False:
        raise SpatialWorkbenchExportError("v0 快照不得把候选坐标配准升级为合格")
    continuous_sources = continuous.get("source_digests")
    if not isinstance(continuous_sources, dict) or continuous_sources.get(
        "motion_corridor"
    ) != corridor.get("corridor_digest"):
        raise SpatialWorkbenchExportError("continuous collision 未绑定当前 motion corridor")
    playback_sources = playback.get("source_digests")
    if not isinstance(playback_sources, dict) or playback_sources.get(
        "link_state_sequence"
    ) != link_states.get("sequence_digest"):
        raise SpatialWorkbenchExportError("playback 未绑定当前 link-state sequence")

    kinematic_model = link_states.get("kinematic_model")
    if not isinstance(kinematic_model, dict):
        raise SpatialWorkbenchExportError("link-state sequence 缺少 kinematic_model")
    joint_ids = kinematic_model.get("joint_ids")
    controller_to_model = kinematic_model.get("controller_to_model")
    if not (
        isinstance(joint_ids, list)
        and len(joint_ids) == 6
        and all(isinstance(item, str) and item for item in joint_ids)
        and len(set(joint_ids)) == 6
        and isinstance(controller_to_model, dict)
    ):
        raise SpatialWorkbenchExportError("CR5 kinematic_model 关节契约非法")
    joint_sign = _vec6(
        controller_to_model.get("sign"), "controller_to_model.sign"
    )
    joint_zero_offset_deg = _vec6(
        controller_to_model.get("zero_offset_deg"),
        "controller_to_model.zero_offset_deg",
    )

    geometry = link_states.get("geometry")
    states = link_states.get("states")
    segments = corridor.get("segments")
    entities = scene.get("entities")
    if not all(isinstance(value, list) for value in (geometry, states, segments, entities)):
        raise SpatialWorkbenchExportError("源产物缺少 geometry/states/segments/entities")
    link_ids = [item.get("link_id") for item in geometry if isinstance(item, dict)]
    if len(link_ids) != len(geometry) or len(set(link_ids)) != len(link_ids):
        raise SpatialWorkbenchExportError("collision link id 缺失或重复")
    continuous_segments = continuous.get("segments")
    if not isinstance(continuous_segments, list):
        raise SpatialWorkbenchExportError("continuous collision 缺少 segments")
    continuous_by_index = {
        item.get("segment_index"): item
        for item in continuous_segments
        if isinstance(item, dict) and isinstance(item.get("segment_index"), int)
    }
    if len(continuous_by_index) != len(continuous_segments):
        raise SpatialWorkbenchExportError("continuous collision segment 缺失或重复")
    playback_segments = playback.get("segments")
    if not isinstance(playback_segments, list):
        raise SpatialWorkbenchExportError("playback 缺少 segments")
    playback_by_index = {
        item.get("segment_index"): item
        for item in playback_segments
        if isinstance(item, dict) and isinstance(item.get("segment_index"), int)
    }
    if len(playback_by_index) != len(playback_segments):
        raise SpatialWorkbenchExportError("playback segment 缺失或重复")
    raw_collision_frames = environment_collision.get("frames")
    if not isinstance(raw_collision_frames, list):
        raise SpatialWorkbenchExportError("environment collision 缺少 frames")
    collision_by_frame = {
        (item.get("segment_index"), item.get("frame_index")): item
        for item in raw_collision_frames
        if isinstance(item, dict)
        and isinstance(item.get("segment_index"), int)
        and isinstance(item.get("frame_index"), int)
    }
    if len(collision_by_frame) != len(raw_collision_frames):
        raise SpatialWorkbenchExportError("environment collision frame 身份缺失或重复")

    compact_states: list[dict[str, Any]] = []
    seen_states: set[str] = set()
    for state in states:
        if not isinstance(state, dict) or not isinstance(state.get("state_id"), str):
            raise SpatialWorkbenchExportError("link state 缺少 state_id")
        state_id = state["state_id"]
        if state_id in seen_states:
            raise SpatialWorkbenchExportError(f"link state 重复: {state_id}")
        seen_states.add(state_id)
        links = state.get("links")
        if not isinstance(links, list) or [item.get("link_id") for item in links] != link_ids:
            raise SpatialWorkbenchExportError(f"{state_id} link 顺序与 geometry 不一致")
        validation = state.get("tool_1_tcp_validation")
        compact_states.append(
            {
                "state_id": state_id,
                "step_index": state.get("step_index"),
                "point_ref": state.get("point_ref"),
                "phase": state.get("phase"),
                "payload_state": state.get("payload_state"),
                "tcp_residual_mm": validation.get("position_residual_mm")
                if isinstance(validation, dict)
                else None,
                "links": [
                    {
                        "link_id": link["link_id"],
                        "world_aabb": _transform_aabb(
                            link.get("world_aabb"),
                            registration_matrix,
                            f"{state_id}/{link['link_id']}",
                        ),
                    }
                    for link in links
                ],
            }
        )

    compact_segments: list[dict[str, Any]] = []
    seen_segments: set[int] = set()
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("segment_index"), int):
            raise SpatialWorkbenchExportError("motion segment 缺少 segment_index")
        segment_index = segment["segment_index"]
        if segment_index in seen_segments:
            raise SpatialWorkbenchExportError(f"motion segment 重复: {segment_index}")
        seen_segments.add(segment_index)
        world_aabb = segment.get("segment_world_aabb")
        status = segment.get("status")
        if status == "sampled-candidate" and world_aabb is None:
            raise SpatialWorkbenchExportError(f"segment {segment_index} 已采样但缺少 AABB")
        if status == "excluded-unresolved" and world_aabb is not None:
            raise SpatialWorkbenchExportError(f"segment {segment_index} 未解析却包含 AABB")
        continuous_segment = continuous_by_index.get(segment_index)
        if continuous_segment is None:
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} 缺少 continuous collision 结果"
            )
        if (
            continuous_segment.get("source_state_id") != segment.get("source_state_id")
            or continuous_segment.get("target_state_id") != segment.get("target_state_id")
        ):
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} corridor/continuous 身份不一致"
            )
        continuous_status = continuous_segment.get("status")
        continuous_world_aabb = continuous_segment.get("segment_world_aabb")
        self_collision = continuous_segment.get("self_collision")
        if continuous_status == "continuous-broad-phase-candidate":
            if continuous_world_aabb is None or not isinstance(self_collision, dict):
                raise SpatialWorkbenchExportError(
                    f"segment {segment_index} 连续候选缺少包络或自碰撞摘要"
                )
            continuous_interval_count: int | None = int(
                continuous_segment.get("interval_count", 0)
            )
            candidate_pair_count: int | None = int(
                self_collision.get("candidate_overlap_pair_count", -1)
            )
            separated_pair_count: int | None = int(
                self_collision.get("separated_pair_count", -1)
            )
            if (
                continuous_interval_count <= 0
                or candidate_pair_count < 0
                or separated_pair_count < 0
            ):
                raise SpatialWorkbenchExportError(
                    f"segment {segment_index} 连续候选计数非法"
                )
        elif continuous_status == "excluded-unresolved":
            if continuous_world_aabb is not None or self_collision is not None:
                raise SpatialWorkbenchExportError(
                    f"segment {segment_index} 连续排除项不得包含计算结果"
                )
            continuous_interval_count = None
            candidate_pair_count = None
            separated_pair_count = None
        else:
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} continuous status 非法"
            )
        playback_segment = playback_by_index.get(segment_index)
        if not isinstance(playback_segment, dict):
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} 缺少 playback 结果"
            )
        if (
            playback_segment.get("source_state_id") != segment.get("source_state_id")
            or playback_segment.get("target_state_id") != segment.get("target_state_id")
        ):
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} corridor/playback 身份不一致"
            )
        playback_frames = playback_segment.get("frames")
        if not isinstance(playback_frames, list) or len(playback_frames) < 2:
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} playback frames 不足"
            )
        collision_frames = [
            collision_by_frame.get((segment_index, frame_index))
            for frame_index in range(len(playback_frames))
        ]
        if any(not isinstance(item, dict) for item in collision_frames):
            raise SpatialWorkbenchExportError(
                f"segment {segment_index} collision/playback frame 不一致"
            )
        segment_contact_frames = [
            item
            for item in collision_frames
            if isinstance(item, dict) and item.get("status") == "proxy-mesh-contact"
        ]
        segment_broad_only_frames = [
            item
            for item in collision_frames
            if isinstance(item, dict)
            and item.get("status") == "broad-phase-overlap-unresolved"
        ]
        segment_minimum_clearance = min(
            float(item["minimum_aabb_clearance_m"])
            for item in collision_frames
            if isinstance(item, dict)
        )
        compact_segments.append(
            {
                "segment_index": segment_index,
                "source_state_id": segment.get("source_state_id"),
                "target_state_id": segment.get("target_state_id"),
                "target_step_index": segment.get("target_step_index"),
                "motion": segment.get("motion"),
                "cp": segment.get("cp"),
                "phase": segment.get("phase"),
                "payload_state": segment.get("payload_state"),
                "status": status,
                "sample_count": segment.get("sample_count"),
                "world_aabb": _transform_aabb(
                    world_aabb, registration_matrix, f"segment {segment_index}"
                )
                if world_aabb is not None
                else None,
                "continuous_status": continuous_status,
                "continuous_interval_count": continuous_interval_count,
                "continuous_world_aabb": _transform_aabb(
                    continuous_world_aabb,
                    registration_matrix,
                    f"continuous segment {segment_index}",
                )
                if continuous_world_aabb is not None
                else None,
                "self_collision_candidate_pair_count": candidate_pair_count,
                "self_collision_separated_pair_count": separated_pair_count,
                "reason_codes": segment.get("reason_codes", []),
                "continuous_reason_codes": continuous_segment.get("reason_codes", []),
                "playback_duration_s": playback_segment.get("duration_s"),
                "playback_frame_count": len(playback_frames),
                "playback_interpolation": playback_segment.get("interpolation"),
                "playback_controller_fidelity": playback_segment.get(
                    "controller_fidelity"
                ),
                "environment_collision_status": (
                    "proxy-mesh-contact"
                    if segment_contact_frames
                    else "broad-phase-overlap-unresolved"
                    if segment_broad_only_frames
                    else "separated-at-sampled-frames"
                ),
                "environment_minimum_aabb_clearance_m": segment_minimum_clearance,
                "environment_contact_frame_count": len(segment_contact_frames),
                "environment_broad_only_frame_count": len(segment_broad_only_frames),
                "environment_first_contact_time_s": (
                    float(segment_contact_frames[0]["time_s"])
                    if segment_contact_frames
                    else None
                ),
            }
        )

    compact_playback_segments: list[dict[str, Any]] = []
    compact_collision_frames: list[dict[str, Any]] = []
    total_playback_frames = 0
    for segment_index in range(len(compact_segments)):
        source = playback_by_index[segment_index]
        raw_frames = source["frames"]
        compact_frames: list[dict[str, Any]] = []
        for frame_index, frame in enumerate(raw_frames):
            if not isinstance(frame, dict) or frame.get("frame_index") != frame_index:
                raise SpatialWorkbenchExportError(
                    f"playback segment {segment_index} frame_index 不连续"
                )
            links = frame.get("links")
            attachments = frame.get("attachments")
            if not isinstance(links, list) or [item.get("link_id") for item in links] != link_ids:
                raise SpatialWorkbenchExportError(
                    f"playback segment {segment_index} frame {frame_index} link 顺序错误"
                )
            if not isinstance(attachments, list) or not attachments:
                raise SpatialWorkbenchExportError(
                    f"playback segment {segment_index} frame {frame_index} 缺 attachment"
                )
            collision_frame = collision_by_frame.get((segment_index, frame_index))
            if not isinstance(collision_frame, dict) or abs(
                float(collision_frame.get("time_s", -1.0)) - float(frame.get("time_s", -2.0))
            ) > 1e-9:
                raise SpatialWorkbenchExportError(
                    f"playback/collision frame 时间不一致: {segment_index}/{frame_index}"
                )
            exact_contacts = collision_frame.get("exact_contacts")
            closest_pair = collision_frame.get("closest_pair")
            if not isinstance(exact_contacts, list) or not isinstance(closest_pair, dict):
                raise SpatialWorkbenchExportError(
                    f"collision frame {segment_index}/{frame_index} 内容不完整"
                )
            compact_collision_frames.append(
                {
                    "segment_index": segment_index,
                    "frame_index": frame_index,
                    "time_s": collision_frame.get("time_s"),
                    "status": collision_frame.get("status"),
                    "minimum_aabb_clearance_m": collision_frame.get(
                        "minimum_aabb_clearance_m"
                    ),
                    "closest_pair": {
                        "moving_object_id": closest_pair.get("moving_object_id"),
                        "environment_component_id": closest_pair.get(
                            "environment_component_id"
                        ),
                    },
                    "broad_overlap_pair_count": collision_frame.get(
                        "broad_overlap_pair_count"
                    ),
                    "unresolved_shaped_overlap_pair_count": collision_frame.get(
                        "unresolved_shaped_overlap_pair_count"
                    ),
                    "exact_contacts": exact_contacts,
                }
            )
            compact_frames.append(
                {
                    "frame_index": frame_index,
                    "time_s": frame.get("time_s"),
                    "segment_time_s": frame.get("segment_time_s"),
                    "progress": frame.get("progress"),
                    "joint_positions_rad": [
                        math.radians(sign * controller + offset)
                        for controller, sign, offset in zip(
                            _vec6(
                                frame.get("controller_joint_deg"),
                                f"playback {segment_index}/{frame_index} controller joints",
                            ),
                            joint_sign,
                            joint_zero_offset_deg,
                        )
                    ],
                    "links": [
                        {
                            "link_id": link.get("link_id"),
                            "matrix_link_to_world": _multiply_matrix4(
                                registration_matrix,
                                _matrix4(
                                    link.get("matrix_link_to_world"),
                                    f"playback {segment_index}/{frame_index}/{link.get('link_id')} matrix",
                                ),
                            ),
                            "world_aabb": _transform_aabb(
                                link.get("world_aabb"),
                                registration_matrix,
                                f"playback {segment_index}/{frame_index}/{link.get('link_id')}",
                            ),
                        }
                        for link in links
                        if isinstance(link, dict)
                    ],
                    "attachments": [
                        {
                            "attachment_id": attachment.get("attachment_id"),
                            "kind": attachment.get("kind"),
                            "matrix_attachment_to_world": _multiply_matrix4(
                                registration_matrix,
                                _matrix4(
                                    attachment.get("matrix_attachment_to_world"),
                                    f"playback {segment_index}/{frame_index}/{attachment.get('attachment_id')} matrix",
                                ),
                            ),
                            "world_aabb": _transform_aabb(
                                attachment.get("world_aabb"),
                                registration_matrix,
                                f"playback {segment_index}/{frame_index}/{attachment.get('attachment_id')}",
                            ),
                        }
                        for attachment in attachments
                        if isinstance(attachment, dict)
                    ],
                }
            )
        total_playback_frames += len(compact_frames)
        compact_playback_segments.append(
            {
                "segment_index": segment_index,
                "duration_s": source.get("duration_s"),
                "start_time_s": source.get("start_time_s"),
                "end_time_s": source.get("end_time_s"),
                "interpolation": source.get("interpolation"),
                "controller_fidelity": source.get("controller_fidelity"),
                "reason_codes": source.get("reason_codes", []),
                "frames": compact_frames,
            }
        )

    sampled = sum(item["status"] == "sampled-candidate" for item in compact_segments)
    excluded = sum(item["status"] == "excluded-unresolved" for item in compact_segments)
    continuous_evaluated = sum(
        item["continuous_status"] == "continuous-broad-phase-candidate"
        for item in compact_segments
    )
    continuous_candidate_pairs = sum(
        int(item["self_collision_candidate_pair_count"] or 0)
        for item in compact_segments
    )
    coverage = corridor.get("coverage")
    if not isinstance(coverage, dict):
        raise SpatialWorkbenchExportError("motion corridor 缺少 coverage")
    if coverage.get("total_motion_segments") != len(compact_segments):
        raise SpatialWorkbenchExportError("coverage 总段数与 segments 不一致")
    if coverage.get("sampled_move_j_segments") != sampled:
        raise SpatialWorkbenchExportError("coverage 已采样段数与 segments 不一致")

    snapshot: dict[str, Any] = {
        "schema": SCHEMA,
        "sample_id": sample_id,
        "action_contract_id": action_contract_id,
        "mode": mode,
        "qualification": corridor.get("qualification"),
        "decision": decision.get("decision"),
        "effect": decision.get("effect"),
        "not_workcell_activation": True,
        "world_frame": environment_collision.get("world_frame"),
        "registration": registration,
        "source": {
            "kind": "eit-compiler-artifact-export",
            "workspace_relative_path": ".unilab/spatial-shadow/current.v0.json",
            "artifacts": {
                "collision_scene": {
                    "file": SOURCE_FILES["collision_scene"],
                    "digest": scene.get("scene_digest"),
                },
                "environment_collision": {
                    "file": SOURCE_FILES["environment_collision"],
                    "digest": environment_collision.get("collision_digest"),
                },
                "link_states": {
                    "file": SOURCE_FILES["link_states"],
                    "digest": link_states.get("sequence_digest"),
                },
                "playback": {
                    "file": SOURCE_FILES["playback"],
                    "digest": playback.get("playback_digest"),
                },
                "motion_corridor": {
                    "file": SOURCE_FILES["motion_corridor"],
                    "digest": corridor.get("corridor_digest"),
                },
                "continuous_collision": {
                    "file": SOURCE_FILES["continuous_collision"],
                    "digest": continuous.get("candidate_digest"),
                },
                "certificate": {
                    "file": SOURCE_FILES["certificate"],
                    "digest": certificate.get("certificate_digest"),
                },
                "decision": {
                    "file": SOURCE_FILES["decision"],
                    "digest": decision.get("decision_digest"),
                },
            },
        },
        "summary": {
            "environment_entity_count": len(entities),
            "state_count": len(compact_states),
            "link_count": len(link_ids),
            "segment_count": len(compact_segments),
            "sampled_segment_count": sampled,
            "excluded_segment_count": excluded,
            "continuous_evaluated_segment_count": continuous_evaluated,
            "self_collision_candidate_pair_count": continuous_candidate_pairs,
            "playable_segment_count": len(compact_playback_segments),
            "playback_frame_count": total_playback_frames,
            "attachment_model_count": len(playback.get("attachment_models", [])),
            "environment_exact_contact_frame_count": environment_collision.get(
                "coverage", {}
            ).get("exact_contact_frame_count"),
            "environment_broad_only_frame_count": environment_collision.get(
                "coverage", {}
            ).get("broad_only_overlap_frame_count"),
            "environment_exact_contact_event_count": environment_collision.get(
                "coverage", {}
            ).get("exact_contact_event_count"),
        },
        "coverage": coverage,
        "continuous_analysis": continuous.get("analysis"),
        "validation": link_states.get("validation"),
        "environment_entities": [
            {
                "entity_id": entity.get("entity_id"),
                "role": entity.get("role"),
                "geometry_path": entity.get("geometry_path"),
                "geometry_sha256": entity.get("geometry_sha256"),
                "geometry_format": entity.get("geometry_format"),
                "geometry_unit": entity.get("geometry_unit"),
                "collision_mode": entity.get("collision_mode"),
                "component_count": entity.get("component_count"),
                "component_world_aabbs": [
                    _compact_aabb(component, f"{entity.get('entity_id')}.component")
                    for component in entity.get("component_world_aabbs", [])
                ],
                "world_aabb": _compact_aabb(
                    entity.get("world_aabb"), str(entity.get("entity_id"))
                ),
            }
            for entity in entities
            if isinstance(entity, dict)
        ],
        "states": compact_states,
        "segments": compact_segments,
        "playback": {
            "duration_s": playback.get("timing", {}).get("duration_s"),
            "nominal_frame_rate_hz": playback.get("timing", {}).get(
                "nominal_frame_rate_hz"
            ),
            "kinematics": {
                "model_id": kinematic_model.get("model_id"),
                "joint_ids": joint_ids,
                "position_unit": "rad",
                "source": "controller-to-model-calibration",
            },
            "attachment_models": playback.get("attachment_models", []),
            "segments": compact_playback_segments,
        },
        "environment_collision": {
            "qualification": environment_collision.get("qualification"),
            "coverage": environment_collision.get("coverage"),
            "summary": environment_collision.get("summary"),
            "frames": compact_collision_frames,
        },
        "partial_world_aabb": _union_aabbs(
            [
                item["world_aabb"]
                for item in compact_segments
                if item["world_aabb"] is not None
            ],
            "partial corridor",
        ),
        "reason_codes": decision.get("reason_codes", []),
        "limitations": sorted(
            {
                *scene.get("limitations", []),
                *link_states.get("limitations", []),
                *corridor.get("limitations", []),
                *continuous.get("limitations", []),
                *playback.get("limitations", []),
                *environment_collision.get("limitations", []),
            }
        ),
    }
    normalized = _normalize_json_numbers(snapshot)
    if not isinstance(normalized, dict):
        raise SpatialWorkbenchExportError("Workbench snapshot 规范化结果不是 object")
    normalized["snapshot_digest"] = _document_digest(normalized)
    return normalized


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the current EIT spatial shadow as a Workbench snapshot."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the checked-in Workbench snapshot without rewriting it",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    source_dir = args.source_dir if args.source_dir.is_absolute() else repo_root / args.source_dir
    output = args.output if args.output.is_absolute() else repo_root / args.output
    snapshot = build_snapshot(source_dir)
    payload = _canonical_bytes(snapshot, pretty=True)
    if args.check:
        try:
            existing = output.read_bytes()
        except OSError as exc:
            raise SpatialWorkbenchExportError(f"Workbench 快照不存在: {output}") from exc
        if existing != payload:
            raise SpatialWorkbenchExportError(
                "Workbench 快照已漂移；请重新运行 export_spatial_workbench_snapshot.py"
            )
    else:
        _atomic_write(output, payload)
    print(
        json.dumps(
            {
                "schema": "unilab.spatial-shadow-workbench-export-summary/v0",
                "validated": True,
                "written": not args.check,
                "output": str(args.output),
                "snapshot_digest": snapshot["snapshot_digest"],
                "summary": snapshot["summary"],
                "decision": snapshot["decision"],
                "effect": snapshot["effect"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
