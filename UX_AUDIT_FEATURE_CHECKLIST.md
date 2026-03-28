# Client Portal Feature Checklist
**Quick reference for audit_student_1 testing**

---

## 🗺️ EXPECTED NAVIGATION STRUCTURE

Based on codebase analysis, the client portal should have these main sections:

### Bottom Navigation (Mobile) or Tab Bar (Desktop):
1. **🏠 Home / Chat** - Main AI chat interface with Little Nate
2. **📊 Metrics** - Emotional coherence graphs, mood tracking
3. **📅 Schedule** - Book sessions with coach
4. **⚙️ Settings** - Profile, billing, preferences
5. **👨‍👩‍👧 Family** (if family plan) - Manage dependents

---

## 💬 CHAT INTERFACE FEATURES TO TEST

### Location: `NeuralInterface` screen (Home tab)

#### Basic Chat:
- [ ] Text input field at bottom
- [ ] Send button (paper plane icon)
- [ ] Message bubbles (user vs Little Nate)
- [ ] Scroll to see history
- [ ] Timestamps on messages

#### Voice Mode:
- [ ] Microphone button visible
- [ ] Tap mic → permission prompt (first time)
- [ ] Speak → Little Nate responds with voice
- [ ] Voice indicator shows when Little Nate is speaking
- [ ] Can interrupt (tap to stop speaking)

#### Avatar (if Sovereign Circle tier):
- [ ] 3D avatar visible above chat
- [ ] Avatar expressions change during conversation
- [ ] Avatar "breathes" (idle animation)
- [ ] Avatar lip-syncs with voice

#### Context & Memory:
- [ ] Little Nate remembers conversation within session
- [ ] Can reference previous messages ("like you said earlier")
- [ ] Can see conversation history by scrolling up
- [ ] "New conversation" or "Clear chat" button (optional)

#### Expected Chat Responses:

**Test Message 1:** "Hello, I'm feeling stressed about work today"  
**Expected Response:** Empathetic acknowledgment, asks clarifying questions about stress source

**Test Message 2:** "What techniques can help me manage this stress?"  
**Expected Response:** Specific techniques (breathing exercises, cognitive reframing, grounding), tailored to previous context

**Test Message 3:** "Can you schedule a session for me?"  
**Expected Response:** Guides user to Schedule tab or offers to help book

---

## ⚙️ SETTINGS SECTIONS TO VERIFY

### Location: Settings icon (usually gear icon in top-right)

### 1. Profile Tab:
```
Expected Fields:
- Full Name: [editable]
- Email: [editable]
- Phone: [editable]
- Profile Picture: [upload button]
- Bio: [text area]
- Assigned Coach: "Audit Lawyer 1" [read-only]
```

### 2. Account Tab:
```
Expected Options:
- Change Password [button]
- Export My Data [button]
- Delete Account [button, red]
- Account Created: [date]
- Last Login: [date]
```

### 3. Notifications Tab:
```
Expected Toggles:
- Email Notifications [toggle]
- Push Notifications [toggle]
- Session Reminders [toggle]
- Coach Messages [toggle]
- Platform Updates [toggle]
```

### 4. Privacy & Security Tab:
```
Expected Options:
- Two-Factor Authentication [setup button]
- Active Sessions [list with "Log out" buttons]
- Consent Version: v13.0_2026 [view button]
- Data Sharing Preferences [toggles]
```

### 5. Billing & Subscription Tab:
```
Expected Display:
- Current Tier: [Threshold / Inner Chamber / Sovereign Circle]
- Subscription Status: [Active / Trial / Expired]
- Token Balance: [number] tokens
- Payment Methods: [list of cards/accounts]
- Billing History: [transaction list]
- Upgrade/Downgrade [buttons]
- Purchase Tokens [button]
```

### 6. Family/Dependents Tab (if applicable):
```
Expected:
- Add Dependent [button]
- Current Members: [list]
  - Name
  - Relationship
  - Tier
  - Actions (Remove, Edit)
```

---

## 📅 SCHEDULING FEATURES TO TEST

### Location: Schedule tab in navigation

### Calendar View:
- [ ] Current month displayed
- [ ] Next/previous month buttons
- [ ] Today's date highlighted
- [ ] Available slots shown in green/blue
- [ ] Booked sessions shown in gold
- [ ] Unavailable slots grayed out

### Booking Flow:
1. Click an available date/time slot
2. Dialog appears:
   - Coach Name: "Audit Lawyer 1"
   - Session Type: [dropdown: Private / Family / Group]
   - Duration: [15 / 30 / 45 / 60 minutes]
   - Price: $X.XX (or "Included in subscription")
   - Notes: [text field]
3. "Confirm Booking" button
4. Confirmation screen:
   - Session details
   - Zoom link (or "Link will be sent via email")
   - "Add to Calendar" button

### Session Management:
- [ ] View upcoming sessions
- [ ] Cancel session (with confirmation)
- [ ] Reschedule session
- [ ] Join Zoom meeting (button appears 5 min before start)

---

## 📊 METRICS TAB (if present)

### Expected Visualizations:
1. **Emotional Coherence Score**
   - Line graph over time
   - Current score (0-100)
   - Trend indicator (↑ ↓ →)

