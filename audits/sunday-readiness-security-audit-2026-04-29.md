# Sunday Readiness Security Audit — Sovereign Sanctuary

**Date:** 2026-04-29 (UTC)  
**Type:** Read-only release-gate review (no code or config changes)  
**Scope:** Public surface, auth/session posture, PII, billing/webhooks, family/minor (policy + schema), admin exposure, dependency scan (attempted), radio-show/regulatory notes  
**Assessor:** Automated + SSH evidence from primary production host where noted  

> **Clarification (2026-04-29):** P1 finding on plaintext **`users.email`** is **reclassified as architectural debt**, not a Sunday launch-blocker. The platform’s intended SQL-layer protection is **pgcrypto on `users.email_enc`** (migration 105); **`users.email`** is an operational plaintext column by design; **`pii_encrypted`** is unmaintained. A naive Fernet-only column backfill would break auth. See **`audits/email-encryption-architecture-clarification-2026-04-29.md`**.

---

## 1. Executive Summary

| Severity | Count (this pass) |
|----------|-------------------|
| **P0 — Critical** | 0 confirmed |
| **P1 — High** | 3 |
| **P2 — Medium** | 6 |
| **P3 — Low / informational** | 5 |

**Sunday-launch verdict: GO WITH FIXES**

No evidence in this pass of live **authentication bypass**, **unauthenticated admin API access**, **billing webhook acceptance without verification**, or **PostgreSQL/Redis exposed on the public internet** on the sampled clone host. **`users.email`** visibility in a DB/backup leak remains a **breach‑magnitude** concern (plaintext operational column); **ciphertext for email at rest** is **`users.email_enc`** (migration 105), per **`email-encryption-architecture-clarification-2026-04-29.md`**.

**Top 3 risks**

1. **PII / `users.email` (reclassified)** — **Architectural debt + residual risk**, not a missing encryption layer in the sense of migration 105. Plaintext **`users.email`** coexists with **pgcrypto `email_enc`**; Fernet-shaped values in **`email`** on some rows reflect **application inconsistency**, not the primary 105 design. See clarification doc above. **P1-1** text below retained for audit trail; **verdict:** not a Sunday blocker; backlog Options A–C documented in clarification.
2. **Dependency CVEs** — **Phase 7 complete** (**§10**); **targeted remediation applied 2026-04-29** (**§11**): backend + bridge images rebuilt with **aiohttp ≥3.13.4**, **starlette ≥0.49.1**, **FastAPI 0.125.x**, **PyJWT ≥2.12**, **pypdf 6.10.2**, **Pillow ≥12.2**, **orjson ≥3.11.6**. **MEDIUM** and residual **GHSA-only** rows remain **backlog** (pytest, python-dotenv, scikit-learn, etc.).
3. **CSP uses `'unsafe-inline'` and `'unsafe-eval'`** on api/app/command vhosts — common for legacy dashboards but **weakens XSS containment** if any stored/reflected XSS appears in HTML/JS.

---

## 2. P0 Findings — Critical

**None confirmed** during read-only checks:

- Unauthenticated access to `/api/admin/*` (sample returned **403** without bearer).
- Unauthenticated SkyEye pulse path (sample **403**).
- Stripe main webhook without valid signature: **`POST /api/billing/webhook`** returned **400** for empty body and for fake `Stripe-Signature` (rejects; aligns with `construct_event` / WebhookFortress path in code).
- Clone VPS (**159.65.108.25**): only **22, 80, 443** open from external probe; **5432, 6379, 11434, 8100** not observed open (slow scan on other IPs; primary in-browser path is Cloudflare → nginx).

---

## 3. P1 Findings — High

### P1-1: `users.email` mixed plaintext / encrypted; `pii_encrypted` often false

**Reclassification (2026-04-29):** **Architectural debt — not a Sunday blocker.** Threat model, `email_enc` as the SQL encryption layer, unmaintained `pii_encrypted`, and why naive Fernet backfill breaks auth are documented in **`audits/email-encryption-architecture-clarification-2026-04-29.md`**.

**Evidence (read-only SQL on production):**

