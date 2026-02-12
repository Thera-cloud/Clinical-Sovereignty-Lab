---
name: Settings gear for users
overview: Add a settings gear icon to both client and coach UX with role-appropriate settings, invite-a-friend via SMS share, family invitations for Top Tier, 30-day soft account deletion, and a comprehensive legal/consent/waiver document covering patents, therapeutic setting, and privacy.
todos:
  - id: legal-document
    content: Write the comprehensive legal agreement (sovereign_sanctuary_agreement.md) covering Terms, Privacy, Therapeutic Waiver, Patent Notice, and Dispute Resolution
    status: completed
  - id: flutter-settings-screens
    content: Create settings_screen.dart with ClientSettingsScreen and CoachSettingsScreen including all sections
    status: completed
  - id: flutter-gear-icons
    content: Add gear icon to NeuralInterfaceV2 and CoachPortalV2 app bars
    status: completed
  - id: invite-friend-feature
    content: Implement Invite a Friend with share_plus native share sheet and referral tracking
    status: completed
  - id: family-invite-feature
    content: "Wire family invite flow for Sovereign Circle: invite token generation, SMS share, accept handler, billing confirmation"
    status: completed
  - id: account-deletion
    content: "Implement 30-day soft delete: request handler, login restoration, daily purge task, coach active-client guard"
    status: completed
  - id: dashboard-settings
    content: Create settings.html for coach web dashboard and add gear icon to command.html
    status: completed
  - id: backend-handlers
    content: "Add WS handlers: request_account_deletion, generate_family_invite_token, accept_family_invite, update_coach_profile, update_notification_prefs"
    status: completed
  - id: consent-version-bump
    content: Bump consent version to v13.0_2026 and update Sovereign Covenant to reference full agreement
    status: completed
isProject: false
---

# Settings Gear Icon — Full Plan

## 1. Entry Points (Gear Icon Placement)

### Client (Flutter Mobile — `NeuralInterfaceV2` in `updated_screens.dart`)

- Gear icon in the app bar top-right
- Opens `ClientSettingsScreen`

### Coach (Flutter Mobile — `CoachPortalV2` in `coach_portal_v2_complete.dart`)

- Gear icon in the app bar top-right
- Opens `CoachSettingsScreen`

### Coach (Web Dashboard — `command.html`)

- Gear icon button in the header bar
- Opens `settings.html`

---

## 2. Invite a Friend (Client Feature)

Uses the phone's **native Share sheet** (no Twilio needed). Flutter's `share_plus` package opens the SMS composer with a pre-filled message from Little Nate.

**Share message template:**

> "Hey! I've been working with Little Nate -- an AI companion that's helped me understand myself in ways I didn't expect. If you're curious, try it out: [download_link]. He's waiting for you."

**Implementation:**

- Add "Invite a Friend" row in client settings under a new **Share** section
- Tapping opens native share sheet with the message pre-filled
- Download link points to app store listing (configurable in backend/env)
- Track referrals: add `referred_by` field to user profile, populated when invited user registers

**File changes:**

- `mobile/lib/screens/settings_screen.dart` (new) — share action
- `mobile/pubspec.yaml` — add `share_plus` dependency

---

## 3. Family Invite (Top Tier / Sovereign Circle)

Infrastructure partially exists but invite sending is not wired. The Stripe service `add_family_member()` creates a user with `PENDING_INVITE` status, and `notifications_service.py` has an unsent `send_family_invitation()` email template.

**New flow for Head of Household:**

- Settings section: **Family** (only shown for Sovereign Circle tier)
- "Invite Family Member" button opens a form: name, phone/email, role (Spouse / Dependent)
- Sends invite via **native SMS share** (same as friend invite but with family-specific message)
- Family invite message template:
  > "You've been invited to join our family's Sovereign Sanctuary by [inviter_name]. Little Nate is ready to welcome you: [accept_link]"
- Accept link opens app with a deep link containing a family invite token

**Billing guardrails (already in `stripe_integration.py`):**

- Spouse: Free (first one)
- First dependent: Free
- Additional members: $75/month
- Display these charges clearly in the invite flow confirmation dialog
- All charges billed to Head of Household

