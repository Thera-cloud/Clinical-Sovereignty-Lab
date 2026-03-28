# Browser Console Debugging Guide for UX Audit
**How to capture technical details during testing**

---

## 🛠️ OPENING BROWSER DEVELOPER TOOLS

### Chrome / Edge:
- **Mac:** `Cmd + Option + I`
- **Windows/Linux:** `F12` or `Ctrl + Shift + I`

### Safari:
1. Enable Developer Menu: Safari → Preferences → Advanced → "Show Develop menu"
2. **Mac:** `Cmd + Option + I`

### Firefox:
- **Mac:** `Cmd + Option + I`
- **Windows/Linux:** `F12` or `Ctrl + Shift + I`

---

## 📋 WHAT TO CHECK IN DEVELOPER TOOLS

### 1. Console Tab (JavaScript Errors)

**Look for:**
- ❌ Red error messages (critical)
- ⚠️ Yellow warnings (may indicate issues)
- ℹ️ Blue info messages (usually harmless)

**Common Error Patterns:**
```
❌ "WebSocket connection failed" → Bridge is down or unreachable
❌ "401 Unauthorized" → Auth token expired or missing
❌ "Failed to load resource: 404" → Missing file/endpoint
❌ "TypeError: Cannot read property 'X' of undefined" → JavaScript bug
❌ "CORS error" → Server misconfiguration
```

**How to Copy Console Logs:**
1. Right-click in Console tab
2. Select "Save as..."
3. Or: Select all text (Cmd/Ctrl+A), copy (Cmd/Ctrl+C)

---

### 2. Network Tab (API Calls)

**How to Monitor:**
1. Open DevTools before loading the page
2. Click "Network" tab
3. Reload page or trigger action
4. Watch for red (failed) or yellow (slow) requests

**What to Check:**
```
Filter by type:
- XHR = API calls
- WS = WebSocket
- Doc = Page loads
- JS = JavaScript files
- CSS = Stylesheets
- Img = Images
```

**Failed Request Analysis:**
1. Click on a failed (red) request
2. Check "Headers" tab:
   - Status Code: 401 (auth), 404 (not found), 500 (server error)
   - Request URL: Was it correct?
   - Authorization: Is the Bearer token present?
3. Check "Response" tab:
   - Error message from server
4. Check "Timing" tab:
   - How long did it take?

**Common Issues:**
```
Status 401 → Missing or expired auth token
Status 403 → Insufficient permissions
Status 404 → Endpoint doesn't exist
Status 422 → Invalid input data
Status 500 → Server-side error
Status 503 → Service unavailable
```

---

### 3. Application Tab (Storage)

**Where to Look:**

#### Local Storage:
```
Application → Local Storage → https://app.sovereignsanctuary.net

Expected keys:
- sc_token → Auth token
- sc_username → audit_student_1
- sc_profile → JSON object with user data
```

#### Session Storage:
```
Application → Session Storage → https://app.sovereignsanctuary.net

Expected keys:
- (similar to Local Storage)
```

#### Cookies:
```
Application → Cookies → https://app.sovereignsanctuary.net

Expected cookies:
- sc_token
- sc_username
- sc_profile
```

**If Auth Fails:**
- Check if these storage items exist
- Check if `sc_token` is a long hex string (not empty or "null")
- Check if `sc_username` = "audit_student_1"

---

### 4. Performance Tab (Load Times)

**How to Record:**
1. Click "Performance" tab
2. Click ⭕ Record button
3. Reload page or perform action
4. Click ⏹️ Stop
5. Analyze timeline

**What to Look For:**
- **Initial Load:** Should be < 3 seconds
- **Chat Response:** Should be < 5 seconds
- **Page Transitions:** Should be < 500ms
- **Long Tasks:** Red bars = JavaScript blocking UI (bad)

---

## 🔍 SPECIFIC ISSUES TO DEBUG

### Issue: Chat Doesn't Respond

**Console Checks:**
```javascript
// Check WebSocket connection:
// Look for: "WebSocket connected" or "WebSocket error"
```

**Network Checks:**
1. Filter Network tab to "WS" (WebSocket)
2. Look for connection to `wss://api.sovereignsanctuary.net/ws`
3. Status should be "101 Switching Protocols" (success)
4. Click on WS connection → "Messages" tab to see message flow

**Expected WebSocket Messages:**
```
→ Sent: {"type": "login_request", "username": "audit_student_1", ...}
← Received: {"type": "login_success", ...}
→ Sent: {"type": "cortex_interaction", "message": "Hello", ...}
← Received: {"type": "cortex_response", "response": "...", ...}
```

---

### Issue: Settings Don't Load

**Console Check:**
```
Look for errors like:
- "Failed to fetch profile"
- "401 Unauthorized"
```

**Network Check:**
1. Filter to "XHR"
2. Look for requests to `/api/...`
3. Check if any return 401, 403, or 500
4. Click on failed request → "Headers" tab
5. Verify "Authorization: Bearer <token>" is present

