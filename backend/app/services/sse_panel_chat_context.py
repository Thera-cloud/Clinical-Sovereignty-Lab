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
_PANEL_FOLLOWUP_RE = re.compile(
    r"(?:focus topics?|three topics|3 topics|got cut off|cut off|"
    r"post them again|story panel|journey (?:image|panel)|"
    r"sovereign journey|sift(?:\s+pass)?)",
    re.I,
)
_SHORT_PANEL_ACK_RE = re.compile(
    r"^(?:sure|yes|yeah|yep|ok|okay|please|go on|continue|and then\??|"
    r"for me or for you\??|what(?:'s| is) next\??|"
    r"can you (?:repeat|repost|list) (?:them|that|those)\??)\s*[.!]?\s*$",
    re.I,
)
_COMPLETE_FOCUS_THREE_RE = re.compile(
    r"(?:^|\n)\s*1[\.)]\s+\S.{8,}?(?:\n)\s*2[\.)]\s+\S.{8,}?(?:\n)\s*3[\.)]\s+\S.{8,}",
    re.I | re.S,
)
_FOCUS_HEADING_RE = re.compile(
    r"(?:For today,\s*)?(?:here are )?(?:the )?three focus topics\b",
    re.I,
)
_STOCK_PANEL_CLOSER_RE = re.compile(
    r"without needing to fix it|"
    r"body-sense or image in the scene that wants a name|"
    r"one thread from recent conversation this image is holding|"
    r"i(?:['’]m| am) right here with you|"
    r"let(?:['’]s| us) talk about these figures together|"
    r"three focus topics for reflection or journaling",
    re.I,
)
_CUTOFF_ASK_RE = re.compile(
    r"(?:focus topics?|three topics|3 topics|got cut off|cut off|"
    r"post them again|list (?:them|those|the topics))",
    re.I,
)

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
    stock_hit = False
    for r in reversed(rows):
        ts = r.get("created_at")
        ts_str = ts.strftime("%b %d") if ts and hasattr(ts, "strftime") else ""
        u = (r.get("user_text") or "").strip()[:220]
        a = (r.get("ai_text") or "").strip()[:180]
        if u:
            lines.append(f"- [{ts_str}] Client: {u}")
        if a:
            lines.append(f"  LN last said (do not copy structure or closer): {a}")
            if _STOCK_PANEL_CLOSER_RE.search(a):
                stock_hit = True
    if stock_hit:
        lines.append(
            "[ANTI-REPEAT] A prior LN panel reply used the stock three-topic closer. "
            "This turn: walk SIFT unique to this scene; no numbered journaling list, "
            "no 'without needing to fix it'."
        )
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


def _sse_panel_contract() -> str:
    return (
        "[SSE PANEL CONTRACT] Sit with THIS image as a new visit. "
        "Name at least two concrete figures, landmarks, or objects from Scene narrative. "
        "Quote a few words from RECENT CHAT and join them to something visible now. "
        "Forbidden stock: 'without needing to fix it'; 'a body-sense or image in the scene "
        "that wants a name'; 'one thread from recent conversation this image is holding'; "
        "'I'm right here with you'; 'Let's talk about these figures together'; "
        "'For today, here are three focus topics for reflection or journaling'. "
        "Walk Sense, Image, Feel, Think on THIS scene (all four). "
        "Do not use A/B/C/E/D section headers or a worksheet outline. "
        "Numbered 1/2/3 journaling prompts only if the client asked for topics or said "
        "they were cut off — and then each line must use nouns from THIS scene."
    )


def focus_topics_complete(text: str) -> bool:
    return bool(_COMPLETE_FOCUS_THREE_RE.search(text or ""))


def sse_should_complete_focus_topics(user_text: str, ctx: str) -> bool:
    """Only backfill topics when the client asked — never on first Go Deeper."""
    if not ctx or "DEEP REFLECTION PROTOCOL" not in ctx:
        return False
    blob = user_text or ""
    return bool(_CUTOFF_ASK_RE.search(blob))


def _ctx_field(ctx: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}:\s*(.+)", ctx or "")
    if not m:
        return ""
    val = m.group(1).strip()
    if not val or val.lower() in ("n/a", "unknown"):
        return ""
    if "not stored" in val.lower():
        return ""
    return val.split("|")[0].strip()


