---
name: Family Linkage v2
overview: "Canonical family linkage across PostgreSQL, bridge registry, and family_members junction. Code deploy first, migration 196 last (single transaction). 33 gap/refinement items including dedupe-on-normalized-columns, junction_needs_sync gate, deletion-path audit, atomic invite claim, single billing guard, honest bridge line counts, real migration test, pre-existing invite redemption."
todos:
  - id: deletion-path-audit
    content: "EARLY: grep all user-delete / family_id-clear paths; add detach_user_from_family(conn, user_id); wire every hit (bridge remove, soft-delete ~24462, stripe_integration.remove_family_member, admin)"
    status: pending
  - id: threading-model-check
    content: "Confirm _family_invites + billing JSON are bridge in-process only (single event loop); if not, use Redis/DB claim for invites"
    status: pending
  - id: module-migration
    content: "family_linkage.py + 196 in BEGIN/COMMIT (backup, normalize, dedupe post-normalize, dup abort DO block, UNIQUE) + rollback drops constraint"
    status: pending
  - id: deploy-code-first
    content: "Deploy backend+bridge; same window run 196+195; HALT if any verify query non-zero"
    status: pending
  - id: user-store-sync
    content: "junction_needs_sync only (relationship drift + family_id drift); gated sync in user_store"
    status: pending
  - id: readers-fix
    content: "client_data_api, pgsd_handlers, widget_engine, ble_co_traveler, coherence/vault (conn-based, fail-closed 503)"
    status: pending
  - id: sse-writer-fix
    content: "family_engine UUID writers/readers; FAMILY_CACHE_VERSION Option A (passive cache key — document reconnect)"
    status: pending
  - id: defense-fix
    content: "hepa_filter relationship; family_data_guardian HoH-only secondary"
    status: pending
  - id: bridge-commit-a
    content: "bridge_server.py ≤50 measured lines: detach_user_from_family in remove path + parent_username ensure"
    status: pending
  - id: bridge-commit-b
    content: "bridge_server.py ≤50 measured lines: atomic invite claim + unconditional add_family_member_billing call"
    status: pending
  - id: billing-idempotency
    content: "stripe_billing.py ONLY guard inside add_family_member_billing (no bridge-side duplicate check)"
    status: pending
  - id: billing-rest
    content: "registration_finalize family_code + sync_family_member"
    status: pending
  - id: tests-verify
    content: "test_family_linkage.py applies real 196 SQL to seeded DB; verify_family_linkage.sh incl pre-deploy token redemption"
    status: pending
  - id: client-503-audit
    content: "Audit coherence/vault callers; Flutter 503 handling (human sign-off)"
    status: pending
isProject: false
---

# Family Linkage v2 — Durable Fix Package (Rev 3)

## Problem (current state)

| Layer | Format today | Canonical target |
|-------|----------------|------------------|
| `users.family_id` | UUID FK | UUID FK |
| `profile_data.family_id` / registry | `FAM_xxx` | `FAM_xxx` |
| `family_members.family_id` | mix `FAM_xxx` / UUID | **`users.family_id::text`** |
| `family_members.user_id` | username / hw_id / UUID | **`users.id::text`** |
| `family_members.relationship` | often null | **`head` / `spouse` / `member`** |

**Verified:** [register_new_user](backend/app/websocket/bridge_server.py) (~3531–3807) reads invites but does **not** consume/delete tokens; [lookup_family_invite](backend/app/websocket/bridge_server.py) (~25177) does not check `consumed`.

---

## Non-negotiables

- Do not modify `_ensure_hoh_family_id`, invite *generation*, or role/DOB shaping.
- Junction writes never fail parent saves (try/except + log).
- **Deploy code before migration 196** (same maintenance window, minutes apart).
- **bridge_server.py:** ≤50 lines **per commit, bridge file only** — measure in PR.
- Chat / Sanctuary unaffected.

---

## Rev 3 refinements (13 items) — must-fix highlighted

