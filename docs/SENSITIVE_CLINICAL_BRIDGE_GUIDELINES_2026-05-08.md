# Sensitive Clinical Bridge — Foundational Guidelines

**Version**: 1.0 (foundation doc, paired with v1.3 plan)
**Date**: 2026-05-08
**Audience**: Clinicians, supervising coaches, auditors, engineers

**Doc-set role**: This is the **clinical authoritative** document. For the technical/spec
authority see plan v1.3 (`docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`)
§Gap A–S. For deployment & rollback see `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md` §Phase 1–6.
When clinical content here conflicts with the plan, this doc wins; when technical
content here conflicts with the plan, the plan wins.

**Companion docs**:
- `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md` (v1.3 plan — spec authority)
- `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md` (rollback + cohort playbook — operational authority)
- `docs/LITTLE_NATE_REGISTER_GUIDELINES_2026-05-06.md` (existing register taxonomy)
- `docs/LITTLE_NATE_GUIDELINES_AUDIT_2026-05-06.md` (existing audit baseline)

---

## 1. Purpose and Scope

### 1.1 What this system is

The Sensitive Clinical Bridge is the orchestration layer that lets Little Nate hold space for two clinical populations whose disclosures live outside the assumptions of the existing therapeutic controller:

1. **Physical intimacy work** — purity-culture wounds, infidelity recovery, sexual trauma history, body-image / embodiment trauma, dissociation during somatic invitation.
2. **Trafficking-survivor bridge support** — pre-clinical companioning for survivors who do not yet have, cannot reach, or have been failed by formal trauma care. Includes survivors actively in danger, survivors in the recruiter role under coercion, minor survivors, and dual-diagnosis survivors.

The bridge sits between disclosure detection and response generation. It evaluates each disclosure against ten signal layers, returns a structured `BridgeDecision`, and lets the existing therapeutic controller render the response. It never generates clinical text directly.

### 1.2 What this system is NOT

- **Not a treatment substitute.** The bridge holds space and routes to specialized resources. It does not deliver EMDR, IFS, somatic therapy, addiction treatment, or legal counsel.
- **Not a surveillance system.** Detectors are clinical signal classifiers, not behavior policing. Output is audit-only when below threshold; only above-threshold signals shift register.
- **Not a mandatory reporter substitute.** Reporting decisions remain with the licensed clinician of record. The bridge surfaces patterns that a reasonable clinician would want to see; it does not auto-file reports except where TVPA / state-law thresholds are objectively crossed (active danger, minor exploitation).
- **Not a replacement for the existing therapeutic controller.** It augments. The controller still owns response composition.

### 1.3 Populations expressly in scope

- Adult trafficking survivors (post-trafficking and active-situation).
- Minor trafficking survivors (additional dual-guardian and mandatory-reporting protections).
- Adults processing purity-culture and infidelity wounds.
- Adults with sexual trauma histories navigating embodiment.
- Survivors with co-occurring substance use.
- Survivors in legal processes (criminal, T-visa, U-visa, civil, custody, expungement, protective order).
- Survivors with polyvictimization layers (childhood abuse, religious trauma, prior partner violence, etc.).

### 1.4 Populations expressly out of scope (escalate to human only)

- Active suicidal ideation with plan and means → existing crisis pathway, no bridge involvement.
- Active homicidal ideation → existing crisis pathway.
- Substance overdose in progress → emergency services hand-off, not therapeutic register.
- Acute psychosis → existing crisis pathway.

The bridge defers to existing crisis infrastructure for these. Where they co-occur with bridge-relevant disclosures, the crisis pathway always wins.

---

## 2. Foundational Ethics

These commitments precede every technical decision. When a feature collides with an ethical commitment, the feature loses.