2. **Mood Tracking**
   - Heatmap or line chart
   - Daily mood entries
   - Pattern analysis

3. **Engagement Score**
   - Bar chart
   - Session frequency
   - Active days

4. **Breakthrough Moments**
   - Timeline of significant insights
   - AI-identified patterns

### Interaction:
- [ ] Can zoom into date ranges
- [ ] Can export data
- [ ] Tooltips on hover/tap
- [ ] "Learn More" buttons for each metric

---

## 👨‍👩‍👧 FAMILY SANCTUARY (if applicable)

### Expected Features:
- [ ] List of family members
- [ ] Each member's wellness score
- [ ] Group session scheduling
- [ ] Private vs shared conversations toggle
- [ ] Family metrics overview

---

## 🎨 VISUAL DESIGN VERIFICATION

### Color Palette (from .cursorrules):
- **Background:** Very dark gray (#050505, #0A0A0A, #111111)
- **Primary Accent:** Gold (#C9A962)
- **Secondary Accent:** Cyan (#4ECDC4) for AI features
- **Alerts:** Red (#EF4444)
- **Success:** Green (not specified, likely #22C55E)

### Typography:
- **Headers:** Cormorant Garamond (elegant serif)
- **Body:** DM Sans (clean sans-serif)
- **Sizes:** Readable, not too small (<14px is concerning)

### Layout:
- **Spacing:** Generous padding, not cramped
- **Cards:** Rounded corners (8-12px)
- **Shadows:** Subtle elevation effects
- **Icons:** Consistent style (likely outlined or duotone)

### Animation:
- **Avatar:** Breathing animation (slow pulse)
- **Transitions:** Smooth (200-300ms)
- **Loading:** Elegant spinners, not jarring
- **Micro-interactions:** Hover effects, button feedback

---

## 🔍 PERFORMANCE BENCHMARKS

### Load Times (from cold start):
- **Login Screen:** < 2 seconds
- **Chat Interface:** < 3 seconds
- **Settings Screen:** < 2 seconds
- **Calendar View:** < 3 seconds
- **First Chat Response:** < 5 seconds

### Interaction Responsiveness:
- **Button Press:** Instant feedback (<100ms)
- **Screen Transition:** < 300ms
- **Chat Send → Response:** < 3 seconds (depends on AI)
- **Scroll Smoothness:** 60fps (no janky)

### Network Efficiency:
- **WebSocket:** Maintains connection (no frequent reconnects)
- **REST API:** < 1 second per request
- **Image Loading:** Progressive (low-res → high-res)
- **Error Recovery:** Auto-retry with exponential backoff

---

## 🚨 COMMON UX ANTI-PATTERNS TO WATCH FOR

### Navigation Issues:
- ❌ No back button or way to return to previous screen
- ❌ Dead-end screens with no exit
- ❌ Inconsistent navigation (different on each screen)
- ❌ Hidden features (no way to discover them)

### Input Issues:
- ❌ Keyboard covers input field (mobile)
- ❌ No validation feedback ("invalid email" not shown)
- ❌ Can't submit on Enter key
- ❌ Text too small to read

### Feedback Issues:
- ❌ No loading indicator (user doesn't know if action worked)
- ❌ Generic error messages ("Error occurred")
- ❌ Success actions with no confirmation
- ❌ Silent failures (button does nothing)

### Visual Issues:
- ❌ Overlapping text
- ❌ Cut-off buttons (off-screen)
- ❌ Invisible text on background
- ❌ Misaligned elements

### Performance Issues:
- ❌ Stuttering animations
- ❌ Slow page transitions (>1 second)
- ❌ Unresponsive buttons (delay >500ms)
- ❌ Memory leaks (app slows down over time)

---

## 📸 SCREENSHOT TARGETS

### Must-Capture Screenshots:
1. **Login screen** (before entering credentials)
2. **Chat interface** (with example conversation)
3. **Settings home** (list of settings sections)
4. **Profile settings** (showing coach assignment)
5. **Billing/subscription** (showing tier and token balance)
6. **Calendar view** (showing availability)
7. **Booking dialog** (showing coach name and options)
8. **Any errors** (critical to document)
9. **Mobile viewport** (if testing on different sizes)
10. **Navigation bar/menu** (showing all options)

---

## 🎯 PRIORITY TESTING ORDER

### Phase 1 - Critical Path (15 minutes):
1. Login
2. Accept consent (if prompted)
3. Send 2-3 chat messages
4. Navigate to Settings
5. Check Profile and Billing sections

### Phase 2 - Core Features (20 minutes):
6. Test scheduling flow (book a session)
7. Check calendar view
8. Navigate through all settings sections
9. Test voice mode (if microphone available)
10. Check metrics/dashboard (if present)

### Phase 3 - Edge Cases (15 minutes):
11. Multi-screen flow (chat → schedule → settings → back to chat)
12. Try to break things (rapid clicking, back button spam)
13. Check responsiveness (resize browser window)
14. Test error states (disconnect WiFi, reconnect)
15. Final UX assessment (Steve Jobs "would I use this?" test)

---

**TOTAL EXPECTED TEST TIME: ~50 minutes**