```text
 username  | email_preview               | pii_encrypted 
-----------+-----------------------------+---------------
 LetsGoLisa| gAAAAABpwT8dqqagP01WHpsA... | f
 paula182  | pswain811@gmail.com         | f
 client1   | gAAAAABpwyRnPBbYxJ9zqdvZ... | f
```

**Risk (original framing):** Backup leak / insider / SQLi still exposes **`users.email`** as stored (often plaintext). **`users.email_enc`** is the migration‑105 ciphertext column; **`pii_encrypted`** is not authoritative.

**Reproduction:** `SELECT username, LEFT(email,40), pii_encrypted FROM users WHERE email IS NOT NULL LIMIT 3;`

**Fix direction (post-audit):** See **`audits/email-encryption-architecture-clarification-2026-04-29.md`** — Options A–C; **immediate path: document (Option C)**; no emergency Fernet column backfill.

---

### P1-2: Phase 7 dependency audit — **completed 2026-04-29** (see §10)

**Evidence:** `pip-audit -r /app/requirements-light.txt` executed inside production `nate_backend`; findings summarized in **§10 Phase 7 Completion** (NVD CVSS v3.1 enrichment for severity).

**Risk (historical — pre-patch):** CRITICAL/HIGH issues were present in **aiohttp**, **PyJWT**, **pypdf**, **Pillow**, **starlette**, and **orjson** until requirements were bumped.

**Fix (applied 2026-04-29):** Coordinated upgrades deployed per **§11** (backend `requirements-light.txt` + bridge `requirements.txt`, images rebuilt, smoke/regression checks passed).

---

### P1-3: Content-Security-Policy allows inline script and eval

**Evidence (nginx excerpts on primary host):** `script-src 'self' 'unsafe-inline' 'unsafe-eval'` on api/app/command server blocks.

**Risk:** Increases blast radius of any XSS or widget injection.

**Fix:** Long-term CSP tightening (nonces/hashes)—**backlog** unless XSS is suspected.

---

## 4. P2 Findings — Medium

| ID | Finding |
|----|--------|
| P2-1 | **Cloudflare edge on `api.sovereignsanctuary.net`:** Sample `HEAD`/`GET` responses show **fewer** security headers than origin nginx config lists (e.g. HSTS/CSP may not apply to all paths or methods). **Verify** `GET https://api.sovereignsanctuary.net/` vs `/health` with full header capture. |
| P2-2 | **`app.sovereignsanctuary.net`:** Static asset locations use `Access-Control-Allow-Origin: *` for GET—acceptable for public assets; ensure **no credentials** on those URLs (expected). |
| P2-3 | **`command.sovereignsanctuary.net`:** CORS uses `Access-Control-Allow-Origin $http_origin` with `Allow-Credentials: true` on API proxy paths—**normal for SPA+bearer**; risk is **mis-reflected Origin** if nginx map is wrong. Spot-check `OPTIONS` preflight from arbitrary Origin (post-audit). |
| P2-4 | **SSH 0.0.0.0:22** on primary—expected; ensure **key-only**, `Fail2Ban`, and no password auth for root. |
| P2-5 | **Twilio webhook** code path logs **WARNING** if auth token missing—confirm token always set in prod (defense in depth). |
| P2-6 | **Primary external port scan from audit runner** to **68.183.168.75**: all tested ports **closed/filtered** from Cursor sandbox (likely Cloudflare-only exposure for web, or firewall). **Do not over-interpret**—internal `ss` on host shows **127.0.0.1:8000, :8765** for app traffic (good). |

---

## 5. P3 Findings — Low / Informational

| ID | Finding |
|----|--------|
| P3-1 | DNS split: **app/coach/command** → **68.183.168.75** direct; **api/root/www/pwa** → **Cloudflare Anycast**—consistent with LB architecture. |
| P3-2 | TLS on **api.sovereignsanctuary.net**: cert **Google WE1**, **TLS 1.2 + 1.3** supported, modern ciphers observed (`CHACHA20-POLY1305` / `AES_256_GCM`). |
| P3-3 | **Billing `/subscription/upgrade`:** Code review: requires **ADMIN or COACH** and ownership check (`billing.py`). Matches prior “Stripe audit fix” intent—**clients should get 403**. |
| P3-4 | Backend logs **7d** sample: **no** matches for `grep -iE '@.*\.com|password=|ssn|credit_card'` (empty—good hygiene for that pattern set). |
| P3-5 | **Webhook idempotency:** Code shows `webhook_events` insert / fortress path—good for replay **within** Stripe semantics; still depends on Stripe timestamp + secrets (documented in code). |

