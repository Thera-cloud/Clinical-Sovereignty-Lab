# Classroom Lived Wisdom — End-to-End Audit Test Scenario

This document defines the canonical acceptance test for the Classroom + Lived Wisdom + UX Decisions flow. Use it to verify notifications, roles, INSIGHTS, client engagement, and lived-wisdom explanation.

---

## Personas and Test Accounts

| Persona | Role | Test account (suggested) | Notes |
|--------|------|---------------------------|--------|
| **Audit Student 1** | Client | `audit_client` / `audit_client_hw` | Display name "Audit Student 1" in profile if desired |
| **Audit Lawyer 1** | Assistant coach | `audit_coach` / `audit_coach_hw` | Display name "Audit Lawyer 1"; in `coach_hierarchy` as assistant under Master Audit Coach |
| **Master Audit Coach** | Master coach | e.g. `master_audit_coach` or existing master (e.g. CoachN) | In `coach_hierarchy` as master of Audit Lawyer 1 |

Ensure `coach_hierarchy` has a row: assistant = Audit Lawyer 1 (`audit_coach_hw`), master = Master Audit Coach, so that “sessions under their oversight” and master-only INSIGHTS apply.

---

## Scenario Steps and Implementation Status

### 1. Live session and archive

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 1.1 | Conduct a live session between **Audit Lawyer 1** (assistant) and **Audit Student 1** (client). | Session appears in Schedule; recording/transcript available. | Manual |
| 1.2 | **Master Audit Coach** archives the transcript (Schedule → Archive Transcript). | Transcript stored; initial analysis runs; analysis written to PG (`classroom_session_analyses`) and JSON; status `pending_dojo_selection`. | ✅ Archive + PG persist done. |
| 1.3 | **Audit Lawyer 1** sees in CLASSROOM that the session is **pending** (ready for assessment / DOJO selection). | CLASSROOM tab shows session with “pending” and “Choose DOJOs” (or equivalent). | ⏳ Pending: DOJO selection UI + status in CLASSROOM. |
| 1.4 | **Audit Lawyer 1** never completes DOJO selection. | Session remains in `pending_dojo_selection`. | N/A (intentional in scenario). |

### 2. Notifications after archive

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 2.1 | After archive, **Audit Lawyer 1** (assistant who ran session) receives email. | “Session ready for assessment — open CLASSROOM and choose DOJOs.” | ⏳ Pending: C1 email trigger. |
| 2.2 | **Master Audit Coach** receives email. | “Analysis pending for [Audit Student 1] — session ready for assessment.” | ⏳ Pending: Master “analysis pending” email (resolve master from `coach_hierarchy`). |

### 3. Master completes DOJO selection and assessment

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 3.1 | **Master Audit Coach** opens CLASSROOM, selects the pending session, **determines DOJOs** (e.g. THERAPIST, BUSINESS) and submits. | `classroom_select_dojos` (or equivalent) sets `selected_dojos` and status `assessing`; backend may allow master to act on assistant’s session. | ⏳ Pending: DOJO selection handler + master override. |
| 3.2 | System generates PhD-level per-DOJO and combined assessment. | Analysis record updated with `assessments`, status `completed`, `final_assessment_doc_id` when doc is created. | ⏳ Pending: B2 assessment generation + B3 FOLDER. |
| 3.3 | Assessment document is placed in **Audit Student 1’s folder** under the coach (or master) FOLDER tab. | File visible in FOLDER for that client. | ⏳ Pending: B3 FOLDER placement. |
| 3.4 | Coach/assistant/master receive email. | “Assessment ready for [Audit Student 1] in FOLDER.” | ⏳ Pending: C post-assessment email. |

### 4. INSIGHTS — Audit Lawyer 1 asks about the session

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 4.1 | **Audit Lawyer 1** opens INSIGHTS and asks Little Nate about the session (e.g. “Give me a brief of my session with Audit Student 1 on [date]” or “What did we cover in that session?”). | Nate has context (session brief / FOLDER recall); responds with detailed brief and can coach the coach. | ⏳ Pending: D1/D3 INSIGHTS brief + FOLDER recall (client name + date). |

### 5. INSIGHTS — Master Audit Coach asks about assistant + client

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 5.1 | **Master Audit Coach** opens INSIGHTS and asks about **Audit Lawyer 1** and **Audit Student 1** (e.g. “What is Little Nate’s assessment of Audit Lawyer 1 and Audit Student 1?” or “How is their coherence?”). | Nate returns master-only view: coherence (client–coach, client–Nate, coach–client–Nate), assessments, and support narrative. | ⏳ Pending: E2 master-only INSIGHTS coherence. |

### 6. Client engages with session materials → notification

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 6.1 | **Audit Student 1** (client) chats with Little Nate about the session and engages with coach materials (e.g. asks about takeaways, goals, or progress). | Nate uses lived wisdom / session context to reflect and support without contradicting the coach. | ⏳ Pending: E1 client-facing Nate session context. |
| 6.2 | System detects “client engaged with session takeaways.” | Logic flags engagement (e.g. first message in context where session takeaways were injected, or explicit trigger). | ⏳ Pending: Client-engagement detection. |
| 6.3 | **Audit Lawyer 1** (assistant) and **Master Audit Coach** receive email. | “Client engaged with session takeaways” / “[Audit Student 1] chatted with Little Nate about their session.” | ⏳ Pending: C3 client-engagement email. |

