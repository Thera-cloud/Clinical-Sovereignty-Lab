# Sovereign Sanctuary Client Portal - Technical UX Expectations
**Based on Codebase Analysis**

## Expected Client Portal Features

### 1. **Main Navigation Structure**
The client should see a bottom navigation bar or similar with these screens:

#### Primary Screens (from `updated_screens.dart`):
- **Companion Chat** (`CompanionChatScreen`) - Main AI chat interface with Little Nate
- **Schedule** (`ClientScheduleScreen`) - Book sessions with assigned coach
- **Metrics/Reports** (`NevedalReportsScreen`) - View emotional coherence metrics
- **Settings** (`SettingsScreen`) - Profile, notifications, privacy

#### Additional Features (tier-dependent):
- **Family Sanctuary** (`FamilySanctuaryScreen`) - If client has family_id assigned
- **Community Mesh** (`CommunityMeshScreen`) - BLE/NFC token sharing with nearby clients
- **AI Modes** (`AiModesScreen`) - Different conversational modes (Sanctuary AI, Group Coaching, etc.)
- **Vault Browser** (`VaultBrowserScreen`) - Attach/view files in chat
- **Nate Organizer** - Task/reminder management
- **Quiz** - Dynamic assessments

---

## A. Chat Interface - Expected UX

### Based on `CompanionChatScreen` (lines 2419-3582 in updated_screens.dart):

**What Should Work:**
- WebSocket connection to `wss://api.sovereignsanctuary.net/ws`
- Text input field at bottom
- Microphone button for voice input (if Speech-to-Text available)
- Message history scrolls smoothly
- Nate's avatar pulses/breathes during response
- File attachment button (vault uploads)
- Token balance visible (top right or header)

**Key UX Elements to Verify:**
1. **Connection Status**
   - Should show "Connected" or similar status
   - If disconnected, should show retry attempts
   - Look for: "Connecting...", "Connected", "Disconnected" messages

2. **Message Send Flow**
   - Type message → Send button becomes active
   - After send: message appears immediately in your bubble
   - Loading indicator while waiting for Nate's response
   - Nate's response appears in different colored bubble

3. **Voice Mode**
   - Tap mic → should request microphone permission
   - While speaking: visual feedback (waveform, pulsing mic icon)
   - Auto-send when you stop speaking (configurable timeout)
   - Nate can respond with voice (TTS)

4. **Avatar Animations**
   - Idle: slow breathing animation
   - Listening: attentive expression
   - Responding: mouth movements synchronized with speech
   - At Sovereign Circle tier: full 3D avatar with emotion tracking

5. **Token Consumption**
   - Each message exchange consumes tokens
   - Token balance should decrement after each response
   - Visual indicator of tokens used per message
   - Warning when balance is low

6. **Conversation History**
   - Scroll up to see previous messages
   - Sessions are preserved across logins
   - Look for "Load older messages" or similar

**Common Issues to Watch For:**
- Message send button not enabling
- No response from Nate (timeout)
- Token balance not updating
- Avatar not animating
- Voice input not working on web (browser permission issue)
- Slow response time (>10 seconds)
- Conversation history not loading

---

## B. Settings Screen - Expected Sections

### Based on `SettingsScreen` (settings_screen.dart):

**Profile Information:**
- Name (editable)
- Email (editable)
- Phone (editable)
- Profile photo upload
- Assigned coach name (read-only)

**Account Settings:**
- Current tier display (Threshold, Inner Chamber, Sovereign Circle)
- Subscription status
- Payment methods (if subscribed)
- Upgrade/downgrade options

**Notification Preferences:**
- Session reminders
- Coach messages
- System notifications
- Email notifications

**Privacy & Data:**
- Consent version (should show v13.0_2026)
- Data export option
- Account deletion option
- Privacy policy link

**Security:**
- Password change
- Biometric unlock (if supported on device)
- Session timeout settings

**Coach Information:**
- Assigned coach: Should show "Audit Lawyer 1" or "audit_lawyer_1"
- Coach contact info
- Session history with this coach

