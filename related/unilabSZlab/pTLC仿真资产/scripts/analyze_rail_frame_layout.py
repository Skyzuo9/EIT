from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "pTLC仿真资产"
INPUT = ASSET_ROOT / "interaction_points.json"
OUTPUT = ASSET_ROOT / "rail_frame_layout_analysis.json"

# These bindings are workflow semantics, not fields in the robot-point records.
# Keep their provenance explicit so a point snapshot can never silently acquire a rail value.
SEMANTIC_BINDINGS = [
    {
        "cluster_id": "sampling_station",
        "point_numbers": [19, 20],
        "rail_slot": 1,
        "basis": "sampling workflow target points",
    },
    {
        "cluster_id": "feed_lift",
        "point_numbers": [21],
        "rail_slot": 1,
        "basis": "feed-lift workflow target point",
    },
    {
        "cluster_id": "waste_unload",
        "point_numbers": [22],
        "rail_slot": 1,
        "basis": "feed/waste workflow target point",
    },
    {
        "cluster_id": "photo_stage",
        "point_numbers": [64, 65, 76],
        "rail_slot": 2,
        "basis": "photo workflow target/check points",
    },
    {
        "cluster_id": "scrape_station",
        "point_numbers": [68, 77],
        "rail_slot": 2,
        "basis": "scrape holder put/pick target points",
    },
    {
        "cluster_id": "photo_scrape_combined",
        "point_numbers": [64, 65, 76, 68, 77],
        "rail_slot": 2,
        "basis": "photo and scrape interfaces share operation-semantic rail slot 2",
    },
    {
        "cluster_id": "staging_a_take",
        "point_numbers": list(range(46, 52)),
        "rail_slot": 2,
        "basis": "staging-A take workflow, slots 1-6",
    },
    {
        "cluster_id": "group_staging",
        "point_numbers": list(range(37, 41)),
        "rail_slot": 3,
        "basis": "group-staging put/pick workflow",
    },
    {
        "cluster_id": "staging_b",
        "point_numbers": list(range(53, 59)),
        "rail_slot": 3,
        "basis": "staging-B bottle workflow, slots 1-6",
    },
    {
        "cluster_id": "collection_station",
        "point_numbers": list(range(71, 75)),
        "rail_slot": 3,
        "basis": "collection bottle/holder put/pick workflow",
    },
    {
        "cluster_id": "staging_a_return",
        "point_numbers": list(range(78, 84)),
        "rail_slot": 3,
        "basis": "staging-A return workflow, slots 1-6",
    },
    {
        "cluster_id": "tool_station",
        "point_numbers": list(range(8, 11)),
        "rail_slot": 4,
        "basis": "tool-change workflow, tool slots 1-3",
    },
    {
        "cluster_id": "develop_tank_rack",
        "point_numbers": list(range(11, 19)),
        "rail_slot": 5,
        "basis": "develop workflow, tanks 1-8",
    },
    {
        "cluster_id": "develop_tower_positive_n",
        "point_numbers": list(range(11, 15)),
        "rail_slot": 5,
        "basis": "develop tanks 1-4 form one four-level target plane",
    },
    {
        "cluster_id": "develop_tower_negative_n",
        "point_numbers": list(range(15, 19)),
        "rail_slot": 5,
        "basis": "develop tanks 5-8 form the opposing four-level target plane",
    },
    {
        "cluster_id": "group_rack_4x3",
        "point_numbers": list(range(25, 37)),
        "rail_slot": 6,
        "basis": "group-rack 4x3 affine target grid",
    },
]

PAIR_NUMBERS = list(zip(range(46, 52), range(78, 84)))
REFERENCE_RAIL_SLOT = 2


def rounded(values: np.ndarray | list[float], digits: int = 6) -> list[float]:
    return [round(float(value), digits) for value in values]


