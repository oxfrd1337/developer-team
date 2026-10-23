"""Non-secret identity of an externally provisioned, immutable credential handle."""

from dataclasses import asdict, dataclass

from .agents_api_contracts import AgentsAPIError, CanaryBinding, bounded_int, safe_ref, sha256


@dataclass(frozen=True, slots=True, repr=False)
class CredentialIdentity:
    project_id: str
    credential_ref: str
    service_account_ref: str
    handle_ref: str
    binding_digest: str
    issued_at: int
    expires_at: int

    def validate(self, binding: CanaryBinding, now: int) -> None:
        if (
            self.project_id != binding.project_id
            or type(self.binding_digest) is not str
            or self.binding_digest != binding.digest
            or not all(safe_ref(v) for v in (
                self.project_id, self.credential_ref, self.service_account_ref, self.handle_ref
            ))
            or not bounded_int(self.issued_at, max(0, now - 300), now)
            or not bounded_int(self.expires_at, now + 1, self.issued_at + 300)
        ):
            raise AgentsAPIError("credential_identity_missing_or_invalid")

    @property
    def digest(self) -> str:
        return sha256(asdict(self))


def require_identity(value: object, binding: CanaryBinding, now: int) -> CredentialIdentity:
    # No dict loader, extra fields, subclasses, raw secret fingerprints or secret echo.
    if type(value) is not CredentialIdentity:
        raise AgentsAPIError("credential_identity_missing_or_invalid")
    value.validate(binding, now)
    return value
