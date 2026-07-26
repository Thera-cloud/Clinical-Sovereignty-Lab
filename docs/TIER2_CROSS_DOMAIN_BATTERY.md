# Tier 2 Cross-Domain Battery

**Status:** scored pack runner (`tier2_pack_v1`) — certify via `clinical_tier2_narrow_agi_gate_check.py`.

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
- **v1:** `tier2_domain_eval_runs` via `run_pack()` / `backend/scripts/tier2_run_domain_battery.py`.

## Code

- Runner: `backend/app/services/tier2_cross_domain_battery.py` → `run_pack`
- Coach REST: `backend/app/routers/pgsd_coach_api.py`
- Flutter: `mobile/lib/screens/coach_pgsd_screen.dart` (Briefings → PGSD)
- Gate: `backend/scripts/clinical_tier2_narrow_agi_gate_check.py`
- FIELD / Patent 12: `ENABLE_PGSD_FIELD` + `patent/PATENT_PROVISIONAL_12_QUANTUM_EMOTIONAL_FIELD.md` (container mirror: `backend/assets/patent/`)
- Certify: `python /app/scripts/clinical_tier2_narrow_agi_gate_check.py` → **GREEN 2026-07-26** (pack `tier2-20260726T143926Z-9121f1e0`)

```bash
docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \
  python /app/scripts/tier2_run_domain_battery.py CLIENT_LETSGOLISA_ID
```