1. **Survivor sovereignty.** The survivor is the authority on their own experience. The system does not interpret, diagnose, or rank traumas.
2. **Holding before fixing.** First-pass response is presence. Specialized-resource pointers come only when the survivor has signaled readiness or when state-law thresholds compel disclosure.
3. **No re-traumatization.** Detailed-disclosure prompts to activated users are forbidden. Trauma-meaning interpretation by Nate is forbidden. Embodiment invitations during repair phase are forbidden. The validator enforces.
4. **No collusion with coercion.** Re-engagement language from the survivor is met with harm-reduction holding, not validation of return-to-trafficker logic, and not moralizing.
5. **No pathologization of parenting.** Survivors who are parents are not assessed as risks to children unless a specific reportable threshold is crossed. Parenting-while-traumatized is not a child protection concern.
6. **Coach + clinician dual-control.** No solo escalation to safe_silence_mode. No solo modification of acuity tier. No solo addition of codewords. Two-person rule.
7. **Audit-trail integrity.** Every bridge decision is logged. Logs are 7-year retained, IMMUTABLE in db_maintenance_agent, RBAC-gated, and contain no raw user or AI text.
8. **Validator supremacy.** If `nate_response_validator` blocks a draft response, the bridge does not override. Better to be silent than to harm.
9. **Cultural humility.** Religious-trauma, cultural-context, and communal-shame survivors get domain-aware response sets, not generic Western individual-therapy framings.
10. **Right of access.** Survivors can export their own data per HIPAA 45 CFR 164.524 (Gap N).

---

## 3. Architecture at a Glance

```
User disclosure
      │
      ▼
┌─────────────────────────────────────────────┐
│   sensitive_clinical_bridge.evaluate_       │
│   disclosure()  ◄── single integration seam │
└──────────────┬──────────────────────────────┘
               │
   18 evaluation steps (Phase 4):
   ├── 1. Coercion pattern scan
   ├── 2. Dissociation delta vs N-3..N-1
   ├── 3. Introjection / voice-shift mirror (Gap 1)
   ├── 4. Linguistic arousal load (Gap 3)
   ├── 5. Trigger date proximity check (Gap 5)
   ├── 6. Re-engagement pattern check (Gap 7)
   ├── 7. Trafficking disclosure classification (Gap G)
   ├── 8. Codeword scan (Gap 2)
   ├── 9. Polyvictim load aggregation (Gap 8)
   ├── 10. Legal-event proximity (Gap 9)
   ├── 11. Substance co-occurrence routing (Gap 10)
   ├── 12. Embodiment phase filter (Gap 6)
   ├── 13. Thalamic novelty gate (Gap 4)
   ├── 14. Jurisdiction policy (Gap L)
   ├── 15. safe_silence_mode evaluation (Gap A + Gap M)
   ├── 16. Cultural / RJ register selection (Gap R + Gap S)
   ├── 17. Mandatory-reporting trigger evaluation
   └── 18. BridgeDecision assembly
               │
               ▼
   therapeutic_controller.prepare_therapeutic_context()
               │
               ▼
   Response rendering (existing pipeline)
               │
               ▼
   nate_response_validator (Layer 8 lexicon — Gap D)
```

All ten signal layers are independent. A failure or false-positive in one cannot cascade. Every step has a per-detector feature flag (Gap F) for canary rollout and emergency disable.

---

## 4. Crystal Domains

Five new canonical crystal domains are reserved (added to the application-layer canonical list in `bulk_crystal_ingestion.py`, not as a DDL CHECK constraint — see migration 202 notes):

| Domain | Purpose |
|---|---|
| `intimacy_clinical` | Adult intimacy wound / repair patterns |
| `purity_culture` | Religious / cultural purity wound holding |
| `infidelity_recovery` | Betrayal trauma, attachment rupture |
| `sexual_trauma` | Sexual trauma history and embodiment |
| `trafficking_trauma` | Trafficking-survivor bridge support |

Sub-domains (Phase 5):
- `embodiment_repair_crystals` (Gap 6)
- `reengagement_holding_crystals` (Gap 7)
- `dual_diagnosis_trafficking` (Gap 10 — Najavits Seeking Safety)
- `child_trafficking_minor_specific` (Gap O)
- `survivor_parenting_holding` (Gap P)
- `restorative_justice_companioning` (Gap Q)
- `cultural_context_holding` (Gap R)