| # | Item | Fix |
|---|------|-----|
| **R1** | Dedupe on normalized columns | Dedupe **after** normalize steps 4–6; partition on final `family_id`, `user_id`. Pre-constraint `DO $$ … RAISE EXCEPTION` if any duplicate survives. |
| **R2** | Transaction wrap | Entire [196_normalize_family_members.sql](backend/migrations/196_normalize_family_members.sql) in `BEGIN; … COMMIT;`. No `CONCURRENTLY` / `VACUUM`. Confirm `psql -f` runs as one script (safe_deploy does not split). |
| **R3** | One gate function name | **`junction_needs_sync` only** — remove `membership_changed` / `junction_row_exists` as separate API. |
| **R4** | Relationship drift in gate | `junction_needs_sync` returns true if row missing, `family_id` mismatch, or **`relationship != expected_rel`**. |
| **R5** | Coverage query is hard stop | `uncovered` count **must be 0** post-migration; non-zero → **ABORT DEPLOY**, do not run verify script or smoke. |
| **R6** | Deletion-path audit | **Required early task** — grep all paths; centralize `detach_user_from_family(conn, user_id)`. See [Deletion-path audit](#deletion-path-audit-r6) below. |
| **R7** | Atomic invite claim | Set `consumed=True` **before** await-heavy signup; rollback on failure; `lookup_family_invite` rejects `consumed`. **Confirm threading model first.** |
| **R8** | Single billing guard | **Only** inside [stripe_billing.py](backend/app/websocket/stripe_billing.py) `add_family_member_billing`; bridge calls unconditionally. |
| **R9** | Honest commit counts | Count **bridge_server.py lines only** per commit; split if >50; stripe_billing in separate commit. |
| **R10** | Pre-existing invite redemption | Capture real pending token pre-deploy; post-deploy redeem in [verify_family_linkage.sh](backend/scripts/verify_family_linkage.sh); defensive defaults in lookup. |
| **R11** | SSE cache honesty | **Option A (chosen):** `FAMILY_CACHE_VERSION` in cache key only — open SSE streams stay stale until reconnect. Document explicitly; no fake "auto refresh". |
| **R12** | Rollback drops constraint | Rollback comment includes `DROP CONSTRAINT IF EXISTS uq_family_members_family_user` before restore. |
| **R13** | Migration test runs real SQL | Test applies full migration file to seeded DB — not parse-only. |

**Must-fix before deploy:** R1, R2, R6, R13, plus R7/R8 after threading-model confirmation.

---

## Deletion-path audit (R6)

**Implement early** — before bridge commits. Central helper in [family_linkage.py](backend/app/services/family_linkage.py):

```python
async def detach_user_from_family(conn, user_id) -> bool:
    """FK null + junction delete by users.id. Returns False if user not found."""
    await conn.execute("UPDATE users SET family_id = NULL WHERE id = $1", user_id)
    await remove_family_member_junction_by_user_id(conn, user_id)
    return True
```

**Grep targets (initial hits — implementer must confirm each):**

| Location | Path | Action needed |
|----------|------|---------------|
| [bridge_server.py](backend/app/websocket/bridge_server.py) ~20800 | `remove_family_member` | Replace ad-hoc SQL with `detach_user_from_family` |
| [bridge_server.py](backend/app/websocket/bridge_server.py) ~24462, ~24857 | Soft delete (`deleted_at = NOW()`) | Call `detach_user_from_family` before/after soft delete |
| [stripe_billing.py](backend/app/websocket/stripe_billing.py) | `remove_family_member_billing` | Ensure junction + FK cleared (may only clear billing today) |
| [stripe_integration.py](backend/app/services/stripe_integration.py) ~1054 | `remove_family_member` | Wire detach helper |
| Admin / GDPR | [data_export.py](backend/app/routers/data_export.py), admin delete handlers | Audit — any account purge must detach |

**Deliverable:** checklist in PR description listing every hit and whether `detach_user_from_family` is wired.

---

## Threading model check (R7, R8)

**Assumption to verify before deploy:**

- `_family_invites` lives in bridge in-memory `registry` (JSON backup) — **single bridge process**, asyncio event loop.
- `billing["family_members"]` in [stripe_billing.py](backend/app/websocket/stripe_billing.py) is file-backed JSON loaded per call — **not multi-process safe** without file lock.

**If confirmed single-threaded per bridge:** R7 sync claim + R8 in-function guard suffice.

**If multi-worker / shared registry:** invite claim needs Redis key `invite:claim:{token}` or PG row; billing needs true upsert or file lock.

---

## Step 1 — Shared module

**File:** [backend/app/services/family_linkage.py](backend/app/services/family_linkage.py)

| Function | Notes |
|----------|-------|
| `resolve_family_keys(conn, fam_str)` | UUID or `FAM_xxx` |
| `resolve_user_keys(conn, identifier)` | id, username, hardware_id, family_id, family_role, name |
| `family_role_to_relationship(role, is_minor=False)` | HEAD→head, SPOUSE→spouse, DEPENDENT→member |
| `display_name_from_profile(...)` | name → preferred_name → users.name → username |
| `junction_needs_sync(conn, username, family_uuid, profile) -> bool` | **Single gate** (R3, R4) |
| `sync_family_member(conn, username)` | `ON CONFLICT (family_id, user_id) DO UPDATE` |
| `remove_family_member_junction_by_user_id(conn, user_id)` | DELETE by id::text |
| `detach_user_from_family(conn, user_id)` | FK null + junction delete (R6) |
| `user_in_family(conn, identifier, family_uuid)` | No raw token UUID cast |
| `load_family_member_user_ids(conn, fam_str)` | users/families join (dual-format reads) |

**`junction_needs_sync` (R4):**

```python
async def junction_needs_sync(conn, username, family_uuid, profile) -> bool:
    keys = await resolve_user_keys(conn, username)
    if not keys or not keys.get("id"):
        return False
    expected_rel = family_role_to_relationship(
        profile.get("family_role"), profile.get("is_minor", False)
    )
    row = await conn.fetchrow(
        "SELECT family_id, relationship FROM family_members WHERE user_id = $1",
        str(keys["id"]),
    )
    if row is None:
        return True
    if row["family_id"] != str(family_uuid):
        return True
    if row["relationship"] != expected_rel:
        return True
    return False
```

---

## Step 2 — Migration 196 (after code deploy, single transaction)

**File:** [backend/migrations/196_normalize_family_members.sql](backend/migrations/196_normalize_family_members.sql)

```sql
BEGIN;

-- Backup (transactional)
DROP TABLE IF EXISTS family_members_backup_196;
CREATE TABLE family_members_backup_196 AS SELECT * FROM family_members;

-- 2. Orphan REPORT (SELECT only — review in logs)
-- 3. Orphan DELETE
-- 4. Normalize family_id (FAM_xxx → families.id::text)
-- 5. Normalize user_id (username/hw_id → users.id::text)
-- 6. Backfill relationship from profile_data.family_role

-- 7. Dedupe on NORMALIZED columns (R1)
WITH ranked AS (
  SELECT ctid,
    ROW_NUMBER() OVER (
      PARTITION BY family_id, user_id
      ORDER BY (relationship IS NOT NULL) DESC, added_at DESC NULLS LAST
    ) AS rn
  FROM family_members
)
DELETE FROM family_members fm USING ranked r
WHERE fm.ctid = r.ctid AND r.rn > 1;

-- Hard abort if duplicates remain (R1)
DO $$
DECLARE dup_count int;
BEGIN
  SELECT COUNT(*) INTO dup_count FROM (
    SELECT family_id, user_id FROM family_members
    GROUP BY family_id, user_id HAVING COUNT(*) > 1
  ) d;
  IF dup_count > 0 THEN
    RAISE EXCEPTION 'Migration 196 abort: % residual duplicate junction rows', dup_count;
  END IF;
END $$;

ALTER TABLE family_members
  ADD CONSTRAINT uq_family_members_family_user UNIQUE (family_id, user_id);

COMMIT;
```

**Rollback (R12):**

```sql
-- ROLLBACK (manual):
--   ALTER TABLE family_members DROP CONSTRAINT IF EXISTS uq_family_members_family_user;
--   TRUNCATE family_members;
--   INSERT INTO family_members SELECT * FROM family_members_backup_196;
```

**Then:** re-run [195_backfill_family_members.sql](backend/migrations/195_backfill_family_members.sql).

**Verify block — HALT deploy if any non-zero (R5):**

```sql
-- Wrong-family junction (expect 0)
SELECT COUNT(*) FROM family_members fm
JOIN users u ON fm.user_id = u.id::text
WHERE u.family_id IS NOT NULL AND fm.family_id <> u.family_id::text;

-- FAM_ prefix in junction (expect 0)
SELECT COUNT(*) FROM family_members WHERE family_id LIKE 'FAM_%';

-- Orphans (expect 0)
SELECT COUNT(*) FROM family_members fm
WHERE NOT EXISTS (SELECT 1 FROM users u WHERE fm.user_id = u.id::text);

-- Coverage (expect 0) — ABORT DEPLOY if non-zero
SELECT COUNT(*) AS uncovered FROM users u
WHERE u.family_id IS NOT NULL AND u.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM family_members fm
    WHERE fm.user_id = u.id::text AND fm.family_id = u.family_id::text
  );
```

**Deploy rule:** Step 6 verify → if `uncovered > 0`, **stop**. Do not run `verify_family_linkage.sh` or production smoke.

---

## Step 3 — Readers/writers (deploy before 196)

### 3a — Gated sync ([user_store.py](backend/app/websocket/user_store.py))

```python
if family_uuid:
    try:
        if await junction_needs_sync(conn, username, family_uuid, profile):
            await sync_family_member(conn, username)
    except Exception as e:
        logger.warning("family_linkage: sync failed for %s: %s", username, e)
```

### 3b–3g — Unchanged from Rev 2

- [client_data_api.py](backend/app/routers/client_data_api.py) pending invites
- [pgsd_handlers.py](backend/app/websocket/pgsd_handlers.py) users/families load
- [family_engine.py](backend/app/sse/family_engine.py) UUID writers; **Option A** cache version (R11)
- [widget_engine.py](backend/app/sse/widget_engine.py), [ble_co_traveler.py](backend/app/sse/ble_co_traveler.py)
- [coherence_api.py](backend/app/routers/coherence_api.py), [legacy_vault_api.py](backend/app/routers/legacy_vault_api.py) fail-closed 503
- [hepa_filter.py](backend/app/services/hepa_filter.py), [family_data_guardian.py](backend/app/services/family_data_guardian.py) HoH-only secondary

---

## Step 4 — Bridge commits (R9: measure bridge lines only)

### Commit A — [bridge_server.py](backend/app/websocket/bridge_server.py) ≤50 lines

- `remove_family_member`: call `detach_user_from_family(conn, user_id)` in transaction (via user_id from hardware_id)
- `register_new_user` ~3522: `_ensure_hoh_family_id` when `parent_username` without invite
- **PR must state measured line count**

### Commit B — [bridge_server.py](backend/app/websocket/bridge_server.py) ≤50 lines

**Atomic invite claim (R7):**

```python
# Before await-heavy signup work
invite = registry.get("_family_invites", {}).get(invite_code)
if not invite or invite.get("consumed"):
    return False, "INVITE_INVALID"
invite["consumed"] = True
try:
    # ... register, save_registry_async ...
    del registry["_family_invites"][invite_code]
    await save_registry_async(...)
    if _is_family_member:
        await billing_system.add_family_member_billing(...)  # no bridge-side guard (R8)
except Exception:
    invite["consumed"] = False
    raise
```

**lookup_family_invite (~25177):** reject `invite.get("consumed")`, expired; defensive `invite.get("consumed", False)` for legacy tokens (R10).

### Separate commit — [stripe_billing.py](backend/app/websocket/stripe_billing.py) (not counted toward bridge 50)

**Single idempotency guard (R8):**

```python
async def add_family_member_billing(self, head_user_id, member_user_id, ...):
    billing = self._load_billing()
    existing = billing.get("family_members", {}).get(member_user_id)
    if existing and existing.get("status") == "active":
        logger.info("billing: %s already active, no-op", member_user_id)
        return existing
    # ... create record ...
```

---

## Step 5 — REST parity

[registration_finalize.py](backend/app/services/registration_finalize.py): `family_code` in profile + `sync_family_member` in txn.

---

## Step 6 — Tests + verification

### Unit tests (R13 — real SQL)

```python
async def test_migration_196_normalizes_fixture(test_db_conn):
    # Seed: FAM_xxx family_id, username user_id, duplicate pair, orphan, null relationship
    sql = pathlib.Path("backend/migrations/196_normalize_family_members.sql").read_text()
    await test_db_conn.execute(sql)  # confirm harness supports BEGIN/COMMIT multi-statement
    assert 0 orphans, 0 FAM_%, 0 dups, constraint exists
```

Also: removal+detach, non-member `user_in_family`, billing idempotency (double call returns same record).

### [verify_family_linkage.sh](backend/scripts/verify_family_linkage.sh) (R10)

1. **Pre-deploy:** capture `PREEXISTING_TOKEN` from real pending invite
2. Post-deploy: redeem pre-existing token → signup succeeds
3. Assert junction UUID keys, token removed, **one** billing record
4. Synthetic new invite path (same assertions)
5. Cleanup test users

---

## Deploy sequence (GREEN)

```text
0. EARLY: deletion-path audit complete (R6); threading model confirmed (R7/R8)
1. git pull origin main
2. safe_deploy.sh backend
3. safe_deploy.sh bridge
4. psql -f 196_normalize_family_members.sql   # single transaction
5. psql -f 195_backfill_family_members.sql
6. Run verify SQL — ALL must be 0 (R5 HALT rule)
7. verify_family_linkage.sh (incl PREEXISTING_TOKEN) — REQUIRED
8. Smoke: Coach Command, Settings invites, PGSD, chat
9. Release note: SSE Option A — clients reconnect for fresh family constellation
```

---

## Commit structure (R9)

1. `feat: family_linkage module + migration 196 (transactional)`
2. `fix: readers/writers + junction_needs_sync gate`
3. `fix: coherence/vault + hepa/guardian + detach_user_from_family`
4. `fix: bridge commit A` — **≤50 bridge lines measured**
5. `fix: bridge commit B` — **≤50 bridge lines measured**
6. `fix: stripe_billing idempotency only` (separate from bridge count)
7. `fix: registration_finalize parity`
8. `test: real migration 196 + verify_family_linkage.sh`
9. **Ops:** 196 + 195 same window as steps 2–3

---

## Prior gap fixes (Rev 1–2) — still in force

Items 1–20 from Rev 2 remain unless superseded above. Key supersessions:

- Dedupe → **R1** (post-normalize + abort DO block)
- Gate naming → **R3/R4** (`junction_needs_sync` only + relationship drift)
- Billing → **R8** (stripe only, not bridge)
- Invite → **R7** (atomic claim, not post-success delete only)
- SSE → **R11** (Option A explicit)
- Migration test → **R13** (apply real SQL)

---

## Human sign-off

1. Guardian: HoH-only secondary (no spouse)
2. Coherence/vault 503 caller audit
3. Lineage deferred to v2.1
4. **SSE Option A:** accept stale in-flight streams until manual reconnect
5. **Threading model** for invites/billing confirmed single-process

---

## Out of scope (v2.1)

- [197_normalize_lineage.sql](backend/migrations/197_normalize_lineage.sql)
- SSE Option B (`family_refresh` push event)
- Flutter 503 UI (audit only)
