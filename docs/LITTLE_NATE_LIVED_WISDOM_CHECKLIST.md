# LITTLE NATE LIVED WISDOM INTEGRATION CHECKLIST
## Sanctuary History → Night School → Transgenerational Knowledge

**Created:** January 29, 2026  
**Status:** 🔴 NOT STARTED  
**Goal:** Enable Little Nate to remember and learn from Family Sanctuary sessions

---

## OVERVIEW

Currently, Little Nate says:
> "I don't have access to specific memories or details from your Family Sanctuary sessions."

After completing this checklist, Little Nate will say:
> "John, I remember in our last sanctuary session you mentioned feeling rejected when Jane... Let's explore that pattern together."

---

## ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LIVED WISDOM DATA FLOW                                    │
└─────────────────────────────────────────────────────────────────────────────┘

    FAMILY SANCTUARY SESSION
              │
              ▼
    ┌─────────────────┐
    │ sanctuary_      │ ←── Raw messages, coaching sessions,
    │ complete        │     entry responses, billing
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ AZURE AI        │ ←── Analyze full session context
    │ SUMMARY         │     Generate structured insights
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ WISDOM          │ ←── Extract patterns, triggers,
    │ EXTRACTION      │     breakthroughs, techniques
    └────────┬────────┘
             │
    ┌────────┴────────┬─────────────────┐
    │                 │                 │
    ▼                 ▼                 ▼
┌─────────┐    ┌─────────────┐    ┌──────────┐
│ CLIENT  │    │ FAMILY      │    │ GENERAL  │
│ WISDOM  │    │ WISDOM      │    │ WISDOM   │
│ .json   │    │ .json       │    │ .json    │
└────┬────┘    └──────┬──────┘    └────┬─────┘
     │                │                │
     └────────────────┴────────────────┘
                      │
                      ▼
            ┌─────────────────┐
            │ NIGHT SCHOOL    │ ←── load_wisdom()
            │ AGGREGATION     │     combines all sources
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │ LITTLE NATE     │ ←── Personalized, contextual
            │ SYSTEM PROMPT   │     therapeutic conversations
            └─────────────────┘