### 7. All other notifications sent and received

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 7.1 | Confirm all designed emails in the flow were sent and received. | (1) Ready for assessment → Audit Lawyer 1; (2) Analysis pending → Master Audit Coach; (3) Assessment ready in FOLDER → coach/assistant/master; (4) Client engaged → Audit Lawyer 1 + Master Audit Coach. | ⏳ Pending: Full notification pipeline. |

### 8. Lived wisdom / learned history — Master asks Nate

| Step | Action | Expected | Status |
|------|--------|----------|--------|
| 8.1 | **Master Audit Coach** asks Little Nate in INSIGHTS: “What lived wisdom and learned history did you capture from this session?” and “How will you help the client, Audit Student 1, between live sessions so they maintain and engage with the assistant coach’s (Audit Lawyer 1) shared guidance and plans?” | Nate answers from stored session wisdom (PG + context): what was captured (transcript, analysis, CEEs, coach–client dynamics) and how Nate will use it to support the client between sessions and align with Audit Lawyer 1’s guidance. | ⏳ Pending: INSIGHTS context that reads from `classroom_session_analyses` / payload and liminal-intelligence narrative in system prompt or context. |

---

## Summary: What Exists Today vs. Pending

| Area | Done | Pending |
|------|------|--------|
| Archive transcript | ✅ Master/coach/assistant can archive; analysis runs and is written to PG. | — |
| CLASSROOM list | ✅ Bridge uses PG; sessions with transcripts listed. | DOJO selection UI; status badges (pending/assessing/completed). |
| DOJO selection | — | B1 UI + `classroom_select_dojos`; master can set DOJOs for assistant’s session. |
| PhD assessment + FOLDER | — | B2 generation; B3 doc + FOLDER placement; link `final_assessment_doc_id`. |
| Notifications | — | C1 ready-for-assessment; C2 master “analysis pending”; post-assessment “in FOLDER”; C3 client-engagement email. |
| INSIGHTS brief + FOLDER recall | — | D1/D3; client name + date → FOLDER/search; brief in Nate context. |
| INSIGHTS master-only | — | E2 coherence (client–coach, client–Nate, coach–client–Nate) for assistant + client. |
| Client Nate session context | — | E1; client chat context includes session takeaways; Nate reflects without contradicting. |
| Client-engagement detection | — | Flag when client uses session takeaways in chat; trigger C3 email. |
| Lived-wisdom explanation in INSIGHTS | — | Master can ask “what did you capture?” and “how will you help between sessions?”; context from PG + liminal guidelines. |

---

## How to Run This Audit (When Implemented)

1. **Prerequisites:** Ensure Audit Student 1, Audit Lawyer 1, and Master Audit Coach exist; Audit Lawyer 1 is assistant under Master in `coach_hierarchy`; one completed live session with transcript.
2. **Execute steps 1–8** in order, using the personas above.
3. **Verify:** Each “Expected” in the tables (emails, INSIGHTS answers, CLASSROOM state, FOLDER doc, client engagement email).
4. **Optional automation:** For steps that expose REST/WebSocket (e.g. archive, classroom sessions, analyses), add script or auditor checks; manual verification for INSIGHTS chat and email delivery.

---

## Audit run (post-deploy)

**Deployed:** Backend + bridge with DOJO selection, C1/C2/post-assessment emails, PG analyses, coach_hierarchy master lookup (status `accepted` or `active`).

1. **Prerequisites:** `audit_coach` (audit_coach_hw) is assistant under CoachN in `coach_hierarchy` (already present on server). Migration 103 available; `get_master_for_assistant_pg` accepts both `accepted` and `active`.
2. **Manual flow:** Run a live session as Audit Lawyer 1 with Audit Student 1 (audit_client); archive the transcript via Schedule → Archive. Check inbox for audit_coach for "Session ready for assessment" and master (CoachN) for "Analysis pending."
3. **DOJO selection:** As CoachN or audit_coach, open coach portal → CLASSROOM, pick the pending session, send WebSocket `{"type":"classroom_select_dojos","session_id":"<id>","dojo_keys":["THERAPIST","BUSINESS"]}`. Expect `classroom_dojos_selected` and "Assessment ready in FOLDER" emails to coach + master.
4. **REST:** `GET /api/coach/classroom/analyses/audit_coach_hw` (with coach auth) returns analyses.
5. **Still pending:** INSIGHTS brief/FOLDER recall (D1/D3), master-only coherence (E2), client session context (E1), client-engagement email (C3), lived-wisdom Q&A (8.1).

---

## Reference Plans

- [Classroom PhD Assessment and Lived Wisdom](classroom_phd_assessment_and_lived_wisdom_ff0eaa2a.plan.md)
- [Lived Wisdom Persistence Addendum](lived_wisdom_persistence_addendum_6996a4c1.plan.md)
- [Classroom UX Decisions](classroom_ux_decisions_plan_75fb6377.plan.md)
