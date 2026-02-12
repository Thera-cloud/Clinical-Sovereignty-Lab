---
name: Patent Update PMB Shame
overview: "Add 5 new specification sections, 5 new independent claims, dependent claims, definitions, data structures, and constants to the Quantum Emotional Coherence patent covering: Crisis Perception Model, Shame Layer, Predictability Model of Behavior, Transgenerational Legacy Analysis, and Observer Protocol."
todos:
  - id: patent-definitions
    content: Add 11 new definitions to the DEFINITIONS section for all new concepts
    status: completed
  - id: patent-section-11
    content: "Write Section 11: Crisis Perception Model (objective vs subjective distress, baseline classification, normalization index)"
    status: completed
  - id: patent-section-12
    content: "Write Section 12: Shame Detection and Core Belief Extraction (shame indicators, core beliefs, shame map, masking patterns)"
    status: completed
  - id: patent-section-13
    content: "Write Section 13: Predictability Model of Behavior (cyclical patterns, precursors, triggers, reactivity, reconsolidation readiness, predictions, confidence thresholds)"
    status: completed
  - id: patent-section-14
    content: "Write Section 14: Transgenerational Legacy Analysis (conversational extraction, cross-member correlation, legacy map)"
    status: completed
  - id: patent-section-15
    content: "Write Section 15: Observer Protocol and Confidence-Gated Action System (observer principle, tiered confidence, action gating, therapeutic framing)"
    status: completed
  - id: patent-claims
    content: Add 5 new independent claims + 8 dependent claims, renumber existing claims 9-30 to 14-35
    status: completed
  - id: patent-appendix
    content: Add 4 new data structures (A.5-A.8) and new constants to Appendix B
    status: completed
  - id: patent-abstract
    content: Update abstract to include new innovations (stay under 150 words)
    status: completed
isProject: false
---

# Patent Update: Crisis Perception, Shame Layer, PMB, Legacy, Observer Protocol

## Current Patent Structure

File: [patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT.md](patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT.md) (1773 lines)

- Sections 1-10 cover: Nevedal Formula, voice biometrics, CEE windows, reconsolidation tracking, crisis detection (keyword-based), adversarial training, group therapy, platform architecture
- Claims 1-8 (independent) + Claims 9-30 (dependent)
- Appendix A: 4 data structures (BiometricSample, NevedalState, CEEEvent, SchemaReconsolidationRecord)
- Appendix B: Constants table

## Additions

### 1. New Definitions (insert into DEFINITIONS section, ~line 57)

- **"Distress Discrepancy"** -- difference between objective biometric distress (computed from C_emo, anxiety, stress metrics) and expressed distress (derived from linguistic sentiment), quantifying the gap between what the body shows and what the client says
- **"Crisis Perception Baseline"** -- classification of a subject's habitual relationship to distress (minimizer, amplifier, normalizer, calibrated), computed from longitudinal distress discrepancy patterns
- **"Shame Index"** -- composite metric (0-1) of shame activation computed from self-blame, unworthiness, and deflection linguistic indicators, weighted by the subject's crisis perception baseline
- **"Core Belief"** -- a recurring shame-based self-referential statement (internal lie) extracted from therapeutic conversation and tracked with frequency, confidence, and associated topics
- **"Shame Map"** -- a per-topic shame intensity profile associating conversational subjects with measured shame activation levels and dominant core beliefs
- **"Predictability Model of Behavior (PMB)"** -- a per-subject behavioral prediction engine computing cyclical patterns, crisis precursor sequences, trigger-topic maps, reactivity signatures, and reconsolidation readiness from longitudinal therapeutic interaction data
- **"Reactivity Signature"** -- classification of a subject's dominant stress response pattern (fight, flight, freeze, fawn) computed from linguistic and engagement behavioral indicators
- **"Reconsolidation Readiness Score"** -- composite metric (0-1) indicating optimal conditions for memory reconsolidation work, combining CEE window proximity, engagement level, emotional charge, and trigger topic presence
- **"Transgenerational Legacy Pattern"** -- a behavioral or emotional pattern identified as inherited from a prior generation, extracted from conversational references to family-of-origin and validated through cross-member behavioral correlation
- **"Confidence-Gated Action Threshold"** -- a minimum confidence level (preferably 95%) that a predicted behavioral pattern must reach before the AI system may reference or act upon it during therapeutic interaction
- **"Observer Protocol"** -- a set of constraints governing AI therapeutic behavior requiring curiosity-based reflection rather than diagnostic assertion, with action gating based on confidence thresholds

### 2. New Specification Sections (insert after Section 10, before CLAIMS)

**Section 11: Crisis Perception Model**

