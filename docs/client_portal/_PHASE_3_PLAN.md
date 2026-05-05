# Client Portal — Phase 3 Spec Plan (Consolidated)

> **Source:** `_TAB_INVENTORY_2026-05-05.md` + `_FOUNDATIONAL_SPEC.md` §3. **Output only** — no feature `.md` files created here.

---

## § A — Already created (4 specs)

| File | Covers (inventory / §3) |
|------|-------------------------|
| `01_chat_with_nate.md` | §3 row **7** Neural chat (`NeuralInterfaceV2`): core WS vocabulary, scaffold, `_ClientWsHub` context; overlaps **D13** nav pattern by reference only |
| `02_re_consent.md` | §3 row **2**, **C3** (`ReConsentScreen`); outbound **TBD** in foundational |
| `03_onboarding_trial.md` | §3 row **3**, **C5** (`OnboardingThresholdScreen`) |
| `04_onboarding_paid.md` | §3 row **4**, **C6** (`OnboardingPaidScreen`) |

---

## § B — Final consolidated spec list (05–40)

**Target:** 37 new files + 4 existing = **41** total (spec **35** split into **35a** + **35b**). Each row = one logically distinct surface; modals bundled thematically where noted.

| # | filename | covers_inventory_items | est_complexity |
|---|----------|-------------------------|----------------|
| 05 | `05_lobby_and_login.md` | §3 r**1**, **C1,C2**, **E4,E5**, error/redirect paths from lobby WS | high |
| 06 | `06_onboarding_tutorial.md` | §3 r**5**, **C7** (`mark_onboarding_complete` cross-ref §4.B) | medium |
| 07 | `07_ai_consent_gate.md` | §3 r**6**, **C8** | medium |
| 08 | `08_critical_session_security_modals.md` | **E1,E2**, **G22,G23** (force password reset + security disconnect; shared “hard stop” UX) | high |
| 09 | `09_biometric_quick_login.md` | **E3**, **G24** (opt-in dialog + Settings **SECURITY** biometrics §B) | medium |
| 10 | `10_family_sanctuary.md` | §3 r**9**, §A row 2, **D12**, socket-close caveat §10 | high |
| 11 | `11_neural_interface_interactions.md` | **D1,D2,D3,D4,D15,D16**, §B **B4-B6**, **G5,G6,G7** (mic, vault attach, TTS read-back, vocab, upload chrome); complements **01** | high |
| 12 | `12_avatar_mode.md` | **G1**, **D6**, §A row 1 (tier/`premium_features` gating §H) | medium |
| 13 | `13_ai_modes_picker.md` | **G2**, **D5**, §A row 3 (`ai_mode_activate/deactivate`) | medium |
| 14 | `14_nudges_and_metrics.md` | **G3,G4**, **D7,D8,D9**, §**B1**, §A rows 4–5 | medium |
| 15 | `15_sse_story_journey_and_recap.md` | **G8,G9**, **D10,D11**, §**B2,B3**, **E22** (intake banner + recap + dismiss) | high |
| 16 | `16_client_schedule.md` | §3 r**10**, §B Assigned Coach booking, foundational schedule WS; overlaps **§7** password-omit debt — **BLOCKED until Fix F+D+E commits land (client schedule auth fixes); do not author until those commits exist on `main`** | high |
| 17 | `17_client_settings_profile_and_preferences.md` | §3 r**11** shell + **G27** + **G28–G30** + **D13** (socket passed in); not whole tools list | high |
| 18 | `18_calendar_sync.md` | **G15**, §B CALENDAR SYNC | medium |
| 19 | `19_share_and_invite.md` | **G25,G26**, **E12**, §B SHARE | low |
| 20 | `20_family_management.md` | §3 r**21**, §B FAMILY card, **E7,E21** | high |
| 21 | `21_subscription_plan_and_billing_portal.md` | §3 r**20** (plan UI, portal, change-plan), **E10,E11**, **G31** | high |
| 22 | `22_token_vault_and_purchase.md` | §3 r**20** token vault strip + **E8** (buy tokens); distinct mental model from plan/portal | medium |
| 23 | `23_voice_therapy.md` | §3 r**23**, **E9** | medium |
| 24 | `24_sovereign_vault.md` | **G10,G11,G12**, **E19** (browser / organizer / transfer — one product, sub-sections in spec) | high |
| 25 | `25_weekly_brief.md` | §3 r**13**, **E15** | medium |
| 26 | `26_coherence_reports.md` | §3 r**14** | medium |
| 27 | `27_memory_search.md` | §3 r**15** | medium |
| 28 | `28_distress_beacon.md` | §3 r**16**, **E6** (separate WS — stays one spec) | high |
| 29 | `29_assessments.md` | §3 r**17** | medium |
| 30 | `30_coaching_mesh.md` | §3 r**18** — **VERIFY before authoring:** confirm `coaching_mesh` and `community_mesh` are distinct products vs. one shared screen rendering different views (compare `coaching_mesh_screen.dart:111` and `community_mesh_screen.dart:84` widgets, WS message namespaces, and DB tables) | high |
| 31 | `31_community_mesh.md` | §3 r**19** — **VERIFY before authoring:** same check as #30; if shared screen, collapse 30+31 into a single `30_mesh_screens.md` with view-mode sub-sections | high |
| 32 | `32_quests_and_missions.md` | **G13**, **E18** | medium |
| 33 | `33_archetype_identity.md` | **G14** | medium |
| 34 | `34_coaching_packs.md` | §3 r**22** | medium |
| 35a | `35a_home_widget.md` | **G16** — platform widget setup (iOS/Android home-screen widget, `settings_screen.dart:2904`); distinct file root from Help — **SPLIT recommended** | low |
| 35b | `35b_help_and_faq.md` | **G17** + **E20** (E20 is the modal-launch path to the same `_HelpFAQScreen` at `settings_screen.dart:5575` — single surface, two entry points; not a third file) | low |
| 36 | `36_check_in_widget_intent.md` | §3 r**24**, **C11** | low |
| 37 | `37_become_a_coach.md` | **G18**, **E13** | medium |
| 38 | `38_legal_agreements_and_data_export.md` | **G19,G20**, **E16,E17** | medium |
| 39 | `39_account_deletion.md` | **G21**, **E14** (destructive — standalone) | high |
| 40 | `40_nevedal_biometrics_service.md` | §3 r**8** (no primary UI; service/timer + `biometric_update` contract) | low |

