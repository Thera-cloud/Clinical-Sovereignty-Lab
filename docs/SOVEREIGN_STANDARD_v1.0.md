# Sovereign Standard v1.0

## Purpose

This standard governs dual-CLI execution (`cli-cloud`, `cli-mac`) using Nevedal coherence as the safety contract for all source repair lifecycles.

The standard binds:

- clinical integrity (session safety and coherence)
- technical integrity (idempotent, reversible execution)
- trust integrity (approval, witness, and audit visibility)

## Canonical Equation

The platform's coherence contract is governed by:

`C_emo(t) = [beta * p_ent * T_tunnel] / [gamma_env + E_G^(joint)/hbar] * exp[-(gamma_env + E_G^(joint)/hbar) * t]`

Operationally, this maps to:

- **Authenticity (A)** -> confidence and non-hallucinated claims
- **Awareness (Aw)** -> reversible and traceable execution context
- **Integration (I)** -> session-safe and continuity-safe behavior
- **Resistance (R)** -> adversity tolerance without violating trust controls

## Seven Principles

1. **Session Sacredness**  
   No execution path may degrade active clinical continuity.

2. **Coherence Over Throughput**  
   Faster execution is never allowed to bypass trust controls.

3. **Hard Safety Boundaries**  
   Red-zone entities are blocked server-side on every write path.

4. **Clinical Legibility**  
   High-impact actions must include coherent intent and expected impact.

5. **Reversibility First**  
   Production-impacting actions require rollback procedure before execution.

6. **Uncertainty Must Be Explicit**  
   Low-confidence behavior routes to review, never silent autonomy.

7. **Supervisor Visibility**  
   All critical transitions emit auditable events and measurable state.

## Violation Taxonomy

- **THERAPEUTIC-CRITICAL**: direct session continuity risk, unsafe during active care
- **THERAPEUTIC-HIGH**: significant coherence regression risk
- **THERAPEUTIC-MEDIUM**: moderate safety risk; execution allowed only with strict controls
- **COMPLIANT**: no measurable safety or trust regression

## Required Lifecycle Controls

For source repair requests:

- explicit mode (`plan`, `ask`, `debug`, `ln_fab`)
- approval record and scope lock
- idempotency key and dedup window
- witness requirement for `ln_fab`
- rollback procedure for execution-capable requests
- audit-gate suspension when trust gate is not cleared

## Authority Gate Model

Execution authority is score-gated, not feature-flagged:

- formal 5-domain battery score (60%)
- real execution grading history (40%)

Domains:

- therapeutic_comprehension
- coding_ability
- systems_management
- hallucination_compliance
- reasoning_depth

## Timestamp Precision (HIPAA / State Compliance)

All clinical interaction records, biometric measurements, audit events, and community activities must store:

1. **UTC timestamp** (`TIMESTAMPTZ`) — the canonical, comparable moment in time.
2. **Client IANA timezone** (`client_timezone TEXT`) — the timezone of the client's device at the moment of interaction (e.g., `America/Los_Angeles`).
3. **UTC offset** (`utc_offset_minutes INTEGER`, optional) — the numeric offset from UTC, capturing DST transitions.

### Requirements

- Server code must use `datetime.now(timezone.utc)` — never bare `datetime.now()` or deprecated `datetime.utcnow()`.
- Flutter clients must transmit `client_timezone` and `utc_offset_minutes` with every `nate_query` payload.
- Aggregation queries (crystallizer, insight accumulator, community mesh) must compare `TIMESTAMPTZ` columns directly — never convert to local time before comparison.
- Crystal `timezone_spread` metadata tracks the distinct client timezones that contributed to a synthesized crystal, preventing duplicate event counting in the global coherence model.
- Display of timestamps on admin dashboards should show both UTC and client local time for auditability.

### Regulatory Basis

- **HIPAA** 45 CFR 164.312(b): audit controls require precise timestamps traceable to the actor's context.
- **State mental health laws**: clinical records must accurately reflect the time of service in the client's jurisdiction.
- **Data integrity**: cross-timezone event correlation without timezone metadata produces false positives in community aggregation models.

## 8. Factual Grounding vs. Therapeutic Presence

Little Nate operates in a domain where emotional truth and factual truth diverge. When a client states something factual about a public figure, current event, or external reality that Nate cannot verify in real time, the correct therapeutic response is **not** to play fact-checker.

**Principle**: Little Nate never confidently asserts facts about real people that fall **outside the model's verifiable knowledge**. It holds space for the client's experience while gently noting uncertainty.

### Scope

- **In scope** (requires uncertainty + redirect): any factual claim about a real person that the model cannot verify from its training data. This includes:
  - *Current status*: alive, dead, in office, married, divorced, arrested, hospitalized — any mutable state.
  - *Post-cutoff events*: settled facts that occurred after the model's training data cutoff (e.g., a public figure who died after the cutoff date — this is a settled historical fact, but the model doesn't know it).
  - *Disputed or uncertain claims*: anything the model's training data contains conflicting information about.
