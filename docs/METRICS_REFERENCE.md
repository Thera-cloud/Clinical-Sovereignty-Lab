# Metrics Collection & Calculation Reference

This document describes every metric collected by the Sovereign Sanctuary platform, where each is computed, how the formulas differ across surfaces, and why those differences exist.

---

## 1. C_emo (Emotional Coherence)

C_emo measures a client's emotional coherence — how integrated and stable their emotional state is during interactions.

### Three Computation Pipelines

| Pipeline | Source | Formula | Range | Storage |
|----------|--------|---------|-------|---------|
| **Text-Chat** | `bridge_server.py` → `MetricsEngine.analyze_and_update()` | Exponential moving average: `c_emo = c_emo_prev * 0.7 + (0.5 + sentiment * 0.3) * 0.3` | 0.1–1.0 | `metrics.json` → `nevedal_state.C_emo` |
| **Voice Biometric** | `nevedal_engine.py` → `NevedalEngine.process_audio()` | Nevedal Formula: `C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G^(joint)/ℏ] × exp[-(γ_env + E_G^(joint)/ℏ) × t]` | 0.0–1.0 | `nevedal_metrics` table (PostgreSQL) |
| **Weekly Brief** | `nevedal_reports_api.py` → `weekly_coherence_brief()` | 7-day average of `nevedal_metrics.c_emo` | 0.0–1.0 | Computed on request |

### Where C_emo Appears

| Surface | Pipeline Used | Time Window |
|---------|---------------|-------------|
| Neural Interface (Stats panel) | Text-Chat | Latest snapshot from `metrics_data`/`metrics_update` |
| Coherence Dashboard (CURRENT STATE) | Voice Biometric | Latest `nevedal_metrics` row |
| Coherence Dashboard (Date chips) | Voice Biometric | Filtered by date range |
| Weekly Brief | Voice Biometric | 7-day average |
| PMB Reports | Text-Chat | Latest from `metrics.json` |
| Nevedal Research Lab | Voice Biometric | Direct from `nevedal_metrics` |

### Why They Differ

- The Text-Chat pipeline uses **sentiment analysis** of conversation text — it updates on every message exchange
- The Voice Biometric pipeline uses **acoustic features** (pitch, energy, speech rate, pause ratio) from live audio — it only updates during voice sessions
- The Weekly Brief averages **voice biometric readings** over 7 days, smoothing out session-by-session spikes

---

## 2. GAP (Growth Attunement Potential)

GAP measures a client's readiness for emotional growth.

### Two Computation Formulas

| Pipeline | Source | Formula | Range |
|----------|--------|---------|-------|
| **Text-Chat (Bridge)** | `MetricsEngine.analyze_and_update()` | `GAP = C_emo * 0.4 + E_warmth * 0.3 + engagement * 0.3` | 0.0–1.0 |
| **Coherence Dashboard (REST)** | `coherence_api.py` | `GAP = abs(C_emo - gamma_env)` | 0.0–1.0 |

### Why They Differ

- The **Bridge GAP** is a *composite wellness score* — it combines emotional coherence with relational warmth and engagement levels. Higher = better overall therapeutic attunement.
- The **Coherence Dashboard GAP** is a *physics-derived gap* — it measures the **distance** between C_emo and the environmental dampening factor (gamma_env). It represents how far the client's coherence has risen above environmental resistance. Lower gamma with high C_emo = larger positive gap.

### Where GAP Appears

| Surface | Formula Used |
|---------|-------------|
| Neural Interface (Stats panel) | Bridge composite |
| Coherence Dashboard | Physics-derived |
| PMB Reports | Bridge composite |
| Nevedal Research Lab | Physics-derived |
| Weekly Brief | Not directly shown |

---

## 3. Quantum (Overall Wellness Score)

Quantum is a holistic wellness score combining multiple dimensions.

### Two Computation Formulas

| Pipeline | Source | Formula | Range |
|----------|--------|---------|-------|
| **Text-Chat (Bridge)** | `MetricsEngine.analyze_and_update()` | `Quantum = 0.3 * C_emo + 0.25 * GAP + 0.25 * engagement + 0.2 * (1 - anxiety_level)` | 0.0–1.0 |
| **Coherence Dashboard (REST)** | `coherence_api.py` | `Quantum = (C_emo + p_ent) / 2.0` | 0.0–1.0 |

### Why They Differ

