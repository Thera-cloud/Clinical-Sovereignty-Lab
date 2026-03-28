---
name: Classroom UX Decisions Plan
overview: "Capture the user's UX clarifications for the Classroom and Lived Wisdom plans: who can archive and use CLASSROOM, who gets which email notifications, client-Nate flow without client notification, INSIGHTS search by client name + date, and coach email when client engages with session takeaways."
todos: []
isProject: false
---

# Classroom + Lived Wisdom: UX Decisions and Plan Updates

This plan records your UX decisions and specifies the exact updates to make to the two existing plan documents so they reflect coach/assistant/master roles, notifications, and client-engagement signaling.

---

## 1. Decisions Summary


| Gap                                                       | Decision                                                                                                                                                                                                                                                                                               |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Who can archive transcript**                            | Coach, assistant, or master can archive.                                                                                                                                                                                                                                                               |
| **Master notification when analysis is pending**          | Master gets an email that analysis is pending (when a session is archived, so the master is in the loop).                                                                                                                                                                                              |
| **Client notification after archive**                     | Client does not get a notification. Little Nate is aware of the archived transcript and uses it to help navigate the client through the coach's goals and between live sessions via Nate's lived wisdom and learned history of the client.                                                             |
| **Who can use CLASSROOM (see sessions, choose DOJOs)**    | Coach, assistant, or master only (all three can do it).                                                                                                                                                                                                                                                |
| **Client access to assessment doc**                       | Client only gets what Little Nate says in chat; not the raw doc. Purpose: keep the coach as the human connection for the depth of assessment.                                                                                                                                                          |
| **INSIGHTS / FOLDER recall**                              | Coach invokes by chat and asks Little Nate to search FOLDER associated with **client name + date of session** (natural-language trigger; backend resolves client name + date to folder/search).                                                                                                        |
| **Coach notification when client engages with takeaways** | Coach (and assistant or master, as appropriate) is **emailed** when the client has engaged with session takeaways in chat with Nate. This (1) gives the coach/assistant/master connection that their client is engaging, and (2) helps them see that Little Nate is supporting them with their client. |


---

## 2. Updates to Apply to the Plan Documents

### 2.1 Main plan: [classroom_phd_assessment_and_lived_wisdom_ff0eaa2a.plan.md](.cursor/plans/classroom_phd_assessment_and_lived_wisdom_ff0eaa2a.plan.md)

**A. Part 1 — Key files / flow**

- **Archive trigger:** Clarify that the **coach, assistant, or master** can trigger "Archive Transcript" from the Schedule tab (whoever has access to that session in the coach portal). No code-path change implied; document the product intent.
- **Recipient of "ready for assessment" email:** Today the plan says "trigger email to coach." Update to: (1) **Coach** (or assistant who ran the session) gets "Session ready for assessment — open CLASSROOM and choose DOJOs." (2) **Master** (if the session was run by an assistant under that master) also gets an email that **analysis is pending** so the master is notified.

**B. Part 2 — Target Architecture**

- Add a small **Notifications** note: (1) Coach/assistant: "Session ready for assessment." (2) Master: "Analysis pending" when a session under their oversight is archived. (3) Coach/assistant/master: "Assessment ready for [Client] in FOLDER." (4) **New:** Coach/assistant/master: "Client engaged with session takeaways" when the client has chatted with Nate about the session.
- In the **Client** subgraph: Add a bullet that the **client does not** get an in-app or email notification when a transcript is archived; Nate uses the archived transcript and lived wisdom to guide the client through the coach's goals and between live sessions.

**C. Phase C — Notifications (C1)**

- **C1:** After archive, send email to **(a) the coach (or assistant) who owns the session** ("Session ready for assessment — open CLASSROOM and choose DOJOs"), and **(b) the master coach**, if the session was conducted by an assistant under that master ("Analysis pending for [Client] — session ready for assessment" or equivalent).
- **New C3 (or extend C):** When the **client** has engaged with session takeaways in chat with Little Nate (e.g. first message in that conversation that references the session or triggers session context), send an **email to the coach (and optionally assistant/master)**: "Client engaged with session takeaways" (or "[Client name] chatted with Little Nate about their session"). Purpose: signal that the client is engaging and that Little Nate is supporting the coach/assistant/master with that client.

**D. Phase D — INSIGHTS (D3)**

- **D3. FOLDER search/recall:** Coach invokes **by chat** (e.g. "Search FOLDER for [client name] and [date of session]" or "What's in [Client]'s folder for the session on [date]?"). Backend/Nate resolves **client name + date of session** to the relevant FOLDER contents and injects into context so Nate can answer. Document that the primary UX is natural-language search by client name + date.