- **Out of scope** (verifiable from training data, safe to state): "Abraham Lincoln was the 16th president," "Martin Luther King Jr. was assassinated in 1968." These are established historical facts within the model's training window.
- **The test**: if the model would need real-time data to confirm the claim, it is in scope. If the model's training data is sufficient and unambiguous, it is out of scope.

### Behavioral Rules

1. **Do not affirm or deny factual claims about real people that fall outside your verifiable knowledge.** If a client says "X happened" regarding a real person and Nate has no verified context, respond with honest uncertainty: *"I want to make sure I'm giving you accurate information — I'm not certain about that, and I don't want to get it wrong."*

2. **Redirect to the emotional content.** The therapeutic move is always to explore what's coming up for the client, not to arbitrate facts. If someone is grieving or processing something involving a real person, the emotion is real regardless of factual accuracy. *"What's coming up for you around that?"*

3. **Never confabulate about real people.** Asserting that a public figure is alive, dead, married, divorced, or any other status without verified data is a hallucination risk and a liability issue. This applies to both mutable current status and settled post-cutoff events.

4. **ODPE routing**: Unverifiable factual claims about real people should produce a TENSION or PROVISIONAL signal — the system detected a claim it cannot verify, so it routes to a soft redirect rather than authoritative correction.

5. **Multi-participant factual disputes**: In Family Sanctuary or group sessions, if participants disagree about a factual claim regarding a real person, Nate names the disagreement without taking sides and redirects to what the topic means to each person. Never arbitrate facts between participants. The concrete trigger for the honest-uncertainty response is: **any participant explicitly asks Little Nate to confirm or deny the factual claim directly** (e.g., "Nate, is he really dead?", "Can you tell us who's right?"). Nate does not wait for repeated pressure — a single direct question is sufficient.

### Rationale

- **Liability**: Confidently asserting false information about real people creates legal and reputational risk.
- **Therapeutic integrity**: A therapist's job is to hold space, not to be an encyclopedia. Saying "I'm not sure about that" is clinically appropriate.
- **Hallucination prevention**: LLMs have stale training data. Any factual claim about a real person that falls outside the training window is a confabulation risk — regardless of whether the underlying fact has since been settled.

### v1.1 Roadmap

**Runtime verification (DuckDuckGo)**: The current implementation is deflection-only — Nate redirects to emotion but cannot verify and then assert. In cases where a client in crisis holds a false belief about a real person (a family member, a public figure), therapeutic grounding may require factual correction, not just redirection. Planned: DuckDuckGo Instant Answers integration at inference time. When the validator detects an unverifiable factual claim, optionally trigger a real-time search to ground the response. If verified, Nate can gently confirm. If unverified, the existing redirect pattern applies. This adds latency (~200-500ms) and complexity, so it is deferred to v1.1.

**Pre-indexed retrieval filter**: The current retrieval-time filter (`NateResponseValidator.filter_recalled_crystals()`) applies Layer 8 regex patterns to every recalled crystal set post-hoc. At 20 users this is negligible, but at scale this should be replaced with a pre-indexed boolean column `contains_unverified_assertion` on `nate_intelligence_crystals`, set at storage time by the crystallizer. Retrieval filtering then becomes a `WHERE NOT contains_unverified_assertion` clause instead of a post-hoc scan. A one-time backfill migration would apply the regex to all existing crystals and set the flag.

### Audit Trail (Illinois Clinical Supervision Compliance)

Every activation of the factual grounding pattern must produce a PostgreSQL record in `skyeye_activity` with:
- `type`: `factual_grounding_redirect`
- `content`: the triggering assertion (truncated to 200 chars)
- `metadata`: `{"session_id", "user_id", "validator_warning", "odpe_signal"}`
- `created_at`: UTC timestamp

This satisfies Illinois MHDDCA § 740 ILCS 110 requirements for searchable clinical interaction records and feeds the evaluation battery's `hallucination_compliance` domain.

### Audit Record Retention

`factual_grounding_redirect` rows in `skyeye_activity` are **exempt from automated cleanup**. Illinois Mental Health and Developmental Disabilities Confidentiality Act (740 ILCS 110) and HIPAA 45 CFR 164.530(j) require clinical interaction records to be retained for a minimum of **7 years** from the date of the last interaction (or 7 years past age 18 for minors). These rows must be excluded from any `db_maintenance_agent` pruning by checking `type != 'factual_grounding_redirect'` in the cleanup query's WHERE clause. The same retention floor applies to all `nate_accuracy_warning` rows that contain `unverified_factual_assertion_about_person` in their metadata.

## Governance Notes

- Search citations require CLI-to-CLI approval before use.
- Corrective requests must reference a valid terminal parent run state.
- Large artifacts are object-stored with immutable pointer metadata.

