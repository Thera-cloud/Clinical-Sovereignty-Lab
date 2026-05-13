# Sensitive Bridge v1.4 — Addiction Architecture + Part-Aware Codeword Spec

**Status:** v0.2 — All open questions resolved, awaiting final owner sign-off
**Author:** Claude (Opus 4.7) drafting under direction of Dr. Nevedal
**Revision Date:** 2026-05-12 (v0.2)
**Prior Revision:** v0.1 (2026-05-12)
**Scope:** Foundational architecture spec for v1.4 work. Implementation prompts derived from this spec follow.
**Foundational Principle:** No piecemeal builds. All addiction tiers and their integration with part-aware codeword listening land together as one coherent system.

---

## Revision Notes — v0.2

Changes from v0.1:

1. Section 20 (Open Questions) removed; all 7 questions resolved by project owner, resolutions integrated below.
2. Section 12 (Coach Alert Routing) rewritten to integrate with existing `coach_notifications.notify_coach()` rather than describe new alert mechanism.
3. Section 11.4 (Crisis-Tier Warm Referral) rewritten to reference existing inactivity-follow-up patterns rather than auto-follow-up.
4. Section 11.5 added documenting PII redaction layer for addiction alert payloads (new clinical safety requirement).
5. Section 9.2 (Codeword Disclosure Types) extended with trafficking-specific types per Q7.
6. Section 14.2 (Schema Additions) updated CHECK constraint to include trafficking disclosure types.
7. Section 19.1 (Phase A) expanded scope to include EmailService bug fix.
8. Section 23 added documenting existing alert infrastructure inventory and integration discipline.

---

## 1. Purpose and Clinical Intent

Sovereign Sanctuary serves clients with complex trauma presentations: D.I.D., trafficking survivors, polyvictimization histories, and addiction patterns that frequently co-occur. The Sensitive Clinical Bridge v1.3 implemented the foundational orchestrator pipeline and identity canonicalization. v1.4 extends the bridge with two interlinked capabilities:

1. **Multi-tier addiction architecture** spanning substance use, behavioral addictions, process addictions, and cross-addiction patterns
2. **Part-aware codeword listening** that connects D.I.D. parts work to real-time chat monitoring, including addiction-coded parts

These two capabilities are linked because a client's addict-parts (Alcohol-Part, Sex-Part, Abused-Part-1, Abused-Part-2) are named entities that can be referenced in codewords, can be the speaker of a chat turn, and can trigger different routing than the same content from a more grounded part. Building them in sequence rather than together would replicate the identity-split mistake of Priority 1.

### 1.1 Non-goals