**E. Phase E — Client-facing Nate (E1)**

- **E1:** Explicitly state: **Client does not receive a notification** when a transcript is archived. Little Nate is aware of the archived transcript and uses it (plus lived wisdom and learned history) to help navigate the client through the coach's goals and between live sessions. Client only experiences this via conversation with Nate.
- Reiterate: **Client never sees the raw assessment doc**; the coach remains the human connection for the depth of assessment. Nate reflects and supports without contradicting.

**F. Phase E — Master / assistant (E2)**

- **E2:** Clarify that **CLASSROOM** (sessions list, choose DOJOs, YOUR PROGRESS, View in FOLDER) is available to **coach, assistant, and master** (whoever has access to that session in the coach portal). Same for INSIGHTS brief and FOLDER recall. Master-only piece remains: asking about **assistant + client** coherence in INSIGHTS.

**G. Part 4 — Order of work**

- Add an item (e.g. after notifications): **"Coach/assistant/master email when client engages with session takeaways"** — detect client engagement with session takeaways in chat and send email to the relevant coach/assistant/master.

**H. Emails (summary section)**

- List all four (or five) emails:
  1. Coach/assistant: "Session ready for assessment — choose DOJOs."
  2. Master: "Analysis pending" (when session under their oversight is archived).
  3. Coach/assistant/master: "Assessment ready for [Client] in FOLDER."
  4. Coach/assistant/master: "Client engaged with session takeaways" (when client chats with Nate about the session).

---

### 2.2 Addendum: [lived_wisdom_persistence_addendum_6996a4c1.plan.md](.cursor/plans/lived_wisdom_persistence_addendum_6996a4c1.plan.md)

**A. Section 2 — New requirement**

- Under "Lived wisdom and learned history," add: **Client does not get a notification** when a transcript is archived. Little Nate uses the archived transcript and learned history to **navigate the client through the coach's goals and between live sessions**; the client experiences this only through conversation with Nate.

**B. Section 3 — Phase A0.4 (Liminal intelligence)**

- Add one line: Stored session wisdom is used so Nate can support the client **between live sessions** and align with the coach's goals, without the client receiving a separate notification about archiving or assessment.

**C. Section 4 — Order of work**

- No structural change; the "client engagement email" is covered in the main plan. Optionally add a cross-reference: "Coach notification when client engages with takeaways (see main plan Phase C / E)."

---

## 3. Implementation Notes (for when you build)

- **Who can archive:** Same Schedule UI and `POST /api/sessions/{sessionId}/zoom/archive_transcript`; authorization already scoped to coach (or assistant/master by existing auth). Ensure backend resolves "master of this coach/assistant" (e.g. from `coach_hierarchy`) when sending the "Analysis pending" email to the master.
- **"Client engaged with session takeaways":** Requires a definition of "engaged" (e.g. client sent a message in a conversation where session context was injected, or first message that triggers `get_client_context_for_nate` including session takeaways). Add a hook or flag in the client–Nate chat path that, when session takeaways are used in context and the client sends a message, triggers an email to the coach (and optionally assistant/master) for that client. Store a lightweight "last_engagement_signal_sent_at" per client (or per session) to avoid spamming (e.g. once per session or once per day per client).
- **INSIGHTS FOLDER search by client name + date:** Backend or Nate context-builder must accept a natural-language or structured "client name + date" and map to (1) client_id, (2) session_id or date range, (3) FOLDER files for that client. Existing folder API may need a query like `?client_name=...&session_date=...` or a dedicated "search folder for client + date" helper used by the INSIGHTS context pipeline.

---

## 4. Checklist for Plan Edits

When you edit the two plan files (in Agent mode or manually), apply:

- Main plan: Archive and CLASSROOM available to coach, assistant, master.
- Main plan: Two emails after archive — coach/assistant ("ready for assessment") and master ("analysis pending").
- Main plan: Client gets no notification; Nate uses transcript and lived wisdom to guide client through coach's goals and between sessions.
- Main plan: INSIGHTS FOLDER recall invoked by chat; search by client name + date of session.
- Main plan: Client never sees raw assessment doc; coach remains human connection for depth.
- Main plan: New email — "Client engaged with session takeaways" to coach/assistant/master.
- Main plan: Order of work + Emails summary updated.
- Addendum: Client no notification; Nate navigates client through goals and between sessions (one short add in requirement + A0.4).

No code or schema changes in this plan; only documentation and product-intent updates to the two plan documents.