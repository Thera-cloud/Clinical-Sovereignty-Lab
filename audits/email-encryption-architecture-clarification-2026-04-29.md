# Email / PII Encryption — Architecture Clarification

**Date:** 2026-04-29 (UTC)  
**Status:** Documentation only (no data or code changes)  
**Relates to:** Sunday Readiness Security Audit 2026-04-29 — P1-1 (`users.email` / encryption expectations)  
**Phase 2 backfill:** **Not approved** — a naive Fernet-only backfill of `users.email` would break authentication and duplicate-detection paths that assume comparable plaintext (or consistent encoding) in the `email` column and registry.

---

## 1. Current architecture

| Component | Role |
|-----------|------|
| **`users.email`** | **Plaintext by design** for the operational column. Registration (`register_new_user` → `UserStore.upsert_user`) writes the raw address here. It is indexed and used in SQL predicates (e.g. `LOWER(email) = LOWER($1)`). Some rows may show Fernet-shaped strings (`gAAAAA…`) from historical or manual experiments; that is **inconsistent** with greenfield registrations, not the defined pgcrypto path. |
| **`users.email_enc`** | **pgcrypto ciphertext (BYTEA)** populated by **migration 105** triggers on INSERT/UPDATE of `email`. This is the **SQL-layer encrypted copy** of the same logical value. Decryption uses the PostgreSQL `decrypt_pii(bytea)` function with session variable **`app.pii_key`**, injected on pool connections via `db_encryption_middleware.py` (key chain: `PII_ENCRYPTION_KEY` → `FIELD_ENCRYPTION_KEY` → derived from `JWT_SECRET`). |
| **`users_secure` view** | Exposes `COALESCE(decrypt_pii(u.email_enc), u.email) AS email` (and analogous fields for name/dob). Intended for reads that need decrypted PII **when** `app.pii_key` is set. |
| **`users.pii_encrypted`** | Boolean from **migration 101**, documented as “Fernet at application layer.” **No application code in this repo updates this flag**; it remains default **`false`** for essentially all rows. It is **not a reliable security or compliance indicator** — treat as **unmaintained / decorative** unless a future migration or job owns it. |
| **`pii_cipher.py` (Fernet)** | **`encrypt_pii` / `decrypt_pii` / `is_encrypted`** use **`SKYEYE_TOKEN_ENCRYPTION_KEY`** and Fernet (AES-128-CBC + HMAC-SHA256). **`encrypt_pii` is not invoked on the registration write path** in current code. **`decrypt_pii`** is used on **some read/display paths** (e.g. admin profile presentation) so Fernet-shaped values in `users.email` or profile JSON do not render as raw blobs. This is **orthogonal** to migration 105 pgcrypto on `email_enc`. |

**Summary:** The **intended encryption-at-rest for email** in the PostgreSQL model is **pgcrypto on `email_enc`**, with **`users.email` retained as a working plaintext column** that feeds the trigger. Fernet in `pii_cipher.py` is **not** the primary write path for registration today.

---

## 2. Why the original audit finding was misleading

1. **Plaintext in `users.email` was flagged as the primary gap.** In the 105 architecture, **plaintext in `email` is expected** alongside **`email_enc`** holding the protected copy. Seeing readable addresses in `users.email` does not, by itself, mean “encryption was never applied” — **`email_enc` must be checked** (e.g. `encryption_coverage` / `COUNT(email_enc)`) for ciphertext presence.

2. **Mixed `gAAAAA…` vs cleartext in `users.email` is confusing but a different issue.** Fernet-shaped tokens in the **text** column indicate **application-layer Fernet** (same prefix as `pii_cipher`) on **some** rows, **not** pgcrypto. That inconsistency is **technical debt** and complicates any simple “encrypt everyone” backfill, because **auth and duplicate checks** may compare against plaintext expectations.

3. **`pii_encrypted = false` was read as “PII not encrypted.”** In practice the flag is **unused**; **do not** infer encryption state from it. Use **`email_enc`** and operational knowledge of migration 105 / backfill scripts instead.

---

## 3. Threat model (practical)

