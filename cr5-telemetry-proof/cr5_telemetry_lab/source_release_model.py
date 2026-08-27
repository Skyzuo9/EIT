"""从只读摘要锁定 ZIP SourceRelease 构造 Workbench ``package_moveit`` 模型。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

_DEVICE_ID = re.compile(r"^[A-Za-z0-9_]+$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "lab.robot_source_releases/v0"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST = _REPOSITORY_ROOT / "config" / "robot-source-releases.json"
_DEFAULT_CACHE = (
    _REPOSITORY_ROOT
    / "cr5-telemetry-proof"
    / ".unilabos"
    / "cache"
    / "robot-source-releases"
)
_receipt_lock = threading.RLock()
_verified_receipts: dict[str, "SourceReleaseReceipt"] = {}


@dataclass(frozen=True, slots=True)
class SourceReleaseReceipt:
    """一次通过摘要锁定的只读源发布读取凭据。"""

    model_id: str
    display_name: str
    archive_path: Path
    archive_sha256: str
    repository: str
    exact_ref: str
    urdf_member: str
    urdf_sha256: str
    authority: str
    qualification: str
    license_evidence: str
    archive_read_only: bool = True


@dataclass(frozen=True, slots=True)
class SourceReleaseModelBundle:
    """满足 UniLab ``package_moveit`` Provider 契约的派生快照。"""

    execution_urdf: str
    render_urdf: str
    srdf: str
    ros2_controllers: dict[str, Any]
    moveit_controllers: dict[str, Any]
    kinematics: dict[str, Any]
    joint_limits: dict[str, Any]
    source_digest: str
    mesh_paths: tuple[Path, ...]
    qualified_joint_names: tuple[str, ...]
    topology_digest: str
    rviz_required: bool = False


def build_dobot_cr5_model(
    *,
    device_id: str,
    position: Mapping[str, Any] | None = None,
    rotation: Mapping[str, Any] | None = None,
) -> SourceReleaseModelBundle:
    """从固定的 Dobot ROS 2 ZIP 构造 CR5 派生模型。"""

    return build_source_release_model(
        "dobot_cr5",
        device_id=device_id,
        position=position,
        rotation=rotation,
    )


def build_fairino_fr5_model(
    *,
    device_id: str,
    position: Mapping[str, Any] | None = None,
    rotation: Mapping[str, Any] | None = None,
) -> SourceReleaseModelBundle:
    """从固定的 FAIRINO ROS 2 ZIP 构造 FR5 派生模型。"""

    return build_source_release_model(
        "fairino_fr5",
        device_id=device_id,
        position=position,
        rotation=rotation,
    )


def build_duco_gcr5_910_model(
    *,
    device_id: str,
    position: Mapping[str, Any] | None = None,
    rotation: Mapping[str, Any] | None = None,
) -> SourceReleaseModelBundle:
    """从摘要锁定的项目 CAD URDF 构造 DUCO GCR5-910 预览模型。"""

    return build_source_release_model(
        "duco_gcr5_910",
        device_id=device_id,
        position=position,
        rotation=rotation,
    )


def build_source_release_model(
    model_id: str,
    *,
    device_id: str,
    position: Mapping[str, Any] | None = None,
    rotation: Mapping[str, Any] | None = None,
    manifest_path: Path | None = None,
    source_root: Path | None = None,
    cache_root: Path | None = None,
) -> SourceReleaseModelBundle:
    """验证源 ZIP，只物化被选 URDF 引用的 mesh，再生成双视图模型。"""

    normalized_device_id = str(device_id).strip()
    if _DEVICE_ID.fullmatch(normalized_device_id) is None:
        raise ValueError("SourceRelease device_id 只能包含字母、数字与下划线")
    manifest, manifest_file = _load_manifest(manifest_path)
    spec = _release_spec(manifest, model_id)
    resolved_source_root = source_root or _resolve_source_root(manifest)
    archive_path = (resolved_source_root / _text(spec, "archive")).resolve()
    expected_archive_digest = _digest(spec, "archive_sha256")
    before = _read_only_stat(archive_path)
    verify_source_release_archive(archive_path, expected_archive_digest)

    try:
        with ZipFile(archive_path, "r") as archive:
            urdf_member = _text(spec, "urdf_member")
            urdf_bytes = _read_member(archive, urdf_member)
            actual_urdf_digest = hashlib.sha256(urdf_bytes).hexdigest()
            expected_urdf_digest = _digest(spec, "urdf_sha256")
            if actual_urdf_digest != expected_urdf_digest:
                raise ValueError(f"{model_id} ZIP 内 URDF 摘要漂移")
            source_root_xml = _parse_source_urdf(urdf_bytes, model_id=model_id)
            mesh_names = _referenced_mesh_names(source_root_xml)
            mesh_paths = _materialize_meshes(
                archive,
                model_id=model_id,
                archive_digest=expected_archive_digest,
                member_prefix=_text(spec, "mesh_member_prefix"),
                mesh_names=mesh_names,
                cache_root=cache_root or _resolve_cache_root(),
            )
    except BadZipFile as error:
        raise ValueError(f"{model_id} SourceRelease 不是有效 ZIP") from error
    after = _read_only_stat(archive_path)
    if after != before:
        raise RuntimeError(f"{model_id} SourceRelease 在只读编译期间发生变化")

    receipt = SourceReleaseReceipt(
        model_id=model_id,
        display_name=_text(spec, "display_name"),
        archive_path=archive_path,
        archive_sha256=expected_archive_digest,
        repository=_text(spec, "repository"),
        exact_ref=_text(spec, "exact_ref"),
        urdf_member=_text(spec, "urdf_member"),
        urdf_sha256=expected_urdf_digest,
        authority=_text(spec, "authority", default="manufacturer"),
        qualification=_text(spec, "qualification", default="kinematic-preview-only"),
        license_evidence=_text(spec, "license_evidence", default="not-recorded"),
    )
    with _receipt_lock:
        _verified_receipts[model_id] = receipt

    return _compile_bundle(
        model_id=model_id,
        device_id=normalized_device_id,
        spec=spec,
        source_root=source_root_xml,
        source_digest=expected_archive_digest,
        urdf_digest=expected_urdf_digest,
        mesh_paths=mesh_paths,
        position=position,
        rotation=rotation,
        manifest_path=manifest_file,
    )


def get_verified_source_release_receipt(model_id: str) -> SourceReleaseReceipt | None:
    """只返回本进程已被 Provider 实际验证过的源发布凭据。"""

    with _receipt_lock:
        return _verified_receipts.get(str(model_id))


def verify_source_release_archive(path: Path, expected_sha256: str) -> None:
    """流式校验整个源 ZIP；不解压、不写回。"""

    expected = str(expected_sha256).lower()
    if _DIGEST.fullmatch(expected) is None:
        raise ValueError("SourceRelease 期望摘要必须是 SHA-256")
    archive = Path(path).resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"SourceRelease ZIP 不存在: {archive}")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f"SourceRelease ZIP 摘要漂移: {archive.name}")


def _compile_bundle(
    *,
    model_id: str,
    device_id: str,
    spec: Mapping[str, Any],
    source_root: ET.Element,
    source_digest: str,
    urdf_digest: str,
    mesh_paths: tuple[Path, ...],
    position: Mapping[str, Any] | None,
    rotation: Mapping[str, Any] | None,
    manifest_path: Path,
) -> SourceReleaseModelBundle:
    source_joint_names = _text_sequence(spec, "source_joint_names")
    canonical_joint_names = _text_sequence(spec, "canonical_joint_names")
    if len(source_joint_names) != 6 or len(canonical_joint_names) != 6:
        raise ValueError(f"{model_id} 当前适配器要求 exact 六轴关节")
    if len(set(source_joint_names)) != 6 or len(set(canonical_joint_names)) != 6:
        raise ValueError(f"{model_id} 关节名存在重复")

    source_links = tuple(link.attrib.get("name", "") for link in source_root.findall("link"))
    if not source_links or len(set(source_links)) != len(source_links):
        raise ValueError(f"{model_id} URDF link 缺失或重复")
    expected_root_link = _text(spec, "source_root_link")
    actual_root_link = _root_link(source_root)
    if actual_root_link != expected_root_link:
        raise ValueError(
            f"{model_id} URDF 根 link 漂移: {actual_root_link} != {expected_root_link}"
        )
    source_tip_link = _text(spec, "source_tip_link")
    if source_tip_link not in source_links:
        raise ValueError(f"{model_id} URDF tip link 缺失")

    family_slug = _safe_identifier(model_id)
    prefix = f"{device_id}_"
    link_names = {
        source_name: f"{prefix}{family_slug}_{_safe_identifier(source_name)}"
        for source_name in source_links
    }
    joint_names = {
        source_name: f"{prefix}{canonical_name}"
        for source_name, canonical_name in zip(
            source_joint_names,
            canonical_joint_names,
            strict=True,
        )
    }
    qualified_joint_names = tuple(joint_names[name] for name in source_joint_names)
    render_root = deepcopy(source_root)
    render_root.set("name", f"{prefix}{family_slug}")
    _strip_runtime_extensions(render_root)
    _qualify_tree(
        render_root,
        model_id=model_id,
        device_id=device_id,
        family_slug=family_slug,
        link_names=link_names,
        joint_names=joint_names,
        source_joint_names=source_joint_names,
        mesh_paths=mesh_paths,
        preview_effort_defaults=spec.get("preview_effort_defaults"),
        preview_velocity_default=spec.get("preview_velocity_default"),
        preview_position_limits=spec.get("preview_position_limits"),
        render=True,
    )
    device_link = f"{prefix}device_link"
    ET.SubElement(render_root, "link", {"name": device_link})
    render_root.append(
        _fixed_joint(
            name=f"{prefix}{family_slug}_base_mount_joint",
            parent=device_link,
            child=link_names[actual_root_link],
        )
    )

    execution_root = deepcopy(render_root)
    for mesh in execution_root.findall(".//mesh"):
        mesh_name = PurePosixPath(str(mesh.attrib.get("filename", ""))).name
        mesh_path = next((path for path in mesh_paths if path.name == mesh_name), None)
        if mesh_path is None:
            raise ValueError(f"{model_id} execution mesh 未受 SourceRelease 管理: {mesh_name}")
        mesh.set("filename", mesh_path.resolve().as_uri())
    execution_root.insert(
        0,
        _fixed_joint(
            name=f"{prefix}world_mount_joint",
            parent="world",
            child=device_link,
            xyz=_vector(position, scale=0.001),
            rpy=_vector(rotation, scale=1.0),
        ),
    )
    _append_mock_ros2_control(execution_root, prefix=prefix, joint_names=canonical_joint_names)

    topology_digest = hashlib.sha256(
        json.dumps(
            {
                "adapter": "robot-source-release/v0",
                "manifest": manifest_path.name,
                "model_id": model_id,
                "device_id": device_id,
                "source_digest": source_digest,
                "urdf_digest": urdf_digest,
                "qualified_joint_names": qualified_joint_names,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    planning_group = f"{prefix}{family_slug}_arm"
    controller_name = f"{prefix}{family_slug}_controller"
    joint_limit_config = _joint_limit_config(render_root, qualified_joint_names)
    return SourceReleaseModelBundle(
        execution_urdf=ET.tostring(execution_root, encoding="unicode"),
        render_urdf=ET.tostring(render_root, encoding="unicode"),
        srdf=_build_srdf(
            robot_name=f"{prefix}{family_slug}",
            planning_group=planning_group,
            base_link=device_link,
            tip_link=link_names[source_tip_link],
        ),
        ros2_controllers=_ros2_controllers(controller_name, qualified_joint_names),
        moveit_controllers=_moveit_controllers(controller_name, qualified_joint_names),
        kinematics={
            planning_group: {
                "kinematics_solver": "kdl_kinematics_plugin/KDLKinematicsPlugin",
                "kinematics_solver_search_resolution": 0.005,
                "kinematics_solver_timeout": 0.05,
            }
        },
        joint_limits={"joint_limits": joint_limit_config},
        source_digest=source_digest,
        mesh_paths=mesh_paths,
        qualified_joint_names=qualified_joint_names,
        topology_digest=topology_digest,
    )


def _load_manifest(path: Path | None) -> tuple[Mapping[str, Any], Path]:
    candidate = Path(
        path
        or os.environ.get("EIT_ROBOT_SOURCE_MANIFEST", "")
        or _DEFAULT_MANIFEST
    ).expanduser().resolve()
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"机器人 SourceRelease 清单不存在: {candidate}") from error
    if not isinstance(value, Mapping) or value.get("schema") != _SCHEMA:
        raise ValueError("机器人 SourceRelease 清单 schema 无效")
    return value, candidate


def _resolve_source_root(manifest: Mapping[str, Any]) -> Path:
    source = manifest.get("source_root")
    if not isinstance(source, Mapping):
        raise ValueError("SourceRelease 清单缺少 source_root")
    environment = _text(source, "environment")
    configured = os.environ.get(environment)
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / _text(source, "default_home_relative")).resolve()


def _resolve_cache_root() -> Path:
    configured = os.environ.get("EIT_ROBOT_SOURCE_CACHE")
    return Path(configured).expanduser().resolve() if configured else _DEFAULT_CACHE


def _release_spec(manifest: Mapping[str, Any], model_id: str) -> Mapping[str, Any]:
    releases = manifest.get("releases")
    if not isinstance(releases, Mapping):
        raise ValueError("SourceRelease 清单缺少 releases")
    value = releases.get(str(model_id))
    if not isinstance(value, Mapping):
        raise KeyError(f"未知机器人 SourceRelease: {model_id}")
    return value


def _read_only_stat(path: Path) -> tuple[int, int, int]:
    if not path.is_file():
        raise FileNotFoundError(f"SourceRelease ZIP 不存在: {path}")
    status = path.stat()
    return status.st_ino, status.st_size, status.st_mtime_ns


def _read_member(archive: ZipFile, member: str) -> bytes:
    if PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts:
        raise ValueError("SourceRelease 成员路径不安全")
    try:
        with archive.open(member, "r") as stream:
            return stream.read()
    except KeyError as error:
        raise ValueError(f"SourceRelease ZIP 缺少成员: {member}") from error


def _parse_source_urdf(data: bytes, *, model_id: str) -> ET.Element:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"{model_id} SourceRelease URDF XML 无效") from error
    if root.tag != "robot":
        raise ValueError(f"{model_id} SourceRelease URDF 根节点必须是 robot")
    return root


def _referenced_mesh_names(root: ET.Element) -> tuple[str, ...]:
    names: list[str] = []
    for mesh in root.findall(".//mesh"):
        filename = str(mesh.attrib.get("filename") or "")
        name = PurePosixPath(filename).name
        if not name or name in {".", ".."}:
            raise ValueError("SourceRelease URDF mesh URI 无效")
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError("SourceRelease URDF 未引用任何 mesh")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("SourceRelease mesh 文件名在大小写折叠后重复")
    return tuple(names)


def _materialize_meshes(
    archive: ZipFile,
    *,
    model_id: str,
    archive_digest: str,
    member_prefix: str,
    mesh_names: tuple[str, ...],
    cache_root: Path,
) -> tuple[Path, ...]:
    output_root = cache_root / archive_digest / model_id / "meshes"
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for name in mesh_names:
        data = _read_member(archive, f"{member_prefix}{name}")
        if not data:
            raise ValueError(f"{model_id} SourceRelease mesh 为空: {name}")
        output = output_root / name
        expected = hashlib.sha256(data).hexdigest()
        if not output.is_file() or _file_digest(output) != expected:
            with tempfile.NamedTemporaryFile(dir=output_root, delete=False) as stream:
                stream.write(data)
                temporary = Path(stream.name)
            os.replace(temporary, output)
        if _file_digest(output) != expected:
            raise ValueError(f"{model_id} SourceRelease mesh 缓存摘要不一致: {name}")
        outputs.append(output.resolve())
    return tuple(outputs)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _root_link(root: ET.Element) -> str:
    links = {str(link.attrib.get("name") or "") for link in root.findall("link")}
    children = {
        str(child.attrib.get("link") or "")
        for child in root.findall("joint/child")
    }
    candidates = links - children
    if len(candidates) != 1:
        raise ValueError("SourceRelease URDF 必须有且只有一个根 link")
    return next(iter(candidates))


def _strip_runtime_extensions(root: ET.Element) -> None:
    for child in tuple(root):
        if child.tag in {"gazebo", "transmission", "ros2_control"}:
            root.remove(child)


def _qualify_tree(
    root: ET.Element,
    *,
    model_id: str,
    device_id: str,
    family_slug: str,
    link_names: Mapping[str, str],
    joint_names: Mapping[str, str],
    source_joint_names: Sequence[str],
    mesh_paths: tuple[Path, ...],
    preview_effort_defaults: object,
    preview_velocity_default: object,
    preview_position_limits: object,
    render: bool,
) -> None:
    for link in root.findall("link"):
        source_name = str(link.attrib.get("name") or "")
        qualified = link_names.get(source_name)
        if qualified is None:
            raise ValueError(f"{model_id} URDF link 未映射: {source_name}")
        link.set("name", qualified)
    movable_seen: list[str] = []
    effort_defaults = _number_sequence_or_empty(preview_effort_defaults)
    velocity_default = _positive_number_or_none(preview_velocity_default)
    position_limits = _position_limits_or_empty(preview_position_limits)
    for joint in root.findall("joint"):
        source_name = str(joint.attrib.get("name") or "")
        joint_type = str(joint.attrib.get("type") or "")
        if joint_type == "fixed":
            joint.set("name", f"{device_id}_{family_slug}_{_safe_identifier(source_name)}")
        else:
            qualified = joint_names.get(source_name)
            if qualified is None:
                raise ValueError(f"{model_id} 出现未签署的可动关节: {source_name}")
            joint.set("name", qualified)
            movable_seen.append(source_name)
            _validate_and_repair_preview_limit(
                joint,
                model_id=model_id,
                joint_index=source_joint_names.index(source_name),
                effort_defaults=effort_defaults,
                velocity_default=velocity_default,
                position_limits=position_limits,
            )
        for relation in ("parent", "child"):
            element = joint.find(relation)
            if element is None:
                raise ValueError(f"{model_id} URDF joint 缺少 {relation}")
            source_link = str(element.attrib.get("link") or "")
            if source_link not in link_names:
                raise ValueError(f"{model_id} URDF joint 引用未知 link: {source_link}")
            element.set("link", link_names[source_link])
    if tuple(movable_seen) != tuple(source_joint_names):
        raise ValueError(f"{model_id} URDF 可动关节顺序或集合漂移")

    managed = {path.name for path in mesh_paths}
    for mesh in root.findall(".//mesh"):
        name = PurePosixPath(str(mesh.attrib.get("filename") or "")).name
        if name not in managed:
            raise ValueError(f"{model_id} URDF 引用了未锁定 mesh: {name}")
        mesh.set(
            "filename",
            f"{device_id}/meshes/{name}" if render else next(
                path.resolve().as_uri() for path in mesh_paths if path.name == name
            ),
        )


def _validate_and_repair_preview_limit(
    joint: ET.Element,
    *,
    model_id: str,
    joint_index: int,
    effort_defaults: tuple[float, ...],
    velocity_default: float | None,
    position_limits: tuple[tuple[float, float], ...],
) -> None:
    limit = joint.find("limit")
    if limit is None:
        if joint_index >= len(position_limits):
            raise ValueError(f"{model_id} 可动关节缺少 limit 且没有受限预览替代值")
        lower_default, upper_default = position_limits[joint_index]
        limit = ET.SubElement(
            joint,
            "limit",
            {
                "lower": str(lower_default),
                "upper": str(upper_default),
                "effort": "0.0",
                "velocity": "0.0",
            },
        )
    lower = _finite_attribute(limit, "lower", model_id=model_id)
    upper = _finite_attribute(limit, "upper", model_id=model_id)
    if lower >= upper:
        raise ValueError(f"{model_id} 可动关节上下限无效")
    effort = _finite_attribute(limit, "effort", model_id=model_id)
    velocity = _finite_attribute(limit, "velocity", model_id=model_id)
    if effort <= 0:
        if joint_index >= len(effort_defaults) or effort_defaults[joint_index] <= 0:
            raise ValueError(f"{model_id} effort 占位值没有受限预览替代值")
        limit.set("effort", str(effort_defaults[joint_index]))
    if velocity <= 0:
        if velocity_default is None:
            raise ValueError(f"{model_id} velocity 占位值没有受限预览替代值")
        limit.set("velocity", str(velocity_default))


def _finite_attribute(element: ET.Element, name: str, *, model_id: str) -> float:
    try:
        value = float(element.attrib[name])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{model_id} joint limit.{name} 无效") from error
    if not math.isfinite(value):
        raise ValueError(f"{model_id} joint limit.{name} 必须为有限数")
    return value


def _fixed_joint(
    *,
    name: str,
    parent: str,
    child: str,
    xyz: str = "0.0 0.0 0.0",
    rpy: str = "0.0 0.0 0.0",
) -> ET.Element:
    joint = ET.Element("joint", {"name": name, "type": "fixed"})
    ET.SubElement(joint, "origin", {"xyz": xyz, "rpy": rpy})
    ET.SubElement(joint, "parent", {"link": parent})
    ET.SubElement(joint, "child", {"link": child})
    return joint


def _vector(value: Mapping[str, Any] | None, *, scale: float) -> str:
    mapping = value if isinstance(value, Mapping) else {}
    values: list[str] = []
    for axis in "xyz":
        number = float(mapping.get(axis, 0.0)) * scale
        if not math.isfinite(number):
            raise ValueError("SourceRelease 安装位姿必须是有限数")
        values.append(str(number))
    return " ".join(values)


def _append_mock_ros2_control(
    root: ET.Element,
    *,
    prefix: str,
    joint_names: Sequence[str],
) -> None:
    control = ET.SubElement(
        root,
        "ros2_control",
        {"name": f"{prefix}preview_mock_system", "type": "system"},
    )
    hardware = ET.SubElement(control, "hardware")
    ET.SubElement(hardware, "plugin").text = "mock_components/GenericSystem"
    for joint_name in joint_names:
        joint = ET.SubElement(control, "joint", {"name": f"{prefix}{joint_name}"})
        ET.SubElement(joint, "command_interface", {"name": "position"})
        state = ET.SubElement(joint, "state_interface", {"name": "position"})
        ET.SubElement(state, "param", {"name": "initial_value"}).text = "0.0"
        ET.SubElement(joint, "state_interface", {"name": "velocity"})


def _build_srdf(
    *,
    robot_name: str,
    planning_group: str,
    base_link: str,
    tip_link: str,
) -> str:
    root = ET.Element("robot", {"name": robot_name})
    group = ET.SubElement(root, "group", {"name": planning_group})
    ET.SubElement(group, "chain", {"base_link": base_link, "tip_link": tip_link})
    return ET.tostring(root, encoding="unicode")


def _joint_limit_config(
    root: ET.Element,
    qualified_joint_names: tuple[str, ...],
) -> dict[str, Any]:
    by_name = {joint.attrib["name"]: joint for joint in root.findall("joint")}
    result: dict[str, Any] = {}
    for name in qualified_joint_names:
        limit = by_name[name].find("limit")
        if limit is None:
            raise ValueError(f"派生 URDF 关节缺少 limit: {name}")
        result[name] = {
            "has_velocity_limits": True,
            "max_velocity": float(limit.attrib["velocity"]),
            "has_acceleration_limits": False,
            "max_acceleration": 0.0,
        }
    return result


def _ros2_controllers(
    controller_name: str,
    joint_names: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "controller_manager": {
            "ros__parameters": {
                controller_name: {
                    "type": "joint_trajectory_controller/JointTrajectoryController"
                }
            }
        },
        controller_name: {
            "ros__parameters": {
                "joints": list(joint_names),
                "command_interfaces": ["position"],
                "state_interfaces": ["position", "velocity"],
                "open_loop_control": True,
            }
        },
    }


def _moveit_controllers(
    controller_name: str,
    joint_names: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "moveit_controller_manager": (
            "moveit_simple_controller_manager/MoveItSimpleControllerManager"
        ),
        "moveit_simple_controller_manager": {
            "controller_names": [controller_name],
            controller_name: {
                "type": "FollowJointTrajectory",
                "action_ns": "follow_joint_trajectory",
                "default": True,
                "joints": list(joint_names),
            },
        },
    }


def _text(mapping: Mapping[str, Any], field: str, *, default: str | None = None) -> str:
    value = mapping.get(field)
    if value is None and default is not None:
        value = default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"SourceRelease {field} 必须是非空文本")
    return value.strip()


def _digest(mapping: Mapping[str, Any], field: str) -> str:
    value = _text(mapping, field).lower()
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"SourceRelease {field} 必须是 SHA-256")
    return value


def _text_sequence(mapping: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = mapping.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"SourceRelease {field} 必须是数组")
    result = tuple(str(item).strip() for item in value)
    if not result or any(not item for item in result):
        raise ValueError(f"SourceRelease {field} 不能包含空值")
    return result


def _number_sequence_or_empty(value: object) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    result = tuple(float(item) for item in value)
    if any(not math.isfinite(item) for item in result):
        raise ValueError("受限预览 effort 默认值必须是有限数")
    return result


def _positive_number_or_none(value: object) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("受限预览 velocity 默认值必须是正有限数")
    return result


def _position_limits_or_empty(value: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    result: list[tuple[float, float]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
            raise ValueError(f"受限预览 position limit[{index}] 必须是 [lower, upper]")
        lower, upper = (float(item) for item in raw)
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            raise ValueError(f"受限预览 position limit[{index}] 无效")
        result.append((lower, upper))
    return tuple(result)


def _safe_identifier(value: str) -> str:
    result = _SAFE_NAME.sub("_", str(value)).strip("_").lower()
    if not result:
        raise ValueError("SourceRelease 名称不能规范为空标识符")
    return result


__all__ = [
    "SourceReleaseModelBundle",
    "SourceReleaseReceipt",
    "build_dobot_cr5_model",
    "build_duco_gcr5_910_model",
    "build_fairino_fr5_model",
    "build_source_release_model",
    "get_verified_source_release_receipt",
    "verify_source_release_archive",
]