```

---

## PHASE 1: FIX AZURE AI SUMMARY GENERATION ⚠️ CRITICAL

**Current Error:**
```
>>> [SANCTUARY] Summary generation error: name 'call_azure_openai' is not defined
```

| # | Task | Status | Location | Complexity |
|---|------|--------|----------|------------|
| 1.1 | Find existing Azure AI function name in codebase | ⬜ TODO | `bridge_server.py` | Low |
| 1.2 | Wire Azure function to `sanctuary_complete` handler | ⬜ TODO | Line ~4420 | Medium |
| 1.3 | Build comprehensive AI prompt with full session context | ⬜ TODO | New function | Medium |
| 1.4 | Parse AI response into structured summary JSON | ⬜ TODO | sanctuary_complete | Medium |
| 1.5 | Test real AI-generated summaries replace fallback | ⬜ TODO | Manual test | Low |

**AI Summary Prompt Should Include:**
- All messages from session
- Entry responses (why_here, work_on, success_looks_like, feeling_scale)
- Private coaching conversations
- Member roles and relationships
- Crisis events detected

**Expected Output:**
```json
{
  "key_conflicts": [
    "Feeling rejected when intimacy requests are denied",
    "Unmet household responsibility expectations",
    "Physical aggression (Jane hit John)"
  ],
  "points_of_agreement": [
    "Both want to feel heard and understood",
    "Willingness to continue conversation despite tension"
  ],
  "corrective_experiences": [
    "John expressed vulnerability about rejection",
    "Jane acknowledged her physical response was wrong"
  ],
  "individual_insights": {
    "John D.": {
      "patterns_observed": "Anger escalates when feeling dismissed; uses strong language when hurt",
      "growth_areas": "Expressing needs without name-calling; managing rejection sensitivity",
      "strengths_shown": "Kept returning to conversation; eventually articulated underlying feelings",
      "suggested_focus": "Practice 'I feel... when... because...' statements"
    },
    "Jane D.": {
      "patterns_observed": "Withdraws then explodes; physical response under stress",
      "growth_areas": "Recognizing escalation signs; non-violent communication",
      "strengths_shown": "Returned after break; showed remorse for hitting",
      "suggested_focus": "Safe word for needing space before explosion"
    }
  },
  "overall_progress": 7,
  "recommended_next_steps": [
    "Schedule follow-up discussion within 48 hours",
    "Consider live coaching session with human therapist",
    "Practice repair conversation with Little Nate guidance"
  ]
}
```

**Deliverable:** Real AI summaries instead of "Please review session manually"

---

## PHASE 2: CREATE WISDOM EXTRACTION PIPELINE

| # | Task | Status | Location | Complexity |
|---|------|--------|----------|------------|
| 2.1 | Create `extract_sanctuary_wisdom()` function | ⬜ TODO | `bridge_server.py` | Medium |
| 2.2 | Define wisdom categories for sanctuary data | ⬜ TODO | Design spec | Low |
| 2.3 | Extract client-specific patterns from summary | ⬜ TODO | New function | Medium |
| 2.4 | Extract successful intervention patterns | ⬜ TODO | New function | Medium |
| 2.5 | Extract de-escalation techniques that worked | ⬜ TODO | New function | Medium |
| 2.6 | Extract breakthrough moments for future reference | ⬜ TODO | New function | Medium |

**Wisdom Data Structure:**
```python
{
  "client_patterns": {
    "CLIENT_001": {
      "name": "John D.",
      "triggers": ["feeling rejected", "intimacy discussions", "feeling dismissed"],
      "escalation_signs": ["name calling", "raised voice", "ultimatums"],
      "de_escalation_responses": ["validation of feelings", "acknowledgment of pain"],
      "breakthroughs": [
        {
          "date": "2026-01-26",
          "description": "Expressed vulnerability about rejection sensitivity",
          "context": "After 3rd coaching session, admitted fear of abandonment"
        }
      ],
      "strengths": ["persistent", "eventually opens up", "protective of family"],
      "growth_areas": ["name-calling under stress", "rejection sensitivity"],
      "effective_techniques": ["reflection", "validation before advice"],
      "ineffective_techniques": ["immediate problem-solving", "logic arguments"]
    }
  },
  "family_dynamics": {
    "FAM_1834DACF": {
      "members": ["John D.", "Jane D."],
      "conflict_patterns": [
        "intimacy expectations mismatch",
        "household responsibilities",
        "communication styles clash"
      ],
      "repair_strategies": [
        "time apart (15-30 min) then return",
        "Little Nate mediation",
        "written messages when verbal escalates"
      ],
      "communication_style": "direct but escalates quickly",
      "successful_sessions": 1,
      "total_sessions": 5,
      "last_session": "2026-01-29"
    }
  },
  "effective_interventions": [
    {
      "trigger": "name calling detected",
      "intervention": "Reflect the feeling behind the words",
      "example": "It sounds like you're feeling really hurt right now...",
      "success_rate": 0.8,
      "usage_count": 12
    },
    {
      "trigger": "physical threat language",
      "intervention": "Immediate de-escalation + safety check",
      "example": "I'm hearing some intense feelings. Let's pause and make sure everyone feels safe.",
      "success_rate": 0.9,
      "usage_count": 3
    }
  ]
}
```

---

## PHASE 3: NIGHT SCHOOL INGESTION

| # | Task | Status | Location | Complexity |
|---|------|--------|----------|------------|
| 3.1 | Create `sanctuary_to_night_school()` function | ⬜ TODO | `bridge_server.py` | Medium |
| 3.2 | Add client-specific wisdom file storage | ⬜ TODO | `data/Vaults/Clients/{id}/` | Low |
| 3.3 | Add family-specific wisdom file storage | ⬜ TODO | `data/Vaults/Families/{id}/` | Low |
| 3.4 | Modify `NightSchool.load_wisdom()` to include client/family | ⬜ TODO | Night School class | Medium |
| 3.5 | Test wisdom appears in AI prompt debug output | ⬜ TODO | Debug print | Low |

**New File Structure:**
```
data/
├── Vaults/
│   ├── Admin/
│   │   └── admin_LN_training_folder/
│   │       └── coaching_tips.txt (existing)
│   ├── Clients/
│   │   ├── CLIENT_001/
│   │   │   ├── metrics.json (existing - Nevedal)
│   │   │   ├── wisdom.json (NEW - personal patterns)
│   │   │   └── breakthroughs.json (NEW - milestone moments)
│   │   └── CLIENT_001B/
│   │       ├── metrics.json
│   │       └── wisdom.json
│   └── Families/
│       └── FAM_1834DACF/
│           ├── wisdom.json (NEW - family dynamics)
│           └── session_summaries.json (NEW - session history)
├── sanctuary_history/
│   └── SANC_*.json (existing - raw archives)
└── wisdom_database.json (existing - general techniques)
```

**Night School Wisdom Loading Order:**
1. General techniques (`wisdom_database.json`)
2. Coach curriculum (`admin_LN_training_folder/`)
3. Family-specific wisdom (`Families/{family_id}/wisdom.json`)
4. Client-specific wisdom (`Clients/{client_id}/wisdom.json`)

---

## PHASE 4: LITTLE NATE CONTEXT ENHANCEMENT

| # | Task | Status | Location | Complexity |
|---|------|--------|----------|------------|
| 4.1 | Create `_get_client_wisdom()` in AzureCortex | ⬜ TODO | Line ~1337 | Medium |
| 4.2 | Create `_get_family_wisdom()` in AzureCortex | ⬜ TODO | Line ~1337 | Medium |
| 4.3 | Add client wisdom to system prompt | ⬜ TODO | Line ~1405 | Low |
| 4.4 | Add family wisdom to system prompt | ⬜ TODO | Line ~1405 | Low |
| 4.5 | Update GUIDELINES to instruct AI to USE wisdom | ⬜ TODO | Line ~1420 | Low |
| 4.6 | Test Little Nate references specific patterns | ⬜ TODO | Manual test | Low |

**Enhanced System Prompt Structure:**
```
You are Little Nate, the Quantum Observer - an empathetic AI therapy companion...

