# Client Portal — Tab & Feature Inventory

> **Generated:** 2026-05-05 — read-only investigation. Counterpart to `_FOUNDATIONAL_SPEC.md`. Every claim cites `file:line`. **TBD** = not verified.

---

## § A — Main screen tabs (post-login client surface)

The client portal **has no `TabController` / `BottomNavigationBar` / `NavigationBar`**. After login, `NeuralInterfaceV2` is a single-`Scaffold` chat surface — `updated_screens.dart:3663–4137`. "Navigation" happens via **`AppBar` action buttons** that push named screens. Verified:

| # | "Tab" (AppBar action) | Icon | file:line | Conditional? | Default surface? | Needs spec? |
|---|---|---|---|---|---|---|
| 0 | Chat body (primary surface) | — | `updated_screens.dart:3796` | No | **Yes** (loaded first) | Yes (`01_chat_with_nate.md` ✓) |
| 1 | Avatar Mode toggle | `face` | `updated_screens.dart:3688–3696` | `_canUseAvatarMode()` → `premium_features.avatar` OR tier ∈ `{TOP_TIER, SOVEREIGN_CIRCLE}` — `updated_screens.dart:3494–3507` | No | Yes (gap) |
| 2 | Family Sanctuary | `family_restroom` | `updated_screens.dart:3698–3715` | None (always shown) | No | Yes (`02_family_sanctuary.md` — TBD) |
| 3 | AI Modes picker | `psychology` | `updated_screens.dart:3717–3724` | None | No | Yes (gap) |
| 4 | Nudges sheet | `notifications_active` | `updated_screens.dart:3726–3743` | `_pendingNudges.isNotEmpty` | No | Yes (gap) |
| 5 | Metrics sheet | `analytics` | `updated_screens.dart:3745–3749` | None | No | Yes (gap) |
| 6 | Custom Vocabulary sheet | `menu_book` | `updated_screens.dart:3750–3754` | None | No | Yes (gap) |
| 7 | Read draft aloud / Stop | `volume_up` / `stop_circle` | `updated_screens.dart:3755–3764` | None | No | Yes (gap, small) |
| 8 | Settings nav | `settings` | `updated_screens.dart:3765–3786` | None | No | Yes (`11_settings.md` — TBD) |
| 9 | Logout | `logout` | `updated_screens.dart:3787–3793` | None | No | No (action, not feature) |

Body adornments above the `TextField` input bar — also "tab-equivalent" surfaces:

| # | Element | file:line | Conditional? |
|---|---|---|---|
| B1 | Quick metrics bar (C/G/Q + mood) | `updated_screens.dart:3799–3812` | `_metrics.isNotEmpty` |
| B2 | SSE Story Journey banner → `IntakeConversationScreen` | `updated_screens.dart:3814–3840` | `_sseIntakePending` (set in `_checkSseIntake` — `1987–2000`) |
| B3 | Welcome-back recap card | `updated_screens.dart:3842–3867` | `_recapData != null && !_recapDismissed && !_sseIntakePending` |
| B4 | Vault attachment button | `updated_screens.dart:4068–4080` | `AppConfig.ENABLE_SOVEREIGN_VAULT && _canUseVault()` — `updated_screens.dart:3510–3516` |
| B5 | Mic / dictation toggle | `updated_screens.dart:4051–4067` | `_speechAvailable` |
| B6 | Upload progress indicator | `updated_screens.dart:4039–4044` | `_uploadProgressState.isVisible` |

**Coach/admin alternate routing** (out of scope, but documented for reference): `main.dart:6738–6794`. CLIENT branch lands on `NeuralInterfaceV2` unless `subscription_plan == 'COACH_ONLY'` or `can_access_nate == false` → `ClientScheduleScreen` — `main.dart:6755–6759`.

---

## § B — Settings screen items (`ClientSettingsScreen`, role=CLIENT)

Source: `mobile/lib/screens/settings_screen.dart` — class `220–`, build `2236–3142`. Section helper: `_sectionHeader` — `3190`. Tier guards: `_isCoachOnly` — `737`; `_isSovereignCircle` — `739–742`; `_hasVaultAccess` — `499–502`.