Crystals carry a `clinical_caution_tags` array enumerating any cautions a clinician should know before recall (e.g., `["activates_purity_wound", "embodiment_invitation_present"]`). Recall pre-filters crystals whose cautions conflict with the active register.

---

## 5. Register Variants

The therapeutic controller gains 4 base + 8 extended register variants (Phase 3):

**Base (Gap 6 / 10 / 7 / dissociation):**
- `purity_wound`
- `betrayal_response`
- `embodiment_repair`
- `dissociation_grounding`

**Extended (Gaps 7 / G / O / P / Q / 10):**
- `harm_reduction_reengagement` — non-collusive, non-moralizing
- `dual_diagnosis_holding` — trauma + addiction simultaneously
- `active_situation_grounding` — immediate safety focus, no rumination invitation
- `recruiter_holding` — non-judgmental, no minimization
- `developmental_grounding` — minor-survivor age-appropriate
- `parenting_support_no_pathologization` — survivor-as-parent
- `rj_companioning` — restorative-justice survivor support
- `cultural_context_holding` — religious / collectivist / non-Western framings

**Banned phrases gain three additions** (Phase 3):
- "Where do you feel that in your body" (when embodiment_phase = repair)
- "Tell me more about what happened" (when activation_load > threshold)
- "What does that mean to you" (Nate-volunteered interpretation of trauma meaning)

Existing banned phrases from `LITTLE_NATE_REGISTER_GUIDELINES_2026-05-06.md` remain in force.

---

## 6. Codewords (Gap 2 + Gap K)

### 6.1 What codewords do

Per-user codewords, set by the treating clinician via the clinician portal (Gap B), let a survivor signal acuity escalation **without changing Nate's outward behavior**. The match upgrades the internal acuity tier and fires a coach alert. The conversation continues without breaking the survivor's experienced sense of safety.

### 6.2 Storage

- SHA-256 hashed with per-codeword salt (32-char hex, `secrets.token_hex(16)`).
- Plaintext NEVER stored, NEVER logged, NEVER returned by any API.
- Comparison uses `hmac.compare_digest` (constant-time).
- Match scope: lower-cased, punctuation stripped, exact phrase match against the hash.

### 6.3 Codeword + mandatory reporting interaction (Gap K)

A clinician may flag a codeword as `triggers_mandatory_reporting=TRUE`. When such a codeword matches, the bridge fires `mandatory_reporting` evaluation in addition to the standard coach alert. This lets a survivor design a codeword that means "please report this to authorities" without saying so explicitly.

### 6.4 Active codeword precondition for safe_silence_mode

A user MUST have at least one active codeword before safe_silence_mode can be activated (Gap A). Without an emergency channel, silencing 72-hour outreach is unsafe.

---

## 7. safe_silence_mode (Gap A + Gap M)

### 7.1 State machine

```
inactive  ──[coach proposes]──►  pending_approval  ──[admin approves]──►  active
   ▲                                     │                                     │
   │                                     │                                     │
   │                              [admin rejects]                              │
   │                                     │                              [25-day warning]
   │                                     ▼                                     │
   │◄──────────[reverted]──────────  inactive  ◄──[30-day expiry auto-revert]──┘
```

### 7.2 Two-step gate

The orchestrator MAY NOT auto-set `safe_silence_mode`. The flow is:
1. Coach proposes via clinician portal.
2. Admin or supervising clinician approves in a separate session.
3. Precondition check: at least one active codeword exists.
4. State transitions to `active`. `expires_at` set to `approved_at + 30 days`.

### 7.3 25-day expiry warning + auto-revert (Gap M)

`nate_checkin_agent` runs a daily scan of `safe_silence_mode_active_users`:
- At `approved_at + 25 days` (and `expiry_warning_sent_at IS NULL`): send warning to clinician + coach. Set `expiry_warning_sent_at`.
- At `expires_at`: auto-revert to `inactive`. Resume normal 72-hour check-in cadence. Send notification.
- Clinician may re-propose at any time.

