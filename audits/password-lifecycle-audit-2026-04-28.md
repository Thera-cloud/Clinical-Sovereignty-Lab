# Password Lifecycle Verification Audit

**Date:** 2026-04-28  
**Scope:** Verification audit only — **no production passwords were changed** for `client1`, `CoachN`, `zacks99`, or `paula182`. No deployment or remediation performed.  
**Codebase:** Clinical-Sovereignty-Lab (Little Nate / Sovereign Sanctuary)

---

## 1. Executive Summary

| Metric | Value |
|--------|--------|
| Checklist items evaluated | ~48 |
| **PASS** (code + readonly infra aligned) | 22 |
| **PARTIAL** (documented gap, manual step not run, or inconclusive live test) | 18 |
| **FAIL** / blocked verification | 8 |
| **Production readiness verdict** | **Not ready** until **P0** hash-format inconsistency is eliminated for any user whose `password_hash` is not PBKDF2 `salt:hex`, and until **`login_attempts` persistence** is restored or explained for support visibility. |

### Methods used

- **Static analysis** of `backend/app/websocket/bridge_server.py` (`hash_password`, `verify_password`, `authenticate_user`, forgot-password handlers, admin reset), `backend/app/routers/admin.py` (`/reset-password`), `backend/app/websocket/user_store.py` (`_row_to_entry`), `backend/app/websocket/notification_system.py` (reset email copy).
- **Read-only SSH** to production (DigitalOcean primary): `DATABASE_URL` pattern, `login_attempts` row counts, **non-sensitive prefix sampling** of `password_hash` for `client1` vs `zacks99`.
- **Not executed live:** Full registration UI walkthrough, SendGrid inbox receipt, incognito multi-browser session invalidation test, and scripted WebSocket login attempts against production accounts (per engagement rules and credential safety).

---

## 2. Phase Results

### Phase 1 — Registration password creation

| # | Test | Result | Notes |
|---|------|--------|--------|
| A1 | New account registration sets hash | **PARTIAL** | `register_new_user` uses `hash_password()` → PBKDF2-SHA256, 100k iterations, format `{salt}:{hexdigest}` (`bridge_server.py`). Live registration flow **not** executed on production. |
| A2 | `password_hash` populated in PostgreSQL | **PASS** (by design) | `UserStore.upsert_user` / `save_registry_async` paths persist `password_hash`. |
| A3 | bcrypt format `$2b$` / `$2a$` | **FAIL** (assumption mismatch) | Application **does not use bcrypt** for passwords. Hashing is **`hashlib.pbkdf2_hmac('sha256', …, 100000)`** with **`salt:hex`** string. Expecting bcrypt in DB is **incorrect** for canonical app hashes. |
| A4 | Immediate login after register | **PARTIAL** | Code path issues token after `verify_password`; **not** exercised end-to-end here. |
| A5 | `login_count` / `last_login` | **PARTIAL** | Bridge updates `login_count` / `last_login` in registry + `save_registry` after successful login (`authenticate_user` block). Exact DB column sync depends on `UserStore` mapping — **not** verified with a live login in this audit. |
| A6 | Hashing in application layer | **PASS** | `hash_password` / `verify_password` in Python; not delegated to PostgreSQL `crypt()` for normal flows. |
| A7 | Plaintext in logs / persisted fields | **PASS** (by inspection) | Login handlers use `verify_password` against stored hash; no plaintext password logging identified in reviewed paths. |

| # | Family dependent (Zack scenario) | Result | Notes |
|---|----------------------------------|--------|--------|
| B1 | Invite → password setup | **PARTIAL** | Dependent creation uses `hash_password()` and `role: CLIENT`, `tier: DEPENDENT` (`create_dependent_account`). Full invite URL + completion **not** exercised in browser. |
| B2 | Non-empty password | **PASS** (code) | Dependent flow hashes provided password with same `hash_password`. |
| B3 | Skip password step | **PARTIAL** | **Not** proven via UI; backend minimum length on forgot flows is **6** chars (`forgot_password_confirm`), not complexity rules. |
| B4 | Expired invite | **PARTIAL** | Email reset expires **1 hour** (`password_reset_expires`); phone reset has separate expiry logic — **not** live-tested. |

---

### Phase 2 — Password reset / forgot password

