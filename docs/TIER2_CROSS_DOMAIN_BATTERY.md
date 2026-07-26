# Tier 2 Cross-Domain Battery (Design Spike)

**Status:** kickoff / substrate — **not** Narrow AGI certification.

## Domains

| Domain | Surface examples | LIVE_CONTEXT (AQ focus) |
|--------|------------------|-------------------------|
| therapy | `bridge_chat`, TTC | allowed |
| family | Family Sanctuary | **blocked** |
| dojo | DOJO mentor / Zoom | **blocked** |
| voice | Twilio voice pipeline | **blocked** |
| ops | Queen / truth-bound ops | **blocked** |

## Privacy wall

1. **No cross-member user-crystal recall** — `recall_crystals_for_context` resolves to one UUID and queries `user_id = that UUID` for user-scoped rows. Family injects per-member slots; never merge peer user_ids into one query.
2. **No clinical `live_focus` bleed** — `get_live_addendum(..., surface=)` allowlist is `{bridge_chat, therapy}` only.
3. **PGSD briefing** may appear on family/private/group/voice behind `ENABLE_PGSD_ACCESS`; that is correlation briefing, not six-quotient LIVE_CONTEXT.

## Scoreboard

- **v0:** `pgsd_cross_domain_agreement` (ACCESS refresh).
- **v1 stub:** `tier2_domain_eval_runs` (migration 284) — designed/running/scored rows; no Sunday auto-act expansion.

## Code

- Scaffold: `backend/app/services/tier2_cross_domain_battery.py`
- Offline privacy: `backend/tests/test_tier2_privacy_walls.py`
- Checklist: Track E.4 / E.5 in `docs/AGENTIC_ROLLOUT_CHECKLIST.md`