**App Preferences:**
- Dark/light mode (app is dark by default)
- Voice settings (TTS speed, voice selection)
- Language (if multilingual support exists)

**Common Issues:**
- Missing coach assignment display
- Cannot edit profile fields
- Save button doesn't work
- No confirmation after saving
- Payment method section missing (if subscribed)

---

## C. Scheduling - Expected Flow

### Based on `ClientScheduleScreen` and session APIs:

**What Should Be Visible:**
1. **Coach Info Card**
   - Coach name: "Audit Lawyer 1" (or audit_lawyer_1)
   - Profile photo
   - Specialties/bio
   - Availability summary

2. **Calendar View**
   - Current week/month view
   - Available time slots highlighted in gold/cyan
   - Booked sessions shown in different color
   - Timezone display

3. **Booking Flow**
   - Select date → available times appear
   - Select time → session details dialog
   - Choose duration (15, 30, 45, 60 min options)
   - Choose session type (if multiple types available)
   - Payment confirmation (or "Waived" if free consultation)
   - Zoom/FaceTime link generation

4. **Free Consultation Option** (if assistant coach):
   - "Free 15-min Consultation" toggle or button
   - Daily limit indicator (1 per day)
   - If already used: "Already used today" message

5. **Upcoming Sessions**
   - List of booked sessions
   - Join button (launches Zoom/FaceTime)
   - Cancel/reschedule option
   - Session status (scheduled, in-progress, completed)

6. **Past Sessions**
   - Session history
   - Duration, date, notes
   - Replay option (if recordings available)

**Common Issues:**
- No available time slots showing
- Cannot select time slot
- Coach name missing or wrong
- Booking confirmation doesn't appear
- Zoom link missing after booking
- Cannot cancel session

---

## D. Metrics/Reports (Nevedal Dashboard)

### Based on `NevedalReportsScreen`:

**Expected Metrics Visualizations:**
1. **Emotional Coherence (C_emo)**
   - Line chart over time
   - Current score (0-1 scale)
   - Trend arrow (↑ improving, ↓ declining)

2. **Mood Tracking**
   - Daily mood entries
   - Pattern visualization (heatmap or graph)
   - Common emotions tagged

3. **Engagement Score**
   - Session participation level
   - Message frequency
   - Voice vs text usage ratio

4. **Breakthrough Moments**
   - Timeline of key insights
   - AI-identified growth moments
   - Coach annotations

5. **Voice Biometrics** (if available)
   - Pitch variance
   - Energy levels
   - Speech rate
   - Pause patterns

**Common Issues:**
- No data showing (if brand new account)
- Charts not rendering
- Data not updating after sessions
- Export button not working

---

## E. Visual Design Standards

### Color Palette (from .cursorrules):
- **Backgrounds:**
  - Void: #050505
  - Chamber: #0A0A0A
  - Elevated: #111111
- **Primary Gold:** #C9A962
- **Bright Gold:** #E8D5A3
- **Dim Gold:** #8B7355
- **AI/Coaching Cyan:** #4ECDC4
- **Research Purple:** #9D4EDD
- **Alert Red:** #EF4444

### Typography:
- **Display:** Cormorant Garamond
- **Body:** DM Sans

### Expected Design Quality:
- Consistent 8px spacing grid
- Smooth animations (fade, slide, pulse)
- Loading states have skeleton screens or spinners
- Buttons have hover/active states
- Cards have subtle shadows/glows
- Icons are Material Design or custom SVG

---

## F. Performance Benchmarks

### Load Times (Expected):
- Initial app load: 2-5 seconds
- Login to dashboard: 1-3 seconds
- Chat message response: 3-8 seconds
- Screen transitions: <500ms

### Network:
- WebSocket should reconnect automatically if dropped
- Max 3 retry attempts with exponential backoff
- Offline state handled gracefully

---

## G. Common Flutter Web Issues to Check

### Known Web-Specific Problems:
1. **Service Worker Caching** (Safari issue)
   - Symptom: App loads but never becomes interactive
   - Bridge logs: `Connection closed for GUEST` with no `login_request`
   - Fix: Clear Safari website data or use incognito

