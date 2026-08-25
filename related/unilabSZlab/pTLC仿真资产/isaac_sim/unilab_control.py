#!/usr/bin/env python3
"""Uni-Lab Robotics commissioning contract for the pTLC Isaac simulation.

This module deliberately contains no Isaac imports.  It adapts the CR5
``MoveTargetCommand`` contract from ``unilab_robot_template`` to an injected
geometry-transition renderer.  The real renderer lives in
``run_unilab_isaac_validation.py``; unit tests inject a deterministic fake.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any


PACKAGE_DIRS = (
    "unilab-robot-contracts",
    "unilab-arm-cr5",
    "unilab-rail-mounted-arm",
)

_TEMPLATE_ROOT: Path | None = None


def configure_template_imports(template_root: Path) -> tuple[str, ...]:
    """Add the exact template source packages required by this adapter."""

    root = template_root.expanduser().resolve()
    global _TEMPLATE_ROOT

    missing: list[str] = []
    paths: list[str] = []
    for distribution in PACKAGE_DIRS:
        source = root / "packages" / distribution / "src"
        if not source.is_dir():
            missing.append(str(source))
            continue
        value = str(source)
        if value not in sys.path:
            sys.path.insert(0, value)
        paths.append(value)
    binding_source = (
        root
        / "packages/unilab-robot-runtime/src/unilab_robot_runtime/binding.py"
    )
    if not binding_source.is_file():
        missing.append(str(binding_source))
    if missing:
        raise FileNotFoundError(
            "Uni-Lab Robotics template packages are missing: " + ", ".join(missing)
        )
    _TEMPLATE_ROOT = root
    return tuple(paths)


def _load_build_test_runtime() -> Callable[..., Any]:
    """Load the template binding directly, avoiding its optional YAML factory import."""

    if _TEMPLATE_ROOT is None:
        raise RuntimeError("configure_template_imports must be called first")
    module_name = "ptlc_unilab_robot_runtime_binding"
    loaded = sys.modules.get(module_name)
    if loaded is None:
        source = (
            _TEMPLATE_ROOT
            / "packages/unilab-robot-runtime/src/unilab_robot_runtime/binding.py"
        )
        spec = importlib.util.spec_from_file_location(module_name, source)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load RuntimeBinding source: {source}")
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = loaded
        spec.loader.exec_module(loaded)
    return loaded.build_test_runtime


def load_json_document(path: Path) -> dict[str, Any]:
    """Load one JSON object and reject other top-level values."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return document


def sha256_file(path: Path) -> str:
    """Return the exact SHA-256 of one evidence input."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible mapping using the command canonicalization style."""

    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tool_context_document() -> dict[str, Any]:
    """Return the identity TCP context used only by this geometry simulation."""

    return {
        "schema": "unilab.tool-context/v1",
        "context_id": "ptlc-simulation-no-tool@1.0.0",
        "attachment_generation": 1,
        "mount_to_tcp": {
            "xyz_m": [0.0, 0.0, 0.0],
            "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
        },
        "qualification": "simulation-only-uncalibrated",
    }


def hardware_profile_document() -> dict[str, Any]:
    """Return the exact simulation profile locked by all commissioning commands."""

    return {
        "schema": "unilab.hardware-profile/simulation-v1",
        "profile_id": "ptlc-cr5-isaac-geometry-sim@1.0.0",
        "mode": "simulation",
        "backend_contract": "moveit-compatible-commissioning",
        "transport": "isaac-geometry-direct",
        "endpoint_ids": ["sim://isaac/ptlc/cr5"],
        "interlock_mode": "simulation",
        "hardware_connections": "none",
    }


