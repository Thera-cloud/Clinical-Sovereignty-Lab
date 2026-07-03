# Open TODOs — Single Source of Truth

**Established:** 2026-04-30
**Maintenance rule:** All future open items go HERE. Do not add to 
historical checklists or .cursor/plans/.

---

## Active

| Item | Category | Severity | File:Line | Added |
|---|---|---|---|---|
| Coach Classroom WebSocket error leaves UI stuck (analyzing flag never resets) | UX | HIGH | mobile/lib/updated_screens.dart:6725 | 2026-04-30 |
| Sovereign Mind master key rotation procedure unimplemented | SECURITY | MEDIUM | backend/app/services/identity_chain.py:37 | 2026-04-30 |
| Wire lived wisdom extraction on sanctuary_complete to Night School | FEATURE | MEDIUM | backend/app/websocket/bridge_server.py:26814 + lived_wisdom.py | 2026-04-30 |
| Exit feeling_scale capture + Nevedal C_emo delta | FEATURE | MEDIUM | backend/app/websocket/bridge_server.py + sanctuary_engine | 2026-04-30 |
| Coach notification when sanctuary needs_review (beyond flag) | UX | MEDIUM | backend/app/websocket/bridge_server.py:27017 | 2026-04-30 |
| Avatar Mode GLB assets: only 3 unique meshes exist across 7 expression files. `sad.glb`/`mad.glb`/`proud.glb` are byte-identical (sha256 `8e83c06a...`); `calming.glb`/`curious.glb`/`empathetic.glb` are also byte-identical (sha256 `47ab3545...`). Client-mood mirroring logic correctly selects the file per mood, but the rendered face doesn't visually change for sad/mad/proud or calming/curious/empathetic — needs re-export of 7 distinct meshes by 3D asset owner. Verified on GREEN `/var/www/sovereignsanctuary-web/avatar-modes/*.glb`. | 3D ASSET | HIGH | mobile/lib/avatar.dart (GlbAvatarWidget expression map) | 2026-07-03 |

## Deferred (acknowledged, not actionable now)

| Item | Category | Severity | Location | Notes |
|---|---|---|---|---|
| The Eye sanctuary effectiveness dashboard + wisdom analytics | FEATURE | LOW | dashboard/the_eye.html | Product scoping needed |
| Edge firmware scaffolding (fragment reassembly, mesh routing, OTA) | INFRA | LOW | edge/ | Pending ZEFCP ship |
| SSE / Sovereign Command remaining media pipeline | FEATURE | LOW | backend/app/sse/ + studio | Large product scope |
| Manual UX/QA verification of feature checklist items | QA | LOW | UX_AUDIT_FEATURE_CHECKLIST.md | Needs device QA session |

## Done (kept for traceability, prune quarterly)

[empty initially]

---

## Process

**Adding an item:**
1. Identify category: SECURITY / BUG / FEATURE / UX / DOC / INFRA
2. Set severity: CRITICAL / HIGH / MEDIUM / LOW
3. Add row to Active table with file:line and date
4. Commit with message: `todos: add <one-line summary>`

**Closing an item:**
1. Move row from Active to Done with completion commit hash
2. Or move to Deferred with one-sentence reason
3. Commit with message: `todos: close <one-line summary>`

**Pruning:**
- Done items older than 90 days can be deleted
- Deferred items reviewed quarterly

---

## Historical checklists (DO NOT ADD TO)

These contain pre-2026-04-30 todos and are kept read-only for 
historical reference. New items go in the Active table above, not 
into these files:

- docs/LITTLE_NATE_PROGRESS_CHECKLIST_UPDATED.md
- docs/LITTLE_NATE_LIVED_WISDOM_CHECKLIST.md
- UX_AUDIT_KNOWN_ISSUES.md
- UX_AUDIT_FEATURE_CHECKLIST.md
- docs/INTEGRATION_GUIDE.md (audit checklist portion only)
- docs/AUDIT_CLIENT_PORTAL_SETTINGS.md
- docs/FULL_STACK_CHECKLIST_V4.md
- docs/MOBILE_APP_UX_FLOW_TREE_V1.md
- docs/FAMILY_SANCTUARY_AUDIT_CHARGES_VAULT_IAP.md
- edge/README.md (TODO section only)
- .cursor/plans/ (entire directory — historical planning)

A reconciliation pass on 2026-04-30 extracted high-value STILL OPEN 
items into the Active and Deferred tables above.
