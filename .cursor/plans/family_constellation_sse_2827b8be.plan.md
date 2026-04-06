---
name: Family Constellation SSE
overview: Add family-linked SSE story journeys with age-gated content, heritage landmarks (crystals + quest stones), couples narrative threading with coherence trajectory and crystal co-occurrence, family cycle detection, dependent biome inheritance, family-aware widget content, privacy audit logging, multi-level coaching crystal pathways, minor lifecycle management (consent, restrictions, parent visibility, age-up transition at 18, emancipation override). Reuses existing `families` + `family_members` tables with added columns.
todos:
  - id: migration-177
    content: "Create migration 177_family_constellation.sql: ALTER family_members + CREATE family_shared_events"
    status: completed
  - id: family-engine
    content: Create backend/app/sse/family_engine.py with 15 functions (max 430 lines)
    status: completed
  - id: api-endpoints
    content: Add 8 family endpoints to admin.py (6 client + 2 admin, max 70 lines)
    status: completed
  - id: age-gate-forge
    content: Add age-gated intake prompts to layer1_identity_forge.py (max 20 lines)
    status: completed
  - id: age-gate-panels
    content: Add age-gated panel generation + heritage landmarks in thera_world_engine.py (max 15 lines)
    status: completed
  - id: couples-threading
    content: Add couples narrative threading + coherence trajectory in thera_world_engine.py (max 15 lines)
    status: completed
  - id: widget-family
    content: Add family-aware widget content in widget_engine.py (max 10 lines)
    status: completed
  - id: flutter-family
    content: Create family_constellation_screen.dart or integrate into settings (max 50 lines)
    status: completed
  - id: monitor-families
    content: Add Families section to sse_monitoring.html (max 30 lines)
    status: completed
  - id: crystal-pathways
    content: Add tag_session_crystal + get_family_session_crystals + post_crystallize_family_tag to family_engine.py (max 70 lines)
    status: completed
  - id: crystal-story-integration
    content: Add family crystal context injection in thera_world_engine.py (max 10 lines) + POST tag-session endpoint in admin.py (max 15 lines)
    status: completed
  - id: minor-lifecycle
    content: Add minor constraints, parent view, consent wiring to family_engine.py + member summary endpoint in admin.py (max 30 lines)
    status: completed
  - id: age-transition
    content: Add age-up detection in layer0_orchestrator.py (max 15 lines) + transition panel in thera_world_engine.py (max 15 lines) + emancipation endpoint (max 10 lines)
    status: completed
  - id: deploy
    content: "Deploy: migration first, then backend files, then Flutter + dashboard"
    status: completed
isProject: false
---

# Phase 6: Family Sanctuary Story Constellation

## Existing Infrastructure (reuse, don't rebuild)

- **`families` table** (migration 001): `id UUID`, `family_code`, `name`, `head_of_household_id`
- **`family_members` table** (migration 029): `id SERIAL`, `family_id TEXT`, `user_id TEXT`, `role`, `joined_at`
- **`age_appropriate_calibration.py`**: Already has `CHILD_CONFIG` (under 13), `ADOLESCENT_CONFIG` (13-17), `ADULT_CONFIG` with system prompt overlays and technique lists
- **`consent_privacy.py`**: Has `minor_enrollment` consent type with parental consent flow
- **`layer1_identity_forge.py`**: 10-turn `INTAKE_PROMPTS` with `get_intake_prompt(turn, user_name)` and `extract_intake_data(conversation, db_pool, user_id)`
- **Crystal recall**: LOCKED crystals = confidence >= 0.85 (`CONFIDENCE_LOCKED` in `crystal_constants.py`); bridge recall queries by confidence threshold, not a "LOCKED" status field

## Step 1: Migration 177 — Extend Existing Tables + New Event Table

**File**: `backend/migrations/177_family_constellation.sql`

Add missing columns to `family_members`:

```sql
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS date_of_birth DATE;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS age_gated BOOLEAN DEFAULT false;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS member_uuid UUID DEFAULT gen_random_uuid();
-- Minor lifecycle columns (addition 14):
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS consent_recorded_at TIMESTAMPTZ;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS consent_parent_id TEXT;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS age_transitioned_at TIMESTAMPTZ;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS emancipated BOOLEAN DEFAULT false;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS emancipated_reason TEXT;
```

Create the shared events table (new):

