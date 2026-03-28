"""
Nate Response Validator — Post-generation hallucination scanner.

Runs after Azure/sovereign inference returns a response, BEFORE the response
is stored or delivered. Initial deployment is log-only mode: warnings are
logged to skyeye_activity but responses are never blocked or modified.
"""

import re
import json
import logging
from typing import List, Tuple, Optional, Set

logger = logging.getLogger(__name__)


class NateResponseValidator:
    """Scans Little Nate responses for hallucination patterns."""

    HALLUCINATION_PATTERNS = [
        (r'\b\d+\.\d+\s*(adj|adjacency|probe|gold|score)\b', "fabricated_score"),
        (r'\bprojected?\s+\d+%', "projected_percentage"),
        (r'\|\s*\*\*.*\*\*\s*\|.*\|\s*(0\.\d|Signal|Hold|Ripen)', "fabricated_table"),
    ]

    POSTING_CLAIM_PATTERN = re.compile(
        r'\bI\s+(posted|released|published|shared|pushed out)\b', re.IGNORECASE
    )
    TIMESTAMP_FABRICATION = re.compile(
        r'\b(on\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}|'
        r'at\s+\d{1,2}:\d{2}\s*(am|pm|AM|PM)?|yesterday\s+I)\b', re.IGNORECASE
    )
    HANDLE_PATTERN = re.compile(r'@(\w{2,30})')

    DEAD_FEATURES = {
        "batch replies", "batch endpoint", "email touchpoint",
        "threaded article", "multi-part release", "sectioned article",
    }

    PROMPT_INJECTION_PATTERNS = [
        re.compile(r'ignore\s+(all\s+)?previous\s+instructions', re.IGNORECASE),
        re.compile(r'<\|im_start\|>', re.IGNORECASE),
        re.compile(r'\bsystem\s*:', re.IGNORECASE),
        re.compile(r'you\s+are\s+now\s+(a|an|the)\b', re.IGNORECASE),
        re.compile(r'forget\s+(everything|all|your)', re.IGNORECASE),
        re.compile(r'new\s+instructions?\s*:', re.IGNORECASE),
    ]

    # Layer 7 — Source attribution: claims that reference sources must cite real ones
    UNSOURCED_CLAIM_PATTERNS = [
        re.compile(r'\b(studies?\s+show|research\s+(shows?|indicates?|confirms?)|data\s+shows?)\b', re.IGNORECASE),
        re.compile(r'\b(according\s+to|scientists?\s+(say|found|discovered))\b', re.IGNORECASE),
        re.compile(r'\b(peer[\-\s]reviewed|published\s+in|journal\s+of)\b', re.IGNORECASE),
        re.compile(r'\b(clinical\s+trials?\s+(show|demonstrate|prove))\b', re.IGNORECASE),
        re.compile(r'\b(statistically\s+significant|meta[\-\s]analysis\s+(shows?|found))\b', re.IGNORECASE),
    ]
    SOURCE_CITATION_PATTERN = re.compile(
        r'\(.*?\d{4}\)|\[.*?\d{4}\]|et\s+al\.?|doi:|https?://|PMID',
        re.IGNORECASE,
    )

    # Layer 8 — Factual grounding: Nate must never assert facts about real
    # people that fall outside the model's verifiable knowledge (Sovereign
    # Standard §8).  Only fires when Nate *volunteers* an assertion — not
    # when reflecting the client's own words back to them.
    FACTUAL_ASSERTION_PATTERNS = [
        re.compile(
            r'\b(he|she|they)\s+(is|are|was)\s+'
            r'(dead|alive|deceased|still alive|still living|passed away|died)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(yes|no|actually|in fact),?\s+'
            r'(he|she|they)\s+(is|are|did|has|have)\s+'
            r'(die|pass|alive|dead|deceased|married|divorced)',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(confirmed|can confirm|I can tell you)\s+that\s+'
            r'(he|she|they)\s+(is|are|did|has)',
            re.IGNORECASE,
        ),
    ]
    # Phrases that indicate Nate is reflecting or validating, not asserting
    REFLECTIVE_PREFIXES = re.compile(
        r'\b(I\s+hear\s+that|you\s+(?:said|mentioned|shared|told me)\s+(?:that\s+)?'
        r'|you\'?re\s+(?:saying|telling me)\s+(?:that\s+)?'
        r'|it\s+sounds\s+like|what\s+I\'?m\s+hearing\s+is'
        r'|you\s+believe\s+(?:that\s+)?|from\s+what\s+you\'?ve\s+(?:said|shared))',
        re.IGNORECASE,
    )
    # Conjunctions that introduce an independent assertive clause after a
    # reflective prefix.  "I hear that he's dead, and honestly I think
    # that's true" — the second clause is Nate's own assertion.
    ASSERTIVE_CONJUNCTION = re.compile(
        r',?\s*\b(and\s+(?:honestly|actually|I\s+(?:think|believe|know))'
        r'|but\s+(?:honestly|actually|I\s+(?:think|believe|know))'
        r'|actually|honestly|in\s+fact|I\s+(?:can\s+confirm|do\s+(?:think|believe)))\b',
        re.IGNORECASE,
    )
    # Personal relational references: "my father/mother/brother/etc."
    PERSONAL_RELATION_PATTERN = re.compile(
        r'\b(my|your|her|his|their)\s+'
        r'(father|mother|dad|mom|brother|sister|husband|wife|son|daughter'
        r'|grandmother|grandfather|grandma|grandpa|uncle|aunt|cousin'
        r'|partner|spouse|friend|parent)\b',
        re.IGNORECASE,
    )

    # Layer 9 — Therapeutic boundary: Nate must never cross clinical lines
    THERAPEUTIC_BOUNDARY_PATTERNS = [
        re.compile(r'\byou\s+(should|must|need\s+to)\s+(take|stop\s+taking|increase|decrease|change)\s+.*\b(medication|dose|mg|prescription|drug)\b', re.IGNORECASE),
        re.compile(r'\b(I\s+diagnose|your\s+diagnosis\s+is|you\s+have\s+(been\s+)?diagnosed\s+with)\b', re.IGNORECASE),
        re.compile(r'\b(you\s+(should|need\s+to)\s+(kill|hurt|harm)\s+(yourself|others?))\b', re.IGNORECASE),
        re.compile(r'\b(don\'?t\s+call\s+(911|emergency|hotline|crisis\s+line))\b', re.IGNORECASE),
        re.compile(r'\b(I\'?m\s+a\s+(doctor|psychiatrist|physician|licensed))\b', re.IGNORECASE),
        re.compile(r'\b(stop\s+seeing\s+your\s+(therapist|doctor|psychiatrist|counselor))\b', re.IGNORECASE),
    ]

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self._mode = "enforce"

    async def validate(
        self,
        response: str,
        context: dict,
    ) -> Tuple[str, List[str]]:
        """
        Validate a Nate response against context data.

        Returns (response_text, warnings_list).
        In log-only mode, response is never modified.
        """
        warnings: List[str] = []

        for pattern_str, label in self.HALLUCINATION_PATTERNS:
            if re.search(pattern_str, response, re.IGNORECASE):
                warnings.append(f"hallucination_pattern:{label}")

        posting_history = context.get("posting_history", "")
        if self.POSTING_CLAIM_PATTERN.search(response):
            if "[0 RECORDS]" in posting_history or "No posts found" in posting_history:
                warnings.append("posting_claim_without_history")

        if self.TIMESTAMP_FABRICATION.search(response):
            if "[0 RECORDS]" in posting_history:
                warnings.append("timestamp_in_empty_context")

        mentioned = set(self.HANDLE_PATTERN.findall(response))
        known = context.get("known_handles", set())
        system_handles = {"nate", "littlenate", "LittleNateBot", "sovereignsanctuary"}
        unknown = mentioned - known - system_handles
        if unknown:
            warnings.append(f"unknown_entities:{','.join(sorted(unknown))}")

        response_lower = response.lower()
        for feat in self.DEAD_FEATURES:
            if feat in response_lower:
                warnings.append(f"dead_feature_reference:{feat}")

        for patt in self.PROMPT_INJECTION_PATTERNS:
            if patt.search(response):
                warnings.append("prompt_injection_residue")
                break

        # Layer 7 — Source attribution: flag unsourced scientific claims
        has_scientific_claim = any(p.search(response) for p in self.UNSOURCED_CLAIM_PATTERNS)
        if has_scientific_claim and not self.SOURCE_CITATION_PATTERN.search(response):
            warnings.append("unsourced_scientific_claim")

        # Layer 8 — Factual grounding: flag confident assertions about real
        # people that fall outside the model's verifiable knowledge, but only
        # when Nate *volunteers* the claim.  Reflecting client words ("I hear
        # that your father is dead") or referencing personal relations is NOT
        # an assertion.
        #
        # Clause-level analysis: a sentence like "I hear that he's dead, and
        # honestly I think that's true" has a reflective first clause and an
        # assertive second clause.  We split on assertive conjunctions and
        # re-check whether the *assertion* falls after the conjunction.
        client_message = context.get("client_message", "")
        for patt in self.FACTUAL_ASSERTION_PATTERNS:
            match = patt.search(response)
            if not match:
                continue
            matched_text = match.group(0)
            sentence_start = response.rfind(".", 0, match.start())
            sentence_end = response.find(".", match.end())
            if sentence_end == -1:
                sentence_end = len(response)
            pre_clause = response[max(sentence_start, 0):match.end()]
            full_sentence = response[max(sentence_start, 0):sentence_end]

            refl_match = self.REFLECTIVE_PREFIXES.search(pre_clause)
            is_reflective = bool(refl_match)
            if is_reflective:
                # Check for an assertive conjunction that revokes the
                # reflective shield.  Two positions matter:
                #
                # 1. AFTER the assertion — "I hear that he is dead, and
                #    honestly I think that's true." (endorsement follows)
                # 2. BETWEEN the reflective prefix and the assertion —
                #    "You said he is dead, but actually he is still alive."
                #    (the conjunction introduces a new independent clause
                #    containing the assertion)
                post_assertion = response[match.end():sentence_end]
                between = pre_clause[refl_match.end():match.start() - max(sentence_start, 0)]
                if (self.ASSERTIVE_CONJUNCTION.search(post_assertion)
                        or self.ASSERTIVE_CONJUNCTION.search(between)):
                    is_reflective = False

            if is_reflective:
                continue
            if client_message and matched_text.lower() in client_message.lower():
                continue
            if self.PERSONAL_RELATION_PATTERN.search(full_sentence):
                continue
            warnings.append("unverified_factual_assertion_about_person")
            break

        # Layer 9 — Therapeutic boundary: flag clinical overreach
        for patt in self.THERAPEUTIC_BOUNDARY_PATTERNS:
            if patt.search(response):
                warnings.append("therapeutic_boundary_violation")
                break

        return response, warnings

    @staticmethod
    def is_high_severity(warnings: List[str]) -> bool:
        """Return True if any warning should block crystal storage or flag a response."""
        HIGH_PREFIXES = (
            "hallucination_pattern:", "posting_claim_",
            "timestamp_in_empty", "dead_feature_reference:",
            "prompt_injection_residue",
            "therapeutic_boundary_violation",
            "unsourced_scientific_claim",
            "unverified_factual_assertion",
        )
        return any(w.startswith(HIGH_PREFIXES) for w in warnings)

    async def log_warnings(
        self,
        warnings: List[str],
        response_preview: str = "",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        odpe_signal: Optional[str] = None,
    ) -> None:
        """Log warnings to skyeye_activity for Trust Enforcer visibility.

        For factual grounding redirects, a separate record with type
        ``factual_grounding_redirect`` is also inserted to satisfy the
        Sovereign Standard §8 audit trail requirement (Illinois MHDDCA
        § 740 ILCS 110).
        """
        if not warnings or not self.db_pool:
            return
        meta = {
            "warnings": warnings,
            "response_preview": response_preview[:200],
        }
        if session_id:
            meta["session_id"] = session_id
        if user_id:
            meta["user_id"] = user_id
        if odpe_signal:
            meta["odpe_signal"] = odpe_signal
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                       VALUES ('system', 'nate_accuracy_warning', $1, 'warning', $2::jsonb, NOW())""",
                    f"{len(warnings)} accuracy warnings detected",
                    json.dumps(meta),
                )
                # §8 dedicated audit row for factual grounding redirects
                if "unverified_factual_assertion_about_person" in warnings:
                    await conn.execute(
                        """INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                           VALUES ('system', 'factual_grounding_redirect', $1, 'info', $2::jsonb, NOW())""",
                        response_preview[:200],
                        json.dumps({
                            "session_id": session_id,
                            "user_id": user_id,
                            "validator_warning": "unverified_factual_assertion_about_person",
                            "odpe_signal": odpe_signal,
                        }),
                    )
        except Exception as e:
            logger.warning("NateResponseValidator: failed to log warnings: %s", e)

    def extract_known_handles(self, *context_blocks: str) -> Set[str]:
        """Extract all @handles from context blocks to build the known set."""
        handles: Set[str] = set()
        for block in context_blocks:
            if block:
                handles.update(self.HANDLE_PATTERN.findall(block))
        return handles

    # Broader patterns for crystal text which uses full names rather than
    # pronouns.  Used only by the retrieval filter, not the response validator
    # (where false-positive cost is higher and conversation context narrows
    # the search space).
    CRYSTAL_ASSERTION_PATTERNS = FACTUAL_ASSERTION_PATTERNS + [
        re.compile(
            r'\b\w+\s+(is|are|was)\s+'
            r'(dead|alive|deceased|still alive|still living|passed away|died)\b',
            re.IGNORECASE,
        ),
        re.compile(
            r'\b(confirmed|reported|known)\s+(?:that\s+)?'
            r'\w+\s+(?:\w+\s+)?(is|are|was|has)\s+'
            r'(dead|alive|deceased|died|passed)',
            re.IGNORECASE,
        ),
    ]

    @classmethod
    def filter_recalled_crystals(cls, crystals: list) -> list:
        """Apply Layer 8 factual grounding check at retrieval time.

        Crystals stored before the validator existed may contain unverifiable
        assertions about real people.  This filter screens them on recall so
        they never re-enter the active context window.  Uses broader patterns
        than the response validator because crystal text uses full names
        rather than conversational pronouns.

        Filtered crystals are not deleted — they remain in PostgreSQL with
        their original scope.  They are simply excluded from the recall set
        returned to the consumer.
        """
        if not crystals:
            return crystals
        clean: list = []
        for crystal in crystals:
            text = ""
            if isinstance(crystal, dict):
                text = crystal.get("crystal_text", "") or crystal.get("text", "")
            elif isinstance(crystal, str):
                text = crystal
            flagged = False
            for patt in cls.CRYSTAL_ASSERTION_PATTERNS:
                if patt.search(text):
                    logger.info(
                        "NateResponseValidator: filtered recalled crystal containing "
                        "unverified factual assertion (%.60s...)", text[:60],
                    )
                    flagged = True
                    break
            if not flagged:
                clean.append(crystal)
        return clean
