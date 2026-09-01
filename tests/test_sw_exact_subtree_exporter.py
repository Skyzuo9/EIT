"""Fail-closed tests for the read-only exact occurrence dry-run."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script("sw_exact_subtree_exporter")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SwExactSubtreeExporterTest(unittest.TestCase):
    def test_resolves_only_approved_exact_root_and_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths, request, handoff, layout, source_digest = self._fixture(root)
            receipt = self._resolve_with_approved_inputs(
                paths, request, handoff, layout, source_digest
            )
            self.assertEqual(receipt["status"], "approved-roots-resolved")
            self.assertEqual(receipt["effect"], "none")
            self.assertFalse(receipt["w2_export_started"])
            self.assertEqual(receipt["solidworks_api_calls"], 0)
            self.assertEqual(receipt["source_mutations"], 0)
            self.assertEqual(
                receipt["devices"][0]["resolved_occurrence_ids"],
                ["RACK-1", "RACK-1/FRAME-1"],
            )
            self.assertEqual(
                receipt["devices"][0]["excluded_exact_subtree_roots"],
                ["RACK-1/BOTTLE-1"],
            )
            self.assertIn("w2-export", receipt["not_qualified_for"])

    def test_rejects_inexact_root_and_approval_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths, request, handoff, layout, source_digest = self._fixture(root)
            request["devices"][0]["exact_subtree_root"] = "RACK"
            paths["request"].write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ExactSubtreeDryRunError, "不是批准 layout 的精确"
            ):
                self._resolve_with_approved_inputs(
                    paths, request, handoff, layout, source_digest
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths, request, handoff, layout, source_digest = self._fixture(root)
            request["approval_binding"]["source_files_digest"] = "f" * 64
            paths["request"].write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ExactSubtreeDryRunError, "approval_binding"
            ):
                self._resolve_with_approved_inputs(
                    paths, request, handoff, layout, source_digest
                )

    def test_rejects_any_non_dry_run_mode_before_selection(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths, request, _, _, _ = self._fixture(root)
            request["mode"] = "execute"
            paths["request"].write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ExactSubtreeDryRunError, "只允许 mode=dry-run"
            ):
                MODULE.resolve_approved_roots(
                    request_path=paths["request"],
                    station_handoff=paths["handoff"],
                    decomposition=paths["decomposition"],
                    station_layout=paths["layout"],
                    coverage_report=paths["coverage"],
                    review=paths["review"],
                )

    def test_real_feeding_station_draft_fails_before_root_resolution(self) -> None:
        base = ROOT / "feeding-station-20260827-win03"
        layout_path = base / "p2-auto" / "station-layout.draft.json"
        if not layout_path.is_file():
            self.skipTest("feeding station P2 draft is not present")
        with tempfile.TemporaryDirectory() as raw:
            request_path = Path(raw) / "request.json"
            request = {
                "schema": "lab.sw_exact_subtree_export_request/v1",
                "run_id": "feeding-station-20260831-win03-w2-dry-run",
                "mode": "dry-run",
                "station": "eit.feeding-station",
                "source_read_only": True,
                "approval_binding": {
                    "source_handoff_sha256": "0" * 64,
                    "source_decomposition_sha256": "0" * 64,
                    "station_layout_sha256": "0" * 64,
                    "source_files_digest": "0" * 64,
                },
                "solidworks": {"revision": "2025", "configuration": "默认"},
                "exporter": {
                    "name": "SwExactSubtreeExporter",
                    "version": "dry-run-v1",
                    "selection_mode": "approved-exact-occurrence-root",
                },
                "devices": [
                    {
                        "asset_instance": "rack-left-01",
                        "slice_role": "rack",
                        "family": "environment.rack",
                        "exact_subtree_root": "投料站料架-1",
                    }
                ],
            }
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.ExactSubtreeDryRunError, "审批门失败"
            ):
                MODULE.resolve_approved_roots(
                    request_path=request_path,
                    station_handoff=base / "station-handoff.json",
                    decomposition=base / "p2-auto" / "station-decomposition.proposal.yaml",
                    station_layout=layout_path,
                    coverage_report=base / "p2-auto" / "coverage-report.json",
                    review=base / "p2-auto" / "DECOMPOSITION-REVIEW.md",
                )

    @staticmethod
    def _resolve_with_approved_inputs(paths, request, handoff, layout, source_digest):
        paths["request"].write_text(
            json.dumps(request, ensure_ascii=False), encoding="utf-8"
        )
        with mock.patch.object(
            MODULE,
            "_validate_approval_inputs",
            return_value=(handoff, layout, {"exact_coverage": True}, source_digest),
        ):
            return MODULE.resolve_approved_roots(
                request_path=paths["request"],
                station_handoff=paths["handoff"],
                decomposition=paths["decomposition"],
                station_layout=paths["layout"],
                coverage_report=paths["coverage"],
                review=paths["review"],
            )

    @staticmethod
    def _fixture(root: Path):
        handoff_root = root / "w1"
        capture = handoff_root / "capture"
        capture.mkdir(parents=True)
        snapshot = {
            "schema": "lab.assembly_snapshot/v0",
            "instances": [
                {"id": "RACK-1", "parent": None},
                {"id": "RACK-1/FRAME-1", "parent": "RACK-1"},
                {"id": "RACK-1/BOTTLE-1", "parent": "RACK-1"},
                {"id": "RACK-1/BOTTLE-1/CAP-1", "parent": "RACK-1/BOTTLE-1"},
                {"id": "FOREIGN-1", "parent": None},
            ],
            "root_occurrences": ["RACK-1", "FOREIGN-1"],
            "mates_candidate": [],
        }
        snapshot_path = capture / "assembly.snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        handoff = {
            "station": "eit.feeding-station",
            "solidworks_capture": {"assembly_snapshot": "capture/assembly.snapshot.json"},
        }
        paths = {
            "request": root / "request.json",
            "handoff": handoff_root / "station-handoff.json",
            "decomposition": root / "station-decomposition.yaml",
            "layout": root / "station-layout.json",
            "coverage": root / "coverage-report.json",
            "review": root / "DECOMPOSITION-REVIEW.md",
        }
        for name, path in paths.items():
            if name != "request":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
        paths["handoff"].write_text(json.dumps(handoff), encoding="utf-8")
        source_digest = "a" * 64
        layout = {
            "placements": [
                {
                    "family": "environment.rack",
                    "kind": "static_environment",
                    "subtree_root": "RACK-1",
                    "excluded_subtree_roots": ["RACK-1/BOTTLE-1"],
                    "source_occurrences": ["RACK-1", "RACK-1/FRAME-1"],
                }
            ]
        }
        request = {
            "schema": "lab.sw_exact_subtree_export_request/v1",
            "run_id": "fixture-win04-w2-dry-run",
            "mode": "dry-run",
            "station": "eit.feeding-station",
            "source_read_only": True,
            "approval_binding": {
                "source_handoff_sha256": sha256(paths["handoff"]),
                "source_decomposition_sha256": sha256(paths["decomposition"]),
                "station_layout_sha256": sha256(paths["layout"]),
                "source_files_digest": source_digest,
            },
            "solidworks": {"revision": "2025", "configuration": "默认"},
            "exporter": {
                "name": "SwExactSubtreeExporter",
                "version": "dry-run-v1",
                "selection_mode": "approved-exact-occurrence-root",
            },
            "devices": [
                {
                    "asset_instance": "rack-left-01",
                    "slice_role": "rack",
                    "family": "environment.rack",
                    "exact_subtree_root": "RACK-1",
                }
            ],
        }
        return paths, request, handoff, layout, source_digest


if __name__ == "__main__":
    unittest.main()
