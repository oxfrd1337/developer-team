"""PR #32 blockers: technical sandbox policy, saved-agent drift and cost approvals.

All apparent provider mutations are credential-free wire fixtures.
"""

import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from developer_team.adapters.agents_api import AgentsAPIAdapter
from developer_team.adapters.agents_api_contracts import (
    CANARY_INSTRUCTIONS,
    CANARY_MESSAGE,
    AgentsAPIError,
    CanaryBinding,
    sha256,
)
from tests.agents_api_support import (
    ENVIRONMENT,
    NOW,
    FixtureGate,
    Harness,
    binding,
    permit,
)

MESSAGE = "agent.session.input.message"


class ReviewHarnessTests(unittest.TestCase):
    def harness(self, **kwargs):
        harness = Harness(**kwargs)
        self.addCleanup(harness.connection.close)
        return harness

    def assert_create_blocks(self, harness, reason):
        with self.assertRaisesRegex(AgentsAPIError, reason):
            harness.adapter.create_session()
        self.assertEqual(harness.state().phase, "SESSION_UNCERTAIN")
        self.assertIsNone(harness.state().session_id)
        self.assertIsNone(harness.state().environment_id)
        self.assertEqual(harness.transport.posts(MESSAGE), [])
        with self.assertRaises(AgentsAPIError):
            harness.restart().create_session()
        self.assertEqual(len(harness.transport.posts("create")), 1)


class HostedEnvironmentReviewTests(ReviewHarnessTests):
    def test_request_explicitly_disables_network_and_selects_small_new_container(self):
        h = self.harness()
        h.adapter.create_session()
        environment = json.loads(h.transport.posts("create")[0].body)["environment"]
        self.assertEqual(environment["type"], "openai_hosted")
        self.assertEqual(environment["network"], {"access": "disabled", "allowed_domains": []})
        self.assertEqual(environment["container_size"], "small")
        self.assertEqual(environment["desktop"], {"enabled": False})
        self.assertEqual(environment["packages"], {"npm": [], "python": [], "system": []})
        self.assertEqual(environment["env"], {})
        for field in ("skills", "plugins", "files", "capability_directories"):
            self.assertEqual(environment[field], [])
        self.assertNotIn("environment_id", environment)
        self.assertNotIn("environment_template_id", environment)
        self.assertEqual(h.state().environment_id, ENVIRONMENT)

    def test_enabled_restricted_or_unknown_network_is_rejected_despite_safe_prompt(self):
        for access in ("enabled", "restricted", "DISABLED", True, None, {}, []):
            with self.subTest(access=access):
                h = self.harness()
                h.transport.session["environment"]["network"]["access"] = access
                self.assertEqual(h.transport.session["agent"]["instructions"], CANARY_INSTRUCTIONS)
                self.assert_create_blocks(h, "effective_environment_mismatch")

    def test_missing_or_null_network_configuration_is_not_assumed_safe(self):
        for network in (None, {}, [], {"allowed_domains": []}, {"access": "disabled"}):
            h = self.harness()
            h.transport.session["environment"]["network"] = network
            self.assert_create_blocks(h, "effective_environment_mismatch")
        h = self.harness()
        del h.transport.session["environment"]["network"]
        self.assert_create_blocks(h, "effective_environment_mismatch")

    def test_domain_exceptions_or_unexpected_network_policy_fields_are_rejected(self):
        for network in (
            {"access": "disabled", "allowed_domains": ["example.com"]},
            {"access": "disabled", "allowed_domains": None},
            {"access": "disabled", "allowed_domains": [], "proxy": "enabled"},
        ):
            h = self.harness()
            h.transport.session["environment"]["network"] = network
            self.assert_create_blocks(h, "effective_environment_mismatch")

    def test_missing_unknown_or_larger_container_size_is_rejected(self):
        for size in (None, "medium", "large", "custom", True, {}, []):
            h = self.harness()
            h.transport.session["environment"]["container_size"] = size
            self.assert_create_blocks(h, "effective_environment_mismatch")
        h = self.harness()
        del h.transport.session["environment"]["container_size"]
        self.assert_create_blocks(h, "effective_environment_mismatch")

    def test_desktop_extra_packages_capabilities_and_unexpected_container_fields_block(self):
        for field, value in (
            ("desktop", {"enabled": True}),
            ("desktop", {"enabled": 0}),
            ("packages", {"npm": [], "python": ["unexpected"], "system": []}),
            ("skills", [{"name": "unexpected"}]),
            ("plugins", [{"name": "unexpected"}]),
            ("files", [{"path": "/workspace/private"}]),
            ("capability_directories", ["/workspace/capabilities"]),
            ("container_memory", "unbounded"),
            ("environment_template_id", "template_unexpected"),
        ):
            with self.subTest(field=field):
                h = self.harness()
                h.transport.session["environment"][field] = value
                self.assert_create_blocks(h, "effective_environment_mismatch")

    def test_environment_drift_before_first_message_blocks_its_post(self):
        for field, value in (
            ("network", {"access": "enabled", "allowed_domains": []}),
            ("container_size", "large"),
            ("id", "env_replaced"),
        ):
            h = self.harness()
            h.adapter.create_session()
            h.transport.session["environment"][field] = value
            with self.assertRaisesRegex(AgentsAPIError, "effective_environment_mismatch"):
                h.adapter.submit_canary()
            self.assertEqual(h.state().message_attempts, 0)
            self.assertEqual(h.state().environment_id, ENVIRONMENT)
            self.assertEqual(h.transport.posts(MESSAGE), [])

    def test_unknown_creation_reconciliation_cannot_bind_unsafe_environment(self):
        h = self.harness()
        h.transport.faults["create"].append(TimeoutError())
        with self.assertRaises(AgentsAPIError):
            h.adapter.create_session()
        h.transport.session["environment"]["network"]["access"] = "enabled"
        with self.assertRaisesRegex(AgentsAPIError, "effective_environment_mismatch"):
            h.restart().reconcile()
        self.assertIsNone(h.state().session_id)
        self.assertIsNone(h.state().environment_id)
        self.assertEqual(len(h.transport.posts("create")), 1)
        self.assertTrue(all(request.method == "GET" for request in h.transport.calls[1:]))

    def test_bound_environment_identity_is_rechecked_during_terminal_reconciliation(self):
        h = self.harness()
        h.active()
        h.transport.turn_status = "completed"
        h.transport.session["environment"]["id"] = "env_other"
        with self.assertRaisesRegex(AgentsAPIError, "effective_environment_mismatch"):
            h.restart().reconcile()
        self.assertIsNone(h.state().terminal_kind)


