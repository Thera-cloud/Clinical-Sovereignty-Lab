"""SSE Sovereign Journey panel context for Little Nate chat.

When a client taps Ask Nate on a journey panel, inject character/theme
explanation so LN can describe why crystals surfaced a core character.
"""

from __future__ import annotations

import json
import re
from typing import Any

_SSE_PANEL_REF_RE = re.compile(r"\[SSE Panel:([a-fA-F0-9\-]+)\]", re.I)
_STORY_PANEL_LEGACY_RE = re.compile(r"\[Story Panel:[^\]]*\]\s*", re.I)

# Client-facing memory → character map (grouped themes per manifestation).
CHARACTER_THEME_GUIDE: dict[str, dict[str, Any]] = {
    "Serpent": {
        "themes": [
            "worry", "shame", "rage", "control", "bitterness", "lies",
            "anxiety", "fear", "anger", "deception", "resentment",
        ],
        "mythic": (
            "The Serpent is conditional love that cannot see its own face — "
            "doubt, control, and old pain whispering from behind the mirror, "
            "not evil, but love turned inward and afraid."
        ),
    },
    "Mirror": {
        "themes": ["bonding", "trust", "love", "enmeshment", "attachment", "codependency"],
        "mythic": (
            "The Mirror holds how we attach — bonds tested, reflections that drift "
            "apart and return, the space where two loves learn they are one and separate."
        ),
    },
    "Reflection": {
        "themes": [
            "identity", "grief", "loss", "boundaries", "self-worth",
            "abandonment", "rejection", "who am I",
        ],
        "mythic": (
            "Reflection asks who you are becoming — grief, empty places, and the "
            "slow work of boundaries that protect without walling love out."
        ),
    },
    "Holy Spirit": {
        "themes": [
            "hope", "faith", "numbness", "forgiveness", "spirit",
            "depression", "spiritual",
        ],
        "mythic": (
            "Holy Spirit is presence without measurement — dawn light after gray "
            "skies, forgiveness that washes the road, hope that does not demand proof."
        ),
    },
    "Curiosity": {
        "themes": [
            "curiosity", "growth", "insight", "loneliness", "opening up",
            "wonder", "discovery", "vulnerability",
        ],
        "mythic": (
            "Curiosity is the part that turns toward what is not yet known — "
            "growth, wonder, and the courage to open a door even when alone."
        ),
    },
    "Pride/Shame": {
        "themes": ["guilt", "trauma", "perfectionism", "never good enough"],
        "mythic": (
            "Pride/Shame is the split between warm and cold light — carrying too much, "
            "trauma knitting slowly, the ache of never feeling good enough."
        ),
    },
}


def _infer_character_from_narrative(narrative: str) -> str:
    """Delivery-runtime panels store narrative but not character_manifest — infer from text."""
    text = (narrative or "").strip()
    if not text:
        return "Mirror"
    lower = text.lower()
    # Longer / multi-word names first to avoid partial matches.
    ordered = [
        "Holy Spirit",
        "Pride/Shame",
        "Serpent",
        "Reflection",
        "Curiosity",
        "Mirror",
    ]
    for name in ordered:
        if name == "Pride/Shame":
            if "pride" in lower or "shame" in lower:
                return name
        elif name.lower() in lower:
            return name
    for name in CHARACTER_THEME_GUIDE:
        if name.lower() in lower:
            return name
    return "Mirror"


def _refresh_r2_presigned(url: str | None) -> str | None:
    """Re-sign expired R2 presigned URLs before backend image fetch (journey feed does this for clients)."""
    if not url:
        return url
    try:
        from urllib.parse import unquote, urlparse

        from app.sse.infrastructure.r2_storage import _R2_BUCKET, presigned_url as _presign

        parsed = urlparse(url.split("?")[0])
        path = unquote(parsed.path.lstrip("/"))
        bucket_prefix = f"{_R2_BUCKET}/"
        key = path[len(bucket_prefix):] if path.startswith(bucket_prefix) else path
        if not key:
            return url
        return _presign(key) or url
    except Exception as exc:
        print(f">>> [SSE PANEL] R2 presign refresh skipped: {type(exc).__name__}: {exc}")
        return url