| Scenario | Impact |
|----------|--------|
| **Database dump / disk leak** | **`users.email` is readable** (plaintext for normal rows). **`email_enc`** is ciphertext without **`app.pii_key`** (or equivalent key material). Risk is **real for the `email` column** — this is the tradeoff of keeping a plaintext operational column. |
| **Backup leak** | Same as DB dump regarding **`users.email`**. |
| **DBA / privileged SQL** | Same — full visibility of **`users.email`**. |
| **Application-layer leak (API)** | **Heterogeneous.** Many code paths **`SELECT email FROM users`** and return or use that value directly. Code that uses **`users_secure`** with **`app.pii_key` set** gets decrypted logical email from **`email_enc`** with fallback to **`users.email`**. **Do not assume** all APIs funnel through **`users_secure`**; audit per endpoint before claiming “API always uses `email_enc`.” |
| **Process memory** | Plaintext email appears in memory during normal handling — **expected** for an operational column; not a distinct class from other request/session data. |

---

## 4. Remediation options (backlog only)

### OPTION A — Wire Fernet into registration writes

- Call **`encrypt_pii()`** on email before persisting (and align **`profile_data`**).
- Migrate existing rows to a **single** representation.
- **Audit every** email lookup, login, forgot-password, Stripe, and duplicate check to **`decrypt_pii()`** or use a stable comparison strategy.
- Reconcile **pgcrypto triggers** (they currently encrypt from **`NEW.email`**; Fernet ciphertext as trigger input changes semantics and must be designed explicitly).

**Estimate:** 1–2 weeks. **Risk:** **High** (authentication and billing touchpoints).

### OPTION B — Drop plaintext `users.email`

- After proving **`email_enc`** is complete and all readers use decryption or **`users_secure`**.
- Rewrite **all** queries and indexes that depend on **`users.email`**.

**Estimate:** 2–3 weeks. **Risk:** **Very high**.

### OPTION C — Accept and document current state

- Treat **`email_enc` + migration 105** as the **declared encryption layer** for email at rest in PostgreSQL, with **`users.email` as intentional operational plaintext**.
- **Deprecate or rename `pii_encrypted`** in documentation (or remove in a later migration **only** after product sign-off — out of scope here).
- Optionally schedule a **read-path audit**: which endpoints use raw **`users.email`** vs **`users_secure`**.

**Estimate:** ~2 hours (docs + inventory). **Risk:** **Low**.

---

## 5. Recommended path

| Horizon | Action |
|---------|--------|
| **Immediate** | **OPTION C** — Adopt this document as the **official architecture description**; stop using **`pii_encrypted`** as a compliance signal until it is owned by code. |
| **Sprint / quarterly** | Evaluate **OPTION A** vs **OPTION B** only with a full **email read/write inventory** and test plan (no “simple” column backfill). |

---

## 6. Sunday-readiness verdict

- This clarification **does not introduce a new P0**.
- **P1-1 in the Sunday audit** is **reclassified**: mixed **`users.email`** appearance reflects **designed plaintext column + optional Fernet-shaped legacy rows + pgcrypto on `email_enc`**, not an undocumented “missing encryption” in the sense of migration 105.
- **Fernet helper not used on registration writes** is **technical debt**, not proof of an **active** remote exploit path for Sunday traffic.
- **No emergency remediation** is required for launch solely on this item; treat remaining work as **backlog** under Options A/B.

---

## 7. References (read-only)

- `backend/migrations/105_pgcrypto_sql_encryption.sql` — triggers, `email_enc`, `users_secure`, `encryption_coverage`
- `backend/migrations/101_pii_encryption.sql` — `pii_encrypted`, `content_encrypted` flags
- `backend/app/services/db_encryption_middleware.py` — `app.pii_key` injection
- `backend/app/services/pii_cipher.py` — Fernet encrypt/decrypt (`SKYEYE_TOKEN_ENCRYPTION_KEY`)
- `backend/app/websocket/user_store.py` — `users.email` write path from registry
- `backend/scripts/backfill_pgcrypto_encryption.py` — bulk pgcrypto backfill pattern
