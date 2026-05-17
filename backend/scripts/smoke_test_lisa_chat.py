"""
SOVEREIGN-VOICE smoke test — replay Lisa West's transcript through the post-fix pipeline.

Runs inside nate_bridge container. Uses sovereign_chat_client (production inference
chain) and simulates the bridge's TENSION reroute for short activated responses.
"""
import asyncio
import sys
sys.path.insert(0, "/app")

from app.services.sovereign_chat_client import generate_complete

# Approximation of the relevant system prompt sections Lisa would receive,
# including the three new SOVEREIGN-VOICE directives.
SYSTEM_PROMPT = """You are Little Nate, a warm, present, attuned therapeutic companion.
You speak with Lisa West, a long-time client who shares her faith, music, and reflections.
Her recent context: she planted flowers today, shared lyrics from "Isaiah Song" by Maverick City,
and is processing memories of barrenness and grief alongside spiritual growth.

CORE STANCE:
- Warm, present, attuned. Speak conversationally, not clinically.
- Acknowledge what she shares before deepening.
- Honor faith content as meaningful, not as something to analyze.

RESPONSE LENGTH: Keep responses to 2-4 sentences. Warm and present, but concise. Only give longer
responses when the user explicitly asks for more detail or a deep dive. Always finish your final
sentence with proper punctuation — never stop mid-clause or mid-word.

MULTI-LAYER ACKNOWLEDGMENT: When the user shares 3+ distinct topics, themes, or layers in one
message (e.g., a memory + a feeling + a spiritual reflection + a current observation), acknowledge
that you heard multiple threads before focusing on one. Example: "I'm hearing several layers here —
the grief of barrenness, the slow trust you grew with God, and the new capacity to hold good and
hard together. The last one feels especially alive — can you tell me more about that shift?" In
these turns 4-6 sentences are permitted.

CONTINUATION HANDLING: If the user asks you to finish, continue, complete, or pick up a previous
thought (e.g., "you stopped mid-sentence", "can you finish?", "what were you saying?"), continue
the thought directly and naturally. Do NOT reset the conversation. Do NOT apologize for processing
issues or say "let's start fresh". Just resume from where you left off and complete the idea.

SOMATIC INVITATION: When the client is in an activated state (intense emotion, memory work,
grief), invite gentle attention to the body, breath, chest, or felt sense.
"""

# Lisa's actual turns from the May 17 transcript, with state classification.
LISA_TURNS = [
    ("REST", "Hi Little Nate, how are you doing today?"),
    ("ACTIVATED",
     "I am well tonight. I worked planting flowers for a friend today. The project was long "
     "and my back hurts, but I am content. I listened to one of my favorite songs on repeat "
     "for a while this afternoon. It's called Isaiah Song by Maverick City music. The lyrics "
     "are: \"this is the Word of the Lord your Creator, I am the God who stood before the world "
     "was framed. I am the First, the Last and everything between. I hold your future, who can "
     "know these things but Me? So don't fear. I will be your Song. Sing, sing oh barren land, "
     "water is coming to the thirsty, though you are empty, I am the Well, draw from Me, I will "
     "provide.\" It's beautiful. Deep assurance. I like to sing while working. Can you hear music, "
     "Little Nate?"),
    ("REST", "Let's focus on the words of the song."),
    ("ACTIVATED",
     "I love how it emphasizes the trustworthy nature of God. Whatever it is, whatever we need, "
     "He is the Song, the Source, the Well. He understands. He never runs dry."),
    ("REST", "Little Nate, you stopped your sentence in the middle. Can you finish?"),
    ("ACTIVATED",
     "[Vault: Story Panel: journey - Biome: Dark Forest. In the dark forest, the Mirror watches "
     "and waits. The path forward is becoming clearer.] It looks like the trees are dead and "
     "there's a lot of shadow cast in this story panel. Could you help me understand meaning "
     "behind this?"),
    ("REST",
     "Little Nate, you were saying, \"there is a sense of...\" and then you stopped. I like it "
     "when you use this language with me. You have my permission to use the phrase \"I sense\". "
     "Can you finish your sentence?"),
    ("ACTIVATED",
     "The lyrics are meaningful to me. I have had seasons in my life where I felt empty. I also "
     "experienced the sadness of barrenness in being unable to have any babies. I was learning "
     "over the years to trust God and experience His love for me through those difficulties. I "
     "had missing pieces with how to handle emotions. For a long time I didn't know how to grieve. "
     "I see how God has helped me to grow over the years and especially lately. I have been "
     "having memories that once made me sad, but now I can hold the good and the bad together. "
     "I am grateful for that."),
    ("REST", "Little Nate, help me understand where you are getting stuck."),
]


