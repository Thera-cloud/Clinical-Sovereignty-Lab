# Client Portal Settings — Audit & Verification

**Screen:** [`mobile/lib/screens/settings_screen.dart`](mobile/lib/screens/settings_screen.dart) → `ClientSettingsScreen`  
**Trust auditor:** [`backend/app/services/settings_tab_auditor.py`](backend/app/services/settings_tab_auditor.py) (15 checks: 10 REST + 5 WS)  
**Test account:** `audit_client` (migration `054_audit_test_accounts.sql`) — CLIENT role; hardware id used in auditor: `audit_client_hw`

## How to obtain a test token

1. Open app as client → login `audit_client` + password from secure store (or reset via admin flow).  
2. Or WebSocket `login_request` with `expected_role: CLIENT`.  
3. Copy `profile['token']` from `login_success` — use as `Authorization: Bearer <token>` for REST.

**Automated verify (REST):**  
`python3 backend/scripts/verify_client_settings.py --base-url https://api.sovereignsanctuary.net --token <CLIENT_BRIDGE_TOKEN> --hw-id audit_client_hw --username audit_client`

**One-shot (password only — same as LoginAuditor):**  
Default password is `AuditClient2026!` (see `login_auditor.py`).  
```bash
python3 backend/scripts/verify_client_settings.py \
  --base-url https://api.sovereignsanctuary.net \
  --ws-url wss://api.sovereignsanctuary.net/ws
```  
WS login acquires a bridge token; REST runs with that token. Use a real browser `User-Agent` on REST if Cloudflare returns 403 (script sets one automatically).

**Deploy notes (REST auth):**  
- `app/auth.py` Redis key env must be `production` (not `prod`) so bridge tokens work on billing and other `get_current_user_id` routes.  
- Data export self-check must allow path username = `profile.username` (see `data_export.py`).

---

## Feature matrix (UI → transport → verify)

| Section | Feature | Transport | Verify |
|---------|---------|-----------|--------|
| **PROFILE** | Edit email/phone/emergency/timezone + Save | WS `update_profile` | Login → WS → Save → reopen settings |
| **SHARE** | Invite a Friend | Native share / clipboard | Manual (no API) |
| **FAMILY** | Invite / roster / remove (Sovereign Circle) | REST `GET /api/client/family/members/{hwId}`; WS family flows | REST with token; tier-gated |
| **SUBSCRIPTION** | Plan, tokens, Change Plan | Profile + billing REST | `GET /api/billing/subscription/{hwId}` |
| **SUBSCRIPTION** | Payments / Family / Coaching | Nav to billing screens | Billing auditor |
| **SUBSCRIPTION** | Buy Tokens | `POST /api/billing/token-packs/purchase` | POST returns checkout or 422 |
| **TOKEN VAULT** | Balance display | Profile (WS/registry) | Visual |
| **SOVEREIGN VAULT** | Stats | `GET /api/v1/vault/stats?user_id=` | REST 200/401 |
| **SOVEREIGN VAULT** | Browse / Transfer / Organizer | Vault screens | Manual |
| **PREFERENCES** | Push / reminders / crisis | WS `update_notification_prefs` | WS after toggle |
| **PREFERENCES** | Voice default | WS `update_voice_preference` | WS |
| **PREFERENCES** | Preferred contact | WS `update_profile` (preferred_contact) | WS |
| **YOUR TOOLS** | Assessments | `GET /api/assessments/available/{hw}` | REST |
| **YOUR TOOLS** | Coherence Reports | Screen + WS `get_coherence_report` | WS auditor |
| **YOUR TOOLS** | Weekly Brief | `GET /api/research/nevedal/reports/brief` | REST |
| **YOUR TOOLS** | Memory Search | WS `memory_search` | WS auditor |
| **YOUR TOOLS** | Distress Beacon | Static + optional WS | Manual |
| **ASSIGNED COACH** | Coach card | `GET /api/client/coach-info/{coachId}` | REST |
| **COACHING TOOLS** | Group / Community mesh | WS mesh | Manual |
| **SECURITY** | Biometric | Local + SharedPreferences | Device manual |
| **MEMORY & PRIVACY** | Device search / photo consent | Local prefs | Manual |
| **MEMORY & PRIVACY** | Conversation Sync | `GET /api/client/health-check`, `POST history/push`, `GET history/pull` | REST + token |
| **LEGAL** | Data export | `GET /api/users/{username}/data-export` | REST |
| **ACCOUNT** | Delete / Logout | WS + local | Manual |

---

## Settings Tab Auditor endpoints (production parity)

| Tab | Method | Path |
|-----|--------|------|
| Weekly Brief | GET | `/api/research/nevedal/reports/brief` |
| Vault | GET | `/api/v1/vault/stats?user_id=audit_client_hw` |
| Vault | GET | `/api/vault/list/audit_client_hw` |
| Billing | GET | `/api/billing/plans` |
| Billing | GET | `/api/billing/subscription/audit_client_hw` |
| Export | GET | `/api/users/audit_client/data-export` |
| Assessments | GET | `/api/assessments/available/audit_client_hw` |
| Assessments | GET | `/api/assessments/history/audit_client_hw` |
| AI Modes | GET | `/api/ai-modes/list` |
| Community | GET | `/api/community/attendance/audit_client_hw` |
| WS | — | `auth` → `get_coherence_report` → `memory_search` |

TRUSTED HTTP codes per auditor: 200, 400, 404, 422.

---

## Manual QA checklist (5 min)

- [ ] Profile Save updates fields after app restart  
- [ ] Notification toggles persist  
- [ ] Weekly Brief loads without error  
- [ ] Memory Search returns results or empty state  
- [ ] Data export triggers download or 202  
- [ ] Coach info loads or shows Not Assigned  
- [ ] Health-check + Sync Now (if local history) no 401  

---

*Generated for operational audit; re-run `verify_client_settings.py` after any settings or client API change.*