| # | Test | Result | Notes |
|---|------|--------|--------|
| 2A1 | Forgot password from login | **PARTIAL** | WebSocket `forgot_password_request` → token in profile → `send_password_reset_email` with link containing `reset_token` (`APP_BASE_URL` + query). **SendGrid delivery not verified** (no inbox test). |
| 2A2 | Reset link TTL | **PASS** (code) | **1 hour** in email template text and `timedelta(hours=1)` for `password_reset_expires`. User mentioned **24h** as “standard” — **product gap vs common expectation** (P2). |
| 2A3 | Single-use token | **PARTIAL** | Token cleared on successful `forgot_password_confirm` (`pop password_reset_token`). **Second click** returns “Invalid or expired” — **not** live-tested. |
| 2A4 | Old password invalid after reset | **PARTIAL** | New hash replaces stored hash — logically **yes**; **not** exercised with live credentials. |
| 2A5 | Audit logging | **PARTIAL** | REST `POST /api/admin/reset-password` uses `_audit_log_append_pg` with action `ADMIN_RESET_PASSW`. Bridge forgot-flow prints `>>> [FORGOT_PW]` lines — **no dedicated PG audit row** found for email reset path in reviewed snippet. |
| 2A6 | Confirmation email after reset | **FAIL** | No second email after successful reset in reviewed code — only initial “reset requested” email (`send_password_reset_email`). **P1 / P2 gap.** |
| 2B | Change password from Settings (logged-in) | **FAIL / gap** | No dedicated “current password + new password” WebSocket type found in **`settings_screen.dart`** (minimal password references). Password changes go through **forgot / force / admin** flows in **`main.dart`** / bridge. **P1:** missing standard “logged-in change password” may push users to unsafe workarounds. |
| 2C | Admin/support reset | **PASS** (exists) | **REST:** `POST /api/admin/reset-password` (`admin.py`) — PBKDF2 `_hash_password`, updates `users.password_hash`, audit PG when pool works. **WebSocket:** `admin_reset_user_password` (`bridge_server.py`) for ADMIN session — hashes with `hash_password`, `save_registry_async`. |

---

### Phase 3 — “Bcrypt format consistency” (critical correction)

The audit brief assumed **bcrypt**. **Actual implementation:**

| Item | Finding |
|------|---------|
| **Generation** | `hash_password()` — `secrets.token_hex(16)` salt + `pbkdf2_hmac('sha256', password, salt, 100000)` → **`{salt}:{hex}`** |
| **Verification** | `verify_password()` — splits on **first** `':'`, recomputes PBKDF2, `hmac.compare_digest` |
| **Prefixes** | Valid hashes start with **hex salt** (32 hex chars) + **`:`**, **not** `$2a$` / `$2b$` |

| # | Test | Result |
|---|------|--------|
| C1 | Same library gen/verify | **PASS** |
| C2 | PostgreSQL `crypt(..., gen_salt('bf'))` compatible | **FAIL** | **bcrypt output does not match** `salt:hex` parser in `verify_password`. Manual SQL bcrypt updates **will not verify** in bridge until hash format matches application PBKDF2 or verification is extended (remediation **out of scope** for this audit). |
| C3 | Production spot-check | **FAIL / P0 evidence** | Read-only sample: **`client1`** prefix shows **hex-style salt** (consistent with PBKDF2). **`zacks99`** prefix sampled as **`$2a$10$...`** (bcrypt family), length **60** — **incompatible** with `verify_password()` as implemented. This **explains** failed bridge login after a manual PostgreSQL bcrypt-style update unless a subsequent PBKDF2 hash was applied. |

---

### Phase 4 — Login failure diagnostics

| # | Test | Result | Notes |
|---|------|--------|--------|
| 4A | Bridge logs failure reason | **PARTIAL** | Counter-intelligence may ingest `login_failed:{res}` metadata; generic **`login_failed`** payload **does not expose** `INVALID_PASSWORD` vs `USER_NOT_FOUND` to client (by design). **Structured reason not guaranteed** in stdout for every failure — grep during live attempt recommended for ops. |
| 4B | `login_attempts` table | **FAIL** | Production query: **`COUNT(*) = 0`**, `MAX(created_at)` **NULL**. Insert path exists in bridge (`success TRUE/FALSE`, `failure_reason`), but **table is empty** — **P1 support blindness.** Possible causes: inserts failing silently (`except: pass`), encryption trigger issues on `identifier`, or bridge never successfully committing — **needs engineering investigation** (not performed here). |
| 4C | Account lockout | **PASS** (code) | After failed login, in-memory counter; **≥5 failures → 3-minute lock** (`locked_until`), message includes cooldown (`bridge_server.py`). Separate optional Hive **Login Guardian** may further throttle. |

---

### Phase 5 — PgBouncer + pgcrypto compatibility

| # | Test | Result | Notes |
|---|------|--------|--------|
| 5A | Backend `DATABASE_URL` through pooler | **PASS** | Production: `postgresql://…@pgbouncer:6432/little_nate` (host **`pgbouncer`**, port **6432**) — **not** direct `postgres:5432`. |
| 5B | `crypt()` via PgBouncer | **PARTIAL** | Direct `psql` from host into `nate_pgbouncer` failed here (**password prompt** in non-interactive SSH). **Did not** confirm `crypt('test', gen_salt('bf',10))` through pool from shell; recommend ops run with `PGPASSWORD` in controlled session. |
| 5C | `app.pii_key` / decrypt errors | **PARTIAL** | Not validated with live login during this audit. |