**If 401 Errors:**
```
This means auth token is missing or invalid.

Check Application → Local Storage:
- Is sc_token set?
- Is it a long hex string?

If empty/null:
- Login flow may have failed
- WebSocket handshake may not have completed
- Redis token propagation delay (wait 5-10 seconds)
```

---

### Issue: Scheduling Calendar is Blank

**Console Check:**
```
Look for:
- "Failed to load availability"
- "Coach not found"
```

**Network Check:**
1. Look for request to `/api/sessions/availability/<coach_id>`
2. Check response:
   - Empty array `[]` = coach has no availability set
   - 404 = coach not found
   - 401 = auth issue

---

### Issue: Voice Mode Doesn't Work

**Console Check:**
```
Look for:
- "Microphone permission denied"
- "MediaDevices not supported"
- "getUserMedia failed"
```

**Browser Permissions:**
1. Click 🔒 or ℹ️ icon in address bar
2. Check microphone permission
3. Should be "Allow" (not "Ask" or "Block")

**Safari Specific:**
- May require user gesture (button click) before accessing mic
- First-time permission is cached; may need to reload

---

## 📸 SCREENSHOT CAPTURING

### Full Page Screenshots:

**Chrome DevTools:**
1. Open DevTools (Cmd/Ctrl+Shift+I)
2. Open Command Palette (Cmd/Ctrl+Shift+P)
3. Type "screenshot"
4. Select "Capture full size screenshot"

**Firefox:**
1. Right-click on page
2. Select "Take Screenshot"
3. Choose "Save full page"

**Safari:**
1. Develop → Show Web Inspector
2. Click camera icon in toolbar

---

## 📊 PERFORMANCE METRICS TO CAPTURE

### Key Timing Metrics:
```
Open Console and run:

// Check page load time:
performance.timing.loadEventEnd - performance.timing.navigationStart

// Check WebSocket connection time:
// (Look in Network → WS → Timing tab)

// Check API response times:
// (Look in Network → XHR → each request → Timing tab)
```

### Memory Usage (if app slows down over time):
```
1. Open DevTools
2. Go to Performance Monitor tab
3. Watch:
   - JS Heap Size (should not continuously grow)
   - DOM Nodes (should not continuously grow)
   - JS Event Listeners (should not continuously grow)
```

---

## 🚨 CRITICAL ERROR PATTERNS

### Red Flag #1: Infinite Loop
```
Console shows same error repeating rapidly:
"Failed to connect... retrying"
"Failed to connect... retrying"
"Failed to connect... retrying"
(every 100ms)

→ WebSocket reconnection loop, needs backend fix
```

### Red Flag #2: Memory Leak
```
Performance Monitor shows:
JS Heap Size: 50MB → 100MB → 200MB → 400MB (keeps growing)

→ JavaScript memory leak, needs code fix
```

### Red Flag #3: CORS Error
```
Console shows:
"Access to fetch at '...' from origin '...' has been blocked by CORS policy"

→ Server missing CORS headers
```

### Red Flag #4: CSP Violation
```
Console shows:
"Refused to load script because it violates Content Security Policy"

→ Server CSP headers too restrictive
```

---

## 📝 WHAT TO INCLUDE IN BUG REPORTS

For each bug, capture:

1. **Screenshot of the error/issue**
2. **Console logs** (copy all red errors)
3. **Network tab** (screenshot of failed requests)
4. **Steps to reproduce:**
   ```
   1. Navigate to X
   2. Click Y
   3. Observe error Z
   ```
5. **Expected behavior:** "Should show chat response"
6. **Actual behavior:** "Shows blank screen"
7. **Browser:** Chrome 125 / Safari 17 / Firefox 126
8. **Device:** Mac / Windows / iPhone
9. **Timestamp:** When did it happen?

---

## 🔧 QUICK FIXES TO TRY

### If Page Won't Load:
1. Hard refresh: `Cmd+Shift+R` (Mac) or `Ctrl+F5` (Windows)
2. Clear cache: DevTools → Application → Clear Storage
3. Try incognito/private mode
4. Try different browser

### If WebSocket Won't Connect:
1. Check if `wss://api.sovereignsanctuary.net/ws` is reachable
2. Wait 10 seconds (Redis propagation delay)
3. Logout and login again
4. Check Network tab for 101 response

### If 401 Errors Persist:
1. Clear Local Storage: Application → Clear Storage
2. Logout and login again
3. Wait 10 seconds after login
4. Check if ENVIRONMENT variables match (backend vs bridge)

---

## 📞 ESCALATION CHECKLIST

Before escalating a bug, confirm:
- [ ] Tried hard refresh
- [ ] Tried different browser
- [ ] Checked console for errors
- [ ] Checked network for failed requests
- [ ] Captured screenshot
- [ ] Documented steps to reproduce
- [ ] Checked if it's a known issue (see UX_AUDIT_KNOWN_ISSUES.md)

---

**READY TO DEBUG LIKE A PRO!** 🚀