### 7.4 Welcome-back template

When the survivor returns to conversation after a silence period, Nate uses the `welcome_back_without_questioning_absence` template. No "where have you been," no "I noticed you were quiet." Just presence and continuity.

---

## 8. Trigger Dates (Gap 5)

Clinician-set significant dates per user. On a match within ±1 day:
- Default register shifts to `predictability_continuity`.
- Thalamic Novelty Gate forced ON.
- Pre-emptive coach alert dispatched at 00:00 UTC of the trigger date.
- `recurring_annually` (default TRUE) means the comparison is on `(month, day)` only.

Date types: `escape_anniversary`, `first_exploitation`, `legal_outcome`, `related_death`, `custody_outcome`, `court_appearance`, `medical_anniversary`, `other`.

`notes_redacted` field MUST contain only sanitized notes — no event details that could re-traumatize on coach view. Validator screens before insert.

---

## 9. Polyvictimization Layers (Gap 8)

Layered trauma histories interact. TMC computes cumulative load via two new signals:
- `polyvictimization_layer_count` (normalized 0..1)
- `polyvictim_severity_load` (weighted sum, normalized; weights: low=1, moderate=2, high=4, critical=6)

Crystal recall cross-references active layers to prefer crystals tagged with overlapping `layer_relevance` markers. PGSD ingests layer interactions; `cycle_detection_engine` spans across layers.

CRISIS escalation: if `polyvictim_severity_load > 0.7` AND any active dissociation or coercion signal, the bridge upgrades to CRISIS regardless of single-signal severity.

---

## 10. Legal Process Awareness (Gap 9)

When `now()` falls within ±72h of any active `user_legal_status.next_event_date`:
- Pre-emptive register shift to `predictability_continuity`.
- Inserted scope statement: *"I'm not legal counsel — your attorney is the right place for case-specific guidance."*
- `specialized_resources` routes to `legal_trafficking` domain (CAST LA, Polaris legal directory, T-visa pathway pointers).

Case types: `criminal_against_trafficker`, `t_visa`, `u_visa`, `civil`, `custody`, `expungement`, `protective_order`, `other`.

`attorney_contact_redacted` may contain organization name only — never direct PII. Validator screens before insert.

---

## 11. Mandatory Reporting (Phase 3)

A new `ReportingTrigger.TRAFFICKING` is added. Triggers:
1. Active-situation disclosure (Gap G `active_situation` classification) — fires regardless of state mandatory reporting because most state laws cover active danger.
2. Imminent-danger disclosure (Gap G `imminent_danger`) — emergency escalation.
3. Minor-survivor anything (Gap O) — auto-fires per child protection statutes.
4. Codeword with `triggers_mandatory_reporting=TRUE` matched (Gap K).
5. Survivor-as-recruiter role disclosed for a minor (Gap G `survivor_as_recruiter` involving a minor target).

Resource block uses `specialized_resources` typed registry (NHTH 1-888-373-7888, BeFree TXT 233733, Polaris). Hardcoded DV hotline replaced.

Jurisdiction policy (Gap L) overlays state-specific reporting requirements. The current jurisdiction is read from `users.profile_data.jurisdiction_state` (default Illinois). When unknown, locale fallback applies (most-protective default).

---

## 12. Coach Handoff (Phase 3)

`coach_override_protocol.py` extensions:
- New focus domains: `intimacy_clinical`, `trafficking_pre_clinical`, `embodiment_repair`, `legal_process`, `polyvictim_layers`.
- Redacted handoff payload: includes signal summaries, register history, active codeword count (NOT the codewords themselves), trigger-date proximity, polyvictim layer tags, legal-event proximity. NEVER includes raw transcripts.
- Immediate-alert thresholds for `trafficking_disclosure` (active or imminent).
- New alert tier `reengagement_alert` distinct from generic crisis (Gap 7).

---

## 13. Audit Logging