| Section | Item label | file:line | Target / action | Conditional? | Needs spec? |
|---|---|---|---|---|---|
| **PROFILE** (`2260`) | Email / Phone / Emergency / Timezone | `2262–2265` | `_saveProfile` (REST) | None | Yes (sub) |
| | Edit / Save / Cancel | `2266–2290` | `update_profile` WS — `2846–2849` | None | — |
| **CALENDAR SYNC** (`2295`) | `GoogleCalendarSection` widget | `2296–2298` | OAuth REST | None | Yes |
| **SHARE** (`2303`) | Invite a Friend | `2305` | `_inviteFriend` — `1502` | `!_isCoachOnly` (`2301`) | Yes |
| | Copy link | `2325–2344` | clipboard | same | — |
| **FAMILY** (`2354`) | Invite Family Members | `2356` | `_showFamilyInviteDialog` — `1522` | `_isSovereignCircle` (`2353`) | Yes |
| | Roster + pending invites | `2367–2513` | `sanctuary_get_members` WS, etc. | same | Yes |
| **SUBSCRIPTION** (`2519`) | Plan / Token Balance / Usage | `2521–2523` | display | `!_isCoachOnly` (`2518`) | Yes |
| | Pending downgrade banner | `2525–2547` | display | `pending_plan` populated | — |
| | Change Plan | `2549–2561` | `_showChangePlanSheet` — `1092` | same | Yes |
| | Manage Subscription | `2563–2575` | `_openBillingPortal` — `1070` | same | Yes |
| | Payments / Family / Coaching links | `2578–2602` | `PaymentMethodsScreen`, `FamilyManagementScreen`, `CoachingPackScreen` | same | Yes (3) |
| | `_PaymentHistoryWidget` | `2604` | display | same | Yes |
| **VOICE THERAPY** (`2609`) | Prepaid balance + Buy Voice Minutes | `2611–2655` | `_showBuyVoiceMinutesSheet` — `950` | None | Yes |
| **TOKEN VAULT** (`2660`) | Balance / Today / This Month | `2662–2723` | display | `!_isCoachOnly` (`2740` end) | Yes |
| | Buy Tokens | `2725–2737` | `_showBuyTokensSheet` — `787` | same | Yes |
| **SOVEREIGN VAULT** (`2744`) | Browse Vault | `2778–2786` | `VaultBrowserScreen` | `ENABLE_SOVEREIGN_VAULT && _hasVaultAccess` (`2743`) | Yes |
| | Transfer Crystal | `2787–2789` | `_showTransferCrystalFlow` | same | Yes |
| | Organize with Nate | `2790–2795` | `NateOrganizerScreen` | `_isSovereignCircle` (`2790`) | Yes |
| **PREFERENCES** (`2801`) | Push / Reminders / Crisis toggles | `2803–2814` | `_saveNotificationPrefs` | None | Yes |
| | Voice Mode by Default | `2816–2819` | `_saveVoicePref` | None | — |
| | Preferred Contact (email/SMS) | `2821–2868` | `update_profile` WS — `2846–2849` | None | — |
| **YOUR TOOLS** (`2874`) | Assessments | `2876–2880` | `QuizScreen` | `!_isCoachOnly` (`2872`) | Yes (`17`) |
| | Coherence Reports | `2881–2885` | `NevedalReportsScreen` | same | Yes (`14`) |
| | Weekly Brief | `2886–2888` | `_showWeeklyBrief` — `2125` | same | Yes (`13`) |
| | Memory Search | `2889–2893` | `SecureSearchScreen` | same | Yes (`15`) |
| | Distress Beacon | `2894–2898` | `DistressBeaconScreen` | same | Yes (`16`) |
| **HOME WIDGET** (`2904`) | Set Up Home Widget | `2906–2918` | platform-instructions sheet | `!kIsWeb && !_isCoachOnly` (`2903`) | Yes |
| **ASSIGNED COACH** (`2924`) | Coach card + specs | `2932–2958` | REST `client/coach-info` | None | Yes (sub) |
| | View Availability & Book | `2960–2970` | `ClientScheduleScreen` | coach known | Yes (`10`) |
| **COACHING TOOLS** (`2977`) | Group Session | `2979–2987` | `CoachingMeshScreen` | `!_isCoachOnly` (`2975`) | Yes (`18`) |
| | Community Circle | `2988–2994` | `CommunityMeshScreen` | same | Yes (`19`) |
| **YOUR ARCHETYPE** (`2999`) | Change Archetype | `3009–3020` | `POST .../sse-client/identity/reset` | `!_isCoachOnly` (same block) | Yes (gap) |
| **YOUR QUESTS & MISSIONS** (`3025`) | Active list + pause/complete | `3026–3038` | `_questAction` / `_missionAction` | same | Yes (gap) |
| | New Quest / New Mission | `3039–3040` | `_showNewQuestDialogSettings` — `406`, `_showNewMissionDialogSettings` — `431` | same | — |
| **SECURITY** (`3046`) | Biometric / Quick Login toggle | `3048–3083` | `_bioIdentity.setBiometricEnabled` | None | Yes |
| **LEGAL & PRIVACY** (`3088`) | Terms, Privacy & Waivers | `3090` | `_showLegalAgreement` — `2229` | None | Yes |
| | Download My Data | `3091` | `_requestDataExport` — `2134` | None | Yes |
| | Consent Version (info) | `3092` | display | None | — |
| **ABOUT & SUPPORT** (`3097`) | Help & FAQ | `3100–3104` | `_HelpFAQScreen` — `5575` | None | Yes (gap) |
| | Contact Support | `3105–3107` | `mailto:` | None | — |
| **BECOME A COACH** (`3113`) | Upgrade / Re-apply / Pending | `3114–3121` | `_requestCoachUpgrade` — `1831` | `!_isCoachOnly` (`3111`) | Yes (gap) |
| **ACCOUNT** (`3126`) | Delete My Account | `3128` | `_requestAccountDeletion` — `2004` | None | Yes |
| | Logout | `3129–3136` | clear creds → `LobbyScreen` | None | — |

