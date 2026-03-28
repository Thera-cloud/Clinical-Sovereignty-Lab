"""
SOVEREIGN SWARM — Night School Content Parser
Extracts protocols, research findings, and techniques from
raw content (papers, books, clinical guidelines).

Operational Specifications §3.1 — Content Parsing.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("night_school.content_parser")


class ContentParser:
    """
    Parses raw clinical content into structured sections:
    protocols, research findings, techniques, and case examples.
    """

    def __init__(self, sovereign_mind=None):
        self._sovereign_mind = sovereign_mind

    async def parse(
        self, raw_content: str, content_type: str = "general"
    ) -> Dict[str, Any]:
        """
        Parse raw content into structured clinical knowledge.
        Uses AI extraction when available, keyword-based fallback otherwise.
        """
        result = {
            "sections": [],
            "protocols": [],
            "techniques": [],
            "research": [],
            "case_examples": [],
            "summary": "",
            "raw_length": len(raw_content),
        }

        # Split into sections
        sections = self._split_sections(raw_content)
        result["sections"] = sections

        # Extract protocols
        result["protocols"] = self._extract_protocols(raw_content)

        # Extract techniques
        result["techniques"] = self._extract_techniques(raw_content)

        # Extract research findings
        result["research"] = self._extract_research(raw_content)

        # Generate summary with AI if available
        if self._sovereign_mind:
            try:
                summary = await self._sovereign_mind.generate(
                    prompt="Summarize this clinical content in 2-3 sentences",
                    context={"content": raw_content[:3000]},
                )
                result["summary"] = summary or ""
            except Exception as e:
                logger.warning("AI summary generation failed: %s", e)

        if not result["summary"] and sections:
            result["summary"] = sections[0].get("content", "")[:200]

        return result

    def _split_sections(self, text: str) -> List[Dict[str, str]]:
        """Split content into sections based on headings."""
        sections = []
        # Match markdown-style headings
        pattern = r'^(#{1,3})\s+(.+)$'
        parts = re.split(pattern, text, flags=re.MULTILINE)

        current_title = "Introduction"
        current_content = []

        for part in parts:
            part = part.strip()
            if part.startswith("#"):
                continue
            if len(part) < 100 and not "\n" in part:
                # Likely a heading
                if current_content:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(current_content),
                    })
                current_title = part
                current_content = []
            else:
                current_content.append(part)

        if current_content:
            sections.append({
                "title": current_title,
                "content": "\n".join(current_content),
            })

        return sections

    def _extract_protocols(self, text: str) -> List[Dict[str, str]]:
        """Extract clinical protocols from content."""
        protocols = []
        protocol_markers = [
            "protocol:", "step 1", "phase 1", "procedure:",
            "intervention:", "treatment plan", "clinical guideline",
        ]
        lower = text.lower()
        for marker in protocol_markers:
            idx = lower.find(marker)
            while idx >= 0:
                # Extract surrounding context
                start = max(0, idx - 50)
                end = min(len(text), idx + 500)
                context = text[start:end].strip()
                protocols.append({
                    "marker": marker,
                    "context": context,
                    "position": idx,
                })
                idx = lower.find(marker, idx + len(marker))

        return protocols[:20]  # Cap at 20

    def _extract_techniques(self, text: str) -> List[Dict[str, str]]:
        """Extract therapeutic techniques from content."""
        techniques = []
        technique_keywords = [
            "technique", "exercise", "intervention", "practice",
            "activity", "homework", "experiment", "enactment",
        ]
        lower = text.lower()
        for kw in technique_keywords:
            idx = lower.find(kw)
            while idx >= 0:
                start = max(0, idx - 30)
                end = min(len(text), idx + 300)
                techniques.append({
                    "keyword": kw,
                    "context": text[start:end].strip(),
                })
                idx = lower.find(kw, idx + len(kw))

        return techniques[:30]

    def _extract_research(self, text: str) -> List[Dict[str, str]]:
        """Extract research findings and citations."""
        research = []
        # Look for citation patterns
        citation_pattern = r'\(([A-Z][a-z]+(?:\s+(?:&|and)\s+[A-Z][a-z]+)*,?\s*\d{4})\)'
        matches = re.finditer(citation_pattern, text)
        for match in matches:
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 100)
            research.append({
                "citation": match.group(1),
                "context": text[start:end].strip(),
            })

        return research[:50]
