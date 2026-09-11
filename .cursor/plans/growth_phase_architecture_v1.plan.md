# Growth-Phase Architecture v1 — heal → thrive for Little Nate

Status: implemented locally (uncommitted), flag-gated `ENABLE_GROWTH_PHASE` (default off). Trigger incident: LetsGoLisa — `coaching_boundary_guard` regex inserted trauma/wound boundary copy for weeks while she was celebrating healing; no heal→thrive phase model existed.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Phase promotion | LN auto-promotes via healing-cycle signal; coach notified (`client_growth_phase_history` + coach roster badge). Coach may override/release. |
| 2 | Scope | All clients. `DEFAULT_PHASE=process` until signal says otherwise. |
| 3 | Reminders | Email only (`ThriveCoachAgent` → SendGrid; replies parsed by `thrive_reply_processor` via `sendgrid_inbound`). |
| 4 | Strengths inventory | In-house, free. 24-strength LN-led interview (`strengths_interview.py`), Clifton-domain roll-up; no VIA licence, no survey UI. |
| 5 | Live-session guidance | Both surfaces: Coach Command thrive brief section + Studio host console rail. **Coach eyes only** (INV-6: callers are de-identified, case talk barred on air — client guidance never enters LN's on-air prompt). |
| 6 | Reuse | Mission/journey/quest (`nate_commitments`) extended with `focus_area/started_at/completed_at/progress_pct/growth_phase/coached_by` — no parallel goal table. |
| 7 | Entry | LN greeting on app open (600 / 300–500 / ≤900 chars) + Welcome box keeps Continue Journey / New Quest / Just Chat and gains **Thera-World** hot button (pulls latest panel, activates ask-Nate-about-panel). |

## Phase model (`services/thrive/growth_phase.py`)

`stabilize → process → consolidate → thrive → generative`. Coaching phases = {thrive, generative}; bridge = {consolidate}. Sub-states: `working_through` (72h, client asked to work something through → LN shifts back to therapeutic register) and `crisis_hold` (48h, CRISIS trip). `effective_phase()` collapses sub-states to `process`.

`FrameworkMap` per phase: EFT stage/steps, EFIT, NICC (thrive/drive/express), Gottman, attachment, post-EMDR reconsolidation stance, PTG domains (Tedeschi & Calhoun), Antifragile stance, time focus (past→present vs present→future), core questions ("What do you want to build now / which goals / what have you completed / what can you complete today"), `ln_register`, `coach_focus`.

## Data (migration `434_growth_phase.sql`, additive, applied manually on GREEN)

`client_growth_phase`, `client_growth_phase_history`, `client_focus_areas`, `client_practice_log`, `client_strengths`, `ln_entry_greetings`, `thrive_reminders`; `nate_commitments` +6 columns. All keyed by canonical `users.username` (`_identity_resolver.resolve_username`).

## Runtime flow

1. Bridge (`bridge_server.py` ~10504, `# QUANTUM-CRYSTAL-ARCH`, flag-gated): `phase_resolver.note_turn` → `profile["growth_phase"]` → if coaching: `practice_tracker.focus_state` → `detect_completion`/`log_completion` → `persona.build_phase_addendum` appended to system prompt. Second hook ~11126: CRISIS → `note_turn(crisis=True)`.
2. Post-LLM: `coaching_boundary_guard.evaluate(..., growth_phase, growth_sub_state)` now phase-gated + negation/celebration aware; trips persisted for observability.
3. `healing_cycle.compute_healing_signal` (predictability + cycle detection + crystals) → `phase_resolver.evaluate` promotes/demotes with streak hysteresis; coach override wins.
4. `focus_state` supplies areas, goals (trajectories: start, target, projected completion, on_track), strengths, `thrive_memory` (phase-aware recall of `thrive`+`coaching` user crystals, recall-reinforced), interview state.
5. `persona._focus_lines` renders focus areas, live goal, strengths, growth memory, and — when no signature yet — one interview question per turn.
6. `strengths_interview.observe_turn` (fire-and-forget from `note_turn`, coaching/consolidate only, never during sub-states) tallies first-person strengths; ≥3 distinct across ≥2 turns → `client_strengths(method='ln_interview')` + `thrive` crystal.
7. Practice harvests (≥40 chars) and completed goals forge `thrive` crystals (`crystallize_thrive`, user-scoped, never global).
8. `ThriveCoachAgent`: due-practice/goal email reminders, phase evaluations, coach notification on transition; caps via `THRIVE_MAX_EMAILS_PER_TICK`, `THRIVE_MAX_EVALS_PER_TICK`.
9. `entry_greeting.py`: three-part greeting (tz/time-of-day/habits chit-chat ≤600; goals or last trauma topic 300–500; 1–3 directions with reasoning ≤900) logged to `ln_entry_greetings`.

## Focus areas → anchor practices (`practice_catalog.py`)

Daily Happiness → Three Good Things · Future Direction → Best Possible Self · Self-Compassion & Confidence → Strength Dates · Handling Stress → Self-Compassion Break. Voice echoes PERMA(-V), Broaden-and-Build, MSC, Appreciative Inquiry.

## REST (`routers/thrive_api.py`, prefix `/api/thrive`, 23 routes)

health · catalog · frameworks · `{u}/entry-greeting` (+`/opened`) · `{u}/phase` · healing-signal · focus · goals · practice-log · reminders · strengths · brief · practices/complete|adopt|{key}/retire · goals (+`/{id}/progress`) · strengths POST · phase/override|release|evaluate · `coach/{coach|me}/roster`. Auth: client self, assigned coach, admin.

## UI

- Client (`updated_screens.dart`): `_fetchEntryGreeting`, Welcome box Thera-World `_recapBtn` → `_theraWorldAskMessage(panelId)`.
- Coach Command: roster phase badge, `_buildThriveBriefSection` (phase, override, goals trajectories, practices, strengths, session guidance).
- Studio (`coach_sovereign_studio_tab.dart`): "SESSION GUIDANCE · COACH EYES ONLY" rail; roster dropdown → `/brief`.

## Crystal domain

`thrive` added to `crystal_domains.ORGANIC_EXTRA` (rule `crystal-intelligence-integrity.mdc` §4 updated same commit).

## Remaining (gp10)

Auditor + trust baseline (5-location sync) for thrive endpoints · offline tests · CI gate · commit own bridge hunks only (pre-existing `_select_max_tokens` change is not mine) · GREEN `git pull` + `safe_deploy.sh backend` outside HH:50–HH:10 audit windows · apply 434 · `ENABLE_GROWTH_PHASE=true` · service count check · Flutter deploy + CF purge · E2E with LetsGoLisa.