`sensitive_bridge_log` (migration 202):
- Append-only. No UPDATE, no DELETE in normal operation.
- 7-year retention per Illinois MHDDCA 740 ILCS 110 + HIPAA 45 CFR 164.530(j).
- IMMUTABLE in `db_maintenance_agent.IMMUTABLE_TYPES` (added in Phase 3).
- RBAC-gated by `access_classification`:
  - `clinician_only` — treating clinician only.
  - `clinician_and_admin` — both.
  - `admin_only_redacted` — admin-redacted view (clinician notes stripped).
- `payload_json` and `decision_summary` MUST NOT contain raw user or AI text. Pre-insert PII screen by `nate_response_validator`.
- Manual purge requires admin + WebAuthn YubiKey tap.

Thirty-three event types are enumerated in the v1.3 migration `CHECK` constraint (migration 202).
Adding a new event_type requires (a) follow-up migration that drops + re-adds the CHECK
constraint with the new value, (b) update to this guidelines doc, and (c) 5-location
trust-enforcer sync if the auditor counts events.

---

## 14. Clinician Portal (Gap B — Phase 5)

A new Flutter screen `sensitive_clinical_profile_screen.dart` and REST router `sensitive_profile_api.py` give the treating clinician one place to manage:
- Codewords (set / deactivate; never view plaintext after creation).
- Embodiment phase (repair / transitioning / ready).
- Novelty-gate threshold (per-user override; default 0.2 trafficking, 0.3 general).
- Arousal-load threshold.
- Substance-use status.
- Polyvictimization layers.
- Legal status entries.
- Trigger dates.
- safe_silence_mode (with two-step gate).

All mutations are logged as `sensitive_profile_mutation` events. Clinician role gated via `require_clinician_for_user` dependency.

---

## 15. Client / Survivor Expectations

These are the contractual promises the system makes to survivors. Engineers and clinicians treat these as inviolable.

1. **You are not surveilled.** The detectors classify clinical signals, not behaviors. They exist to help Nate hold space for you, not to report you.
2. **Your codewords are private.** Even your clinician cannot retrieve them after creation. They can only verify whether one matched, and that verification leaves an audit trail.
3. **Your data is exportable.** Per HIPAA 45 CFR 164.524, you can request your own audit trail at any time (Gap N — Phase 5).
4. **Your absence is welcomed back without questioning.** If you go quiet for 72 hours and return, Nate will not ask where you've been.
5. **Your parenting is not pathologized.** Being a survivor and being a parent are not in tension in this system.
6. **Your culture is held.** Religious-trauma, collectivist-context, and communal-shame are first-class register variants — not afterthoughts.
7. **Your re-engagement is met with harm reduction.** If you are pulled back toward someone who hurt you, Nate will hold space, not moralize, and not collude.
8. **Your safety wins.** Where state law compels disclosure, that disclosure happens. Where state law does not, your sovereignty wins.

---

## 16. Coach / Clinician Expectations

1. **You own clinical decisions.** The bridge surfaces signals. You decide what to do with them.
2. **Two-person rule.** No solo escalation of acuity tier, no solo addition of codewords, no solo activation of safe_silence_mode.
3. **Audit-trail review.** You are expected to review `sensitive_bridge_log` events for your active clients per your organization's supervision cadence.
4. **Lexicon authoring.** Validator-extension lexicon updates require two-clinician review before merge (Gap D).
5. **Cohort gating.** Per-detector feature flags let you withhold a detector from a client until you have reviewed it for that client (Gap F).
6. **Crystal authoring.** New crystals in sensitive domains require clinician sign-off via the bulk-ingestion review workflow (Phase 5).
7. **Resource-list freshness.** Resource registry entries (NHTH, BeFree, Polaris, AASECT, EMDR/SE/IFS/EFT/Gottman locators) are reviewed quarterly. You are the steward.

---

## 17. Engineer Expectations