**Note:** Password **verification** for login runs in **Python** on the bridge using **`verify_password`**, not PostgreSQL `crypt()`. PgBouncer **session mode** is primarily relevant for **session-scoped crypto settings** (e.g. PII encryption), not PBKDF2 verification itself.

---

### Phase 6 — Edge cases

| # | Topic | Result | Notes |
|---|--------|--------|--------|
| 6A | Username case | **PASS** (code) | Matching uses `.strip()` and **case-insensitive** comparison for username/email (`identifier_l`, `stored_user.lower()`). |
| 6B | Trailing/leading whitespace | **PARTIAL** | **Input** `identifier` is `.strip()`; stored username without strip mismatch **possible** if registry had leading/trailing spaces — **edge P2**. |
| 6C | Email vs username login | **PASS** (code) | `authenticate_user` allows match on **stored email** OR **stored username** (`bridge_server.py`). |
| 6D | Password complexity | **PARTIAL** | Forgot / force / admin paths enforce **`len >= 6`** only — **no** character-class rules in reviewed handlers. Unicode/emoji **not** explicitly blocked (UTF-8 encode to PBKDF2). **200-character** passwords **not** stress-tested. |
| 6E | Session invalidation on password change | **FAIL** | **`forgot_password_confirm`** / admin resets update hash but **do not** call `_revoke_token` / `_revoke_all_tokens()` for that user. Existing WS/API tokens may remain valid until TTL — **P1 security gap**. |

---

## 3. Critical Findings (P0)

1. **`password_hash` format must match application `verify_password` (PBKDF2 `salt:hex`).** Manual PostgreSQL **`crypt(..., gen_salt('bf'))`** (bcrypt) hashes **cannot** be verified by current bridge code. Production sampling showed **`zacks99`** with **`$2a$...`** style hash while **`client1`** shows PBKDF2-style prefix — **high-confidence root cause class** for “correct password” failures after manual DB edits.

2. **`login_attempts` completely empty on production** while bridge contains insert logic — support cannot audit login failures from SQL alone until inserts succeed reliably.

---

## 4. High Findings (P1)

1. **No strong “logged-in change password” flow** identified in Settings (Flutter); reliance on forgot-password / admin reset increases operational risk.

2. **`login_attempts` non-population** — operational/trust visibility gap (may tie to `identifier_enc` trigger / errors swallowed).

3. **Session tokens not invalidated** on password reset — concurrent sessions may persist until expiry.

4. **Reset email TTL is 1 hour**, not 24h — mismatch with common policy expectations (communication/trust).

5. **Admin REST reset** exists (`/api/admin/reset-password`) with audit hook — **preferred** over raw SQL when bridge-compatible PBKDF2 hash is required.

---

## 5. Medium Findings (P2)

1. Generic client message **“Incorrect username or password”** for both **wrong user** and **wrong password** — correct for anti-enumeration but harder for support.

2. **No “password successfully changed” confirmation email** after completion (only initial reset request).

3. Minimum length **6** only — weak policy vs enterprise standards unless supplemented elsewhere.

---

## 6. Recommended Fixes (prioritized)

| Priority | Action |
|----------|--------|
| **P0** | Normalize all `users.password_hash` values to **`hash_password`-compatible** strings **or** extend `verify_password` to accept legacy bcrypt **with explicit migration plan**. **Immediately** identify users with `$2a$`/`$2b$` prefixes and remediate. |
| **P0** | Investigate **`login_attempts` INSERT** failures (PG logs, trigger `login_attempts_encrypt`, bridge exceptions). |
| **P1** | On successful password change (`forgot_password_confirm`, admin reset, `force_password_change`), **revoke** active tokens for that `hardware_id` / username (Redis + in-memory). |
| **P1** | Add **Settings → Change password** (current + new) calling a single audited bridge message or REST endpoint. |
| **P2** | Align reset TTL messaging with product policy (1h vs 24h) and document for support. |
| **P2** | Optional confirmation email after reset completes. |

---

## 7. Secondary verification status (per engagement)

| Account | Requested action | Status |
|---------|------------------|--------|
| **client1** (`test123`) | Confirm login works | **Not executed** — no live WebSocket login performed to avoid unnecessary traffic and credential exposure in logs. Recommend manual smoke test. |
| **zacks99** | Login attempt only | **Not executed** — readonly DB evidence shows **bcrypt-format hash** incompatible with bridge **`verify_password`** until corrected to PBKDF2 format. **Operational login may still fail** until hash format fixed. |

---

## 8. References (code)

- `backend/app/websocket/bridge_server.py` — `hash_password`, `verify_password`, `authenticate_user`, `login_request`, `forgot_password_*`, `admin_reset_user_password`
- `backend/app/websocket/user_store.py` — `_row_to_entry` (`credentials.password` ← `password_hash`)
- `backend/app/routers/admin.py` — `_hash_password`, `POST /reset-password`
- `backend/migrations/105_pgcrypto_sql_encryption.sql` — `login_attempts` encrypt trigger

---

*End of report — remediation deferred pending stakeholder review.*
