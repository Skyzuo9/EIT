#!/usr/bin/env python3
"""验证 Windows 工站源发布是否足以进入 Mac 后半段编译链。"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any

try:
    from station_glb_semantics import (
        DIAGNOSIS_SCHEMA,
        diagnose_glb_pair,
        normalized_snapshot,
    )
except ModuleNotFoundError:  # 允许测试从仓库根目录加载脚本
    from scripts.station_glb_semantics import (
        DIAGNOSIS_SCHEMA,
        diagnose_glb_pair,
        normalized_snapshot,
    )

HANDOFF_SCHEMA = "lab.station_source_handoff/v0"
SNAPSHOT_SCHEMA = "lab.assembly_snapshot/v0"
CAPTURE_SCHEMA = "lab.solidworks_capture_report/v0"
SOURCE_SCHEMA = "lab.source/v0"
REPRODUCIBILITY_SCHEMA = "lab.station_capture_reproducibility/v0"
VALIDATION_SCHEMA = "lab.station_source_handoff_validation/v1"
MANIFEST_ALGORITHM = "sha256(utf8(files.sha256))"
DIGEST = re.compile(r"^[0-9a-f]{64}$")
PROVIDER = re.compile(
    r"^(?P<module>[A-Za-z_][A-Za-z0-9_.]*):"
    r"(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)$"
)
WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


class HandoffValidation:
    """收集失败关闭错误和不阻塞警告。"""

    def __init__(self, manifest: Path) -> None:
        self.manifest = manifest.resolve()
        self.root = self.manifest.parent
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.details: dict[str, Any] = {}

    def run(self) -> dict[str, Any]:
        manifest = self._json(self.manifest, "station-handoff.json")
        if manifest.get("schema") != HANDOFF_SCHEMA:
            self.errors.append(f"manifest schema 必须是 {HANDOFF_SCHEMA}")
        station = self._text(manifest.get("station"), "station")
        capture = self._mapping(manifest.get("solidworks_capture"), "solidworks_capture")
        robot = self._mapping(manifest.get("robot_release"), "robot_release")
        reproducibility = self._mapping(
            manifest.get("reproducibility"),
            "reproducibility",
        )

        snapshot_path = self._path(capture.get("assembly_snapshot"), "assembly_snapshot")
        report_path = self._path(capture.get("capture_report"), "capture_report")
        source_path = self._path(capture.get("source"), "source")
        hashes_path = self._path(capture.get("files_sha256"), "files_sha256")
        source_root = self._path(
            capture.get("source_release_root"),
            "source_release_root",
            require_file=False,
        )
        render_path = self._path(capture.get("render_glb"), "render_glb")
        reproducibility_report_path = self._repro_path(
            reproducibility.get("report"), "report"
        )
        repeat_snapshot_path = self._repro_path(
            reproducibility.get("repeat_snapshot"), "repeat_snapshot"
        )
        repeat_capture_report_path = self._repro_path(
            reproducibility.get("repeat_capture_report"), "repeat_capture_report"
        )
        repeat_glb_path = self._repro_path(
            reproducibility.get("repeat_glb"), "repeat_glb"
        )
        diagnosis_value = reproducibility.get("glb_semantic_diagnosis")
        diagnosis_path = (
            self._repro_path(diagnosis_value, "glb_semantic_diagnosis")
            if isinstance(diagnosis_value, str) and diagnosis_value.strip()
            else None
        )

        snapshot = self._json(snapshot_path, "assembly_snapshot")
        report = self._json(report_path, "capture_report")
        source = self._json(source_path, "source")
        snapshot_info = self._validate_snapshot(snapshot, "assembly_snapshot")
        report_info = self._validate_capture_report(report, "capture_report")
        self._validate_component_count(snapshot_info, report_info, "主采集")
        source_digest = self._verify_source_hashes(hashes_path, source_root)
        self._validate_source(source, source_digest)
        glb_stats = self._validate_glb(render_path, "render_glb")
        self._validate_report_glb(report_info, glb_stats, render_path, "主采集")
        self._validate_reproducibility(
            snapshot=snapshot,
            snapshot_path=snapshot_path,
            report=report,
            primary_glb=render_path,
            reproducibility_report_path=reproducibility_report_path,
            repeat_snapshot_path=repeat_snapshot_path,
            repeat_capture_report_path=repeat_capture_report_path,
            repeat_glb_path=repeat_glb_path,
            diagnosis_path=diagnosis_path,
        )
        self._validate_absolute_path_locations(snapshot, "assembly_snapshot")
        self._validate_absolute_path_locations(report, "capture_report")
        self._validate_robot(robot)

        return {
            "schema": VALIDATION_SCHEMA,
            "passed": not self.errors,
            "station": station,
            "manifest": str(self.manifest),
            "manifest_sha256": self._sha256(self.manifest) if self.manifest.is_file() else None,
            "errors": self.errors,
            "warnings": self.warnings,
            "details": self.details,
            "qualification": "source-input-validated" if not self.errors else "rejected",
            "not_qualified_for": [
                "kinematic-preview",
                "collision",
                "spatial-interlock-enforced",
                "execution",
            ],
        }

    def _validate_snapshot(self, snapshot: dict[str, Any], field: str) -> dict[str, Any]:
        if snapshot.get("schema") != SNAPSHOT_SCHEMA:
            self.errors.append(f"{field} schema 必须是 {SNAPSHOT_SCHEMA}")
        units = self._mapping(snapshot.get("units"), f"{field}.units")
        expected_units = {
            "length": "m",
            "angle": "rad",
            "orientation": "quaternion_xyzw",
        }
        if units != expected_units:
            self.errors.append(f"{field} 单位必须是 m/rad/quaternion_xyzw")
        instances = snapshot.get("instances")
        if not isinstance(instances, list) or not instances:
            self.errors.append(f"{field} 必须包含非空 instances")
            return {"count": 0, "ids": set(), "roots": set()}
        ids: set[str] = set()
        parents: dict[str, str | None] = {}
        for index, raw in enumerate(instances):
            item = self._mapping(raw, f"{field}.instances[{index}]")
            instance_id = self._text(item.get("id"), f"{field}.instances[{index}].id")
            if instance_id in ids:
                self.errors.append(f"{field} occurrence id 重复: {instance_id}")
            ids.add(instance_id)
            parent = item.get("parent")
            if parent is not None and (not isinstance(parent, str) or not parent.strip()):
                self.errors.append(f"{instance_id}.parent 必须是 null 或非空 occurrence id")
                parent = None
            parents[instance_id] = parent.strip() if isinstance(parent, str) else None
            transform = self._mapping(
                item.get("transform_world"),
                f"{field}.instances[{index}].transform_world",
            )
            xyz = self._vector(transform.get("xyz_m"), 3, f"{instance_id}.xyz_m")
            quat = self._vector(transform.get("quat_xyzw"), 4, f"{instance_id}.quat_xyzw")
            if xyz and any(abs(value) > 1000 for value in xyz):
                self.errors.append(f"{instance_id} 世界位姿超过 1000 m，疑似单位错误")
            if quat:
                norm = math.sqrt(sum(value * value for value in quat))
                if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
                    self.errors.append(f"{instance_id} 四元数未归一化")
            scale = transform.get("scale")
            if not self._finite(scale) or float(scale) <= 0:
                self.errors.append(f"{instance_id} scale 必须为正有限数")

        for instance_id, parent in parents.items():
            if parent is not None and parent not in ids:
                self.errors.append(f"{field} parent 引用不存在: {instance_id} -> {parent}")
            if parent == instance_id:
                self.errors.append(f"{field} occurrence 不得以自身为 parent: {instance_id}")
        self._validate_parent_cycles(parents, field)

        roots = snapshot.get("root_occurrences")
        declared_roots: list[str] = []
        if not isinstance(roots, list) or not roots:
            self.errors.append(f"{field} 缺少 root_occurrences")
        else:
            for index, root in enumerate(roots):
                if not isinstance(root, str) or not root.strip():
                    self.errors.append(f"{field}.root_occurrences[{index}] 必须是非空文本")
                    continue
                declared_roots.append(root.strip())
            if len(declared_roots) != len(set(declared_roots)):
                self.errors.append(f"{field}.root_occurrences 含重复项")
        actual_roots = {item for item, parent in parents.items() if parent is None}
        if set(declared_roots) != actual_roots:
            self.errors.append(
                f"{field}.root_occurrences 与 parent 图根集合不一致: "
                f"declared={sorted(set(declared_roots))}, actual={sorted(actual_roots)}"
            )
        info = {"count": len(instances), "ids": ids, "roots": actual_roots}
        if field == "assembly_snapshot":
            self.details["instance_count"] = len(instances)
            self.details["root_occurrence_count"] = len(actual_roots)
        return info

    def _validate_parent_cycles(self, parents: dict[str, str | None], field: str) -> None:
        complete: set[str] = set()
        for start in parents:
            if start in complete:
                continue
            path: list[str] = []
            positions: dict[str, int] = {}
            current: str | None = start
            while current is not None and current in parents and current not in complete:
                if current in positions:
                    cycle = path[positions[current] :] + [current]
                    self.errors.append(f"{field} parent 图存在环: {' -> '.join(cycle)}")
                    break
                positions[current] = len(path)
                path.append(current)
                current = parents[current]
            complete.update(path)

    def _validate_capture_report(self, report: dict[str, Any], field: str) -> dict[str, Any]:
        if report.get("schema") != CAPTURE_SCHEMA:
            self.errors.append(f"{field} schema 必须是 {CAPTURE_SCHEMA}")
        if report.get("status") != "passed":
            self.errors.append(f"{field} status 不是 passed")
        if report.get("source_read_only") is not True:
            self.errors.append(f"{field} 必须证明 SolidWorks 只读打开")
        component_count = report.get("component_count")
        if isinstance(component_count, bool) or not isinstance(component_count, int) or component_count <= 0:
            self.errors.append(f"{field}.component_count 必须是正整数")
            component_count = None
        open_errors = report.get("open_errors")
        if isinstance(open_errors, int) and open_errors != 0:
            self.errors.append(f"{field}.open_errors 非零: {open_errors}")
        open_warnings = report.get("open_warnings")
        if isinstance(open_warnings, int) and open_warnings != 0:
            explanation = report.get("open_warning_explanation")
            if not isinstance(explanation, str) or not explanation.strip():
                self.warnings.append(
                    f"{field}.open_warnings={open_warnings}；交接回执必须人工解释该位掩码"
                )
            self.details.setdefault("open_warning_masks", {})[field] = open_warnings
        glb = self._mapping(report.get("glb_export"), f"{field}.glb_export")
        if glb.get("exists") is not True or glb.get("save_result") is not True:
            self.errors.append(f"{field} 未证明 GLB 导出成功")
        if glb.get("magic") != "glTF":
            self.errors.append(f"{field} 的 GLB magic 不是 glTF")
        if field == "capture_report":
            self.details["solidworks_com_revision"] = report.get("com_revision")
            self.details["capture_component_count"] = component_count
        return {"component_count": component_count, "glb_export": glb}

    def _validate_component_count(
        self,
        snapshot: dict[str, Any],
        report: dict[str, Any],
        label: str,
    ) -> None:
        if report.get("component_count") != snapshot.get("count"):
            self.errors.append(
                f"{label} snapshot occurrence 数量与 capture report component_count 不一致"
            )

    def _validate_source(self, source: dict[str, Any], manifest_digest: str | None) -> None:
        if source.get("schema") != SOURCE_SCHEMA:
            self.errors.append(f"source schema 必须是 {SOURCE_SCHEMA}")
        if source.get("read_policy") != "read-only":
            self.errors.append("source read_policy 必须是 read-only")
        if source.get("manifest_algorithm") != MANIFEST_ALGORITHM:
            self.errors.append(f"source.manifest_algorithm 必须是 {MANIFEST_ALGORITHM}")
        digest = str(source.get("source_files_digest") or "")
        if DIGEST.fullmatch(digest) is None:
            self.errors.append("source_files_digest 不是 SHA-256")
        elif manifest_digest is not None and digest != manifest_digest:
            self.errors.append("source_files_digest 与 files.sha256 聚合摘要不一致")
        self.details["source_files_digest"] = manifest_digest

    def _verify_source_hashes(self, hashes_path: Path, source_root: Path) -> str | None:
        if not hashes_path.is_file() or not source_root.is_dir():
            return None
        try:
            manifest_text = hashes_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            self.errors.append(f"files.sha256 不是 UTF-8 文本: {error}")
            return None
        checked = 0
        paths: list[str] = []
        seen: set[str] = set()
        for line_number, raw in enumerate(manifest_text.splitlines(), 1):
            if not raw.strip():
                continue
            parts = raw.split(maxsplit=1)
            if len(parts) != 2 or DIGEST.fullmatch(parts[0]) is None:
                self.errors.append(f"files.sha256 第 {line_number} 行格式无效")
                continue
            relative = parts[1].strip().lstrip("*")
            if "\\" in relative or relative.startswith("./"):
                self.errors.append(f"files.sha256 第 {line_number} 行必须使用规范 POSIX 相对路径")
                continue
            if relative in seen:
                self.errors.append(f"files.sha256 路径重复: {relative}")
                continue
            seen.add(relative)
            paths.append(relative)
            target = self._within(source_root, relative, f"files.sha256:{line_number}")
            if not target.is_file():
                self.errors.append(f"源发布文件缺失: {relative}")
                continue
            actual = self._sha256(target)
            if actual != parts[0]:
                self.errors.append(f"源发布哈希不匹配: {relative}")
                continue
            checked += 1
        if paths != sorted(paths):
            self.errors.append("files.sha256 路径未按字典序排列")
        if checked == 0:
            self.errors.append("files.sha256 没有验证通过的源文件")
        self.details["source_files_verified"] = checked
        return self._sha256(hashes_path)

    def _validate_glb(self, path: Path, field: str) -> dict[str, int]:
        empty = {
            "nodes": 0,
            "meshes": 0,
            "primitives": 0,
            "accessors": 0,
            "vertices": 0,
            "triangles": 0,
        }
        if not path.is_file():
            return empty
        try:
            data = path.read_bytes()
            if len(data) < 20:
                raise ValueError("文件过小")
            magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
            if magic != b"glTF":
                raise ValueError("文件头不是 glTF")
            if version != 2:
                raise ValueError(f"GLB version 必须是 2，实际为 {version}")
            if declared_length != len(data):
                raise ValueError(
                    f"GLB header length={declared_length} 与实际 bytes={len(data)} 不一致"
                )
            offset = 12
            chunks: list[tuple[int, bytes]] = []
            while offset < len(data):
                if offset + 8 > len(data):
                    raise ValueError("GLB chunk header 截断")
                chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
                offset += 8
                if chunk_length % 4 != 0 or offset + chunk_length > len(data):
                    raise ValueError("GLB chunk 长度非法或越界")
                chunks.append((chunk_type, data[offset : offset + chunk_length]))
                offset += chunk_length
            if not chunks or chunks[0][0] != 0x4E4F534A:
                raise ValueError("GLB 首个 chunk 必须是 JSON")
            document = json.loads(chunks[0][1].rstrip(b" \t\r\n\x00").decode("utf-8"))
            asset = document.get("asset") if isinstance(document, dict) else None
            if not isinstance(asset, dict) or str(asset.get("version")) != "2.0":
                raise ValueError("GLB JSON 缺少 asset.version=2.0")
            nodes = document.get("nodes", [])
            meshes = document.get("meshes", [])
            accessors = document.get("accessors", [])
            if not all(isinstance(value, list) for value in (nodes, meshes, accessors)):
                raise ValueError("GLB nodes/meshes/accessors 必须是数组")
            primitive_count = 0
            vertices = 0
            triangles = 0
            for mesh_index, mesh in enumerate(meshes):
                if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives"), list):
                    raise ValueError(f"GLB meshes[{mesh_index}].primitives 无效")
                for primitive in mesh["primitives"]:
                    if not isinstance(primitive, dict):
                        raise ValueError("GLB primitive 必须是对象")
                    primitive_count += 1
                    attributes = primitive.get("attributes")
                    if not isinstance(attributes, dict) or not isinstance(attributes.get("POSITION"), int):
                        raise ValueError("GLB primitive 缺少 POSITION accessor")
                    position_index = attributes["POSITION"]
                    if position_index < 0 or position_index >= len(accessors):
                        raise ValueError("GLB POSITION accessor 越界")
                    position_accessor = accessors[position_index]
                    count = position_accessor.get("count") if isinstance(position_accessor, dict) else None
                    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                        raise ValueError("GLB POSITION accessor count 无效")
                    vertices += count
                    if primitive.get("mode", 4) == 4:
                        index_index = primitive.get("indices")
                        if isinstance(index_index, int):
                            if index_index < 0 or index_index >= len(accessors):
                                raise ValueError("GLB index accessor 越界")
                            index_accessor = accessors[index_index]
                            index_count = (
                                index_accessor.get("count")
                                if isinstance(index_accessor, dict)
                                else None
                            )
                            if isinstance(index_count, int) and not isinstance(index_count, bool):
                                triangles += index_count // 3
                        else:
                            triangles += count // 3
            stats = {
                "nodes": len(nodes),
                "meshes": len(meshes),
                "primitives": primitive_count,
                "accessors": len(accessors),
                "vertices": vertices,
                "triangles": triangles,
            }
            if (
                stats["nodes"] == 0
                or stats["meshes"] == 0
                or stats["primitives"] == 0
                or stats["accessors"] == 0
            ):
                raise ValueError("GLB 没有可验证的非空几何")
        except (
            AttributeError,
            KeyError,
            OSError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
            struct.error,
            ValueError,
        ) as error:
            self.errors.append(f"{field} 结构/几何无效: {error}")
            return empty
        if field == "render_glb":
            self.details["render_glb_bytes"] = len(data)
            self.details["render_glb_sha256"] = self._sha256(path)
            self.details["render_glb_geometry"] = stats
        return stats

    def _validate_report_glb(
        self,
        report: dict[str, Any],
        stats: dict[str, int],
        path: Path,
        label: str,
    ) -> None:
        glb = report.get("glb_export", {})
        reported_bytes = glb.get("bytes") if isinstance(glb, dict) else None
        if path.is_file() and reported_bytes != path.stat().st_size:
            self.errors.append(f"{label} capture report GLB bytes 与文件不一致")
        geometry = glb.get("geometry") if isinstance(glb, dict) else None
        if not isinstance(geometry, dict):
            self.errors.append(f"{label} capture report 缺少 GLB geometry 统计")
            return
        for key in ("nodes", "meshes", "primitives", "accessors"):
            if geometry.get(key) != stats.get(key):
                self.errors.append(
                    f"{label} capture report GLB geometry.{key} 与文件不一致"
                )

    def _validate_absolute_path_locations(self, value: Any, field: str) -> None:
        allowed = (
            re.compile(r"^(?:assembly_snapshot|repeat_assembly_snapshot)\.source_document$"),
            re.compile(
                r"^(?:assembly_snapshot|repeat_assembly_snapshot)\.instances\[\d+\]\.document$"
            ),
            re.compile(r"^(?:capture_report|repeat_capture_report)\.source_document$"),
        )
        audit_paths = 0

        def visit(item: Any, path: str) -> None:
            nonlocal audit_paths
            if isinstance(item, dict):
                for key, child in item.items():
                    visit(child, f"{path}.{key}")
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    visit(child, f"{path}[{index}]")
            elif isinstance(item, str) and self._is_absolute_path(item):
                if any(pattern.fullmatch(path) for pattern in allowed):
                    audit_paths += 1
                else:
                    self.errors.append(f"绝对路径只能出现在审计字段，发现于 {path}")

        visit(value, field)
        self.details["absolute_audit_path_count"] = (
            int(self.details.get("absolute_audit_path_count", 0)) + audit_paths
        )

    @staticmethod
    def _is_absolute_path(value: str) -> bool:
        return value.startswith("/") or WINDOWS_ABSOLUTE.match(value) is not None

    def _validate_reproducibility(
        self,
        *,
        snapshot: dict[str, Any],
        snapshot_path: Path,
        report: dict[str, Any],
        primary_glb: Path,
        reproducibility_report_path: Path,
        repeat_snapshot_path: Path,
        repeat_capture_report_path: Path,
        repeat_glb_path: Path,
        diagnosis_path: Path | None,
    ) -> None:
        reproducibility = self._json(
            reproducibility_report_path,
            "reproducibility.report",
        )
        repeat_snapshot = self._json(
            repeat_snapshot_path,
            "reproducibility.repeat_snapshot",
        )
        repeat_report = self._json(
            repeat_capture_report_path,
            "reproducibility.repeat_capture_report",
        )
        repeat_snapshot_info = self._validate_snapshot(
            repeat_snapshot,
            "repeat_assembly_snapshot",
        )
        repeat_report_info = self._validate_capture_report(
            repeat_report,
            "repeat_capture_report",
        )
        self._validate_component_count(
            repeat_snapshot_info,
            repeat_report_info,
            "第二次采集",
        )
        repeat_glb_stats = self._validate_glb(repeat_glb_path, "repeat_render_glb")
        self._validate_report_glb(
            repeat_report_info,
            repeat_glb_stats,
            repeat_glb_path,
            "第二次采集",
        )
        self._validate_absolute_path_locations(
            repeat_snapshot,
            "repeat_assembly_snapshot",
        )
        self._validate_absolute_path_locations(
            repeat_report,
            "repeat_capture_report",
        )
        if reproducibility.get("schema") != REPRODUCIBILITY_SCHEMA:
            self.errors.append(
                f"reproducibility schema 必须是 {REPRODUCIBILITY_SCHEMA}"
            )
        if reproducibility.get("status") != "passed":
            self.errors.append("reproducibility status 不是 passed")
        if repeat_snapshot.get("schema") != SNAPSHOT_SCHEMA:
            self.errors.append("repeat snapshot schema 无效")
        if (
            repeat_report.get("schema") != CAPTURE_SCHEMA
            or repeat_report.get("status") != "passed"
            or repeat_report.get("source_read_only") is not True
        ):
            self.errors.append("repeat capture report 未证明第二次只读采集通过")

        primary_instances = snapshot.get("instances", [])
        repeat_instances = repeat_snapshot.get("instances", [])
        if report.get("component_count") != len(primary_instances):
            self.errors.append("primary snapshot occurrence 数量与 capture report 不一致")
        if repeat_report.get("component_count") != len(repeat_instances):
            self.errors.append("repeat snapshot occurrence 数量与 capture report 不一致")
        normalized_match = normalized_snapshot(snapshot) == normalized_snapshot(
            repeat_snapshot
        )
        if not normalized_match:
            self.errors.append("Mac 复算发现两次规范化 snapshot 不一致")
        if reproducibility.get("normalized_snapshot_match") is not normalized_match:
            self.errors.append("reproducibility 的 snapshot 判定与 Mac 复算不一致")

        if not primary_glb.is_file() or not repeat_glb_path.is_file():
            return
        with repeat_glb_path.open("rb") as handle:
            if handle.read(4) != b"glTF":
                self.errors.append("repeat GLB 文件头不是 glTF")
                return
        primary_glb_hash = self._sha256(primary_glb)
        repeat_glb_hash = self._sha256(repeat_glb_path)
        primary_snapshot_hash = self._sha256(snapshot_path)
        repeat_snapshot_hash = self._sha256(repeat_snapshot_path)
        expected_hashes = {
            "primary_glb_sha256": primary_glb_hash,
            "repeat_glb_sha256": repeat_glb_hash,
            "primary_snapshot_sha256": primary_snapshot_hash,
            "repeat_snapshot_sha256": repeat_snapshot_hash,
        }
        for field, actual in expected_hashes.items():
            if reproducibility.get(field) != actual:
                self.errors.append(f"reproducibility.{field} 与实际文件不一致")

        exact_match = primary_glb_hash == repeat_glb_hash
        if reproducibility.get("exact_glb_match") is not exact_match:
            self.errors.append("reproducibility 的 GLB 字节判定与实际不一致")

        semantic_match = exact_match
        difference_class = "none"
        diagnosis: dict[str, Any] | None = None
        if not exact_match:
            if diagnosis_path is None:
                self.errors.append("GLB 字节不一致时必须包含 Mac 语义诊断")
            else:
                diagnosis = self._json(
                    diagnosis_path,
                    "reproducibility.glb_semantic_diagnosis",
                )
                if diagnosis.get("schema") != DIAGNOSIS_SCHEMA:
                    self.errors.append("GLB semantic diagnosis schema 无效")
                try:
                    recomputed = diagnose_glb_pair(primary_glb, repeat_glb_path)
                except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
                    self.errors.append(f"Mac 无法复算 GLB 语义签名: {error}")
                else:
                    semantic_match = bool(
                        recomputed.get("normalized_glb_semantic_match")
                    )
                    difference_class = str(recomputed.get("difference_class") or "")
                    for field in (
                        "status",
                        "algorithm",
                        "exact_glb_match",
                        "normalized_glb_semantic_match",
                        "difference_class",
                        "primary_semantic_sha256",
                        "repeat_semantic_sha256",
                    ):
                        if diagnosis.get(field) != recomputed.get(field):
                            self.errors.append(
                                f"GLB semantic diagnosis.{field} 与 Mac 复算不一致"
                            )
                    for side, actual in (
                        ("primary_glb", primary_glb_hash),
                        ("repeat_glb", repeat_glb_hash),
                    ):
                        value = diagnosis.get(side)
                        if not isinstance(value, dict) or value.get("sha256") != actual:
                            self.errors.append(f"GLB semantic diagnosis.{side} 哈希不匹配")
                    if diagnosis.get("approved_for_p1_packaging") is not True:
                        self.errors.append("GLB semantic diagnosis 未批准 P1 封装")
            if not semantic_match or difference_class != "component_traversal_order_only":
                self.errors.append("GLB 存在需要调查的语义差异")

        if reproducibility.get("normalized_glb_semantic_match") is not semantic_match:
            self.errors.append("reproducibility 的 GLB 语义判定与 Mac 复算不一致")
        if reproducibility.get("difference_class") != difference_class:
            self.errors.append("reproducibility 的 GLB 差异分类与 Mac 复算不一致")
        expected_basis = "exact-bytes" if exact_match else "mac-semantic-diagnosis"
        if reproducibility.get("acceptance_basis") != expected_basis:
            self.errors.append("reproducibility 的 acceptance_basis 与 Mac 复算不一致")
        self.details["reproducibility"] = {
            "normalized_snapshot_match": normalized_match,
            "exact_glb_match": exact_match,
            "normalized_glb_semantic_match": semantic_match,
            "difference_class": difference_class,
            "repeat_glb_sha256": repeat_glb_hash,
        }

    def _validate_robot(self, robot: dict[str, Any]) -> None:
        if robot.get("authority") != "manufacturer":
            self.errors.append("robot_release.authority 必须是 manufacturer")
        vendor = self._text(robot.get("vendor"), "robot_release.vendor")
        model = self._text(robot.get("model"), "robot_release.model")
        provider_ref = self._text(robot.get("provider"), "robot_release.provider")
        expected_digest = str(robot.get("source_digest") or "").lower()
        if DIGEST.fullmatch(expected_digest) is None:
            self.errors.append("robot_release.source_digest 不是 SHA-256")
            return
        match = PROVIDER.fullmatch(provider_ref)
        if match is None:
            self.errors.append("robot_release.provider 必须是 module:symbol")
            return
        try:
            provider = getattr(
                importlib.import_module(match.group("module")),
                match.group("symbol"),
            )
            bundle = provider(device_id="handoff_probe")
        except Exception as error:  # noqa: BLE001 - 形成稳定门禁诊断
            self.errors.append(f"机械臂 Provider 无法实例化: {error}")
            return
        actual_digest = str(getattr(bundle, "source_digest", "")).lower()
        if actual_digest != expected_digest:
            self.errors.append("机械臂 Provider source_digest 与交接清单不一致")
        joints = tuple(getattr(bundle, "qualified_joint_names", ()))
        meshes = tuple(Path(path) for path in getattr(bundle, "mesh_paths", ()))
        if not joints or any(not name.startswith("handoff_probe_") for name in joints):
            self.errors.append("机械臂 Provider 未产生实例限定关节名")
        if not meshes or any(not path.is_file() for path in meshes):
            self.errors.append("机械臂 Provider mesh 不完整")
        self.details["robot"] = {
            "vendor": vendor,
            "model": model,
            "source_digest": actual_digest,
            "joint_count": len(joints),
            "mesh_count": len(meshes),
        }

    def _json(self, path: Path, field: str) -> dict[str, Any]:
        if not path.is_file():
            self.errors.append(f"{field} 文件缺失: {path}")
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            self.errors.append(f"{field} 不是可读 JSON: {error}")
            return {}
        return self._mapping(value, field)

    def _path(
        self,
        value: Any,
        field: str,
        *,
        require_file: bool = True,
    ) -> Path:
        relative = self._text(value, field)
        path = self._within(self.root, relative, field)
        if require_file and not path.is_file():
            self.errors.append(f"{field} 文件缺失: {path}")
        if not require_file and not path.is_dir():
            self.errors.append(f"{field} 目录缺失: {path}")
        return path

    def _repro_path(self, value: Any, field: str) -> Path:
        relative = self._text(value, f"reproducibility.{field}")
        path = self._within(self.root, relative, f"reproducibility.{field}")
        if not path.is_file():
            self.errors.append(f"reproducibility.{field} 文件缺失: {path}")
        return path

    def _within(self, root: Path, relative: str, field: str) -> Path:
        raw = Path(relative)
        if raw.is_absolute() or WINDOWS_ABSOLUTE.match(relative):
            self.errors.append(f"{field} 必须使用相对路径")
            return root / "__invalid_absolute_path__"
        target = (root / raw).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self.errors.append(f"{field} 路径越出交接目录")
            return root / "__invalid_escape_path__"
        return target

    def _mapping(self, value: Any, field: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            self.errors.append(f"{field} 必须是对象")
            return {}
        return value

    def _text(self, value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            self.errors.append(f"{field} 必须是非空文本")
            return ""
        return value.strip()

    def _vector(self, value: Any, size: int, field: str) -> list[float]:
        if not isinstance(value, list) or len(value) != size or any(
            not self._finite(item) for item in value
        ):
            self.errors.append(f"{field} 必须包含 {size} 个有限数")
            return []
        return [float(item) for item in value]

    @staticmethod
    def _finite(value: Any) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validation = HandoffValidation(args.manifest)
    result = validation.run()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
