"""Spatial-ready collision asset contract and deterministic compiler tests."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "compile_collision_geometry_manifest.py"
SCHEMA = ROOT / "schemas" / "collision-geometry-manifest-v1.schema.json"
SELECTION_SCHEMA = ROOT / "schemas" / "collision-candidate-selection-v1.schema.json"
ARTIFACT = (
    ROOT
    / "artifacts"
    / "collision-assets"
    / "v1"
    / "ptlc-collision-geometry-manifest.json"
)
SPEC = importlib.util.spec_from_file_location("compile_collision_geometry_manifest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CollisionGeometryManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)
        selection_schema = json.loads(SELECTION_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(selection_schema)
        cls.selection_validator = Draft202012Validator(selection_schema)

    def test_current_ptlc_manifest_is_deterministic_and_schema_valid(self) -> None:
        first = MODULE.compile_ptlc_candidate_manifest(ROOT)
        second = MODULE.compile_ptlc_candidate_manifest(ROOT)
        self.assertEqual(first, second)
        MODULE.validate_manifest_identity(first)
        self.validator.validate(first)
        self.assertEqual(ARTIFACT.read_bytes(), MODULE._encoded_document(first))

        self.assertEqual(first["qualification"], "collision-candidate")
        self.assertEqual(first["allowed_uses"], ["offline-review", "shadow"])
        self.assertFalse(first["capabilities"]["collision_qualified"])
        self.assertFalse(first["capabilities"]["dynamic_links"])
        self.assertEqual(len(first["assets"]), 15)
        self.assertIn("raw-bytes", {item["digest_mode"] for item in first["source_artifacts"]})
        self.assertEqual(
            first["generator"]["implementation_digest_mode"], "utf8-lf-v1"
        )

    def test_visual_and_collision_representations_are_separate_and_bound(self) -> None:
        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        for asset in manifest["assets"]:
            with self.subTest(asset_id=asset["asset_id"]):
                self.assertNotEqual(asset["visual"]["path"], asset["narrow_phase"]["path"])
                self.assertEqual(asset["visual"]["format"], "glb")
                self.assertEqual(asset["visual"]["source_unit"], "m")
                self.assertEqual(asset["narrow_phase"]["format"], "stl")
                self.assertIn(asset["narrow_phase"]["source_unit"], {"m", "mm"})
                self.assertTrue(asset["narrow_phase"]["watertight"])
                self.assertEqual(asset["qualification"], "collision-candidate")
                self.assertIn(
                    "collision-candidate-not-qualified", asset["reason_codes"]
                )
                for representation in (asset["visual"], asset["narrow_phase"]):
                    path = ROOT / representation["path"]
                    self.assertTrue(path.is_file())
                    self.assertEqual(representation["sha256"], MODULE._sha256(path))

    def test_source_derived_compound_convex_is_selected_fail_closed(self) -> None:
        selection = json.loads((ROOT / MODULE.CANDIDATE_SELECTION).read_text(encoding="utf-8"))
        self.selection_validator.validate(selection)
        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        rack = next(asset for asset in manifest["assets"] if asset["asset_id"] == "develop_tank_rack")
        self.assertEqual(rack["narrow_phase"]["representation"], "compound-convex")
        self.assertEqual(rack["narrow_phase"]["component_count"], 40)
        self.assertEqual(rack["narrow_phase"]["source_unit"], "m")
        self.assertIn("compound-convex.runtime.stl", rack["narrow_phase"]["path"])
        self.assertEqual(rack["derivation"]["algorithm_version"], "v3")
        self.assertTrue(rack["qc"]["open_cavity_preserved"])

        report_path = ROOT / selection["selections"][0]["report_path"]
        rejected = json.loads(report_path.read_text(encoding="utf-8"))
        rejected["levels"]["l2"]["compound_convex"]["cavity_preservation"]["status"] = "not-preserved"
        rejected["levels"]["l2"]["compound_convex"]["cavity_preservation"]["cavity_preserved"] = False
        with self.assertRaisesRegex(MODULE.CollisionManifestError, "空腔未保留"):
            MODULE.compile_ptlc_candidate_manifest(
                ROOT, candidate_report_values={"develop_tank_rack": rejected}
            )

    def test_open_workstations_preserve_cavities(self) -> None:
        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        open_assets = [asset for asset in manifest["assets"] if asset["qc"]["open_cavity_expected"]]
        self.assertGreaterEqual(len(open_assets), 1)
        for asset in open_assets:
            with self.subTest(asset_id=asset["asset_id"]):
                self.assertTrue(asset["qc"]["open_cavity_preserved"])
                self.assertTrue(asset["qc"]["source_components_disjoint"])
                self.assertIn(
                    asset["narrow_phase"]["representation"],
                    {"multi-body-open", "compound-convex"},
                )
                self.assertGreater(asset["narrow_phase"]["component_count"], 1)

    def test_tools_are_not_misclassified_as_static_environment(self) -> None:
        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        roles = {asset["asset_id"]: asset["role"] for asset in manifest["assets"]}
        self.assertEqual(roles["tool_suction"], "stored-tool")
        self.assertEqual(roles["tool_large_gripper"], "stored-tool")
        self.assertEqual(roles["tool_small_gripper"], "stored-tool")
        self.assertEqual(roles["tool_station"], "static-environment")

    def test_candidate_schema_rejects_software_admission_or_qualification_upgrade(self) -> None:
        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        manifest["allowed_uses"].append("software-admission")
        errors = list(self.validator.iter_errors(manifest))
        self.assertTrue(errors)

        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        manifest["capabilities"]["collision_qualified"] = True
        errors = list(self.validator.iter_errors(manifest))
        self.assertTrue(errors)

    def test_absolute_or_parent_escaping_paths_are_rejected(self) -> None:
        for invalid in ("C:\\temp\\collision.stl", "/tmp/collision.stl", "../collision.stl"):
            with self.subTest(path=invalid):
                manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
                manifest["assets"][0]["narrow_phase"]["path"] = invalid
                errors = list(self.validator.iter_errors(manifest))
                self.assertTrue(errors)

    def test_digest_drift_is_rejected(self) -> None:
        manifest = MODULE.compile_ptlc_candidate_manifest(ROOT)
        manifest["assets"][0]["nominal_dimensions_m"][0] += 0.001
        with self.assertRaisesRegex(MODULE.CollisionManifestError, "manifest_digest"):
            MODULE.validate_manifest_identity(manifest)

    def test_semantic_digest_is_stable_across_lf_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            json_lf = root / "lf.json"
            json_crlf = root / "crlf.json"
            text_lf = root / "lf.py"
            text_crlf = root / "crlf.py"
            json_lf.write_bytes(b'{"b": 2, "a": 1}\n')
            json_crlf.write_bytes(b'{\r\n  "a": 1,\r\n  "b": 2\r\n}\r\n')
            text_lf.write_bytes(b"first\nsecond\n")
            text_crlf.write_bytes(b"first\r\nsecond\r\n")

            self.assertEqual(
                MODULE._artifact_digest(json_lf, "canonical-json-v1"),
                MODULE._artifact_digest(json_crlf, "canonical-json-v1"),
            )
            self.assertEqual(
                MODULE._artifact_digest(text_lf, "utf8-lf-v1"),
                MODULE._artifact_digest(text_crlf, "utf8-lf-v1"),
            )
            self.assertNotEqual(
                MODULE._artifact_digest(json_lf, "raw-bytes"),
                MODULE._artifact_digest(json_crlf, "raw-bytes"),
            )

    def test_missing_asset_or_failed_cavity_qc_is_rejected(self) -> None:
        qc = json.loads((ROOT / MODULE.COLLISION_QC).read_text(encoding="utf-8"))
        missing = deepcopy(qc)
        missing["assets"].pop()
        missing["count"] -= 1
        with self.assertRaisesRegex(MODULE.CollisionManifestError, "资产集合不一致"):
            MODULE.compile_ptlc_candidate_manifest(ROOT, collision_qc_value=missing)

        failed = deepcopy(qc)
        target = next(item for item in failed["assets"] if item["open_cavity_expected"])
        target["open_cavity_preserved"] = False
        with self.assertRaisesRegex(MODULE.CollisionManifestError, "开放空腔未保留"):
            MODULE.compile_ptlc_candidate_manifest(ROOT, collision_qc_value=failed)


if __name__ == "__main__":
    unittest.main()