```sql
CREATE TABLE IF NOT EXISTS family_shared_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_family_shared_events_family ON family_shared_events(family_id);
```

Note: `family_members.family_id` is TEXT (matching `families.family_code`), not UUID. The new event table follows the same convention.

## Step 2: Family Engine — NEW file

**File**: `backend/app/sse/family_engine.py` (max 430 lines)

Fifteen core functions:

**Original 7:**

- `create_family_unit(head_user_id, family_name, db_pool)` — INSERT into `families` with generated `family_code`, then INSERT into `family_members` with role=`head`
- `add_family_member(family_id, user_id, role, display_name, date_of_birth, db_pool, consenting_parent_id=None)` — INSERT into `family_members`, auto-compute `age_gated` from DOB vs today. If minor (under 18): requires `consenting_parent_id`, stores `consent_recorded_at=now()` and `consent_parent_id`. No SSE journey starts until consent is recorded. Wire `consent_privacy.py` `minor_enrollment` consent type
- `get_family_constellation(family_id, db_pool)` — JOIN `family_members` with `sse_user_journeys` and `sse_identity_forge` to return member journey status, biome, archetype, latest panel
- `get_family_for_user(user_id, db_pool)` — SELECT from `family_members` WHERE user_id matches (check both hardware_id and username via the standard `ANY($1)` pattern)
- `generate_shared_event(family_id, event_type, db_pool)` — INSERT into `family_shared_events`
- `check_age_gate(user_id, db_pool)` — Query `family_members.date_of_birth`, compute age, return `{age_gated, age_tier, allowed_themes}`. Reuse `age_appropriate_calibration.py` tier logic
- `get_heritage_landmarks(user_id, db_pool)` — Find parent(s) via `family_members` (role in head/spouse), query their LOCKED crystals (`confidence >= 0.85`) AND completed quests, transform into landmark descriptions. Max 5 crystal landmarks + 3 quest stones per parent. **Never expose raw crystal_text** — only domain-based descriptions

**New 3 (additions 1-7):**

- `get_couples_crystal_overlap(spouse1_id, spouse2_id, db_pool)` — (max 15 lines) Query crystals for both spouses, find overlapping domains. Returns `{shared_domains: [...], shared_npc_seeds: [{domain, crystal_count_combined}]}`. Shared domains produce shared NPCs that appear as the same character in both partners' story panels — a bridge figure, a shared landmark, a meeting place
- `detect_family_cycles(family_id, db_pool)` — (max 20 lines) Cross-reference PMB/cycle data across family members. Find temporal correlations (e.g., dad's anger cycle Wednesdays, daughter's anxiety Thursdays). Returns list of correlated cycle pairs. These inform: shared storm events in panels, admin alerts, widget content
- `get_dependent_start_biome(parent_user_id, db_pool)` — (max 5 lines) Query parent's current biome from `sse_user_journeys`, return a bright variant for child's starting biome. Maps: `dark_forest` -> `enchanted_forest`, `river_valley` -> `enchanted_river`, etc. If no parent journey, falls back to `enchanted_forest`

**New 3 (additions 8-10 — Coaching Crystal Pathways):**

- `tag_session_crystal(crystal_id, session_type, family_id, participant_ids, db_pool)` — (max 30 lines) Tag a crystal with family session context after crystallization. Updates crystal metadata with source type (`individual`/`couples`/`parent_child`/`family_group`) and `family_id`. For couples/parent-child/group: duplicates crystal for other participants with adjusted confidence (original speaker = full, listeners = 0.7x). For parent-child: runs age-appropriate filter on crystal text before storing child's version
- `get_family_session_crystals(user_id, family_id, db_pool)` — (max 15 lines) Returns crystals organized by session type: `{individual: [...], couples: [...], parent_child: [...], family_group: [...]}`. The story engine uses each category differently: individual → personal NPCs; couples → shared NPCs and convergence; parent_child → heritage/guardian imagery; family_group → shared environmental events
- `post_crystallize_family_tag(user_id, session_metadata, db_pool)` — (max 25 lines) Post-crystallization hook called AFTER `crystallize_from_conversation()` finishes. Does NOT modify `bridge_server.py` (PROTECTED). Queries most recent crystals for user (created in last 5 min), tags them with family session context from `session_metadata`. If couples session: duplicates to spouse. If parent-child: creates age-filtered version for child. If family_group: duplicates to all members. Wired via a `POST /api/sse-client/family/tag-session` endpoint the Flutter app calls after a family session ends