---

## § C — Lobby / onboarding entry points (pre-NeuralInterfaceV2)

| # | Surface | Class | file:line | Auto-redirect or persistent? |
|---|---|---|---|---|
| C1 | App bootstrap | `_InitialRouteWidget` → `LobbyScreen` | `main.dart:215`, `247–318` | Auto |
| C2 | Lobby (login + role chooser) | `LobbyScreen` / `_LobbyScreenState` | `main.dart:6206`, `6214` | Persistent until `login_success` |
| C3 | Re-consent gate | `ReConsentScreen` | `main.dart:9837` | Auto (when `consent_update_needed` — `6660, 6674–6681`) |
| C4 | Coach Ethics gate | `CoachEthicsScreen` | `main.dart:9919` | Auto, **coach-only** (`6661, 6684–6691`) — out of client scope |
| C5 | Trial onboarding | `OnboardingThresholdScreen` | `onboarding_threshold_screen.dart:15` | Auto (`isTrial && !hasSeenOnboarding` — `main.dart:6704–6712`) |
| C6 | Paid onboarding | `OnboardingPaidScreen` | `onboarding_paid_screen.dart:14` | Auto (`isPaid && !hasSeenPaidOnboarding` — `main.dart:6714–6727`) |
| C7 | Mandatory tutorial | `OnboardingTutorialScreen` | `updated_screens.dart:58` | Auto (`!onboardingDone && role != 'ADMIN'` — `main.dart:6730–6737`) |
| C8 | AI consent | `AiConsentScreen` | `ai_consent_screen.dart:23` | Auto (`!hasConsent && !localConsent` — `main.dart:6761–6780`) |
| C9 | Force password reset | `_showForcePasswordResetDialog` | `main.dart:6430`, fired `6797–6801` | Auto modal (when `force_password_reset` event) |
| C10 | Biometric opt-in | `_showBiometricOptInDialog` | invoked `main.dart:6669` | Auto modal before navigating |
| C11 | Widget intent → Check-in | `CheckinScreen` | `checkin_screen.dart:7`; trigger `main.dart:6788–6792` | Auto (when `_pendingWidgetAction == 'open_checkin'`) |