---

## 6. Phase-by-Phase Results

### Phase 1 — Public attack surface

**A) DNS (sample 2026-04-29)**

| Host | A record observation |
|------|----------------------|
| sovereignsanctuary.net | Cloudflare (104.26.x / 172.67.x) |
| www, pwa | Cloudflare |
| api | Cloudflare |
| app, coach, command | **68.183.168.75** (origin-direct) |

**B) Ports (evidence)**

- **Primary host `ss`:** Public: **80, 443, 22, 8766, 3001, 8001**; app backends **127.0.0.1:8000, 127.0.0.1:8765, 127.0.0.1:3000**.
- **Clone 159.65.108.25 external nc:** **22, 80, 443** only (no DB/Redis in sample).
- **Hetzner / mirror:** Scan not completed in log window; assume **non-public** DB per architecture rules unless re-probed.

**C) nginx / TLS**

- Origin nginx adds **HSTS (preload), X-Frame-Options, nosniff, Referrer-Policy, CSP** on **api**, **app**, **command** vhosts (excerpted from `/etc/nginx/sites-enabled/*`).
- Cloudflare-terminated responses may differ by path (see P2-1).

**D) Rate limiting**

- **Not load-tested** (per engagement rules). Middleware exists in codebase (`webhook_rate_limit`); brute-force on login not hammered.

**E) WebSocket**

- Curl HTTP/2 upgrade to `/ws` returned **426** / protocol quirks—**browser uses WSS through nginx**; unauthenticated socket typically connects then **must send `login_request`** (per platform design). **No unauthenticated data exfiltration proven** in this pass.

---

### Phase 2 — Authentication & session

- **Admin REST without token:** **403** on sampled paths—not open.
- **JWT deep manipulation:** Not exercised (would require capturing tokens—out of scope).
- **User enumeration / timing:** Not measured (avoid noisy prod probes).

---

### Phase 3 — PII & data exposure

- **DB:** See **P1-1** (`users.email`). `\d users` shows plaintext `email`, `name`, `phone`, `dob` columns—encryption may be partial or legacy.
- **Logs:** See P3-4.
- **Errors:** Not systematically fuzzed (avoid user impact).

---

### Phase 4 — Billing

- **Stripe webhook path:** **`POST /api/billing/webhook`** (prefix `/api/billing`).
- **Invalid / missing signature:** **400** responses (good).
- **Free upgrade:** Staff-gated in code review (`role in ADMIN/COACH` + ownership).

---

### Phase 5 — Family & minor

- **Schema:** `is_minor`, `guardian_id`, `family_id` present on `users`.
- **Behavioral tests:** Not executed (would need controlled accounts—document only). **Crisis API exfil** not probed without auth.

---

### Phase 6 — Admin exposure

- Sample unauthenticated admin API: **403**.
- Dashboard HTML loads **without** API token; **data** requires WebSocket login + bridge token / REST bearer (per architecture). SkyEye “Wisdom widget” not broken by this audit.

---

### Phase 7 — Dependencies

- **Completed 2026-04-29** — **§10 Phase 7** (`pip-audit` in `nate_backend` + NVD severity pass).

---

### Phase 8 — Radio / regulatory / press

- **988 / disclaimers:** `dashboard/privacy.html` includes **988**, **NOT licensed therapist**, crisis language—**good** if this page is linked from app store / signup flows (spot-check live `privacy.html` host).
- **Journalist fake distress:** Product/clinical assessment—not security; ensure crisis pathways and logging exist (existing platform behavior).
- **Minor signup:** `is_minor` exists; **enforce parental consent in UX/backend**—verify in dedicated compliance review (not executed here).

---

## 7. Recommended Pre-Sunday Fixes (ordered)

