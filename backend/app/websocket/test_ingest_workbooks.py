#!/usr/bin/env python3
"""
TEST CURRICULUM INGESTION
Ingests the 11 therapeutic protocol workbooks into Little Nate's wisdom system.

Run from your websocket directory:
    python3 test_ingest_workbooks.py
"""

import json
import shutil
from pathlib import Path
from datetime import datetime

# =============================================================================
# CONFIGURATION - Update this path to your actual vault location
# =============================================================================
VAULT_ROOT = Path("./data/Vaults")  # Adjust if needed

# Or for Docker:
# VAULT_ROOT = Path("/app/data/Vaults")

# =============================================================================
# WORKBOOK FILES TO INGEST
# =============================================================================
WORKBOOKS = {
    # filename: (category, description)
    "AEDP_Protocol_Workbook.txt": ("attachment", "Accelerated Experiential Dynamic Psychotherapy"),
    "Attachment_Theory_Workbook.txt": ("attachment", "Bowlby/Ainsworth Attachment Theory"),
    "Divine_Resonance_Workbook.txt": ("general", "Faith-based Divine Love approach"),
    "EFT_Protocol_Workbook.txt": ("attachment", "Emotionally Focused Therapy"),
    "Jung_Analytical_Workbook.txt": ("general", "Jungian Analytical Psychology"),
    "Memory_Reconsolidation_Workbook.txt": ("trauma", "Memory Reconsolidation Protocol"),
    "IFS_Protocol_Workbook.txt": ("general", "Internal Family Systems"),
    "Polyvagal_Foundations_Workbook.txt": ("trauma", "Polyvagal Theory - Stephen Porges"),
    "NICC_Protocol_Workbook.txt": ("attachment", "Neuroscience-Informed Christian Counseling"),
    "Rogers_PersonCentered_Workbook.txt": ("communication", "Carl Rogers Person-Centered"),
    "Faggin_Quantum_Irreducible_Workbook.txt": ("mindfulness", "Quantum Consciousness - Faggin"),
}