---

## § D — `NeuralInterfaceV2` internal features (sub-features of the chat surface)

Each is a substantive sub-feature warranting its own spec entry.

| # | Sub-feature | file:line | Brief description |
|---|---|---|---|
| D1 | Mic dictation (speech_to_text) | `updated_screens.dart:4051–4067`; controls `2922–2974` | Mic toggle, dictation buffer, sentence/word delete by voice |
| D2 | Vault attachment | `4068–4080` | `[Vault:<id>]` token injection into `_chatController` |
| D3 | Read draft aloud (TTS) | `3755–3764`; `_readBackDraft` `2445–2455` | Plays current draft via TTS engine |
| D4 | Custom Vocabulary sheet | `3750–3754`; `_openVocabularySheet` `2200` | User-defined terms used by speech recognition |
| D5 | AI Modes picker | `3717–3724`; `_showAiModePicker` `1940` | Activates `ai_mode_activate` / `ai_mode_deactivate` (`1877–1889`) |
| D6 | Avatar Mode (3D) | `3688–3696`; `_canUseAvatarMode` `3494`; `_toggleAvatarMode` `3519` | Spline iframe avatar; gated `TOP_TIER`+ |
| D7 | Nudges sheet | `3726–3743`; `_showNudgesSheet` `1788` | Displays `_pendingNudges`; `nudge_mark_opened` / `nudge_dismiss` |
| D8 | Metrics sheet | `3745–3749`; `_showMetricsSheet` `3392` | C_emo / GAP / Quantum / mood detail |
| D9 | Quick metrics bar | `3799–3812` | Persistent above input bar |
| D10 | SSE Story banner → `IntakeConversationScreen` | `3814–3840`; `IntakeConversationScreen` `onboarding_paid_screen.dart:550` | Begins identity intake conversation |
| D11 | Welcome-back recap card | `3842–3867` | Journey/quest/mission summary at session start |
| D12 | Family Sanctuary nav (closes parent socket) | `3698–3715` | iOS Safari WS contention mitigation `3701–3703` |
| D13 | Settings nav (passes `widget.socket`) | `3765–3786` | Reuses chat WS for settings WS calls |
| D14 | Logout | `3787–3793` | Closes socket → `LobbyScreen` |
| D15 | Upload progress indicator | `4039–4044` | Visible during vault uploads |
| D16 | Vault item return → token injection | `3779–3783` | `Navigator.push` result handling |

---

## § E — Modal / overlay features

| # | Modal | Trigger | file:line |
|---|---|---|---|
| E1 | Force password reset dialog | WS `force_password_reset` event | `main.dart:6797–6801`; dialog `6430–6500+` |
| E2 | Security disconnect dialog | WS `security_disconnect` event | `main.dart:6803–6830` |
| E3 | Biometric opt-in dialog | flag `_showBiometricOptIn` post-login | `main.dart:6667–6669` |
| E4 | Login failed snackbar / shake | WS `login_failed` | `main.dart:6831–6858` |
| E5 | Forgot password / username sent | WS events | `main.dart:6859–6872` |
| E6 | Distress Beacon screen (separate WS) | Settings → Your Tools | `distress_beacon_screen.dart:33`, `47`; payload `173–178` |
| E7 | Family invite dialog | Settings → Family | `settings_screen.dart:1522` |
| E8 | Buy Tokens sheet | Settings → Token Vault | `settings_screen.dart:787` |
| E9 | Buy Voice Minutes sheet | Settings → Voice Therapy | `settings_screen.dart:950` |
| E10 | Open billing portal | Settings → Manage Subscription | `settings_screen.dart:1070` |
| E11 | Change plan sheet | Settings → Change Plan | `settings_screen.dart:1092` |
| E12 | Invite Friend (SMS share) | Settings → Share | `settings_screen.dart:1502` |
| E13 | Coach upgrade request | Settings → Become a Coach | `settings_screen.dart:1831` |
| E14 | Account deletion flow | Settings → Account | `settings_screen.dart:2004` |
| E15 | Weekly brief modal | Settings → Your Tools | `settings_screen.dart:2125`; REST `6321–6323` |
| E16 | Data export request | Settings → Legal & Privacy | `settings_screen.dart:2134` |
| E17 | Legal agreement viewer | Settings → Legal & Privacy | `settings_screen.dart:2229` |
| E18 | New quest / new mission dialogs | Settings → Quests & Missions | `settings_screen.dart:406`, `431` |
| E19 | Transfer crystal flow | Settings → Sovereign Vault | `_showTransferCrystalFlow` (TBD line) |
| E20 | Help & FAQ screen | Settings → About | `settings_screen.dart:5575` (`_HelpFAQScreen`) |
| E21 | Family member remove confirm | Settings → Family roster | `settings_screen.dart:2444` |
| E22 | Recap dismiss action | NeuralInterfaceV2 body | `updated_screens.dart:2025` |