class SavedAgentReviewTests(ReviewHarnessTests):
    def test_request_overrides_all_execution_and_cost_relevant_saved_agent_fields(self):
        h = self.harness()
        h.adapter.create_session()
        agent = json.loads(h.transport.posts("create")[0].body)["agent"]
        self.assertEqual(
            set(agent),
            {"model", "instructions", "tools", "multi_agent", "reasoning", "service_tier", "text"},
        )
        self.assertEqual(agent["model"], "synthetic-canary-model-v1")
        self.assertEqual(agent["reasoning"], {"effort": "low", "summary": None})
        self.assertEqual(agent["service_tier"], "default")
        self.assertEqual(agent["text"], {"format": {"type": "text"}, "verbosity": "low"})
        self.assertEqual(agent["tools"], [])
        self.assertEqual(agent["multi_agent"], {"enabled": False})

    def test_changed_saved_agent_after_verification_is_overridden_before_creation(self):
        h = self.harness()
        saved = {
            "model": "synthetic-expensive-model",
            "reasoning": {"effort": "max", "summary": "auto"},
            "service_tier": "priority",
            "text": {"format": {"type": "text"}, "verbosity": "high"},
            "tools": [{"type": "web_search"}],
            "multi_agent": {"enabled": True},
            "instructions": "changed after account verification",
        }
        original_exchange = h.transport.exchange

        def resolve_saved_agent(request):
            if request.method == "POST" and request.url.endswith("/sessions"):
                overrides = json.loads(request.body)["agent"]
                h.transport.session["agent"] = {
                    **saved,
                    **overrides,
                    "id": h.binding.agent_id,
                    "multi_agent": {"enabled": False, "max_concurrent_subagents": None},
                }
            return original_exchange(request)

        with patch.object(h.transport, "exchange", side_effect=resolve_saved_agent):
            self.assertEqual(h.adapter.create_session()["phase"], "SESSION_READY")
        self.assertEqual(h.transport.session["agent"]["model"], h.binding.model)
        self.assertEqual(h.transport.session["agent"]["service_tier"], "default")

    def test_provider_cannot_ignore_pins_even_with_matching_session_metadata(self):
        for field, value in (
            ("model", "synthetic-expensive-model"),
            ("reasoning", {"effort": "max", "summary": None}),
            ("reasoning", {"effort": "low", "summary": "detailed"}),
            ("service_tier", "priority"),
            ("service_tier", "auto"),
            ("text", {"format": {"type": "text"}, "verbosity": "high"}),
        ):
            with self.subTest(field=field, value=value):
                h = self.harness()
                h.transport.session["agent"][field] = value
                self.assertEqual(
                    h.transport.session["metadata"], {"dt016_binding": h.binding.digest}
                )
                self.assert_create_blocks(h, "effective_agent_mismatch")

    def test_missing_cost_fields_and_nested_defaults_are_rejected(self):
        for field in ("model", "reasoning", "service_tier", "text"):
            h = self.harness()
            del h.transport.session["agent"][field]
            self.assert_create_blocks(h, "effective_agent_mismatch")
        for field, value in (
            ("reasoning", None),
            ("reasoning", {"effort": "low"}),
            ("reasoning", {"effort": None, "summary": None}),
            ("service_tier", None),
            ("text", {"format": {"type": "text"}}),
            ("multi_agent", {"enabled": False}),
            ("multi_agent", {"enabled": 0, "max_concurrent_subagents": None}),
        ):
            h = self.harness()
            h.transport.session["agent"][field] = value
            self.assert_create_blocks(h, "effective_agent_mismatch")

    def test_unknown_execution_fields_or_structured_output_constraints_are_rejected(self):
        for field, value in (
            ("temperature", 0.5),
            ("reasoning", {"effort": "low", "summary": None, "budget": "unlimited"}),
            ("text", {"format": {"type": "json_schema", "schema": {}}, "verbosity": "low"}),
        ):
            h = self.harness()
            h.transport.session["agent"][field] = value
            self.assert_create_blocks(h, "effective_agent_mismatch")

    def test_agent_drift_after_creation_blocks_first_message(self):
        for field, value in (
            ("model", "synthetic-other-model"),
            ("service_tier", "fast"),
            ("reasoning", {"effort": "high", "summary": None}),
        ):
            h = self.harness()
            h.adapter.create_session()
            h.transport.session["agent"][field] = value
            with self.assertRaisesRegex(AgentsAPIError, "effective_agent_mismatch"):
                h.restart().submit_canary()
            self.assertEqual(h.transport.posts(MESSAGE), [])

    def test_model_change_invalidates_permit_grant_and_existing_journal_binding(self):
        h = self.harness()
        changed = binding(model="synthetic-canary-model-v2")
        self.assertNotEqual(changed.digest, h.binding.digest)
        old_permit = permit()
        with self.assertRaisesRegex(AgentsAPIError, "binding_mismatch"):
            old_permit.validate(changed, "create_session", NOW)
        with self.assertRaisesRegex(AgentsAPIError, "binding_mismatch"):
            h.journal.load(changed)
        adapter = AgentsAPIAdapter(
            changed,
            h.journal,
            transport=h.transport,
            gate=FixtureGate(permit(changed)),
            now=lambda: NOW,
        )
        with self.assertRaisesRegex(AgentsAPIError, "journal"):
            adapter.create_session()
        self.assertEqual(h.transport.calls, [])

    def test_model_is_required_and_invalid_or_secret_like_model_is_rejected_without_echo(self):
        data = asdict(binding())
        del data["model"]
        with self.assertRaises(TypeError):
            CanaryBinding(**data)
        for model in (None, True, "", "free prompt model", "x" * 97, "sk-sensitive-model"):
            h = self.harness()
            with self.assertRaisesRegex(AgentsAPIError, "bound_model") as caught:
                AgentsAPIAdapter(binding(model=model), h.journal)
            self.assertNotIn("sk-sensitive-model", str(caught.exception))
            self.assertEqual(h.transport.calls, [])

    def test_old_configuration_digest_cannot_reuse_approval_or_journal(self):
        h = self.harness()
        previous = asdict(h.binding)
        del previous["model"]
        previous_digest = sha256(
            {**previous, "message": CANARY_MESSAGE, "instructions": CANARY_INSTRUCTIONS}
        )
        self.assertNotEqual(previous_digest, h.binding.digest)
        h.gate.value = permit(binding_digest=previous_digest, grant_binding_digest=previous_digest)
        with self.assertRaisesRegex(AgentsAPIError, "binding_mismatch"):
            h.adapter.create_session()
        self.assertEqual(h.transport.calls, [])

    def test_old_journal_without_environment_binding_is_not_implicitly_migrated(self):
        h = self.harness()
        state = asdict(h.state())
        del state["environment_id"]
        h.connection.execute("UPDATE dt016_canary SET state = ?", (json.dumps(state),))
        h.connection.commit()
        with self.assertRaisesRegex(AgentsAPIError, "journal"):
            h.restart().create_session()
        self.assertEqual(h.transport.calls, [])