**Gap coverage check:** **G1–G31** distributed across **11–15, 17–25, 28, 32–34, 35a, 35b, 37–40**; **E1–E22** except those folded: **E4–E5→05**, **E3→09**, **E6→28**, **E7,E21→20**, **E8→22**, **E9→23**, **E10–E11→21**, **E12→19**, **E13→37**, **E14→39**, **E15→25**, **E16–E17→38**, **E18→32**, **E19→24**, **E20→35b**, **E22→15**.

---

## § C — Specs deferred / not creating (separate `.md`)

| Item | Justification |
|------|----------------|
| **Logout** (**§A row 9**, **D14**) | Thin action on chat + lobby return; document in **05** + **01** § nav teardown only |
| **`_PaymentHistoryWidget` row** §B SUBSCRIPTION | Read-only stripe of **21**; no separate UX surface |
| **Pending downgrade banner** §B | Display variant inside **21** |
| **`mailto:` Contact Support** §B ABOUT | Zero spec surface |
| **Consent version info** §B LEGAL | Read-only label under **38** |
| **`C4` Coach Ethics** | Explicitly coach-only — out of client portal scope |
| **Coach alternate routing** (schedule-only CLIENT) §A footnote | **16** § edge case + **01** omission note |
| **Legacy `NeuralInterface`** §10 | Maintainer debt; cite in **01** appendix, no client-facing spec |

---

## § D — Recommended creation order

1. **Priority 1 — active friction / bugs (login & schedule)**  
   **05**, **08**, **09**, **16** ← **16 is LAST in batch and BLOCKED** until Fix F+D+E commits land on `main` (client schedule auth fixes). Author 05/08/09 first; gate 16 on the commit landing.  
2. **Priority 2 — tier-gated / revenue**  
   **06**, **07**, **10**, **21**, **22**, **23**, **24**, **12**, **34**  
3. **Priority 3 — QoL chat chrome**  
   **11**, **13**, **14**, **15**, **25**, **26**, **27**, **17**, **18**, **19**  
4. **Priority 4 — edge / compliance / niche**  
   **28**, **29**, **30**, **31**, **32**, **33**, **35a**, **35b**, **36**, **37**, **38**, **39**, **40**

---

## § E — Cross-portal terminology check (client vs `docs/coach_portal/features/`)

| Client plan spec (representative) | Coach portal analogue | Terminology mismatch / flag |
|-----------------------------------|----------------------|----------------------------|
| **16** Schedule / booking | `02_schedule.md` | Client UX: **book / availability**; coach: **schedule** roster — aligned term **schedule** |
| **25** Weekly brief | `04_briefings.md` | Client **Brief** vs coach **Briefings** — same idea, plural vs singular branding |
| **26** Coherence reports | `03_insights.md` | Coach umbrella **Insights** may subsume metrics; client **Nevedal coherence** naming — clarify in specs |
| **24** Sovereign Vault | `09_folder.md` | Coach **Folder** uploads vs client **Vault** product — distinct names, related blob/R2 concepts |
| **30 / 31** Mesh screens | Coach **training** trajectory (`07_training.md`, mesh in DOJO orbit) | Client **Community / Coaching mesh** vs coach **training / mesh engine** docs — cross-link glossary |
| **01 / 11** Neural chat | `01_clients.md` | Coach sees **clients** list; client sees **Little Nate chat** — no shared end-user term |
| **29** Assessments | `05_dojo.md` / quizzes | Risk: **quiz** vs **DOJO assessment** vs **assessment** — keep **Assessments** for client-facing spec title |

---

*Plan generated 2026-05-05. Revise counts if inventory IDs shift.*