class IsaacGeometryPort:
    """MoveIt-compatible commissioning port backed by an Isaac frame renderer.

    ``render_transition`` is the settlement boundary.  A completion receipt is
    returned only after that callback has written and validated all requested
    frames.  If it raises, the upstream template adapter conservatively records
    ``execution_unknown`` and fences subsequent motion.
    """

    def __init__(
        self,
        *,
        model: Any,
        tool_context: Any,
        targets: Mapping[str, Any],
        initial_target_ref: str,
        render_transition: Callable[
            [tuple[float, ...], tuple[float, ...], str, str], Mapping[str, Any]
        ],
    ) -> None:
        if initial_target_ref not in targets:
            raise ValueError(f"Initial target is not in the PointSet: {initial_target_ref}")
        self.model = model
        self.tool_context = tool_context
        self.targets = dict(targets)
        self.render_transition = render_transition
        initial = self.targets[initial_target_ref]
        positions = getattr(initial, "joint_positions", None)
        if positions is None:
            raise ValueError("The initial Isaac target must be a joint target")
        self.joints = tuple(float(value) for value in positions)
        self._target_by_joint_key = {
            self._joint_key(target.joint_positions): target_ref
            for target_ref, target in self.targets.items()
            if getattr(target, "joint_positions", None) is not None
        }
        self.results: dict[str, dict[str, Any]] = {}
        self.online = True
        self.idle = True
        self.active_command_id: str | None = None

    @staticmethod
    def _joint_key(values: Sequence[float]) -> tuple[float, ...]:
        return tuple(round(float(value), 12) for value in values)

    def read_commissioning_state(self) -> Mapping[str, Any]:
        """Return fresh joint and FK-derived TCP state for maintenance gating."""

        pose = self.model.forward_kinematics(self.joints, self.tool_context)
        return {
            "observed_at": time.time(),
            "max_age_s": 2.0,
            "source": "simulation-only:isaac-geometry-port",
            "online": self.online,
            "idle": self.idle,
            "active_command_id": self.active_command_id,
            "execution_fenced": False,
            "joint_positions": list(self.joints),
            "tcp_pose": {
                "frame_ref": pose.frame_ref,
                "xyz_m": list(pose.xyz_m),
                "orientation_xyzw": list(pose.orientation_xyzw),
            },
        }

    def execute_joint_target(
        self,
        *,
        group_name: str,
        joint_names: Sequence[str],
        target: Sequence[float],
        command_id: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Render one approved joint target and return a bound completion receipt."""

        if group_name != self.model.planning_group:
            raise ValueError("Isaac port received an unexpected planning group")
        if tuple(joint_names) != tuple(self.model.joint_names):
            raise ValueError("Isaac port joint order differs from the exact CR5 model")
        values = tuple(float(value) for value in target)
        if len(values) != len(self.model.joint_specs) or not all(
            math.isfinite(value) for value in values
        ):
            raise ValueError("Isaac port requires six finite CR5 joint values")
        target_ref = self._target_by_joint_key.get(self._joint_key(values))
        if target_ref is None:
            raise ValueError("Isaac port accepts only targets resolved from the active PointSet")
        speed = float(parameters.get("speed", 0.0))
        acceleration = float(parameters.get("acceleration", 0.0))
        if not 0.0 < speed <= 0.25 or not 0.0 < acceleration <= 0.25:
            raise ValueError("Isaac commissioning scale must remain in (0, 0.25]")

        before = self.joints
        self.idle = False
        self.active_command_id = command_id
        render_evidence = self.render_transition(before, values, command_id, target_ref)
        self.joints = values
        self.idle = True
        self.active_command_id = None
        receipt = {
            "command_id": command_id,
            "state": "succeeded",
            "completed": True,
            "target_ref": target_ref,
            "joint_positions_si": list(values),
            "joint_degrees": [math.degrees(value) for value in values],
            "transport": "isaac-geometry-direct",
            "motion_profile_ref": str(parameters["motion_profile_ref"]),
            "velocity_scale": speed,
            "acceleration_scale": acceleration,
            "render_evidence": dict(render_evidence),
        }
        self.results[command_id] = receipt
        return receipt

    def execute_cartesian_target(self, **_: Any) -> Mapping[str, Any]:
        """Reject Cartesian dispatch until pose convention and IK are validated."""

        raise NotImplementedError(
            "The pTLC Isaac validation supports versioned joint targets only"
        )

    def query_command(self, command_id: str) -> Mapping[str, Any] | None:
        """Return a prior receipt without replaying motion."""

        return self.results.get(command_id)

    def cancel(self, command_id: str) -> bool:
        """Confirm a normal simulated stop only for the active command."""

        if command_id != self.active_command_id:
            return False
        self.idle = True
        self.active_command_id = None
        return True

    def apply_tool_context(self, tool_context: Any) -> Mapping[str, Any]:
        """Accept only the same immutable simulation ToolContext."""

        if tool_context.digest != self.tool_context.digest:
            raise ValueError("Isaac port refuses a different ToolContext digest")
        self.tool_context = tool_context
        return {
            "applied": True,
            "tool_context_digest": tool_context.digest,
            "attachment_generation": tool_context.attachment_generation,
        }


class _RuntimeMarker:
    """Minimal simulation runtime retained behind the template RuntimeBinding."""

    has_unsettled_fence = False


def execute_point_sequence(
    *,
    point_set: Mapping[str, Any],
    render_transition: Callable[
        [tuple[float, ...], tuple[float, ...], str, str], Mapping[str, Any]
    ],
    target_refs: Sequence[str],
    source_boot_id: str = "ptlc-isaac-validation-boot-1",
) -> dict[str, Any]:
    """Execute versioned CR5 targets through the template maintenance surface."""

    if not target_refs:
        raise ValueError("At least one target_ref is required")

    from unilab_arm_cr5 import MODEL_DESCRIPTOR
    from unilab_arm_cr5.adapters import MoveItCommissioningAdapter
    from unilab_robot_contracts import (
        BackendKind,
        CommandState,
        DeploymentMode,
        HardwareProfile,
        InterlockMode,
        MotionTargetResolver,
        MoveTargetCommand,
        RigidTransform,
        ToolContext,
    )
    build_test_runtime = _load_build_test_runtime()

    tool_document = tool_context_document()
    tool_digest = canonical_digest(tool_document)
    tool_context = ToolContext(
        context_id=str(tool_document["context_id"]),
        digest=tool_digest,
        mount_to_tcp=RigidTransform.identity(),
        attachment_generation=int(tool_document["attachment_generation"]),
    )
    resolver = MotionTargetResolver(
        point_set,
        model=MODEL_DESCRIPTOR,
        tool_context=tool_context,
    )
    targets = resolver.resolve_all()
    for target_ref in target_refs:
        if target_ref not in targets:
            raise ValueError(f"PointSet does not contain requested target: {target_ref}")

    profile_document = hardware_profile_document()
    profile_digest = canonical_digest(profile_document)
    profile = HardwareProfile(
        profile_id=str(profile_document["profile_id"]),
        digest=profile_digest,
        mode=DeploymentMode.SIMULATION,
        backend=BackendKind.MOVEIT,
        endpoint_ids=frozenset(str(value) for value in profile_document["endpoint_ids"]),
        interlock_mode=InterlockMode.SIMULATION,
    )
    port = IsaacGeometryPort(
        model=MODEL_DESCRIPTOR,
        tool_context=tool_context,
        targets=targets,
        initial_target_ref=str(target_refs[0]),
        render_transition=render_transition,
    )
    adapter = MoveItCommissioningAdapter(
        port=port,
        model=MODEL_DESCRIPTOR,
        targets=targets,
        point_set_revision=resolver.revision,
        hardware_profile_digest=profile.digest,
        tool_context_digest=tool_context.digest,
    )
    binding = build_test_runtime(
        _RuntimeMarker(),
        profile.endpoint_ids,
        owner_id="ptlc-unilab-isaac-validation",
        commissioning_port=adapter,
        deployment_mode=profile.mode,
    )

    trace: list[dict[str, Any]] = []
    session = binding.open_maintenance_session("ptlc-simulation-operator")
    try:
        for sequence, target_ref in enumerate(target_refs, start=1):
            command = MoveTargetCommand(
                command_id=f"ptlc-isaac-{sequence:03d}-{target_ref.rsplit('.', 1)[-1]}",
                hardware_profile_digest=profile.digest,
                source_boot_id=source_boot_id,
                monotonic_sequence=sequence,
                motion_profile_ref="ptlc-simulation-slow@1.0.0",
                velocity_scale=0.10,
                acceleration_scale=0.10,
                target_ref=str(target_ref),
                target_revision=resolver.revision,
            )
            result = session.execute(command)
            snapshot = session.snapshot()
            trace.append(
                {
                    "command": command.canonical_payload(),
                    "fingerprint": command.fingerprint(),
                    "result": {
                        "command_id": result.command_id,
                        "state": result.state.value,
                        "success": result.success,
                        "message": result.message,
                        "output": dict(result.output),
                    },
                    "post_snapshot": {
                        "source": snapshot.source,
                        "online": snapshot.online,
                        "idle": snapshot.idle,
                        "execution_fenced": snapshot.execution_fenced,
                        "joint_positions_si": [
                            asdict(value) for value in snapshot.joint_positions or ()
                        ],
                    },
                }
            )
            if result.state is not CommandState.SUCCEEDED:
                raise RuntimeError(
                    f"Uni-Lab commissioning command failed: {result.command_id}: "
                    f"{result.state.value}: {result.message}"
                )
    finally:
        session.close()
        binding.close()

    return {
        "profile": {**profile_document, "digest": profile.digest},
        "tool_context": {**tool_document, "digest": tool_context.digest},
        "point_set_revision": resolver.revision,
        "target_refs": list(target_refs),
        "commands": trace,
        "final_joint_positions_si": list(port.joints),
        "all_commands_succeeded": all(
            record["result"]["state"] == "succeeded" for record in trace
        ),
        "hardware_connections": "none",
    }


__all__ = [
    "IsaacGeometryPort",
    "canonical_digest",
    "configure_template_imports",
    "execute_point_sequence",
    "hardware_profile_document",
    "load_json_document",
    "sha256_file",
    "tool_context_document",
]