---

## § F — Foundational spec § 3 cross-check

Foundational spec § 3 enumerates 24 features (rows 1–24).

| Spec row | Foundational label | Matched to (this inventory) | Status |
|---|---|---|---|
| 1 | Lobby & login | § C, C2 | matched |
| 2 | Re-consent | § C, C3 | matched |
| 3 | Onboarding trial | § C, C5 | matched (spec ✓) |
| 4 | Onboarding paid | § C, C6 | matched (spec ✓) |
| 5 | Onboarding tutorial | § C, C7 | matched |
| 6 | AI consent gate | § C, C8 | matched |
| 7 | Neural chat (v2) | § A row 0 + § D | matched (spec ✓) |
| 8 | Nevedal biometrics | service `nevedal_flutter.dart:471–516` | matched (no UI) |
| 9 | Family Sanctuary | § A row 2 | matched |
| 10 | Client schedule | § B → ASSIGNED COACH | matched |
| 11 | Client settings hub | § B (root) | matched |
| 12 | Your tools | § B → YOUR TOOLS | matched |
| 13 | Weekly brief | § E, E15 | matched |
| 14 | Coherence reports | § B → YOUR TOOLS | matched |
| 15 | Memory search | § B → YOUR TOOLS | matched |
| 16 | Distress beacon | § B + § E, E6 | matched |
| 17 | Assessments | § B → YOUR TOOLS | matched |
| 18 | Coaching mesh | § B → COACHING TOOLS | matched |
| 19 | Community mesh | § B → COACHING TOOLS | matched |
| 20 | Subscription & billing | § B → SUBSCRIPTION | matched |
| 21 | Family management | § B + § E, E7 | matched |
| 22 | Coaching packs | § B (link in Subscription) | matched |
| 23 | Voice therapy prefs | § B → VOICE THERAPY | matched |
| 24 | Check-in widget | § C, C11 | matched (intent-only entry) |

**Code surfaces with NO row in foundational § 3 (gaps):**