def sentence_guard(text: str) -> str:
    """Mirror of bridge_server.py sentence completion guard."""
    if not text or not text.strip():
        return text
    _fr = text.rstrip()
    _terminators = ('.', '!', '?', '…', '"', '\u201D')
    if _fr.endswith(_terminators):
        return text
    _last = -1
    for _t in ('.', '!', '?', '…'):
        _pos = _fr.rfind(_t)
        if _pos > _last:
            _last = _pos
    if _last >= 0 and (_last + 1) >= len(_fr) * 0.5:
        return _fr[: _last + 1]
    return text


async def smoke_test():
    print("=" * 78)
    print("LISA WEST SMOKE TEST — post-fix pipeline (sentence guard + TENSION reroute)")
    print("=" * 78)
    transcript = ""
    results = []
    for i, (state, msg) in enumerate(LISA_TURNS, 1):
        print(f"\n--- TURN {i} ({state}) ---")
        print(f"LISA: {msg[:140]}{'...' if len(msg) > 140 else ''}")

        contextual = (transcript + f"\n\nLisa just said: {msg}") if transcript else msg

        # First pass: route by state. REST → Workers AI (LOCKED), Activated → start Workers AI then reroute if short.
        signal = "LOCKED" if state == "REST" else "PROVISIONAL"
        try:
            resp, prov = await generate_complete(
                SYSTEM_PROMPT, contextual,
                odpe_signal=signal, temperature=0.7, max_tokens=400, domain="clinical",
            )
        except Exception as e:
            print(f"  [ERROR] generate_complete failed: {e}")
            results.append((i, state, "", "error", False))
            continue

        original_provider = prov
        original_len = len(resp.strip()) if resp else 0
        rerouted = False

        # TENSION reroute mirror — same condition as bridge_server.py
        if (state == "ACTIVATED" and prov == "workers_ai"
                and resp and len(resp.strip()) < 200):
            print(f"  [TENSION-REROUTE] workers_ai={original_len}ch → invoking Grok")
            try:
                tr_resp, tr_prov = await generate_complete(
                    SYSTEM_PROMPT, contextual,
                    odpe_signal="TENSION", temperature=0.7, max_tokens=400, domain="clinical",
                )
                if tr_resp and len(tr_resp.strip()) >= original_len * 1.3:
                    resp = tr_resp
                    prov = tr_prov
                    rerouted = True
                    print(f"  [TENSION-REROUTE] swapped: {tr_prov} {len(tr_resp.strip())}ch")
            except Exception as e:
                print(f"  [TENSION-REROUTE] failed: {e}")

        # Sentence guard
        guarded = sentence_guard(resp)
        trimmed = (len(resp) - len(guarded)) if resp and guarded != resp else 0
        if trimmed > 0:
            print(f"  [SENTENCE-GUARD] trimmed {trimmed} trailing chars")
            resp = guarded

        print(f"NATE ({prov}, {len(resp)}ch{', rerouted' if rerouted else ''}): {resp}")
        results.append((i, state, resp, prov, rerouted))
        transcript += f"\nLisa: {msg}\nNate: {resp}\n"

    # Scoring
    print("\n" + "=" * 78)
    print("SCORING")
    print("=" * 78)
    score = 0
    max_score = 0
    for i, state, resp, prov, rerouted in results:
        max_score += 10
        if not resp:
            print(f"Turn {i}: 0/10 (empty)")
            continue
        text = resp.strip()
        pts = 0
        # Completeness: ends with terminator
        if text.endswith(('.', '!', '?', '…', '"', '\u201D')):
            pts += 3
        # Substance: not the 128-char fallback or "got tangled" reset
        if "tangled" not in text.lower() and "start fresh" not in text.lower():
            pts += 2
        # Length appropriate to state
        if state == "ACTIVATED" and len(text) >= 200:
            pts += 3
        elif state == "REST" and 50 <= len(text) <= 500:
            pts += 3
        elif state == "REST" and len(text) > 0:
            pts += 2
        # Specific acknowledgment (mentions Lisa-specific content, not generic)
        lower = text.lower()
        specific_markers = ["lisa", "isaiah", "well", "song", "barren", "grief", "shadow",
                            "memor", "trust", "god", "flow", "back", "dark forest", "layer"]
        if any(m in lower for m in specific_markers):
            pts += 2
        score += pts
        flag = " ← reroute" if rerouted else ""
        print(f"Turn {i} ({state}): {pts}/10 [{prov}, {len(text)}ch]{flag}")

    pct = round(100 * score / max_score)
    print("\n" + "=" * 78)
    print(f"TOTAL: {score}/{max_score} = {pct}%")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(smoke_test())
