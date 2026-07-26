# Tier 2 Cross-Domain Battery

**Status:** `tier2_pack_v2` — strict `surface_hits≥1` (override: `TIER2_REQUIRE_SURFACE_HITS=false`).

## Domains

| Domain | Surface examples | LIVE_CONTEXT (AQ focus) |
|--------|------------------|-------------------------|
| therapy | `bridge_chat`, TTC | allowed |
| family | Family Sanctuary | **blocked** |
| dojo | DOJO mentor / Zoom | **blocked** |
| voice | Twilio voice pipeline | **blocked** |
| ops | Queen / truth-bound ops | **blocked** |

## Privacy wall

1. **No cross-member user-crystal recall** — per-member UUID scoping only.
2. **No clinical `live_focus` bleed** — allowlist `{bridge_chat, therapy}` only.
3. **PGSD briefing** may appear on family/private/group/voice behind `ENABLE_PGSD_ACCESS`.

## Scoreboard

- **v0:** `pgsd_cross_domain_agreement`
- **v2:** `tier2_domain_eval_runs` via `run_pack` / `run_multi_family_pack`

## Ops

```bash
# Single subject
docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \
  python /app/scripts/tier2_run_domain_battery.py CLIENT_LETSGOLISA_ID

# Multi-family (≥2 subjects)
docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \
  python /app/scripts/tier2_run_domain_battery.py --multi HW_A HW_B

# Coach REST E2E smoke
SKYEYE_AUDIT_TOKEN=... python backend/scripts/tier2_coach_pgsd_e2e_smoke.py CLIENT_LETSGOLISA_ID

# Gate (harden)
docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \
  python /app/scripts/clinical_tier2_narrow_agi_gate_check.py
```

## Code

- Runner: `backend/app/services/tier2_cross_domain_battery.py`
- Coach REST: `backend/app/routers/pgsd_coach_api.py`
- Flutter: `mobile/lib/screens/coach_pgsd_screen.dart`
- Queen FIELD CLI: `query_pgsd_wells`, `query_pgsd_ground_state`
- Patent 12: **FILING-READY** `patent/PATENT_PROVISIONAL_12_QUANTUM_EMOTIONAL_FIELD.md`
- Helix: `ENABLE_PGSD_HELIX_HINT=true` (compose + clinical/TENSION pin)
