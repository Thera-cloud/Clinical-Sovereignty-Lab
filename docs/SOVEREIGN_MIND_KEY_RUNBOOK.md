# Sovereign Mind master key — mini runbook

**Purpose:** Document where the Ed25519 Sovereign Mind (master) key is loaded at backend startup, operational guardrails, and the **known gap** (no rotation / re-sign path yet).

**Scope:** Read-only reference aligned with `backend/app/main.py` (loader) and `backend/app/services/identity_chain.py` (API). Do not treat this file as a substitute for implemented rotation code.

---

## When this applies

Swarm identity chain setup runs only when **`ENABLE_SOVEREIGN_SWARM`** is true (see app settings). If swarm is disabled, the loader block in `main.py` is skipped.

---

## Key source (priority order)

Loader logic in **`backend/app/main.py`** (Sovereign Swarm init block):

1. **Environment / settings — `SOVEREIGN_MIND_MASTER_KEY`**  
   - If non-empty: PEM string is passed to `IdentityChainService.load_master_key(...)`.

2. **Fallback file — `data/sovereign_master_key.pem`**  
   - Resolved as: `os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sovereign_master_key.pem")`  
   - With `__file__` = `backend/app/main.py`, that is the **`backend/data/`** directory next to `backend/app/`, i.e. repo path **`backend/data/sovereign_master_key.pem`**.

3. **Generate new key**  
   - If env is empty and the file is missing: `IdentityChainService.initialize_master_key()` returns a new PEM; startup then tries to create the directory, write the file, and **`chmod 0o600`** on the PEM.

---

## Identity chain service (reference only)

**Class:** `IdentityChainService` in **`backend/app/services/identity_chain.py`**

| Method | Role |
|--------|------|
| `load_master_key(private_key_pem: str)` | Load Sovereign Mind private key from PEM string |
| `initialize_master_key()` | Generate new keypair; returns private PEM |

Fibre identities are created with `create_fibre_identity`; the master signs each fibre public key. Existing rows are loaded via `load_identities_from_db()` (queries `fibres.public_key` / `identity_signature`).

---

## Known gap — rotation not implemented

**Location:** `backend/app/services/identity_chain.py` — module-level **TODO(L4)** (~line 37).

**Implication:** There is **no** supported procedure in code to rotate the master key, re-sign all fibre identities, and migrate in-flight trust chains. The design today assumes a **long-lived** master key.

**Tracked in:** `docs/OPEN_TODOS.md` (Active table).

---

## Operational hygiene (today)

- **Backup** `backend/data/sovereign_master_key.pem` (or the vault copy behind `SOVEREIGN_MIND_MASTER_KEY`) using your standard secret-handling process. Losing it after fibres are issued may require re-issuing identities.
- **Never commit** the PEM to git; verify `.gitignore` covers `backend/data/*.pem` if used locally.
- **Permissions:** Prefer `0600` on disk (startup sets this when it writes the file).
- **Docker / deploy:** Ensure the path containing the PEM is on a **persistent volume** if you rely on the file fallback; otherwise a recreated container may generate a **new** key and invalidate prior signatures.

---

## Future rotation (not yet shipped — outline only)

When engineering implements L4 rotation, expect roughly:

1. Introduce a new master key (or dual-trust window).
2. Re-sign or re-issue every fibre identity (`create_fibre_identity` / DB updates).
3. Verify chains with `verify_chain` against the active root(s).
4. Document cutover and rollback; update this `docs/SOVEREIGN_MIND_KEY_RUNBOOK.md` with the real procedure.

Until then, treat master key changes as **high-risk** and coordinate with whoever owns swarm / fibres data.

---

## Quick reference

| Item | Value |
|------|--------|
| Settings / env key | `SOVEREIGN_MIND_MASTER_KEY` |
| Default PEM file (repo-relative) | `backend/data/sovereign_master_key.pem` |
| Load method | `IdentityChainService.load_master_key` |
| Generate method | `IdentityChainService.initialize_master_key` |

**Loader implementation:** `backend/app/main.py` — search for `IdentityChainService` / `SOVEREIGN_MIND_MASTER_KEY` / `sovereign_master_key.pem`.