1. **Single integration seam.** Only `therapeutic_controller.prepare_therapeutic_context()` calls `sensitive_clinical_bridge.evaluate_disclosure()`. No other call site.
2. **Protected files unchanged.** `bridge_server.py` is untouched by this work. The orchestrator wires through the controller.
3. **Feature flags first.** Every new detector ships behind a flag in `GAP_FEATURE_FLAGS`. Default OFF until clinician sign-off per gap.
4. **No raw text in logs.** Pre-insert PII screen by validator. CI lint check forbids any direct INSERT into `sensitive_bridge_log` that bypasses the screen.
5. **Latency budgets.** Orchestrator p95 < 200ms. Codeword check p95 < 5ms. CI bench enforces.
6. **5-location sync for the auditor.** Adding the 29th auditor (Phase 6) follows `trust-enforcer-architecture.mdc` exactly.
7. **Migration ordering is locked.** 202 → 203 → 204 → 205 → 206 → 207 → 208. Do not reorder.
8. **Shadow mode for 14 days.** Orchestrator runs but never modifies register output, only logs what it WOULD have done. Clinician reviews each shadow decision (Gap I — Phase 6).
9. **Per-phase observation window.** 7 days minimum between phase advancement. No exceptions for "just one more thing."
10. **Auto-disable on >5% false-positive rate.** Per gap, over 7 days, with admin alert (Gap F).

---

## 18. What to Do When X Happens

| X | Action |
|---|---|
| Detector firing too often | Check `detector_telemetry` false-positive rate. If >5% over 7 days, gap auto-disables. Lower threshold via clinician portal first. |
| Codeword leaked by accident | Deactivate codeword via clinician portal (sets `active=FALSE`). Never reuse the leaked text. Audit log records deactivation. |
| safe_silence_mode stuck in pending_approval | Admin reviews via clinician portal. Reject sets state back to `inactive`. |
| safe_silence_mode expired and survivor returns | Welcome-back template fires. Survivor not asked about absence. |
| Validator blocks a draft response | Bridge does not override. Nate falls back to silence-with-presence. Audit logged. |
| Active-situation disclosure | `active_situation_grounding` register fires. Emergency resource block. Mandatory-reporting evaluation. Coach immediate alert. |
| Survivor-as-recruiter disclosure (adult target) | `recruiter_holding` register fires. Expungement-aware legal-aid pointer. Coordinated coach + legal alert. NO mandatory reporting (TVPA case law treats this as victim behavior). |
| Survivor-as-recruiter disclosure (minor target) | `recruiter_holding` register fires + mandatory-reporting auto-fires per child protection statutes. Coach immediate alert. |
| Minor survivor disclosure of any trafficking | Mandatory reporting auto-fires. Developmental_grounding register. Dual-guardian approval required for any profile mutation (Gap O). |
| Database migration fails partway | Roll back per `SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md`. Do not proceed to dependent migrations. |
| Auditor reports < expected check count | 5-location sync drift. Re-run baseline update per `trust-enforcer-architecture.mdc`. |
| Survivor requests data export | `client_data_export.py` generates redacted JSON of their `sensitive_bridge_log` entries within 30 days (Gap N). |

---

## 19. Compliance References

- **HIPAA 45 CFR 164.524** — Right of access (Gap N).
- **HIPAA 45 CFR 164.530(j)** — 6-year minimum retention (we extend to 7 to align with Illinois).
- **Illinois MHDDCA 740 ILCS 110** — Mental Health and Developmental Disabilities Confidentiality Act (7-year retention).
- **TVPA — Trafficking Victims Protection Act** — Federal framework. Case law treats coercion-driven recruitment by victims as victim behavior, not perpetrator behavior, when the recruiter is themselves under coercion.
- **42 USC § 5106a (CAPTA)** — Child Abuse Prevention and Treatment Act, mandatory reporting framework for minor trafficking.
- **State-specific child protection statutes** — vary by jurisdiction; resolved via `jurisdiction_compliance.py` (Gap L).

---

## 20. Versioning

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-05-08 | Initial foundation doc, paired with v1.3 plan. Migrations 202–208. |

Future updates require:
1. New migration if schema changes.
2. Plan-file amendment.
3. Two-clinician sign-off for clinical content changes.
4. PR description noting which sections changed.
5. Backup of prior version of this doc to `docs/foundation_backups/`.