**Backend changes:**

- Wire `send_family_invitation()` in `notifications_service.py` to actually send
- Add `generate_family_invite_token` WS handler — creates a time-limited invite token
- Add `accept_family_invite` WS handler — validates token, links user to family
- Populate `invited_member_ids` in sanctuary creation

---

## 4. Account Deletion (30-Day Soft Delete)

Both client and coach get a "Delete My Account" option in Settings > About & Support.

**Flow:**

1. User taps "Delete My Account"
2. Confirmation dialog explains: *"Your data will be held for 30 days. If you sign back in within that window, your account will be restored. After 30 days, all data is permanently purged."*
3. Second confirmation: type "DELETE" to proceed
4. Backend sets `deletion_requested_at` timestamp and `account_status = "PENDING_DELETION"`
5. User is logged out immediately
6. If user logs in within 30 days: `account_status` resets, `deletion_requested_at` cleared
7. After 30 days: cron/scheduled task permanently deletes profile, conversation history, biometric data, and billing records (retains anonymized aggregate data for research)

**Backend changes in `bridge_server.py`:**

- New WS handler: `request_account_deletion` — sets `deletion_requested_at`, changes status, logs out
- Modify login handler: if `account_status == "PENDING_DELETION"` and within 30 days, restore and log them in
- New scheduled task: daily check for accounts past 30-day window, permanent purge

**Coach-specific:**

- Cannot delete if they have active assigned clients (must transfer or unassign first)
- Warning: "You have X active clients. Please transfer them before deleting."

---

## 5. Support, About, and Comprehensive Legal Agreement

The current Sovereign Covenant (11 sections in `mobile/lib/main.dart` lines 6088-6157) is solid but narrow. The settings screen will include a **Legal & Privacy** section that displays the full expanded agreement.

### Legal Document Structure

Create a standalone legal document accessible from settings: **"Sovereign Sanctuary — Terms of Use, Privacy Policy, and Therapeutic Waiver"**

**Part I — Terms of Use**

- Sections 1-8 of existing Sovereign Covenant (Private Membership, AI Identity, Profiling Consent, Age/Family, TRAIGA, Crisis, Zero Tolerance, Platform Immunity)
- NEW: Intellectual property notice — the platform uses patented algorithms (Nevedal Quantum Emotional Coherence Engine, US Provisional Patent) and all outputs, scoring, and analytical frameworks are proprietary
- NEW: Acceptable use policy — no scraping, reverse-engineering, or extraction of algorithmic outputs
- NEW: Service availability — no uptime guarantee, maintenance windows

**Part II — Privacy Policy**

- Section 9 of existing Covenant (Biometric Data) expanded into full privacy policy
- Data collected: voice biometrics (pitch, energy, speech rate, pause ratio), facial geometry, text conversations, emotional coherence scores, session metadata
- Data processing: Azure OpenAI (third party), encrypted in transit and at rest
- Data retention: active account data retained indefinitely; deleted accounts purged after 30 days; anonymized aggregate data retained for research
- Data sharing: never sold; shared only with assigned coach (session summaries), family head of household (aggregate family metrics), and law enforcement (if legally compelled)
- State-specific rights: California (CCPA/CPRA), Illinois (BIPA), Texas (CUBI), Virginia (VCDPA), Colorado, Connecticut, Indiana, Kentucky, Rhode Island opt-out waivers (as in existing covenant)
- Right to delete, right to export (data portability)
- Children's privacy: COPPA compliance — minors only via guardian-created dependent accounts

**Part III — Therapeutic Setting Waiver**

- Platform is NOT a licensed mental health provider
- Coaches are independent practitioners, not employees
- AI companion (Little Nate) provides emotional support, not diagnosis or treatment
- No doctor-patient or therapist-client privilege applies to AI interactions
- Coach sessions may create a therapeutic relationship governed by the coach's licensure, NOT by the platform
- Users acknowledge emotional content may surface; platform is not liable for emotional distress
- Crisis protocol acknowledgment (988, emergency room)
- Informed consent for experimental methodology: the Nevedal Quantum Emotional Coherence framework is a research model, not a clinically validated diagnostic tool
- Biometric analysis is for self-awareness and coaching support, not medical assessment

