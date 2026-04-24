"""
Clinical Translation Engine — narrative (client) ↔ clinical (coach) views of the same event.
Post-generation enrichment only; does not alter client-facing copy or generation prompts.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SYSTEM_PANEL = """You are a clinical translator. Given metadata from a therapeutic story-world panel \
(the client's metaphorical journey scene), produce a concise clinical summary using standard \
therapeutic terminology (IFS, EFT, AEDP, CBT as appropriate). Include:
- Therapeutic modality being used (best fit)
- Observable behavioral indicators (inferred from narrative/prompt, stated tentatively)
- Emotional coherence movement if detectable from cues (otherwise null)
- Recommended coach follow-up if applicable (otherwise null)

If the user blob includes a "session_observations" field with multimodal/longitudinal pattern data \
from recent sessions (e.g. shame cycle, sustained withdrawal, gaze aversion), reference observed \
behavioral patterns in the clinical summary (e.g. "Client's recent sessions show elevated gaze \
aversion consistent with shame cycle — this panel's exile retrieval theme is therapeutically aligned").

Return JSON only, no markdown:
{"clinical_summary": "3-4 sentences max", "therapeutic_modality": "short label", \
"behavioral_indicators": ["..."], "ec_movement": null or {"from": float, "to": float}, \
"recommended_follow_up": null or "short string"}"""

_SYSTEM_EVENT = """You translate clinical or risk-assessment signals into gentle mythic story language \
for a client's Thera-World narrative. Output 1-2 sentences only, second-person or neutral mythic tone, \
no jargon, no diagnosis language. No markdown."""


def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _fallback_from_metadata(panel_metadata: Dict[str, Any]) -> Dict[str, Any]:
    tone = (panel_metadata.get("panel_tone") or "").strip()
    biome = (panel_metadata.get("biome") or "").strip()
    nar = (panel_metadata.get("narrative_text") or "")[:200].strip()
    return {
        "clinical_summary": (
            f"Automated clinical translation unavailable. Panel tone: {tone or 'unknown'}; "
            f"biome: {biome or 'unknown'}. Narrative cue: {nar or 'n/a'}…"
        ),
        "therapeutic_modality": "unspecified",
        "behavioral_indicators": [],
        "ec_movement": None,
        "recommended_follow_up": "Review latest panel narrative with client in session.",
    }


class ClinicalTranslationEngine:
    """
    Translates between narrative (client-facing) and clinical (coach-facing) language
    for the same therapeutic event.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def translate_panel_to_clinical(self, panel_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Given an SSE panel's generation metadata, produce a structured clinical summary for the coach.
        """
        try:
            from app.sse.llm_fallback import chat_completion_with_fallback
        except ImportError:
            from sse.llm_fallback import chat_completion_with_fallback  # type: ignore

        user_blob = {
            "generation_prompt": (panel_metadata.get("generation_prompt") or "")[:2500],
            "narrative_text": (panel_metadata.get("narrative_text") or "")[:2500],
            "archetype_hint": (panel_metadata.get("archetype_hint") or "")[:500],
            "quest_context": (panel_metadata.get("quest_context") or "")[:800],
            "therapeutic_intent": (panel_metadata.get("therapeutic_intent") or "")[:500],
            "biome": (panel_metadata.get("biome") or "")[:200],
            "panel_tone": (panel_metadata.get("panel_tone") or "")[:120],
        }
        _obs = panel_metadata.get("session_observations") or panel_metadata.get("multimodal") \
            or panel_metadata.get("longitudinal_patterns")
        if _obs:
            try:
                user_blob["session_observations"] = json.dumps(_obs, ensure_ascii=False)[:1500]
            except Exception:
                user_blob["session_observations"] = str(_obs)[:1500]
        messages = [
            {"role": "system", "content": _SYSTEM_PANEL},
            {"role": "user", "content": json.dumps(user_blob, ensure_ascii=False)},
        ]
        raw = await chat_completion_with_fallback(messages, max_tokens=450, temperature=0.35)
        parsed = _parse_json_object(raw or "")
        if not parsed:
            return _fallback_from_metadata(panel_metadata)

        out: Dict[str, Any] = {
            "clinical_summary": str(parsed.get("clinical_summary") or "").strip(),
            "therapeutic_modality": str(parsed.get("therapeutic_modality") or "").strip() or "unspecified",
            "behavioral_indicators": parsed.get("behavioral_indicators") or [],
            "ec_movement": parsed.get("ec_movement"),
            "recommended_follow_up": parsed.get("recommended_follow_up"),
        }
        if not isinstance(out["behavioral_indicators"], list):
            out["behavioral_indicators"] = [str(out["behavioral_indicators"])]
        else:
            out["behavioral_indicators"] = [str(x) for x in out["behavioral_indicators"][:12]]
        if out["ec_movement"] is not None and not isinstance(out["ec_movement"], dict):
            out["ec_movement"] = None
        if out["recommended_follow_up"] is not None:
            out["recommended_follow_up"] = str(out["recommended_follow_up"]).strip() or None
        if not out["clinical_summary"]:
            return _fallback_from_metadata(panel_metadata)
        return out

    async def translate_event_to_narrative(self, clinical_event: Dict[str, Any]) -> str:
        """
        Given a clinical event (assessment result, risk change, etc.), produce mythic narrative for the client.
        """
        try:
            from app.sse.llm_fallback import chat_completion_with_fallback
        except ImportError:
            from sse.llm_fallback import chat_completion_with_fallback  # type: ignore

        messages = [
            {"role": "system", "content": _SYSTEM_EVENT},
            {"role": "user", "content": json.dumps(clinical_event, ensure_ascii=False)[:4000]},
        ]
        raw = await chat_completion_with_fallback(messages, max_tokens=200, temperature=0.65)
        text = (raw or "").strip()
        if text:
            return text.split("\n")[0].strip()[:800]
        return (
            "The path shifts slightly ahead—something in the landscape remembers you, "
            "even when the way is unclear."
        )


async def enrich_after_panel_generation(
    db_pool,
    user_id: str,
    panel_id: Optional[str],
    panel_metadata: Dict[str, Any],
    delivery_log_id: Optional[str] = None,
) -> None:
    """
    Run clinical translation and persist to sse_panel_log and/or sse_delivery_generation_log.
    Safe to call with only delivery_log_id (batch pipeline) or only panel_id (Thera-World journey).
    """
    if not db_pool:
        return
    try:
        eng = ClinicalTranslationEngine(db_pool)
        result = await eng.translate_panel_to_clinical(panel_metadata)
        payload = json.dumps(result, ensure_ascii=False)
        async with db_pool.acquire() as conn:
            if panel_id:
                await conn.execute(
                    "UPDATE sse_panel_log SET clinical_translation = $1 WHERE panel_id = $2::uuid",
                    payload,
                    panel_id,
                )
            if delivery_log_id:
                await conn.execute(
                    "UPDATE sse_delivery_generation_log SET clinical_translation = $1 WHERE log_id = $2::uuid",
                    payload,
                    delivery_log_id,
                )
    except Exception as e:
        logger.warning("enrich_after_panel_generation failed for user=%s: %s", user_id, e)