2. **WebSocket Connection**
   - Symptom: "Disconnected" message, cannot send messages
   - Check browser console for WebSocket errors
   - Verify: `wss://api.sovereignsanctuary.net/ws` is reachable

3. **Microphone Permissions**
   - Web requires HTTPS for microphone access
   - Browser must prompt for permission
   - If denied, voice mode won't work

4. **File Uploads**
   - Web file picker may look different than native
   - CORS issues can block uploads
   - Check network tab for 403/CORS errors

---

## H. Test Account Details

**Username:** `audit_student_1`  
**Password:** `AuditTest2026!`  
**Role:** CLIENT  
**Expected Assigned Coach:** Audit Lawyer 1 (`audit_lawyer_1`)  
**Expected Tier:** (Unknown - verify in Settings)  
**Expected Features:** Basic chat, scheduling, metrics (tier-dependent)

---

## I. Critical UX Tests by Priority

### P0 (Must Work):
1. ✅ Can log in successfully
2. ✅ Chat interface loads
3. ✅ Can send a message and receive response
4. ✅ Can navigate between screens
5. ✅ Settings screen displays profile info

### P1 (Should Work):
1. ✅ Voice input works (browser permissions)
2. ✅ Schedule shows coach info
3. ✅ Can view available time slots
4. ✅ Metrics/reports display data
5. ✅ Token balance is visible and updates

### P2 (Nice to Have):
1. ✅ Avatar animations are smooth
2. ✅ File attachment works
3. ✅ Conversation history loads fully
4. ✅ Biometric unlock (if device supports)
5. ✅ Dark mode consistency

---

## J. Specific Code Patterns to Verify

### From `main.dart` Client Login Flow:
1. Login → `login_request` WebSocket message
2. Response → `login_success` with `profile` data
3. Navigation → `NeuralInterface` (main client portal)
4. If consent needed → `ReConsentScreen` appears first

### From `NeuralInterface` (main client screen):
- Should show: avatar, chat input, bottom nav
- Active WebSocket indicated by connection status
- Token balance in header or corner
- Coach name visible somewhere in UI

### Onboarding Tutorial:
- If first login, `OnboardingTutorialScreen` may appear
- 7 steps for clients (Welcome, Chat, Voice, Metrics, Avatar, Family, Pricing)
- Can skip at any time
- Uses Nate's voice narration (web autoplay may block)

---

## K. Red Flags (Immediate Showstoppers)

🚨 **Critical Issues:**
- Cannot log in at all
- App shows white screen after login
- Chat interface never appears
- Messages send but no response ever comes
- Settings screen is completely blank
- Navigation buttons don't work
- App crashes on any action

⚠️ **Major Issues:**
- Response time >15 seconds
- Coach name shows wrong coach or "null"
- Token balance not updating
- Cannot access settings
- Schedule shows no time slots ever
- Voice input completely broken

🟡 **Minor Issues:**
- Slow animations
- Inconsistent colors
- Missing icons
- Awkward text wrapping
- No loading indicators
- Confusing navigation labels

---

## L. Steve Jobs Would Ask...

1. **"Can my mom use this without help?"**
   - Is the UI intuitive enough for non-tech users?
   - Are labels clear and jargon-free?

2. **"Does it spark joy?"**
   - Are the animations delightful?
   - Does the avatar feel alive?
   - Is the design elegant or cluttered?

3. **"What's the core experience?"**
   - Chat with Nate should be the hero feature
   - Everything else should support that goal
   - Is chat prominent, or buried?

4. **"Why would someone choose this over BetterHelp?"**
   - What's unique here?
   - Is the AI companion compelling?
   - Does it feel premium at the Sovereign Circle tier?

5. **"Would I use this every day?"**
   - Is it fast enough?
   - Is it reliable?
   - Does it respect my time?

---

## M. Automated Test Script (Optional)

If you want to run automated tests, here's a Playwright script outline:

