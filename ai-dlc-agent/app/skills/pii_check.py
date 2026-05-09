"""PII detection for user-supplied CLI inputs using LLM Guard's Anonymize scanner.

Uses the protectai/llm-guard ``Anonymize`` input scanner backed by Presidio Analyzer
and a BERT NER model to detect PII entities before they reach the agent.

The scanner is initialised lazily on first call so the NER model is only downloaded
when PII checking is actually performed (not on import or --dry-run).

If ``llm-guard`` is not installed the check degrades gracefully: a warning is printed
and the input is allowed through unchanged.

Detected entity types (subset of Presidio defaults):
    PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN,
    IP_ADDRESS, URL, IBAN_CODE, CRYPTO, UUID
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity types we care about for CLI input validation.
# URL is excluded — user stories legitimately reference URLs (e.g. API endpoints).
# ---------------------------------------------------------------------------
_ENTITY_TYPES: list[str] = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "IP_ADDRESS",
    "IBAN_CODE",
    "CRYPTO",
    "UUID",
]

# Module-level cache so the scanner is only built once per process.
_scanner_cache: object | None = None
_vault_cache: object | None = None


def _get_scanner() -> tuple[object, object] | None:
    """
    Lazily initialise and cache the LLM Guard Anonymize scanner.

    Returns:
        (scanner, vault) tuple, or None if llm-guard is not installed.
    """
    global _scanner_cache, _vault_cache

    if _scanner_cache is not None:
        return _scanner_cache, _vault_cache

    try:
        from llm_guard.input_scanners import Anonymize  # type: ignore[import]
        from llm_guard.vault import Vault  # type: ignore[import]
    except ImportError:
        logger.warning(
            "llm-guard is not installed — PII checking is disabled. "
            "Install it with: pip install llm-guard"
        )
        return None

    vault = Vault()
    scanner = Anonymize(
        vault,
        entity_types=_ENTITY_TYPES,
        language="en",
        # threshold=0 means flag any detection, however low-confidence.
        # Raise this (e.g. 0.5) to reduce false positives at the cost of recall.
        threshold=0,
    )
    _scanner_cache = scanner
    _vault_cache = vault
    return scanner, vault


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class PIICheckResult:
    """Result of a PII scan on a single input field."""

    field: str
    """Name of the input field that was scanned (e.g. 'story')."""

    original: str
    """The original, unmodified input text."""

    sanitized: str
    """The text with PII entities replaced by placeholders (e.g. [REDACTED_PERSON_1])."""

    is_valid: bool
    """True if no PII was detected above the threshold."""

    risk_score: float
    """Highest risk score across all detected entities (0.0–1.0)."""

    detected_entities: list[str] = field(default_factory=list)
    """List of entity type labels that were detected (e.g. ['PERSON', 'EMAIL_ADDRESS'])."""


def check_input(text: str, field: str = "input") -> PIICheckResult:
    """
    Scan ``text`` for PII using LLM Guard's Anonymize scanner.

    Args:
        text:  The raw user-supplied string to scan.
        field: Human-readable label for the field (used in error messages).

    Returns:
        :class:`PIICheckResult` describing what was found (if anything).
        If llm-guard is not installed, returns a passing result with a warning.

    Example::

        result = check_input(args.story, field="story")
        if not result.is_valid:
            raise PIIDetectedError(result.field, result.detected_entities)
    """
    pair = _get_scanner()
    if pair is None:
        # llm-guard not installed — pass through with a warning.
        return PIICheckResult(
            field=field,
            original=text,
            sanitized=text,
            is_valid=True,
            risk_score=0.0,
            detected_entities=[],
        )

    scanner, _vault = pair

    try:
        sanitized, is_valid, risk_score = scanner.scan(text)
    except Exception as exc:  # noqa: BLE001
        # Scanner errors (e.g. model download failure) should not block the workflow.
        logger.warning("PII scanner error for field '%s': %s — allowing input through", field, exc)
        return PIICheckResult(
            field=field,
            original=text,
            sanitized=text,
            is_valid=True,
            risk_score=0.0,
            detected_entities=[],
        )

    # Derive which entity types were actually redacted by comparing original vs sanitized.
    detected: list[str] = []
    if not is_valid:
        # LLM Guard replaces entities with [REDACTED_<TYPE>_N] placeholders.
        # Parse the sanitized text to extract the type labels.
        import re
        detected = list(dict.fromkeys(
            m.group(1)
            for m in re.finditer(r"\[REDACTED_([A-Z_]+)_\d+\]", sanitized)
        ))
        if not detected:
            # Fallback: scanner flagged it but no placeholders found — report generic.
            detected = ["PII"]

    return PIICheckResult(
        field=field,
        original=text,
        sanitized=sanitized,
        is_valid=is_valid,
        risk_score=float(risk_score) if isinstance(risk_score, (int, float)) else 0.0,
        detected_entities=detected,
    )


def check_inputs(**fields: str) -> list[PIICheckResult]:
    """
    Scan multiple named input fields and return all results.

    Args:
        **fields: Keyword arguments mapping field name → text to scan.
                  Example: ``check_inputs(story=args.story, repo=args.repo)``

    Returns:
        List of :class:`PIICheckResult`, one per field, in the order provided.

    Example::

        results = check_inputs(story=args.story, repo=args.repo)
        violations = [r for r in results if not r.is_valid]
        if violations:
            for v in violations:
                raise PIIDetectedError(v.field, v.detected_entities)
    """
    return [check_input(text, field=name) for name, text in fields.items()]