def _first_clause(text: str, max_len: int = 120) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    part = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return part[:max_len].rstrip(" ,;:")


def _last_client_excerpt(ctx: str) -> str:
    hits = re.findall(r"\] Client: (.+)", ctx or "")
    if not hits:
        return ""
    return re.sub(r"\s+", " ", hits[-1].strip())[:90].rstrip(" .")


def _topics_from_ctx(ctx: str) -> list[str]:
    char = _ctx_field(ctx, "Core character manifested") or "the figure in this panel"
    biome = _ctx_field(ctx, "Biome") or "this landscape"
    narrative = _ctx_field(ctx, "Scene narrative")
    scene = _first_clause(narrative) or f"{char} in {biome}"
    themes: list[str] = []
    raw_themes = _ctx_field(ctx, "Crystal themes that drove this panel")
    if raw_themes:
        themes = [
            t.strip()
            for t in raw_themes.split(",")
            if t.strip() and "not stored" not in t.lower() and t.strip() != "n/a"
        ]
    client_line = _last_client_excerpt(ctx)
    theme = themes[0] if themes else "what is stirring"
    t1 = f"Stay with {scene} — what is {char} doing that you have not said out loud?"
    t2 = (
        f"One detail in {biome} that matches {theme} in your body right now."
    )
    if client_line:
        t3 = f'You said "{client_line}" — where does that land in this picture?'
    elif len(themes) > 1:
        t3 = f"How is {themes[1]} different in this scene than the last panel?"
    else:
        t3 = f"What would change if you took one step closer to {char} here?"
    return [t1, t2, t3]


def ensure_three_focus_topics(ai_text: str, ctx: str) -> str:
    """If the model cut off or skipped section E, finish the three numbered topics."""
    text = ai_text or ""
    if focus_topics_complete(text):
        return text
    topics = _topics_from_ctx(ctx)
    block = (
        "\n\nThree threads from this scene:\n"
        f"1. {topics[0]}\n"
        f"2. {topics[1]}\n"
        f"3. {topics[2]}\n"
    )
    heading = _FOCUS_HEADING_RE.search(text)
    if heading:
        return text[: heading.start()].rstrip() + block
    return text.rstrip() + block


def _build_deep_reflection_protocol(char_name: str) -> str:
    return "\n".join([
        _sse_panel_contract(),
        "",
        "[SOVEREIGN JOURNEY DEEP REFLECTION PROTOCOL — unique sitting, not a template]",
        "",
        "PURPOSE: This image is a memory-evocation tool. Join FAR crystal memory to "
        "NEAR chat using what is actually painted in THIS panel — not a generic essay.",
        "",
        "THIS VISIT (warm mythic voice; no pipeline names; no section letters):",
        f"- Open on a concrete detail from Scene narrative or the image, then why {char_name} "
        "is in that spot today (one or two sentences, not a preamble).",
        "- Then walk SIFT as a doorway into THIS scene. All four — unique to what is painted:",
        "  Sense: one body or place detail (ground, breath, texture) tied to a landmark "
        "or object in Scene narrative.",
        f"  Image: which figure or symbol is calling — name {char_name} or another figure "
        "actually in the scene.",
        "  Feel: the emotion under that image, joined to a few quoted words from RECENT CHAT.",
        "  Think: the meaning they are making — no diagnosis, no fixing.",
        "- Close with one invitation to stay with that figure or feeling. "
        "Do not add a numbered 1/2/3 journaling list unless they asked for topics or said they were cut off.",
        "- If RECENT CHAT already contains a numbered 1/2/3 closer from you, do not use "
        "numbered prompts this turn — still walk SIFT, then one new question.",
        "- If the client asked for focus topics or said they were cut off, after SIFT give three "
        f"complete sentences that name {char_name} plus nouns from Scene narrative "
        "and a RECENT CHAT quote. Never the stock journaling trio.",
        "",
        "RULES: Do not invent chat or crystal quotes not in the evidence blocks. "
        "Do not mention panel_sequence, FFT, ODPE, or algorithms. "
        "Stay in Thera-world. You may name companions or landmarks from the "
        "Thera-world concept palette when they belong to this scene. Do not invent a city, "
        "office, or second mythology. "
        "Never claim a figure is absent if the scene narrative names it. "
        "Never copy LN last said.",
    ])