**New 2 (additions 11-13 — Minor Lifecycle):**

- `get_minor_parent_view(parent_id, child_id, db_pool)` — (max 20 lines) Returns age-appropriate view of child's journey for the parent. Includes: biome, archetype, panel thumbnails (not narratives for teens 13-17), check-in emotions, quest names. Excludes: conversation transcripts, crystal text, session details, intake responses (except archetype). Verifies parent has `head`/`spouse` role in the child's family. Logs access to `family_shared_events` (privacy audit)
- `emancipate_minor(user_id, reason, admin_id, db_pool)` — (max 10 lines) Sets `age_gated=false`, `emancipated=true`, `emancipated_reason=reason` on the family member. Blocks parent visibility. Keeps `family_id` for heritage landmarks. Logs action to `family_shared_events` with admin_id and reason

Heritage landmark transformation pattern:

```python
LANDMARK_TEMPLATES = {
    "clinical": "A standing stone inscribed with ancient wisdom about healing",
    "coaching": "A great tree whose roots hold memories of growth",
    "research": "An observatory tower with starlit knowledge",
    "general": "A cairn of stacked stones marking a lesson learned",
}

QUEST_STONE_TEMPLATE = "A weathered shield mounted on a tree, marking where a guardian completed their quest for {goal}"
```

Heritage now includes both crystal landmarks and quest stones from completed parent quests (`sse_quests WHERE user_id IN (parent_ids) AND status='completed'`).

## Step 3: API Endpoints in admin.py

**File**: `backend/app/routers/admin.py` (max 40 new lines on `sse_client_router`)

Client-facing (authenticated user):
- `POST /api/sse-client/family/create` — body: `{family_name}`, creates family with caller as head (minors blocked)
- `POST /api/sse-client/family/add-member` — body: `{user_id, role, display_name, date_of_birth}`, only head can add (minors blocked)
- `GET /api/sse-client/family` — returns constellation for caller's family
- `GET /api/sse-client/family/heritage` — returns heritage landmarks (dependents only), logs access to `family_shared_events`
- `POST /api/sse-client/family/tag-session` — body: `{session_type, family_id, participant_ids}`, tags recent crystals with family context (called by Flutter after family session ends)
- `GET /api/sse-client/family/member/{member_id}/summary` — returns age-filtered view of child's journey for parent (logged)

Admin (on `sse_router`):
- `GET /api/sse/monitor/families` — all family units with member counts
- `POST /api/sse/admin/family/emancipate-minor` — body: `{user_id, reason}`, admin-only early independence override

## Step 4: Age-Gated Identity Forge

**File**: `backend/app/sse/layer1_identity_forge.py` (max 20 new lines)

Add age-specific intake prompt sets:

```python
CHILD_INTAKE_PROMPTS = [
    (1, "opening", "Hi {name}! I'm Little Nate..."),
    (2, "character", "If you were a character in a story, what would you be like?"),
    (3, "place", "What's your favorite place in the whole world?"),
    (4, "safe", "What makes you feel safe and happy?"),
    (5, "superpower", "If you had one superpower, what would it be?"),
]

ADOLESCENT_INTAKE_PROMPTS = [
    # 8-turn: skip spiritual framework and wound indicators
    # Keep: opening, presenting_concern, identity_self, world, roots, strength, identity_forge, hope
]
```

Modify `get_intake_prompt(turn, user_name, age_tier="adult")` to select the prompt set based on `age_tier`. The existing `extract_intake_data` already handles variable conversation lengths — the extraction prompt asks for JSON fields regardless of turn count.

## Step 5: Age-Gated Panel Generation

**File**: `backend/app/sse/thera_world_engine.py` (max 15 new lines)

In `generate_journey_panel()`, after the journey/profile is loaded (~line 331), query age gate:

```python
age_info = await family_engine.check_age_gate(user_id, db_pool)
if age_info.get("age_tier") == "child":
    # Swap dark biome names for bright variants
    # Restrict NPC pool to positive archetypes
    # Force narrative tone to "wonder" or "adventure"
```

Also inject heritage landmarks into the panel prompt for age-gated users:

```python
landmarks = await family_engine.get_heritage_landmarks(user_id, db_pool)
if landmarks:
    image_prompt += ", " + ", ".join(l["visual"] for l in landmarks[:2])
```

## Step 6: Couples Narrative Threading + Coherence Trajectory + Crystal Co-Occurrence

