# GEO Build Plan — Coach Discoverability & AI Search

**Status:** code landed locally (uncommitted) — flags OFF — not deployed — GREEN migration 336 not applied  

**Initiative:** GEO (separate from v1.5 single push)  
**Sources:** 7/7 read + saved in [`.cursor/plans/geo-sources/`](geo-sources/SOURCE_MANIFEST.md)  
**Law:** MASTER v4.0 §17.0 no-partial-build · spec v1.5 P1–P7 / B1–B5 / G1–G5 / NG1–NG12 · kickoff ground rules

---

## 0. Source inventory (binding check-off)

| # | Saved path | Read | Saved | Used as |
|---|---|---|---|---|
| 1 | `geo-sources/disco_workers_61_64.py` | [x] | [x] | Port #61–#64 into `backend/app/services/disco/` |
| 2 | `geo-sources/test_workers_61_64.py` | [x] | [x] | Port 35 checks → `backend/tests/test_disco_workers_61_64.py` |
| 3 | `geo-sources/test_disco_pipeline.py` | [x] | [x] | Port 27 checks → `backend/tests/test_disco_pipeline.py` |
| 4 | `geo-sources/disco_pipeline.py` | [x] | [x] | Port §18 gaps 1–9 + register linter |
| 5 | `geo-sources/sovereign-sanctuary-discoverability-MASTER.md` | [x] | [x] | GEO law, tiers, workers #1–#64, DAC1–DAC49 |
| 6 | `geo-sources/plan-agent-kickoff-prompt.md` | [x] | [x] | Plan format: audits → frozen iface → tickets → order → gate → Qs |
| 7 | `geo-sources/sovereign-sanctuary-workspace-voice-unified-spec.md` | [x] | [x] | Consumed contracts only — GEO does **not** join the v1.5 push |

Re-sync from Downloads if hashes in `SOURCE_MANIFEST.md` drift.

---

## 1. Binding law (verbatim — do not merge or “improve”)

### 1.1 GEO boundary (MASTER §5 + `BuildBoundary`)

- GEO **never** joins the v1.5 single push or its Queens GREEN gate.
- GEO **never** reads v1.5 tables directly. It consumes four read-only contracts. Missing contract → degrade, never crash.
- No client data / session-derived content on any public surface.
- No schema spam, fake reviews, keyword stuffing, or AI bulk pages detached from real coaches.
- Credential-register terms on a coaching-class public surface = **build-blocking**.
- Tragedy-driven demand = supportive-resource or silence — never opportunistic SEO.
- Partial tier = FLAG OFF. No Tier N starts until Tier N−1 is 100% + verified.

### 1.2 Four contracts GEO may consume (frozen)

```
credentials     → relationship_class, credential_type, jurisdiction, identifier, verified_at, expires_at
engagements     → campaign_engagements rows (channel includes ai_search when T3.3 ships)
content_topics  → coach-flagged topics for hub/article scheduling
authoring       → approved marketing_content (linkedin_post / newsletter_issue / blog) as capture surfaces
```

Undeclared table access raises. See `BuildBoundary.CONTRACTS` in `disco_pipeline.py`.

### 1.3 v1.5 principles GEO must not violate when it touches those contracts