def _neuro_panel_context(row: Any, char_name: str) -> dict[str, Any] | None:
    """QUANTUM-CRYSTAL-ARCH — Neuro region detection without new SELECT columns.

    A panel is Neuro when its biome is a Neuro place AND its core figure is a
    Neuro champion. Returns {place_label, purpose, braid} or None (Origin)."""
    try:
        from app.sse.neuro_scoring import champion_by_name, four_move_braid_block
        from app.sse.thera_world_regions import NEURO_BIOMES, biome_display_name
    except Exception:
        return None
    biome_id = (row.get("biome") or "").strip()
    if biome_id not in NEURO_BIOMES:
        return None
    champ = champion_by_name(char_name)
    if not champ:
        return None
    place = biome_display_name(biome_id)
    change_line = ""
    meta = row.get("panel_metadata") if hasattr(row, "get") else None
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta)
        except Exception:
            meta = {}
    if isinstance(meta, dict):
        change_line = meta.get("change_line") or ""
    try:
        braid = four_move_braid_block(
            place, champ.get("name") or char_name, change_line=change_line,
        )
    except Exception:
        braid = ""
    return {
        "place_label": place,
        "purpose": champ.get("purpose") or "",
        "role": champ.get("role") or "",
        "braid": braid,
    }


def _build_panel_block(
    row: Any,
    themes: list[str],
    domains: list[str],
    evidence: dict[str, str],
) -> str:
    char_name = (row.get("character_manifest") or "Mirror").strip()
    neuro = _neuro_panel_context(row, char_name)
    if neuro:
        guide = {"mythic": neuro["purpose"] or f"{char_name} — {neuro['role']}."}
    else:
        guide = CHARACTER_THEME_GUIDE.get(char_name, CHARACTER_THEME_GUIDE["Mirror"])
    theme_line = ", ".join(themes[:6]) if themes else "(theme snapshot not stored for this panel)"
    domain_line = ", ".join(domains[:4]) if domains else "n/a"
    narrative = (row.get("narrative_text") or "").strip()
    biome = (row.get("biome") or "").replace("_", " ")
    if neuro:
        biome = neuro["place_label"]
    tone = row.get("panel_tone") or ""
    generated = row.get("generated_at")
    gen_str = generated.isoformat() if generated and hasattr(generated, "isoformat") else str(generated or "")

    try:
        from app.sse.thera_world_concepts import format_thera_world_concept_palette
        palette = format_thera_world_concept_palette(
            biome=row.get("biome") or "",
            core_character=char_name,
            quest_goal="",
            mission_target="",
        )
    except Exception:
        palette = ""
    parts = [
        "[SOVEREIGN JOURNEY PANEL — client asked about this image]",
        _sse_panel_contract(),
        _format_theme_map(),
        palette,
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
    if neuro and neuro.get("braid"):
        # Neuro visit: all four lived moves braided in-scene, on top of SIFT.
        parts += ["", neuro["braid"]]
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
                    WHERE ((user_id = $1::uuid AND scope != 'archived')
                        OR (user_id IS NULL AND scope = 'global'))
                      AND superseded_by IS NULL
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
                    WHERE ((user_id = $1::uuid AND scope != 'archived')
                        OR (user_id IS NULL AND scope = 'global'))
                      AND superseded_by IS NULL
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


def _http_get_bytes(url: str) -> bytes | None:
    """Sync GET for asyncio.to_thread — must not be async (coroutine has no len)."""
    import httpx

    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code != 200 or not resp.content:
            return None
        return resp.content


async def _r2_url_to_data_url(url: str) -> str | None:
    if not url or not url.startswith("http"):
        return None
    url = _refresh_r2_presigned(url) or url
    try:
        import asyncio
        import base64

        data = await asyncio.to_thread(_http_get_bytes, url)
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


async def _recent_panel_thread(db_pool, ids: list[str]) -> bool:
    if not db_pool or not ids:
        return False
    try:
        rows = await db_pool.fetch(
            """
            SELECT user_text, ai_text
            FROM conversation_history
            WHERE user_id = ANY($1::text[])
            ORDER BY created_at DESC
            LIMIT 6
            """,
            ids,
        )
    except Exception as exc:
        print(f">>> [SSE PANEL] Follow-up thread check skipped: {type(exc).__name__}: {exc}")
        return False
    for r in rows:
        blob = f"{r.get('user_text') or ''} {r.get('ai_text') or ''}"
        if "Sovereign Journey story panel" in blob or _PANEL_FOLLOWUP_RE.search(blob):
            return True
        if "DEEP REFLECTION" in blob or "focus topics" in blob.lower():
            return True
    return False


async def _latest_journey_panel_row(db_pool, ids: list[str]):
    if not db_pool or not ids:
        return None
    try:
        return await db_pool.fetchrow(
            """
            SELECT panel_id, panel_type, r2_url, narrative_text, biome,
                   character_manifest, panel_tone, crystal_domains_used, generated_at,
                   panel_metadata
            FROM sse_panel_log
            WHERE user_id = ANY($1::text[])
            ORDER BY generated_at DESC NULLS LAST
            LIMIT 1
            """,
            ids,
        )
    except Exception as exc:
        print(f">>> [SSE PANEL] Latest panel lookup skipped: {type(exc).__name__}: {exc}")
        return None


async def build_sse_panel_chat_context(
    db_pool, profile: dict[str, Any], user_text: str
) -> tuple[str, str, str | None]:
    """Return (updated_user_text, context_block, optional_image_data_url)."""
    if not db_pool or not profile or not user_text:
        return user_text, "", None

    match = _SSE_PANEL_REF_RE.search(user_text)
    legacy = bool(_STORY_PANEL_LEGACY_RE.search(user_text)) if not match else False
    ids = _member_ids(profile)
    if not ids:
        return user_text, "", None

    followup = False
    if not match and not legacy:
        followup = bool(_PANEL_FOLLOWUP_RE.search(user_text))
        if not followup and _SHORT_PANEL_ACK_RE.match(user_text.strip()):
            followup = await _recent_panel_thread(db_pool, ids)
        if not followup:
            return user_text, "", None

    row = None
    if match:
        panel_id = match.group(1)
        try:
            row = await db_pool.fetchrow(
                """
                SELECT panel_id, panel_type, r2_url, narrative_text, biome,
                       character_manifest, panel_tone, crystal_domains_used, generated_at,
                       panel_metadata
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

    if followup and not row:
        row = await _latest_journey_panel_row(db_pool, ids)

    if not row:
        evidence = await _gather_therapeutic_evidence(db_pool, ids, [])
        try:
            from app.sse.thera_world_concepts import format_thera_world_concept_palette
            _unresolved_palette = format_thera_world_concept_palette()
        except Exception:
            _unresolved_palette = ""
        ctx = "\n".join([
            "[SOVEREIGN JOURNEY PANEL — client asked about a story image]",
            _format_theme_map(),
            _unresolved_palette,
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
        if followup:
            ctx += (
                "\n\n[SSE PANEL FOLLOW-UP] Continue THIS scene. "
                "If they asked to repost topics, give three new sentences using nouns from "
                "Scene narrative and a RECENT CHAT quote — never the stock journaling trio."
            )
        return user_text, ctx, None

    themes, domains = _parse_crystal_meta(row.get("crystal_domains_used"))
    evidence = await _gather_therapeutic_evidence(db_pool, ids, themes)
    ctx = _build_panel_block(row, themes, domains, evidence)
    image_data_url = await _r2_url_to_data_url(row.get("r2_url") or "")
    if image_data_url:
        ctx += "\n\n[SSE PANEL IMAGE] The journey panel image is attached as a vision block."
    if followup:
        ctx += (
            "\n\n[SSE PANEL FOLLOW-UP] Continue THIS scene. "
            "If they asked to repost topics, give three new sentences using nouns from "
            "Scene narrative and a RECENT CHAT quote — never the stock journaling trio."
        )
    return user_text, ctx, image_data_url
