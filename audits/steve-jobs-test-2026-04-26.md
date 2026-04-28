# Steve Jobs Test — Client & Coach Portal Release-Gate Audit

**Date:** 2026-04-26 (report generated)  
**Scope:** Client portal + Coach portal (E2E system audit per request)  
**Accounts (reference only; no credentials stored in repo):** `client1` (CLIENT), `CoachN` (COACH)  
**Rules:** No code changes during audit; no password changes; no subscription cancellation; no account deletion; separation of audit vs remediation.

---

## 1. Executive Summary

| Severity | Count | Notes |
|----------|-------|--------|
| **P0** | 0 *verified in this run* | Full P0 surface not exhaustively tested (browser E2E not executed here). |
| **P1** | 1 *process* | **Human E2E + Stripe + three-browser + device testing not completed** — release gate cannot pass on automation-only evidence. |
| **P2** | *TBD by human QA* | Polish items require DevTools, responsive breakpoints, and copy review in production UI. |

**Ship readiness assessment:** **NOT READY** (for a strict Steve Jobs / release-gate sign-off).

**Reason:** This deliverable combines **server-side verification** and **schema/API probes** only. Phases 1–3 (full client/coach UI), Phase 5 (browser route isolation, token abuse), Phase 6 (p50/p95 API timing, concurrent peaks), and most Stripe / video / multi-session integration steps **require manual execution** in Chrome, Safari, Firefox, and on a real device or emulator. Those steps were **not run** in this environment per engagement rules (no code changes; audit not remediation).

**Top 5 blockers to reach READY**

1. Complete **Phase 1–2** manual pass with `client1` / `CoachN` in **three browsers** + **mobile device** (not DevTools-only).  
2. Complete **Phase 3** inter-portal tests in **two isolated sessions** (incognito + separate browser), then **revert test data** per checklist.  
3. Run **Stripe test flows** (4242 / 4000…0002) in **test mode** as specified; confirm webhooks and DB rows; **do not** cancel production subscription.  
4. **Deploy Flutter web** if client settings fixes (B1/B3 from prior work) are not yet on `coach.*` / `app.*` — until then, web settings UX is unaudited as “shipped.”  
5. Capture **screenshots** under `/opt/clinical-sovereignty-lab/audits/screenshots/2026-04-26/` for every FAIL/PARTIAL.

---

## 2. P0 Defects (data loss, security, billing broken)

| ID | Finding | Status |
|----|---------|--------|
| P0-A | None confirmed in automated checks | **N/A — manual E2E pending** |

---

## 3. P1 Defects (broken flow, no recovery, Jobs-level polish)

| ID | Finding | Evidence / Repro |
|----|---------|------------------|
| P1-PROC | Release-gate audit incomplete without human browser + Stripe + device runs | This report; no screenshots from live UI pass. |
| P1-DEPLOY | Prior work: `settings_screen.dart` B1/B3 fixes may not be live until `flutter build web` + rsync to `/var/www/sovereignsanctuary-web/` | Compare `version.json` / build stamp on coach/app after deploy. |

---

## 4. P2 Defects

Deferred to human QA (empty states, modal Esc, copy, 375/768/1920 layouts, dark mode).

---

## 5. Phase-by-Phase Results

**Legend:** PASS / FAIL / PARTIAL / **NOT RUN** (not executed in this audit)

### Phase 1 — Client Portal (client1)

| Area | Result | Notes |
|------|--------|--------|
| A Authentication | **NOT RUN** | Login, wrong password, forgot password, logout, refresh, timeout require browser. |
| B Onboarding & assessments | **NOT RUN** | Requires UI. |
| C Thera-world / SSE | **NOT RUN** | |
| D Little Nate chat | **NOT RUN** | |
| E Billing / subscription | **NOT RUN** | Stripe test cards require controlled browser session; do not cancel subscription. |
| F Coaching access | **NOT RUN** | |
| G Family Sanctuary | **PARTIAL** | DB: `client1` has `coach_id` = `COACH_COACHN_ID`, `assigned_coach` = CoachN — assignment OK. Family features not exercised. |
| H Settings | **NOT RUN** | Prior static review noted export/WS issues; retest after Flutter web deploy. |
| I UI/UX polish | **NOT RUN** | |

### Phase 2 — Coach Portal (CoachN)

| Area | Result | Notes |
|------|--------|--------|
| A–L (all tabs / settings) | **NOT RUN** | Requires logged-in coach session and tab-by-tab pass. |

### Phase 3 — Inter-portal integration

| Test | Result | Notes |
|------|--------|--------|
| A–J | **NOT RUN** | Two concurrent browser contexts + revert checklist not executed. |

### Phase 4 — Backend & data integrity

