---
name: Settings gear for users
overview: Add a settings gear icon to both the client (Flutter mobile) and coach (Flutter mobile + web dashboard) UX, with role-appropriate settings screens backed by existing and new WebSocket handlers.
todos:
  - id: flutter-client-settings
    content: Create ClientSettingsScreen in Flutter with profile, preferences, subscription, privacy, and about sections
    status: pending
  - id: flutter-coach-settings
    content: Create CoachSettingsScreen in Flutter with profile, practice/fees, tax, preferences, subscription, and about sections
    status: pending
  - id: flutter-gear-icons
    content: Add gear icon to NeuralInterfaceV2 and CoachPortalV2 app bars
    status: pending
  - id: dashboard-settings-html
    content: Create settings.html for coach web dashboard with all coach settings sections
    status: pending
  - id: dashboard-gear-icon
    content: Add gear icon to command.html header linking to settings.html
    status: pending
  - id: backend-new-handlers
    content: "Add WS handlers: update_coach_profile, update_notification_prefs, update_voice_preference, request_data_export, request_account_deletion"
    status: pending
isProject: false
---

# Settings Gear Icon — Coach and Client UX

## Entry Points

### Client (Flutter Mobile — `NeuralInterfaceV2`)

- Add a gear icon to the app bar (top-right, next to existing controls)
- Tapping opens a `ClientSettingsScreen`

### Coach (Flutter Mobile — `CoachPortalV2`)

- Add a gear icon to the app bar (top-right)
- Tapping opens a `CoachSettingsScreen`

### Coach (Web Dashboard — `command.html` header)

- Add a gear icon button in the header bar (next to "Export Report" / "Refresh Data")
- Opens `settings.html` (new dashboard page)

---

## Client Settings Screen


| Section | Fields | Backend Support |
| ------- | ------ | --------------- |


### 1. Profile

- **Name** (display only — admin-editable)
- **Email** (editable — `update_profile` handler exists)
- **Phone** (editable — `update_profile` handler exists)
- **Emergency Contact** (editable — `update_profile` handler exists)
- **Profile Photo** (editable — `update_profile` handler exists)

### 2. Preferences

- **Timezone** (editable — `update_profile` handler exists, default "America/New_York")
- **Notification preferences** (NEW — needs handler: push on/off, session reminders, crisis alerts)
- **Voice mode default** (NEW — needs handler: auto-enable voice on session start)

### 3. Subscription and Billing

- **Current plan** (read-only display: Threshold / Inner Chamber / Sovereign Circle)
- **Token balance** (read-only)
- **Token usage this month** (read-only)
- **Upgrade button** (links to tier selection / in-app purchase flow)

### 4. Privacy and Legal

- **Consent status** (read-only: version, date signed)
- **Data export request** (button — triggers backend job, NEW handler)
- **Delete account request** (button — triggers admin review, NEW handler)

### 5. About and Support

- **App version**
- **Help / FAQ link**
- **Contact support**
- **Logout button**

---

## Coach Settings Screen

### 1. Profile

- **Name** (display only — admin-editable)
- **Email** (editable — `update_profile`)
- **Phone** (editable — `update_profile`)
- **Specialties** (editable — NEW handler needed, stored as `specialties` TEXT[] in DB)
- **Coaching Style** (editable — NEW handler: directive / reflective / integrative)
- **Profile Photo** (editable — `update_profile`)
- **Zoom Link** (editable — NEW handler, field exists in profile JSON)

### 2. Practice and Fees

- **Coaching Fee** (editable — `coach_set_fee` handler exists)
- **Payment Mode** (editable — `coach_set_payment_mode` handler exists: "Platform Handles" vs "Coach Handles")
- **Platform Fee** (read-only: 30% or $30 min)

### 3. Tax and Compliance

- **W-9 Status** (read-only badge: Filed / Missing)
- **Submit W-9** (action — `coach_submit_w9` handler exists)
- **TIN Document** (upload status, read-only)
- **1099 Status** (read-only: "Required" if YTD >= $600)
- **Address Verification** (status + edit — partial handler exists)

### 4. Preferences

- **Timezone** (editable — `update_profile`)
- **Emergency Contact** (editable — `update_profile`)
- **Notification preferences** (NEW handler: new client alerts, session reminders, crisis alerts, Night School updates)

### 5. Subscription

- **Current plan/tier** (read-only)
- **Certification status** (read-only: Approved / Pending / Rejected)

### 6. Dojo (if applicable)

- **Selected Dojos** (read-only list)
- **Dojo discount / pricing** (read-only)

### 7. About and Support

- **App version**
- **Help / FAQ link**
- **Contact support**
- **Logout button**

---

## What already exists in the backend

Existing WebSocket handlers in [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py):

- `update_profile` — email, phone, timezone, emergency_contact, profile_photo_url
- `coach_set_fee` — coaching_fee
- `coach_set_payment_mode` — payment_mode
- `coach_submit_w9` — w9_submitted, w9_data

## New backend handlers needed

1. `update_coach_profile` — specialties, coaching_style, zoom_link
2. `update_notification_prefs` — per-role notification toggles
3. `update_voice_preference` — client voice mode default
4. `request_data_export` — triggers data export job
5. `request_account_deletion` — flags account for admin review

## Files to create/modify

- **Flutter**: New `settings_screen.dart` in `mobile/lib/screens/` with `ClientSettingsScreen` and `CoachSettingsScreen`
- **Flutter**: Add gear icon to `updated_screens.dart` (NeuralInterfaceV2 app bar) and `coach_portal_v2_complete.dart` (CoachPortal app bar)
- **Dashboard**: New `settings.html` for coach web settings
- **Dashboard**: Add gear icon to `command.html` header
- **Backend**: Add new WS handlers in `bridge_server.py`

## Design

- Follow existing design system: `#050505` background, gold `#C9A962` accents, DM Sans body font
- Settings sections as expandable cards with section headers
- Toggle switches for boolean preferences
- Dropdown selectors for coaching_style, timezone
- Read-only fields shown with a lock icon or muted styling

