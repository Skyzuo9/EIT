#!/usr/bin/env python3
"""Generate a fail-closed station decomposition draft from SolidWorks URDF CSV evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any
from zipfile import BadZipFile, ZipFile

import yaml


EVIDENCE_SCHEMA = "lab.urdf_occurrence_evidence/v0"
PROPOSAL_SCHEMA = "lab.station_decomposition/v1.1"
_INSTANCE_SUFFIX = re.compile(r"-\d+$")
_CAD_EXTENSION = re.compile(r"\.(?:sldasm|sldprt|step|stp)(?=-|$)", re.IGNORECASE)
_DEFAULT_CONFIG = re.compile(r"\(default_按加工_\)", re.IGNORECASE)
_NON_WORD = re.compile(r"[\s_]+")


class ProposalError(ValueError):
    """Source evidence cannot form an exact, fully covering draft."""


@dataclass(frozen=True, slots=True)
class PackageEvidence:
    package: str
    source: str
    tokens: tuple[str, ...]
    token_matches: Mapping[str, tuple[str, ...]]
    candidate_roots: tuple[str, ...]
    unmatched_tokens: tuple[str, ...]
    source_authority: str
    source_digest: str
    robot_family: str | None = None


class OccurrenceIndex:
    def __init__(self, instances: list[Mapping[str, Any]]) -> None:
        self.by_id: dict[str, Mapping[str, Any]] = {}
        self.children: dict[str, list[str]] = {}
        for raw in instances:
            occurrence = _required_text(raw, "id")
            if occurrence in self.by_id:
                raise ProposalError(f"snapshot occurrence 重复: {occurrence}")
            self.by_id[occurrence] = raw
            self.children[occurrence] = []
        for occurrence, raw in self.by_id.items():
            parent = raw.get("parent")
            if parent is not None:
                if parent not in self.by_id:
                    raise ProposalError(f"snapshot parent 不存在: {occurrence} -> {parent}")
                self.children[parent].append(occurrence)
        for values in self.children.values():
            values.sort()
        self.roots = tuple(sorted(key for key, value in self.by_id.items() if value.get("parent") is None))
        self._descendants = {occurrence: frozenset(self.descendants(occurrence)) for occurrence in self.by_id}
        self._token_index: dict[str, set[str]] = defaultdict(set)
        for occurrence, raw in self.by_id.items():
            leaf = occurrence.rsplit("/", 1)[-1]
            document = PureWindowsPath(str(raw.get("document") or "")).name
            for value in (leaf, document):
                for variant in _name_variants(value):
                    self._token_index[variant].add(occurrence)

    def descendants(self, root: str) -> list[str]:
        result: list[str] = []
        pending = [root]
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(reversed(self.children[current]))
        return sorted(result)

    def ancestors(self, occurrence: str) -> tuple[str, ...]:
        result: list[str] = []
        current: str | None = occurrence
        while current is not None:
            result.append(current)
            parent = self.by_id[current].get("parent")
            current = str(parent) if parent is not None else None
        return tuple(result)

    def token_matches(self, token: str) -> tuple[str, ...]:
        variants = _name_variants(token)
        for variant in variants:
            matches = self._token_index.get(variant)
            if matches:
                return tuple(sorted(matches))
        return ()

    def minimal_covering_roots(
        self,
        token_matches: Mapping[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        if not token_matches or any(not values for values in token_matches.values()):
            return ()
        possible: set[str] = set()
        for matches in token_matches.values():
            for occurrence in matches:
                possible.update(self.ancestors(occurrence))
        covering = {
            root
            for root in possible
            if all(
                any(candidate in self._descendants[root] for candidate in matches)
                for matches in token_matches.values()
            )
        }
        deepest = {
            root
            for root in covering
            if not any(
                other != root and other in self._descendants[root]
                for other in covering
            )
        }
        return tuple(sorted(deepest))

    def is_strict_descendant(self, child: str, parent: str) -> bool:
        return child != parent and child in self._descendants[parent]


def generate_proposal(
    handoff_path: Path,
    legacy_urdf_root: Path,
    *,
    robot_manifest_path: Path,
    robot_model_id: str,
    source_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    handoff = _read_json(handoff_path)
    snapshot_path = _relative_file(
        handoff_path.parent,
        _mapping(handoff.get("solidworks_capture"), "solidworks_capture").get("assembly_snapshot"),
    )
    snapshot = _read_json(snapshot_path)
    raw_instances = snapshot.get("instances")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise ProposalError("assembly snapshot 缺少 instances")
    instances = [_mapping(item, "snapshot.instances[]") for item in raw_instances]
    index = OccurrenceIndex(instances)

    packages = list(_legacy_packages(legacy_urdf_root, index))
    packages.append(
        _robot_package(
            robot_manifest_path,
            robot_model_id,
            index,
            source_root=source_root,
        )
    )
    selected, duplicate_roots = _select_package_roots(packages)
    bottle_selection = _select_4ml_bottle(index)
    if bottle_selection is not None and bottle_selection not in selected:
        selected[bottle_selection] = {
            "family": "material-family:glass-bottle-4ml",
            "kind": "device",
            "package": "4ml玻璃瓶 standalone geometry",
            "source_authority": "solidworks-occurrence-and-standalone-stl",
            "review_note": (
                "按 occurrence id 自然序确定的首个 4 ml 有盖瓶，仅作首条几何纵切候选；"
                "未批准物理槽位或运行时实例。"
            ),
        }

    for root in index.roots:
        selected.setdefault(
            root,
            {
                "family": _generic_family(root),
                "kind": "static_environment",
                "package": "snapshot top-level shell",
                "source_authority": "solidworks-occurrence-snapshot",
                "review_note": "自动兜底的顶层装配壳；其已识别子设备通过 exclude_subtree_roots 分离。",
            },
        )

    _attach_direct_exclusions(selected, index)
    devices: list[dict[str, Any]] = []
    robots: list[dict[str, Any]] = []
    for root in sorted(selected, key=lambda item: (_depth(item), item)):
        item = selected[root]
        common = {
            "subtree_root": root,
            "exclude_subtree_roots": item["exclude_subtree_roots"],
            "review_note": item["review_note"],
        }
        if item["kind"] == "robot_replacement":
            robots.append({"replaced_by": item["family"], **common})
        else:
            devices.append({"family": item["family"], "kind": item["kind"], **common})

    proposal = {
        "schema": PROPOSAL_SCHEMA,
        "station": _required_text(handoff, "station"),
        "source_handoff_digest": _sha256(handoff_path),
        "devices": devices,
        "robot_subtrees": robots,
        "unassigned_policy": "fail",
        "approval": {
            "status": "draft",
            "reviewed_by": "",
            "reviewed_at": "",
            "notes": "Agent 从摘要锁定 URDF CSV 与 occurrence snapshot 自动生成；待机械/CAD 审核。",
        },
    }
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "station": proposal["station"],
        "source_handoff": str(handoff_path.resolve()),
        "source_handoff_digest": proposal["source_handoff_digest"],
        "snapshot": str(snapshot_path.resolve()),
        "snapshot_occurrence_count": len(index.by_id),
        "legacy_urdf_root": str(legacy_urdf_root.resolve()),
        "package_count": len(packages),
        "packages": [_package_json(package) for package in packages],
        "selected_rule_count": len(selected),
        "duplicate_root_candidates": duplicate_roots,
        "robot_model_id": robot_model_id,
        "robot_occurrence_roots": [
            root for root, item in selected.items() if item["kind"] == "robot_replacement"
        ],
        "bottle_4ml_representative": bottle_selection,
        "qualification": "draft-evidence-only",
        "publication_eligible": False,
        "not_qualified_for": [
            "hardware-execution",
            "manufacturer-joint-limits",
            "collision",
            "tcp",
            "base-calibration",
            "physical-slot-selection",
        ],
    }
    review = _render_review(proposal, evidence, selected)
    return proposal, evidence, review


def _legacy_packages(root: Path, index: OccurrenceIndex) -> Iterable[PackageEvidence]:
    csv_files = sorted(Path(root).glob("*/urdf/*.csv"))
    if not csv_files:
        raise ProposalError(f"legacy URDF root 没有 companion CSV: {root}")
    for csv_path in csv_files:
        tokens = _csv_components(csv_path.read_text(encoding="utf-8-sig"))
        yield _package_evidence(
            package=csv_path.parents[1].name,
            source=str(csv_path.resolve()),
            tokens=tokens,
            index=index,
            source_authority="legacy-solidworks-urdf-csv",
            source_digest=_sha256(csv_path),
        )


def _robot_package(
    manifest_path: Path,
    model_id: str,
    index: OccurrenceIndex,
    *,
    source_root: Path | None,
) -> PackageEvidence:
    manifest = _read_json(manifest_path)
    releases = _mapping(manifest.get("releases"), "robot manifest.releases")
    spec = _mapping(releases.get(model_id), f"robot manifest.releases.{model_id}")
    root = Path(source_root or _manifest_source_root(manifest)).expanduser().resolve()
    archive_path = (root / _required_text(spec, "archive")).resolve()
    expected_digest = _required_text(spec, "archive_sha256").lower()
    if _sha256(archive_path) != expected_digest:
        raise ProposalError(f"{model_id} robot SourceRelease 摘要漂移")
    csv_member = _required_text(spec, "csv_member")
    try:
        with ZipFile(archive_path) as archive:
            with archive.open(csv_member) as stream:
                csv_text = stream.read().decode("utf-8-sig")
    except (BadZipFile, KeyError, UnicodeError, OSError) as error:
        raise ProposalError(f"{model_id} robot CSV 不可读: {error}") from error
    return _package_evidence(
        package=_required_text(spec, "display_name"),
        source=f"{archive_path}!/{csv_member}",
        tokens=_csv_components(csv_text),
        index=index,
        source_authority=_required_text(spec, "authority"),
        source_digest=expected_digest,
        robot_family=f"robot-family:{model_id.replace('_', '.', 1)}",
    )


def _package_evidence(
    *,
    package: str,
    source: str,
    tokens: tuple[str, ...],
    index: OccurrenceIndex,
    source_authority: str,
    source_digest: str,
    robot_family: str | None = None,
) -> PackageEvidence:
    if not tokens:
        raise ProposalError(f"URDF package 没有 SW Components: {package}")
    matches = {token: index.token_matches(token) for token in tokens}
    unmatched = tuple(token for token, values in matches.items() if not values)
    matched_only = {token: values for token, values in matches.items() if values}
    roots = index.minimal_covering_roots(matched_only)
    return PackageEvidence(
        package=package,
        source=source,
        tokens=tokens,
        token_matches=matches,
        candidate_roots=roots,
        unmatched_tokens=unmatched,
        source_authority=source_authority,
        source_digest=source_digest,
        robot_family=robot_family,
    )


def _select_package_roots(
    packages: list[PackageEvidence],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    selected: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for package in packages:
        if not package.candidate_roots:
            continue
        completeness = (len(package.tokens) - len(package.unmatched_tokens)) / len(package.tokens)
        if completeness < 0.8:
            continue
        for root in package.candidate_roots:
            candidate = {
                "family": package.robot_family or _package_family(package.package),
                "kind": "robot_replacement" if package.robot_family else _package_kind(package.package),
                "package": package.package,
                "source_authority": package.source_authority,
                "review_note": (
                    f"由 {package.package} companion CSV 映射；"
                    f"SW Components 覆盖 {len(package.tokens) - len(package.unmatched_tokens)}/{len(package.tokens)}。"
                ),
                "score": (1 if package.robot_family else 0, completeness, len(package.tokens)),
            }
            previous = selected.get(root)
            if previous is None or candidate["score"] > previous["score"]:
                if previous is not None:
                    duplicates.append({"subtree_root": root, "kept": package.package, "dropped": previous["package"]})
                selected[root] = candidate
            else:
                duplicates.append({"subtree_root": root, "kept": previous["package"], "dropped": package.package})
    return selected, duplicates


def _attach_direct_exclusions(
    selected: dict[str, dict[str, Any]],
    index: OccurrenceIndex,
) -> None:
    roots = set(selected)
    for root, item in selected.items():
        descendants = {candidate for candidate in roots if index.is_strict_descendant(candidate, root)}
        direct = sorted(
            candidate
            for candidate in descendants
            if not any(
                other != candidate
                and other in descendants
                and index.is_strict_descendant(candidate, other)
                for other in descendants
            )
        )
        item["exclude_subtree_roots"] = direct
        item.pop("score", None)


def _select_4ml_bottle(index: OccurrenceIndex) -> str | None:
    candidates = [
        occurrence
        for occurrence, raw in index.by_id.items()
        if PureWindowsPath(str(raw.get("document") or "")).name
        == "4ml玻璃瓶(Default_按加工_).SLDPRT"
    ]
    return min(candidates, key=_natural_key) if candidates else None


def _csv_components(text: str) -> tuple[str, ...]:
    try:
        rows = csv.DictReader(io.StringIO(text))
        result: list[str] = []
        for row in rows:
            for value in str(row.get("SW Components") or "").split(";"):
                token = value.strip()
                if token and token not in result:
                    result.append(token)
    except (csv.Error, UnicodeError) as error:
        raise ProposalError(f"URDF companion CSV 无效: {error}") from error
    return tuple(result)


def _name_variants(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    normalized = _DEFAULT_CONFIG.sub("", normalized)
    normalized = _CAD_EXTENSION.sub("", normalized)
    normalized = _NON_WORD.sub("", normalized)
    variants = [normalized]
    current = normalized
    while _INSTANCE_SUFFIX.search(current):
        current = _INSTANCE_SUFFIX.sub("", current)
        if current and current not in variants:
            variants.append(current)
    return tuple(variants)


def _package_family(package: str) -> str:
    if "投料站料架" in package:
        return "environment.feeding-station-rack"
    if "ETH17" in package:
        return "instrument.rail.eth17"
    if "机器人移动轴模组" in package:
        return "instrument.gripper.nmr-preprocess"
    digest = hashlib.sha256(package.encode("utf-8")).hexdigest()[:12]
    return f"legacy-urdf-family:{digest}"


def _package_kind(package: str) -> str:
    return "static_environment" if "料架" in package else "device"


def _generic_family(root: str) -> str:
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    return f"station-assembly-shell:{digest}"


def _package_json(package: PackageEvidence) -> dict[str, Any]:
    return {
        "package": package.package,
        "source": package.source,
        "source_authority": package.source_authority,
        "source_digest": package.source_digest,
        "robot_family": package.robot_family,
        "sw_component_count": len(package.tokens),
        "matched_component_count": len(package.tokens) - len(package.unmatched_tokens),
        "tokens": [
            {"value": token, "occurrence_matches": list(package.token_matches[token])}
            for token in package.tokens
        ],
        "unmatched_tokens": list(package.unmatched_tokens),
        "candidate_subtree_roots": list(package.candidate_roots),
    }


def _render_review(
    proposal: Mapping[str, Any],
    evidence: Mapping[str, Any],
    selected: Mapping[str, Mapping[str, Any]],
) -> str:
    lines = [
        "# URDF → occurrence 自动分解审核",
        "",
        f"- station：`{proposal['station']}`",
        f"- snapshot occurrence：{evidence['snapshot_occurrence_count']}",
        f"- URDF/机器人包：{evidence['package_count']}",
        f"- 自动规则：{evidence['selected_rule_count']}",
        f"- 机器人根：{', '.join(f'`{item}`' for item in evidence['robot_occurrence_roots']) or '未解析'}",
        f"- 4 ml 有盖瓶几何代表：`{evidence['bottle_4ml_representative'] or '未解析'}`",
        "- proposal 状态：`draft`；可发布：`false`",
        "",
        "## 自动规则",
        "",
        "| subtree root | family | kind | 排除子树数 | 证据包 |",
        "|---|---|---|---:|---|",
    ]
    for root in sorted(selected, key=lambda item: (_depth(item), item)):
        item = selected[root]
        lines.append(
            f"| `{_md(root)}` | `{_md(item['family'])}` | `{item['kind']}` | "
            f"{len(item['exclude_subtree_roots'])} | {_md(item['package'])} |"
        )
    lines.extend(
        [
            "",
            "## 仍需签署",
            "",
            "- 核对 GCR5-910 本体根及 ETH17、安装板、夹爪/末端工具的边界；",
            "- 决定自动选择的 4 ml 有盖瓶是否仅作为代表几何，或绑定具体物理槽位；",
            "- 确认项目 CAD URDF 的关节轴/零位；其 ±π、effort=1、velocity=0.5 仅是受限预览替代值；",
            "- visual 与 collision 共用 STL，不能签为合格碰撞体；",
            "- 填写审核人和时间并改为 approved 前，不得进入真实 W2、部署或真机执行。",
            "",
        ]
    )
    return "\n".join(lines)


def _depth(occurrence: str) -> int:
    return occurrence.count("/")


def _natural_key(value: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value))


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("`", "\\`")


def _manifest_source_root(manifest: Mapping[str, Any]) -> Path:
    source = _mapping(manifest.get("source_root"), "robot manifest.source_root")
    import os

    configured = os.environ.get(_required_text(source, "environment"))
    if configured:
        return Path(configured)
    return Path.home() / _required_text(source, "default_home_relative")


def _relative_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ProposalError("handoff assembly_snapshot 路径无效")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ProposalError("handoff assembly_snapshot 逃逸交接目录") from error
    if not candidate.is_file():
        raise ProposalError(f"handoff assembly_snapshot 不存在: {candidate}")
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProposalError(f"JSON 不可读: {path}: {error}") from error
    return _mapping(value, str(path))


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProposalError(f"{field} 必须是 object")
    return dict(value)


def _required_text(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProposalError(f"{field} 必须是非空文本")
    return value.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ProposalError(f"文件不可读: {path}: {error}") from error
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--legacy-urdf-root", type=Path, required=True)
    parser.add_argument(
        "--robot-manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "robot-source-releases.json",
    )
    parser.add_argument("--robot-model-id", default="duco_gcr5_910")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        proposal, evidence, review = generate_proposal(
            args.handoff.resolve(),
            args.legacy_urdf_root.resolve(),
            robot_manifest_path=args.robot_manifest.resolve(),
            robot_model_id=args.robot_model_id,
            source_root=args.source_root.resolve() if args.source_root else None,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = args.output_dir / "station-decomposition.proposal.yaml"
        evidence_path = args.output_dir / "urdf-occurrence-evidence.json"
        review_path = args.output_dir / "URDF-OCCURRENCE-REVIEW.md"
        proposal_path.write_text(
            yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        review_path.write_text(review, encoding="utf-8", newline="\n")
    except ProposalError as error:
        sys.stderr.write(f"station decomposition proposal rejected: {error}\n")
        return 2
    print(proposal_path)
    print(evidence_path)
    print(review_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
