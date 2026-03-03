---
name: Lisa Beta Test Fixes
overview: "Fix 6 client portal issues reported by beta tester Lisa: vault upload auth failure, voice mode not triggering TTS, weekly brief showing zeros due to wrong DB column names, assessments returning empty (likely fixed by ENVIRONMENT fix), Organize with Nate tier gate mismatch, and Nate hallucinating a file export feature that doesn't exist."
todos:
  - id: vault-auth
    content: "Fix vault upload auth: add Bearer token to vault_browser_screen.dart and vault_attachment_button.dart"
    status: completed
  - id: voice-mode
    content: Wire voice_mode_default to auto-trigger TTS on Nate reply in updated_screens.dart
    status: completed
  - id: weekly-brief
    content: Fix session INSERT column names in bridge_server.py (session_start -> started_at, session_end -> ended_at)
    status: completed
  - id: assessments-error
    content: Add error handling to quiz_screen.dart for non-200 responses + verify quizzes seeded
    status: completed
  - id: organizer-tier
    content: Fix _isSovereignCircle in settings_screen.dart to remove FAMILY and use tier fallback
    status: completed
  - id: nate-export-hallucination
    content: Add file export limitation to Nate system prompt in skyeye_chat.py and bridge_server.py
    status: completed
  - id: flutter-build
    content: Run flutter build web --release to verify all Dart changes compile
    status: completed
  - id: deploy-verify
    content: Deploy all changes, verify with Lisa's test scenarios
    status: completed
isProject: false
---

# Lisa Beta Test -- Client Portal Fixes

## Issue 1: Vault Upload Fails (HIGH)

**Error**: `ClientException: Load failed, url=https://api.sovereignsanctuary.net/api/v1/upload?user_id=CLIENT_LETSGOLISA_ID`

**Root cause**: `mobile/lib/screens/vault_browser_screen.dart` sends `X-User-Id` header but no `Authorization: Bearer` token. The backend `vault_api.py` uses `get_member_id_and_tier` which chains through `get_current_user` -- requires a valid Redis bridge token. Without Bearer auth, the request is rejected.

**Fix** in [vault_browser_screen.dart](mobile/lib/screens/vault_browser_screen.dart) `_pickAndUpload()` (~line 496):

- Add `request.headers['Authorization'] = 'Bearer $token'` (get token from profile)
- Remove `user_id` query parameter (only works in dev/localhost mode per `auth.py`)

Also fix [vault_attachment_button.dart](mobile/lib/widgets/vault_attachment_button.dart) `_uploadFile()` (~line 180):

- Same auth header addition

---

## Issue 2: Voice Mode -- No Audio (HIGH)

**Root cause**: `voice_mode_default` preference is saved in profile but **never read** when Nate replies. TTS is only triggered by manual tap on the speaker icon.

**Fix** in [updated_screens.dart](mobile/lib/updated_screens.dart) (NeuralInterfaceV2):

- When `nate_response` or `chat_reply` arrives and Nate's text is added to the message list, check if `voice_mode_default == true` in the user's profile/notification prefs
- If true, automatically call `_speakNateMessage(replyText)` after rendering the message
- Guard with `if (mounted)` and cancel any in-flight TTS before starting new one

---

## Issue 3: Weekly Brief Shows All Zeros (MEDIUM)

**Root cause**: Session creation in `bridge_server.py` uses wrong column names. The `sessions` table has `started_at` and `ended_at`, but the INSERT uses `session_start` and `session_end`. Sessions are never recorded, so the Weekly Brief calculates 0 for everything.

**Fix** in [bridge_server.py](backend/app/websocket/bridge_server.py):

- ~line 5253: Change `session_start` to `started_at` in the INSERT
- ~line 5304: Change `session_end` to `ended_at` in the UPDATE
- Verify with: `SELECT column_name FROM information_schema.columns WHERE table_name = 'sessions' AND column_name IN ('started_at', 'ended_at', 'session_start', 'session_end')`

---

## Issue 4: Assessments Not Showing (MEDIUM -- likely already fixed)

**Root cause**: The ENVIRONMENT mismatch (bridge=development, backend=production) caused all REST API calls including `GET /api/quizzes` to return 401. We already fixed this by adding `ENVIRONMENT=production` to the bridge.

**Remaining work**:

- Verify quizzes are seeded: `SELECT COUNT(*) FROM quizzes` (expect 5)
- Add error handling in [quiz_screen.dart](mobile/lib/screens/quiz_screen.dart) `_loadQuizzes()` (~line 108): show a SnackBar on non-200 responses instead of silently showing "No assessments available"

---

## Issue 5: Organize with Nate Tier Gate (MEDIUM)

**Root cause**: `settings_screen.dart` `_isSovereignCircle` uses `plan.contains('FAMILY')` which shows the button for family members. But the bridge's `normalize_tier()` only accepts `TOP_TIER`/`SOVEREIGN_CIRCLE`/`SOVEREIGN`/`TOP`. Family members see the button but get rejected.

**Fix** in [settings_screen.dart](mobile/lib/screens/settings_screen.dart) (~line 405):

- Remove `FAMILY` from `_isSovereignCircle` check (unless product decision is to grant family members access)
- Also check `_profile['tier']` as fallback when `subscription_plan` is empty:

```dart
  final plan = (_profile['subscription_plan'] ?? _profile['tier'] ?? '').toString().toUpperCase();
  return plan == 'TOP_TIER' || plan.contains('SOVEREIGN') || plan == 'TOP';
  

```

---

## Issue 6: Nate Promises File Export (LOW)

**Root cause**: Little Nate's system prompt doesn't tell him he cannot export/download files to the user's device. He hallucinated the capability.

**Fix** in [skyeye_chat.py](backend/app/services/skyeye_chat.py) `LITTLE_NATE_SYSTEM_PROMPT` section `YOUR PLATFORM CAPABILITIES`:

- Add: "You CANNOT export, download, or save files to the user's device. You cannot create documents, PDFs, or text files. If a user asks you to export content, suggest they take a screenshot or copy-paste the text."

Also add to the bridge's AI system prompt in [bridge_server.py](backend/app/websocket/bridge_server.py) wherever the client-facing AI context is built:

- Same capability limitation

---

## Verification Steps

After deploying all fixes:

1. Log in as Lisa (letsgolisa) and tap Assessments -- should show 5 preset quizzes
2. Upload a screenshot to Sovereign Vault -- should succeed
3. Enable Voice Mode by Default, send a message -- Nate should speak his reply
4. Check Weekly Brief after a conversation -- should show session count > 0
5. Check Organize with Nate -- should only appear if Lisa is actually Sovereign Circle tier
6. Ask Nate to export a document -- should politely decline

## Files Modified


| File                                              | Changes                                        |
| ------------------------------------------------- | ---------------------------------------------- |
| `mobile/lib/screens/vault_browser_screen.dart`    | Add Bearer auth to upload                      |
| `mobile/lib/widgets/vault_attachment_button.dart` | Add Bearer auth to upload                      |
| `mobile/lib/updated_screens.dart`                 | Auto-TTS on voice_mode_default                 |
| `backend/app/websocket/bridge_server.py`          | Fix session column names (started_at/ended_at) |
| `mobile/lib/screens/quiz_screen.dart`             | Error handling for non-200                     |
| `mobile/lib/screens/settings_screen.dart`         | Fix tier gate logic                            |
| `backend/app/services/skyeye_chat.py`             | Add file export limitation to system prompt    |


