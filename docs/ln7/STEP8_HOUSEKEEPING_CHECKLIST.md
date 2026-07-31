# Step 8 — One-hour housekeeping sweep

## 8.1 — Memory containment (ORANGE PEFT)

- [x] Drop-in on ORANGE: `MemoryMax=22G` / `MemoryHigh=20G` (peak was **20.3G**; 18G would OOM)
- [x] `systemctl daemon-reload` — PEFT left **stopped** (post-canary spindown / CEO hold)
- [ ] Restart only when next canary authorized

## 8.2 — DigitalOcean account audit (2026-07-31)

- [x] Droplets: primary, clone, sandbox (178.128…), small sfo2 — **no GPU bakeoff orphans**
- [x] Volumes: `volume-sfo2-01` attached to primary only

## 8.3 — Cursor budget check

- [ ] Operator: Cursor Settings → Usage before live `ln7_bakeoff` bus work

## 8.4 — Incident archive

- [x] `docs/ln7/INCIDENT_SEAMS_1_TO_7_CLOSED.md` published
- [x] Autopsy header present: `docs/ln7/ATTEMPT6_AUTOPSY.md`
- [ ] M2 registry ingest of baseline JSON (later — not blocking)

## Post-sweep verify (GREEN)

- [ ] Apply mig `314_ln7_fuel_gauge.sql`
- [ ] Deploy Steps 6–8; `Ln7OpsScheduler` in STARTUP COMPLETE
- [x] Offline: bakeoff regression + dry bus + fuel/health guards PASS
