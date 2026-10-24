"""Issue #49: synthetic JSON attacks at the official CLI/broker boundary."""

import json
import socket
import unittest
from copy import deepcopy
from unittest.mock import patch

from developer_team import provider_readonly_prepare as broker
from developer_team import provider_readonly_runner as runner
from developer_team.adapters.agents_api_contracts import AgentsAPIError
from developer_team.provider_readonly_diagnostics import PROVIDER_GATES


class ReportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.socket = self.enterContext(patch.object(socket, "socket", side_effect=AssertionError))
        self.enterContext(patch("os.pread", side_effect=AssertionError("read forbidden")))

    def tearDown(self):
        self.socket.assert_not_called()

    def collected(self, valid):
        report = runner._report("READ_ONLY", "COLLECTED")
        if valid:
            for gate in PROVIDER_GATES:
                report["checks"][gate] = "PASS"
                report["provider_diagnostics"][gate] = {"stage": "FINAL_VALIDATION", "code": "PASS"}
            report["provider_observations"] = "SOME_VALID"
        self.assertEqual(broker._sanitize(json.dumps(report)), report)
        return report

    def reject_forged_pass(self, gate):
        # Both the review's all-missing report and an otherwise valid collection.
        for valid in (False, True):
            with self.subTest(provider_valid=valid):
                report = self.collected(valid)
                report["checks"][gate] = "PASS"
                with self.assertRaises(AgentsAPIError):
                    broker._sanitize(json.dumps(report))

    def test_provider_contract_current_pass_rejected(self):
        self.reject_forged_pass("provider_contract_current")

    def test_credential_scope_pass_rejected(self):
        self.reject_forged_pass("credential_scope")

    def test_secret_store_pass_rejected(self):
        self.reject_forged_pass("secret_store")

    def test_environment_configuration_pass_rejected(self):
        self.reject_forged_pass("environment_configuration")

    def test_single_canary_grant_pass_rejected(self):
        self.reject_forged_pass("single_canary_grant")

    def test_real_transport_pass_rejected(self):
        self.reject_forged_pass("real_transport")

    def test_durable_journal_pass_rejected(self):
        self.reject_forged_pass("durable_journal")

    def test_fresh_create_approval_pass_rejected(self):
        self.reject_forged_pass("fresh_create_approval")

    def test_fresh_submit_approval_pass_rejected(self):
        self.reject_forged_pass("fresh_submit_approval")

    def test_all_provider_pass_subsets_require_exact_diagnostics_and_summary(self):
        for mask in range(8):
            report = self.collected(False)
            for index, gate in enumerate(PROVIDER_GATES):
                if mask & (1 << index):
                    report["checks"][gate] = "PASS"
                    report["provider_diagnostics"][gate] = {
                        "stage": "FINAL_VALIDATION",
                        "code": "PASS",
                    }
            report["provider_observations"] = "SOME_VALID" if mask else "NONE_VALID"
            self.assertEqual(broker._sanitize(json.dumps(report)), report)
            for gate in PROVIDER_GATES:
                changed = deepcopy(report)
                changed["checks"][gate] = (
                    runner.MISSING if report["checks"][gate] == "PASS" else "PASS"
                )
                with self.subTest(mask=mask, gate=gate), self.assertRaises(AgentsAPIError):
                    broker._sanitize(json.dumps(changed))
            changed = report | {"provider_observations": "NONE_VALID" if mask else "SOME_VALID"}
            with self.assertRaises(AgentsAPIError):
                broker._sanitize(json.dumps(changed))

    def test_blocked_must_be_canonical_and_cannot_carry_collected_evidence(self):
        blocked = runner._report("READ_ONLY", "BLOCKED")
        self.assertEqual(broker._sanitize(json.dumps(blocked)), blocked)
        for gate in runner.GATES:
            changed = deepcopy(blocked)
            changed["checks"][gate] = "PASS"
            if gate in PROVIDER_GATES:
                changed["provider_diagnostics"][gate] = {
                    "stage": "FINAL_VALIDATION",
                    "code": "PASS",
                }
                changed["provider_observations"] = "SOME_VALID"
            with self.subTest(gate=gate), self.assertRaises(AgentsAPIError):
                broker._sanitize(json.dumps(changed))
        changed = deepcopy(blocked)
        changed["provider_diagnostics"][PROVIDER_GATES[0]] = {
            "stage": "ADMIN_PROJECT",
            "code": "HTTP_403",
        }
        with self.assertRaises(AgentsAPIError):
            broker._sanitize(json.dumps(changed))

    def test_schema_vocabulary_types_and_boolean_confusion_rejected(self):
        report = self.collected(True)
        for field in report:
            with self.subTest(field=field), self.assertRaises(AgentsAPIError):
                broker._sanitize(json.dumps({k: v for k, v in report.items() if k != field}))
        with self.assertRaises(AgentsAPIError):
            broker._sanitize(json.dumps(report | {"extra": False}))
        for field in report:
            for wrong in (None, True, False, 0, 1, 2.0, [], {}, "UNKNOWN"):
                with self.subTest(field=field, wrong=wrong):
                    if type(wrong) is type(report[field]) and wrong == report[field]:
                        continue
                    with self.assertRaises(AgentsAPIError):
                        broker._sanitize(json.dumps(report | {field: wrong}))
        for gate in runner.GATES:
            for wrong in (True, False, 0, 1, None, [], {}, "UNKNOWN"):
                changed = deepcopy(report)
                changed["checks"][gate] = wrong
                with self.subTest(gate=gate, wrong=wrong), self.assertRaises(AgentsAPIError):
                    broker._sanitize(json.dumps(changed))

    def test_duplicate_top_level_check_and_diagnostic_keys_rejected(self):
        raw = json.dumps(self.collected(True))
        for token in (
            '"schema_version": 2',
            '"account_project_binding": "PASS"',
            '"code": "PASS"',
            '"stage": "FINAL_VALIDATION"',
        ):
            with self.subTest(token=token), self.assertRaises(AgentsAPIError):
                broker._sanitize(raw.replace(token, token + ", " + token, 1))
