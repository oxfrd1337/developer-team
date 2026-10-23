"""Review regressions: independent permission layers and pinned scope trust subjects."""

import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from unittest.mock import Mock

from developer_team.adapters.agents_api_contracts import MINIMAL_CAPABILITIES, AgentsAPIError
from developer_team.scope_evidence import (
    EXPECTED_EFFECTIVE_PERMISSIONS,
    EXPECTED_KEY_PERMISSIONS,
    EXPECTED_PRINCIPAL_PERMISSIONS,
    EffectivePermission,
    KeyPermission,
    PrincipalPermission,
    ScopeAttestorIdentity,
    ScopeVerifierIdentity,
)
from tests.agents_api_support import NOW
from tests.provider_readonly_support import Harness, ScopeSource, ScopeVerifier


class PermissionLayerTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def blocked(self, **changes):
        self.h.scope_source.evidence = replace(self.h.scope_source.evidence, **changes)
        self.assertIsNone(self.h.collector.read(self.h.bound, "credential_scope"))
        self.assertEqual(self.h.scope_verifier.calls, 0)
        self.assertEqual(self.h.calls, [])

    def test_independent_namespaces_normalize_only_after_verification(self):
        evidence = self.h.scope_source.evidence
        self.assertEqual(evidence.key_scopes, EXPECTED_KEY_PERMISSIONS)
        self.assertEqual(evidence.principal_scopes, EXPECTED_PRINCIPAL_PERMISSIONS)
        self.assertEqual(evidence.effective_scopes, EXPECTED_EFFECTIVE_PERMISSIONS)
        self.assertNotEqual(evidence.key_scopes, evidence.principal_scopes)
        self.assertNotEqual(evidence.effective_scopes, evidence.key_scopes)
        observation = self.h.collector.read(self.h.bound, "credential_scope")
        self.assertIsNotNone(observation)
        self.assertEqual(self.h.scope_verifier.calls, 1)
        for field in ("key_capabilities", "principal_capabilities", "effective_capabilities"):
            self.assertEqual(observation.facts[field], sorted(MINIMAL_CAPABILITIES))
        self.assertEqual(self.h.calls, [])

    def test_key_permissions_in_principal_namespace_block(self):
        self.blocked(principal_scopes=EXPECTED_KEY_PERMISSIONS)

    def test_principal_permissions_in_key_namespace_block(self):
        self.blocked(key_scopes=EXPECTED_PRINCIPAL_PERMISSIONS)

    def test_raw_provider_names_cannot_cross_either_namespace(self):
        for field, value in (
            ("principal_scopes", frozenset({"api.model.read"})),
            ("key_scopes", frozenset({"model.read"})),
            ("key_scopes", frozenset(p.value for p in EXPECTED_KEY_PERMISSIONS)),
        ):
            self.h = Harness()
            self.blocked(**{field: value})

    def test_mixed_namespace_sets_block_even_when_required_rights_are_present(self):
        for field, wrong in (
            ("key_scopes", PrincipalPermission.MODEL_READ),
            ("principal_scopes", KeyPermission.MODEL_READ),
            ("effective_scopes", KeyPermission.MODEL_READ),
        ):
            self.h = Harness()
            scopes = getattr(self.h.scope_source.evidence, field)
            self.blocked(**{field: scopes | {wrong}})

    def test_each_missing_permission_blocks_in_each_layer(self):
        for field in ("key_scopes", "principal_scopes", "effective_scopes"):
            for permission in getattr(self.h.scope_source.evidence, field):
                self.h = Harness()
                scopes = getattr(self.h.scope_source.evidence, field)
                self.blocked(**{field: scopes - {permission}})

    def test_additional_known_rights_block_in_each_layer(self):
        for field, extra in (
            ("key_scopes", KeyPermission.FILES_WRITE),
            ("principal_scopes", PrincipalPermission.FILES_WRITE),
            ("effective_scopes", EffectivePermission.FILES_WRITE),
        ):
            self.h = Harness()
            scopes = getattr(self.h.scope_source.evidence, field)
            self.blocked(**{field: scopes | {extra}})

    def test_unknown_rights_never_reach_external_verifier(self):
        for field in ("key_scopes", "principal_scopes", "effective_scopes"):
            for extra in ("unknown", "admin", "all", "api.files.write", 1, None):
                self.h = Harness()
                scopes = getattr(self.h.scope_source.evidence, field)
                self.blocked(**{field: scopes | {extra}})

    def test_effective_claim_cannot_restore_missing_key_or_principal_right(self):
        for field, permission in (
            ("key_scopes", KeyPermission.AGENTS_WRITE),
            ("principal_scopes", PrincipalPermission.RESPONSES_WRITE),
        ):
            self.h = Harness()
            scopes = getattr(self.h.scope_source.evidence, field)
            self.blocked(**{field: scopes - {permission}})

    def test_inconsistent_effective_rights_block_with_complete_key_and_principal(self):
        self.blocked(
            effective_scopes=EXPECTED_EFFECTIVE_PERMISSIONS - {EffectivePermission.MODEL_READ}
        )

    def test_effective_permissions_cannot_use_key_or_role_types(self):
        for scopes in (EXPECTED_KEY_PERMISSIONS, EXPECTED_PRINCIPAL_PERMISSIONS):
            self.h = Harness()
            self.blocked(effective_scopes=scopes)

    def test_mutable_sets_and_untyped_json_remain_invalid(self):
        for field in ("key_scopes", "principal_scopes", "effective_scopes"):
            self.h = Harness()
            self.blocked(**{field: set(getattr(self.h.scope_source.evidence, field))})
        self.h = Harness()
        self.h.scope_source.evidence = asdict(self.h.scope_source.evidence)
        self.assertIsNone(self.h.collector.read(self.h.bound, "credential_scope"))


class ScopeSubjectTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def scope(self):
        return self.h.collector.read(self.h.bound, "credential_scope")

    def test_independent_correct_verifier_passes_with_separate_capabilities(self):
        self.assertIsNot(self.h.scope_source, self.h.scope_verifier)
        self.assertFalse(hasattr(self.h.scope_source, "verify"))
        self.assertFalse(hasattr(self.h.scope_verifier, "read_scope"))
        self.assertIsNotNone(self.scope())
        self.assertEqual(self.h.scope_verifier.calls, 1)
        self.assertEqual(self.h.collector.report()["live"], "NO-GO")

    def test_source_is_verifier_no_go_before_read_or_verify(self):
        source = Mock(identity=self.h.scope_source.identity)
        self.h.collector._scope_source = source
        self.h.collector._scope_verifier = source
        self.assertIsNone(self.scope())
        source.read_scope.assert_not_called()
        source.verify.assert_not_called()

    def test_source_cannot_self_verify_evidence_even_with_true_callback(self):
        source = self.h.scope_source
        source.verify = Mock(return_value=True)
        self.h.collector._scope_verifier = source
        self.assertIsNone(self.scope())
        source.verify.assert_not_called()

    def test_distinct_wrapper_objects_with_same_subject_no_go(self):
        forged = replace(
            self.h.scope_verifier.identity, subject_ref=self.h.scope_source.identity.subject_ref
        )
        self.h.collector._scope_verifier = Mock(identity=forged, verify=Mock(return_value=True))
        self.h.collector._verifier_pin = forged
        self.assertIsNone(self.scope())
        self.h.collector._scope_verifier.verify.assert_not_called()

    def test_shared_trust_domain_or_public_key_is_not_independent(self):
        for field in ("trust_domain_ref", "public_key_digest"):
            self.h = Harness()
            forged = replace(
                self.h.scope_verifier.identity,
                **{field: getattr(self.h.scope_source.identity, field)},
            )
            self.h.collector._scope_verifier = Mock(identity=forged, verify=Mock(return_value=True))
            self.h.collector._verifier_pin = forged
            self.assertIsNone(self.scope())
            self.h.collector._scope_verifier.verify.assert_not_called()

    def test_identical_identity_object_is_rejected_despite_distinct_adapters(self):
        self.h.collector._scope_verifier = Mock(identity=self.h.scope_source.identity)
        self.h.collector._verifier_pin = self.h.scope_source.identity
        self.assertIsNone(self.scope())

    def test_swapped_source_and_verifier_adapters_fail_before_callbacks(self):
        self.h.collector._scope_source, self.h.collector._scope_verifier = (
            self.h.scope_verifier,
            self.h.scope_source,
        )
        self.assertIsNone(self.scope())
        self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_swapped_role_identity_pins_are_invalid(self):
        self.h.collector._attestor_pin, self.h.collector._verifier_pin = (
            self.h.collector._verifier_pin,
            self.h.collector._attestor_pin,
        )
        self.assertIsNone(self.scope())
        self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_source_or_verifier_cannot_change_pinned_identity(self):
        for target in ("scope_source", "scope_verifier"):
            self.h = Harness()
            adapter = getattr(self.h, target)
            adapter.identity = replace(adapter.identity, subject_ref="replacement")
            self.assertIsNone(self.scope())
            self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_evidence_cannot_choose_different_issuer_or_verifier_audience(self):
        for field in ("attestor_identity", "verifier_identity"):
            self.h = Harness()
            evidence = self.h.scope_source.evidence
            changed = replace(getattr(evidence, field), subject_ref="other")
            self.h.scope_source.evidence = replace(evidence, **{field: changed})
            self.assertIsNone(self.scope())
            self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_evidence_cannot_swap_issuer_and_audience(self):
        evidence = self.h.scope_source.evidence
        self.h.scope_source.evidence = replace(
            evidence,
            attestor_identity=evidence.verifier_identity,
            verifier_identity=evidence.attestor_identity,
        )
        self.assertIsNone(self.scope())
        self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_unpinned_source_and_verifier_cannot_self_register_trust(self):
        for field in ("_attestor_pin", "_verifier_pin"):
            self.h = Harness()
            setattr(self.h.collector, field, None)
            self.assertIsNone(self.scope())
            self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_trust_identities_and_evidence_are_immutable(self):
        for value, field in (
            (self.h.scope_source.identity, "subject_ref"),
            (self.h.scope_verifier.identity, "subject_ref"),
            (self.h.scope_source.evidence, "signature"),
        ):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, field, "changed")

    def test_malformed_trust_identity_fields_are_invalid(self):
        for identity_type, adapter_name, pin_name in (
            (ScopeAttestorIdentity, "scope_source", "_attestor_pin"),
            (ScopeVerifierIdentity, "scope_verifier", "_verifier_pin"),
        ):
            for changes in (
                {"subject_ref": "private@example.invalid"},
                {"trust_domain_ref": ""},
                {"public_key_digest": "g" * 64},
                {"public_key_digest": "a" * 63},
                {"public_key_digest": None},
            ):
                self.h = Harness()
                original = getattr(self.h, adapter_name).identity
                identity = identity_type(**{**asdict(original), **changes})
                getattr(self.h, adapter_name).identity = identity
                setattr(self.h.collector, pin_name, identity)
                self.assertIsNone(self.scope())
                self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_changed_source_identity_during_read_blocks_before_verify(self):
        source = self.h.scope_source
        evidence = source.evidence

        def read(*args):
            source.identity = replace(source.identity, subject_ref="changed")
            return evidence

        source.read_scope = read
        self.assertIsNone(self.scope())
        self.assertEqual(self.h.scope_verifier.calls, 0)

    def test_verifier_identity_changed_during_verification_is_rejected(self):
        verifier = self.h.scope_verifier

        def verify(evidence):
            verifier.identity = replace(verifier.identity, subject_ref="changed")
            return True

        verifier.verify = verify
        self.assertIsNone(self.scope())

    def test_verifier_cannot_swap_controller_participants_during_callback(self):
        def verify(evidence):
            self.h.collector._scope_source = ScopeSource()
            return True

        self.h.scope_verifier.verify = verify
        self.assertIsNone(self.scope())

    def test_verifier_cannot_replace_controller_pins_during_callback(self):
        def verify(evidence):
            self.h.collector._verifier_pin = replace(
                self.h.scope_verifier.identity, subject_ref="replacement"
            )
            return True

        self.h.scope_verifier.verify = verify
        self.assertIsNone(self.scope())

    def test_direct_validation_cannot_bypass_subject_separation(self):
        evidence = self.h.scope_source.evidence
        with self.assertRaises(AgentsAPIError):
            evidence.validate(
                self.h.bound,
                self.h.identity,
                NOW,
                self.h.scope_source,
                self.h.scope_source,
                self.h.scope_source.identity,
                self.h.scope_verifier.identity,
            )

    def test_fresh_separate_correct_adapters_with_same_pins_are_supported(self):
        self.h.collector._scope_source = ScopeSource()
        self.h.collector._scope_verifier = ScopeVerifier()
        self.assertIsNotNone(self.scope())
