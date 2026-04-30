> **HISTORICAL — READ ONLY as of 2026-04-30.** New open items go 
> in `docs/OPEN_TODOS.md`, not here. This file is preserved for 
> historical reference and pending reconciliation. See 
> docs/OPEN_TODOS.md for active work.

# Known Technical Issues That May Affect UX Audit
**Reference for audit_student_1 testing**

---

## 🔴 HIGH-IMPACT ISSUES

### 1. Safari Service Worker Caching
**Symptom:** Blank screen, non-functional UI, or "stuck" on old version  
**Cause:** Safari aggressively caches `flutter_service_worker.js`, `flutter_bootstrap.js`, and `index.html`  
**Fix for Tester:** Hard refresh (Cmd+Shift+R) or clear website data for sovereignsanctuary.net  
**Technical:** Nginx headers set to `no-cache` but Safari may still cache  
**Rule Reference:** `safari-flutter-web-caching.mdc`

### 2. Redis Token Propagation Delay
**Symptom:** REST API calls return 401 immediately after login, even though WebSocket works  
**Cause:** Bridge stores tokens to Redis asynchronously ("memory + Redis scheduled"); there's a timing gap  
**Impact:** Settings, scheduling, token balance APIs fail for 1-5 seconds after login  
**Fix for Tester:** Wait 5-10 seconds after login before navigating to Settings or Schedule  
**Rule Reference:** `learned-integration-patterns.mdc` #71

### 3. ENVIRONMENT Variable Mismatch (If Recent Deploy)
**Symptom:** ALL REST APIs return 401 for ALL users, but WebSocket auth works perfectly  
**Cause:** Bridge and backend have different `ENVIRONMENT` env vars (development vs production)  
**Impact:** Total REST API failure — Settings, Schedule, Token Lab, all return 401  
**Check:** `docker exec nate_backend printenv ENVIRONMENT` vs `docker exec nate_bridge printenv ENVIRONMENT`  
**Rule Reference:** `learned-integration-patterns.mdc` #70

---

## 🟡 MEDIUM-IMPACT ISSUES

### 4. Coach Assignment Field Inconsistency
**Symptom:** Coach name doesn't appear in Schedule tab, or shows "No coach assigned"  
**Cause:** audit_student_1 may be missing one of three coach assignment fields: `coach_id`, `assigned_coach_id`, `assigned_coach`  
**Query to Check:**
```sql
SELECT username, 
       profile_data->>'coach_id' AS cid,
       profile_data->>'assigned_coach_id' AS acid,
       profile_data->>'assigned_coach' AS ac
FROM users WHERE username = 'audit_student_1';
```
**Expected:** All three should show "Audit Lawyer 1" or "audit_lawyer_1"  
**Rule Reference:** `coach-client-assignment-fields.mdc`

### 5. Token Balance Display
**Symptom:** Token balance shows "undefined" or NaN in Settings  
**Cause:** `token_balance` column and `profile_data->>'token_balance'` may be out of sync  
**Impact:** Can't purchase token packs, confusion about usage  
**Rule Reference:** `token-usage-agent-lifecycle.mdc`

### 6. Notification Observer Not Polling (If SkyEye Features Tested)
**Symptom:** Growth Dashboard shows "No post analytics yet" even though platforms are connected  
**Cause:** Observer may not be reading from correct table (`skyeye_platform_tokens` vs `skyeye_platforms`)  
**Impact:** Empty engagement data, no social analytics  
**Rule Reference:** `notification-observer-data-pipeline.mdc`

### 7. Bridge PostgreSQL Connection Failure
**Symptom:** Login works but session data doesn't persist, metrics don't save  
**Cause:** Bridge's `db_pool` is None; it falls back to JSON file auth  
**Log Check:** `docker logs nate_bridge 2>&1 | grep "USE_POSTGRES_REGISTRY=true but no db_pool"`  
**Impact:** Data loss, metrics don't persist across sessions  
**Rule Reference:** `bridge-postgres-connectivity.mdc`

---

## 🟢 LOW-IMPACT ISSUES

### 8. Avatar Mode Tier Gating
**Symptom:** No 3D avatar in chat (flat icon only)  
**Cause:** Avatar mode requires Sovereign Circle tier; audit_student_1 may be on Threshold or Inner Chamber  
**Expected:** This is correct behavior, not a bug  
**Rule Reference:** `.cursorrules` (design system)

### 9. Consent Screen on First Login
**Symptom:** Modal asking to accept consent version v13.0_2026  
**Cause:** First login after account creation requires consent acceptance  
**Expected:** This is correct behavior  
**Rule Reference:** `registration-flow-integrity.mdc`

