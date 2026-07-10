# Incident Memo — Crystal Recall Scope Failure Resulting in Cross-Client PHI Exposure

**Prepared for**: Legal review (one-hour read)
**Date of memo**: 2026-07-09
**Status**: Root cause fixed and deployed. Confirmed exposure quarantined. Systemic write-time guard and standing auditor are in progress (not yet deployed as of this memo).
**Prepared by**: Engineering (Cursor agent session), verified against production PostgreSQL (`little_nate` DB, host 68.183.168.75) via direct SQL query, not from application logs or memory.

---

## 1. What happened (plain language)

Little Nate's long-term memory system ("crystals") has a scope field that is supposed to control who can retrieve a given memory. Three scopes matter here:

- `global` — intended to be de-identified, safe-for-anyone knowledge (research findings, general clinical patterns, marketing copy).
- `admin_only` — intended to be visible **only** to administrators, never surfaced to any client or coach session.
- `user:<id>` — intended to be visible **only** to the specific client it belongs to.

The recall code that assembles a user's session context did **not** actually enforce this. Every query that pulled from the "global pool" (rows where `user_id IS NULL`) used a **blocklist** — it excluded only `scope = 'archived'` — instead of an **allowlist** that required `scope = 'global'`. As a result, `admin_only`-scoped crystals were retrievable by any logged-in user's normal chat session, exactly as if they were `global`.

Separately, a memory-synthesis process (`crystallize_wisdom_absorption`) had a fail-open bug: when it could not resolve which client a piece of conversation belonged to, it defaulted to writing the crystal with `user_id = NULL` (global-eligible) instead of failing the write or quarantining it. In at least two cases, this process concatenated **personalized, name-bearing "Session Insight" text from real client conversations** into crystals that were then global-pool-eligible under the broken scope check above.

The combination of these two defects allowed two specific pieces of one client's personally identifiable session content to be retrieved into two other clients' unrelated chat sessions.

This is the same class of defect first discovered in the public-trial funnel (`P0.1`, now closed) but it is broader: it affected the **main authenticated application**, not just the anonymous trial, and it had been live in production since at least **2026-03-23** (earliest recall-log timestamp under the affected code path) until the fix was deployed on **2026-07-09/07-10**.

---

## 2. Two distinct scopes of this incident — do not conflate them

It is important for legal review to separate two numbers that look similar but mean very different things:

### 2a. Systemic blast radius (the bug's total reach — mostly benign content)

Querying `crystal_recall_log` for every recall event where the source crystal had `scope = 'admin_only'` and `user_id IS NULL`, across the full lifetime of the bug:

- **58 total recall events**
- **9 distinct recalling accounts** (8 real client accounts + 1 internal audit/test account, `audit_client_hw`)
- **55 distinct crystals** recalled under this broken scope
- Date range: **2026-03-23 to 2026-07-10**

We individually inspected the full text of **all 55** of these crystals (not just a sample). **53 of the 55 contain no personal names and no session-specific narrative** — they are de-identified aggregate clinical/marketing/research synthesis (e.g., "Polyvagal-informed clinical assessment: In sessions with low coherence (avg C_emo=0.25)...", "Persistent notifications erode attention..."). Their `crystal_owner_uuid`-equivalent fields are null; there is nothing in them to attribute to a specific person. Retrieval of these 53 crystals by the wrong scope is a **process/control failure** (the scope enforcement did not work as designed), but it did **not** expose personal information to anyone.

### 2b. Actual confirmed PHI exposure (the material finding)

Only **2 of the 55** admin_only-recalled crystals contain identifiable, personalized content naming a specific real client. We ran an exhaustive query for `Session Insight` markers and known client-name mentions against the full text of all 55 crystals — these are the only two positive hits system-wide (see Section 4 for the query and full output).