**File**: `backend/app/sse/thera_world_engine.py` (max 15 new lines, same file as Step 5)

In `generate_journey_panel()`, after biome/character are determined (~line 347):

```python
family = await family_engine.get_family_for_user(user_id, db_pool)
if family:
    spouse = [m for m in family.get("members", []) if m["role"] == "spouse"]
    if spouse:
        spouse_id = spouse[0]["user_id"]
        # Check if spouse has recent sessions (last 7 days)
        # If yes, add "another traveler on the horizon" to image prompt

        # COHERENCE TRAJECTORY (addition 3):
        # Query nevedal_metrics for both users' C_emo trend (last 7 days)
        # Both rising → distant figure gets CLOSER ("a familiar figure walking beside you")
        # One falling → figure recedes ("a shadow on the far ridge")
        # Both falling → storm event in both panels

        # CRYSTAL CO-OCCURRENCE (addition 1):
        overlap = await family_engine.get_couples_crystal_overlap(user_id, spouse_id, db_pool)
        if overlap.get("shared_domains"):
            # Add shared NPC to image prompt — same character in both worlds
            # e.g., shared 'attachment' domain → "a bridge keeper" NPC
```

## Step 6b: Family Cycle Detection Integration

When `detect_family_cycles` finds correlated cycles across members, the panel engine injects shared storm visuals. This is called from `generate_journey_panel()` for family members:

```python
if family:
    family_cycles = await family_engine.detect_family_cycles(family["family_id"], db_pool)
    if family_cycles:
        # Active correlated cycles → add storm elements to all family members' panels
        # Log as shared event for admin visibility
```

## Step 6c: Dependent Starting Biome (Addition 6)

When a child is added to a family and begins their SSE journey, their starting biome should reflect the parent's current progress rather than always starting in `dark_forest`.

In `family_engine.get_dependent_start_biome()`, look up parent's biome and return a bright variant. The journey initialization in `thera_world_engine.py` or the enrollment flow calls this when the user is `age_gated`:

```python
parent_biome = await family_engine.get_dependent_start_biome(parent_user_id, db_pool)
# Uses mapping: dark_forest→enchanted_forest, river_valley→enchanted_river, etc.
```

## Step 6d: Family-Aware Widget Content (Addition 5)

**File**: `backend/app/sse/widget_engine.py` (max 10 new lines)

Add family-aware checks after existing priority logic:

```python
# Family biome transition: "Someone in your family is growing today"
# (no identity revealed — just family_id aggregate query)

# Dependent struggling: parent widget shows "Someone in your family needs presence today"
# (age-gated privacy: never reveal which member or what content)

# Family milestone: 3+ members had sessions this week →
# "Your family is showing up together this week"
```

These checks query `family_members` + `sse_panel_log` / `sse_user_journeys` for aggregate family activity without exposing individual data.

## Step 6e: Privacy Audit Log (Addition 7)

Every heritage access or child journey data view is logged to `family_shared_events` for clinical compliance:

```python
# In the heritage endpoint (admin.py), 3 lines:
await db_pool.execute(
    "INSERT INTO family_shared_events (family_id, event_type, event_data) VALUES ($1, 'heritage_access', $2)",
    family_id, json.dumps({"accessor": current_user_id, "target": child_user_id}))
```

This creates an auditable trail of who accessed whose data and when.

## Step 6f: Multi-Level Coaching Crystal Pathways (Addition 8)

Family Sanctuary sessions produce crystals tagged by session type. Each type feeds different story elements:

| Session Type | Source Tag | Crystal Distribution | Story Effect |
|---|---|---|---|
| Individual | `individual` | Speaker only (normal flow) | Personal NPCs and journey narrative |
| Couples | `couples` | Both partners (speaker full, listener 0.7x) | Shared NPCs, converging storylines, meeting-place landmarks |
| Parent-Child | `parent_child` | Parent full crystal + child gets age-filtered version | Guardian/child imagery, heritage features |
| Family Group | `family_group` | All members get a version | Shared weather, season change, festival events |

`tag_session_crystal()` in `family_engine.py` handles duplication and confidence adjustment. The age-appropriate filter for child crystal versions reuses `age_appropriate_calibration.py` to strip clinical vocabulary.

## Step 6g: Story Engine Family Crystal Integration (Addition 9)

**File**: `backend/app/sse/thera_world_engine.py` (max 10 new lines)

