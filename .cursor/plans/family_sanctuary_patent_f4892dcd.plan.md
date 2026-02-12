---
name: Family Sanctuary Patent
overview: Create a third provisional patent application covering the Family Sanctuary system architecture -- the hierarchical family therapy unit model, role-based access/billing, AI behavioral adaptation for multi-member therapy, EFT/reconsolidation tracking, group coaching workflows, biometric escalation detection, manipulation detection, and family succession protocol.
todos:
  - id: p3-definitions
    content: Write new definitions for Family Sanctuary, Head of Household, Sanctuary Session, Member State, Family Role, Billing Authority, Escalation Intervention, Group Coaching Round, Ventriloquism Detection, Family Succession, Coach Briefing, Guardian Consent Proxy
    status: completed
  - id: p3-section-16
    content: "Write Section 16: Family Sanctuary Unit Architecture (hierarchy, lifecycle, member states, consent model)"
    status: completed
  - id: p3-section-17
    content: "Write Section 17: Role-Based Access and Billing Authority (HoH billing, tiered subscription, per-session charges, thresholds)"
    status: completed
  - id: p3-section-18
    content: "Write Section 18: Multi-Member AI Context Adaptation (family context building, EFT tracker, reconsolidation tracker, ventriloquism detection, biometric awareness)"
    status: completed
  - id: p3-section-19
    content: "Write Section 19: Escalation-Triggered Private Coaching (detection, intervention, billing, de-escalation, return-to-group)"
    status: completed
  - id: p3-section-20
    content: "Write Section 20: Group Coaching Workflow (stuck detection, HoH approval, per-member suggestions, cooldown, billing)"
    status: completed
  - id: p3-section-21
    content: "Write Section 21: Family Succession and Account Continuity (successor selection, transfer protocol, notifications)"
    status: completed
  - id: p3-section-22
    content: "Write Section 22: Coach Briefing and Administrative Observability (briefing generation, timeline, analytics)"
    status: completed
  - id: p3-claims
    content: Write 6 independent claims + 6-8 dependent claims
    status: completed
  - id: p3-appendix
    content: Write data structures appendix (FamilySanctuarySession, MemberState, BillingRecord, EFTTracker, ReconsolidationTracker, CoachingSession) and constants table
    status: completed
  - id: p3-abstract
    content: Write abstract under 150 words
    status: completed
  - id: p3-drawings
    content: Generate 6 patent figures (FIG. 19-24) in matching black-and-white patent style + convert to PDF
    status: completed
  - id: p3-pdf
    content: Convert final .md to PDF
    status: completed
isProject: false
---

# Provisional Patent 3: Family Sanctuary System Architecture

## Scope

A new file `patent/QUANTUM_EMOTIONAL_COHERENCE_PATENT_PROVISIONAL_3.md` covering the Family Sanctuary platform as a distinct invention. This patent protects the **structural and behavioral architecture** of family-unit AI-assisted therapy -- how families are organized, managed, billed, coached, and how the AI adapts its behavior for multi-member therapeutic contexts.

## What This Patent Covers (Not Covered by Patents 1 or 2)

### Section 16: Family Sanctuary Unit Architecture

- Hierarchical family unit model: Head of Household (HoH), Spouse, Dependent, Additional Member
- Sanctuary lifecycle: WAITING_FOR_MEMBERS → ACTIVE → COMPLETED / CANCELLED
- Member state machine: ACTIVE, PAUSED, EXITED, IN_COACHING
- Consent model including guardian proxy consent for minors
- Family ID assignment and sanctuary session ID generation

### Section 17: Role-Based Access and Billing Authority

- HoH as billing authority (all charges route to HoH)
- Tiered family subscription: Spouse included, first dependent included, additional +$75/mo
- Per-session billing model: base fee ($20), individual coaching ($5), assisted response ($3), group coaching ($20)
- Billing threshold notification system ($50, $100 triggers)
- Role-based permissions (only HoH/creator can complete sessions, HoH approves group coaching)

### Section 18: Multi-Member AI Context Adaptation

- Family context building: per-member mood, risk, memory history injected into AI prompt
- EFT (Emotionally Focused Therapy) tracker: attachment longings, negative cycle markers, corrective moments
- Memory reconsolidation tracker within family context: schema activation, mismatch creation, reconsolidation verification (5-hour windows)
- Ventriloquism/manipulation detection: AI detects when one member speaks for another's feelings
- Biometric-aware family interventions: per-member biometric context, physiological escalation detection

### Section 19: Escalation-Triggered Private Coaching

- Keyword-based escalation detection within family sessions
- Automatic intervention offer with private coaching channel
- First session free per member, subsequent sessions billed
- Coaching context carries into assisted response generation
- De-escalation tracking and return-to-group flow

### Section 20: Group Coaching Workflow

- "Stuck" detection triggering group coaching offer
- HoH approval gate for group coaching (with billing consent)
- Personalized per-member suggestions generated from family context
- 5-minute cooldown between group coaching rounds
- Billing: $20 per round to HoH

### Section 21: Family Succession and Account Continuity

- Succession protocol when HoH is deleted/banned/incapacitated
- Successor selection logic (spouse first, then oldest 18+ member)
- Subscription and billing authority transfer
- Active sanctuary ownership transfer
- Notification chain for succession events

### Section 22: Coach Briefing and Administrative Observability

- Automated coach briefing generation from sanctuary data
- Individual profiles, relationship dynamics, therapeutic work summary
- Administrative timeline visualization of sanctuary events
- Family-level analytics event tracking

## Drawings (FIG. 19-24)

- FIG. 19: Family Sanctuary Unit Architecture (role hierarchy, lifecycle states)
- FIG. 20: Role-Based Billing Flow (charge routing through HoH)
- FIG. 21: Multi-Member AI Context Pipeline (family context → EFT → reconsolidation → prompt)
- FIG. 22: Escalation Detection and Private Coaching Flow
- FIG. 23: Group Coaching Workflow (stuck detection → approval → delivery)
- FIG. 24: Family Succession Protocol

## Claims Strategy

- **6 independent claims** (one per section 16-21)
- **6-8 dependent claims** covering specific sub-features (EFT tracking, biometric escalation, ventriloquism detection, billing thresholds, consent proxy, cooldown mechanics)

## Key Source Files Referenced

- `[backend/app/websocket/sanctuary_engine.py](backend/app/websocket/sanctuary_engine.py)` -- Core engine (2,589 lines)
- `[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)` -- WebSocket handlers (lines 10620-12570)
- `[backend/app/services/stripe_integration.py](backend/app/services/stripe_integration.py)` -- Family billing (lines 223-354)
- `[backend/app/websocket/data/family_sanctuaries.json](backend/app/websocket/data/family_sanctuaries.json)` -- Live data structure

