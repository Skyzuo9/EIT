"""Geometry and QC tests for L0/L1/L2 collision candidates."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script("generate_collision_candidates")


@unittest.skipIf(MODULE.trimesh is None, "trimesh geometry test extras are not installed")
class CollisionCandidateGeneratorTest(unittest.TestCase):
    def test_generates_all_levels_and_required_qc(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = MODULE.trimesh.creation.box(extents=(1.0, 0.5, 0.25))
            glb = root / "box.glb"
            glb.write_bytes(MODULE.trimesh.Scene({"box": source}).export(file_type="glb"))
            request_path = self._request(root, "glb", glb.name)
            output = root / "out"
            report = MODULE.generate(request_path, output)
            self.assertEqual(report["status"], "candidate-generated")
            self.assertEqual(set(report["levels"]), {"l0", "l1", "l2"})
            self.assertEqual(len(report["files"]), 8)
            for item in report["files"]:
                self.assertTrue((output / item["path"]).is_file())
                self.assertEqual(len(item["sha256"]), 64)
            for candidate in self._candidates(report):
                self.assertIn("size_error", candidate)
                self.assertIn("maximum_missed_envelope_m", candidate["missed_envelope"])
                self.assertIn("cavity_preserved", candidate["cavity_preservation"])
                self.assertIn("component_count", candidate["geometry"])
                self.assertIn("is_watertight", candidate["geometry"]["watertight"])
            self.assertTrue(
                report["levels"]["l2"]["compound_convex"]["missed_envelope"]["passes_at_1e-8_m"]
            )
            multi_sphere = report["levels"]["l1"]["multi_sphere"]
            self.assertEqual(multi_sphere["geometry"]["analytic_primitive"], "sphere-set")
            self.assertEqual(multi_sphere["geometry"]["primitive_count"], 1)
            self.assertTrue(
                multi_sphere["missed_envelope"]["passes_at_1e-8_m"]
            )
            self.assertEqual(
                multi_sphere["runtime_artifact"]["format"], "json"
            )
            self.assertTrue(
                (output / report["levels"]["l2"]["compound_convex"]["runtime_artifact"]["path"])
                .is_file()
            )
            self.assertEqual(
                report["levels"]["l2"]["compound_convex"]["runtime_artifact"]["component_triangle_counts"],
                [12],
            )

    def test_compound_convex_preserves_disconnected_component_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            left = MODULE.trimesh.creation.box(extents=(0.2, 0.2, 0.2))
            right = left.copy()
            left.apply_translation((-0.6, 0.0, 0.0))
            right.apply_translation((0.6, 0.0, 0.0))
            scene = MODULE.trimesh.Scene({"left": left, "right": right})
            glb = root / "two-boxes.glb"
            glb.write_bytes(scene.export(file_type="glb"))
            request_path = self._request(root, "glb", glb.name, cavity_limit=0.01)
            report = MODULE.generate(request_path, root / "out")
            hull_qc = report["levels"]["l1"]["convex_hull"]["cavity_preservation"]
            compound = report["levels"]["l2"]["compound_convex"]
            compound_qc = compound["cavity_preservation"]
            self.assertEqual(report["source_geometry"]["component_count"], 2)
            self.assertEqual(compound["geometry"]["component_count"], 2)
            self.assertEqual(hull_qc["status"], "not-preserved")
            self.assertEqual(compound_qc["status"], "preserved")
            self.assertTrue(compound_qc["component_separation_preserved"])
            multi_sphere = report["levels"]["l1"]["multi_sphere"]
            self.assertEqual(multi_sphere["geometry"]["primitive_count"], 2)
            self.assertTrue(multi_sphere["missed_envelope"]["passes_at_1e-8_m"])

    def test_step_requires_and_binds_explicit_tessellation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            step = root / "fixture.step"
            step.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="ascii")
            mesh = MODULE.trimesh.creation.cylinder(radius=0.02, height=0.05)
            glb = root / "fixture.glb"
            glb.write_bytes(MODULE.trimesh.Scene({"fixture": mesh}).export(file_type="glb"))
            request_path = self._request(root, "step", step.name, tessellated=glb.name)
            report = MODULE.generate(request_path, root / "out")
            self.assertEqual(report["source"]["kind"], "step")
            self.assertEqual(report["source"]["geometry_basis"], "explicit-step-tessellation-glb")
            self.assertFalse(report["source"]["direct_brep_parsed"])
            self.assertNotEqual(report["source"]["source_sha256"], report["source"]["geometry_sha256"])

    def test_simplified_static_mesh_reports_nonconservative_error(self) -> None:
        try:
            import fast_simplification  # noqa: F401
        except ImportError:
            self.skipTest("fast-simplification is not installed")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            mesh = MODULE.trimesh.creation.icosphere(subdivisions=3, radius=0.1)
            glb = root / "sphere.glb"
            glb.write_bytes(MODULE.trimesh.Scene({"sphere": mesh}).export(file_type="glb"))
            value = {
                "schema": MODULE.REQUEST_SCHEMA,
                "asset_id": "fixture.simplified",
                "source": {"kind": "glb", "path": glb.name, "unit": "m"},
                "policy": {
                    **self._policy(),
                    "l2_mode": "simplified-static-mesh",
                    "target_face_ratio": 0.25,
                },
            }
            request = root / "simplified-request.json"
            request.write_text(json.dumps(value), encoding="utf-8")
            report = MODULE.generate(request, root / "out")
            candidate = report["levels"]["l2"]["simplified_static_mesh"]
            self.assertEqual(candidate["method"], "quadric-decimation-static-mesh")
            self.assertFalse(candidate["missed_envelope"]["containment_guarantee"])
            self.assertLess(candidate["geometry"]["triangles"], report["source_geometry"]["triangles"])

    def test_rejects_step_without_tessellation_and_output_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            step = root / "fixture.step"
            step.write_text("ISO-10303-21;", encoding="ascii")
            bad = {
                "schema": MODULE.REQUEST_SCHEMA,
                "asset_id": "fixture.step",
                "source": {"kind": "step", "path": step.name},
                "policy": self._policy(),
            }
            bad_path = root / "bad.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CollisionCandidateError, "缺少"):
                MODULE.validate_request(bad_path)

            mesh = MODULE.trimesh.creation.box()
            glb = root / "box.glb"
            glb.write_bytes(MODULE.trimesh.Scene({"box": mesh}).export(file_type="glb"))
            request_path = self._request(root, "glb", glb.name)
            output = root / "out"
            output.mkdir()
            (output / "keep.txt").write_text("user data", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CollisionCandidateError, "禁止覆盖"):
                MODULE.generate(request_path, output)
            self.assertEqual((output / "keep.txt").read_text(), "user data")

    @staticmethod
    def _policy(cavity_limit: float = 0.05):
        return {
            "l2_mode": "compound-convex",
            "max_components": 128,
            "max_sample_vertices": 4096,
            "cavity_added_fill_ratio_limit": cavity_limit,
        }

    @classmethod
    def _request(cls, root: Path, kind: str, path: str, *, tessellated=None, cavity_limit=0.05):
        if kind == "glb":
            source = {"kind": "glb", "path": path, "unit": "m"}
        else:
            source = {
                "kind": "step",
                "path": path,
                "tessellated_path": tessellated,
                "tessellated_unit": "m",
            }
        value = {
            "schema": MODULE.REQUEST_SCHEMA,
            "asset_id": "fixture.asset",
            "source": source,
            "policy": cls._policy(cavity_limit),
        }
        request = root / f"{kind}-request.json"
        request.write_text(json.dumps(value), encoding="utf-8")
        return request

    @staticmethod
    def _candidates(report):
        return [
            report["levels"]["l0"]["aabb"],
            report["levels"]["l0"]["obb"],
            report["levels"]["l1"]["best_primitive"],
            report["levels"]["l1"]["convex_hull"],
            report["levels"]["l1"]["multi_sphere"],
            report["levels"]["l2"]["compound_convex"],
        ]


if __name__ == "__main__":
    unittest.main()