```javascript
// test/client_portal_ux.spec.js
const { test, expect } = require('@playwright/test');

test.describe('Client Portal UX Audit', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('https://app.sovereignsanctuary.net');
  });

  test('Login flow completes successfully', async ({ page }) => {
    await page.click('text=Client');
    await page.fill('input[name="username"]', 'audit_student_1');
    await page.fill('input[type="password"]', 'AuditTest2026!');
    await page.click('button:has-text("Login")');
    
    // Wait for main interface
    await expect(page).toHaveURL(/.*interface.*/i, { timeout: 10000 });
    
    // Verify core elements present
    await expect(page.locator('text=/Little Nate|Chat|Message/i')).toBeVisible();
  });

  test('Chat sends message and receives response', async ({ page }) => {
    // ... login first ...
    
    const chatInput = page.locator('input[placeholder*="message" i]').first();
    await chatInput.fill('Hello, I am feeling stressed about work today');
    await page.click('button[aria-label*="send" i]');
    
    // Wait for response (max 15s)
    await expect(page.locator('text=/stress|help|support/i')).toBeVisible({ timeout: 15000 });
  });

  test('Settings screen loads with profile info', async ({ page }) => {
    // ... login first ...
    
    await page.click('[aria-label*="settings" i]');
    await expect(page.locator('text=/profile|account/i')).toBeVisible();
    await expect(page.locator('text=/audit_student_1|Audit Student/i')).toBeVisible();
  });

  // Add more tests...
});
```

Run with: `npx playwright test --headed --project=chromium`

---

## N. Manual Testing Checklist

Print this and check off as you test:

### Login & Onboarding
- [ ] Gateway loads in <3s
- [ ] Client button is obvious
- [ ] Login dialog appears
- [ ] Can enter credentials
- [ ] Login succeeds
- [ ] Consent screen (if shown) is clear
- [ ] Tutorial (if shown) makes sense
- [ ] Can skip tutorial
- [ ] Main app loads after onboarding

### Chat Interface
- [ ] Chat input field is visible
- [ ] Can type message
- [ ] Send button works
- [ ] Message appears in chat history
- [ ] Nate responds within 10s
- [ ] Response is contextual
- [ ] Can send follow-up
- [ ] Conversation history preserved
- [ ] Microphone button present (if tier allows)
- [ ] Voice input works (if tested)
- [ ] Token balance visible
- [ ] Token balance decrements after response

### Settings
- [ ] Settings icon/button is visible
- [ ] Settings screen loads
- [ ] Profile info shown (name, email)
- [ ] Assigned coach shown: "Audit Lawyer 1"
- [ ] Current tier displayed
- [ ] Can edit profile fields
- [ ] Save button works
- [ ] Confirmation message after save
- [ ] Notification preferences available
- [ ] Privacy settings available
- [ ] Password change option present

### Scheduling
- [ ] Schedule screen accessible
- [ ] Coach name visible
- [ ] Calendar view loads
- [ ] Available time slots shown
- [ ] Can select a time slot
- [ ] Booking dialog appears
- [ ] Duration options available
- [ ] Can confirm booking (test with caution)
- [ ] Upcoming sessions list
- [ ] Past sessions (if any)

### Metrics/Reports
- [ ] Metrics screen accessible
- [ ] Charts/graphs render
- [ ] Data is present (or "No data yet" message)
- [ ] Metrics make sense
- [ ] Export option (if available)

### Navigation
- [ ] All screens accessible from nav
- [ ] Back buttons work
- [ ] No dead ends
- [ ] Smooth transitions
- [ ] Bottom nav (if present) works

### Visual Design
- [ ] Colors match brand (#050505, #C9A962, etc.)
- [ ] Typography is readable
- [ ] Spacing is consistent
- [ ] No overlapping text
- [ ] Icons are clear
- [ ] Loading states have indicators
- [ ] Animations are smooth

### Performance
- [ ] App loads in <5s
- [ ] Screen transitions <1s
- [ ] Chat responses <10s
- [ ] No crashes
- [ ] WebSocket stays connected

### Error Handling
- [ ] Network errors show message
- [ ] Invalid input shows validation
- [ ] Timeout errors handled gracefully
- [ ] Can recover from errors

---

Use this technical guide alongside the audit report template to conduct a thorough evaluation!
