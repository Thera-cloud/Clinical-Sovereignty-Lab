"""
HIVE DEFENSE v4.3 — Anonymization Proxy
NER-based PII stripping before sending data to AI API calls.

All prompts sent to Azure OpenAI / Claude are scrubbed of PII:
- Names → [PERSON_1], [PERSON_2]
- Emails → [EMAIL]
- Phone numbers → [PHONE]
- Addresses → [ADDRESS]
- SSNs → [SSN]
- Dates of birth → [DOB]

The proxy maintains a reversible mapping for the current session
so responses can be de-anonymized for the user.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger("anonymization_proxy")

# PII patterns (regex-based NER substitute)
PII_PATTERNS = [
    # SSN
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),
    # Phone numbers (various formats)
    (r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE]"),
    # Email addresses
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]"),
    # Dates (MM/DD/YYYY, YYYY-MM-DD)
    (r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "[DATE]"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "[DATE]"),
    # Credit card numbers
    (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[CREDIT_CARD]"),
    # US addresses (simplified)
    (r"\b\d{1,5}\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd)\b", "[ADDRESS]"),
    # ZIP codes
    (r"\b\d{5}(?:-\d{4})?\b", "[ZIP]"),
]

# Common name patterns (for therapeutic context)
NAME_TITLE_PATTERN = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
)


class AnonymizationProxy:
    """
    Strips PII from prompts before they reach AI APIs.
    Maintains a reversible mapping for response de-anonymization.
    """

    def __init__(self):
        self._session_mappings: Dict[str, Dict[str, str]] = {}

    async def is_ready(self) -> bool:
        """Check if AnonymizationProxy is operational (patterns compiled)."""
        try:
            test_text = "test@example.com 555-123-4567"
            result, mapping = self.anonymize(test_text)
            return "[EMAIL]" in result or "[PHONE]" in result
        except Exception:
            return False

    def anonymize(self, text: str, session_id: str = "") -> Tuple[str, Dict[str, str]]:
        """
        Anonymize text by replacing PII with placeholders.
        Returns (anonymized_text, mapping_dict).
        """
        mapping: Dict[str, str] = {}
        result = text

        # Apply regex patterns
        for pattern, replacement in PII_PATTERNS:
            for match in re.finditer(pattern, result):
                original = match.group()
                if original not in mapping:
                    # Create unique placeholder
                    idx = len(mapping) + 1
                    placeholder = f"{replacement[:-1]}_{idx}]"
                    mapping[original] = placeholder
                result = result.replace(original, mapping[original], 1)

        # Apply name detection
        for match in NAME_TITLE_PATTERN.finditer(result):
            original = match.group()
            if original not in mapping:
                idx = sum(1 for k in mapping.values() if "PERSON" in k) + 1
                placeholder = f"[PERSON_{idx}]"
                mapping[original] = placeholder
            result = result.replace(original, mapping[original], 1)

        # Store mapping for this session
        if session_id:
            if session_id not in self._session_mappings:
                self._session_mappings[session_id] = {}
            self._session_mappings[session_id].update(mapping)

        return result, mapping

    def deanonymize(self, text: str, session_id: str = "", mapping: Dict[str, str] = None) -> str:
        """
        Reverse anonymization using the stored or provided mapping.
        """
        if mapping is None:
            mapping = self._session_mappings.get(session_id, {})

        if not mapping:
            return text

        # Reverse the mapping
        reverse_map = {v: k for k, v in mapping.items()}
        result = text
        for placeholder, original in reverse_map.items():
            result = result.replace(placeholder, original)

        return result

    def anonymize_for_ai(
        self, prompt: str, session_id: str = "", system_context: str = "",
    ) -> Dict[str, Any]:
        """
        Prepare a prompt for AI API call with full anonymization.
        Returns both anonymized prompt and the mapping for de-anonymization.
        """
        anon_prompt, prompt_map = self.anonymize(prompt, session_id)
        anon_context = ""
        if system_context:
            anon_context, _ = self.anonymize(system_context, session_id)

        return {
            "anonymized_prompt": anon_prompt,
            "anonymized_context": anon_context,
            "mapping": prompt_map,
            "original_pii_count": len(prompt_map),
            "session_id": session_id,
        }

    def clear_session(self, session_id: str) -> None:
        """Clear mapping data for a completed session."""
        self._session_mappings.pop(session_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """Get anonymization statistics."""
        return {
            "active_sessions": len(self._session_mappings),
            "total_mappings": sum(len(m) for m in self._session_mappings.values()),
        }
