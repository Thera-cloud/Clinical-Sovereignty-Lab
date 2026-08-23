# Thera-World Index Case — Emergent Collision (2026-08-22)

**Audience**: neuroscience review, patent/board briefing, Little Nate system memory  
**Classification**: research / architecture record (not a clinical chart; not a patent claim amendment)  
**Logged**: 2026-08-22  
**Companion**: `docs/NEUROSCIENCE_FOUNDATIONS_2026-05-07.md` §3.1  
**Code**: `backend/app/sse/thera_world_engine.py` → `compose_journey_narrative`

---

## Thesis

Thera-World is **designed** to turn stored therapeutic memory into a daily imaginal scene. A specific cultural figure in this index case was **not designed**. The generator emitted a high-specificity symbol from sparse, non-literal cues. The client recognized it as a private identity mapping. That recognition is clinically useful and scientifically constrained. It is not mind-reading.

**One line for board / patent:** expected class of output, unexpected instance.

**Term — emergent collision:** the image writer invented a culturally loaded visual schema from loose identity tokens; that invention lined up with a real mapping the client had not verbally given Little Nate before the panels.

---

## What is predesigned (claim the method)

Daily journey panels are retrieval-conditioned generation:

1. Identity forge (`sse_identity_forge`): archetype + character visual.
2. Crystal recall (recent + deep) from `nate_intelligence_crystals`.
3. Quests, missions, coach notes, assessment calibration.
4. `compose_journey_narrative` (LLM, temperature ~0.7) returns `narrative_text` + `image_prompt`, instructed to reflect the client **metaphorically, not literally**.
5. Image model renders `image_prompt`. Logged in `sse_panel_log.prompt_used`.
6. Client SIFT / “asking about my Sovereign Journey story panel image” (`sse_panel_chat_context.py`) writes new crystals.

This is the Sovereign Story Engine imaginal loop already described in the neuroscience foundations brief: image + narrative as a non-verbal memory anchor (Pearson et al. imagery overlap; Ecker/Schiller/Lane reconsolidation as **design target**, not a measured outcome in this case).

Stock archetypes include explorer, warrior, sage, healer, guardian, seraph. There is **no** Catwoman / feline stock asset in SSE.

---

## What is phenomenon (do not claim as a method step)

The named feline/protector figure was not hardcoded, not queued from a Catwoman disclosure, and not episodic recall by Little Nate.

Machine side: associative completion. Client-conditioned tokens × cultural visual priors. Sparse cues (explorer, “a little wild,” older alter-related crystals, a given name) have a strong cultural attractor in a well-known feline feminine protector schema.

Human side: recognition. A generated visual hit a stored identity schema. Recognition is the client’s memory, not the model “knowing.”

Confound to name first: apophenia. Once a cat-woman is seen, the client may bind it to a protector story. The audit trail shows **the prompt already contained feline / catwoman language before she asked**. This is generator specificity plus client recognition — not projection onto a blank card.

---

## Index case (internal)

Do **not** paste this block into a global crystal, a public patent filing, or another client’s context.

| Field | Value |
|---|---|
| Client username | `sweet2noend@yahoo.com` |
| Role | CLIENT |
| Display name | Kristy Moore |
| Journey `user_id` | `CLIENT_SWEET2NOEND@YAHOO.COM_ID` |
| Related accounts | `Freeindeed` CLIENT; `freeindeed` / `sweet2noend` COACH (same person, separate journeys) |

### Timeline (UTC)

| When | What |
|---|---|
| 2026-03-24 | Crystal: alters including a named figure (Angela). Not a Catwoman-movie mapping. |
| 2026-04-02 | Client asked Nate not to focus on alters. |
| 2026-04-06 onward | Journey panels: generic explorer / fortress. No feline language. |
| 2026-06-14 | First feline language in `sse_panel_log.prompt_used` (`subtle feline grace`). |
| 2026-06-30 03:30 | First explicit `catwoman-inspired explorer archetype`. |
| 2026-07-09 | Prompt language includes former-protector / Angela. |
| 2026-08-02 / 08-04 | `graceful cat-like poise` / `feline-inspired agility`. |
| 2026-08-06 21:36–22:50 | SIFT chat: “in my pic why is there a cat women.” Client says she never told Nate the Catwoman-movie / protector mapping. Nate first overclaims memory, then says he did not know yesterday. Client asks how Thera-World works; pastes a written scene dated 2026-06-26. |
| 2026-08-07 01:06 | Identity forge row completed (`archetype_hint=explorer`). Visual is a wild blonde explorer — not Catwoman. **After** the disclosure chat. |
| 2026-08-07 01:08–17:10 | Follow-up: probability / “how did you know”; later SIFT turn uses the new conversation as context. |
| 2026-08-07 03:15 | Next panel: crystal mountains / Mirror or Curiosity — prompt does **not** say catwoman. |

