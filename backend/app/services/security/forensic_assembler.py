"""
HIVE DEFENSE PROTOCOL — Forensic Assembler (Phase 8B)
Cross-references Ghost Swarm reports to produce consolidated intelligence.

After a Ghost Swarm mission is recalled, the Forensic Assembler ingests
the heterogeneous findings from passive observers, active probes, canary
injectors, and (optionally) decoys, then performs multi-source
cross-verification to separate real intelligence from attacker-planted
disinformation.

Cross-Verification Logic
------------------------
* **Consistent** findings (reported by ≥2 independent ghost types)
  are classified as high-confidence real intelligence.
* **Inconsistent** findings (contradicted by other ghosts) are flagged
  as probable attacker disinformation / deception.
* **Singleton** findings (reported by exactly one ghost) remain
  low-confidence and are included but clearly marked.

Output: a verified :class:`AttackerProfile` with confidence scores,
confirmed C&C addresses, protocol details, timing patterns, and
recommended response actions.

Patent-Pending — Phase 8B
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import AttackerProfile, GhostType

logger = logging.getLogger("hive.forensic_assembler")


# =============================================================================
# CONFIDENCE THRESHOLDS
# =============================================================================

# Minimum number of independent ghost sources that must agree for a finding
# to be considered "verified"
VERIFIED_THRESHOLD = 2

# Confidence tier labels
CONFIDENCE_VERIFIED = "verified"       # ≥ VERIFIED_THRESHOLD sources agree
CONFIDENCE_PROBABLE = "probable"       # Single credible source
CONFIDENCE_UNCERTAIN = "uncertain"     # Conflicting reports
CONFIDENCE_DISINFO = "disinformation"  # Contradicted by majority

# Weights by ghost type (decoys are excluded from analysis by default)
GHOST_TYPE_WEIGHTS: Dict[str, float] = {
    GhostType.PASSIVE_OBSERVER.value: 1.0,   # Most reliable — observation only
    GhostType.ACTIVE_PROBE.value: 0.9,       # Slightly less — may trigger responses
    GhostType.CANARY_INJECTOR.value: 0.85,   # Good for tracing, less for direct intel
    GhostType.DECOY.value: 0.0,              # Never used for intelligence
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class AssembledFinding:
    """
    A single cross-referenced finding from multiple ghost sources.

    Attributes
    ----------
    finding_key : str
        Canonical identifier for the finding (e.g., ``"cnc_address:10.0.1.5"``).
    category : str
        Finding category (``"cnc_address"``, ``"protocol"``, ``"timing"``).
    value : Any
        The finding value.
    sources : list[dict]
        List of ``{"ghost_id": ..., "ghost_type": ..., "raw": ...}`` from
        each ghost that reported this finding.
    confidence : float
        Aggregate confidence score in [0.0, 1.0].
    confidence_tier : str
        One of: ``verified``, ``probable``, ``uncertain``, ``disinformation``.
    contradicted_by : list[str]
        Ghost IDs that reported contradictory information.
    """

    __slots__ = (
        "finding_key",
        "category",
        "value",
        "sources",
        "confidence",
        "confidence_tier",
        "contradicted_by",
    )

    def __init__(self, finding_key: str, category: str, value: Any) -> None:
        self.finding_key = finding_key
        self.category = category
        self.value = value
        self.sources: List[Dict[str, Any]] = []
        self.confidence: float = 0.0
        self.confidence_tier: str = CONFIDENCE_UNCERTAIN
        self.contradicted_by: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "finding_key": self.finding_key,
            "category": self.category,
            "value": self.value,
            "source_count": len(self.sources),
            "source_types": list({s["ghost_type"] for s in self.sources}),
            "confidence": round(self.confidence, 4),
            "confidence_tier": self.confidence_tier,
            "contradicted_by_count": len(self.contradicted_by),
        }


class AssembledReport:
    """
    Consolidated intelligence report from a Ghost Swarm mission.

    Attributes
    ----------
    report_id : UUID
        Unique identifier for this report.
    mission_id : UUID
        The Ghost Swarm mission these findings came from.
    findings : list[AssembledFinding]
        All cross-referenced findings.
    verified_cnc_addresses : list[str]
        C&C addresses confirmed by ≥2 independent ghosts.
    protocol_details : dict
        Verified protocol information.
    timing_patterns : dict
        Verified timing analysis.
    disinformation_detected : bool
        Whether attacker deception was identified.
    disinformation_findings : list[AssembledFinding]
        Findings flagged as disinformation.
    recommended_response : str
        Recommended defensive action.
    assembled_at : datetime
        When this report was assembled.
    """

    def __init__(self, mission_id: UUID) -> None:
        self.report_id: UUID = uuid4()
        self.mission_id = mission_id
        self.findings: List[AssembledFinding] = []
        self.verified_cnc_addresses: List[str] = []
        self.protocol_details: Dict[str, Any] = {}
        self.timing_patterns: Dict[str, Any] = {}
        self.disinformation_detected: bool = False
        self.disinformation_findings: List[AssembledFinding] = []
        self.recommended_response: str = ""
        self.assembled_at: datetime = datetime.utcnow()
        self.ghost_summary: Dict[str, int] = {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the full report."""
        return {
            "report_id": str(self.report_id),
            "mission_id": str(self.mission_id),
            "assembled_at": self.assembled_at.isoformat(),
            "findings_count": len(self.findings),
            "verified_findings": sum(
                1 for f in self.findings if f.confidence_tier == CONFIDENCE_VERIFIED
            ),
            "verified_cnc_addresses": self.verified_cnc_addresses,
            "protocol_details": self.protocol_details,
            "timing_patterns": self.timing_patterns,
            "disinformation_detected": self.disinformation_detected,
            "disinformation_count": len(self.disinformation_findings),
            "recommended_response": self.recommended_response,
            "ghost_summary": self.ghost_summary,
            "findings": [f.to_dict() for f in self.findings],
        }


