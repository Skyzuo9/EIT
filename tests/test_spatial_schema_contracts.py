"""Contract-level guards for the narrow spatial shadow v0 schemas."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCHEMA_DIR = ROOT / "schemas"
DIGEST = "0" * 64


def _load_validator(filename: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class SpatialSchemaContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.certificate_validator = _load_validator(
            "spatial-occupancy-certificate-v0.schema.json"
        )
        cls.decision_validator = _load_validator(
            "spatial-interlock-decision-v0.schema.json"
        )

    def test_v0_candidate_certificate_is_valid(self) -> None:
        self.certificate_validator.validate(self._candidate_certificate())

    def test_v0_certificate_rejects_qualification_upgrade(self) -> None:
        for qualification in ("collision-qualified", "hardware-qualified"):
            with self.subTest(qualification=qualification):
                certificate = self._candidate_certificate()
                certificate["qualification"] = qualification
                errors = list(self.certificate_validator.iter_errors(certificate))
                self.assertTrue(errors)
                self.assertTrue(
                    any(list(error.path) == ["qualification"] for error in errors)
                )

    def test_shadow_decision_accepts_all_observational_classifications(self) -> None:
        for result in ("allowed", "blocked", "unknown"):
            with self.subTest(decision=result):
                decision = self._shadow_decision()
                decision["decision"] = result
                self.decision_validator.validate(decision)

    def test_shadow_decision_rejects_enforced_mode(self) -> None:
        decision = self._shadow_decision()
        decision["mode"] = "enforced"
        self.assertFalse(self.decision_validator.is_valid(decision))

    def test_shadow_decision_rejects_runtime_effect(self) -> None:
        for effect in ("allow", "deny", "block"):
            with self.subTest(effect=effect):
                decision = self._shadow_decision()
                decision["effect"] = effect
                self.assertFalse(self.decision_validator.is_valid(decision))

    @staticmethod
    def _candidate_certificate() -> dict[str, object]:
        return {
            "schema": "lab.spatial-occupancy-certificate/v0",
            "certificate_id": f"spatial-cert:{DIGEST}",
            "sample_id": "fixture-sample",
            "action_contract_id": "fixture-action",
            "mode": "shadow",
            "qualification": "candidate",
            "input_digests": {
                "test_lock": DIGEST,
                "collision_scene": DIGEST,
                "motion_contract": DIGEST,
            },
            "analysis": {
                "motion_corridor_status": "not-computed",
                "continuous_collision_status": "not-computed",
                "stop_envelope_status": "unknown",
                "recovery_envelope_status": "unknown",
                "result": "unknown",
                "reason_codes": ["fixture"],
            },
            "certificate_digest": DIGEST,
        }

    @staticmethod
    def _shadow_decision() -> dict[str, object]:
        return {
            "schema": "lab.spatial-interlock-decision/v0",
            "decision_id": f"spatial-decision:{DIGEST}",
            "mode": "shadow",
            "effect": "none",
            "sample_id": "fixture-sample",
            "action_contract_id": "fixture-action",
            "certificate_ref": f"spatial-cert:{DIGEST}",
            "world_snapshot_version": "fixture-world-v0",
            "decision": "unknown",
            "reason_codes": ["fixture"],
            "decision_digest": DIGEST,
        }


if __name__ == "__main__":
    unittest.main()
