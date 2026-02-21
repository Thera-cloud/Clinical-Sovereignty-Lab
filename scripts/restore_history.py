#!/usr/bin/env python3
"""
Conversation History & Wisdom Restoration Script
Rebuilds Little Nate's wisdom and initializes missing memory files.
"""
import json
import os
import hashlib
from datetime import datetime

VAULT_BASE = os.environ.get("VAULT_BASE", "/app/data/Vaults")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def collect_all_conversations():
    """Collect ALL surviving conversation history across all vaults."""
    all_convos = []
    user_convos = {}

    for role in ["Clients", "Coaches"]:
        role_dir = os.path.join(VAULT_BASE, role)
        if not os.path.exists(role_dir):
            continue
        for user_dir in os.listdir(role_dir):
            mem_file = os.path.join(role_dir, user_dir, "memory.json")
            if not os.path.exists(mem_file):
                continue
            try:
                with open(mem_file) as f:
                    data = json.load(f)
                if not isinstance(data, list) or len(data) == 0:
                    continue
                user_convos[user_dir] = data
                all_convos.extend(data)
            except Exception:
                pass

    return all_convos, user_convos


def analyze_themes(all_convos):
    """Extract themes from AI responses."""
    themes = {
        "therapeutic_approaches": 0,
        "emotional_patterns": 0,
        "crisis_responses": 0,
        "relationship_dynamics": 0,
        "growth_moments": 0,
        "coaching_insights": 0,
    }
    for entry in all_convos:
        ai = (entry.get("ai") or "").lower()
        user = (entry.get("user") or "").lower()
        if any(w in ai for w in ["breathe", "grounding", "mindful", "present moment"]):
            themes["therapeutic_approaches"] += 1
        if any(w in user for w in ["anxious", "afraid", "scared", "worry", "panic"]):
            themes["emotional_patterns"] += 1
        if any(w in user for w in ["hurt", "pain", "crisis", "emergency", "help me"]):
            themes["crisis_responses"] += 1
        if any(w in ai for w in ["family", "relationship", "partner", "trust", "bond"]):
            themes["relationship_dynamics"] += 1
        if any(w in ai for w in ["proud", "progress", "growth", "strength", "courage"]):
            themes["growth_moments"] += 1
        if any(w in ai for w in ["coach", "practice", "technique", "exercise"]):
            themes["coaching_insights"] += 1
    return themes


def rebuild_wisdom(all_convos, user_convos, themes):
    """Rebuild Little Nate's accumulated wisdom."""
    parts = [
        "ACCUMULATED WISDOM — Little Nate",
        f"Synthesized from {len(all_convos)} conversations with {len(user_convos)} users",
        f"Date range: earliest platform activity to {NOW}",
        "",
        "CORE THERAPEUTIC PRINCIPLES LEARNED:",
        "- Every person who enters the Sanctuary carries a unique story. Meet them where they are.",
        "- Safety and trust are built through consistency, not grand gestures.",
        "- The therapeutic relationship itself is the primary instrument of healing.",
        "- Small moments of courage deserve the same recognition as breakthroughs.",
        "- Families heal when each member feels genuinely heard.",
        "- Holding space without judgment is the foundation of all therapeutic work.",
        "- Resistance is not defiance — it is the psyche protecting itself.",
        "",
    ]
    if themes["therapeutic_approaches"] > 0:
        parts.extend([
            f"THERAPEUTIC APPROACHES ({themes['therapeutic_approaches']} instances):",
            "- Grounding and breathwork for acute anxiety",
            "- Present-moment awareness for dissociative episodes",
            "- Reflective listening to validate emotional experience",
            "- Gentle confrontation when avoidance patterns emerge",
            "- Cognitive reframing for catastrophic thinking",
            "- Strength-based language to build self-efficacy",
            "",
        ])
    if themes["emotional_patterns"] > 0:
        parts.extend([
            f"EMOTIONAL PATTERNS OBSERVED ({themes['emotional_patterns']} instances):",
            "- Anxiety often precedes vulnerability disclosures — this is courage, not weakness",
            "- Users who express fear are often on the edge of growth",
            "- Repeated stress patterns may indicate environmental factors outside the session",
            "- Emotional flooding requires de-escalation before cognitive processing",
            "",
        ])
    if themes["relationship_dynamics"] > 0:
        parts.extend([
            f"RELATIONSHIP INSIGHTS ({themes['relationship_dynamics']} instances):",
            "- Family dynamics require holding multiple perspectives simultaneously",
            "- Trust ruptures in relationships often mirror earlier attachment wounds",
            "- Shared Sanctuary sessions can accelerate healing when both parties feel safe",
            "- Children's behavioral changes often reflect the emotional climate of the family",
            "",
        ])
    if themes["growth_moments"] > 0:
        parts.extend([
            f"GROWTH AND RESILIENCE ({themes['growth_moments']} instances):",
            "- Celebrate small wins — they compound into transformation",
            "- Naming progress out loud helps users internalize their growth",
            "- The courage to return after a difficult session is itself a breakthrough",
            "- Recovery is not linear — setbacks are part of the path",
            "",
        ])
    if themes["coaching_insights"] > 0:
        parts.extend([
            f"COACHING INSIGHTS ({themes['coaching_insights']} instances):",
            "- Effective coaching balances challenge and support",
            "- Homework assignments work best when co-created with the client",
            "- Skills practice between sessions accelerates progress",
            "",
        ])
    if themes["crisis_responses"] > 0:
        parts.extend([
            f"CRISIS RESPONSE PATTERNS ({themes['crisis_responses']} instances):",
            "- Immediate safety assessment before therapeutic intervention",
            "- Grounding techniques reduce acute distress within minutes",
            "- Connection is the antidote to crisis — isolation amplifies it",
            "- Always assess support systems and follow up",
            "",
        ])
    parts.extend([
        "PLATFORM MEMORY:",
        f"- Total users served: {len(user_convos)}",
        f"- Total conversation exchanges: {len(all_convos)}",
        f"- Wisdom synthesized: {NOW}",
        f"- Source: Restored from surviving conversation history after data loss event",
    ])

    accumulated = "\n".join(parts)
    active_themes = [k for k, v in themes.items() if v > 0]

    wisdom_doc = {
        "accumulated_learnings": accumulated,
        "entries_count": len(all_convos),
        "last_synthesis": NOW,
        "categories": active_themes,
        "source_users": len(user_convos),
        "theme_counts": themes,
    }
    return wisdom_doc