Both of these two crystals were separately identified during our earlier name-search audit (a broader ILIKE scan across the whole global crystal pool, not limited to admin_only, which found 45 candidate crystals mentioning a real client's name; 33 of those 45 were confirmed true positives containing genuine PHI-bearing text). We then checked `crystal_recall_log` for **all 45** name-bearing candidates, system-wide, for the entire lifetime of the data (not just the admin_only subset) — **only 2 of those 45 crystals were ever recalled by any user, ever.** The other 43 sat in the database as global-pool-eligible but were never actually pulled into a live session by anyone.

**This means the confirmed, provable exposure is limited to exactly 2 recall events, both involving the same victim:**

| Crystal ID | Recalled by (account) | Real name of recalling account | Recall date | Content exposed |
|---|---|---|---|---|
| `181990` | `CLIENT_LETSGOLISA_ID` | **Lisa West** | 2026-07-05 | A personalized "Session Insight" excerpt addressed to and naming **"John D."** (a different, unrelated real client), containing Nate's personalized therapeutic language directed at John D. The same crystal also contains personalized content addressed to Lisa West herself (referencing "the Meredith conversation," her own history of "leadership burnout, judgmental group dynamics, and relational injuries"). Lisa West's own content is not a breach against her; the John D. content she received **is** a breach against John D. |
| `355292` | `CLIENT_LONGRA_ID` | **longra** (client account, real name not fully resolved in registry — username is "longra") | 2026-07-02 | A personalized "Session Insight" excerpt directly addressed to and naming **"John D."**: *"John D., I sense a bit of curiosity in your words..."* — no unrelated content of the recalling user's own is mixed in here; this crystal is entirely John D.'s personalized session exchange. |

**Bottom line for legal**: **One real client — "John D." (username `client1`, hardware ID `CLIENT_001`) — had personally identifiable, personalized session content exposed to two other real clients** ("Lisa West" and "longra") on two separate occasions, roughly 5 weeks ago (2026-07-02 and 2026-07-05). No other client's identifiable content is confirmed to have been retrieved by anyone besides the client it belonged to (self-recall, not a breach) or nobody at all.

We found no evidence of exposure in the reverse direction (John D. accessing anyone else's PHI) — his own recall history in the admin_only-scope dataset consists of 3 generic, de-identified crystals with no names.

---

## 3. Root cause (technical, for the record)

Two independent defects combined to produce this exposure:

1. **Missing scope enforcement (the primary defect).** Eleven SQL query sites across six backend files (`crystal_recall_bridge.py`, `bridge_server.py`, `twilio_grok_xtts_pipeline.py`, `sse_panel_chat_context.py`, `sensitive_clinical_bridge.py`, `voice_crystal_enricher.py`, plus a metrics query in `quantum_crystal_orchestrator.py`) queried the "global pool" (`user_id IS NULL`) using a blocklist (`scope NOT IN ('archived')` or similar), which allowed any non-archived scope — including `admin_only` and orphaned `user:*` scopes — to be treated as globally retrievable.

2. **Fail-open write path (the source of the two PHI-bearing crystals).** The memory-synthesis function `crystallize_wisdom_absorption` accepted an unresolved or empty `user_ref` and defaulted to writing a global-pool-eligible crystal (`user_id = NULL`) rather than rejecting the write or quarantining the content. This is how personalized, name-bearing session text ended up eligible for global/admin_only retrieval in the first place — it should never have been written outside a specific client's own scope.

---

## 4. Verification method (so this can be independently re-checked)

All figures above were produced by direct SQL query against the production database, not from application logs, not from memory, and not from prior conversation summaries. The two most important verification queries:

**Exhaustive scan of all 55 admin_only-recalled crystals for name/session-insight content:**
```sql
SELECT id,
       (crystal_text ILIKE '%Session Insight%') AS has_session_insight,
       (crystal_text ~* '(John D\.|Lisa West|Bill West|Paula Swain|Zack Swain|Jane D\.|Dr\. Nevedal|Lisa,|Eric Bando|Lana Smith|Kristy Moore|longra)') AS has_name_mention
FROM nate_intelligence_crystals
WHERE id IN (<55 ids>)
ORDER BY has_session_insight DESC, has_name_mention DESC, id;
```
Result: 2 of 57 rows returned `t`/`t` (181990, 355292); all others `f`/`f`.

**Recall history for all 45 name-bearing candidate crystals (system-wide, not scope-limited):**
```sql
SELECT crl.crystal_id, crl.user_id AS recalling_user_ref, u.username, u.profile_data->>'name' AS name,
       u.role, crl.source, crl.session_id, crl.recalled_at
FROM crystal_recall_log crl
LEFT JOIN users u ON (u.hardware_id = crl.user_id OR u.username = crl.user_id OR u.id::text = crl.user_id)
WHERE crl.crystal_id IN (<45 ids>)
ORDER BY crl.recalled_at;
```
Result: exactly 2 rows (crystal 181990 → Lisa West, crystal 355292 → longra).

Both source crystals (181990, 355292) are confirmed currently quarantined: `scope = 'archived'`, `user_id IS NULL`, as of 2026-07-05 and 2026-07-02 respectively (archival timestamps captured in `updated_at`).

---

## 5. Remediation completed to date

1. **18 crystals** confirmed to contain real client names in a global-eligible scope were archived (quarantined; no longer retrievable by anyone, including the two identified in Section 2b).
2. **11 SQL query sites across 6 backend files** were changed from a blocklist (`scope NOT IN (...)`) to an **allowlist** (`scope = 'global'` required whenever `user_id IS NULL`). This closes both the `admin_only` leak and the broader `user:*`-orphan pattern discovered during the fix (a mis-scoped `user:<id>` crystal with a null `user_id` would previously have leaked into the global pool the same way).
3. A regression test (`test_admin_only_scope_isolation.py`) was added asserting that none of the old vulnerable query patterns can reappear in the 6 protected files, and that the new allowlist condition is present at every site.
4. The public-trial funnel (P0.1) was separately hardened: crystal recall is now fully removed from the trial path (not merely filtered), a fiction-frame hard-stop was added to the trial boundary prompt, and a third-party-disclosure boundary clause was added and verified via a targeted red-team re-probe (zero live leaks confirmed as of 2026-07-09/07-10, both for the trial funnel and for the main app's admin_only path).
5. Fix deployed to production (GREEN, 68.183.168.75) via the standard safe-deploy path; service health and CI gate confirmed green after deploy.

**Still open (not yet deployed as of this memo — see Section 6):** a write-time guard to prevent a new name-bearing crystal from ever being written to `scope='global'` in the first place, and a standing recurring auditor to catch any future recurrence automatically rather than relying on a manual, one-time SQL sweep.

---

## 6. Statutory / compliance considerations for legal review

This project is a clinical/therapeutic platform (per workspace context: Illinois Mental Health and Developmental Disabilities Confidentiality Act, 740 ILCS 110, and HIPAA-aligned retention practices are already referenced elsewhere in the codebase's compliance rules — e.g., 7-year minimum retention for `factual_grounding_redirect` and `nate_accuracy_warning` records). Legal should independently confirm scope, but the engineering-side facts to evaluate are:

- **One identified client ("John D.") had personally identifiable therapeutic session content disclosed to two other clients** on two occasions, without his knowledge or consent, due to a software defect (not a hack, not user error, not a third-party actor — an internal access-control bug).
- The disclosed content included his name and a snippet of Nate's personalized clinical/therapeutic response to him — the kind of content 740 ILCS 110 and HIPAA would classify as protected mental-health treatment information.
- The exposure window for these two specific incidents is narrow and dated (2026-07-02 and 2026-07-05); the underlying software defect that made it *possible* was live for approximately 3.5+ months (since at least 2026-03-23) before being fixed.
- No evidence was found of this content being copied, screenshotted, exported, or further redistributed by the two recalling clients — it appeared inline in their own AI chat session context. There is no telemetry confirming whether either client actually *read* or *noticed* the exposed name/content within their session (both events occurred in the ordinary flow of an AI chat response, not as a flagged or highlighted disclosure).
- Whether individual notification to the affected client (John D.) and/or the two recipients (Lisa West, longra) is legally required, and on what timeline, is a legal determination outside engineering's authority. Engineering flags this memo's Section 2b table as the authoritative factual basis for that determination.
- No other real client's PHI is confirmed to have reached a third party under this defect, based on exhaustive recall-log review of every crystal that could plausibly have contained it.

---

## 7. Recommended next engineering steps (already in progress, tracked separately)

To close the underlying failure class rather than continuing to patch individual scope-check sites one at a time:

1. **Write-time guard**: block the creation of any `scope='global'` (or otherwise global-pool-eligible) crystal if its text contains a resolvable client name from the live user roster, or if the writing process could not resolve a specific `user_id` for the content. Apply this in `crystallize_from_conversation`, `crystallize_wisdom_absorption`, and the crystal-synthesis path in `nate_memory_crystallizer.py`.
2. **Standing recurring auditor**: a background agent that periodically re-scans all `global`/`admin_only`-eligible crystals against the live client-name roster and auto-quarantines any match, with results wired into the existing Trust Enforcer reporting pipeline (so a recurrence surfaces automatically in the next audit cycle rather than requiring another manual incident investigation).

These two items are tracked as open engineering work following this memo and are not yet deployed.
