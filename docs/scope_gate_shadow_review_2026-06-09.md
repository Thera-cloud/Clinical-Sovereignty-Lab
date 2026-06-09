# Scope-gate shadow review — 48h window

**Review owner:** Eng + Ops  
**Clinical sign-off:** Pending — **global flag flip HELD**  
**Plan:** `.cursor/plans/coaching_scope_gate_plan.md` steps 2–4

---

## Decision gate (do not flip flags until all PASS)

| Gate | Status |
|------|--------|
| SSH passphrase rotated | **Operator action** — see `docs/SECURITY_SSH_PASSPHRASE_ROTATION_2026-06-09.md` |
| `>>> [SCOPE_GATE]` mirror deployed on GREEN | Pending deploy (this commit) |
| 48h post-mirror log review complete | **IN PROGRESS** — window opens at bridge restart below |
| Staging / pilot 3–5 sessions | Not started |
| Clinical + product sign-off | Not started |
| Ticket `SCOPE_GATE_LOCK_PERSISTENCE` | Open |
| Ticket `CHAT_HISTORY_WITHIN_SESSION_REPAIR` | Open |
| `ENABLE_COACHING_SCOPE_GATE` / `ENABLE_CLASSIFIER_LAYER` / `ENABLE_ARC_MEMORY` global true | **HELD** |

---

## Phase 0 — Pre-mirror baseline (GREEN, 2026-06-09 ~03:21 UTC)

**Env:** `printenv ENABLE_*` empty → code defaults **false**.

| Metric (48h `docker logs nate_bridge`) | Count | Notes |
|----------------------------------------|------:|-------|
| `[SCOPE_GATE]` (logger.info) | **0** | INFO not in docker logs — review blocked |
| `>>> [SCOPE_GATE] direct_response fired` | **0** | Expected with flag off |
| `>>> [ARC]` | **12** | All `CLIENT_LETSGOLISA_ID` |
| `>>> [ARC] … triggered=True` | **≥4** | 4- and 6-domain breadth |
| `scope gate FIRED` | **0** | `ENABLE_ARC_MEMORY` off |
| `>>> [CLASSIFIER] disagreements` | **4** | Lisa turns 3 & 7 — regex/classifier drift |

**Classifier disagreements (Lisa):**

- Turn 3: `classifier_action_request_regex_no_mismatch`, `regex_sees_dissatisfaction_classifier_missed`
- Turn 7: `classifier_sees_dissatisfaction_regex_missed` (×2 in tail)

**Conclusion (Phase 0):** Detection counterfactuals exist (ARC/classifier); scope-gate shadow **not observable**; **no user-facing stabilization**.

---

## Phase 1 — Mirror deploy

**Change:** `little_nate_adaptive.py` prints `>>> [SCOPE_GATE] … would_fire=…` alongside logger.info.

**Compose:** `docker-compose.prod.yml` bridge `environment:`

```yaml
ENABLE_COACHING_SCOPE_GATE=${ENABLE_COACHING_SCOPE_GATE:-false}
ENABLE_CLASSIFIER_LAYER=${ENABLE_CLASSIFIER_LAYER:-false}
ENABLE_ARC_MEMORY=${ENABLE_ARC_MEMORY:-false}
```

**Deploy (GREEN, after `git push origin main`):**

```bash
cd /opt/clinical-sovereignty-lab && git pull origin main && bash scripts/safe_deploy.sh bridge
```

**Post-deploy verify (immediate):**

```bash
docker exec nate_bridge printenv ENABLE_COACHING_SCOPE_GATE ENABLE_CLASSIFIER_LAYER ENABLE_ARC_MEMORY
# Expected: false false false

docker exec nate_bridge grep -c '>>> \[SCOPE_GATE\]' /app/app/services/little_nate_adaptive.py
# Expected: >= 1 (print mirror present)

docker logs nate_bridge --since 10m 2>&1 | grep '>>> \[SCOPE_GATE\]' | tail -5
# Expected: >0 lines after any client chat turn
```

**48h window start (UTC):** _Record bridge container start time after deploy:_ `docker inspect -f '{{.State.StartedAt}}' nate_bridge`

**48h window end (UTC):** _Start + 48 hours_

---

## Phase 2 — 48h review commands (run at window end)

```bash
SINCE=48h
docker logs nate_bridge --since $SINCE 2>&1 | grep -c '>>> \[SCOPE_GATE\]'
docker logs nate_bridge --since $SINCE 2>&1 | grep '>>> \[SCOPE_GATE\].*would_fire=True' | wc -l
docker logs nate_bridge --since $SINCE 2>&1 | grep '>>> \[SCOPE_GATE\].*multi_topic_clinical_opening' | wc -l
docker logs nate_bridge --since $SINCE 2>&1 | grep '>>> \[SCOPE_GATE\].*scope_gate_continuation' | wc -l
docker logs nate_bridge --since $SINCE 2>&1 | grep '>>> \[SCOPE_GATE\].*would_fire=True' | grep -o 'uid=[^ ]*' | sort -u
docker logs nate_bridge --since $SINCE 2>&1 | grep '>>> \[ARC\].*triggered=True' | wc -l
docker logs nate_bridge --since $SINCE 2>&1 | grep 'disagreements' | wc -l
docker logs nate_bridge --since $SINCE 2>&1 | grep 'direct_response fired' | wc -l
# Last line must stay 0 until intentional flag flip
```

### Pass criteria (step 2)

- `>>> [SCOPE_GATE]` count **> 0** (mirror working).
- `would_fire=True` on dense openings; **silent** on obvious single-topic work-stress-only sessions (manual spot-check uids).
- `direct_response fired` **= 0** while flags false.
- No sustained `would_fire=True` on `domains=1` ARC-only noise without scope groups (spot-check).

### Fail / hold flip if

- Mirror count still 0 after client traffic.
- `would_fire=True` rate looks like >X% of all chat turns (set X with clinical after first 48h — suggest review if >15% without dense-session explanation).
- Classifier disagreements cluster on dissatisfaction without plan follow-up.

---

## Phase 2 results (fill at T+48h)

| Metric | Value | PASS? |
|--------|------:|:-----:|
| `>>> [SCOPE_GATE]` total | | |
| `would_fire=True` | | |
| `multi_topic_clinical_opening` in labels | | |
| `scope_gate_continuation` in labels | | |
| Unique uids with `would_fire=True` | | |
| `>>> [ARC] triggered=True` | | |
| Classifier disagreements | | |
| `direct_response fired` | | must be 0 |

**Reviewer:** _______________  **Date (UTC):** _______________

**Clinical sign-off:** _______________  **Date:** _______________

---

## References

- Tickets: `docs/tickets/SCOPE_GATE_LOCK_PERSISTENCE.md`, `docs/tickets/CHAT_HISTORY_WITHIN_SESSION_REPAIR.md`
- Acceptance harness: `docs/40_turn_acceptance_2026-05-18_r3.md` (flags on, local only)