| Priority | Action | Est. | Regression risk |
|----------|--------|------|------------------|
| 1 | **Reconcile `users.email` encryption** — inventory plaintext rows, plan encrypt/backfill or document waiver | 4–24h eng + DBA | Medium (triggers, app reads) |
| 2 | **`pip-audit` CRITICAL/HIGH (six runtime packages + FastAPI/starlette)** — **DONE** (§11); follow-up for MEDIUM backlog | 1–4h | Low–medium |
| 3 | **Verify Cloudflare vs origin headers** on `api` for HSTS/CSP on all HTML/error routes | 1–2h | Low |
| 4 | **CORS spot-check** on command dashboard for reflected Origin | 1h | Low |
| 5 | **SSH posture audit** (password auth off, keys only) | <1h | Low |

---

## 8. Acceptance Criteria for Sunday Launch

**Must fix before Sunday (if leadership agrees with severity):**

- None **mandatory** from **P0** list (empty)—**P1-1 email encryption posture** is the strongest “organizational risk” item; technical launch can proceed if accepted as **known debt** with executive sign-off.

**Can be accepted as known risk (documented):**

- CSP with `unsafe-inline` / `unsafe-eval` until refactor.
- Residual **MEDIUM** / non-target dependency work remains **backlog** (§10 + §11.4); **CRITICAL + listed HIGHs** for the six runtime packages are **addressed** in **§11**.

---

## 9. Evidence Log (commands / paths)

| Check | Result snippet |
|-------|----------------|
| DNS dig | app/coach/command → 68.183.168.75; api → Cloudflare |
| `ss -tlnp` (primary) | 127.0.0.1:8000, 127.0.0.1:8765; public 80/443 |
| `curl` admin | 403 without auth |
| `POST /api/billing/webhook` | 400 without valid Stripe signature |
| `users` email sample | Mixed plaintext / `gAAAAA` tokens |
| nginx headers | HSTS, CSP, XFO on vhost files |
| TLS openssl | TLS1.2/1.3, cert until 2026-06-16 |
| Backend log grep 7d | No PII pattern hits in sample |
| Clone ports | 22,80,443 open only |
| `pip-audit` (Phase 7) | 52 findings / 9 packages; see §10 |

---

## 10. Phase 7 Completion — Python dependency scan (`pip-audit`)

**When:** 2026-04-29 (UTC)  
**Where:** `docker exec nate_backend …` on primary production host (`nate_backend` image, Python 3.11).  
**Scope:** `pip-audit` pip-install in container, then `pip-audit -r /app/requirements-light.txt` (resolves the same pins the backend image installs from).  
**Packages changed (historical note):** Original Phase 7 run was scanner-only; **§11** records the **post-audit** dependency pins applied to production images.  

### 10.1 pip-audit summary

| Metric | Value |
|--------|-------|
| **Total vulnerability rows reported** | **52** |
| **Distinct packages with ≥1 hit** | **9** (`aiohttp`, `orjson`, `pillow`, `pypdf`, `pyjwt`, `pytest`, `python-dotenv`, `scikit-learn`, `starlette`) |
| **Exit code** | Non-zero (expected when vulnerabilities exist) |

### 10.2 Severity enrichment (NIST NVD, CVSS v3.1)

`pip-audit` text output does not include CVSS. Each **CVE** id from the JSON report was looked up in the **NVD CVE API 2.0** (`/rest/json/cves/2.0?cveId=…`) to obtain **baseSeverity**. Four rows are **GHSA-only** ids in `pip-audit`’s primary id field (pypdf advisories) with **no CVE in the same record**—those four are listed separately and should be tracked to current **pypdf** releases during remediation.

| Severity (NVD base) | Row count (of 52) | Notes |
|---------------------|-------------------|--------|
| **CRITICAL** | **1** | Single row: **CVE-2026-34520** → **aiohttp** 3.9.5 (C parser accepts null/control bytes in response headers; NVD base score **9.1**). |
| **HIGH** | **27** | Dominated by **aiohttp** (request smuggling, DoS, redirect/header issues), plus **pypdf**, **Pillow**, **PyJWT**, **orjson**, **starlette** Range DoS, etc. |
| **MEDIUM** | **20** | Includes **starlette** CVE-2025-54121 (large multipart spool / event-loop blocking), several **aiohttp** issues NVD rated MEDIUM, **pytest** CVE-2025-71176, **python-dotenv** CVE-2026-28684, **scikit-learn** CVE-2024-5206, etc. |
| **GHSA-only (no CVE on row)** | **4** | **pypdf** advisories **GHSA-jj6c-8h6c-hppx**, **GHSA-4pxv-j86v-mhcw**, **GHSA-7gw9-cf7v-778f**, **GHSA-x284-j5p8-9c5p** — still addressed by upgrading **pypdf** to a current fixed release (pip-audit fix column points at **6.10.x** line). |