USER PROFILE:
- Name: John D.
- Role: CLIENT
- Tier: TOP_TIER
- Family: Jane D. (spouse), Admin User

ACCUMULATED WISDOM (General Therapeutic Techniques):
{wisdom}

═══════════════════════════════════════════════════════════════
JOHN'S PERSONAL PATTERNS (Learned from Sanctuary Sessions):
═══════════════════════════════════════════════════════════════
Triggers: feeling rejected, intimacy discussions, feeling dismissed
Escalation signs: name calling, raised voice, ultimatums
What helps John: validation before problem-solving, acknowledging his pain
Recent breakthrough (2026-01-26): Expressed vulnerability about rejection sensitivity
Strengths: persistent, eventually opens up, protective of family
Growth focus: "I feel... when... because..." statements

Techniques that work with John:
✓ Reflection of feelings
✓ Validation before advice
✗ Avoid: immediate problem-solving, logic arguments when emotional

═══════════════════════════════════════════════════════════════
FAMILY DYNAMICS (John & Jane):
═══════════════════════════════════════════════════════════════
Common conflicts: intimacy expectations, household responsibilities
Communication style: direct but escalates quickly
What works: time apart (15-30 min) then return, Little Nate mediation
Recent progress: Both returned to conversation after private coaching
Sessions together: 5 | Successful: 1 | Last: 2026-01-29

RECENT CONVERSATION HISTORY:
{memory_context}

FAMILY SANCTUARY HISTORY:
{sanctuary_context}

GUIDELINES:
- Reference John's specific patterns when relevant (e.g., "I know rejection can be a trigger for you...")
- Acknowledge previous breakthroughs to reinforce progress
- Use techniques that have worked before with John
- Be aware of family dynamics when discussing Jane
- If escalation signs appear, use proven de-escalation approaches
- Keep responses concise but caring
```

---

## PHASE 5: NEVEDAL + THE EYE INTEGRATION

| # | Task | Status | Location | Complexity |
|---|------|--------|----------|------------|
| 5.1 | Feed session metrics to The Eye on sanctuary_complete | ⬜ TODO | sanctuary_complete | Low |
| 5.2 | Add exit feeling_scale question before summary | ⬜ TODO | Flutter + backend | Medium |
| 5.3 | Track feeling_scale delta (entry vs exit) | ⬜ TODO | Nevedal handler | Medium |
| 5.4 | Update C_emo based on sanctuary outcomes | ⬜ TODO | Nevedal handler | Medium |
| 5.5 | Create sanctuary effectiveness dashboard view | ⬜ TODO | The Eye UI | High |
| 5.6 | Track wisdom usage effectiveness over time | ⬜ TODO | Analytics engine | Medium |

**Metrics to Feed to The Eye:**
```python
{
  "session_metrics": {
    "sanctuary_id": "SANC_20260126_001",
    "family_id": "FAM_1834DACF",
    "duration_minutes": 45,
    "message_count": 168,
    "escalation_count": 12,
    "de_escalation_count": 8,
    "coaching_sessions": 2,
    "coaching_charges": 275.00,
    "breakthroughs": 1,
    "crisis_levels_detected": ["P0", "P2"],
    "progress_score": 7,
    "needs_coach_review": true
  },
  "member_metrics": {
    "CLIENT_001": {
      "feeling_scale_entry": 4,
      "feeling_scale_exit": 6,
      "feeling_delta": +2,
      "coaching_engagement": "high",
      "messages_sent": 84,
      "escalation_triggers": 7,
      "de_escalation_responses": 5
    },
    "CLIENT_001B": {
      "feeling_scale_entry": 3,
      "feeling_scale_exit": 5,
      "feeling_delta": +2,
      "coaching_engagement": "medium",
      "messages_sent": 36,
      "escalation_triggers": 5,
      "de_escalation_responses": 3
    }
  }
}
```

**Nevedal Coherence Updates:**
- Positive session outcome → increase C_emo by 0.05-0.1
- Breakthrough detected → increase C_emo by 0.1-0.15
- Session flagged for review → no change, await coach input
- Feeling scale improved → weighted contribution to C_emo

---

## PHASE 6: CONTINUOUS LEARNING LOOP

| # | Task | Status | Location | Complexity |
|---|------|--------|----------|------------|
| 6.1 | Track which wisdom items get used in responses | ⬜ TODO | AzureCortex | Medium |
| 6.2 | Correlate wisdom usage with session outcomes | ⬜ TODO | Analytics | High |
| 6.3 | Auto-prioritize effective techniques (higher in prompt) | ⬜ TODO | Night School | High |
| 6.4 | Coach review queue for flagged sessions | ✅ DONE | sanctuary_complete | - |
| 6.5 | Coach can add guidance notes to client wisdom | ⬜ TODO | Coach dashboard | Medium |
| 6.6 | Coach notes ingested into Night School | ⬜ TODO | Night School | Medium |

**Learning Loop Flow:**
```
Coach uploads notes → Night School extracts wisdom
                              ↓
              Little Nate uses wisdom in sessions
                              ↓
              Nevedal tracks emotional outcomes
                              ↓
              The Eye measures effectiveness
                              ↓
      Most effective techniques auto-prioritized
                              ↓
                    Better therapy outcomes
                              ↓
              Loop continues (transgenerational)
