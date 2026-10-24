"""Closed diagnostic vocabulary; never evidence or authorization."""

from .adapters.agents_api_contracts import AgentsAPIError

PROVIDER_GATES = ("account_project_binding", "spend_controls", "agent_configuration")
STAGES = {
    "account_project_binding": frozenset(
        {"NOT_ATTEMPTED", "PRECHECK", "ADMIN_PROJECT", "ADMIN_SERVICE_ACCOUNTS", "ADMIN_API_KEYS",
         "COMPLETE"}
    ),
    "spend_controls": frozenset({"NOT_ATTEMPTED", "PRECHECK", "ADMIN_SPEND_LIMIT", "COMPLETE"}),
    "agent_configuration": frozenset(
        {"NOT_ATTEMPTED", "PRECHECK", "CANARY_MODELS", "CANARY_AGENT", "COMPLETE"}
    ),
}
CODES = frozenset({
    "NOT_ATTEMPTED", "HTTP_401", "HTTP_403", "HTTP_429", "HTTP_5XX", "HTTP_REDIRECT",
    "HTTP_OTHER", "TLS_OR_PROXY_FAILURE", "DNS_FAILURE", "TIMEOUT", "TRANSPORT_FAILURE",
    "RESPONSE_TOO_LARGE", "SCHEMA_MISMATCH", "EXPECTED_RECORD_MISSING",
    "CONFIGURATION_MISMATCH", "LOCAL_VALIDATION_FAILED", "OBSERVATION_REJECTED", "PASS",
})


class DiagnosticError(AgentsAPIError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in CODES else "LOCAL_VALIDATION_FAILED"
        super().__init__(self.code)


def empty_diagnostics():
    return {gate: {"code": "NOT_ATTEMPTED", "stage": "NOT_ATTEMPTED"} for gate in PROVIDER_GATES}


def valid_diagnostics(value, checks, count):
    if (
        type(value) is not dict or set(value) != set(PROVIDER_GATES)
        or type(count) is not int or not 0 <= count <= 3
    ):
        return False
    for gate in PROVIDER_GATES:
        item = value[gate]
        if (
            type(item) is not dict or set(item) != {"code", "stage"}
            or type(item["code"]) is not str or item["code"] not in CODES
            or type(item["stage"]) is not str or item["stage"] not in STAGES[gate]
            or (item["code"] == "PASS") != (checks[gate] == "PASS")
            or (item["code"] == "NOT_ATTEMPTED") != (item["stage"] == "NOT_ATTEMPTED")
            or (item["code"] in {"PASS", "OBSERVATION_REJECTED"}) != (item["stage"] == "COMPLETE")
            or (item["stage"] == "PRECHECK" and item["code"] != "LOCAL_VALIDATION_FAILED")
        ):
            return False
    return count == sum(checks[gate] == "PASS" for gate in PROVIDER_GATES)