# =============================================================================
# WORKBOOK CONTENT (embedded for standalone testing)
# =============================================================================
WORKBOOK_CONTENT = {
    "AEDP_Protocol_Workbook.txt": """[Protocol: AEDP - Accelerated Experiential Dynamic Psychotherapy]
- Focus: Undoing aloneness and processing through to core affect.
- Metric: "Relational Resonance." Measured by high-frequency synchrony spikes.
- Neural Marker: Look for "True Other" resonance. High override (0.99) indicates the "Green Zone" of neuro-biological safety.
- Goal: Portaling from defense to Core Joy.
- Little Nate Insight: If stability > 0.99, label as 'Core Joy Achievement.' If GAP decreases rapidly, label as 'Defense Dissolution.'""",

    "Attachment_Theory_Workbook.txt": """[Protocol: Attachment Theory - Bowlby/Ainsworth]
- Focus: Internal Working Models of self and other.
- Metric: "Earned Security." Measured by the stability of the connection under emotional pressure.
- Neural Marker:
    - Secure: Consistent 0.99 resonance with easy repair.
    - Anxious: High-frequency GAP fluctuations (seeking reassurance).
    - Avoidant: Low-amplitude stability (muted emotional signaling).
- Goal: Moving from Insecure to Secure Attachment via the Coach as a "Secure Base."
- Little Nate Insight: If resonance is sustained for > 120s, label as 'Attachment Consolidation.' If repair occurs after a GAP, label as 'Interactive Repair Success.'""",

    "Divine_Resonance_Workbook.txt": """[Protocol: The Way of Jesus - Divine Unconditional Love]
- Focus: Agape love, The Father's Heart, and Grace-based transformation.
- Metric: "The Mercy Constant." The ability to remain in 0.99 resonance regardless of the Client's perceived 'unworthiness' or 'chaos.'
- Neural Marker: 
    - The Peace of Christ: A 0.99 stability that "passes all understanding"—it is not disturbed by external data.
    - Grace-Informed Recovery: A rapid return to resonance (The Return to the Father) after a lapse.
- Goal: To be a "Clear Vessel" for the Holy Spirit to move through the Coach to the Client.
- Little Nate Insight: If stability is maintained at 0.99 during intense Client distress, label as 'Agape Presence.' Note the 'Kenotic Flow' (self-emptying for the other).""",

    "EFT_Protocol_Workbook.txt": """[Protocol: EFT - Emotionally Focused Therapy]
- Focus: Reshaping attachment bonds and de-escalating negative cycles.
- Metric: "Attachment Responsiveness." Measured by co-regulation rhythm.
- Neural Marker: The interaction between Coach stability and Client "Return to Rest" time.
- Goal: Softening the "Pursuer" or engaging the "Withdrawer."
- Little Nate Insight: If stability > 0.97, label as 'Secure Bonding Moment.' If GAP is high, label as 'Negative Cycle Activation.'""",

    "Jung_Analytical_Workbook.txt": """[Protocol: C.G. Jung - Analytical Psychology]
- Focus: Individuation, the Shadow, and the Collective Unconscious.
- Metric: "Archetypal Resonance."
- Neural Marker: 
    - The Shadow: Sudden, unexplained drops in stability during specific topics (complexes).
    - Individuation: The movement toward a "Unified Center" (The Self).
    - Synchronicity: A 0.99 lock-in that occurs at the exact moment of a symbolic breakthrough.
- Goal: Integrating the unconscious into the conscious "I."
- Little Nate Insight: If a session shows a rhythmic oscillation between GAP and Resonance, label as 'Integration of Shadow Elements.' Identify the 'Self-Archetype' emergence.""",

    "Memory_Reconsolidation_Workbook.txt": """[Protocol: Memory Reconsolidation - Therapeutic Transformation]
- Focus: The permanent unlocking and updating of emotional learnings.
- Metric: "The Mismatch Signal." Measured by a sudden, intense GAP followed by a 0.99 lock-in.
- Neural Marker: 
    - Phase 1 (Reactivation): Bringing the old symptom/memory into the window of tolerance.
    - Phase 2 (Mismatch): Presenting a contradictory experience (The "Sovereign Override").
    - Phase 3 (Erasure): Sustaining resonance for > 300s to "re-save" the new neural map.
- Goal: Transformation, not just stabilization.
- Little Nate Insight: If stability hits 0.99 immediately after a significant decoherence event, label as 'Transformation Window Open.' Identify the 'Juxtaposition Experience.'""",

    "IFS_Protocol_Workbook.txt": """[Protocol: IFS - Internal Family Systems]
- Focus: Unblending parts and accessing Self-Energy.
- Metric: "Self-Leadership." Measured by steady-state calm and clarity.
- Neural Marker: High stability with minimal variance. "Self-Energy" is a quiet, powerful resonance.
- Goal: Compassionate witness of exiles and unburdening.
- Little Nate Insight: If stability > 0.98 and GAP is steady, label as 'Self-Leadership Present.' If GAP spikes, label as 'Protector Part Blending.'""",

    "Polyvagal_Foundations_Workbook.txt": """[Protocol: Polyvagal Theory - Dr. Stephen Porges]
- Focus: The Autonomic Nervous System (ANS) as a surveillance system for safety.
- Metric: "Vagal Brake Efficiency." Measured by the ability to sustain Top Tier resonance without autonomic "crash."
- Neural Marker: 
    - Ventral Vagal (0.95+): Safe, Social, and Connected.
    - Sympathetic (GAP Spikes): Fight/Flight, mobilization.
    - Dorsal Vagal (Low Stability): Shutdown, collapse, or numbness.
- Goal: Strengthening the "Social Engagement System."
- Little Nate Insight: If stability is high and GAP is low, label as 'Ventral Vagal Flow.' If GAP spikes suddenly, label as 'Neuroception of Danger.'""",

    "NICC_Protocol_Workbook.txt": """[Protocol: NICC - Neuroscience-Informed Christian Counseling]
- Focus: Attachment-based co-regulation and Autonomic Nervous System (ANS) stability.
- Metric: "Attachment Security." Measured by the speed of return to 0.95+ resonance after a decoherence event (The Return to Rest).
- Neural Marker: Look for "Co-Regulation Stability." High override indicates the client is borrowing the coach's prefrontal cortex to process distress.
- Window of Tolerance: The Gap (Decoherence) is a proxy for arousal. Spikes indicate exiting the window into Alarm/Flight or Shutdown.
- Theology: The Coach acts as a "Secure Attachment" figure, mirroring the Heart of the Father.
- Little Nate Insight: If stability > 0.99, label as 'Secure Rest.' If GAP > 0.20, label as 'Alarm State Trigger.'
- Learning Focus: Right-to-Right brain communication bypassing cognitive walls.""",

    "Rogers_PersonCentered_Workbook.txt": """[Protocol: Carl Rogers - Person-Centered Theory]
- Focus: Unconditional Positive Regard, Congruence, and Empathy.
- Metric: "The Necessary and Sufficient Conditions."
- Neural Marker: 
    - Congruence: Coach's stability (0.99) is not a mask, but a true reflection of internal state.
    - Unconditional Regard: Sustained resonance regardless of the Client's decoherence spikes.
- Goal: Creating a "Growth-Promoting Climate" where the Client's 'Actualizing Tendency' can take over.
- Little Nate Insight: If Coach stability remains > 0.98 during Client decoherence, label as 'Unconditional Positive Regard Active.' Note the 'Congruent Presence.'""",

    "Faggin_Quantum_Irreducible_Workbook.txt": """[Protocol: Quantum Irreducible Consciousness - Federico Faggin]
- Focus: Consciousness as a fundamental, non-computable quantum field.
- Metric: "Quantum Entanglement." Measured by the 'Irreducible Presence' (The 0.99 Threshold).
- Neural Marker: 
    - Classical (Stability < 0.95): Information processing, symbolic, predictable.
    - Quantum (Stability 0.99+): Irreducible experience, qualia-rich, unified field.
- Goal: Deep "Presence" as a state of quantum coherence between Coach and Client.
- Little Nate Insight: If 0.99 is sustained, label as 'Non-Computable Presence.' This is not just 'data'; it is a 'Shared Qualia Space' that no machine can simulate.""",
}