**CRITICAL detail**

- **CVE-2026-34520** / **aiohttp** 3.9.5 — NVD **CRITICAL** 9.1; `pip-audit` fix version **3.13.4**.

**HIGH — representative details (non-exhaustive)**

- **PyJWT** 2.9.0 — **CVE-2026-32597** (failure to enforce JWS `crit` header semantics; NVD **HIGH** 7.5); fix **≥2.12.0**.  
- **starlette** 0.46.2 — **CVE-2025-62727** (crafted `Range` header quadratic processing / DoS; NVD **HIGH** 7.5); fix **≥0.49.1**.  
- **orjson** 3.9.15 — **CVE-2025-67221** (unbounded recursion in `dumps`; NVD **HIGH** 7.5); fix **≥3.11.6**.  
- **Pillow** 10.4.0 — **CVE-2026-25990** (PSD out-of-bounds write; **HIGH**), **CVE-2026-40192** (FITS gzip decompression bomb; **HIGH**); fixes **≥12.1.1** / **≥12.2.0** per advisory text.  
- **pypdf** 4.0.2 — numerous **HIGH** / **MEDIUM** CVEs (malicious PDF → memory exhaustion, infinite loops, long runtimes); current pip-audit “fix” column tops out at **6.10.2** for the GHSA-only rows.  
- **aiohttp** 3.9.5 — multiple **HIGH** issues (e.g. **CVE-2024-52304**, **CVE-2025-53643** request smuggling under Python-parser conditions; **CVE-2025-69223** zip bomb DoS; **CVE-2026-34515–34518** and related 2026 advisories); aggregate remediation **≥3.13.4**.

### 10.3 Packages warranting prompt upgrade (no bumps performed here)

Priority is **compatibility-tested** bumps—not raw `pip install -U` on production without CI:

1. **aiohttp → ≥3.13.4** (clears **CRITICAL** CVE-2026-34520 and the bulk of server/client CVEs in the scan).  
2. **starlette → ≥0.49.1** and aligned **FastAPI** pin (Starlette Range DoS).  
3. **PyJWT → ≥2.12.0**.  
4. **pypdf → ≥6.10.2** (or newer stable that resolves all GHSA/CVE rows).  
5. **Pillow → ≥12.2.0**.  
6. **orjson → ≥3.11.6**.  
7. **python-dotenv → ≥1.2.2**, **pytest → ≥9.0.3**, **scikit-learn → ≥1.5.0** — lower runtime exposure on the API hot path but should be updated in the lock/requirements used for builds.

**Dev / blast-radius notes:** **pytest** and **scikit-learn** issues are primarily **supply-chain / lab / offline** risk profiles; **aiohttp**, **starlette**, **PyJWT**, **orjson**, **Pillow**, and **pypdf** matter directly for **internet-facing** parsing, static file/range handling, JWT edge cases, JSON serialization, imaging, and user-supplied documents.

---

## 11. Security Patch Application (2026-04-29 UTC)

**Scope:** Surgical bump of the **six HIGH/CRITICAL runtime packages** called out in §10.3 (plus **FastAPI** aligned to **starlette**), on **GREEN** only. **No** changes to protected application modules (`main.py`, `bridge_server.py`). **MEDIUM**-only and non-listed **GHSA** findings **deferred to backlog**.

### 11.1 Packages updated (pins → resolved in container)

