"""The guardrail plane.

Untrusted text in, safe structured text out. Model output in, a verdict out.

Nothing here is the security control on its own - the tool gateway's scopes and
the policy engine's re-check are. These detectors catch attempts, record them, and
route to a human, which is a different and more honest job.
"""

from backstop_guardrails.events import (
    Action,
    Detector,
    GuardrailEvent,
    GuardrailVerdict,
    Severity,
)
from backstop_guardrails.injection import InjectionReport, canary_leaked, new_canary, scan
from backstop_guardrails.normalise import normalise
from backstop_guardrails.pii import (
    PIIKind,
    Vault,
    is_valid_card,
    is_valid_iban,
    is_valid_tckn,
    tokenise,
    turkish_name_gazetteer,
)
from backstop_guardrails.pipeline import (
    InputGuardrail,
    OutputCandidate,
    OutputGuardrail,
    PolicyCheck,
    SanitisedInput,
)
from backstop_guardrails.spotlight import Provenance, Spotlight

__all__ = [
    "Action",
    "Detector",
    "GuardrailEvent",
    "GuardrailVerdict",
    "InjectionReport",
    "InputGuardrail",
    "OutputCandidate",
    "OutputGuardrail",
    "PIIKind",
    "PolicyCheck",
    "Provenance",
    "SanitisedInput",
    "Severity",
    "Spotlight",
    "Vault",
    "canary_leaked",
    "is_valid_card",
    "is_valid_iban",
    "is_valid_tckn",
    "new_canary",
    "normalise",
    "scan",
    "tokenise",
    "turkish_name_gazetteer",
]
