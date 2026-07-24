# Avatar Mode — Facial Expression Design Brief

**Audience:** 3D asset owner / GLB pipeline
**Why this exists:** Only 3 visually distinct meshes currently exist across 7 GLB files (see `docs/OPEN_TODOS.md`, 2026-07-03 entry). `sad.glb` / `mad.glb` / `proud.glb` are byte-identical; `calming.glb` / `curious.glb` / `empathetic.glb` are byte-identical. This brief lists every expression the client-mood mirroring system can request, in priority order, with a visual spec for each so re-exports land in one pass instead of several rounds of guessing.

---

## How expressions get selected (context for the artist)

Little Nate's avatar expression is driven by two things:
1. **What Nate is about to say** (keyword/intent detection on his own reply — `backend/app/websocket/avatar_handlers.py::_determine_avatar_state`)
2. **What the client just said** (mood-mirroring / mis-mirror guard — if the client discloses distress, Nate's face must not stay warm/celebratory; it mirrors toward empathetic/sad first)

Twelve logical states exist in code (`mobile/lib/avatar.dart` → `AvatarExpression` enum). Right now they're collapsed into **7 GLB file slots**, and those 7 files only render **3 unique faces**. The table below is organized by GLB file slot (what needs to be re-exported), with the logical states each slot covers and why collapsing them loses meaning.

---

## Priority 1 — Currently indistinguishable, high frequency (fix first)

### `mininate empathetic.glb` (the "soft" bucket)
Currently shared by **4 different logical states** — this is the single biggest fidelity loss since it fires constantly (every empathy/validation/encouragement/greeting response).

| Logical state | When it fires | Target look |
|---|---|---|
| **Empathetic** | Nate says "I understand," "that sounds hard," "I'm sorry," responding to disclosed pain | Eyebrows raised + slightly furrowed (raise 0.4, furrow 0.3), eyes soft and slightly narrowed (softness 0.9), mouth closed, very slight downward corner (smile ≈ +0.3, i.e. not a full smile) — this is "concerned tenderness," not a smile |
| **Warm** | Greetings, default idle state | Eyebrows relaxed (raise 0.2, furrow 0), eyes gently open (softness 0.8), warm closed-mouth smile (smile 0.6) — the "resting kind face" |
| **Validating** | "That makes sense," "understandable," nodding agreement | Eyebrows raised + light furrow (raise 0.3, furrow 0.1), soft eyes (softness 0.8), gentle smile (smile 0.5) — between Empathetic and Warm, slightly more "affirming nod" energy |
| **Encouraging** | "You can do this," "keep going," lighter praise | Eyebrows raised (raise 0.5, furrow 0), open bright eyes (softness 0.4), warm open smile (smile 0.8, mouth slightly open) — more energy/brightness than Warm |

**Minimum viable fix:** split into at least 2 meshes — a *tender/concerned* face (Empathetic + Validating) and a *bright/warm* face (Warm + Encouraging). Full fix: 4 distinct meshes.

### `mininate calming.glb` / `mininate curious.glb` (currently identical to Empathetic)
| Logical state | When it fires | Target look |
|---|---|---|
| **Calming** | "Let's breathe," "ground yourself," responding to anxiety/panic | Brows relaxed, low furrow (raise 0.1, furrow 0), eyes soft and slightly lowered/heavy-lidded (openness 0.85, softness 0.9), closed mouth, gentle even smile (smile 0.4) — slow, settled, unhurried. Should read as "steady," visually calmer/slower than Warm. |
| **Curious** | Nate asks a question, chin-rest gesture | Brows raised high (raise 0.6, furrow 0), eyes wide and bright (openness 1.15, softness 0.3), mouth slightly open with light smile (openness 0.2, smile 0.4) — inquisitive, head slightly tilted if the rig supports it |

These two are emotionally opposite (calm/slow vs. alert/inquisitive) and must not share a mesh.

---

## Priority 2 — Currently indistinguishable, distress-critical (fix second — these are the client-mood-mirroring faces)

### `mininate sad.glb` / `mininate mad.glb` / `mininate proud.glb` (currently identical)
This bucket is the most therapeutically sensitive because it's what the client sees reflected back when they disclose real distress. A wrong or generic face here undermines trust.

| Logical state | When it fires | Target look |
|---|---|---|
| **Sad** | Client discloses grief/loss/crying; mirrors client's own sadness | Brows raised at inner corners + moderate furrow (raise 0.5, furrow 0.4 — the classic "worried/grief" brow), eyes softened and slightly lowered (softness 0.95), mouth closed with a slight downward curve (smile −0.3, narrower width 0.9). No teeth, no brightness. Should read as genuinely sorrowful, not neutral. |
| **Frustrated** | Mirrors client's own frustration/anger with understanding (not judgment) | Brows lowered and furrowed hard (raise 0.2, furrow 0.6 — the deepest furrow of any state), eyes slightly narrowed but alert (openness 1.05, softness 0.4), mouth tight/flat, very slight downward tension (smile −0.1). This must read as "taking your frustration seriously," not annoyed *at* the client — no gritted teeth, no aggressive eyes. |
| **Proud** | Celebrating a milestone/achievement | Brows raised (raise 0.4, furrow 0), eyes bright and open (openness 0.9, softness 0.7), big open genuine smile (smile 0.9, openness 0.4, width 1.2 — the widest, most open mouth of any state) | 

Sad, Frustrated, and Proud are emotionally as far apart as any three states in the whole set (grief / controlled anger / joy) — this is the most jarring of the current collapses and the highest-priority fix per the mood-mirroring feature.

---

## Priority 3 — Already unique, keep as reference

### `mininate neutral.glb`
Covers **Neutral**, **Attentive**, and **Thoughtful**. Currently the only mesh that's actually distinct from the others, so it's the de facto visual baseline. If budget only allows incremental work, use this file's construction as the style reference for the new meshes above.

| Logical state | When it fires | Target look (for consistency, not urgent to re-export) |
|---|---|---|
| **Neutral** | Default resting state | Brows flat (raise 0, furrow 0), eyes normal (openness 1.0, softness 0.5), closed mouth, very slight smile (smile 0.2) |
| **Attentive** | Client is actively speaking/listening | Brows slightly raised (raise 0.3), eyes wide open and alert (openness 1.1, softness 0.3), mouth barely open (openness 0.1) — "leaning in to listen" |
| **Thoughtful** | Nate is processing/"thinking" state | Brows lightly furrowed (raise 0.1, furrow 0.2), eyes slightly narrowed (openness 0.85, softness 0.6), closed mouth, faint smile (smile 0.1) — "considering" |

These three are close enough emotionally that sharing one mesh is an acceptable compromise if the artist's time is constrained — unlike the Priority 1/2 buckets, this is a defensible design choice, not a bug.

---

## Summary table — full re-export list (7 files → up to 12 distinct meshes)

| GLB file | States it must serve | # distinct meshes needed | Priority |
|---|---|---|---|
| `mininate neutral.glb` | neutral, attentive, thoughtful | 1 (already OK) or up to 3 | Low |
| `mininate empathetic.glb` | warm, empathetic, validating, encouraging | 2 minimum, 4 ideal | **P1** |
| `mininate calming.glb` | calming | 1 | **P1** |
| `mininate curious.glb` | curious | 1 | **P1** |
| `mininate sad.glb` | sad | 1 | **P2 (highest trust impact)** |
| `mininate mad.glb` | frustrated | 1 | **P2 (highest trust impact)** |
| `mininate proud.glb` | proud | 1 | **P2** |

**Absolute minimum viable re-export (7 meshes, one per existing file):** gets every file visually distinct from every other file. This alone fixes the "happy face for sad mood" bug.

**Recommended re-export (up to 12 meshes):** splits the empathetic/warm/validating/encouraging bucket and the neutral/attentive/thoughtful bucket, giving full fidelity to match the 2D fallback face's expression design (`mobile/lib/avatar.dart::ExpressionStateMachine`), which already has per-state mouth/eyebrow/eye parameters for all 12 states as a numeric reference.

---

## Technical notes for delivery

- Keep the exact filename convention: `mininate <name>.glb` (space, lowercase, `.glb`), URL-encoded as `mininate%20<name>.glb` in `mobile/lib/avatar.dart`.
- If new distinct files are added (e.g. splitting `empathetic` into `warm` + `empathetic`), flag it — `mobile/lib/avatar.dart::_expressionToGlb` needs a matching one-line update per new file, plus a deploy to `/var/www/sovereignsanctuary-web/avatar-modes/` on GREEN.
- Verify uniqueness before handoff: `sha256sum *.glb` — no two files should match unless intentionally sharing (per the Priority 3 exception above).
- Camera/lighting must match the existing rig (`cameraOrbit: 0deg 80deg 2.5m`, `fieldOfView: 30deg`) so expressions read correctly at the fixed viewing angle already in production.