This spec does NOT cover:
- Generic AI therapy (Sovereign Sanctuary is sole-clinician + AI; the AI augments, never replaces)
- Self-diagnosis by clients (status fields are clinician-set or coach-set, not self-declared)
- Replacement of 12-step communities, sponsors, or clinical providers (we route to them, we do not replace them)
- Medication management or substance-use medical advice (out of scope; handled by client's medical providers)

---

## 2. Addiction Tier Taxonomy

Four tiers, each with explicit status field, clinical framework support, and resource routing.

### 2.1 Tier 1 — Substance Use Disorders

| Status field | Values | Clinical scaffold |
|---|---|---|
| `substance_status` | `none \| recovery \| active_use \| crisis` | AA Big Book, NA literature, AA 12 Steps |
| `substance_subtype` | `alcohol \| opioid \| stimulant \| cannabis \| nicotine \| sedative \| polysubstance \| other` | Substance-specific lexicons, withdrawal awareness |

### 2.2 Tier 2 — Behavioral Addictions (DSM-5 / clinically recognized)

| Status field | Values | Clinical scaffold |
|---|---|---|
| `sex_addiction_status` | `none \| recovery \| active \| crisis` | Carnes 30-task, Weiss inner child, SAA/SLAA/COSA, Minwalla DST |
| `gambling_status` | `none \| recovery \| active \| crisis` | GA Big Book, Gam-Anon family resources |
| `gaming_status` | `none \| recovery \| active \| crisis` | ITAA literature, Reset/Game Quitters frameworks |

### 2.3 Tier 3 — Process Addictions (mixed clinical recognition)

| Status field | Values | Clinical scaffold |
|---|---|---|
| `food_compulsion_status` | `none \| recovery \| active \| crisis` | OA, FA literature; routes to eating disorder care if BED/anorexia/bulimia indicated |
| `work_compulsion_status` | `none \| recovery \| active \| crisis` | Workaholics Anonymous, achievement-as-trauma-defense framing |
| `spending_compulsion_status` | `none \| recovery \| active \| crisis` | Debtors Anonymous, financial harm reduction |
| `codependency_status` | `none \| recovery \| active \| crisis` | CoDA, Mellody/Beattie frameworks, ACA when family-of-origin indicated |

### 2.4 Tier 4 — Cross-Addiction Profile

Cross-addiction is NOT a separate addiction; it is a pattern layer that tracks:

- Multiple simultaneous active addictions
- Transfer addiction (one in recovery, another emerged)
- Primary/secondary addiction designations
- Trauma-rooted addiction clustering
- Cycle phase coordination across addictions

Stored as `cross_addiction_profile` JSONB on `users.profile_data`. See section 14 for schema. Both stored layer (clinician narrative) and derived view (computed from per-type fields on each orchestrator pass).

---

## 3. Identity Canonicalization (Lesson From Priority 1)

**All addiction-related status fields and tables canonicalize on `users.username`.**

No field accepts hardware_id, device_id, or any other identifier as the user key. The Sensitive Bridge boundary translation via `_identity_resolver.resolve_username()` is applied before any addiction field is read or written.

Identity surface inventory amendment will be issued covering all new fields and tables added by v1.4.

---

## 4. Per-Addiction Status PUT Endpoints

Each addiction type gets a consistent REST endpoint shape mirroring the existing `substance-status` endpoint pattern.

```
PUT /sensitive-profile/{user_id}/substance-status
PUT /sensitive-profile/{user_id}/sex-addiction-status
PUT /sensitive-profile/{user_id}/gambling-status
PUT /sensitive-profile/{user_id}/gaming-status
PUT /sensitive-profile/{user_id}/food-compulsion-status
PUT /sensitive-profile/{user_id}/work-compulsion-status
PUT /sensitive-profile/{user_id}/spending-compulsion-status
PUT /sensitive-profile/{user_id}/codependency-status
PUT /sensitive-profile/{user_id}/cross-addiction-profile
```

Request body shape:

```json
{
  "status": "recovery",
  "subtype": "alcohol",
  "since_date": "2024-01-15",
  "active_frameworks": ["12_step_AA", "IFS", "EFT"],
  "primary_part_names": ["Alcohol-Part"],
  "clinical_notes_id": "optional-uuid",
  "set_by": "DrNevedal1"
}
```

Server validation: status enum, subtype enum, set_by is clinician or sole_lead_authorized coach, audit row to `sensitive_bridge_log` with `event_type='addiction_status_update'`, append-only retention 7 years.

---

## 5. TMC Wiring — Per-Addiction Branch Signals

In `backend/app/sse/ucd/tmc.py` `_gather_signals`, each addiction status field maps to its corresponding TMC signal:

```python
profile_data = await self._load_user_profile(user_id)

# Permissive activation: any non-"none" status activates the branch
tmc_signals['substance_branch_active'] = profile_data.get('substance_status') in (
    'recovery', 'active_use', 'crisis'
)
tmc_signals['sex_addiction_branch_active'] = profile_data.get('sex_addiction_status') in (
    'recovery', 'active', 'crisis'
)
# ... same pattern for gambling, gaming, food_compulsion, work_compulsion,
# spending_compulsion, codependency

# Cross-addiction signal: True if 2+ addiction branches are active
active_addictions_count = sum([
    tmc_signals.get(f'{t}_branch_active', False) for t in (
        'substance', 'sex_addiction', 'gambling', 'gaming',
        'food_compulsion', 'work_compulsion', 'spending_compulsion', 'codependency'
    )
])
tmc_signals['cross_addiction_active'] = active_addictions_count >= 2
tmc_signals['cross_addiction_count'] = active_addictions_count
```

**Permissive activation rationale (clinician direction):** Recovery status still activates the branch. "Substance abuse is always considered at least recovery due to relapse prevention monitoring." Same logic extends to all addiction types.

---

## 6. Orchestrator Branch Resolvers

Each branch signal maps to a resolver in `sensitive_clinical_bridge.py`:

```
_resolve_substance_branch
_resolve_sex_addiction_branch
_resolve_gambling_branch
_resolve_gaming_branch
_resolve_food_compulsion_branch
_resolve_work_compulsion_branch
_resolve_spending_compulsion_branch
_resolve_codependency_branch
_resolve_cross_addiction_branch  (composite)
```

Each resolver returns False if branch not active, loads addiction-specific lexicons, routes to addiction-specific response patterns, logs to `sensitive_bridge_log` when fired.

---

## 7. DST (Minwalla) Gating Logic

Minwalla's Dissociative Structural Trauma model. DST lens activates when:

- `sex_addiction_status` is non-`none`, OR
- Any addiction is active AND `polyvictimization_layers` contains entries indicating trauma roots

When DST lens applies, orchestrator enriches context with dissociation awareness flag, part-state inquiry preference (more likely to ask which part is speaking), trauma-informed pacing (slower escalation, more grounding offers).

---

## 8. Framework Composition Rules

### 8.1 Coach-Set Menu + AI-Selectable Per Turn

Per-client framework menu stored in `users.profile_data.sensitive_clinical.framework_menu`:

```json
{
  "framework_menu": {
    "default_set": ["IFS", "EFT", "Carnes_30_task", "ACT"],
    "ifs_enabled": true,
    "eft_enabled": true,
    "carnes_30_task_enabled": true,
    "weiss_inner_child_enabled": true,
    "minwalla_dst_enabled": "auto",
    "act_hexaflex_enabled": true,
    "crystal_knowledge_graph_enabled": false,
    "override_per_session": true
  },
  "framework_overrides": {
    "primary_lens_for_today": "DST",
    "override_set_by": "DrNevedal1",
    "override_expires": "2026-05-13T00:00:00Z"
  }
}
```

### 8.2 AI Per-Turn Selection

When multiple frameworks are enabled, orchestrator selects primary lens per turn based on:

| Client state signal | Preferred lens |
|---|---|
| Strong emotional surge with low coherence | EFT (Emotion Focused) |
| Part conflict expressed | IFS (parts work) |
| Values incongruence verbalized | ACT (defusion + values) |
| Sex addiction crisis indicators | Carnes 30-task + Minwalla DST |
| Inner child wound language | Weiss inner child |
| Dissociation indicators present | DST + IFS Self-energy |
| Trauma activation present | Stabilization (grounding) before any lens |

Multiple lenses can be simultaneously active; orchestrator labels response with informing lens(es). Labeling internal to audit log, not surfaced to client.

### 8.3 Little Nate Already Knows

The AI carries baseline knowledge of these frameworks from training data. v1.4 does NOT re-teach frameworks — it provides per-client framework menu, per-turn selection rules, lexicon scaffolding for detection, response shaping aligned with selected framework's structure.

---

## 9. Part-Aware Codeword Listening

### 9.1 Connection to Codeword Listener (Priority 5)

The existing `user_safety_codewords` table is extended to include part identification.

**Part numbering convention (resolved per Q1):** Per-client unique. Part-1 for Lisa is a different entity from Part-1 for William. No global semantic meaning to part numbers. `part_category` carries the clinical semantic.

```sql
ALTER TABLE user_safety_codewords ADD COLUMN part_name VARCHAR(64);
ALTER TABLE user_safety_codewords ADD COLUMN part_number INTEGER;
ALTER TABLE user_safety_codewords ADD COLUMN part_category VARCHAR(32);
-- part_category: 'addict_part' | 'abused_part' | 'protector_part' | 'manager_part'
--                | 'exile_part' | 'self_part' | 'caretaker_part' | 'unnamed'
ALTER TABLE user_safety_codewords ADD COLUMN addiction_link VARCHAR(32);
-- addiction_link: 'substance' | 'sex_addiction' | 'gambling' | 'gaming'
--                 | 'food_compulsion' | 'work_compulsion' | 'spending_compulsion'
--                 | 'codependency' | NULL
```

A codeword can be:
- Client-named: "I'm scared" → Abused-Part-2 speaking
- Part-numbered (D.I.D.): "I need help" → Part-7 (this client's Part-7)
- Addiction-coded: "I want a drink" → Alcohol-Part (addict_part, addiction_link=substance)
- Combination: "I need to disappear" → Abused-Part-1 AND addict_part, addiction_link=substance

### 9.2 Codeword Disclosure Types — Extension

Existing CHECK constraint allows `explicit_word | innocuous_phrase`. v1.4 extends to 14 total types:

```sql
ALTER TABLE user_safety_codewords DROP CONSTRAINT IF EXISTS codeword_disclosure_type_check;
ALTER TABLE user_safety_codewords ADD CONSTRAINT codeword_disclosure_type_check CHECK (
  disclosure_type IN (
    'explicit_word', 'innocuous_phrase',
    'soft_pause', 'grounding_request', 'covert_observation', 'reengagement_risk',
    'active_harm', 'imminent_danger',
    'addict_part_speaking', 'dissociation_indicator', 'part_conflict',
    'trafficking_history_disclosure', 'trafficking_active_risk', 'trafficking_imminent_danger'
  )
);
```

**Trafficking-specific types (per Q7):** Aligned with existing `user_polyvictimization_layers`:
- `trafficking_history_disclosure` → trauma-informed acknowledgment, polyvictim layer log entry, no immediate hotline push
- `trafficking_active_risk` → trauma-informed acknowledgment, hotline option offered, coach alert
- `trafficking_imminent_danger` → crisis-tier warm referral, hotline presented, coach alert dispatched, severity flag

### 9.3 Codeword Listener Wiring (Priority 5 Integration)

In `therapeutic_controller.prepare_therapeutic_context`, pass `nate_checkin_agent` to `evaluate_disclosure`:

```python
from app.services.nate_checkin_agent import nate_checkin_agent
context = await evaluate_disclosure(
    user_message=user_message,
    user_profile=user_profile,
    sensitive_signals=sensitive_signals,
    nate_checkin_agent=nate_checkin_agent,
)
```

`evaluate_disclosure` calls `nate_checkin_agent.detect_codeword_disclosure(user_message, user_profile.username)`:

1. Loads codewords for user from `user_safety_codewords` (canonical username)
2. Pattern-matches user_message against each codeword
3. Returns disclosure event with: matched codeword id, disclosure_type, part_name + part_number + part_category, addiction_link
4. Orchestrator routes response based on combined disclosure_type + part_category + addiction_link

### 9.4 Routing Examples

| Codeword fires | Routing |
|---|---|
| `explicit_word`, addict_part, substance | Substance branch + addict-part response + log event |
| `imminent_danger` | Crisis-tier: pause AI, SAMHSA + 988 numbers, `notify_coach(urgency='critical')` to DrNevedal1, log event |
| `dissociation_indicator`, Part-3 | DST lens + grounding + acknowledge this client's Part-3 + log event |
| `part_conflict`, exile_part | IFS Self-energy invitation + slowdown + log event |
| `addict_part_speaking`, sex_addiction | Sex addiction branch + Carnes phase check-in + Weiss invitation + log event |
| `trafficking_imminent_danger` | Crisis-tier warm referral: pause AI, 1-888-373-7888 / text 233733, `notify_coach(urgency='critical')`, log event |

---

## 10. Crystal Factory Augmentation

Per Q5 "all three: max depth" — three layers.

### 10.1 Layer 1 — Crystal-Augmented Lexicons

Crystals capture client's specific addiction language (personal metaphors), personal triggers (e.g., "Friday after work"), recovery resources client has named. Detector lexicons read these crystals at inference time.

### 10.2 Layer 2 — Crystal-Augmented Response Patterns

Crystals capture which response patterns work for this client (Carnes landed or felt mechanical, IFS landed or felt abstract, EFT landed or felt intrusive). Orchestrator uses these to weight framework selection in 8.2.

### 10.3 Layer 3 — Per-Client Clinical Knowledge Graph

Knowledge graph linking parts, addictions, trauma roots, recovery resources, trigger patterns, coping repertoire.

**Authorization (per Q2):** Opt-in per client via framework_menu (`crystal_knowledge_graph_enabled: false` default). Clinician must explicitly enable. Built incrementally over many sessions; never overwrites coach-set clinical truth.

### 10.4 Crystal Forge — Public Literature Seed (per Q3)

**"Lexicon scaffolds will contain short paraphrased detection patterns and can reflect verbatim text but if verbatim text used then it must follow with proper APA referencing including a linked website or similar."**

Implementation requirements:
- Each lexicon YAML file has `source` field with full APA citation
- Each pattern entry has optional `verbatim: true` flag; if true, requires `citation` field with linked URL
- Paraphrased patterns do not require per-pattern citation but file's `source` field must be populated
- Citations linked at runtime when AI presents framework concepts to client
- All citations periodically reviewed by project owner for currency

Seed list:
- **Substance:** AA Big Book, NA Basic Text
- **Sex addiction:** Carnes 30-task, Carnes three-circle, Weiss inner child framework, Minwalla DST principles, SAA Green Book
- **Gambling:** GA Combo Book, "20 Questions" patterns
- **Gaming:** ITAA QA literature, Cam Adair / Game Quitters
- **Food:** OA 12&12, FA "I Put My Hand In Yours"
- **Work:** Workaholics Anonymous Book of Recovery
- **Spending:** Debtors Anonymous PRG, J. Mundis
- **Codependency:** CoDA literature, Beattie Codependent No More, Mellody Facing Codependence

Each seed scaffolded as `status: scaffolded_unreviewed` until project owner marks `status: clinically_active`. Orchestrator does NOT load `scaffolded_unreviewed` lexicons in production.

---

## 11. Resource Library and Crisis-Tier Warm Referral

### 11.1 Static Resource Library

`backend/data/addiction_resources/`:
- `hotlines.yaml` — phone numbers, text codes, hours
- `meeting_locators.yaml` — fellowship meeting URLs
- `online_meetings.yaml` — Zoom/video meeting schedules
- `clinical_referrals.yaml` — provider type definitions
- `books_and_workbooks.yaml` — Carnes, Weiss, Beattie, Mellody, AA Big Book, NA Basic Text
- `self_assessment_tools.yaml` — Carnes SAST, Whitfield-Reddick, AUDIT, CAGE, GA 20 Questions

### 11.2 Hotlines (per Q6)

```yaml
hotlines:
  general_addiction_substance_and_behavioral:
    name: SAMHSA National Helpline
    phone: 1-800-662-4357
    hours: 24/7
    languages: [english, spanish]
    addiction_scope: [substance, behavioral_general]
  suicide_crisis_universal:
    name: National Suicide and Crisis Lifeline
    phone: '988'
    text: '988'
    hours: 24/7
    addiction_scope: [any_acute_crisis]
  sex_addiction_specific:
    name: SAA International Office
    phone: 1-800-477-8191
    hours: 24/7
    addiction_scope: [sex_addiction]
  gambling_specific:
    name: GA National Hotline
    phone: 1-855-222-5542
    hours: 24/7
    addiction_scope: [gambling]
  text_crisis:
    name: Crisis Text Line
    text: HOME to 741741
    hours: 24/7
    addiction_scope: [any_crisis_text_preferred]
  human_trafficking:
    name: National Human Trafficking Hotline
    phone: 1-888-373-7888
    text: '233733'
    hours: 24/7
    addiction_scope: [trafficking_victim_survivor]
```

### 11.3 Active Referral

When AI detects pattern matching a fellowship's primary scope, AI may suggest referral with clinical framing. Gated by: client framework menu, stage of recovery, recent suggestion history (don't repeat within X turns).

### 11.4 Crisis-Tier Warm Referral (per Q5)

When `disclosure_type` is `imminent_danger`, `active_harm`, `trafficking_imminent_danger`, or `crisis` addiction status fires:

1. Pause AI's normal conversational flow. Bridge enters crisis mode.
2. Acknowledge what was said. Brief, present, non-clinical.
3. Offer specific number from hotlines list matched to disclosure type.
4. Confirm coach alert sent: "I'm letting Dr. Nevedal know what you just shared."
5. Stay with client until they confirm next step.
6. Log event with severity flag and full disclosure context.

**Acknowledgment tracking (per Q5):** Do NOT auto-follow-up on crisis acknowledgment. Coach asks in their own time during human session. If client goes inactive after crisis, the existing NateCheckInAgent 62h/72h inactivity-follow-up path reaches them — that is the reengagement channel, NOT a new auto-follow-up.

Coach alert mechanism (section 12) fires in parallel.

### 11.5 PII Redaction Layer (NEW in v0.2)

For clinical safety with D.I.D. and trafficking survivors, addiction crisis alert payloads MUST redact identifying information about third parties before coach transmission.

Redaction rules applied to alert payload's conversation context:

- Proper names other than client and coach → `[name]`
- Phone numbers other than hotlines → `[phone]`
- Email addresses other than client/coach → `[email]`
- Physical addresses → `[address]`
- Specific dates of past events: generalized to `[approximate date]` if recent (last 30 days), preserved if historical
- URLs preserved (typically resource links, not PII)
- Hotline numbers in conversation NOT redacted

Implementation: `backend/app/services/pii_redaction.py`. Applied to addiction alert payloads BEFORE passing to `coach_notifications.notify_coach()`. Unredacted version remains in `sensitive_bridge_log` (accessible to authorized clinicians via View Brief).

Coach receives sanitized alert + link to View Brief where full context is available with their access classification.

---

## 12. Coach Alert Routing (per Q4 — piggy-back on existing)

### 12.1 Canonical Path

Addiction-tier coach alerts use existing `coach_notifications.notify_coach()` in `backend/app/services/coach_notifications.py`. v1.4 does NOT create new alert path; extends usage of existing function.

```python
from app.services.coach_notifications import notify_coach
from app.services.pii_redaction import redact_pii

sanitized_context = redact_pii(recent_conversation_turns[-2:])

await notify_coach(
    coach_username=assigned_coach,  # DrNevedal1 for sole-clinician deployment
    urgency=_map_disclosure_to_urgency(disclosure_event),
    subject=f"Addiction crisis — {client_username} — {disclosure_type}",
    message=sanitized_context,
    channels=['in_app', 'sms', 'email'],
    payload={
        'client_username': client_username,
        'disclosure_type': disclosure_type,
        'addiction_link': addiction_link,
        'part_identification': part_id_dict,
        'view_brief_link': f"https://command.sovereignsanctuary.net/client/{client_username}/brief",
        'sensitive_bridge_log_event_id': event_id,
    },
)
```

### 12.2 Urgency Mapping

```python
def _map_disclosure_to_urgency(disclosure_event):
    critical_types = {'imminent_danger', 'active_harm', 'trafficking_imminent_danger'}
    high_types = {'trafficking_active_risk', 'reengagement_risk',
                  'addict_part_speaking', 'part_conflict'}
    if disclosure_event['disclosure_type'] in critical_types:
        return 'critical'
    if disclosure_event['disclosure_type'] in high_types:
        return 'high'
    if disclosure_event.get('addiction_status_tier') == 'crisis':
        return 'critical'
    if disclosure_event.get('addiction_status_tier') == 'active':
        return 'high'
    return 'normal'
```

### 12.3 Channels by Urgency

Per existing `notify_coach()` logic (preserved):

| Urgency | Channels |
|---|---|
| `critical` | in_app + SMS + email |
| `high` | in_app + SMS |
| `normal` | in_app only |

### 12.4 Storage

Alerts persist in `coach_escalation_notifications` table (existing). v1.4 adds no new alert tables. `sensitive_bridge_log` audit row separately records alert dispatch with cross-reference to `coach_escalation_notifications.id`.

### 12.5 Sole-Clinician Routing

For current sole-clinician deployment, all addiction-tier crisis alerts route to coach_username=`DrNevedal1`. When coach assignment system is later operational, resolution comes from `users.coach_id` or `assigned_coach_id` (same as existing `NateCheckInAgent._send_coach_alert`).

---

## 13. Intimacy_Clinical Parallel Lane

Existing `intimacy_clinical` with `unfaithful_shame` register remains active in parallel with `sex_addiction_status`.

| Lane | Concern |
|---|---|
| `intimacy_clinical.unfaithful_shame` | Relational/marital impact; partner-betrayal trauma; couples' work |
| `sex_addiction_status` | Addiction structure; recovery framework; addict-part work; cycle phase |

Both can be active for the same client. Orchestrator routes to both lanes when both active.

---

## 14. Data Schema — Complete v1.4 Migrations

One migration file: `backend/migrations/215_v1_4_addiction_architecture.sql`

### 14.1 New JSONB sub-keys on `users.profile_data`

Documented in app code:
- `substance_status`, `substance_subtype`
- `sex_addiction_status`
- `gambling_status`
- `gaming_status`
- `food_compulsion_status`
- `work_compulsion_status`
- `spending_compulsion_status`
- `codependency_status`
- `cross_addiction_profile` (JSONB sub-object)
- `sensitive_clinical.framework_menu` (JSONB sub-object including `crystal_knowledge_graph_enabled` default false)
- `sensitive_clinical.framework_overrides` (JSONB sub-object)

### 14.2 Schema additions

```sql
-- Extend user_safety_codewords
ALTER TABLE user_safety_codewords
  ADD COLUMN part_name VARCHAR(64),
  ADD COLUMN part_number INTEGER,
  ADD COLUMN part_category VARCHAR(32),
  ADD COLUMN addiction_link VARCHAR(32);

CREATE INDEX idx_codewords_part_name ON user_safety_codewords (user_id, part_name)
  WHERE part_name IS NOT NULL;
CREATE INDEX idx_codewords_addiction_link ON user_safety_codewords (user_id, addiction_link)
  WHERE addiction_link IS NOT NULL;

-- Disclosure type CHECK constraint expansion (includes trafficking per Q7)
ALTER TABLE user_safety_codewords DROP CONSTRAINT IF EXISTS codeword_disclosure_type_check;
ALTER TABLE user_safety_codewords ADD CONSTRAINT codeword_disclosure_type_check CHECK (
  disclosure_type IN (
    'explicit_word', 'innocuous_phrase',
    'soft_pause', 'grounding_request', 'covert_observation', 'reengagement_risk',
    'active_harm', 'imminent_danger',
    'addict_part_speaking', 'dissociation_indicator', 'part_conflict',
    'trafficking_history_disclosure', 'trafficking_active_risk', 'trafficking_imminent_danger'
  )
);

-- Per-client parts registry
CREATE TABLE IF NOT EXISTS user_parts_registry (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  part_name VARCHAR(64) NOT NULL,
  part_number INTEGER,
  part_category VARCHAR(32) NOT NULL,
  addiction_link VARCHAR(32),
  description TEXT,
  protected_exile_part_id INTEGER REFERENCES user_parts_registry(id),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  created_by VARCHAR(64) NOT NULL,
  retired_at TIMESTAMPTZ,
  UNIQUE (user_id, part_name)
);
CREATE INDEX idx_parts_registry_user ON user_parts_registry (user_id) WHERE is_active = TRUE;
CREATE INDEX idx_parts_registry_addiction ON user_parts_registry (user_id, addiction_link)
  WHERE addiction_link IS NOT NULL;

-- Addiction status history (append-only)
CREATE TABLE IF NOT EXISTS addiction_status_history (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  addiction_type VARCHAR(32) NOT NULL,
  previous_status VARCHAR(32),
  new_status VARCHAR(32) NOT NULL,
  subtype VARCHAR(32),
  set_by VARCHAR(64) NOT NULL,
  notes TEXT,
  set_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_addiction_history_user ON addiction_status_history (user_id, addiction_type);

-- Cross-addiction transfer events (append-only)
CREATE TABLE IF NOT EXISTS cross_addiction_transfer_events (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  from_addiction VARCHAR(32) NOT NULL,
  to_addiction VARCHAR(32) NOT NULL,
  noted_at TIMESTAMPTZ DEFAULT NOW(),
  noted_by VARCHAR(64) NOT NULL,
  clinical_notes TEXT
);
CREATE INDEX idx_transfer_user ON cross_addiction_transfer_events (user_id);

-- Note: crisis_events table writer added in app code (section 17),
-- no DDL change required for crisis_events.
```

### 14.3 Lexicon directory structure

```
backend/data/lexicons/addiction/
  substance/{alcohol,opioid,stimulant,cannabis,nicotine,sedative,polysubstance,crystal_seed}.yaml
  sex_addiction/{carnes_30_task,weiss_inner_child,minwalla_dst,saa_phrases,sex_addiction_general,crystal_seed}.yaml
  gambling/{ga_phrases,gambling_general,crystal_seed}.yaml
  gaming/{itaa_phrases,gaming_general,crystal_seed}.yaml
  food_compulsion/{oa_phrases,fa_phrases,food_compulsion_general,crystal_seed}.yaml
  work_compulsion/{wa_phrases,work_compulsion_general,crystal_seed}.yaml
  spending_compulsion/{da_phrases,spending_compulsion_general,crystal_seed}.yaml
  codependency/{coda_phrases,mellody_facing_codep,beattie_codep_no_more,aca_phrases,codependency_general,crystal_seed}.yaml
  cross_addiction/{transfer_patterns,multi_addiction_general,crystal_seed}.yaml
  frameworks/{ifs_parts_work,eft_emotion_focused,act_hexaflex,dst_minwalla}.yaml
  trafficking/{trafficking_general,trafficking_active_risk,crystal_seed}.yaml
```

YAML file shape (per Q3 citation requirement):

```yaml
status: scaffolded_unreviewed
source:
  citation: "Carnes, P. (2001). Out of the shadows: Understanding sexual addiction (3rd ed.). Hazelden."
  link: "https://www.hazelden.org/store/item/47502"
last_review: null
reviewed_by: null
detector_patterns:
  - pattern: "I can't stop"
    weight: 0.7
    notes: "Generic powerlessness; Step 1 alignment"
    verbatim: false
  - pattern: "powerless over"
    weight: 0.9
    notes: "Direct AA Step 1 language"
    verbatim: true
    citation: "Alcoholics Anonymous (2001). The Big Book (4th ed.), p. 59. https://www.aa.org/the-big-book"
response_seeds:
  - context: "Step 1 powerlessness expression"
    framing: "Honoring that powerlessness landed for you. That's exactly where Step 1 lives."
    source: "AA framework synthesis; not direct quotation"
crystal_seeds: []
```

---

## 15. Flutter UI Surfaces

### 15.1 Sensitive Clinical Profile — Addiction Section (extended)

Collapsible subsections per addiction type. Each subsection: status dropdown, subtype dropdown (substance only), active frameworks multi-select, primary part name(s) with autocomplete from `user_parts_registry`, Set status button calling type-specific PUT.

### 15.2 Parts Registry Screen — New

`ClientPartsRegistryScreen`: list of named parts with category, addiction_link, description; Add part form (name, optional number for D.I.D., category dropdown, addiction_link dropdown, description); edit/retire actions; IFS-aware educational notes.

### 15.3 Framework Menu Screen — New

`ClientFrameworkMenuScreen`: toggle per framework, Crystal Knowledge Graph opt-in (default off per Q2), "Default lens for today" override with expiration picker, coach notes field.

### 15.4 Cross-Addiction Profile Screen — New

`ClientCrossAddictionProfileScreen`: derived view (auto-computed active/recovery), primary/secondary designations, transfer history with Add event form, trauma roots flag, polyvictim link.

---

## 16. Sensitive Bridge Visibility Pill Extension

View Brief pill (commit 2a6a8be) extends with addiction overlay: addiction icon overlay if any status active/crisis; cross-addiction badge if cross-addiction active; tap opens Sensitive Profile with addiction section auto-expanded.

---

## 17. Telemetry and Audit

Events flowing through `sensitive_bridge_log`:

- `addiction_status_update`
- `addiction_branch_activated`
- `addiction_lexicon_match`
- `addiction_response_generated`
- `coach_alert_dispatched` (with cross-reference to `coach_escalation_notifications.id`)
- `coach_alert_acknowledged`
- `referral_suggested`
- `referral_acknowledged`
- `crisis_warm_handoff`
- `cross_addiction_transfer_logged`
- `part_codeword_match`
- `framework_lens_selected`
- `trafficking_disclosure_detected`
- `pii_redaction_applied`

7-year retention, RBAC, ON DELETE RESTRICT.

**Crisis_events PG writer (new in v1.4):** When addiction-tier crisis fires, write row to existing `crisis_events` table in addition to `sensitive_bridge_log`. Fills the gap Cursor identified: table schema exists, no writer currently. Admin dashboards reading `crisis_events` will now reflect addiction-tier crisis events.

---

## 18. Testing Plan

### 18.1 Schema migration test

- Migration 215 against staging PG; verify all tables created with constraints
- Verify CHECK constraint accepts all 14 disclosure types
- Run migration twice; second run no-op (idempotency)

### 18.2 PUT endpoint smoke tests

Per addiction type: 200 with valid body, 422 invalid value, 403 non-admin, 404 unknown user.

### 18.3 TMC signal propagation

- substance_status=recovery → substance_branch_active=True
- sex_addiction_status=crisis → sex_addiction_branch_active=True AND cross_addiction signal updated
- 2 addictions active → cross_addiction_active=True, count=2

### 18.4 Codeword listener

Test codeword "I need to disappear" with part_category=addict_part, addiction_link=substance. Submit chat. Assert correct disclosure event, correct routing to substance branch + addict-part response.

### 18.5 Crisis-tier warm handoff

Trigger imminent_danger. Assert AI pauses, presents hotline, `notify_coach(urgency='critical')` dispatched, `coach_escalation_notifications` row written, `crisis_events` PG row written (new writer), `sensitive_bridge_log` row with `coach_alert_dispatched`, PII redaction applied.

### 18.6 PII redaction

Submit conversation with third-party name, phone, address. Trigger alert. Assert coach payload sanitized. Assert full unredacted version in `sensitive_bridge_log`. Assert hotline numbers NOT redacted.

### 18.7 Framework selection

Framework_menu=[IFS,EFT,Carnes]. Emotional surge → EFT lens. Parts conflict → IFS lens. Step 1 language → Carnes lens.

### 18.8 Trafficking disclosure

Codeword "I had to go back" with trafficking_active_risk. Submit chat. Assert 1-888-373-7888 presented, coach alert, polyvictim layer log entry.

### 18.9 EmailService fix

Confirm `send_crisis_alert` method exists and is callable. Trigger sanctuary_request_coach. Assert email sent (no silent failure). Assert log entry.

### 18.10 End-to-end synthetic test client

Create `audit_addiction_test_01`. Walk through enrollment → status setting → codeword creation → chat turn → response verification → coach alert simulation → PII verification. Verify all 14 telemetry types fire.

---

## 19. Rollout Sequence

### 19.1 Phase A — Schema, infrastructure, EmailService bug fix (one deploy)

1. Migration 215 lands on GREEN
2. PUT endpoints deployed
3. TMC wiring deployed (signal-only; resolvers not yet wired to action)
4. Lexicon scaffolding in place (all `scaffolded_unreviewed`)
5. `.cursor/rules/v1_4_*.mdc` rules added
6. PII redaction service deployed (`pii_redaction.py`)
7. crisis_events PG writer added
8. **EmailService bug fix:** implement `send_crisis_alert` method on `EmailService` so existing `sanctuary_request_coach` path no longer silently fails
9. NO USER-FACING CHANGES; master switch FALSE

### 19.2 Phase B — Branch resolvers (one deploy)

1. Each `_resolve_*_branch` resolver implemented
2. Crystal Factory Layer 1 (lexicon augmentation) wired
3. Coach alert dispatch wired via `notify_coach()` integration
4. Still no user-facing changes (master switch FALSE)

### 19.3 Phase C — Codeword listener wiring (Priority 5)

1. `prepare_therapeutic_context` passes `nate_checkin_agent`
2. `evaluate_disclosure` accepts and uses it
3. Part-aware codeword storage live
4. UI extension for parts registry + framework menu live
5. No user-facing detector firing until master switch flips

### 19.4 Phase D — Lexicon clinical review and activation

1. Project owner reviews each `scaffolded_unreviewed` lexicon
2. Edits clinically as needed; confirms APA citations and verbatim flags per Q3
3. Marks `status: clinically_active`
4. Per-lexicon activation; orchestrator loads activated lexicons
5. Crystal Factory seeds with activated content

### 19.5 Phase E — Pilot cohort enablement

1. William Henderson + 4 other pilot_5 cohort users get master switch enabled
2. Their `gap_features_enabled` JSONB sets addiction-aware gaps per clinical fit
3. Crystal Knowledge Graph (Layer 3) opt-in; default off
4. Monitor `sensitive_bridge_log` for false positives, missed detections, response quality

### 19.6 Phase F — Cohort_25 and general availability

Standard rollout: pilot_5 → cohort_25 → cohort_100 → general_availability.

---

## 20. Estimated Effort

| Phase | Effort | Blocking |
|---|---|---|
| Phase A | 3-4 days Cursor execution | None |
| Phase B | 3-5 days Cursor execution | Phase A complete |
| Phase C | 1-2 days Cursor execution | Phase B complete |
| Phase D | 5-15 days project owner time | Phase A complete |
| Phase E | 1 day | Phase D complete for enabled lexicons |
| Phase F | 2-4 weeks observation | Phase E successful |

Total elapsed: 4-8 weeks from spec approval to v1.4 general availability.

---

## 21. Approval Block

| Approver | Role | Signature | Date |
|---|---|---|---|
| Dr. Nate Nevedal | Project Owner / Sole Lead Therapist | ___________ | _________ |

---

## 22. Cross-Reference to Earlier Architecture

- v1.3 orchestrator pipeline: `backend/app/services/sensitive_clinical_bridge.py` 17-step pipeline (extended in section 6)
- v1.3 identity canonicalization: Priority 1 commit a7c03b7 (extended in section 3)
- v1.3 enrollment cohort labels: `inspection_test, pilot_5, cohort_25, cohort_100, general_availability` (section 19.6)
- v1.3 sensitive_bridge_log retention: 7 years, RBAC, ON DELETE RESTRICT (section 17)
- v1.3 master switch: `app_settings.sensitive_bridge_master_enabled` (gates all v1.4 features)

---

## 23. Existing Alert Infrastructure Inventory (NEW in v0.2)

Per Cursor inventory (2026-05-12). v1.4 integration discipline below.

### 23.1 Existing paths

| Path | Function | Use case | v1.4 integration |
|---|---|---|---|
| Inactivity coach alert | `NateCheckInAgent._send_coach_alert` (62h threshold) | Time-based inactivity | Pattern reused for reengagement reference; NOT canonical addiction path |
| Live WebSocket ping | `send_coach_notification` (bridge_server) | Real-time, coach connected | Optional augmentation; not relied upon |
| Multi-channel escalation | `coach_notifications.notify_coach()` + `coach_escalation_notifications` | Tiered urgency, multi-channel | **CANONICAL** for v1.4 |
| Broadcast notification | `notification_system.create_notification(ALL_COACHES)` | In-memory broadcast | Not used by v1.4 |

### 23.2 Existing crisis flow

| Component | Current state | v1.4 action |
|---|---|---|
| `NevedalHandler._log_crisis` | Writes JSON to `data/Vaults/.../crisis_log.json` | Preserved; extended with addiction-specific keywords |
| `crisis_events` PG table | Schema exists; no writer in code | v1.4 ADDS WRITER for addiction-tier crises |
| `NotificationSystem.send_crisis_alert` | Implemented but unused; no PII redaction | Not called by v1.4; superseded by `notify_coach()` |
| `EmailService.send_crisis_alert` | METHOD MISSING; calls fail silently | v1.4 Phase A FIXES this method |
| `sanctuary_request_coach` | Calls broken EmailService method | After Phase A, works correctly |

### 23.3 Inactivity follow-up (per Q5)

- Existing `NateCheckInAgent` 62h/72h pattern handles inactivity outreach
- v1.4 does NOT add separate addiction-acknowledgment follow-up
- If client goes inactive after crisis, existing path reaches them
- Coach asks about acknowledgment in their own time during human session

### 23.4 Integration discipline

- v1.4 functions needing coach alerts call `notify_coach()`, never duplicate
- v1.4 functions needing crisis logging write to BOTH `sensitive_bridge_log` (canonical) AND `crisis_events` (admin parity)
- v1.4 functions needing inactivity-aware behavior consult `NateCheckInAgent` patterns; do not duplicate scheduling

---

## Appendix A — Lessons Incorporated From May 12 2026 Incident

1. All new fields canonical on `users.username` from start (section 3)
2. Migration in one file, not piecemeal (section 14)
3. Phase A schema-only, master switch FALSE (section 19.1)
4. Identity surface inventory amendment issued for all v1.4 fields
5. All new tables ON DELETE RESTRICT on user_id FK (section 14.2)
6. All addiction status changes append-only with 7-year retention (sections 14.2, 17)
7. Integration over duplication — v1.4 reuses existing alert infrastructure (section 23) rather than forking new paths

End of spec.