| Test | Result | Notes |
|------|--------|--------|
| 4A Crystals 24h | **PASS (empty window)** | Query returned **0 rows** for `user_id` in (client1, CoachN UUIDs), last 24h. No activity in window — not proof of broken generation. |
| 4B Nevedal metrics | **PASS (zero count)** | `COUNT(*) = 0` for client1 last 24h — consistent with no traffic in window. |
| 4C Stripe webhooks | **PARTIAL** | Table `webhook_audit_log` **does not exist**. Used `webhook_events_v2`: 3 rows in 24h (`checkout.session.completed` success, `customer.subscription.updated` all_cords_passed, `invoice.paid` success). |
| 4D PII encryption (`name_enc`) | **FAIL (query invalid for current schema)** | `users` has `name` / `email` columns; **no `name_enc`** in `\d users`. Audit step must be rewritten against actual encryption design (e.g. profile JSON, vault tables) before sign-off. |
| 4E Three-node dispatch | **NOT RUN** | No new classroom session during audit. |
| 4F Plaintext in logs | **PASS (sample)** | `docker logs nate_backend --since 24h \| grep -iE "(email\|ssn\|password)"` returned **empty** (no matches in sample). |

### Phase 5 — Security & privacy

| Test | Result | Notes |
|------|--------|--------|
| 5D API without token | **PARTIAL** | `GET /api/client/health-check` → **403**; `GET /api/sessions/coach/FAKE` → **403** (rejects unauthenticated; not 401 — document for client apps). |
| 5A–C, E–I | **NOT RUN** | Requires tokens, two accounts, crafted URLs. |

### Phase 6 — Performance

| Test | Result | Notes |
|------|--------|--------|
| Snapshot | **PARTIAL** | `docker stats nate_backend` (one sample): ~**648 MiB / 6 GiB**, CPU ~0.65%. Not a load test. |
| p50/p95 API | **NOT RUN** | Needs APM or `curl` timing series under load. |

---

## 6. Performance Baseline Numbers

| Metric | Value | Method |
|--------|-------|--------|
| `nate_backend` memory | ~648 MiB / 6 GiB limit | `docker stats --no-stream` (single snapshot, idle period) |
| `nate_backend` CPU | ~0.65% | same |
| Coach TLS (origin probe) | HTTP 200 | `curl` to host nginx with `Host: coach.sovereignsanctuary.net` |
| API health | HTTP 200 | `/health` via `api.sovereignsanctuary.net` |

**Not captured:** page load seconds, API p50/p95, PG latency, concurrent connection peaks, bridge CPU during chat.

---

## 7. Backend Data Integrity Findings

- **Accounts:** `client1` = CLIENT, ACTIVE; `CoachN` = COACH, ACTIVE (PostgreSQL).  
- **Coach assignment:** `client1` → `COACH_COACHN_ID` / `CoachN` in `profile_data` — **consistent** with coach-client rules.  
- **Crystals (24h):** no rows for those two user UUIDs — expected if no chat/crystallization in window.  
- **Webhooks:** use **`webhook_events_v2`**, not `webhook_audit_log`. Recent events show successful processing types in last 24h (low volume).  

---

## 8. Security & Privacy Findings

- Unauthenticated API probes return **403** (not 401) — acceptable for “blocked” semantics; ensure mobile/web clients handle both 401/403 per existing patterns.  
- Log grep sample: **no** obvious email/SSN/password pattern hits in 24h backend log (limited grep; not a guarantee of full log hygiene).  
- **Schema note:** PII-at-rest check against `name_enc` **not applicable** to current `users` table — align audit with migrations / encryption docs before claiming PASS.

---

## 9. Recommended Pre-Launch Fixes (P0 + P1)

1. **Execute full manual** Phases 1–3, 5–6 per original script; attach screenshots.  
2. **Fix audit script** for Phase 4D to match real encryption columns/tables.  
3. **Ship Flutter web** for settings if B1/B3 are still not in production bundle.  
4. **Document** 403 vs 401 for unauthenticated API in coach/client QA checklist.  
5. Re-run this report with **PASS/FAIL** per line after human run.  

---

## 10. Recommended Post-Launch Fixes (P2)

- Empty states, microcopy, modal focus trap, Esc, responsive breakpoints.  
- Performance baselines under **25+ concurrent** users (load-test methodology in `.cursor/rules/load-test-performance-baseline.mdc`).  

---

## Appendix A — SQL executed (production)

```sql
-- Users
SELECT username, role, subscription_status FROM users
WHERE username IN ('client1','CoachN');

-- Coach assignment
SELECT profile_data->>'coach_id', profile_data->>'assigned_coach' FROM users WHERE username='client1';

-- Crystals 24h (client1 + CoachN UUIDs)
SELECT COALESCE(origin_surface::text,'null'), domain, COUNT(*)
FROM nate_intelligence_crystals
WHERE created_at >= NOW() - INTERVAL '24 hours'
  AND user_id IN (
    (SELECT id FROM users WHERE username='client1'),
    (SELECT id FROM users WHERE username='CoachN')
  )
GROUP BY 1,2;

-- Nevedal metrics 24h (client1)
SELECT COUNT(*) FROM nevedal_metrics
WHERE user_id = (SELECT id FROM users WHERE username='client1')
  AND created_at >= NOW() - INTERVAL '24 hours';

-- Webhooks (table: webhook_events_v2)
SELECT event_type, processing_result, COUNT(*)
FROM webhook_events_v2
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY 1,2;
```

---

## Appendix B — Screenshot location

Server path (placeholder):  
`/opt/clinical-sovereignty-lab/audits/screenshots/2026-04-26/README.txt`

**Screenshots were not generated in this automated run.**

---

*End of report — await human review before remediation.*
