"""Issue #42: synthetic least-privilege identity and outer spend-cap regressions."""

import unittest
from unittest.mock import patch

from developer_team.agents_acceptance import ReadOnlyVerifier
from tests.acceptance_support import Collector
from tests.agents_api_support import NOW
from tests.provider_readonly_support import Harness


class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.socket = self.enterContext(
            patch("socket.socket", side_effect=AssertionError("offline"))
        )
        self.h = Harness()

    def tearDown(self):
        self.socket.assert_not_called()

    def set_role(self, role):
        self.h.account["role"] = role
        self.h.key["owner"]["service_account"]["role"] = role

    def test_all_documented_default_roles_allow_identity_binding(self):
        for role in ("none", "member", "owner"):
            with self.subTest(role=role):
                self.set_role(role)
                self.assertEqual(self.h.check("account_project_binding"), "PASS")

    def test_none_and_successful_gets_do_not_supply_missing_scope(self):
        self.set_role("none")
        self.h.spend["threshold_amount"] = 100
        self.h.collector._scope_source = None
        report = self.h.collector.report()
        for gate in ("account_project_binding", "agent_configuration", "spend_controls"):
            self.assertEqual(report["checks"][gate], "PASS")
        self.assertEqual(report["checks"]["credential_scope"], "MISSING_OR_INVALID")
        self.assertEqual(len(self.h.calls), 6)
        self.assertTrue(all(method == "GET" for _, method, _ in self.h.calls))
        self.assertEqual(report["real_submissions"], 0)
        self.assertEqual(report["live"], "NO-GO")
        self.assertIs(report["live_authorized"], False)
        self.assertEqual(self.h.bound.budget_cents, 5)
        self.assertEqual(self.h.spend["threshold_amount"], 100)

    def test_none_still_requires_independent_scope_verifier(self):
        self.set_role("none")
        self.h.collector._scope_verifier = None
        self.assertEqual(self.h.check("account_project_binding"), "PASS")
        self.assertEqual(self.h.check("credential_scope"), "MISSING_OR_INVALID")

    def test_none_with_independent_synthetic_scope_only_satisfies_scope_gate(self):
        self.set_role("none")
        report = self.h.collector.report()
        self.assertEqual(report["checks"]["credential_scope"], "PASS")
        self.assertGreater(self.h.scope_verifier.calls, 0)
        self.assertEqual(report["live"], "NO-GO")
        self.assertIs(report["live_authorized"], False)
        self.assertEqual(report["real_submissions"], 0)

    def test_unknown_roles_block_even_when_account_and_principal_agree(self):
        for role in ("unknown", "custom", "", None, True, 0):
            with self.subTest(role=role):
                self.set_role(role)
                self.assertEqual(self.h.check("account_project_binding"), "MISSING_OR_INVALID")

    def test_every_account_principal_role_mismatch_blocks(self):
        for account in ("none", "member", "owner"):
            for principal in ("none", "member", "owner", None):
                if account == principal:
                    continue
                with self.subTest(account=account, principal=principal):
                    self.set_role(account)
                    self.h.key["owner"]["service_account"]["role"] = principal
                    self.assertEqual(self.h.check("account_project_binding"), "MISSING_OR_INVALID")

    def test_none_does_not_relax_project_account_or_key_binding(self):
        for target in ("account", "key", "principal"):
            with self.subTest(target=target):
                self.h = Harness()
                self.set_role("none")
                item = (
                    self.h.key["owner"]["service_account"]
                    if target == "principal"
                    else getattr(self.h, target)
                )
                item["project_id"] = "proj_foreign"
                self.assertEqual(self.h.check("account_project_binding"), "MISSING_OR_INVALID")
        for target in ("account", "key", "principal"):
            with self.subTest(identity=target):
                self.h = Harness()
                self.set_role("none")
                item = (
                    self.h.key["owner"]["service_account"]
                    if target == "principal"
                    else getattr(self.h, target)
                )
                item["id"] = "foreign"
                self.assertEqual(self.h.check("account_project_binding"), "MISSING_OR_INVALID")

    def test_provider_limits_keep_observed_integer_cents_across_valid_range(self):
        self.assertEqual(self.h.bound.budget_cents, 5)
        for limit in (5, 6, 99, 100):
            with self.subTest(limit=limit):
                self.h.spend["threshold_amount"] = limit
                checks, observations = ReadOnlyVerifier(self.h.collector).inspect(
                    self.h.bound, NOW, self.h.identity
                )
                self.assertEqual(checks["spend_controls"], "PASS")
                self.assertEqual(
                    observations["spend_controls"].facts,
                    {"project_limit_cents": limit, "enforcement_delayed": True},
                )
                self.assertEqual(self.h.bound.budget_cents, 5)

    def test_provider_rejects_out_of_range_and_non_integer_thresholds(self):
        for limit in (0, 4, 101, -1, True, False, 5.0, 100.0, "5", "100", None):
            with self.subTest(limit=limit):
                self.h.spend["threshold_amount"] = limit
                self.assertEqual(self.h.check("spend_controls"), "MISSING_OR_INVALID")

    def test_outer_limit_still_requires_currency_interval_and_enforcement(self):
        for changes in (
            {"currency": "EUR"},
            {"interval": "day"},
            {"enforcement": {"status": "inactive"}},
            {"enforcement": {"status": "enforcing", "unexpected": True}},
            {"enforcement": None},
            {"object": "soft_limit"},
        ):
            with self.subTest(changes=changes):
                self.h = Harness()
                self.h.spend.update(threshold_amount=100, **changes)
                self.assertEqual(self.h.check("spend_controls"), "MISSING_OR_INVALID")

    def inspect_spend(self, **facts):
        collector = Collector()
        collector.drift("spend_controls", **facts)
        return ReadOnlyVerifier(collector).inspect(self.h.bound, NOW, self.h.identity)

    def test_verifier_independently_accepts_outer_cap_without_local_budget_change(self):
        for limit in (5, 6, 99, 100):
            with self.subTest(limit=limit):
                checks, observations = self.inspect_spend(project_limit_cents=limit)
                self.assertEqual(checks["spend_controls"], "PASS")
                self.assertEqual(observations["spend_controls"].facts["project_limit_cents"], limit)
                self.assertEqual(self.h.bound.budget_cents, 5)

    def test_verifier_independently_rejects_invalid_outer_caps(self):
        for limit in (0, 4, 101, -1, True, False, 5.0, 100.0, "5", "100", None):
            with self.subTest(limit=limit):
                checks, observations = self.inspect_spend(project_limit_cents=limit)
                self.assertEqual(checks["spend_controls"], "MISSING_OR_INVALID")
                self.assertNotIn("spend_controls", observations)

    def test_verifier_requires_explicit_delayed_enforcement_and_exact_schema(self):
        for facts in (
            {"enforcement_delayed": False},
            {"enforcement_delayed": 1},
            {"enforcement_delayed": None},
            {"unexpected": True},
        ):
            with self.subTest(facts=facts):
                checks, _ = self.inspect_spend(project_limit_cents=100, **facts)
                self.assertEqual(checks["spend_controls"], "MISSING_OR_INVALID")
        for field in ("project_limit_cents", "enforcement_delayed"):
            collector = Collector()
            del collector.observations["spend_controls"].facts[field]
            checks, _ = ReadOnlyVerifier(collector).inspect(self.h.bound, NOW, self.h.identity)
            self.assertEqual(checks["spend_controls"], "MISSING_OR_INVALID")