| Gap | Discovery anchor | Severity |
|---|---|---|
| G1 | Avatar Mode | § A row 1 / § D6 | High (premium gating, 3D iframe) |
| G2 | AI Modes picker | § A row 3 / § D5 | High (server-side mode activation) |
| G3 | Nudges system | § A row 4 / § D7 | High (notifications surface) |
| G4 | Metrics sheet | § A row 5 / § D8 | Medium |
| G5 | Custom Vocabulary | § A row 6 / § D4 | Medium |
| G6 | Mic dictation | § D1 | Medium |
| G7 | TTS read-aloud | § A row 7 / § D3 | Low |
| G8 | SSE Story Journey + IntakeConversationScreen | § D10 | High (narrative pipeline) |
| G9 | Welcome-back recap card | § D11 | Low |
| G10 | Sovereign Vault browser | § B → SOVEREIGN VAULT | High |
| G11 | Nate Organizer | § B → SOVEREIGN VAULT | Medium |
| G12 | Transfer Crystal | § B → SOVEREIGN VAULT / § E19 | Medium |
| G13 | Quests & Missions | § B → YOUR QUESTS & MISSIONS | High |
| G14 | Archetype change | § B → YOUR ARCHETYPE | Medium |
| G15 | Calendar Sync (Google) | § B → CALENDAR SYNC | Medium |
| G16 | Home Widget setup | § B → HOME WIDGET | Low |
| G17 | Help & FAQ | § E, E20 | Low |
| G18 | Become a Coach upgrade | § B → BECOME A COACH | Medium |
| G19 | Legal Agreement viewer | § E, E17 | Low |
| G20 | Data export | § E, E16 | Medium |
| G21 | Account deletion | § E, E14 | Medium |
| G22 | Force password reset modal | § E, E1 | Medium |
| G23 | Security disconnect modal | § E, E2 | Medium |
| G24 | Biometric opt-in (and Settings biometric toggle) | § E, E3 + § B → SECURITY | Medium |
| G25 | Invite Friend (SMS share) | § E, E12 | Low |
| G26 | Share / copy link | § B → SHARE | Low |
| G27 | Profile editor (PROFILE section) | § B → PROFILE | Medium |
| G28 | Notification preferences | § B → PREFERENCES | Low |
| G29 | Voice mode default toggle | § B → PREFERENCES | Low |
| G30 | Preferred contact (email/SMS) | § B → PREFERENCES | Low |
| G31 | Payment methods screen | § B (Subscription quick link) | Medium |

**Foundational rows with no code (vestigial):** none found in this pass — every row in § 3 traces to a class.

---

## § G — Recommended Phase 3 spec count

**Total recommended specs:** **24 (foundational rows)** + **31 (gaps G1–G31)** = **55** feature specs. Realistically, group small siblings to land at **~38–42** files.

Suggested numbered list (existing files marked ✓):

```
01_chat_with_nate.md                     ✓ (created)
02_family_sanctuary.md                   foundational #9
03_onboarding_trial.md                   ✓ (created)
04_onboarding_paid.md                    ✓ (created)
05_onboarding_tutorial.md                foundational #5
06_ai_consent_gate.md                    foundational #6
07_lobby_and_login.md                    foundational #1
08_re_consent_gate.md                    foundational #2
09_force_password_reset_modal.md         G22
10_security_disconnect_modal.md          G23
11_biometric_optin_and_quick_login.md    G24
12_settings_root.md                      foundational #11 (PROFILE + sectional index)
13_calendar_sync.md                      G15
14_share_invite.md                       G25 + G26
15_family_section.md                     foundational #21 (FAMILY card + invite)
16_subscription_overview.md              foundational #20
17_change_plan_flow.md                   E11
18_billing_portal_link.md                E10
19_payment_methods.md                    G31
20_family_management_screen.md           foundational #21 detailed
21_coaching_packs_screen.md              foundational #22
22_voice_therapy.md                      foundational #23 (balance + buy minutes)
23_token_vault.md                        foundational #20 detail (Token section)
24_buy_tokens_flow.md                    E8
25_sovereign_vault_browser.md            G10
26_transfer_crystal.md                   G12
27_nate_organizer.md                     G11
28_preferences.md                        G28 + G29 + G30
29_your_tools_index.md                   foundational #12
30_assessments.md                        foundational #17
31_coherence_reports.md                  foundational #14
32_weekly_brief.md                       foundational #13
33_memory_search.md                      foundational #15
34_distress_beacon.md                    foundational #16
35_home_widget_setup.md                  G16
36_assigned_coach_card.md                (subset of foundational #11)
37_client_schedule.md                    foundational #10
38_coaching_mesh.md                      foundational #18
39_community_mesh.md                     foundational #19
40_archetype_change.md                   G14
41_quests_and_missions.md                G13
42_security_section.md                   G24 detail
43_legal_and_privacy_viewer.md           G19
44_download_my_data.md                   G20
45_help_and_faq.md                       G17
46_become_a_coach_upgrade.md             G18
47_account_deletion.md                   G21
48_logout.md                             (small)
49_avatar_mode.md                        G1
50_ai_modes_picker.md                    G2
51_nudges_system.md                      G3
52_metrics_sheet.md                      G4
53_custom_vocabulary.md                  G5
54_mic_dictation.md                      G6
55_tts_read_draft.md                     G7
56_sse_story_journey_intake.md           G8
57_welcome_recap_card.md                 G9
58_nevedal_biometrics_service.md         foundational #8 (no UI)
59_checkin_widget_intent.md              foundational #24
```

