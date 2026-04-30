# Open TODOs — Single Source of Truth

**Established:** 2026-04-30
**Maintenance rule:** All future open items go HERE. Do not add to 
historical checklists or .cursor/plans/.

---

## Active

| Item | Category | Severity | File:Line | Added |
|---|---|---|---|---|
| Sovereign Mind master key rotation procedure unimplemented | SECURITY | MEDIUM | backend/app/services/identity_chain.py:37 | 2026-04-30 |
| _Awaiting reconciliation report from comprehensive checklist audit_ | — | — | — | 2026-04-30 |

## Deferred (acknowledged, not actionable now)

[empty initially]

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

A reconciliation pass on 2026-04-30 will extract any STILL OPEN 
items from these files into this Active table.
