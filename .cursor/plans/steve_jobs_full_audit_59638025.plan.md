---
name: Steve Jobs Full Audit
overview: Execute all 158 tests of the Steve Jobs audit across 12 categories — verifying every user-facing surface of the platform is functioning at 100% before building the Assign Coach Admin Tab.
todos:
  - id: phase-1
    content: "Phase 1: First Contact (Tests 1-12) — Login, registration, portal isolation, browser compat"
    status: completed
  - id: phase-2
    content: "Phase 2: Client Experience (Tests 13-31) — Every client screen and action"
    status: completed
  - id: phase-3
    content: "Phase 3: Coach Experience (Tests 32-50) — Every coach tool, critical for Assign Coach build"
    status: completed
  - id: phase-4
    content: "Phase 4: Family Experience (Tests 51-61) — Family billing mechanics"
    status: completed
  - id: phase-5
    content: "Phase 5: Money (Tests 62-84) — Every dollar correct"
    status: completed
  - id: phase-6
    content: "Phase 6: SkyEye (Tests 85-95) — Social media command center"
    status: completed
  - id: phase-7
    content: "Phase 7: Sovereign Command (Tests 96-108) — Admin dashboard"
    status: completed
  - id: phase-8
    content: "Phase 8: Security (Tests 109-122) — Auth, MFA, Sentinel, isolation"
    status: completed
  - id: phase-9
    content: "Phase 9: Infrastructure (Tests 123-136) — Services, trust, containers"
    status: completed
  - id: phase-10
    content: "Phase 10: Liminal Presence (Tests 137-141) — Voice integrity"
    status: completed
  - id: phase-11
    content: "Phase 11: Edge Cases (Tests 142-150) — Scale and concurrency"
    status: completed
  - id: phase-12
    content: "Phase 12: App Store Compliance (Tests 151-158) — Submission readiness"
    status: completed
isProject: false
---

# Steve Jobs Full Audit — 158 Tests, 12 Categories

## Execution Strategy

Each section is tested via a combination of:

- **Live API probes** (`curl` against production endpoints via SSH)
- **Database verification** (direct `psql` queries for data integrity)
- **WebSocket flow tests** (simulated login/message sequences)
- **UI verification** (endpoint responses matching what dashboards render)
- **Flutter build verification** (for mobile screen correctness)

Results are logged as PASS/FAIL/WARNING with evidence (HTTP status codes, query results, error messages). Any FAIL triggers an immediate fix before proceeding to the next section.

## Phase 1: First Contact (Tests 1-12)

Verify every login path, registration flow, portal isolation, and browser compatibility.

- Tests 1-3: Client/Coach/Admin registration and login end-to-end
- Tests 4-5: Admin triple-layer auth + wrong-portal rejection
- Tests 6-7: Safari cold start + WebSocket-before-credentials ordering
- Tests 8-9: Password reset via email and phone (Twilio Verify)
- Tests 10-12: Dual-account routing, consent gate, biometric login

**Key files**: [bridge_server.py](backend/app/websocket/bridge_server.py) (auth handlers), [main.dart](mobile/lib/main.dart) (login UI)

## Phase 2: Client Experience (Tests 13-31)

Every client-facing screen must load, render data, and handle user actions.

- Tests 13-16: Onboarding, chat, voice mode, AI modes
- Tests 17-19: Avatar, session history, coherence metrics
- Tests 20-22: Vault upload/search/organize
- Tests 23-27: Quiz, billing, payment methods, settings, notifications
- Tests 28-31: Distress beacon, community mesh, account deletion, reports

**Key files**: All screens in [mobile/lib/screens/](mobile/lib/screens/), REST endpoints in [billing.py](backend/app/routers/billing.py), [vault_api.py](backend/app/routers/vault_api.py)

## Phase 3: Coach Experience (Tests 32-50)

Every coach tool must function — this is critical path for the Assign Coach build.

- Tests 32-36: Dashboard, filters, pre-session briefing, scheduling, live session
- Tests 37-42: Session notes, fee setting, coaching advice, Night School, DOJO training, DOJO Mentor
- Tests 43-50: Judge DOJO, Coach Nate progress, W-9, financials, assistant coach, supervised hours, coaching mesh, ethics

**Key files**: [coach_portal_v2_complete.dart](mobile/lib/screens/coach_portal_v2_complete.dart), [coach.py](backend/app/routers/coach.py), [coach_hierarchy_api.py](backend/app/routers/coach_hierarchy_api.py), [sessions.py](backend/app/routers/sessions.py)

## Phase 4: Family Experience (Tests 51-61)

Family billing mechanics must be airtight before multi-coach assignment.