(59 files; final count after consolidation TBD per author judgment.)

---

## § H — Conditional features (tier-gated, role-gated, platform-gated)

| Feature | Gating condition | file:line of gate |
|---|---|---|
| Avatar Mode | `premium_features.avatar == true` OR tier ∈ `{TOP_TIER, SOVEREIGN_CIRCLE}` | `updated_screens.dart:3494–3507` |
| Sovereign Vault (browse, transfer) | `AppConfig.ENABLE_SOVEREIGN_VAULT && _hasVaultAccess` (tier ∈ `{STANDARD, TOP_TIER, FAMILY}`) | `settings_screen.dart:499–502`, `2743` |
| Vault attachment in chat | `AppConfig.ENABLE_SOVEREIGN_VAULT && _canUseVault()` (tier ∈ `{STANDARD, INNER_CHAMBER, TOP_TIER, SOVEREIGN_CIRCLE}`) | `updated_screens.dart:3510–3516`, `4068` |
| Nate Organizer | `_isSovereignCircle` (tier ∈ `{TOP_TIER, SOVEREIGN}`) | `settings_screen.dart:739–742`, `2790` |
| FAMILY section + Invite | `_isSovereignCircle` | `settings_screen.dart:2353` |
| SHARE section | `!_isCoachOnly` | `settings_screen.dart:2301` |
| SUBSCRIPTION + TOKEN VAULT | `!_isCoachOnly` | `settings_screen.dart:2518`, `2740` |
| YOUR TOOLS | `!_isCoachOnly` | `settings_screen.dart:2872` |
| HOME WIDGET | `!kIsWeb && !_isCoachOnly` | `settings_screen.dart:2903` |
| COACHING TOOLS / ARCHETYPE / QUESTS | `!_isCoachOnly` | `settings_screen.dart:2975`, `3043` |
| BECOME A COACH | `!_isCoachOnly` | `settings_screen.dart:3111` |
| Chat surface vs. Schedule-only | `subscription_plan == 'COACH_ONLY'` OR `can_access_nate == false` → `ClientScheduleScreen` instead of `NeuralInterfaceV2` | `main.dart:6755–6759` |
| Trial onboarding | `role == 'CLIENT' && isTrial && !hasSeenOnboarding` | `main.dart:6704–6712` |
| Paid onboarding | `role == 'CLIENT' && isPaid && !hasSeenPaidOnboarding` | `main.dart:6714–6727` |
| Mandatory tutorial | `!onboardingDone && role != 'ADMIN'` | `main.dart:6730–6737` |
| AI consent | `!hasConsent && !localConsent` | `main.dart:6770–6780` |
| Re-consent | `data['consent_update_needed'] == true` | `main.dart:6660`, `6674–6681` |
| Coach Ethics gate | `coach_ethics_needed && role == 'COACH'` (out of CLIENT scope) | `main.dart:6661`, `6684–6691` |
| Check-in via widget | `_pendingWidgetAction == 'open_checkin' && role == 'CLIENT'` | `main.dart:6788–6792` |
| Biometric Login section caveats (web) | `kIsWeb` text branch | `settings_screen.dart:3066–3083` |
| Coach upgrade re-apply vs. apply | `profile['upgrade_to_coach_status'] in {PENDING, REJECTED}` | `settings_screen.dart:3115–3120` |
| Recap card | `_recapData != null && !_recapDismissed && !_sseIntakePending` | `updated_screens.dart:3842` |
| SSE Story banner | `_sseIntakePending` | `updated_screens.dart:3814` |

---

*End of inventory. No code changes; no spec files created in this pass.*