In `generate_journey_panel()`, after family context is loaded, inject family crystal context into the LLM prompt:

```python
family_crystals = await family_engine.get_family_session_crystals(user_id, family_id, db_pool)

# Add to system prompt based on crystal categories present:
# couples_crystals → "The protagonist senses another presence in the landscape.
#                      Shared themes: {domains}"
# parent_child_crystals → "Ancient paths connect the protagonist to those
#                           who came before (or will come after)"
# family_group_crystals → "The world itself is changing — all travelers feel it"
```

## Step 6h: Crystallization Pipeline Hook (Addition 10)

**DO NOT modify `bridge_server.py` (PROTECTED).**

Instead, wire via a new endpoint the Flutter app calls after a family session ends:

**File**: `backend/app/routers/admin.py` (max 15 new lines on `sse_client_router`)

```python
@sse_client_router.post("/family/tag-session")
async def tag_family_session(body: dict, user=Depends(_sse_auth)):
    # body: {session_type: "couples"|"parent_child"|"family_group",
    #        family_id: str, participant_ids: [str]}
    await family_engine.post_crystallize_family_tag(
        user["hw"], body, db_pool)
    return {"tagged": True}
```

The function queries crystals created in the last 5 minutes for the user, tags them with the family context, and duplicates as needed. This keeps `bridge_server.py` untouched while ensuring family session crystals flow into the story engine correctly.

## Step 6i: Minor Account Constraints (Addition 11)

When a dependent under 18 is added to a family, their account has special restrictions enforced at multiple layers:

**Parental Consent** (wired via `consent_privacy.py`):
- `add_family_member()` requires `consenting_parent_id` for minors
- Stores `consent_recorded_at` and `consent_parent_id` in `family_members`
- No SSE journey starts until consent is recorded (enrollment check)

**Minor Restrictions** (enforced across surfaces):
- Cannot create family units or add members (check in `create_family_unit` / `add_family_member`)
- Cannot access parent's journey/panels/crystals (family engine filters by role)
- Cannot use voice calls (checked in `voice_billing_api.py` admission)
- Cannot purchase tokens or manage billing (checked in `stripe_integration.py`)
- Widget content age-filtered: no crisis language for under 13 (uses `CHILD_CONFIG` overlays)
- "Ask Nate About This" responses age-calibrated via `age_appropriate_calibration.py`

**Parent Visibility** (`get_minor_parent_view`):
- CAN see: biome, archetype, panel thumbnails (not narratives for 13-17), check-in emotions, quest names
- CANNOT see: conversation transcripts, crystal text, session details, intake responses (except archetype)
- All access logged to `family_shared_events` for clinical compliance

**Endpoint**: `GET /api/sse-client/family/member/{member_id}/summary` (max 10 lines in admin.py) — returns filtered view based on requester relationship and child's age tier

## Step 6j: Age-Up Transition — Turning 18 (Addition 12)

**File**: `backend/app/sse/layer0_orchestrator.py` (max 15 new lines)

Daily check at 03:00 UTC:

```python
async def check_age_transitions(db_pool):
    """Find family members who turned 18 since last check."""
    rows = await db_pool.fetch(
        "SELECT * FROM family_members WHERE age_gated = true "
        "AND date_of_birth <= CURRENT_DATE - INTERVAL '18 years'")
    for row in rows:
        # Set age_gated = false, age_transitioned_at = now()
        # Role changes: 'dependent' → 'adult_child'
        # Fire admin alert: "age_transition"
        # Generate transition ceremony panel
        # Widget: "Your story has entered a new chapter."
```

**What changes at 18**: `age_gated` flips false, full 10-turn intake available (offer to redo), all biome variants unlock, full NPC roster (Serpent, Shame archetypes), voice calls unlock, own billing, can create own family unit, parent visibility reverts (no more child summary access unless now-adult grants it)

**What stays**: Journey continues (same biome, quests, missions), all panels preserved, crystal history, archetype, heritage landmarks from parents stay permanently, family membership stays (role → `adult_child`)

**Transition Ceremony Panel** in `thera_world_engine.py` (max 15 new lines):

```python
async def generate_age_transition_panel(user_id, db_pool) -> dict:
    """One-time panel: bright biome → full adult biome transition."""
    # LLM narrative: "The world opens. The enchanted forest gives way to
    # the true landscape. You stand at the threshold of your own story now."
    # Stored as panel_type='age_transition' in sse_panel_log
```

