"""Typed permission layers and independently pinned scope-attestation subjects.

KeyPermission contains documented API-key names. PrincipalPermission and
EffectivePermission are local semantic types, NOT invented provider RBAC strings.
A controlled account source must attest the complete principal/role union using
its documented role namespace (e.g. model.read), never by stripping api. prefixes.
"""

from dataclasses import dataclass
from enum import Enum, auto

from .adapters.agents_api_contracts import (
    MINIMAL_CAPABILITIES,
    AgentsAPIError,
    bounded_int,
    safe_ref,
)
from .adapters.agents_credentials import CredentialIdentity, require_identity


class KeyPermission(Enum):
    AGENTS_READ = "api.agents.read"
    AGENTS_WRITE = "api.agents.write"
    RESPONSES_WRITE = "api.responses.write"
    MODEL_READ = "api.model.read"
    FILES_WRITE = "api.files.write"


class PrincipalPermission(Enum):
    AGENTS_READ = auto()
    AGENTS_WRITE = auto()
    RESPONSES_WRITE = auto()
    MODEL_READ = auto()
    FILES_WRITE = auto()


class EffectivePermission(Enum):
    AGENTS_READ = auto()
    AGENTS_WRITE = auto()
    RESPONSES_WRITE = auto()
    MODEL_READ = auto()
    FILES_WRITE = auto()


EXPECTED_KEY_PERMISSIONS = frozenset({
    KeyPermission.AGENTS_READ, KeyPermission.AGENTS_WRITE,
    KeyPermission.RESPONSES_WRITE, KeyPermission.MODEL_READ,
})
EXPECTED_PRINCIPAL_PERMISSIONS = frozenset({
    PrincipalPermission.AGENTS_READ, PrincipalPermission.AGENTS_WRITE,
    PrincipalPermission.RESPONSES_WRITE, PrincipalPermission.MODEL_READ,
})
EXPECTED_EFFECTIVE_PERMISSIONS = frozenset({
    EffectivePermission.AGENTS_READ, EffectivePermission.AGENTS_WRITE,
    EffectivePermission.RESPONSES_WRITE, EffectivePermission.MODEL_READ,
})

# Explicit independent mappings; no string equality or namespace rewriting.
_PERMISSION_RULES = (
    (KeyPermission.AGENTS_READ, PrincipalPermission.AGENTS_READ, EffectivePermission.AGENTS_READ),
    (
        KeyPermission.AGENTS_WRITE,
        PrincipalPermission.AGENTS_WRITE,
        EffectivePermission.AGENTS_WRITE,
    ),
    (KeyPermission.RESPONSES_WRITE, PrincipalPermission.RESPONSES_WRITE,
     EffectivePermission.RESPONSES_WRITE),
    (KeyPermission.MODEL_READ, PrincipalPermission.MODEL_READ, EffectivePermission.MODEL_READ),
)


def _require(condition):
    if not condition:
        raise AgentsAPIError("scope_evidence_missing_or_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class ScopeAttestorIdentity:
    subject_ref: str
    trust_domain_ref: str
    public_key_digest: str


@dataclass(frozen=True, slots=True, repr=False)
class ScopeVerifierIdentity:
    subject_ref: str
    trust_domain_ref: str
    public_key_digest: str


def _validate_trust_identity(identity, identity_type):
    _require(type(identity) is identity_type)
    _require(safe_ref(identity.subject_ref) and safe_ref(identity.trust_domain_ref))
    digest = identity.public_key_digest
    _require(type(digest) is str and len(digest) == 64 and set(digest) <= set("0123456789abcdef"))


def validate_scope_subjects(source, verifier, attestor_identity, verifier_identity):
    """Pins come from trusted controller provisioning, never from the evidence.

    Distinct Python objects alone do not establish independence: subjects, trust
    domains and public trust-key digests must also differ. Immutable role-specific
    identities are checked at each call, before AND after external callbacks.
    """
    _require(source is not None and verifier is not None and source is not verifier)
    _validate_trust_identity(attestor_identity, ScopeAttestorIdentity)
    _validate_trust_identity(verifier_identity, ScopeVerifierIdentity)
    _require(attestor_identity.subject_ref != verifier_identity.subject_ref)
    _require(attestor_identity.trust_domain_ref != verifier_identity.trust_domain_ref)
    _require(attestor_identity.public_key_digest != verifier_identity.public_key_digest)
    _require(
        type(source.identity) is ScopeAttestorIdentity and source.identity == attestor_identity
    )
    _require(
        type(verifier.identity) is ScopeVerifierIdentity and verifier.identity == verifier_identity
    )


def _permissions(value, permission_type, expected):
    _require(type(value) is frozenset)
    _require(all(type(permission) is permission_type for permission in value))
    _require(value == expected)


def _local_capabilities(effective):
    # Only a complete separately validated semantic set has this normalization.
    _require(effective == EXPECTED_EFFECTIVE_PERMISSIONS)
    return sorted(MINIMAL_CAPABILITIES)


@dataclass(frozen=True, slots=True, repr=False)
class ScopeEvidence:
    """Authenticated complete key permissions, principal union and effective rights.

    The signature must cover every field, including issuer AND verifier audience.
    No self-attested boolean, raw provider string union or JSON loader is accepted.
    The independently provisioned verifier authenticates the source and full data.
    """

    identity: CredentialIdentity
    observed_at: int
    expires_at: int
    key_scopes: frozenset[KeyPermission]
    principal_scopes: frozenset[PrincipalPermission]
    effective_scopes: frozenset[EffectivePermission]
    attestor_identity: ScopeAttestorIdentity
    verifier_identity: ScopeVerifierIdentity
    signature: bytes

    def validate(self, binding, identity, now, source, verifier, attestor_pin, verifier_pin):
        validate_scope_subjects(source, verifier, attestor_pin, verifier_pin)
        require_identity(identity, binding, now)
        _require(type(self.identity) is CredentialIdentity and self.identity == identity)
        _require(bounded_int(self.observed_at, max(0, now - 300), now))
        _require(bounded_int(self.expires_at, now + 1, self.observed_at + 300))
        _require(type(self.attestor_identity) is ScopeAttestorIdentity)
        _require(type(self.verifier_identity) is ScopeVerifierIdentity)
        _require(self.attestor_identity == attestor_pin and self.verifier_identity == verifier_pin)
        _require(type(self.signature) is bytes and 1 <= len(self.signature) <= 4096)
        _permissions(self.key_scopes, KeyPermission, EXPECTED_KEY_PERMISSIONS)
        _permissions(self.principal_scopes, PrincipalPermission, EXPECTED_PRINCIPAL_PERMISSIONS)
        _permissions(self.effective_scopes, EffectivePermission, EXPECTED_EFFECTIVE_PERMISSIONS)
        key_rights = frozenset(e for k, _, e in _PERMISSION_RULES if k in self.key_scopes)
        principal_rights = frozenset(
            e for _, p, e in _PERMISSION_RULES if p in self.principal_scopes
        )
        _require(self.effective_scopes == key_rights & principal_rights)
        verified = False
        try:
            verified = verifier.verify(self) is True
        except Exception:
            verified = False
        _require(verified)
        validate_scope_subjects(source, verifier, attestor_pin, verifier_pin)
        # Normalize only AFTER every permission layer and independent verification.
        return {
            "credential_identity_digest": identity.digest,
            "key_capabilities": _local_capabilities(key_rights),
            "principal_capabilities": _local_capabilities(principal_rights),
            "effective_capabilities": _local_capabilities(self.effective_scopes),
            "additional_permissions": [],
        }