- The **Bridge Quantum** is a *weighted therapeutic composite* factoring in coherence, growth potential, engagement, and inverse anxiety. It prioritizes clinical relevance.
- The **Coherence Dashboard Quantum** is a *quantum physics analogue* averaging emotional coherence with perceptual entropy (p_ent). It represents the average "quantum state" of the client's emotional field.

### Where Quantum Appears

| Surface | Formula Used |
|---------|-------------|
| Neural Interface (Stats panel) | Bridge weighted composite |
| Coherence Dashboard | Physics average |
| PMB Reports | Bridge weighted composite |
| Nevedal Research Lab | Physics average |

---

## 4. CEE Moments (Corrective Emotional Experiences)

CEE moments are instances where a client's emotional state shifts significantly — moments of breakthrough or deep connection.

### Two Detection Mechanisms

| Mechanism | Source | Trigger Criteria | Storage |
|-----------|--------|-----------------|---------|
| **Voice Biometric** | `nevedal_engine.py` | `cee_window = True` when acoustic features indicate sustained high coherence | `nevedal_metrics.cee_window` (boolean per row) |
| **Text-Chat Mismatch** | `MetricsEngine.analyze_and_update()` | `delta >= 0.08` or `(c_emo >= 0.75 AND prev_cemo < 0.75)` | `metrics.json` → `nevedal_state.cee_experiences[]` + `nevedal_metrics` (as of v2) |

### What Changed (v2 — March 2026)

Text-chat CEE events now also write to `nevedal_metrics` with `cee_window = TRUE`, so the Weekly Brief and Coherence Dashboard count CEE moments from **both** voice sessions and text chat.

### Where CEE Count Appears

| Surface | Sources Counted |
|---------|----------------|
| Weekly Brief | Voice (`nevedal_metrics.cee_window`) + Text-chat (`cee_experiences` from `metrics.json`) |
| Coherence Dashboard (CEE Windows) | History entries where `C_emo >= 0.75` + `cee_experiences` from `nevedal_state` |
| Neural Interface | Not directly shown (reflected in C_emo trend) |
| Nevedal Research Lab | `nevedal_metrics.cee_window` |

---

## 5. Session Count

### Three Definitions

| Surface | Definition | Source |
|---------|-----------|--------|
| Neural Interface (Stats) | **Message exchanges analyzed** — increments per `analyze_and_update()` call | `metrics.json` → `nevedal_state.session_count` |
| Weekly Brief | **Actual therapy sessions** (rows in `sessions` table, including AI + Coach) | `sessions` table, `started_at >= NOW() - 7 days` |
| Coherence Dashboard | **Voice biometric data points** (rows in `nevedal_metrics`) | `nevedal_metrics` row count |

### Why They Differ

- The Neural Interface's "500 sessions" means 500 text messages were analyzed, not 500 therapy sessions
- The Weekly Brief counts actual session rows (with `started_at`/`ended_at` timestamps)
- The Coherence Dashboard counts individual voice biometric readings (multiple per session)

---

## 6. Mood

### Detection

Mood is detected via keyword analysis in `MetricsEngine.analyze_and_update()`:

| Mood | Trigger |
|------|---------|
| happy | Positive word count > negative word count |
| sad | Negative word count > positive word count |
| neutral | Positive ≈ negative |

Positive words: thank, good, great, better, happy, love, hope, wonderful, amazing, blessed, grateful, excited, proud, peaceful, calm, strong, clear

Negative words: sad, hurt, angry, scared, anxious, depressed, lonely, hopeless, worthless, tired, empty, overwhelmed

### Mood Emoji Mapping (Neural Interface)

| Mood | Emoji |
|------|-------|
| happy | 😊 |
| neutral | 😐 |
| sad | 😔 |

---

## 7. E_warmth (Emotional Warmth)

Measures the relational warmth in conversations.

| Source | Formula |
|--------|---------|
| `MetricsEngine.analyze_and_update()` | Count of warmth words (thank, appreciate, help, support, kind, care) × 0.1, accumulated |

Stored in `metrics.json` → `nevedal_state.E_warmth`. Range: 0.0–1.0.

---

## 8. Engagement

Measures how actively the client participates in conversations.

| Source | Formula |
|--------|---------|
| `MetricsEngine.analyze_and_update()` | `min(1.0, word_count / 50) * 0.5 + (0.5 if question mark present else 0.3)`, then averaged with previous |

Stored in `metrics.json` → `nevedal_state.engagement`. Range: 0.0–1.0.

---

## 9. Velocity