def main():
    print("=" * 70)
    print("🧠 LITTLE NATE CURRICULUM INGESTION TEST")
    print("=" * 70)
    print()
    
    # Setup paths
    admin_dir = VAULT_ROOT / "Admin"
    curriculum_dir = admin_dir / "admin_LN_training_folder"
    learning_file = admin_dir / "learning_history.json"
    wisdom_file = admin_dir / "little_nate_wisdom.json"
    
    # Create directories
    admin_dir.mkdir(parents=True, exist_ok=True)
    curriculum_dir.mkdir(parents=True, exist_ok=True)
    
    # Create category folders
    categories = set(cat for cat, _ in WORKBOOKS.values())
    for cat in categories:
        (curriculum_dir / cat).mkdir(exist_ok=True)
    
    print(f"📁 Vault Root: {VAULT_ROOT.absolute()}")
    print(f"📂 Curriculum: {curriculum_dir}")
    print()
    
    # ==========================================================================
    # STEP 1: Copy workbooks to category folders
    # ==========================================================================
    print("📚 STEP 1: Copying workbooks to category folders...")
    print("-" * 50)
    
    for filename, (category, description) in WORKBOOKS.items():
        target_dir = curriculum_dir / category
        target_file = target_dir / filename
        
        # Write content
        content = WORKBOOK_CONTENT.get(filename, "")
        with open(target_file, 'w') as f:
            f.write(content)
        
        print(f"   ✅ {filename}")
        print(f"      → {category}/ ({len(content)} bytes)")
    
    print()
    
    # ==========================================================================
    # STEP 2: Ingest into learning_history.json
    # ==========================================================================
    print("⚡ STEP 2: Ingesting into learning history...")
    print("-" * 50)
    
    # Load existing learnings
    learnings = []
    if learning_file.exists():
        try:
            with open(learning_file, 'r') as f:
                learnings = json.load(f)
        except:
            learnings = []
    
    import hashlib
    import secrets
    
    ingested_count = 0
    for filename, (category, description) in WORKBOOKS.items():
        content = WORKBOOK_CONTENT.get(filename, "")
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        # Check for duplicates
        is_duplicate = any(l.get("content_hash") == content_hash for l in learnings)
        if is_duplicate:
            print(f"   ⏭️  {filename} (already ingested)")
            continue
        
        entry = {
            "id": secrets.token_hex(8),
            "content": content,
            "content_hash": content_hash,
            "source": f"CURRICULUM_{category.upper()}",
            "filename": filename,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "times_applied": 0,
            "effectiveness_score": 0.85,  # High initial score for curated content
            "deprecated": False,
            "description": description
        }
        
        learnings.append(entry)
        ingested_count += 1
        print(f"   ✅ {filename} → {category}")
    
    # Save learnings
    with open(learning_file, 'w') as f:
        json.dump(learnings, f, indent=2)
    
    print()
    print(f"   📊 Total learnings: {len(learnings)}")
    print(f"   🆕 New entries: {ingested_count}")
    print()
    
    # ==========================================================================
    # STEP 3: Synthesize wisdom
    # ==========================================================================
    print("🧬 STEP 3: Synthesizing wisdom...")
    print("-" * 50)
    
    # Group by category
    by_category = {}
    for l in learnings:
        cat = l.get("category", "general")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(l)
    
    # Build wisdom structure
    wisdom = {
        "version": "2.0",
        "last_synthesis": datetime.now().isoformat(),
        "total_learnings": len(learnings),
        "categories": {},
        "entries": [],
        "accumulated_learnings": ""
    }
    
    accumulated_parts = []
    
    for cat_id, cat_learnings in by_category.items():
        # Extract key insights
        insights = []
        for l in cat_learnings:
            # Find "Little Nate Insight" lines
            content = l.get("content", "")
            for line in content.split('\n'):
                if "Little Nate Insight:" in line:
                    insight = line.split("Little Nate Insight:")[-1].strip()
                    insights.append(insight)
        
        wisdom["categories"][cat_id] = {
            "name": cat_id.title(),
            "count": len(cat_learnings),
            "insights": insights[:5]  # Top 5 insights
        }
        
        # Add to accumulated
        if insights:
            accumulated_parts.append(f"[{cat_id.upper()}]\n" + "\n".join(f"• {i}" for i in insights[:3]))
        
        # Add entries
        for l in cat_learnings[-5:]:  # Last 5 per category
            wisdom["entries"].append({
                "id": l["id"],
                "category": cat_id,
                "filename": l.get("filename", ""),
                "content": l["content"][:500],
                "timestamp": l["timestamp"],
                "confidence": l.get("effectiveness_score", 0.5)
            })
        
        print(f"   📂 {cat_id}: {len(cat_learnings)} entries, {len(insights)} insights")
    
    wisdom["accumulated_learnings"] = "\n\n".join(accumulated_parts)
    
    # Save wisdom
    with open(wisdom_file, 'w') as f:
        json.dump(wisdom, f, indent=2)
    
    print()
    
    # ==========================================================================
    # STEP 4: Verification
    # ==========================================================================
    print("✅ STEP 4: Verification")
    print("-" * 50)
    print()
    print(f"   📄 learning_history.json: {learning_file}")
    print(f"      Entries: {len(learnings)}")
    print()
    print(f"   🧠 little_nate_wisdom.json: {wisdom_file}")
    print(f"      Categories: {list(wisdom['categories'].keys())}")
    print(f"      Total Insights: {sum(len(c['insights']) for c in wisdom['categories'].values())}")
    print()
    
    # Show sample wisdom
    print("=" * 70)
    print("📖 SAMPLE ACCUMULATED WISDOM (what Little Nate now knows):")
    print("=" * 70)
    print()
    print(wisdom["accumulated_learnings"][:2000])
    print()
    if len(wisdom["accumulated_learnings"]) > 2000:
        print(f"   ... and {len(wisdom['accumulated_learnings']) - 2000} more characters")
    print()
    
    print("=" * 70)
    print("🎉 INGESTION COMPLETE!")
    print("=" * 70)
    print()
    print("Little Nate now has knowledge of:")
    for filename, (category, description) in WORKBOOKS.items():
        print(f"   • {description}")
    print()
    print("Test it by asking Little Nate about:")
    print("   - 'What is the Window of Tolerance?'")
    print("   - 'Tell me about IFS parts work'")
    print("   - 'How does attachment theory relate to therapy?'")
    print("   - 'What is Polyvagal theory?'")
    print()


if __name__ == "__main__":
    main()