Pre-June-30 `conversation_history` does **not** contain the Catwoman-movie protector mapping. That talk is August 6–7.

---

## Neuroscience briefing (house language)

Do not say “the AI found her unconscious.”

1. Two systems met: retrieval-conditioned generation, and human recognition.
2. The model sampled a high-probability visual schema. That is closer to a personalized TAT card than to episodic recall.
3. The surprising part is under-determination by explicit report: she had not verbally given Nate that mapping before the June panels.
4. Therapeutic interest: “I never told you that” vs “it is in my world” is a **prediction-error**. That can open a reconsolidation window **if** the old learning is active and the experience is safe. This case does **not** prove reconsolidation (no fMRI, pupillometry, or pre/post schema measure). It is a logged behavioral sequence.
5. Honest scope (same as foundations §3.1): imaginal engagement of DMN / right-hemisphere imagery in users is **not measured**.

---

## Patent / board posture

| | Predesigned — claim this | Phenomenon — do not claim as a method step |
|---|---|---|
| What | Method: condition daily imaginal stimuli on identity + crystals; present as an ongoing world; capture inquiry; write new crystals | Outcome: a culturally specific named figure matched an undisclosed identity mapping |
| Evidence | Engine + `sse_panel_log` + SIFT widget | This index case timeline |
| IP use | Enablement of personalized imaginal generation + closed memory loop | Optional unexpected-result illustration for non-obviousness **only if** framed as: the method *can* emit high-specificity symbols from incomplete explicit report. Never: it *reliably recovers undisclosed trauma* |

Align to existing QEC language: schema activation by imaginal / symbolic method. Align to Crystal Intelligence: memory units condition generation, then the SIFT conversation reinforces new units.

**Claim the apparatus and the loop. Do not claim accurate surfacing of dissociative parts.** n=1, no control, no rate.

Ethics finding for the board: Nate first spoke as if he remembered the Catwoman story, then walked it back. **The system must not narrate generative coincidence as prior knowledge.** Log the prompt. Tell the client the image is composed metaphor. Offer coach review when a symbol is that specific.

### 90-second oral script

Thera-World is not a random art feed. Each day a composer writes a scene from stored therapeutic memory and identity, then an image model draws it. We instruct it to speak in metaphor, not to illustrate the chart.

In this index case, the composer began using feline language, then “catwoman-inspired explorer,” weeks before the client told Nate that a protector had first appeared as Catwoman. That mapping was not in prior chat. It was not a hardcoded asset.

The method is designed. The figure was an emergent completion: sparse identity cues plus a strong cultural schema. The client’s shock is a prediction-error — which maps to reconsolidation as a **design target**, not a measured outcome here.

We will not tell a regulator we can pull undisclosed trauma on demand. We will tell them we can generate personalized imaginal material from a memory store, we can log every prompt, and we must disclose that high-specificity hits are possible without prior verbal report.

---

## Accuracy rule for Little Nate

If a client asks how a Thera-World figure “knew” something they never said:

- Do **not** claim prior conversational knowledge unless `conversation_history` or a dated crystal contains that mapping.
- Say the panel is composed metaphor from stored themes and cultural schemas.
- The exact image language is in `sse_panel_log.prompt_used`.
- Do not claim mind-reading, quantum access to unspoken trauma, or reliable recovery of undisclosed identity material.

---

## System log pointers (GREEN, 2026-08-22)

- Repo record: this file.
- Neuroscience cross-ref: `docs/NEUROSCIENCE_FOUNDATIONS_2026-05-07.md` §3.1.
- `skyeye_activity` id **242342**, type `thera_world_index_case` (2026-08-23 00:55:52 UTC). Local `db_maintenance_agent.py` adds this type to `IMMUTABLE_TYPES` — **pending commit (uncommitted)**; GREEN prune exemption is not live until that file is deployed.
- Global research crystal id **816738**, domain `research`, scope `global`, confidence 0.85, `content_hash` `a259e52fec0ae16c19c4c71d6c7c28ccbb7bd4cfdf65ec13f70ef58e2828b55f`. PHI-free operational text only (no client name).

These are local docs plus GREEN data writes. Not a patent filing. Not committed unless requested.
