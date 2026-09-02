#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from method_identity import (  # noqa: E402
    G120_NOT_PRODUCTION_ASSERTION,
    METHOD_IDENTITIES,
    assert_identity_contract,
    method_identity,
    require_method_identity,
)


class MethodIdentityTests(unittest.TestCase):
    def test_exact_frozen_role_strings(self) -> None:
        self.assertEqual(
            METHOD_IDENTITIES["g120_on"]["role"],
            "G120-A (S-VIO-derived new method)",
        )
        self.assertEqual(
            METHOD_IDENTITIES["g120_off"]["role"],
            "G120-A matched XFeat-OFF",
        )
        self.assertEqual(
            METHOD_IDENTITIES["released_svio"]["role"],
            "original released S-VIO comparator",
        )

    def test_every_lineage_excludes_production_and_paper_configuration(self) -> None:
        assert_identity_contract()
        self.assertEqual(
            G120_NOT_PRODUCTION_ASSERTION,
            "G120-A is not the production estimator and is not a production paper configuration.",
        )
        for identity in METHOD_IDENTITIES.values():
            self.assertIs(identity["lineage"]["is_production_estimator"], False)
            self.assertIs(identity["lineage"]["is_production_paper_configuration"], False)

    def test_receipt_requires_exact_role_and_full_structured_lineage(self) -> None:
        expected = method_identity("g120_on")
        require_method_identity(expected, "g120_on", label="synthetic receipt")
        for key in ("role", "lineage"):
            bad = method_identity("g120_on")
            bad[key] = "drift" if key == "role" else {"is_production_estimator": False}
            with self.assertRaisesRegex(RuntimeError, "role/lineage"):
                require_method_identity(bad, "g120_on", label="synthetic receipt")

    def test_legacy_arm_aliases_map_without_changing_receipt_identity(self) -> None:
        self.assertEqual(method_identity("on"), method_identity("g120_on"))
        self.assertEqual(method_identity("off"), method_identity("g120_off"))
        self.assertEqual(method_identity("comparator"), method_identity("released_svio"))


if __name__ == "__main__":
    unittest.main()