| Package | Minimum (advisory) | Pin / constraint | Resolved (`nate_backend` / `nate_bridge`) |
|--------|---------------------|------------------|-------------------------------------------|
| **aiohttp** | ≥ 3.13.4 (CVE-2026-34520 CRITICAL) | `~=3.13.4` | **3.13.5** |
| **starlette** | ≥ 0.49.1 (CVE-2025-62727 HIGH) | `>=0.49.1,<0.51.0` | **0.50.0** |
| **fastapi** | (compat with starlette 0.49+) | `~=0.125.0` | **0.125.0** |
| **PyJWT** | ≥ 2.12.0 (CVE-2026-32597 HIGH) | `[crypto]~=2.12.0` | **2.12.1** |
| **pypdf** | ≥ 6.10.2 (multiple HIGH / GHSA) | `~=6.10.2` | **6.10.2** |
| **Pillow** | ≥ 12.2.0 (HIGH bundle) | `~=12.2.0` | **12.2.0** |
| **orjson** | ≥ 3.11.6 (CVE-2025-67221 HIGH) | `~=3.11.6` | **3.11.8** |

**Files:** `backend/requirements-light.txt` (API image), `backend/requirements.txt` (bridge image). **pydantic** kept on **2.5.x** (FastAPI **0.125.x** chosen to avoid forced **pydantic ≥2.9**).

### 11.2 Build / deploy timeline (primary host 68.183.168.75)

| Step | Time (UTC, approx.) | Evidence |
|------|---------------------|----------|
| Backend image build | 2026-04-29 ~19:19 | `/tmp/security-patch-build.log` — `Image clinical-sovereignty-lab-backend Built` |
| Backend recreate + health | same window | `GET /health` → `healthy`; startup **113/113** services healthy |
| Bridge image build | 2026-04-29 ~19:23–19:33 | `docker compose -f docker-compose.prod.yml build bridge` exit 0 |
| Bridge recreate | ~19:34–19:35 | `nate_bridge` **Bridge Online**; `pip list` shows patched **aiohttp** / **PyJWT** / **starlette** / **fastapi** |

### 11.3 Phase 3 regression / smoke (post-deploy)

| Check | Result |
|-------|--------|
| **GET** `/health` + **jq** | **200**, JSON well-formed |
| **Admin REST** `GET /api/skyeye/pulse` with `SKYEYE_AUDIT_TOKEN` | **200** |
| **Admin REST** without auth (sample `GET /api/admin/webauthn/keys`) | **401** |
| **WebSocket login** (`client1` / `test123`, `expected_role`: **CLIENT**) | **`login_success`** + 32-char token (pre- and post-bridge rebuild) |
| **pypdf / Pillow / orjson** (in-container **PdfWriter** roundtrip, **Image** PNG, **orjson.dumps**) | **OK** |
| **ORANGE** `10.13.13.5` in backend logs (5m window) | **No lines** (no dispatch traffic in window; not a failure) |
| **Bridge** logs after recreate | **Bridge Online**, **Database pool**, **UserStore** path unchanged |

**Note:** **`POST /api/auth/login`** is not used for production auth (bridge **WebSocket** + REST bearer); REST probes above validate **FastAPI/starlette** stack behavior.

### 11.4 Deferred / backlog (not in this deploy)

- **pytest**, **python-dotenv**, **scikit-learn**, and other **§10** **MEDIUM** rows — schedule separate CI/pass with broader test burn-in.
- **pypdf** GHSA-only rows without CVE on the same record — covered by **6.10.2** pin per pip-audit fix column; re-run **`pip-audit`** on next maintenance window to confirm row count drop.
- **PII / email architecture** — remains **P1-1** documentation track (**not** blocked by this patch train).

### 11.5 Post-patch pip-audit verification (~20:03 UTC, 2026-04-29)

**Command:** `docker exec nate_backend sh -c 'pip-audit -r /app/requirements-light.txt'` (after Phase 2 image).

**Result:** **4** vulnerability rows in **3** packages — **python-dotenv** 1.0.1 (CVE-2026-28684, fix ≥1.2.2), **pytest** 7.4.4 (CVE-2025-71176, fix ≥9.0.3), **scikit-learn** 1.3.2 (PYSEC-2024-110, fix ≥1.5.0). **No** findings for **aiohttp**, **starlette**, **fastapi**, **PyJWT**, **pypdf**, **Pillow**, or **orjson** — the **six** Phase-2 runtime targets plus FastAPI/starlette alignment are **cleared** at pinned versions; remainder matches §11.4 backlog.

---

**End of report (updated 2026-04-29 with §11 — security patch train complete for listed packages).**