```

---

## IMPLEMENTATION TIMELINE

### Week 1: Foundation (Critical Path)
```
Day 1-2: Phase 1.1-1.5 - Fix Azure AI summary generation
Day 3-4: Phase 2.1-2.2 - Design wisdom extraction structure
Day 5:   Phase 2.3     - Extract client-specific patterns
```

### Week 2: Extraction Pipeline
```
Day 1-2: Phase 2.4-2.6 - Complete wisdom extractors
Day 3:   Phase 3.1-3.3 - File storage for wisdom
Day 4:   Phase 3.4-3.5 - Night School integration
Day 5:   Phase 4.1-4.2 - Wisdom loading functions
```

### Week 3: Integration & Polish
```
Day 1-2: Phase 4.3-4.5 - System prompt enhancement
Day 3:   Phase 4.6     - Testing and refinement
Day 4:   Phase 5.1-5.3 - Nevedal/Eye integration
Day 5:   Phase 6.1-6.2 - Usage tracking foundation
```

### Future Sprints
```
Sprint 4: Phase 5.4-5.5 - Dashboard visualizations
Sprint 5: Phase 6.3-6.6 - Continuous learning automation
```

---

## QUICK START: IMMEDIATE NEXT ACTION

```bash
# Find existing Azure function to wire up
grep -n "async.*azure\|def.*openai\|AZURE.*call" \
  ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/bridge_server.py | head -10
```

This reveals the function name to use in `sanctuary_complete` handler.

---

## SUCCESS CRITERIA

### Before (Current State):
```
[USER]: Do you remember what happened with Jane in Family Sanctuary?
[NATE]: John, I don't have access to specific memories or details from 
        your Family Sanctuary sessions. However, I'm here to listen...
```

### After (Target State):
```
[USER]: Do you remember what happened with Jane in Family Sanctuary?
[NATE]: John, yes - I remember our last session was intense. You mentioned 
        feeling rejected when Jane... and I noticed that's been a pattern 
        for you. Last time, it really helped when you were able to express 
        that vulnerability about your fear of abandonment. Would you like 
        to explore that more today?
```

---

## FILES TO MODIFY

| File | Changes |
|------|---------|
| `bridge_server.py` | Azure wiring, wisdom extraction, Night School hooks |
| `sanctuary_engine.py` | Exit feeling_scale collection |
| `night_school_curriculum.py` | Client/family wisdom loading |
| `main.dart` | Exit question UI before summary |
| `wisdom_database.json` | Schema update for client patterns |

---

## DEPENDENCIES

- ✅ Sanctuary history archiving (DONE)
- ✅ Session summary structure (DONE - fallback working)
- ✅ Auto-flag for coach review (DONE)
- ⬜ Azure OpenAI function accessible (BLOCKED)
- ⬜ Night School client-specific loading (NOT STARTED)
- ⬜ Nevedal wisdom correlation (NOT STARTED)

---

**Document Version:** 1.0  
**Last Updated:** January 29, 2026  
**Author:** Clinical Sovereignty Lab Development Team