- **P1** Intelligence stays server-side. Directory/schema/llms.txt are delivery; LN generates.
- **P2** SendGrid at volume; Gmail 1:1 only. Recruitment outreach (#64) uses **prospect rails (SendGrid)**, never client rails.
- **P3** One Google credentials interface. GEO GBP/listings do not mint a second OAuth store.
- **P4** Vault consent granular. Public directory is opt-in coach surface; vault_sync never leaks clients.
- **P5** Coach approval gates outbound. Article **publication** never auto-approves (MASTER §19.2 Correction 2).
- **P6** No LinkedIn auto-comment/reply.
- **P7** Queens govern trust. Register linter + claim-truth + crisis screen log RED.

**B1–B5** (booking) stay on the existing LN state machine. GEO booking CTA enters that flow; GEO never creates Google events.

**G1–G5** (supervision) are v1.5-internal. GEO public surfaces never render supervised-client identity.

### 1.4 Human-owned (plan around; never guess)

| ID | Owner | What |
|---|---|---|
| O6 / D2 / C#24 | counsel | Clinical advertising + testimonial matrix; erasure UI values |
| O7 | counsel | Retention / crypto-shred / EU residency |
| O8 | Admin | Exact launch-coach roster for T1 GBP/listing drive |
| O9 | Admin / Google | Workspace OAuth verification (CASA) — **blocks ENABLE_WS_OAUTH**, not GEO T1 start |
| O2 | LN7 | Gmail sent/discarded fidelity (v1.5) |
| O5 | LN7 | Studio webhook secret UX (v1.5) |
| D4 | Queens | Crawler carve-out for allowed AI bots on `/coaches/*` only |

**Resolved (do not reopen):** O1 = `gmail.readonly`. D1 = subdirectory `/coaches/{slug}` on brand domain. D3 consent text drafted. T0.1–T0.6 decisions closed. Claim #3 mechanism = **sampling + distributed substance**, not batching.

---

## 2. Phase 1 audits (kickoff — before any GEO ticket starts)

### 2.A Schema reconciliation (O3) — live vs spec

Spec v1.5 names are **intent**. Live names (migration 328 + later) win.

| Spec name | Live name | Notes |
|---|---|---|
| `coaches(id)` UUID | `users.username` + `users.hardware_id` | No `coaches` table. View `workspace_identity` exists. |
| `google_credentials` | `google_workspace_connection` (+ sibling `google_calendar_connection` 183) | TokenCipher, not BYTEA KMS box. |
| `clients.vault_sync` | `users.vault_sync` | Plus `app_enabled`, `relationship_class`, `client_jurisdiction`. |
| `calendar_links` | **not found as named** | Session↔Google mapping lives in calendar sync services; confirm before GEO cites it. |
| `calendar_watch_channels` | exists (328) | `coach_id VARCHAR` PK. Unused this push (History poll). |
| `email_drafts` | exists (328) | Status set differs (`pending`/`blocked` vs spec `generated`/`blocked_vault`). |
| `marketing_campaigns` | `coach_marketing_campaigns` | Plus SkyEye campaign tables. |
| `marketing_content` | exists (296 + 328 widen) | Types include `directory_page`, `linkedin_post`, `newsletter_issue`. |
| `campaign_engagements` | exists (328) | **Narrower than spec** — missing channel/source CHECKs, prospect_email, payload JSONB. GEO `ai_search` needs an additive widen. |
| `post_nudges` | exists (328) | Column names differ (`scheduled_at`/`sent_at` vs `fire_at`/`delivered_at`). |
| `canonical_identity` | **absent** | GEO T1.1 creates. |
| `vocabulary_taxonomy` | **absent** | GEO T1.1 creates. |
| `discovery_pages` | **absent** | GEO T1.1 creates. |
| `visibility_probes` | **absent** | GEO T3. |
| `recruiting_targets` / `trending_topics` | **absent** | GEO T3/T4. |

**GEO migration set (one additive file, after T1.1 freeze):** `backend/migrations/NNN_disco_spine.sql` — only the GEO spine + `campaign_engagements` channel widen for `ai_search`. Do not recreate 328 tables.

### 2.B Bridge integration

- `bridge_handlers_v2.CoachNexusV2` **is imported** in `bridge_server.py`.
- `coach_nate_query` **is in the message loop** (~22484).
- GEO does not change the loop. LN Widget (T5.3) is a **new public HTTP/WS surface**, blocked until DAC35 crisis screen.

### 2.C Surface inventory (exists vs spec assumes)

| Surface | Live | GEO implication |
|---|---|---|
| FastAPI `main.py` | yes | New `/api/v1/public/` + disco routers; keep app hosts blocked from crawlers |
| Cloudflare Workers | 8-worker fleet | Crawler allow-list + cache for `/coaches/*` only; do not merge workers |
| R2 | `nate-vault` + others | Public OG/images later (§18.10 media gap) |
| Redis | auth + cache | Probe budget / worker heartbeats |
| SendGrid | yes | #64 prospect outreach only |
| LinkedIn publisher | dual-app | Capture surfaces (T5.5) consume approved posts; no auto-comment |
| `ENABLE_WS_OAUTH` | **off** | Coach connect blocked until O9. GEO T1 can start without it. |
| Calendar pull | 183 + Workspace merge (335) | Busy cache exists; GEO does not own it |
| Brand site | Squarespace (T0.5) | T1 includes migrate-off-Squarespace + 301 map |

---

## 3. Frozen interface (Workstream A for GEO)

Port from `disco_pipeline.py` / `disco_workers_61_64.py` — signatures freeze before workers #1–#64 are wired to PG.

```
disco.boundary.get(contract, default) -> {degraded, value|reason}
disco.boundary.readiness() -> {credentials, engagements, content_topics, authoring}

disco.render.affected(changed_sources) -> [page]
disco.render.rebuild(changed_sources) -> {changed_sources, rebuilt_pages, skipped_pages}

disco.cost.charge(worker, usd) -> bool   # freeze at budget
disco.locale.hreflang_block(slug, available) -> [{rel,hreflang,href}]
disco.runtime.run(worker, fn, *args) -> {ok, attempts, dead_lettered?}
disco.horizons.consolidate(daily_series) -> rows  # insufficient_history if no prior window
disco.horizons.divergence_action(rows) -> str
disco.canary.evaluate(control_rate, variant_rate, samples) -> HOLD|ROLLBACK|PROMOTE|CONTINUE
disco.lint.register_lint(text, relationship_class) -> {blocked, violations, action}

#61 VerificationOrchestrator.process(claim) -> AUTO_ATTESTED | HUMAN_CONFIRM
#62 InlineValueRenderer.render_page(article_html, unit, region) -> HTML  # no <script>
#63 CACLedger.period(...) + ClaimTruthRegister.check(copy)
#64 RecruitmentEngine.source/outreach/handle_reply  # EU gated; SendGrid prospect rail
```

CI gate: ported tests must print **27/27** and **35/35** before any public page flag turns ON.

---

## 4. Tickets (numbered)

### Track M — Migration + proof port (starts first)

| ID | Scope | Deps | Satisfies | Kill flag |
|---|---|---|---|---|
| **M1** | Copy pipeline + workers into `backend/app/services/disco/` (stdlib, adapters stubbed). Port both harnesses to pytest. | — | §18.11, §22 | `DISCO_BUILD` |
| **M2** | Additive `NNN_disco_spine.sql`: `canonical_identity`, `vocabulary_taxonomy`, `discovery_pages`, `visibility_probes`, `recruiting_targets`, `trending_topics` + widen `campaign_engagements` for `channel='ai_search'`. | 2.A names | T1.1 | — |
| **M3** | Seed T1.2 taxonomy (10 concepts, EN query language). DE/FR rows stay draft until native phrasing (C6). | M2 | T1.2 | `DISCO_LINT` |
| **M4** | `BuildBoundary` adapter: map live `users.relationship_class` + credential columns → `credentials` contract; degrade if missing. | M2, 328 | §18.2 | — |

### Track T1 — Foundation (no public page until 100%)

| ID | Scope | Deps | Satisfies | Flag |
|---|---|---|---|---|
| **T1.3** | `#1 disco_canonical_renderer` — one record → page + JSON-LD + sameAs + llms.txt + bylines | M2, M1 | DAC1 | `DISCO_RENDER` |
| **T1.4** | `#14 disco_build_deploy` SSR/SSG + raw-HTML crawlability gate | T1.3 | DAC6 | `DISCO_BUILD` |
| **T1.5** | `#32 disco_schema_validator` blocking in CI | T1.3 | DAC6 | `DISCO_SCHEMA` |
| **T1.6** | `#15 disco_register_linter` pre-publish (use pipeline `register_lint`) | M1 | DAC3 | `DISCO_LINT` |
| **T1.7** | `#16 disco_area_deriver` licensure → areaServed | M4 | §2.2 | `DISCO_AREA` |
| **T1.8** | `#4 disco_credential_propagator` same-day lapse | M4 | DAC3 | `DISCO_CREDSTATE` |
| **T1.9** | `#5 disco_lifecycle` pause/depart 301 + unstitch | T1.3 | DAC4 | `DISCO_LIFECYCLE` |
| **T1.10** | Deploy authored robots.txt (brand + **separate app-host**) + llms.txt; verify CF not blocking OAI-SearchBot / GPTBot / PerplexityBot / ClaudeBot / Google-Extended | T1.4 | T1.10, C1–C3 | Queens D4 |
| **T1.11** | Organization + Person(founder) + Service/SoftwareApplication on brand pages | T1.4 | §11 | `DISCO_RENDER` |
| **T1.12** | GSC + Bing verified; sitemaps submitted | T1.4 | T1.12 | — |
| **T1.13** | Onboarding authorization: listing-agent + GBP manager consent (D3 text) | — | §19.1 | — |
| **T1.14** | `#35 disco_gbp_manager` claim drive for every launch coach | T1.13, O8 | DAC9/10, DAC31 | `DISCO_GBP` |
| **T1.15** | `#34` + `#38` listing orchestrator + tracker | T1.13, O8 | DAC9, DAC31 | `DISCO_LISTINGS` / `DISCO_LISTTRACK` |
| **T1.16** | `#49-adjacent disco_authority_builder` outreach packets + placement tracking | T1.3 | §19.1a | `DISCO_AUTHORITY` |
| **T1.MIG** | Squarespace → own SSR/SSG, 1:1 301s, cart retirement, T0.2 copy live **before** DNS cutover | T1.4, T1.11 | T0.5 | `DISCO_BUILD` |

**T1 gate:** identical render across surfaces; zero drift; raw-HTML pass; app unindexed; listing + GBP status recorded for every launch coach (DAC31).

### Track T2 — Coverage (after T1 gate)

| ID | Scope | Deps | Satisfies | Flag |
|---|---|---|---|---|
| **T2.1** | `#2 disco_onboarding_pipeline` same-day legibility | T1 gate | DAC2 | `DISCO_ONBOARD` |
| **T2.5** | `#3 disco_hub_generator` supply-gated only | T1.3 | DAC7 | `DISCO_HUBS` |
| **T2.6** | `#6 disco_drift_auditor` | T1.3 | §2.0 | `DISCO_DRIFT` |
| **T2.7** | `#37 disco_credential_prechecker` | M4 | DAC10 | `DISCO_CREDCHECK` |
| **T2.8** | Publish T2.8 pricing copy + Offer schema (four tiers only; `$5/day for you and your partner`) | T1.11 | C4 | `DISCO_LINT` |
| **T2.9** | Publish T2.9 brand-defense copy (no “primary-source” / “background checked”) | T1.11 | C5 | `DISCO_LINT` |
| **T2.10** | EU consent banner + consent mode + form notices | T1.MIG | §9.5 | — |

### Track T3 — Measurement (before any adaptive flag)

| ID | Scope | Deps | Satisfies | Flag |
|---|---|---|---|---|
| **T3.1** | Load T3.1 8-class probe set; wire `ProbeScheduler` (API / GROUNDED / MANUAL) | M1 | §18.1 | `DISCO_PANEL` |
| **T3.2** | Claims log + `#36 disco_correction_dispatcher` | T3.1 | §9.6 | `DISCO_CORRECT` |
| **T3.3** | `#10 disco_referrer_attribution` → `campaign_engagements.channel='ai_search'` | M2 | T3.3 | `DISCO_ATTRIB` |
| **T3.4** | `#31 disco_funnel_instrumentation` citation→click→signup→subscriber | T3.3 | DAC36 | `DISCO_FUNNEL` |
| **T3.5** | `#33` + `#29` index watch + decay | T1.12 | — | `DISCO_INDEXWATCH` / `DISCO_DECAY` |
| **T3.6** | `#30 disco_competitor_watch` + authority metrics (§19.1b) | T3.1 | DAC5 | `DISCO_COMPWATCH` |
| **T3.7** | `consolidate_horizons` + `divergence_action` daily 7/30/90/180/365 | M1 | DAC21 | — |
| **T3.8** | Backfill miner + seasonal memory | T3.7 | DAC26 | — |

**T3 gate:** every adaptive metric populated. **No T4 flag ON until this passes.**

### Track T4 — Autonomy (all-or-nothing)

Port remaining workers #40–#60 from MASTER §13–§20. Seed #61–#64 from saved Python.

| ID | Worker | DAC | Flag |
|---|---|---|---|
| **T4.1** | `#41 disco_performance_rotator` | DAC20 | `DISCO_ROTATION` |
| **T4.2** | `#42 disco_citation_learner` | DAC14 | — |
| **T4.3** | `#43` + `#40` content loop/scheduler — **publish requires human** | DAC16 | `DISCO_SCHEDULE` |
| **T4.12** | `#49 disco_originality_gate` BLOCKING | DAC32 | — |
| **T4.13** | `#50 disco_volume_governor` | DAC34 | — |
| **T4.14** | `#51 disco_thin_content_auditor` | — | — |
| **T4.15** | `#52–#54` lever 1 entity proof | DAC37/38 | — |
| **T4.16** | `#55–#57` lever 2 information gain (gain scorer BLOCKING) | DAC39/40 | — |
| **T4.17** | `#58–#60` lever 3 un-gated value (`ask_governor` BLOCKING) | DAC41 | — |
| **T4.18** | Lever crystallization + conflict precedence | DAC42/43 | — |
| **T4.19** | `#61 VerificationOrchestrator` (saved file) | DAC44 | — |
| **T4.20** | `#63 CACLedger` + ClaimTruthRegister (saved file) | DAC47/48 | — |
| **T4.21** | `#64 RecruitmentEngine` (saved file; EU gated) | DAC49 | — |
| **T4.4–T4.10** | `#44–#48`, `#11`, `#39` as MASTER §17.5 | DAC7/15/17/22/24/28/30 | per §13 |
| **T4.11** | Load authored autonomy config (A3 = schedule only, never publish) | DAC18 | Queens |

### Track T5 — Integration (after T4 gate + crisis)

| ID | Scope | Blocker | DAC |
|---|---|---|---|
| **T5.1** | `#13 disco_agent_api` + MCP listing | T1.10 C3 comments | — |
| **T5.2** | Public credential-verification endpoint | T4.19 | — |
| **T5.7** | Widget crisis screening + conversion suspend on distress | — | DAC35/36 |
| **T5.9** | `#62 InlineValueRenderer` in initial HTML (saved file) | — | DAC45/46 |
| **T5.3** | LN Widget on directory/product | **T5.7 must pass first** | — |
| **T5.8** | Per-step funnel attribution | T3.4 | DAC36 |
| **T5.4** | Campaign↔discovery bidirectional bridge | authoring contract live | DAC27 |
| **T5.5** | Campaign assets as indexed capture surfaces | P5 approval | DAC29 |
| **T5.6** | `#12 disco_review_dispatcher` coaching-class, jurisdiction-gated | O6 if clinical | — |

### Track V — v1.5 remainder (NOT GEO; listed so GEO does not wait on the wrong things)

These stay on the Workspace/Voice plan. GEO degrades until contracts appear.

- [ ] V-OAuth: `ENABLE_WS_OAUTH` after O9/CASA
- [ ] V-Gmail/Drive/campaign flags
- [ ] V-O6/O7 counsel gates for erasure UI
- [ ] V-E2E booking: one-email approve, leftover Approve, Workspace calendar without retry
- [ ] V-Widen `campaign_engagements` to spec channels if Voice needs them (coordinate with M2)

---

## 5. Integration order (O10) — earliest-risk-first, inside GEO only

1. **M1 proof port** — if 27/27 or 35/35 fail, stop. Risk: silent rewrite of #63 batching (forbidden).
2. **M2 spine + M4 boundary** — risk: GEO queries `google_credentials` / `coaches.id` (false names). Surfaces here.
3. **T1.6 linter + T1.5 schema CI** — risk: treatment-register leak on coaching pages.
4. **T1.13–T1.15 listings/GBP in parallel with T1.3–T1.4 directory** — risk: repeating §19.1 mistake (listings after directory).
5. **T1.10 crawler allow + app-host block** — risk: CF default-blocks AI bots **or** indexes Coach Command.
6. **T1.MIG Squarespace cutover** — risk: 404s / lost GSC. Last T1 step before gate.
7. **T2 then T3** — risk: turning T4 on against empty horizons (`insufficient_history` must not read as `stable`).
8. **T4.3/T4.12/T4.13 before content loop volume** — risk: programmatic-content penalty.
9. **T4.19 then T5.2** — risk: public “verified” badge without attestation signature.
10. **T5.7 + T5.9 before T5.3 widget** — risk: crisis funnel (§19.3).

### Top 5 integration risks

| # | Risk | Where it surfaces |
|---|---|---|
| 1 | Name-map collision (spec UUID coaches vs live username) | M2 / M4 |
| 2 | Authority cold-start if listings slip after directory | T1.13–15 vs T1.3 |
| 3 | Horizon “stable” on short history | T3.7 (already fixed in pipeline — do not regress) |
| 4 | Auto-publish via A3 timeout | T4.3 / T4.11 |
| 5 | Widget without crisis HTML | T5.3 before T5.7/T5.9 |

---

## 6. Gate plan

### 6.1 GEO 100% (MASTER §17.7)

Every T0–T5 box checked; DAC1–DAC49 pass; flags OFF only as kill switches; zero drift; raw-HTML + valid schema on every public page type; one unattended adaptation cycle; four gated classes block/escalate (DAC18).

### 6.2 Proof harnesses (must stay green)

- [x] `test_disco_pipeline.py` — 27/27 (`backend/tests/test_disco_pipeline.py`)
- [x] `test_workers_61_64.py` — 35/35 (`backend/tests/test_disco_workers_61_64.py`)
- [x] CI: both under `backend/tests/` (not in `--ignore`; `run_ci_tests.sh` collects them)

### 6.3 v1.5 AC1–AC33

**Not this gate.** Track V owns them. GEO only requires the four contracts to be non-degraded when T5.4/T5.5 turn on.

### 6.4 Drills GEO must own (map)

| Drill | Ticket | Note |
|---|---|---|
| Credential lapse same-day | T1.8 | DAC3 |
| Depart 301 / no 404 | T1.9 | DAC4 |
| Register lint RED | T1.6 | DAC3 |
| Crisis HTML without JS | T5.9 | DAC45/46 |
| EU outreach blocked | T4.21 | #64 test |
| Claim-truth G2 | T4.20 | #63 |
| Canary rollback | T4.5 | pipeline `CanaryPromoter` |
| Budget freeze | M1 `CostLedger` | §18.4 |

---

## 7. Questions (flagged — do not guess)

**Admin**

1. Launch-coach roster for T1.14/T1.15 (O8)?
2. Approve this plan so M1/M2 may start?
3. Brand DNS cutover window for T1.MIG?

**Counsel**

4. Send T0.3/T0.4 briefs (O6/O7) — clinical-class surfaces stay gated until reply.
5. WCAG bar for public health-adjacent pages (§18.10)?

**LN7**

6. Confirm `calendar_links` live equivalent before any GEO ticket cites it.
7. `campaign_engagements` widen: one migration shared with Voice, or GEO-only `ai_search` column?

**Queens**

8. D4: allow-list AI crawlers on `/coaches/*` + `/llms.txt` only; keep app/coach/command blocked.
9. Daily disco compute budget USD for `CostLedger` (pipeline demo used $25)?

---

## 8. Still open content gaps (§18.10 — flagged, not tickets)

- Media pipeline (photos, OG, rights)
- WCAG unspecified
- Analytics vendor (GA4 vs privacy-first / server-side)
- Named owner + spend for counsel / listings / residual human tasks

---

## 9. Dependency graph (text)

```
M1 → M2 → M3
 M1 → M4
M2+M4 → T1.3 → T1.4/T1.5/T1.11
M1 → T1.6
M4 → T1.7/T1.8
T1.3 → T1.9
T1.4 → T1.10/T1.12/T1.MIG
T1.13 → T1.14/T1.15   (parallel with T1.3, not after)
T1 GATE → T2.* → T3.* → T3 GATE → T4.* → T4 GATE
T4.19 → T5.2
T5.7+T5.9 → T5.3
authoring contract → T5.4/T5.5
```

---

## 10. First execution slice (after Admin “yes”)

1. Land M1 (port 4 Python files + pytest).
2. Land M2 spine migration (additive).
3. Stop. Do not publish `/coaches/*` until T1 gate.

Admin approved 2026-08-16 (DrNevedal1). Implementation is local/uncommitted. Public `/coaches/*` stays unpublished until `DISCO_RENDER=true` after T1 gate + GREEN migrate.