- 11.1 Objective vs Subjective Distress Computation -- formulas for objective_distress and expressed_distress, the discrepancy calculation
- 11.2 Perception Baseline Classification -- exponential moving average tracking, minimizer/amplifier/normalizer/calibrated classification logic, minimum data requirements (10+ messages)
- 11.3 Normalization Index -- variance-based computation detecting flat discrepancy patterns indicating inability to distinguish crisis from baseline
- 11.4 Clinical Significance -- therapeutic meaning of each baseline type, connection to trauma presentation

**Section 12: Shame Detection and Core Belief Extraction**

- 12.1 Shame Indicator Detection -- self-blame, unworthiness, and deflection phrase detection with perception-baseline weighting
- 12.2 Core Belief Extraction -- pattern matching for internal lies ("I am not enough", "I am broken", etc.), frequency tracking, confidence scoring, topic association
- 12.3 Shame Map Construction -- per-topic shame intensity tracking linking conversational subjects to shame activation and dominant core beliefs
- 12.4 Shame Masking Pattern Classification -- fear-masked, anger-masked, withdrawal-masked, people-pleasing-masked
- 12.5 Therapeutic Principle -- shame constructs the client's stated reality; the system detects the discrepancy between shame-constructed narrative and biometric truth without correcting the client directly

**Section 13: Predictability Model of Behavior**

- 13.1 Cyclical Pattern Detection -- day-of-week and period-of-month analysis from mood and metric history, minimum 28 entries + 3 cycle repetitions
- 13.2 Crisis Precursor Sequence Identification -- analysis of 3-5 metric snapshots preceding each logged crisis event, common sequence extraction, minimum 3 crises with 90% match
- 13.3 Trigger-Topic Mapping -- correlation of conversational topics with metric changes (anxiety, stress, shame, minimization), rolling average intensity tracking, minimum 10 occurrences
- 13.4 Reactivity Signature Classification -- fight/flight/freeze/fawn from linguistic + engagement indicators, exponential moving average, minimum 30 messages for classification
- 13.5 Reconsolidation Readiness Scoring -- composite of CEE proximity (C_emo in 0.3-0.7 range), engagement level, emotional charge, and trigger topic presence
- 13.6 Behavioral Prediction Generation -- forward-looking predictions from cyclical patterns and precursor activation, each with computed confidence level
- 13.7 Confidence Threshold Requirements -- minimum data requirements table for each pattern type before predictions can reach actionable confidence

**Section 14: Transgenerational Legacy Analysis**

- 14.1 Conversational Legacy Extraction -- detection of family-of-origin references paired with behavioral pattern keywords, storage of extracted patterns with source (father/mother/grandparent), pattern type, client quote, and timestamp
- 14.2 Cross-Member Behavioral Correlation -- comparison of perception baselines, reactivity signatures, and shame profiles across family members within a group therapy unit to detect transmitted patterns
- 14.3 Legacy Map Construction -- linking extracted conversation-based legacy patterns to observed behavioral patterns in the client and/or their family members
- 14.4 Clinical Application -- how transgenerational awareness informs therapeutic approach without blame assignment

**Section 15: Observer Protocol and Confidence-Gated Action System**

- 15.1 Core Principle -- the AI is the observer, not the solution; it helps clients discover hidden truths through curiosity rather than diagnosis
- 15.2 Tiered Confidence Levels -- 0-50% (learning/silent), 50-80% (observation/no reference), 80-95% (awareness/tone adjustment only), 95%+ (reflection/curiosity-based questions)
- 15.3 Action Gating -- only patterns at 95%+ confidence are included in the AI system prompt for therapeutic interaction; all patterns are available to the administrative console at all confidence levels
- 15.4 Minimum Data Requirements -- table of minimum observations per pattern type before confidence can reach actionable threshold
- 15.5 Therapeutic Framing Rules -- AI never presents observations as conclusions, uses curiosity framing ("I wonder...", "What do you make of..."), never corrects shame-based beliefs directly

### 3. New Independent Claims

**Claim 9 (new)**: Method for computing a crisis perception baseline by measuring distress discrepancy between objective biometric indicators and expressed linguistic sentiment, classifying subjects as minimizer/amplifier/normalizer/calibrated.

**Claim 10 (new)**: Method for detecting and tracking shame-based core beliefs through linguistic analysis of therapeutic conversation, computing a shame index from self-blame, unworthiness, and deflection indicators weighted by crisis perception baseline, and constructing a per-topic shame map.

**Claim 11 (new)**: Method for behavioral prediction using a Predictability Model of Behavior comprising cyclical pattern detection, crisis precursor sequence identification, trigger-topic mapping, and reactivity signature classification, with confidence-gated output requiring minimum thresholds before the AI acts on predictions.

**Claim 12 (new)**: Method for transgenerational legacy pattern detection through conversational extraction of family-of-origin behavioral references combined with cross-member behavioral correlation within therapeutic group units.