- Tests 51-54: Add spouse (free), child under 12 (free), paid dependents (tiered), family sanctuary
- Tests 55-58: Dependent Get Help billing, group sanctuary billing, member removal + tier recalc
- Tests 59-61: Family invite flow, admin merge, admin separation

**Key files**: [billing.py](backend/app/routers/billing.py) (family endpoints), [stripe_integration.py](backend/app/services/stripe_integration.py), [bridge_server.py](backend/app/websocket/bridge_server.py) (sanctuary handlers)

## Phase 5: Money (Tests 62-84)

Every dollar must be correct — extends the completed financial audit with user-perspective tests.

- Tests 62-66: Subscription lifecycle (checkout, upgrade, downgrade, cancel, failed payment)
- Tests 67-72: Token packs, consumption tracking, sharing fee, GKM donations, receipt threshold, free month
- Tests 73-79: Session payment 72h, auto-cancel 24h, coach payout, minimum fee, signup code sharing, DOJO discounts, master coach sharing
- Tests 80-84: School discount enrollment, family member checkout, Stripe webhooks, founding member, corporate billing

**Key files**: [session_payment_agent.py](backend/app/services/session_payment_agent.py), [stripe_integration.py](backend/app/services/stripe_integration.py), [gkm_api.py](backend/app/routers/gkm_api.py), [school_code_api.py](backend/app/routers/school_code_api.py)

## Phase 6: SkyEye (Tests 85-95)

Social media command center end-to-end.

- Tests 85-89: Platform connections, content creation, Big Nate Chat, Notification Observer, post analytics
- Tests 90-95: Campaigns, drip sequences, compliance, LinkedIn dual-credential, token health, session engine cycle

**Key files**: [skyeye_api.py](backend/app/routers/skyeye_api.py), [skyeye_session_engine.py](backend/app/services/skyeye_session_engine.py), [notification_observer.py](backend/app/services/notification_observer.py)

## Phase 7: Sovereign Command (Tests 96-108)

Admin dashboard — the surface where the new Assign Coach tab will live.

- Tests 96-100: Tab loading, user management, coach approval, family management, revenue dashboard
- Tests 101-108: Crisis watchlist, The Eye, PMB, Token Lab, GKM, Hive Defense, Trust Enforcer, discounts

**Key files**: [command.html](dashboard/command.html), [family_merge.html](dashboard/family_merge.html), [admin.py](backend/app/routers/admin.py)

## Phase 8: Security (Tests 109-122)

Nothing leaks, nothing breaks.

- Tests 109-115: YubiKey registration/auth, Sentinel freeze, TOTP, SMS, challenge expiry, passphrase
- Tests 116-122: PII detection, detonation chamber, rate limiting, token revocation, portal isolation, data deletion, secure search

**Key files**: [admin.py](backend/app/routers/admin.py) (WebAuthn endpoints), [sentinel.py](backend/app/websocket/sentinel.py), [detonation_chamber.py](backend/app/services/security/detonation_chamber.py)

## Phase 9: Infrastructure (Tests 123-136)

The machine under the hood.

- Tests 123-126: 90/90 services, 441/441 trust, 5/5 pre-flight, bridge PG connectivity
- Tests 127-131: Redis, containers, Nginx TLS, WebSocket upgrade, no-cache headers
- Tests 132-136: Agent digest email, Trust Enforcer email, load_dotenv safety, backups, sandbox VPS

**Key files**: [main.py](backend/app/main.py), [trust_enforcer.py](backend/app/services/trust_enforcer.py), docker-compose configs

## Phase 10: Liminal Presence (Tests 137-141)

Nate's voice integrity.

- Tests 137-141: Silence Sentinel, Language Drift Monitor, Field Response Parser, voice correction loop, hallucination prevention

**Key files**: [skyeye_chat.py](backend/app/services/skyeye_chat.py), [liminal_presence_auditor.py](backend/app/services/liminal_presence_auditor.py)

## Phase 11: Edge Cases (Tests 142-150)

The stuff that breaks at scale.

- Tests 142-150: Simultaneous logins, mid-session disconnect, concurrent sanctuary, token race condition, large upload, slow network, expired OAuth, pool exhaustion, midnight reset

## Phase 12: App Store Compliance (Tests 151-158)

The gates you must pass.

- Tests 151-158: Privacy policy, terms, data deletion page, production config, app icons, no hardcoded creds, Apple IAP, Google Play billing

**Key files**: [app_config.dart](mobile/lib/config/app_config.dart), compliance pages in [dashboard/](dashboard/)

## Fix Protocol

When a test FAILS:

1. Document the failure with evidence (status code, error message, expected vs actual)
2. Fix the root cause in the relevant file
3. Deploy the fix
4. Re-run the specific test to confirm PASS
5. Continue to next test

When all 158 tests PASS, proceed to the Assign Coach Admin Tab build (migration renumbered to 083).