**Notification chain** (5 lines in widget_engine.py):
- Now-adult: "Happy birthday. Your Thera-World has grown with you."
- Parent: "{child_name}'s therapeutic journey is now their own."
- Admin: `age_transition` alert in `family_shared_events`

## Step 6k: Emancipation / Early Independence (Addition 13)

Admin-only override for minors (16-17) who need independent accounts (estranged parent, foster care, court-ordered).

**Endpoint**: `POST /api/sse/admin/family/emancipate-minor` (max 10 lines in admin.py on `sse_router`)

```python
@sse_router.post("/admin/family/emancipate-minor")
async def emancipate_minor(body: dict, user=Depends(_sse_admin_auth)):
    # body: {user_id, reason}
    await family_engine.emancipate_minor(
        body["user_id"], body["reason"], user["hw"], db_pool)
    return {"emancipated": True}
```

Effects:
- `age_gated = false`, `emancipated = true`, `emancipated_reason = reason`
- Removes parent visibility (blocks `get_minor_parent_view`)
- Keeps `family_id` for heritage landmarks
- Logs action with reason to `family_shared_events`
- Requires admin role — NOT parent-initiated

## Step 7: Flutter Family Constellation Screen

**File**: `mobile/lib/screens/family_constellation_screen.dart` (NEW, max 50 lines) or integrated into `settings_screen.dart`

- Family member cards with archetype image, biome badge, display name
- Head-of-household can add members via form (name, role, DOB)
- Each card shows latest panel thumbnail
- "Heritage" section for dependents shows landmark descriptions
- Age-gated members show a child-safe badge icon
- Navigate from settings or FamilySanctuaryScreen

## Step 8: SSE Monitor Families Tab

**File**: `dashboard/sse_monitoring.html` (max 30 new lines)

Add a "Families" section:
- List all family units with member count (from `/api/sse/monitor/families`)
- Click to expand: member journey status
- Admin can add/remove members

## Deployment Sequence

1. `scp` migration 177 to GREEN, run against PostgreSQL
2. `scp` family_engine.py, admin.py, layer1_identity_forge.py, thera_world_engine.py, widget_engine.py, layer0_orchestrator.py
3. Restart backend, verify 104/104 health
4. `flutter build web --release && ./deploy-web.sh`
5. Deploy sse_monitoring.html to all 3 dashboard dirs

## Privacy Invariants

- Child NEVER sees parent's `crystal_text` — only domain-transformed landmarks
- Parent cannot see child's conversation_history or clinical data through the family view
- Heritage landmarks are one-directional: parent-to-child only
- `age_gated` is computed from DOB, not manually set (prevents bypass)
- Age tier reuses `AgeAppropriateCalibrator` from `age_appropriate_calibration.py`
- Family widget content never reveals which member or what clinical content — aggregate signals only ("someone in your family")
- Every heritage/child-data access logged to `family_shared_events` with accessor and target IDs (clinical compliance audit trail)
- Couples crystal co-occurrence reveals shared DOMAINS, never individual crystal text
- Family cycle detection uses aggregate temporal patterns, never individual session content
- Parent-child crystal duplication runs age-appropriate filter before storing child's version — strips clinical vocabulary
- Listener crystal copies get 0.7x confidence (speaker retains full confidence) — prevents low-engagement crystals from dominating recall
- `post_crystallize_family_tag` does NOT modify `bridge_server.py` — hooks via Flutter endpoint call after session ends
- Crystal `source` tags (`individual`/`couples`/`parent_child`/`family_group`) are metadata only — do not change crystal recall priority or decay behavior
- Minor accounts require parental consent (`consent_recorded_at` + `consent_parent_id`) before any SSE journey starts
- Minors cannot create families, add members, access voice calls, purchase tokens, or manage billing
- Parent view of minor child is age-tiered: under 13 gets full panel thumbnails; 13-17 gets thumbnails only (no narratives) — respects adolescent therapeutic confidentiality
- Parent can NEVER see child's conversation transcripts, crystal text, session details, or intake responses (except archetype)
- At age 18: `age_gated` flips automatically, parent visibility reverts, role changes to `adult_child`. Heritage landmarks from parents stay permanently
- Emancipation is admin-only (not parent-initiated) and requires a documented reason stored in `family_shared_events`
- Widget birthday notification for age-up does NOT reveal any clinical content — celebratory only