**Claim 13 (new)**: Method for confidence-gated therapeutic AI action comprising tiered visibility (administrative access at all confidence levels, AI therapeutic action only at 95%+ confidence) and an observer protocol constraining AI to curiosity-based reflection rather than diagnostic assertion.

### 4. New Dependent Claims

- Claim depending on new Claim 9: specific formula for objective_distress and expressed_distress
- Claim depending on new Claim 9: normalization index computation and its clinical significance
- Claim depending on new Claim 10: specific core belief patterns and shame masking classifications
- Claim depending on new Claim 10: shame map construction linking topics to dominant beliefs
- Claim depending on new Claim 11: reconsolidation readiness scoring formula
- Claim depending on new Claim 11: specific minimum data requirements (28 entries, 3 cycles, etc.)
- Claim depending on new Claim 12: family-of-origin keyword detection and pattern classification
- Claim depending on new Claim 13: specific confidence tier boundaries and therapeutic framing rules

### 5. New Data Structures (Appendix A)

**A.5 CrisisPerceptionProfile**

```
CrisisPerceptionProfile:
    distress_discrepancy:    float (-1 to 1)
    minimization_score:      float (0-1)
    sensitivity_score:       float (0-1)
    normalization_index:     float (0-1)
    perception_baseline:     enum (MINIMIZER, AMPLIFIER, NORMALIZER, CALIBRATED, CALIBRATING)
    calibration_count:       integer
    discrepancy_history:     list of DiscrepancyEntry
```

**A.6 ShameProfile**

```
ShameProfile:
    shame_index:             float (0-1)
    shame_baseline:          float (0-1)
    core_beliefs:            list of CoreBelief
    shame_map:               list of ShameMapEntry
    shame_masking_pattern:   enum (FEAR_MASKED, ANGER_MASKED, WITHDRAWAL_MASKED, PEOPLE_PLEASING_MASKED, UNKNOWN)
```

**A.7 PredictabilityModelOfBehavior**

```
PMB:
    cyclical_patterns:       list of CyclicalPattern
    crisis_precursors:       list of PrecursorSequence
    trigger_map:             list of TriggerEntry
    reactivity_type:         enum (FIGHT, FLIGHT, FREEZE, FAWN, MIXED)
    reactivity_indicators:   map of (type -> float 0-1)
    reconsolidation_readiness: float (0-1)
    legacy_patterns:         list of LegacyPattern
    predictions:             list of BehavioralPrediction
```

**A.8 TransgenerationalLegacyPattern**

```
LegacyPattern:
    source:                  string (father, mother, grandparent, family_general)
    pattern:                 string (emotional_suppression, caretaker_role, etc.)
    client_quote:            string
    extracted_at:            datetime
    reflected_in_client:     boolean
    cross_validated:         boolean
```

### 6. New Constants (Appendix B)

- Shame perception multipliers (minimizer: 1.3, normalizer: 1.5)
- Shame EMA alpha (0.12)
- Crisis perception EMA alpha (0.15)
- Confidence tier boundaries (0.50, 0.80, 0.95)
- PMB minimum data requirements (28 entries for cyclical, 3 crises for precursors, 10 for triggers, 30 for reactivity, 8 for beliefs, 5 for legacy)
- Reconsolidation readiness weights (therapeutic_range: 0.3, engagement: 0.25, emotional_charge: 0.25, trigger_topic: 0.2)

### 7. Update Abstract

Expand the abstract to mention crisis perception modeling, shame-based core belief detection, behavioral prediction with confidence-gated action, and transgenerational legacy analysis. Must stay under 150 words.

### 8. Renumber Existing Claims

Current dependent claims 9-30 must be renumbered to 14-35 (shifted by 5 to accommodate 5 new independent claims).

## Filing Strategy

This will be written as a **standalone second provisional patent application** in a new file, not as modifications to the original. Reasons:

- The original provisional (filed Feb 9, 2026) cannot be amended
- Filing a second provisional NOW gives the new innovations the earliest possible priority date
- When converting to the non-provisional (utility patent), both provisionals are cited as priority documents and the material merges into one patent
- The original material keeps the Feb 9 date; the new material gets today's filing date

The document will:

- Reference the original provisional by title, inventor, and filing date
- Use identical terminology and mathematical notation conventions
- Be self-contained with its own abstract, sections, claims, data structures, and constants
- Include a CROSS-REFERENCE section citing the original provisional
- Include the Oath and Declaration for Nathaniel James Nevedal

## Files Changed

- **NEW: [patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT_PROVISIONAL_2.md**](patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT_PROVISIONAL_2.md) -- Second provisional patent application covering Crisis Perception Model, Shame Layer, PMB, Transgenerational Legacy, Observer Protocol
- **[patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT.md](patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT.md)** -- NO CHANGES (original provisional stays as-filed)

