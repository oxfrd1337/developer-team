"""Closed DT-017E diagnostic vocabulary; never evidence or authorization."""

from .adapters.agents_api_contracts import AgentsAPIError

PROVIDER_GATES = ("account_project_binding", "spend_controls", "agent_configuration")
STAGES = {
    "account_project_binding": frozenset(
        {
            "NOT_ATTEMPTED",
            "IDENTITY_VALIDATION",
            "ADMIN_PROJECT",
            "ADMIN_SERVICE_ACCOUNTS",
            "ADMIN_API_KEYS",
            "FINAL_VALIDATION",
        }
    ),
    "spend_controls": frozenset(
        {"NOT_ATTEMPTED", "IDENTITY_VALIDATION", "ADMIN_SPEND_LIMIT", "FINAL_VALIDATION"}
    ),
    "agent_configuration": frozenset(
        {
            "NOT_ATTEMPTED",
            "IDENTITY_VALIDATION",
            "CANARY_MODELS",
            "CANARY_AGENT",
            "FINAL_VALIDATION",
        }
    ),
}
CODES = frozenset(
    {
        "NOT_ATTEMPTED",
        "PASS",
        "HTTP_401",
        "HTTP_403",
        "HTTP_429",
        "HTTP_5XX",
        "HTTP_OTHER",
        "REDIRECT_BLOCKED",
        "TLS_OR_PROXY_FAILURE",
        "DNS_FAILURE",
        "TRANSPORT_FAILURE",
        "TIMEOUT",
        "RESPONSE_TOO_LARGE",
        "SCHEMA_MISMATCH",
        "EXPECTED_RECORD_MISSING",
        "CONFIGURATION_MISMATCH",
        "BUDGET_MISMATCH",
        "IDENTITY_OR_HANDLE_INVALID",
        "READ_UNAVAILABLE",
    }
)
# Internal wire statuses are never provider HTTP statuses and never leave reports.
WIRE_FAILURES = {
    -1: "TIMEOUT",
    -2: "TLS_OR_PROXY_FAILURE",
    -3: "DNS_FAILURE",
    -4: "RESPONSE_TOO_LARGE",
    -5: "TRANSPORT_FAILURE",
}


class DiagnosticFailure(AgentsAPIError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in CODES else "SCHEMA_MISMATCH"
        super().__init__(self.code)


def empty_diagnostics():
    return {gate: {"stage": "NOT_ATTEMPTED", "code": "NOT_ATTEMPTED"} for gate in PROVIDER_GATES}


def sanitize_diagnostics(value):
    """Rebuild only known literals, rejecting even additional nested fields."""
    if type(value) is not dict or set(value) != set(PROVIDER_GATES):
        raise DiagnosticFailure("SCHEMA_MISMATCH")
    result = {}
    for gate in PROVIDER_GATES:
        item = value[gate]
        if (
            type(item) is not dict
            or set(item) != {"stage", "code"}
            or type(item["stage"]) is not str
            or item["stage"] not in STAGES[gate]
            or type(item["code"]) is not str
            or item["code"] not in CODES
            or (item["stage"] == "NOT_ATTEMPTED") != (item["code"] == "NOT_ATTEMPTED")
            or (item["code"] == "PASS" and item["stage"] != "FINAL_VALIDATION")
        ):
            raise DiagnosticFailure("SCHEMA_MISMATCH")
        result[gate] = {"stage": item["stage"], "code": item["code"]}
    return result