class FreshCreationApprovalReviewTests(ReviewHarnessTests):
    def assert_approval_blocks(self, operation="create_session", **changes):
        h = self.harness()
        if operation == "submit_canary":
            h.adapter.create_session()
        h.gate.value = permit(**changes)
        before = len(h.transport.calls)
        with self.assertRaisesRegex(AgentsAPIError, "fresh_first_.*_approval_required"):
            getattr(h.adapter, operation)()
        self.assertEqual(len(h.transport.calls), before)
        self.assertEqual(h.transport.posts(MESSAGE), [])
        if operation == "create_session":
            self.assertEqual(h.state().phase, "PREPARED")
            self.assertEqual(h.state().session_attempts, 0)

    def test_missing_create_approval_blocks_despite_valid_grant_and_submit_approval(self):
        self.assert_approval_blocks(create_approved_at=None)

    def test_old_future_or_wrong_type_create_approval_blocks_before_any_provider_call(self):
        for approval in (NOW - 61, NOW + 1, True, False, "now", float(NOW)):
            with self.subTest(approval=approval):
                self.assert_approval_blocks(create_approved_at=approval)

    def test_missing_or_wrong_create_approval_binding_blocks(self):
        for digest in (
            None,
            "b" * 64,
            True,
            binding(intent_id="intent_other").digest,
            binding(model="synthetic-other-model").digest,
        ):
            self.assert_approval_blocks(create_approval_binding_digest=digest)

    def test_fresh_create_approval_does_not_replace_separate_submit_approval(self):
        self.assert_approval_blocks("submit_canary", submit_approved_at=None)

    def test_missing_or_wrong_submit_approval_binding_blocks_first_message(self):
        for digest in (None, "b" * 64, binding(idempotency_key="key_other").digest):
            self.assert_approval_blocks("submit_canary", submit_approval_binding_digest=digest)

    def test_approval_cannot_predate_its_operator_grant(self):
        self.assert_approval_blocks(create_approved_at=NOW - 1)
        self.assert_approval_blocks("submit_canary", submit_approved_at=NOW - 1)

    def test_exact_freshness_boundary_is_accepted_for_both_distinct_mutations(self):
        h = self.harness()
        h.gate.value = permit(
            grant_issued_at=NOW - 120, create_approved_at=NOW - 60, submit_approved_at=NOW - 60
        )
        h.adapter.create_session()
        h.adapter.submit_canary()
        self.assertEqual(len(h.transport.posts("create")), 1)
        self.assertEqual(len(h.transport.posts(MESSAGE)), 1)

    def test_create_approval_expiry_during_journal_work_blocks_final_post(self):
        h = self.harness()
        clock = [NOW]
        adapter = h.restart(now=lambda: clock[0])
        original_load = h.journal.load

        def delayed_load(bound):
            state = original_load(bound)
            clock[0] = NOW + 61
            return state

        with patch.object(h.journal, "load", side_effect=delayed_load):
            with self.assertRaisesRegex(AgentsAPIError, "fresh_first_create_approval"):
                adapter.create_session()
        self.assertEqual(h.transport.calls, [])
        self.assertEqual(h.state().phase, "SESSION_UNCERTAIN")

    def test_create_approval_revocation_after_write_ahead_blocks_final_post(self):
        h = self.harness()
        original_replace = h.journal.replace

        def revoke(bound, revision, state):
            original_replace(bound, revision, state)
            if state.request_count == 1:
                h.gate.value = permit(create_approved_at=None)

        with patch.object(h.journal, "replace", side_effect=revoke):
            with self.assertRaisesRegex(AgentsAPIError, "fresh_first_create_approval"):
                h.adapter.create_session()
        self.assertEqual(h.transport.calls, [])
        self.assertEqual(h.state().phase, "SESSION_UNCERTAIN")

    def test_submit_approval_expiry_after_write_ahead_blocks_final_post(self):
        h = self.harness()
        h.adapter.create_session()
        clock = [NOW]
        adapter = h.restart(now=lambda: clock[0])
        original_replace = h.journal.replace

        def delay(bound, revision, state):
            original_replace(bound, revision, state)
            if state.phase == "MESSAGE_UNCERTAIN":
                clock[0] = NOW + 61

        with patch.object(h.journal, "replace", side_effect=delay):
            with self.assertRaisesRegex(AgentsAPIError, "fresh_first_submit_approval"):
                adapter.submit_canary()
        self.assertEqual(h.transport.posts(MESSAGE), [])
        self.assertEqual(h.state().phase, "MESSAGE_UNCERTAIN")

    def test_slow_external_gate_cannot_validate_freshness_against_its_start_time(self):
        h = self.harness()
        clock = [NOW]
        adapter = h.restart(now=lambda: clock[0])

        def delayed_authorize(bound, operation, now):
            clock[0] = NOW + 61
            return permit()

        with patch.object(h.gate, "authorize", side_effect=delayed_authorize):
            with self.assertRaisesRegex(AgentsAPIError, "fresh_first_create_approval"):
                adapter.create_session()
        self.assertEqual(h.transport.calls, [])
        self.assertEqual(h.state().phase, "PREPARED")

    def test_every_post_rechecks_its_operation_in_external_gate(self):
        h = self.harness()
        observed = []

        def inspect(operation, request):
            if request.method == "POST":
                observed.append((operation, h.gate.calls[-1][1]))

        h.transport.before_response = inspect
        h.active().cancel()
        self.assertEqual(
            observed,
            [("create", "create_session"), ("message", "submit_canary"), ("cancel", "cancel")],
        )

    def test_missing_old_future_or_wrong_type_cancel_approval_blocks_before_any_call(self):
        for approval in (None, NOW - 61, NOW + 1, True, "now"):
            h = self.harness()
            h.active()
            h.gate.value = permit(cancel_approved_at=approval)
            before = len(h.transport.calls)
            with self.assertRaisesRegex(AgentsAPIError, "fresh_cancel_approval"):
                h.adapter.cancel()
            self.assertEqual(len(h.transport.calls), before)
            self.assertEqual(h.transport.posts("agent.session.input.cancel"), [])

    def test_missing_or_wrong_cancel_approval_binding_blocks(self):
        for digest in (None, "b" * 64, binding(intent_id="intent_other").digest):
            h = self.harness()
            h.active()
            h.gate.value = permit(cancel_approval_binding_digest=digest)
            with self.assertRaisesRegex(AgentsAPIError, "fresh_cancel_approval"):
                h.adapter.cancel()
            self.assertEqual(h.transport.posts("agent.session.input.cancel"), [])

    def test_cancel_approval_expiry_after_write_ahead_blocks_final_post(self):
        h = self.harness()
        h.active()
        clock = [NOW]
        adapter = h.restart(now=lambda: clock[0])
        original_replace = h.journal.replace

        def delay(bound, revision, state):
            original_replace(bound, revision, state)
            if state.phase == "CANCEL_UNCERTAIN":
                clock[0] = NOW + 61

        with patch.object(h.journal, "replace", side_effect=delay):
            with self.assertRaisesRegex(AgentsAPIError, "fresh_cancel_approval"):
                adapter.cancel()
        self.assertEqual(h.transport.posts("agent.session.input.cancel"), [])
        self.assertEqual(h.state().phase, "CANCEL_UNCERTAIN")

    def test_stop_and_read_remain_available_without_expired_start_approvals(self):
        h = self.harness()
        h.active()
        h.gate.value = permit(
            create_approved_at=None, submit_approved_at=None, grant_expires_at=NOW
        )
        self.assertEqual(h.adapter.reconcile()["phase"], "TURN_BOUND")
        self.assertEqual(h.adapter.cancel()["phase"], "CANCEL_REQUESTED")
        self.assertEqual(len(h.transport.posts(MESSAGE)), 1)
