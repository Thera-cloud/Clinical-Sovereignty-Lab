"""
F-Code Suggestion Engine — Azure OpenAI-powered ICD-10-CM F-code suggestions.

Little Nate analyzes client data at milestone markers (30, 60, 90 days, 6 months, 12+ months)
and suggests up to 4 ICD-10-CM F-codes. The coach reviews and assigns the actual codes.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("nate.fcode_engine")

MILESTONE_WINDOWS = ["30d", "60d", "90d", "6mo", "12mo"]

MILESTONE_DAYS = {
    "30d": 30,
    "60d": 60,
    "90d": 90,
    "6mo": 180,
    "12mo": 365,
}


class FCodeEngine:
    """AI-powered F-code suggestion engine using client session/metric data."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self._endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self._api_key = os.getenv("AZURE_API_KEY", "")
        self._deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

    async def get_suggestions(self, client_id: str, window: str = "30d") -> List[Dict]:
        """Generate F-code suggestions for a client at the given milestone window."""
        if window not in MILESTONE_WINDOWS:
            return []
        if not self.db_pool:
            return []

        context = await self._gather_client_context(client_id, window)
        if not context:
            return []

        fcode_ref = await self._get_fcode_reference()
        suggestions = await self._ai_suggest(context, fcode_ref, window)
        return suggestions

    async def assign_fcodes(self, client_id: str, coach_id: str, fcodes: List[Dict]) -> List[Dict]:
        """Coach assigns F-codes (up to 4) to a client."""
        if not self.db_pool or not fcodes:
            return []

        assigned = []
        async with self.db_pool.acquire() as conn:
            for fc in fcodes[:4]:
                code = fc.get("code", "")
                description = fc.get("description", "")
                window = fc.get("milestone_window", "30d")
                notes = fc.get("notes", "")

                try:
                    row = await conn.fetchrow(
                        """INSERT INTO client_fcodes (client_id, coach_id, fcode, fcode_description,
                            milestone_window, source, confidence_score, active, notes)
                           VALUES ($1, $2, $3, $4, $5, 'coach', 1.0, TRUE, $6)
                           RETURNING id, fcode, fcode_description, assigned_at""",
                        client_id, coach_id, code, description, window, notes,
                    )
                    if row:
                        assigned.append({
                            "id": str(row["id"]),
                            "fcode": row["fcode"],
                            "description": row["fcode_description"],
                            "assigned_at": row["assigned_at"].isoformat(),
                        })
                except Exception as e:
                    logger.warning("FCodeEngine: failed to assign %s to %s: %s", code, client_id, e)

        return assigned

    async def get_history(self, client_id: str) -> Dict:
        """Full history of assigned + suggested codes for a client."""
        if not self.db_pool:
            return {"assigned": [], "suggestions": []}

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, fcode, fcode_description, assigned_at, milestone_window,
                          source, confidence_score, active, notes
                   FROM client_fcodes WHERE client_id = $1
                   ORDER BY assigned_at DESC""",
                client_id,
            )

        assigned = []
        suggestions = []
        for r in rows:
            entry = {
                "id": str(r["id"]),
                "fcode": r["fcode"],
                "description": r["fcode_description"],
                "assigned_at": r["assigned_at"].isoformat() if r["assigned_at"] else None,
                "milestone_window": r["milestone_window"],
                "confidence_score": r["confidence_score"],
                "active": r["active"],
                "notes": r["notes"],
            }
            if r["source"] == "coach":
                assigned.append(entry)
            else:
                suggestions.append(entry)

        return {"assigned": assigned, "suggestions": suggestions}

    async def get_compare(self, client_id: str) -> Dict:
        """Side-by-side comparison of coach-assigned vs Nate-suggested over time."""
        history = await self.get_history(client_id)
        return {
            "coach_assigned": history["assigned"],
            "nate_suggestions": history["suggestions"],
            "agreement_rate": self._calc_agreement(history["assigned"], history["suggestions"]),
        }

    async def get_family_correlations(self, family_id: str) -> List[Dict]:
        """Cross-reference F-codes across family members for transgenerational patterns."""
        if not self.db_pool:
            return []

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT u.username, u.profile_data->>'name' as name,
                          cf.fcode, cf.fcode_description, cf.source, cf.active
                   FROM client_fcodes cf
                   JOIN users u ON u.username = cf.client_id
                   WHERE u.profile_data->>'family_id' = $1 AND cf.active = TRUE
                   ORDER BY u.username, cf.fcode""",
                family_id,
            )

        family_codes: Dict[str, List[Dict]] = {}
        for r in rows:
            name = r["name"] or r["username"]
            if name not in family_codes:
                family_codes[name] = []
            family_codes[name].append({
                "fcode": r["fcode"],
                "description": r["fcode_description"],
                "source": r["source"],
            })

        correlations = []
        all_codes = set()
        for member_codes in family_codes.values():
            for c in member_codes:
                all_codes.add(c["fcode"][:3])

        for code_prefix in all_codes:
            members_with = []
            for member, codes in family_codes.items():
                if any(c["fcode"].startswith(code_prefix) for c in codes):
                    members_with.append(member)
            if len(members_with) > 1:
                correlations.append({
                    "code_category": code_prefix,
                    "members_affected": members_with,
                    "count": len(members_with),
                    "potential_transgenerational": True,
                })

        return correlations

    async def _gather_client_context(self, client_id: str, window: str) -> Optional[Dict]:
        """Gather client data for AI analysis."""
        if not self.db_pool:
            return None

        async with self.db_pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT id, profile_data FROM users WHERE username = $1", client_id
            )
            if not user_row:
                return None

            profile = user_row["profile_data"]
            if isinstance(profile, str):
                profile = json.loads(profile)

            days = MILESTONE_DAYS.get(window, 30)

            user_id = user_row.get("id")
            metrics = await conn.fetch(
                """SELECT c_emo, p_ent, t_tunnel, gamma_env, cee_window, recorded_at
                   FROM nevedal_metrics WHERE user_id = $1
                   AND recorded_at > NOW() - INTERVAL '1 day' * $2::int
                   ORDER BY recorded_at DESC LIMIT 20""",
                user_id, days,
            )

            sessions = await conn.fetch(
                """SELECT session_type, status, duration_seconds, created_at FROM sessions
                   WHERE user_id = $1
                   AND created_at > NOW() - INTERVAL '1 day' * $2::int
                   ORDER BY created_at DESC LIMIT 10""",
                user_id, days,
            )

        return {
            "client_id": client_id,
            "window": window,
            "profile": {
                "name": profile.get("name", ""),
                "attachment_style": profile.get("attachment_style", ""),
                "crisis_perception": profile.get("crisis_perception_baseline", ""),
                "shame_index": profile.get("shame_index", ""),
                "reactivity_profile": profile.get("reactivity_profile", {}),
                "legacy_patterns": profile.get("legacy_patterns", {}),
            },
            "metrics": [
                {
                    "c_emo": float(m["c_emo"]) if m["c_emo"] else 0,
                    "p_ent": float(m["p_ent"]) if m["p_ent"] else 0,
                    "cee_window": bool(m["cee_window"]),
                }
                for m in metrics
            ],
            "session_count": len(sessions),
            "session_types": [
                s["session_type"] or "unknown" for s in sessions
            ],
        }

    async def _get_fcode_reference(self) -> List[Dict]:
        """Load F-code reference table for AI context."""
        if not self.db_pool:
            return []

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT code, description, category, common_symptoms FROM fcode_reference ORDER BY code LIMIT 100"
            )

        return [
            {
                "code": r["code"],
                "description": r["description"],
                "category": r["category"],
                "symptoms": r["common_symptoms"] or [],
            }
            for r in rows
        ]

    async def _ai_suggest(self, context: Dict, fcode_ref: List[Dict], window: str) -> List[Dict]:
        """Use Azure OpenAI to generate F-code suggestions."""
        try:
            import httpx

            if not self._endpoint or not self._api_key:
                return []

            url = f"https://{self._endpoint}/openai/deployments/{self._deployment}/chat/completions?api-version=2024-06-01"

            ref_text = "\n".join(
                f"  {r['code']}: {r['description']} ({r['category']}) — symptoms: {', '.join(r['symptoms'][:3])}"
                for r in fcode_ref[:60]
            )

            system_prompt = f"""You are a clinical assessment AI assistant (Little Nate). Based on the client data provided, suggest up to 4 ICD-10-CM F-codes that may apply.

AVAILABLE F-CODES:
{ref_text}

RULES:
- Suggest codes based on observable patterns, NOT diagnoses
- Label these as "AI Considerations" — the certified coach makes final assignments
- Include a confidence score (0.0-1.0) for each suggestion
- Consider the milestone window ({window}) — shorter windows = lower confidence
- Return ONLY valid JSON array

Return format:
[{{"code": "F41.1", "description": "Generalized anxiety disorder", "confidence": 0.75, "reasoning": "Elevated worry patterns across 6 sessions"}}]"""

            user_msg = json.dumps(context, default=str)

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json={"messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ], "max_completion_tokens": 800},
                    headers={"api-key": self._api_key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                    suggestions = json.loads(content)

                    if self.db_pool:
                        async with self.db_pool.acquire() as conn:
                            for s in suggestions[:4]:
                                try:
                                    await conn.execute(
                                        """INSERT INTO client_fcodes (client_id, coach_id, fcode, fcode_description,
                                              milestone_window, source, confidence_score, active, notes)
                                           VALUES ($1, 'nate_ai', $2, $3, $4, 'nate_suggestion', $5, FALSE, $6)""",
                                        context["client_id"],
                                        s.get("code", ""),
                                        s.get("description", ""),
                                        window,
                                        s.get("confidence", 0.5),
                                        s.get("reasoning", ""),
                                    )
                                except Exception as e:
                                    logger.warning("FCodeEngine: failed to store suggestion: %s", e)

                    return suggestions[:4]

        except Exception as e:
            logger.warning("FCodeEngine: AI suggestion failed: %s", e)

        return []

    def _calc_agreement(self, assigned: List[Dict], suggestions: List[Dict]) -> float:
        """Calculate agreement rate between coach and AI suggestions."""
        if not assigned or not suggestions:
            return 0.0
        assigned_codes = {a["fcode"][:3] for a in assigned}
        suggested_codes = {s["fcode"][:3] for s in suggestions}
        if not suggested_codes:
            return 0.0
        overlap = assigned_codes & suggested_codes
        return round(len(overlap) / len(suggested_codes), 2)
