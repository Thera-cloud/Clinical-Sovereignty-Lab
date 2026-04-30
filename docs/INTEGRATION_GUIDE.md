> **SUPERSEDED — DO NOT FOLLOW THIS GUIDE.** This document references 
> architecture that has been replaced (main_hybrid.dart → main.dart, 
> bridge_server_hybrid.py → bridge_server.py, CoachPortalScreen → 
> CoachDashboardScreenV2 in updated_screens.dart, etc). 
> 
> Confirmed superseded by reconciliation audit 2026-04-30. 
> Kept only for historical reference. See docs/OPEN_TODOS.md for 
> current open work and current production architecture for 
> integration patterns.

# Little Nate Coach Portal v2.0 - Integration Guide

## Phase 1 Deliverables

This package contains the enhanced Coach Portal with all features from the HTML mockups:

### Files Delivered

1. **`coach_portal_v2_complete.dart`** (1,815 lines)
   - Complete Flutter/Dart implementation of Coach Portal
   - Tab navigation (Clients, Calendar, Sessions, Nate AI)
   - All screens and dialogs

2. **`bridge_handlers_v2.py`** (810 lines)
   - New message handlers for bridge server
   - CoachNexusV2 class with all backend logic

---

## Features Implemented

### ✅ Tab Navigation System
- Bottom tab bar matching cp_01_dashboard.html and cp_02_calendar.html
- 4 tabs: Clients, Calendar, Sessions, Nate AI
- Active state highlighting with gold accent

### ✅ Clients Tab (cp_01_dashboard.html)
- Client cards with Top Tier badges
- Next session indicator
- Quick action buttons (Join Session, Ask Nate, Pre-Brief, History)
- Active client count badge

### ✅ Calendar Tab (cp_02_calendar.html)
- Full month grid view with navigation
- Day cells with session indicators (green dots)
- Today highlighting
- "Add Availability" button
- Today's sessions list with:
  - Confirmed/Pending status badges
  - Join/Cancel buttons
  - Platform indicator (Zoom/FaceTime)
  - Biometrics notice

### ✅ Sessions Tab (cp_05_top_tier_sessions.html)
- Recorded sessions list
- Filter chips (All, This Week, Family Only, Needs Review)
- Session cards with:
  - Top Tier star badges
  - Family tags
  - Duration display
  - Meta info (Platform, Biometrics, AI analyzed)
  - "Get Coaching Advice" and "Playback" buttons

### ✅ Ask Nate Tab (cp_04_ask_nate.html)
- Client context selector
- Quick question chips
- Chat interface with:
  - Little Nate avatar (two eyes)
  - User bubbles (gold)
  - Nate bubbles (cyan border)
  - Typing indicator
- Data sources badges

### ✅ Pre-Session Brief Screen (cp_07_presession_brief.html)
- Session alert banner with Join button
- Client profile with Top Tier badge
- Recent AI Session Mood indicator
- Topics to Address (color-coded dots)
- Recent Breakthroughs
- Family Context cards with relationship notes
- Little Nate's Suggestion card

### ✅ Coaching Advice Screen (cp_06_coaching_advice.html)
- Session context header
- Key Observations card
- Recommendation highlight box
- Session Biometrics bars (Engagement, Emotional Range, Stress, Openness)
- Notable Moments with timestamps
- Next Session Suggestions
- Save/Export action buttons

### ✅ Cancel Session Dialog (cp_03_cancel_session.html)
- Warning icon and title
- Session preview (Client, Date/Time, Type)
- Reason dropdown
- Email notification info box
- Reschedule link checkbox
- Go Back / Cancel Session buttons

### ✅ Scheduler Dialog (12_scheduler_dialog.png)
- Slot input field
- Publish Slot button

---

## Integration Steps

### 1. Update main_v1.dart

Replace the existing `CoachDashboardScreen` class with the new `CoachPortalScreen`:

```dart
// In LobbyScreen._handlePacket(), change:
if (role == 'COACH') {
  nextScreen = CoachPortalScreen(  // Changed from CoachDashboardScreen
    currentUserProfile: profile,
    username: _tempUser,
    password: _tempPass,
  );
}
```

### 2. Update bridge_server_hybrid_v1.py

Add the new imports and initialize CoachNexusV2:

```python
# After existing imports, add:
from bridge_handlers_v2 import CoachNexusV2

# After existing initializations:
coach_nexus_v2 = CoachNexusV2(VAULT_ROOT)
```

Add the new message handlers inside the `async for msg in websocket:` loop:

```python
# Copy all handlers from bridge_handlers_v2.py's docstring
elif msg_type == "fetch_coach_calendar":
    # ... (see bridge_handlers_v2.py)
```

### 3. Required Imports for Dart

Ensure these imports are at the top of the combined file:

```dart
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'dart:async';
```

---

## Testing Checklist

- [ ] Login as COACH role
- [ ] Verify tab navigation works
- [ ] Check Clients tab displays assigned clients
- [ ] Test Calendar month navigation
- [ ] Verify today's sessions display
- [ ] Test "Add Availability" dialog
- [ ] Navigate to Pre-Session Brief from client card
- [ ] Test Ask Nate quick questions
- [ ] View Sessions tab recordings
- [ ] Open Coaching Advice screen
- [ ] Test Cancel Session dialog
- [ ] Verify socket messages are sent/received

---

## Phase 2 Features (Future)

The following features are ready for Phase 2 development:

1. **Video Session Integration** - Actual Zoom/FaceTime launch
2. **Biometrics Processing** - Real-time voice/video analysis
3. **Family Relationship Mapping** - Visual family tree
4. **Recording Playback** - Audio/video player component
5. **AI Analysis Pipeline** - Integration with Azure for session analysis
6. **Push Notifications** - Session reminders, client updates

---

## Color Palette Reference

| Element | Color | Hex |
|---------|-------|-----|
| Gold/Primary | ![#FFD700](https://via.placeholder.com/15/FFD700/000000?text=+) | `#FFD700` |
| Cyan/Nate | ![#00FFFF](https://via.placeholder.com/15/00FFFF/000000?text=+) | `#00FFFF` |
| Purple/Advice | ![#9C27B0](https://via.placeholder.com/15/9C27B0/000000?text=+) | `#9C27B0` |
| Green/Positive | ![#4CAF50](https://via.placeholder.com/15/4CAF50/000000?text=+) | `#4CAF50` |
| Orange/Caution | ![#FF9800](https://via.placeholder.com/15/FF9800/000000?text=+) | `#FF9800` |
| Red/Danger | ![#F44336](https://via.placeholder.com/15/F44336/000000?text=+) | `#F44336` |
| Background | ![#0A0A0A](https://via.placeholder.com/15/0A0A0A/000000?text=+) | `#0A0A0A` |
| Card | ![#1A1A1A](https://via.placeholder.com/15/1A1A1A/000000?text=+) | `#1A1A1A` |

---

## Support

For questions or issues, refer to:
- Original HTML mockups in `/mnt/project/cp_*.html`
- UX screenshots in `/mnt/project/*.png`
- Existing code in `main_v1.dart` and `bridge_server_hybrid_v1.py`