Rate of change in GAP (Growth Attunement Potential).

| Source | Formula |
|--------|---------|
| `MetricsEngine.analyze_and_update()` | `velocity = current_GAP - previous_GAP` |

Range: -1.0 to 1.0. Positive = improving, negative = declining.

---

## 10. Anxiety Level, Depression Indicators, Stress Level

These are keyword-based detectors that run on every text exchange.

| Metric | Keywords | Scale Factor |
|--------|----------|-------------|
| Anxiety | anxious, nervous, worried, panic, racing, tense | × 0.15 per match |
| Depression | hopeless, worthless, empty, numb, tired, no energy | × 0.15 per match |
| Stress | stressed, overwhelmed, pressure, deadline, too much | × 0.15 per match |

Range: 0.0–1.0. Stored in `metrics.json` → `nevedal_state`.

---

## 11. Risk Level

Composite risk assessment derived from multiple metrics.

| Level | Trigger |
|-------|---------|
| LOW | Default |
| MEDIUM | `depression_score > 0.6` OR `anxiety_level > 0.7` |
| HIGH | `depression_score > 0.8` |
| CRITICAL | Crisis keywords detected in text |

---

## 12. Voice Biometric Metrics (Nevedal Formula Only)

These metrics are only collected during voice sessions via `NevedalEngine.process_audio()`:

| Metric | Description | Source |
|--------|-------------|--------|
| p_ent (Perceptual Entropy) | Information richness of voice signal | Pitch variance + spectral analysis |
| T_tunnel (Tunnel Coefficient) | Emotional barrier permeability | Voice pause patterns |
| gamma_env (Environmental Dampening) | External emotional resistance | Background noise + speech disruption |
| E_G^(joint) (Joint Emotional Energy) | Combined therapist-client field energy | Dyad analysis (when available) |
| cee_window | Whether a Corrective Emotional Experience is occurring | Sustained high coherence threshold |
| cee_duration_seconds | Duration of the CEE window in seconds | Timer |

---

## Data Storage Locations

| Store | Purpose | Metrics Held |
|-------|---------|-------------|
| `metrics.json` (per-client file) | Text-chat metrics, bridge-computed | C_emo, GAP, Quantum, mood, anxiety, depression, stress, engagement, session_count, cee_experiences, history snapshots |
| `nevedal_metrics` (PostgreSQL) | Voice biometric readings + text-chat CEE events | c_emo, p_ent, t_tunnel, gamma_env, e_g_joint, cee_window, cee_duration_seconds |
| `client_metrics` (PostgreSQL) | Periodic sync of bridge metrics | All `nevedal_state` fields as JSONB, plus indexed columns for c_emo, gap, quantum, etc. |
| `sessions` (PostgreSQL) | Session lifecycle tracking | started_at, ended_at, session_type, duration_seconds |
| `memory.json` (per-client file) | Conversation transcripts | user text, ai response, timestamp, session_id |

---

## Surface-to-Pipeline Map

| Surface | C_emo | GAP | Quantum | CEE | Sessions |
|---------|-------|-----|---------|-----|----------|
| Neural Interface (Stats) | Text-Chat | Bridge composite | Bridge weighted | Not shown | Message count |
| Coherence Dashboard | Voice Biometric | Physics (`abs(c_emo - gamma)`) | Physics (`(c_emo + p_ent) / 2`) | Both voice + text | Biometric data points |
| Weekly Brief | Voice 7-day avg | Not shown | Not shown | Both voice + text | Actual session rows |
| PMB Reports | Text-Chat | Bridge composite | Bridge weighted | Text-chat only | Message count |
| Nevedal Research Lab | Voice Biometric | Physics | Physics | Voice only | Biometric data points |

---

## Weekly Brief Data Sources (v2)

The Weekly Brief now pulls from **5 data sources** to generate a deeply personal check-in:

| Source | What It Provides | File/Table |
|--------|------------------|------------|
| `nevedal_metrics` (PG) | C_emo trend, voice CEE windows | PostgreSQL |
| `sessions` (PG) | Session count (AI + Coach), session types | PostgreSQL |
| `memory.json` | Conversation transcripts, relational themes | File system |
| `metrics.json` | Text-chat CEE experiences | File system |
| `coach_session_notes.json` | Coach observations, homework, therapeutic notes | File system |

The Azure OpenAI prompt includes actual conversation excerpts, detected topics, and coach notes so Little Nate can reference specific shared experiences rather than producing generic wellness advice.