def scalar(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def load_payload() -> tuple[dict, str]:
    raw = INPUT.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def flatten_robot_points(payload: dict) -> list[dict]:
    return [
        point
        for group in payload["data"]["robot"]["groups"]
        for point in group["points"]
    ]


def rail_positions_by_slot(payload: dict) -> dict[int, dict]:
    rail_groups = [
        group
        for group in payload["data"]["plc_servo"]["groups"]
        if group["key"] == "rail"
    ]
    if len(rail_groups) != 1:
        raise RuntimeError(f"Expected one PLC rail group, found {len(rail_groups)}")
    return {int(point["slot"]): point for point in rail_groups[0]["points"]}


def points_by_robot_name(robot_points: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for point in robot_points:
        name = point["robot_name"]
        if not name.startswith("P") or not name[1:].isdigit():
            continue
        if name in result:
            raise RuntimeError(f"Duplicate numbered robot point: {name}")
        result[name] = point
    return result


def point_xyz(point_lookup: dict[str, dict], number: int) -> np.ndarray:
    return np.asarray(point_lookup[f"P{number}"]["pose"][:3], dtype=float)


def pca_singular_values(points: np.ndarray) -> list[float]:
    centered = points - points.mean(axis=0)
    return rounded(np.linalg.svd(centered, compute_uv=False))


def fit_rail_frame(
    point_lookup: dict[str, dict],
    rail_by_slot: dict[int, dict],
) -> dict:
    take = np.stack([point_xyz(point_lookup, a) for a, _ in PAIR_NUMBERS])
    returned = np.stack([point_xyz(point_lookup, b) for _, b in PAIR_NUMBERS])
    raw_delta = returned - take
    q_take = float(rail_by_slot[2]["value"])
    q_return = float(rail_by_slot[3]["value"])
    delta_q = q_return - q_take
    if delta_q == 0:
        raise RuntimeError("Rail fit requires two distinct configured positions")

    mean_xy = raw_delta[:, :2].mean(axis=0)
    observed_xy_distance = float(np.linalg.norm(mean_xy))
    rail_translation_per_q = np.array(
        [-mean_xy[0] / delta_q, -mean_xy[1] / delta_q, 0.0]
    )
    l_axis = rail_translation_per_q / np.linalg.norm(rail_translation_per_q)
    n_axis = np.array([-l_axis[1], l_axis[0], 0.0])
    corrected_delta = raw_delta + delta_q * rail_translation_per_q
    residual_xy = corrected_delta[:, :2]
    residual_xy_norm = np.linalg.norm(residual_xy, axis=1)

    nominal_translation_per_q = l_axis
    nominal_corrected_delta = raw_delta + delta_q * nominal_translation_per_q
    nominal_residual_xy = nominal_corrected_delta[:, :2]
    relative_angle_deg = math.degrees(math.atan2(-l_axis[1], -l_axis[0]))

    pairs = []
    for (take_number, return_number), delta, corrected, residual_norm in zip(
        PAIR_NUMBERS,
        raw_delta,
        corrected_delta,
        residual_xy_norm,
    ):
        pairs.append(
            {
                "take_point": f"P{take_number}",
                "return_point": f"P{return_number}",
                "raw_return_minus_take_xyz_mm": rounded(delta),
                "corrected_return_minus_take_xyz_mm": rounded(corrected),
                "corrected_xy_residual_norm_mm": scalar(residual_norm),
            }
        )

    return {
        "fit_scope": "horizontal translation only",
        "pair_semantics": "Each P46-P51 target and P78-P83 target addresses the same physical staging-A slot at rail slots 2 and 3 respectively.",
        "take_rail": {"slot": 2, "configured_value_mm": q_take},
        "return_rail": {"slot": 3, "configured_value_mm": q_return},
        "configured_delta_q_mm": delta_q,
        "pair_count": len(PAIR_NUMBERS),
        "pairs": pairs,
        "mean_raw_return_minus_take_xyz_mm": rounded(raw_delta.mean(axis=0)),
        "sample_std_raw_delta_xyz_mm": rounded(raw_delta.std(axis=0, ddof=1)),
        "observed_mean_xy_distance_mm": scalar(observed_xy_distance),
        "fitted_scale_mm_translation_per_mm_command": scalar(
            observed_xy_distance / abs(delta_q), 9
        ),
        "controller_xyz_translation_per_positive_rail_mm": rounded(
            rail_translation_per_q, 9
        ),
        "l_axis_unit_in_controller_xyz": rounded(l_axis, 9),
        "n_axis_unit_in_controller_xyz": rounded(n_axis, 9),
        "signed_deviation_from_controller_negative_x_deg": scalar(relative_angle_deg),
        "fit_residuals": {
            "xy_rms_mm": scalar(np.sqrt(np.mean(residual_xy_norm**2))),
            "xy_max_mm": scalar(residual_xy_norm.max()),
            "xy_sample_std_mm": rounded(raw_delta[:, :2].std(axis=0, ddof=1)),
            "z_mean_mm_not_fitted": scalar(raw_delta[:, 2].mean()),
            "z_sample_std_mm_not_fitted": scalar(raw_delta[:, 2].std(ddof=1)),
            "z_interpretation": "Take/return process-height offset; not evidence of rail slope.",
        },
        "unit_scale_comparison": {
            "assumed_scale_mm_per_mm": 1.0,
            "xy_rms_mm": scalar(
                np.sqrt(np.mean(np.sum(nominal_residual_xy**2, axis=1)))
            ),
            "xy_max_mm": scalar(np.linalg.norm(nominal_residual_xy, axis=1).max()),
        },
        "common_frame_equation": {
            "reference_q_mm": q_take,
            "vector_form": "p_common_xyz = p_controller_xyz + (q_mm - reference_q_mm) * controller_xyz_translation_per_positive_rail_mm",
            "coordinate_form": "L=dot(p_controller,l_axis)+scale*(q-reference_q); N=dot(p_controller,n_axis); Z=controller_z",
            "handedness": "L cross N = +Z",
        },
    }


def cluster_record(
    binding: dict,
    point_lookup: dict[str, dict],
    rail_by_slot: dict[int, dict],
    fit: dict,
) -> dict:
    q_ref = float(fit["common_frame_equation"]["reference_q_mm"])
    q = float(rail_by_slot[binding["rail_slot"]]["value"])
    translation_per_q = np.asarray(
        fit["controller_xyz_translation_per_positive_rail_mm"], dtype=float
    )
    l_axis = np.asarray(fit["l_axis_unit_in_controller_xyz"], dtype=float)
    n_axis = np.asarray(fit["n_axis_unit_in_controller_xyz"], dtype=float)
    controller_xyz = np.stack(
        [point_xyz(point_lookup, number) for number in binding["point_numbers"]]
    )
    common_xyz = controller_xyz + (q - q_ref) * translation_per_q
    lnz = np.column_stack(
        [common_xyz @ l_axis, common_xyz @ n_axis, common_xyz[:, 2]]
    )
    minimum = lnz.min(axis=0)
    maximum = lnz.max(axis=0)
    point_records = [
        {
            "point": f"P{number}",
            "controller_xyz_mm": rounded(controller),
            "common_lnz_mm": rounded(transformed),
        }
        for number, controller, transformed in zip(
            binding["point_numbers"], controller_xyz, lnz
        )
    ]
    return {
        "cluster_id": binding["cluster_id"],
        "point_numbers": binding["point_numbers"],
        "rail_slot": binding["rail_slot"],
        "rail_configured_value_mm": q,
        "semantic_binding_basis": binding["basis"],
        "point_count": len(point_records),
        "interaction_target_cluster_lnz_mm": {
            "center": rounded(lnz.mean(axis=0)),
            "minimum": rounded(minimum),
            "maximum": rounded(maximum),
            "extents": rounded(maximum - minimum),
            "pca_singular_values": pca_singular_values(lnz),
        },
        "points": point_records,
        "boundary": "This cluster describes TCP interaction targets, not device center, outer dimensions, or collision geometry.",
    }


def center_by_id(clusters: list[dict]) -> dict[str, np.ndarray]:
    return {
        cluster["cluster_id"]: np.asarray(
            cluster["interaction_target_cluster_lnz_mm"]["center"], dtype=float
        )
        for cluster in clusters
    }


def delta_record(centers: dict[str, np.ndarray], source: str, target: str) -> dict:
    delta = centers[target] - centers[source]
    return {
        "source": source,
        "target": target,
        "delta_lnz_mm": rounded(delta),
        "planar_distance_mm": scalar(np.linalg.norm(delta[:2])),
    }


def main() -> None:
    payload, input_sha256 = load_payload()
    robot_points = flatten_robot_points(payload)
    point_lookup = points_by_robot_name(robot_points)
    rail_by_slot = rail_positions_by_slot(payload)

    missing_rail = [point["id"] for point in robot_points if "rail" not in point]
    with_rail = [point["id"] for point in robot_points if "rail" in point]
    fit = fit_rail_frame(point_lookup, rail_by_slot)
    clusters = [
        cluster_record(binding, point_lookup, rail_by_slot, fit)
        for binding in SEMANTIC_BINDINGS
    ]
    centers = center_by_id(clusters)
    order = sorted(centers, key=lambda name: float(centers[name][0]))
    q_ref = float(fit["common_frame_equation"]["reference_q_mm"])
    scale = float(fit["fitted_scale_mm_translation_per_mm_command"])

    output = {
        "schema_version": "0.1",
        "analysis_type": "rail-frame relative-layout constraint analysis",
        "source": {
            "interaction_points": str(INPUT.relative_to(ROOT)),
            "interaction_points_sha256": input_sha256,
            "controller_point_frame": "DOBOT User 0 / Tool 1 as stored",
            "units": {"translation": "mm", "rotation": "deg"},
        },
        "rail_field_audit": {
            "robot_record_count": len(robot_points),
            "base_record_count": sum(
                not point.get("is_derived", False) for point in robot_points
            ),
            "derived_record_count": sum(
                bool(point.get("is_derived", False)) for point in robot_points
            ),
            "records_with_rail_field": len(with_rail),
            "records_without_rail_field": len(missing_rail),
            "all_robot_records_lack_rail_field": len(with_rail) == 0,
            "consequence": "Rail bindings below are operation-semantic joins. They do not modify or backfill any robot-point record.",
        },
        "semantic_binding_provenance": {
            "rail_values": {
                "source": "interaction_points.json data.plc_servo.groups[key=rail]",
                "values_by_slot_mm": {
                    str(slot): float(rail_by_slot[slot]["value"])
                    for slot in sorted(rail_by_slot)
                },
            },
            "point_family_to_rail_slot": {
                "source_kind": "operation_semantics_transcribed_for_analysis",
                "human_readable_source": "pTLC实验室仿真重建基线_2026-08-13.md sections 7.2, 8 and appendix B",
                "boundary": "The family-to-slot relation is absent from the point JSON and must be checked against the operation workflow whenever the workflow changes.",
                "bindings": [
                    {
                        "cluster_id": binding["cluster_id"],
                        "point_range": [
                            min(binding["point_numbers"]),
                            max(binding["point_numbers"]),
                        ],
                        "explicit_point_numbers": binding["point_numbers"],
                        "rail_slot": binding["rail_slot"],
                        "basis": binding["basis"],
                    }
                    for binding in SEMANTIC_BINDINGS
                ],
            },
        },
        "rail_fit": fit,
        "rail_carriage_l_positions_relative_to_reference": {
            "reference_slot": REFERENCE_RAIL_SLOT,
            "reference_configured_q_mm": q_ref,
            "positions_by_slot_mm": {
                str(slot): scalar((float(rail_by_slot[slot]["value"]) - q_ref) * scale)
                for slot in sorted(rail_by_slot)
            },
            "boundary": "Slots 1/2 and 5/6 share configured positions but retain different operation semantics.",
        },
        "interaction_target_clusters": clusters,
        "layout_constraints": {
            "linear_order_by_cluster_center_l": order,
            "develop_inventory_u_cluster": {
                "members": [
                    "develop_tower_positive_n",
                    "develop_tower_negative_n",
                    "group_rack_4x3",
                ],
                "evidence": "P11-P14 and P15-P18 are opposing four-level target planes; P25-P36 is a four-level by three-bay plane approximately 124 mm farther along +L.",
                "recommended_topology": "Two opposing 1x4 side towers plus a 4x3 back-wall rack under one U-shaped parent cluster.",
                "boundary": "Target planes constrain openings and approach corridors, not enclosure wall offsets.",
            },
            "collection_cluster": {
                "members": ["staging_b", "collection_station"],
                "relative_center": delta_record(
                    centers, "staging_b", "collection_station"
                ),
                "recommended_topology": "Keep staging-B adjacent to collection rather than in a detached inventory/exploded zone.",
            },
            "selected_relative_centers": [
                delta_record(centers, "develop_tank_rack", "group_rack_4x3"),
                delta_record(centers, "photo_scrape_combined", "collection_station"),
                delta_record(centers, "staging_a_take", "staging_a_return"),
            ],
        },
        "uncertainty_and_identifiability": [
            {
                "item": "world rigid transform",
                "status": "unidentifiable",
                "effect": "The constraint frame may be translated and yaw-rotated as a whole without changing any fitted relation.",
            },
            {
                "item": "rail vertical slope and full travel linearity",
                "status": "not identified",
                "effect": "Only one 182 mm paired baseline exists; the 12.545 mm take/return Z offset is deliberately excluded from the rail fit.",
            },
            {
                "item": "TCP and tool-frame calibration",
                "status": "unavailable",
                "effect": "Interaction targets are precise controller records but cannot directly locate device exterior surfaces.",
            },
            {
                "item": "device center, dimensions and collision envelope",
                "status": "unidentifiable from targets alone",
                "effect": "Use photographs or CAD for enclosure geometry; never move a target point to fit a proxy AABB.",
            },
            {
                "item": "semantic rail bindings",
                "status": "workflow-derived",
                "effect": "All robot records lack a rail field, so a changed operation script can invalidate a binding without changing the point snapshot.",
            },
            {
                "item": "fit repeatability",
                "status": "estimated from six paired slots",
                "effect": "Use XY RMS and maximum residual from rail_fit as the empirical consistency bound; it is not a hardware accuracy certificate.",
            },
        ],
        "allowed_use": [
            "Relative layout blocking in the fitted L/N/Z constraint frame",
            "Interaction-marker placement and station-topology checks",
            "Testing whether proxy openings contain their required point clusters and approach corridors",
        ],
        "forbidden_claims": [
            "Surveyed laboratory world coordinates",
            "Verified robot-to-rail or TCP calibration",
            "Device exterior dimensions inferred solely from target clusters",
            "Collision-safe or reachable motion without URDF, TCP and collision validation",
        ],
    }
    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "input_sha256": input_sha256,
                "cluster_count": len(clusters),
                "fit_xy_rms_mm": fit["fit_residuals"]["xy_rms_mm"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