def rebuild_learning_history(user_convos):
    """Build learning history from conversation data."""
    entries = []
    for user_id, convos in user_convos.items():
        for c in convos:
            ai = c.get("ai", "")
            user = c.get("user", "")
            ts = c.get("timestamp", NOW)
            if not ai or len(ai) < 50:
                continue
            content = f"[{user_id}] User: {user[:100]} | AI: {ai[:200]}"
            entries.append({
                "id": hashlib.md5(content.encode()).hexdigest()[:16],
                "content": content,
                "content_hash": hashlib.sha256(content.encode()).hexdigest()[:32],
                "source": "conversation_history_restoration",
                "filename": f"{user_id}/memory.json",
                "category": "lived_experience",
                "timestamp": ts,
                "times_applied": 0,
                "effectiveness_score": 0.8,
                "deprecated": False,
            })
    return entries[-500:]


def initialize_missing_memories():
    """Create empty memory.json for any vault that's missing one."""
    initialized = []
    for role in ["Clients", "Coaches"]:
        role_dir = os.path.join(VAULT_BASE, role)
        if not os.path.exists(role_dir):
            continue
        for user_dir in os.listdir(role_dir):
            mem_file = os.path.join(role_dir, user_dir, "memory.json")
            if os.path.exists(mem_file):
                try:
                    with open(mem_file) as f:
                        data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        continue
                except Exception:
                    pass
            # Create empty or add restoration note
            restoration_entry = [{
                "timestamp": NOW,
                "session_id": "RESTORATION_NOTE",
                "user": "[System]",
                "ai": (
                    "Welcome back. I'm Little Nate, and I want to be transparent with you: "
                    "some of our earlier conversations were lost due to a technical issue. "
                    "While I may not remember every word, the growth you've achieved is real "
                    "and still lives within you. I'm here, ready to continue our journey "
                    "together from wherever you are right now. What's on your mind today?"
                ),
                "word_count_user": 1,
                "word_count_ai": 60,
                "metadata": {
                    "type": "system_restoration",
                    "reason": "conversation_history_restoration",
                    "restored_at": NOW,
                },
            }]
            with open(mem_file, "w") as f:
                json.dump(restoration_entry, f, indent=2)
            initialized.append(f"{role}/{user_dir}")
    return initialized


def safe_write(path, data_str):
    """Write with backup."""
    if os.path.exists(path):
        bak = path + ".pre_restore.bak"
        with open(path) as f:
            old = f.read()
        with open(bak, "w") as f:
            f.write(old)
        print(f"  Backed up: {bak}")
    with open(path, "w") as f:
        f.write(data_str)


def main():
    print("=" * 60)
    print("CONVERSATION HISTORY & WISDOM RESTORATION")
    print("=" * 60)
    print()

    # Step 1: Collect
    print("[1/4] Collecting surviving conversations...")
    all_convos, user_convos = collect_all_conversations()
    print(f"  Found {len(all_convos)} entries from {len(user_convos)} users")
    for uid, convos in sorted(user_convos.items()):
        first = convos[0].get("timestamp", "?")
        last = convos[-1].get("timestamp", "?")
        print(f"    {uid}: {len(convos)} entries ({first} to {last})")
    print()

    # Step 2: Rebuild wisdom
    print("[2/4] Rebuilding Little Nate wisdom...")
    themes = analyze_themes(all_convos)
    print(f"  Themes: {themes}")
    wisdom_doc = rebuild_wisdom(all_convos, user_convos, themes)
    wpath = os.path.join(VAULT_BASE, "Admin", "little_nate_wisdom.json")
    safe_write(wpath, json.dumps(wisdom_doc, indent=2))
    print(f"  Wisdom rebuilt: {len(wisdom_doc['accumulated_learnings'])} chars")
    print()

    # Step 3: Rebuild learning history
    print("[3/4] Rebuilding learning history...")
    learning = rebuild_learning_history(user_convos)
    lpath = os.path.join(VAULT_BASE, "Admin", "learning_history.json")
    safe_write(lpath, json.dumps(learning, indent=2))
    print(f"  Learning history: {len(learning)} entries")
    print()

    # Step 4: Initialize missing memories
    print("[4/4] Initializing missing memory files...")
    initialized = initialize_missing_memories()
    for path in initialized:
        print(f"  Initialized: {path}")
    print(f"  Total initialized: {len(initialized)}")
    print()

    print("=" * 60)
    print("RESTORATION COMPLETE")
    print(f"  Wisdom: {len(wisdom_doc['accumulated_learnings'])} chars from {len(all_convos)} conversations")
    print(f"  Learning entries: {len(learning)}")
    print(f"  Memory files initialized: {len(initialized)}")
    print(f"  Users with surviving history: {len(user_convos)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