**Part IV — Patent and Proprietary Technology Notice**

- The platform utilizes technology covered by provisional patent applications
- Nevedal Formula for Quantum Emotional Coherence (C_emo calculation)
- Voice biometric extraction and emotional state modeling
- Predictability Model of Behavior (PMB)
- Family system dynamics and ventriloquism detection
- Night School AI training methodology
- Users may not: reproduce, distribute, or create derivative works from any algorithmic output
- Session transcripts are user-owned; analytical overlays (coherence scores, emotional maps, CEE windows) are platform-owned
- Research participation: aggregate anonymized data may be used in published research

**Part V — Waivers and Dispute Resolution**

- Sections 10-11 of existing Covenant (Hold Harmless, Binding Arbitration) expanded
- Assumption of risk: user acknowledges emotional exploration carries inherent risk
- Limitation of liability: platform liability capped at subscription fees paid in prior 12 months
- Indemnification: user indemnifies platform against claims from third parties
- Force majeure
- Severability clause
- Governing law: State of [TBD — likely California or Texas]
- 30-day informal dispute resolution period before arbitration
- Class action waiver (existing)
- Jury trial waiver (existing)

### Implementation

- Store the full legal document as `legal/sovereign_sanctuary_agreement.md` in the repo (single source of truth)
- Render in Flutter settings via a scrollable modal
- Render in web dashboard settings as a dedicated section
- Bump consent version from `v12.6_2026_FINAL` to `v13.0_2026` — existing users will be prompted to re-consent on next login (existing enforcement logic handles this)
- Keep `ReConsentScreen` flow as-is; it already blocks login until new version accepted

---

## 6. Complete Settings Sections (Updated)

### Client Settings

- **Profile** — email, phone, emergency contact, photo, timezone
- **Share** — Invite a Friend (native share sheet)
- **Family** (Sovereign Circle only) — Invite family member, view members, billing summary
- **Subscription** — Current plan, token balance, usage, upgrade
- **Preferences** — Notifications, voice mode default
- **Legal & Privacy** — Full agreement viewer, consent status, re-consent action
- **About & Support** — App version, help/FAQ, contact support
- **Account** — Delete account (30-day soft delete), Logout

### Coach Settings

- **Profile** — email, phone, specialties, coaching style, photo, Zoom link
- **Practice & Fees** — Coaching fee, payment mode, platform fee display
- **Tax & Compliance** — W-9 status/submit, TIN, 1099 status, address
- **Preferences** — Timezone, notifications
- **Subscription** — Current tier, certification status
- **Legal & Privacy** — Full agreement viewer, consent status
- **About & Support** — App version, help/FAQ, contact support
- **Account** — Delete account (30-day soft delete, with active-client guard), Logout

---

## 7. Files to Create or Modify

### New Files

- `mobile/lib/screens/settings_screen.dart` — ClientSettingsScreen + CoachSettingsScreen (Flutter)
- `dashboard/settings.html` — Coach web settings page
- `legal/sovereign_sanctuary_agreement.md` — Comprehensive legal document (single source of truth)

### Modified Files

- `mobile/lib/updated_screens.dart` — Add gear icon to NeuralInterfaceV2 app bar
- `mobile/lib/screens/coach_portal_v2_complete.dart` — Add gear icon to CoachPortal app bar
- `mobile/lib/main.dart` — Update Sovereign Covenant text to reference full agreement; update consent version
- `mobile/pubspec.yaml` — Add `share_plus` dependency
- `dashboard/command.html` — Add gear icon to header
- `backend/app/websocket/bridge_server.py` — New handlers: `request_account_deletion`, `restore_account`, `generate_family_invite_token`, `accept_family_invite`, `update_coach_profile`, `update_notification_prefs`
- `backend/app/services/notifications_service.py` — Wire `send_family_invitation()`
- `backend/app/websocket/sanctuary_engine.py` — Populate `invited_member_ids` from invite tokens