def _member_ids(profile: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("hardware_id", "username", "id", "user_id"):
        value = str(profile.get(key) or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _parse_crystal_meta(raw: Any) -> tuple[list[str], list[str]]:
    """Return (themes, domains) from sse_panel_log.crystal_domains_used."""
    if raw is None:
        return [], []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [], []
    if isinstance(raw, list):
        return [], [str(x) for x in raw if x]
    if isinstance(raw, dict):
        themes = [str(x) for x in (raw.get("themes") or []) if x]
        domains = [str(x) for x in (raw.get("domains") or raw.get("top_domains") or []) if x]
        return themes, domains
    return [], []


def _format_theme_map() -> str:
    lines = ["[MEMORY → CORE CHARACTER MAP — use when explaining panels]"]
    for name, info in CHARACTER_THEME_GUIDE.items():
        theme_list = ", ".join(info["themes"][:8])
        if len(info["themes"]) > 8:
            theme_list += ", …"
        lines.append(f"- When memory often speaks of: {theme_list} → Core character: {name}")
    return "\n".join(lines)


def _format_reply_therapy_snapshot(rt: Any) -> str:
    if not rt or not isinstance(rt, dict):
        return "[REPLY THERAPY 3+3+3] No corrective emotional experience snapshot on file yet."
    themes = rt.get("themes") or {}
    if not isinstance(themes, dict) or not themes:
        return "[REPLY THERAPY 3+3+3] Tracker initialized; no themed CEE clusters recorded yet."
    lines = ["[REPLY THERAPY 3+3+3 — corrective emotional experience clusters]"]
    active = rt.get("active_reply_theme")
    if active:
        lines.append(f"- Active reply theme (threshold met): {active}")
    for name, td in sorted(themes.items(), key=lambda x: -(
        (x[1].get("mismatch_count") or 0) + (x[1].get("reconsolidation_count") or 0)
    ))[:4]:
        if not isinstance(td, dict):
            continue
        mc = td.get("mismatch_count") or 0
        rc = td.get("reconsolidation_count") or 0
        ec = td.get("evocative_recall_count") or 0
        flag = " [3+3+3 threshold met]" if td.get("threshold_met") else ""
        lines.append(
            f"- {name}: mismatch={mc}, reconsolidation={rc}, evocative_recall={ec}{flag}"
        )
        preview = (td.get("mismatch_events") or td.get("reconsolidation_events") or [])
        if preview and isinstance(preview, list):
            last = preview[-1]
            if isinstance(last, dict) and last.get("preview"):
                lines.append(f"  recent: \"{str(last['preview'])[:120]}\"")
    lines.append(
        "Use only when relevant: frame as building corrective emotional experiences toward "
        "memory reconsolidation — never as scores or homework."
    )
    return "\n".join(lines)


def _format_chat_threads(rows: list[Any]) -> str:
    if not rows:
        return "[RECENT CHAT — near experience] No recent chat threads in database for this client."
    lines = ["[RECENT CHAT — near experience threads LN should cite in reasoning]"]
    for r in reversed(rows):
        ts = r.get("created_at")
        ts_str = ts.strftime("%b %d") if ts and hasattr(ts, "strftime") else ""
        u = (r.get("user_text") or "").strip()[:220]
        if u:
            lines.append(f"- [{ts_str}] Client: {u}")
    return "\n".join(lines)


def _format_crystal_excerpts(rows: list[Any]) -> str:
    if not rows:
        return "[CRYSTAL HISTORY — far memory] No matching crystal excerpts found."
    lines = ["[CRYSTAL HISTORY — far memory strands that often speak for this client]"]
    for r in rows:
        conf = r.get("confidence")
        conf_s = f"{float(conf):.2f}" if conf is not None else "?"
        text = (r.get("crystal_text") or "").strip()[:280]
        domain = r.get("domain") or "general"
        lines.append(f"- ({domain}, conf={conf_s}) {text}")
    return "\n".join(lines)


def _format_cycle_signals(rows: list[Any]) -> str:
    if not rows:
        return "[CYCLE SIGNALS] No repeating experience cycles detected in the last 30 days."
    lines = ["[CYCLE SIGNALS — patterns LN may link near chat ↔ far memory]"]
    for r in rows:
        domain = r.get("domain") or "unknown"
        period = r.get("detected_period_days") or 0
        conf = r.get("confidence") or 0
        amp = r.get("amplitude") or 0
        lines.append(
            f"- {domain}: ~{float(period):.0f}d period, confidence={float(conf):.2f}, "
            f"amplitude={float(amp):.2f}"
        )
    return "\n".join(lines)


def _build_deep_reflection_protocol(char_name: str) -> str:
    return "\n".join([
        "[SOVEREIGN JOURNEY DEEP REFLECTION PROTOCOL — follow this structure in your reply]",
        "",
        "PURPOSE: The journey image is a memory-evocation tool. It brings FAR crystal memory "
        "into contact with NEAR chat experience so you can walk memory reconsolidation modalities "
        "(linking old themes to what is alive today). The core character manifests because of "
        "what the client is bringing into the space — explain that reasoning explicitly.",
        "",
        "RESPONSE STRUCTURE (warm mythic voice; no internal pipeline names):",
        "",
        "A. What I am noticing (structured reasoning)",
        "   - Cite 2–4 themes from RECENT CHAT with approximate timing.",
        "   - Cite 2–3 excerpts from CRYSTAL HISTORY as far-memory strands.",
        "   - If CYCLE SIGNALS exist, name one repeating pattern and how it touches today's scene.",
        "   - Name what the client is bringing into the space (their words/themes).",
        "",
        "B. Why this core character appeared",
        f"   - Give the one-line memory→character map for {char_name}.",
        f"   - Link explicitly: crystal themes + recent chat → why {char_name} stepped forward.",
        "",
        "C. What is shaping my reasoning",
        "   - Name 2–3 specific evidence pieces from the sections above (quote short snippets).",
        "   - If REPLY THERAPY 3+3+3 data is present, mention corrective emotional experience "
        "progress only in human terms (mismatch → reconsolidation → evocative recall), not counts.",
        "",
        "D. SIFT exploration (Sense → Image → Feel → Think)",
        "   Offer SIFT as a gentle doorway into the imagery:",
        "   - Sense: what the body notices in the scene (grounding, breath, tension).",
        "   - Image: which symbol or figure calls to them.",
        "   - Feel: emotion beneath the image.",
        "   - Think: meaning they are making — without fixing or diagnosing.",
        "",
        "E. Three focus topics for today",
        "   End with exactly 3 numbered topics drawn from the intersection of crystal themes, "
        "chat history, cycle patterns, and this panel's character. Each topic is for reflection "
        "or journaling today — not tasks or homework.",
        "",
        "F. Optional deeper dive",
        "   Close by offering: if they wish to go further with the imagery and core character "
        "reflections — the memory strands their crystals often speak of — you can walk a fuller "
        "SIFT pass and memory reconsolidation together.",
        "",
        "RULES: Do not invent chat or crystal quotes not in the evidence blocks. "
        "Do not mention panel_sequence, FFT, ODPE, or algorithms. "
        "NPCs/symbols only from the scene narrative. "
        "Never claim a figure is absent if the scene narrative names it.",
    ])


def _build_panel_block(
    row: Any,
    themes: list[str],
    domains: list[str],
    evidence: dict[str, str],
) -> str:
    char_name = (row.get("character_manifest") or "Mirror").strip()
    guide = CHARACTER_THEME_GUIDE.get(char_name, CHARACTER_THEME_GUIDE["Mirror"])
    theme_line = ", ".join(themes[:6]) if themes else "(theme snapshot not stored for this panel)"
    domain_line = ", ".join(domains[:4]) if domains else "n/a"
    narrative = (row.get("narrative_text") or "").strip()
    biome = (row.get("biome") or "").replace("_", " ")
    tone = row.get("panel_tone") or ""
    generated = row.get("generated_at")
    gen_str = generated.isoformat() if generated and hasattr(generated, "isoformat") else str(generated or "")

    parts = [
        "[SOVEREIGN JOURNEY PANEL — client asked about this image]",
        _format_theme_map(),
        "",
        f"THIS PANEL ({gen_str}):",
        f"- Core character manifested: {char_name}",
        f"- Crystal themes that drove this panel: {theme_line}",
        f"- Crystal domain tags (secondary): {domain_line}",
        f"- Biome: {biome or 'unknown'} | Tone: {tone or 'unknown'}",
        f"- Scene narrative: {narrative[:1200] if narrative else 'n/a'}",
        "- When the client asks about symbols/characters, describe every figure named in the "
        "scene narrative (including NPCs such as Cartographer, Archivist, Serpent, etc.).",
        "",
        f"MYTHIC MEANING OF {char_name.upper()}:",
        guide["mythic"],
        "",
        evidence.get("chat", ""),
        "",
        evidence.get("crystals", ""),
        "",
        evidence.get("cycles", ""),
        "",
        evidence.get("reply_therapy", ""),
        "",
        _build_deep_reflection_protocol(char_name),
    ]
    return "\n".join(parts)


async def _gather_therapeutic_evidence(
    db_pool, ids: list[str], themes: list[str]
) -> dict[str, str]:
    """Fetch near chat, far crystals, cycles, and Reply Therapy snapshot for panel explain."""
    out = {
        "chat": "[RECENT CHAT — near experience] (unavailable)",
        "crystals": "[CRYSTAL HISTORY — far memory] (unavailable)",
        "cycles": "[CYCLE SIGNALS] (unavailable)",
        "reply_therapy": "[REPLY THERAPY 3+3+3] (unavailable)",
    }
    if not db_pool or not ids:
        return out
    try:
        chat_rows = await db_pool.fetch(
            """
            SELECT user_text, ai_text, created_at
            FROM conversation_history
            WHERE user_id = ANY($1::text[])
              AND LENGTH(COALESCE(user_text, '')) > 10
            ORDER BY created_at DESC
            LIMIT 10
            """,
            ids,
        )
        out["chat"] = _format_chat_threads([dict(r) for r in chat_rows])
    except Exception as exc:
        print(f">>> [SSE PANEL] Chat history fetch skipped: {type(exc).__name__}: {exc}")

    user_uuid = None
    try:
        user_uuid = await db_pool.fetchval(
            """
            SELECT id FROM users
            WHERE hardware_id = ANY($1::text[]) OR username = ANY($1::text[])
            LIMIT 1
            """,
            ids,
        )
    except Exception as exc:
        print(f">>> [SSE PANEL] User UUID lookup skipped: {type(exc).__name__}: {exc}")

    if user_uuid:
        try:
            theme_patterns = [f"%{t}%" for t in themes[:6] if t]
            if theme_patterns:
                crystal_rows = await db_pool.fetch(
                    """
                    SELECT crystal_text, domain, confidence, created_at
                    FROM nate_intelligence_crystals
                    WHERE (user_id = $1::uuid OR user_id IS NULL)
                      AND superseded_by IS NULL
                      AND scope != 'archived'
                      AND crystal_text ILIKE ANY($2::text[])
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT 6
                    """,
                    str(user_uuid),
                    theme_patterns,
                )
            else:
                crystal_rows = await db_pool.fetch(
                    """
                    SELECT crystal_text, domain, confidence, created_at
                    FROM nate_intelligence_crystals
                    WHERE (user_id = $1::uuid OR user_id IS NULL)
                      AND superseded_by IS NULL
                      AND scope != 'archived'
                    ORDER BY created_at DESC
                    LIMIT 6
                    """,
                    str(user_uuid),
                )
            out["crystals"] = _format_crystal_excerpts([dict(r) for r in crystal_rows])
        except Exception as exc:
            print(f">>> [SSE PANEL] Crystal fetch skipped: {type(exc).__name__}: {exc}")

    try:
        cycle_rows = await db_pool.fetch(
            """
            SELECT domain, detected_period_days, amplitude, confidence, detected_at
            FROM cycle_detections
            WHERE user_id = ANY($1::text[])
              AND detected_at > NOW() - INTERVAL '30 days'
            ORDER BY confidence DESC
            LIMIT 5
            """,
            ids,
        )
        out["cycles"] = _format_cycle_signals([dict(r) for r in cycle_rows])
    except Exception as exc:
        print(f">>> [SSE PANEL] Cycle fetch skipped: {type(exc).__name__}: {exc}")

    try:
        rt_row = await db_pool.fetchrow(
            """
            SELECT cm.nevedal_state->'reply_therapy' AS reply_therapy
            FROM client_metrics cm
            JOIN users u ON u.id = cm.user_id
            WHERE u.hardware_id = ANY($1::text[]) OR u.username = ANY($1::text[])
            ORDER BY cm.updated_at DESC
            LIMIT 1
            """,
            ids,
        )
        rt_raw = rt_row.get("reply_therapy") if rt_row else None
        if isinstance(rt_raw, str):
            try:
                rt_raw = json.loads(rt_raw)
            except json.JSONDecodeError:
                rt_raw = None
        out["reply_therapy"] = _format_reply_therapy_snapshot(rt_raw)
    except Exception as exc:
        print(f">>> [SSE PANEL] Reply therapy fetch skipped: {type(exc).__name__}: {exc}")

    return out


async def _r2_url_to_data_url(url: str) -> str | None:
    if not url or not url.startswith("http"):
        return None
    url = _refresh_r2_presigned(url) or url
    try:
        import asyncio
        import base64

        import httpx

        async def _fetch() -> bytes | None:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code != 200 or not resp.content:
                    return None
                return resp.content

        data = await asyncio.to_thread(_fetch)
        if not data or len(data) > 4_000_000:
            return None
        ctype = "image/png"
        lower = url.split("?")[0].lower()
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            ctype = "image/jpeg"
        elif lower.endswith(".webp"):
            ctype = "image/webp"
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{ctype};base64,{b64}"
    except Exception as exc:
        print(f">>> [SSE PANEL] Image fetch skipped: {type(exc).__name__}: {exc}")
        return None


async def build_sse_panel_chat_context(
    db_pool, profile: dict[str, Any], user_text: str
) -> tuple[str, str, str | None]:
    """Return (updated_user_text, context_block, optional_image_data_url)."""
    if not db_pool or not profile or not user_text:
        return user_text, "", None

    match = _SSE_PANEL_REF_RE.search(user_text)
    legacy = bool(_STORY_PANEL_LEGACY_RE.search(user_text)) if not match else False
    if not match and not legacy:
        return user_text, "", None

    ids = _member_ids(profile)
    if not ids:
        return user_text, "", None

    row = None
    if match:
        panel_id = match.group(1)
        try:
            row = await db_pool.fetchrow(
                """
                SELECT panel_id, panel_type, r2_url, narrative_text, biome,
                       character_manifest, panel_tone, crystal_domains_used, generated_at
                FROM sse_panel_log
                WHERE panel_id = $1::uuid AND user_id = ANY($2::text[])
                """,
                panel_id,
                ids,
            )
        except Exception as exc:
            print(f">>> [SSE PANEL] Panel lookup failed: {type(exc).__name__}: {exc}")
            return user_text, "", None
        if not row:
            # Journey feed also serves delivery-runtime artifacts (weekly clips,
            # monthly recaps, panels) whose id is a log_id, not a panel_id.
            try:
                drow = await db_pool.fetchrow(
                    """
                    SELECT log_id, generation_type, r2_url,
                           COALESCE(NULLIF(btrim(client_narrative_text), ''), '') AS client_narrative_text,
                           storyboard_id, generated_at
                    FROM sse_delivery_generation_log
                    WHERE log_id = $1::uuid AND user_id = ANY($2::text[])
                    """,
                    panel_id,
                    ids,
                )
                if drow:
                    narrative = (drow.get("client_narrative_text") or "").strip()
                    row = {
                        "panel_id": str(drow.get("log_id")),
                        "panel_type": drow.get("generation_type") or "panel",
                        "source_type": "delivery",
                        "r2_url": drow.get("r2_url"),
                        "narrative_text": narrative,
                        "biome": drow.get("storyboard_id") or "",
                        "character_manifest": _infer_character_from_narrative(narrative),
                        "panel_tone": drow.get("generation_type") or "",
                        "crystal_domains_used": None,
                        "generated_at": drow.get("generated_at"),
                    }
            except Exception as exc:
                print(f">>> [SSE PANEL] Delivery lookup skipped: {type(exc).__name__}: {exc}")
        user_text = _SSE_PANEL_REF_RE.sub(
            "(asking about my Sovereign Journey story panel image)", user_text, count=1
        ).strip()
    else:
        user_text = _STORY_PANEL_LEGACY_RE.sub(
            "(asking about my Sovereign Journey story panel image) ", user_text, count=1
        ).strip()

    if not row:
        evidence = await _gather_therapeutic_evidence(db_pool, ids, [])
        ctx = "\n".join([
            "[SOVEREIGN JOURNEY PANEL — client asked about a story image]",
            _format_theme_map(),
            "",
            evidence.get("chat", ""),
            "",
            evidence.get("crystals", ""),
            "",
            evidence.get("cycles", ""),
            "",
            evidence.get("reply_therapy", ""),
            "",
            _build_deep_reflection_protocol("Mirror"),
            "",
            "Panel record was not resolved. Still follow the DEEP REFLECTION PROTOCOL using "
            "evidence above and the client's message.",
        ])
        return user_text, ctx, None

    themes, domains = _parse_crystal_meta(row.get("crystal_domains_used"))
    evidence = await _gather_therapeutic_evidence(db_pool, ids, themes)
    ctx = _build_panel_block(row, themes, domains, evidence)
    image_data_url = await _r2_url_to_data_url(row.get("r2_url") or "")
    if image_data_url:
        ctx += "\n\n[SSE PANEL IMAGE] The journey panel image is attached as a vision block."
    return user_text, ctx, image_data_url