# =============================================================================
# FORENSIC ASSEMBLER
# =============================================================================

class ForensicAssembler:
    """
    Cross-references Ghost Swarm findings to produce consolidated
    intelligence reports.

    The assembler operates entirely outside the containment zone,
    working only on pre-collected finding data.  It never interacts
    with the live containment environment.

    Usage
    -----
    ::

        assembler = ForensicAssembler()
        report = await assembler.assemble_findings(ghost_findings, mission_id)
        profile = await assembler.build_cnc_profile(report)
    """

    def __init__(self) -> None:
        self._reports: Dict[UUID, AssembledReport] = {}

    # --------------------------------------------------------------------- #
    # MAIN ASSEMBLY
    # --------------------------------------------------------------------- #

    async def assemble_findings(
        self,
        ghost_findings: List[Dict[str, Any]],
        mission_id: Optional[UUID] = None,
    ) -> AssembledReport:
        """
        Assemble raw ghost findings into a consolidated intelligence report.

        Parameters
        ----------
        ghost_findings : list[dict]
            Raw findings from :meth:`GhostSwarm.get_findings`.  Each dict
            must contain ``_ghost_id``, ``_ghost_type``, and observation
            data.
        mission_id : UUID, optional
            Mission identifier.  If ``None``, a new UUID is generated.

        Returns
        -------
        AssembledReport
            The consolidated report with confidence-scored findings.
        """
        if mission_id is None:
            mission_id = uuid4()

        report = AssembledReport(mission_id)
        logger.info(
            "Assembling findings for mission %s — %d raw findings.",
            mission_id,
            len(ghost_findings),
        )

        # Phase 1: Filter out decoy noise
        real_findings = [
            f for f in ghost_findings
            if not f.get("_is_decoy", False)
        ]
        logger.debug(
            "Filtered to %d real findings (removed %d decoy entries).",
            len(real_findings),
            len(ghost_findings) - len(real_findings),
        )

        # Phase 2: Categorise and group findings
        categorised = self._categorise_findings(real_findings)

        # Phase 3: Cross-reference within each category
        for category, entries in categorised.items():
            assembled = self._cross_reference_category(category, entries)
            report.findings.extend(assembled)

        # Phase 4: Detect disinformation
        self._detect_disinformation(report)

        # Phase 5: Extract verified intelligence
        self._extract_verified_intelligence(report)

        # Phase 6: Generate recommendation
        report.recommended_response = self._generate_recommendation(report)

        # Phase 7: Ghost summary
        report.ghost_summary = self._summarise_ghost_contributions(real_findings)

        # Store report
        self._reports[report.report_id] = report

        logger.info(
            "Assembly complete for mission %s: %d findings, %d verified, "
            "%d flagged as disinfo.  Recommendation: %s",
            mission_id,
            len(report.findings),
            sum(1 for f in report.findings if f.confidence_tier == CONFIDENCE_VERIFIED),
            len(report.disinformation_findings),
            report.recommended_response,
        )

        return report

    # --------------------------------------------------------------------- #
    # PHASE 2: CATEGORISATION
    # --------------------------------------------------------------------- #

    def _categorise_findings(
        self,
        findings: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group raw findings by category.

        Categories are derived from the ``type`` field of each finding:
        ``passive_capture`` → ``traffic``, ``active_probe`` → ``probe``,
        ``canary_injection`` → ``canary``, etc.
        """
        categories: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        type_to_category = {
            "passive_capture": "traffic",
            "active_probe": "probe",
            "canary_injection": "canary",
        }

        for finding in findings:
            ftype = finding.get("type", "unknown")
            category = type_to_category.get(ftype, ftype)
            categories[category].append(finding)

        logger.debug(
            "Categorised findings: %s",
            {k: len(v) for k, v in categories.items()},
        )
        return dict(categories)

    # --------------------------------------------------------------------- #
    # PHASE 3: CROSS-REFERENCE
    # --------------------------------------------------------------------- #

    def _cross_reference_category(
        self,
        category: str,
        entries: List[Dict[str, Any]],
    ) -> List[AssembledFinding]:
        """
        Cross-reference findings within a single category.

        Extracts canonical keys from each finding and groups entries
        that refer to the same underlying observation.  Then scores
        confidence based on source diversity.
        """
        # Group by canonical keys extracted from the finding
        key_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for entry in entries:
            keys = self._extract_canonical_keys(category, entry)
            for key, value in keys:
                key_groups[key].append({
                    "ghost_id": entry.get("_ghost_id", "unknown"),
                    "ghost_type": entry.get("_ghost_type", "unknown"),
                    "value": value,
                    "raw": entry,
                })

        assembled: List[AssembledFinding] = []
        for finding_key, sources in key_groups.items():
            finding = AssembledFinding(
                finding_key=finding_key,
                category=category,
                value=self._consensus_value(sources),
            )
            finding.sources = sources
            finding.confidence = self._compute_confidence(sources)
            finding.confidence_tier = self._assign_confidence_tier(
                finding.confidence, len(sources), sources
            )
            assembled.append(finding)

        return assembled

    def _extract_canonical_keys(
        self,
        category: str,
        entry: Dict[str, Any],
    ) -> List[Tuple[str, Any]]:
        """
        Extract canonical key-value pairs from a raw finding.

        Returns a list of (canonical_key, value) tuples that can be used
        to match findings across ghosts.
        """
        keys: List[Tuple[str, Any]] = []

        if category == "traffic":
            # Extract from traffic patterns
            patterns = entry.get("traffic_patterns", {})
            for proto in patterns.get("protocols_seen", []):
                keys.append((f"protocol_seen:{proto}", proto))
            if patterns.get("unique_sources"):
                keys.append(
                    (f"traffic:unique_sources:{patterns['unique_sources']}", patterns["unique_sources"])
                )
            # Timing analysis
            timing = entry.get("timing_analysis", {})
            if timing.get("periodicity_score") is not None:
                # Bucket periodicity to allow fuzzy matching
                bucket = round(timing["periodicity_score"], 1)
                keys.append((f"timing:periodicity:{bucket}", timing["periodicity_score"]))
            if timing.get("burst_detected"):
                keys.append(("timing:burst_detected", True))

        elif category == "probe":
            # Active probe results
            fp = entry.get("response_fingerprint", {})
            if fp.get("response_pattern"):
                keys.append((f"probe:pattern:{fp['response_pattern']}", fp["response_pattern"]))
            if fp.get("version_string"):
                keys.append((f"probe:version:{fp['version_string']}", fp["version_string"]))
            proto = entry.get("protocol_detected")
            if proto and proto != "unknown":
                keys.append((f"probe:protocol:{proto}", proto))

        elif category == "canary":
            # Canary tokens — each is unique, but we track injection points
            injection_point = entry.get("injection_point", "")
            if injection_point:
                keys.append((f"canary:point:{injection_point}", entry.get("canary_token")))

        else:
            # Generic: use the type as key
            keys.append((f"{category}:observation", entry))

        return keys

    # --------------------------------------------------------------------- #
    # CONFIDENCE SCORING
    # --------------------------------------------------------------------- #

    def _compute_confidence(self, sources: List[Dict[str, Any]]) -> float:
        """
        Compute confidence score for a finding based on its sources.

        Factors:
            * Number of independent sources
            * Diversity of ghost types
            * Weight of each ghost type
            * Value consistency across sources
        """
        if not sources:
            return 0.0

        # Source count factor (diminishing returns above 3)
        count_factor = min(len(sources) / VERIFIED_THRESHOLD, 1.5)

        # Type diversity factor
        unique_types: Set[str] = {s["ghost_type"] for s in sources}
        diversity_factor = len(unique_types) / len(GHOST_TYPE_WEIGHTS)

        # Weighted source quality
        type_weights = [
            GHOST_TYPE_WEIGHTS.get(s["ghost_type"], 0.5) for s in sources
        ]
        avg_weight = statistics.mean(type_weights) if type_weights else 0.5

        # Value consistency (do all sources agree on the value?)
        values = [str(s.get("value", "")) for s in sources]
        most_common_count = Counter(values).most_common(1)[0][1] if values else 0
        consistency_factor = most_common_count / len(values) if values else 0.0

        confidence = (
            0.35 * count_factor +
            0.20 * diversity_factor +
            0.20 * avg_weight +
            0.25 * consistency_factor
        )

        return min(max(confidence, 0.0), 1.0)

    def _assign_confidence_tier(
        self,
        confidence: float,
        source_count: int,
        sources: List[Dict[str, Any]],
    ) -> str:
        """Assign a human-readable confidence tier."""
        unique_types = {s["ghost_type"] for s in sources}

        # Verified: ≥2 sources from different ghost types with high confidence
        if source_count >= VERIFIED_THRESHOLD and len(unique_types) >= 2 and confidence >= 0.6:
            return CONFIDENCE_VERIFIED

        # Check for contradiction (different values from different ghosts)
        values = [str(s.get("value", "")) for s in sources]
        unique_values = set(values)
        if len(unique_values) > 1 and source_count >= 2:
            # Majority agrees → probable; minority is contradicted
            most_common = Counter(values).most_common(1)[0][1]
            if most_common >= source_count * 0.5:
                return CONFIDENCE_PROBABLE
            return CONFIDENCE_UNCERTAIN

        if confidence >= 0.4:
            return CONFIDENCE_PROBABLE

        return CONFIDENCE_UNCERTAIN

    @staticmethod
    def _consensus_value(sources: List[Dict[str, Any]]) -> Any:
        """Return the most common value among sources (majority vote)."""
        if not sources:
            return None
        values = [s.get("value") for s in sources]
        # For non-hashable values, use first value
        try:
            most_common = Counter(str(v) for v in values).most_common(1)
            if most_common:
                winner_str = most_common[0][0]
                for v in values:
                    if str(v) == winner_str:
                        return v
        except Exception:
            pass
        return values[0]

    # --------------------------------------------------------------------- #
    # PHASE 4: DISINFORMATION DETECTION
    # --------------------------------------------------------------------- #

    def _detect_disinformation(self, report: AssembledReport) -> None:
        """
        Flag findings that appear to be attacker-planted disinformation.

        A finding is flagged as disinformation when:
        * It contradicts the majority of other findings in the same category
        * Only a single ghost type reports it AND other types contradict it
        * Confidence is below the uncertain threshold with contradictions
        """
        category_groups: Dict[str, List[AssembledFinding]] = defaultdict(list)
        for finding in report.findings:
            category_groups[finding.category].append(finding)

        for category, findings in category_groups.items():
            if len(findings) < 2:
                continue

            # Look for contradictions within category
            for finding in findings:
                # Check if this finding contradicts the majority
                contradictors = []
                for other in findings:
                    if other is finding:
                        continue
                    if self._findings_contradict(finding, other):
                        contradictors.append(other)

                if contradictors and len(contradictors) >= len(findings) - 1:
                    # This finding contradicts most others → likely disinfo
                    finding.confidence_tier = CONFIDENCE_DISINFO
                    finding.contradicted_by = [
                        str(s["ghost_id"])
                        for c in contradictors
                        for s in c.sources
                    ]
                    report.disinformation_findings.append(finding)

        report.disinformation_detected = len(report.disinformation_findings) > 0

    @staticmethod
    def _findings_contradict(a: AssembledFinding, b: AssembledFinding) -> bool:
        """
        Determine whether two findings in the same category contradict
        each other.  Two findings contradict if they address the same
        dimension but report incompatible values.
        """
        # Same key prefix but different values
        a_prefix = a.finding_key.rsplit(":", 1)[0] if ":" in a.finding_key else a.finding_key
        b_prefix = b.finding_key.rsplit(":", 1)[0] if ":" in b.finding_key else b.finding_key

        if a_prefix == b_prefix and a.value != b.value:
            return True
        return False

    # --------------------------------------------------------------------- #
    # PHASE 5: EXTRACT VERIFIED INTELLIGENCE
    # --------------------------------------------------------------------- #

    def _extract_verified_intelligence(self, report: AssembledReport) -> None:
        """
        Populate the report's verified C&C, protocol, and timing fields
        from high-confidence findings.
        """
        for finding in report.findings:
            if finding.confidence_tier not in (CONFIDENCE_VERIFIED, CONFIDENCE_PROBABLE):
                continue

            key = finding.finding_key

            # C&C addresses
            if "cnc_address" in key or "probe:version" in key:
                if isinstance(finding.value, str) and finding.value:
                    if finding.value not in report.verified_cnc_addresses:
                        report.verified_cnc_addresses.append(finding.value)

            # Protocol details
            if "protocol" in key:
                report.protocol_details[key] = {
                    "value": finding.value,
                    "confidence": finding.confidence,
                    "tier": finding.confidence_tier,
                }

            # Timing patterns
            if "timing" in key:
                report.timing_patterns[key] = {
                    "value": finding.value,
                    "confidence": finding.confidence,
                    "tier": finding.confidence_tier,
                }

    # --------------------------------------------------------------------- #
    # PHASE 6: RECOMMENDATION
    # --------------------------------------------------------------------- #

    def _generate_recommendation(self, report: AssembledReport) -> str:
        """
        Generate a recommended defensive response based on the assembly.

        Recommendations escalate with verified intelligence:
        * C&C identified → deploy Infinite Mirror Trap
        * Protocol identified but no C&C → deploy more ghosts
        * Disinformation detected → attacker is sophisticated, proceed carefully
        * Insufficient data → extend observation window
        """
        verified_count = sum(
            1 for f in report.findings if f.confidence_tier == CONFIDENCE_VERIFIED
        )

        if report.verified_cnc_addresses and verified_count >= 3:
            if report.disinformation_detected:
                return (
                    "DEPLOY_MIRROR_TRAP_WITH_CAUTION — C&C identified but "
                    "disinformation detected.  Attacker is sophisticated.  "
                    "Use Projected Helix for adaptive response."
                )
            return (
                "DEPLOY_MIRROR_TRAP — C&C server(s) confirmed by multiple "
                "independent ghosts.  Recommend Infinite Mirror Trap deployment."
            )

        if report.protocol_details and verified_count >= 1:
            return (
                "EXTEND_OBSERVATION — Protocol identified but C&C not yet "
                "confirmed.  Deploy additional ghost swarm with increased "
                "active probes."
            )

        if report.disinformation_detected:
            return (
                "CAUTION_DISINFO — Attacker appears to be planting "
                "disinformation.  Increase swarm size and add canary "
                "injectors for tracing."
            )

        return (
            "INSUFFICIENT_DATA — Not enough corroborated findings.  "
            "Extend observation window or increase swarm composition."
        )

    # --------------------------------------------------------------------- #
    # GHOST SUMMARY
    # --------------------------------------------------------------------- #

    @staticmethod
    def _summarise_ghost_contributions(
        findings: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Count findings per ghost type."""
        counter: Dict[str, int] = defaultdict(int)
        for f in findings:
            gtype = f.get("_ghost_type", "unknown")
            counter[gtype] += 1
        return dict(counter)

    # --------------------------------------------------------------------- #
    # BUILD C&C PROFILE
    # --------------------------------------------------------------------- #

    async def build_cnc_profile(
        self,
        assembled_report: AssembledReport,
    ) -> AttackerProfile:
        """
        Construct an :class:`AttackerProfile` from an assembled report.

        Parameters
        ----------
        assembled_report : AssembledReport
            The consolidated intelligence report.

        Returns
        -------
        AttackerProfile
            A profile of the attacker's C&C infrastructure with
            confidence-scored attributes.
        """
        profile = AttackerProfile(
            active_channels=assembled_report.verified_cnc_addresses,
            communication_protocol=assembled_report.protocol_details,
            behavioral_patterns=assembled_report.timing_patterns,
        )

        # Determine sophistication level from disinfo and finding diversity
        if assembled_report.disinformation_detected:
            profile.sophistication_level = min(
                5,
                3 + len(assembled_report.disinformation_findings),
            )
        else:
            verified = sum(
                1 for f in assembled_report.findings
                if f.confidence_tier == CONFIDENCE_VERIFIED
            )
            # Fewer verified → potentially more evasive → higher sophistication
            if verified == 0:
                profile.sophistication_level = 4
            elif verified <= 2:
                profile.sophistication_level = 3
            else:
                profile.sophistication_level = 2

        # Tool signatures from probe findings
        for finding in assembled_report.findings:
            if "probe:version" in finding.finding_key and isinstance(finding.value, str):
                if finding.value and finding.value not in profile.tool_signatures:
                    profile.tool_signatures.append(finding.value)

        # Expected responses (for Mirror Trap consumption)
        profile.expected_responses = {
            "protocol_patterns": assembled_report.protocol_details,
            "timing_expectations": assembled_report.timing_patterns,
            "confidence_summary": {
                "verified": sum(
                    1 for f in assembled_report.findings
                    if f.confidence_tier == CONFIDENCE_VERIFIED
                ),
                "probable": sum(
                    1 for f in assembled_report.findings
                    if f.confidence_tier == CONFIDENCE_PROBABLE
                ),
                "uncertain": sum(
                    1 for f in assembled_report.findings
                    if f.confidence_tier == CONFIDENCE_UNCERTAIN
                ),
                "disinformation": sum(
                    1 for f in assembled_report.findings
                    if f.confidence_tier == CONFIDENCE_DISINFO
                ),
            },
        }

        profile.first_seen = assembled_report.assembled_at
        profile.last_seen = assembled_report.assembled_at

        logger.info(
            "Built C&C profile %s — sophistication: %d, channels: %d, "
            "tool signatures: %d",
            profile.profile_id,
            profile.sophistication_level,
            len(profile.active_channels),
            len(profile.tool_signatures),
        )

        return profile

    # --------------------------------------------------------------------- #
    # REPORT ACCESS
    # --------------------------------------------------------------------- #

    async def get_report(self, report_id: UUID) -> Optional[AssembledReport]:
        """Retrieve a previously assembled report by ID."""
        return self._reports.get(report_id)
