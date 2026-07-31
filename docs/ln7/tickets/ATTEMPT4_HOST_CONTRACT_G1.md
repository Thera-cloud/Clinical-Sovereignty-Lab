# Ticket: Attempt 4 host-role contract → G1

**Filed:** 2026-07-31  
**Status:** engineering complete; paid droplet gated  
**Related:** `~/.local/state/ln7_gpu_watch/ATTEMPT4_AMENDMENT_20260731.txt`

## Amendment (authoritative)

Authorization: **one** Attempt 4. Attempt 5 has no remaining content.

Centerpiece: host-role contract (pattern fix for seams 1–7).

| Role | Meaning |
|---|---|
| `LN7_AUTH_BASE` | HTTP to backend (local curl/docker on GREEN; never SSH-to-self) |
| `LN7_ORCH_HOST` | Where scripts run (`blue` \| `green`) |
| `LN7_BURST_SSH` | `root@$DROPLET_IP` from handoff only — never inherited from `GREEN_HOST` |

Preconditions (droplet last):

1. Amendment written before any paid provision.
2. Host-role contract on `main` (fail-closed loopback).
3. Topology matrix dry-run green (BLUE-orch + GREEN-orch, $0 GPU).
4. Destroy self-test green (second destroy + 404; never ANOMALY-then-exit on billing).
5. Default: GREEN orch SSHes **only** the droplet; compare via local `AUTH_BASE`.
6. Paid droplet **only** after ≥300 organic G1 rows **and** reviewed host-contract on `main` **and** `LN7_BURST_ALLOW_PAID=1`.

Fail clause: park. Re-entry = ≥300 organic rows + reviewed patch. No attempt 5.

## Code

- `scripts/ln7_host_roles.sh`
- `scripts/ln7_host_roles_preflight.sh`
- `scripts/ln7_binary_audit_preflight.sh`
- Wired: `ln7_hive_burst.sh`, `ln7_ab_bakeoff_compare.sh`, `ln7_destroy_cuda_droplet.sh`
- Fence: `frozen-config/fence_tests/test_host_role_contract.py`

## G1 path (this ticket)

1. Host-contract + fence test committed.
2. Binary-audit preflight PASS.
3. Penny destroy rehearsal (fake id → 404 verified-gone).
4. This amendment filed to ticket (this file).
5. G1 wired with `ENABLE_LN7_AUTO_PROMOTE=false` and `DUAL_COO_MECHANICAL_PROMOTE=false`.
6. CI green (flywheel + fence + host-roles).
7. One verified `shadow_outcome` with `oracle=ci_pack`.
8. Flip **G1** (`LN7_G1_OPEN=true`) — **not** G2 weld keys.

## Verification (GREEN 2026-07-31)

| Check | Result |
|---|---|
| Commit on `main` / GREEN HEAD | `3e5c6cdc` (+ prove script follow-up) |
| Binary audit | `BINARY_AUDIT_PREFLIGHT=PASS` |
| Penny destroy (fake id `999999999`) | verified-gone **404** after attempt 1 |
| Flags before flip | `LN7_G1_OPEN=f`, `ENABLE_LN7_AUTO_PROMOTE=f`, `DUAL_COO_MECHANICAL_PROMOTE=f` |
| Shadow row | `patch_hash=g1_verified_shadow_20260731_host_contract` `oracle=ci_pack` `passed=true` envelope `fd1c3c4a-ee44-4195-82c9-3b53bd1ed963` |
| After flip | `LN7_G1_OPEN=t`; G2 weld keys still **false** |

Prove helper: `backend/scripts/ln7_g1_shadow_prove.py`