### 10. Onboarding Tutorial
**Symptom:** 7-step walkthrough on first login (Welcome, Chat, Voice Mode, Metrics, Avatar, Family, Pricing)  
**Cause:** First-time user onboarding flow  
**Expected:** This is correct behavior; can be skipped  
**Code:** `OnboardingTutorialScreen` in `updated_screens.dart`

---

## 🔧 VERIFICATION COMMANDS (For Tech Review)

### Check audit_student_1 Profile:
```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
SELECT username, role, 
       profile_data->>'coach_id' AS coach_id,
       profile_data->>'assigned_coach' AS coach,
       subscription_status, tier,
       token_balance,
       profile_data->>'consent_version' AS consent
FROM users WHERE username = 'audit_student_1'
\""
```

### Check Backend Health:
```bash
ssh root@68.183.168.75 "curl -s http://localhost:8000/health"
# Expected: {"status": "healthy"}
```

### Check Bridge Health:
```bash
ssh root@68.183.168.75 "docker logs nate_bridge --tail 20 2>&1 | grep -E 'Database pool|UserStore|PostgreSQL Registry'"
# Expected: "Database pool created", "UserStore ready", "PostgreSQL Registry: ENABLED"
```

### Check WebSocket Connectivity:
```bash
ssh root@68.183.168.75 "docker logs nate_bridge --tail 50 2>&1 | grep 'audit_student_1'"
# Look for: login_request, login_success, GUEST closes (Safari cache issue)
```

### Check ENVIRONMENT Sync:
```bash
ssh root@68.183.168.75 "echo 'Backend:' \$(docker exec nate_backend printenv ENVIRONMENT); echo 'Bridge:' \$(docker exec nate_bridge printenv ENVIRONMENT)"
# Both must show: production
```

---

## 📱 MOBILE vs WEB DIFFERENCES

### Flutter Web (app.sovereignsanctuary.net):
- Service worker caching issues (Safari)
- WebSocket URL: `wss://api.sovereignsanctuary.net/ws`
- Bottom nav bar (if mobile viewport)
- May show "Install App" prompt

### Native Mobile (iOS/Android):
- No service worker issues
- Better performance
- Native microphone/camera permissions
- BLE/NFC features enabled

---

## 🎯 TEST ACCOUNT DETAILS

**Username:** audit_student_1  
**Password:** AuditTest2026!  
**Role:** CLIENT  
**Expected Coach:** audit_lawyer_1 (Audit Lawyer 1)  
**Expected Tier:** Unknown (check during audit)  
**Token Balance:** Unknown (check during audit)

**Coach Account for Comparison:**  
**Username:** audit_lawyer_1  
**Password:** (not provided for this audit)  
**Role:** COACH

---

## 🚨 IMMEDIATE RED FLAGS TO REPORT

If you see ANY of these during testing, they are CRITICAL bugs:

1. **White Screen / Blank Screen** (no UI loads at all)
2. **"Connection Refused" or ERR_CONNECTION_REFUSED**
3. **Login succeeds but chat returns "Unauthorized"**
4. **Settings screen shows "Error loading profile"**
5. **All navigation buttons do nothing**
6. **Chat input field is missing or disabled**
7. **Infinite loading spinner (>30 seconds)**
8. **DrNevedal1 appears in family member list** (admin should NEVER be in client family)

---

## 📞 ESCALATION PATH

**For Technical Issues During Audit:**
1. Check this document first for known issues
2. Try hard refresh (Cmd+Shift+R) if on Safari
3. Wait 10 seconds and retry (Redis propagation)
4. Try different browser (Chrome vs Safari)
5. If still broken, document thoroughly with:
   - Screenshot of error
   - Browser console logs (F12 → Console tab)
   - Network tab (F12 → Network → filter for failed requests)
   - Exact steps to reproduce

---

## 📋 Engineering backlog (not audit-blocking)

### Coach Classroom — bridge `{"type":"error"}` handling
When the bridge returns a generic WebSocket `error` during classroom video analysis, `updated_screens.dart` coach handler (`~6725`) clears `_dojoBusy` / `_notesLoading` but does **not** reset `_classroomAnalyzing`, `_classroomVideoPipelineActive`, or cancel the classroom poll. **Expected:** show SnackBar with `message`/`detail`, set `_classroomAnalyzing = false`, cancel poll, optionally `_requestClassroomSessions()`.

---

**END OF TECHNICAL REFERENCE**
