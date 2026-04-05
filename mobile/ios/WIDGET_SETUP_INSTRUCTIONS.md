# NateWidget — Xcode Setup Instructions

These steps must be performed manually in Xcode. They cannot be automated.

## Prerequisites

- Xcode 15+ installed
- Apple Developer Team: LKSHXV9K95
- CocoaPods dependencies resolved (`cd ios && pod install`)

## Steps

1. **Open the workspace**
   `mobile/ios/Runner.xcworkspace` (NOT `Runner.xcodeproj`)

2. **Add Widget Extension target**
   File > New > Target > Widget Extension
   - Product Name: `NateWidget`
   - Team: LKSHXV9K95
   - Bundle Identifier: `net.sovereignsanctuary.littlenate.NateWidget`
   - Include Configuration Intent: NO
   - Include Live Activity: NO

3. **Activate scheme** — when prompted "Activate NateWidget scheme?" click Activate.

4. **Delete Xcode template files** — Xcode auto-generates placeholder Swift files.
   Delete from the NateWidget group: `NateWidget.swift`, `NateWidgetBundle.swift`,
   `Assets.xcassets` (if created by Xcode template).

5. **Add our widget files** — drag these into the NateWidget group in Xcode:
   - `mobile/ios/NateWidget/NateWidget.swift`
   - `mobile/ios/NateWidget/NateWidgetBundle.swift`
   Ensure "Copy items if needed" is unchecked and target NateWidget is checked.

6. **Add App Groups to both targets**
   - Select **Runner** target > Signing & Capabilities > + Capability > App Groups
     Add: `group.net.sovereignsanctuary.littlenate`
   - Select **NateWidget** target > Signing & Capabilities > + Capability > App Groups
     Add: `group.net.sovereignsanctuary.littlenate`

7. **Set deployment target** — select NateWidget target > General > Minimum Deployments.
   Match Runner's iOS deployment target (currently iOS 15.0).

8. **Build and run** on a physical device. Long-press the home screen, tap +,
   search "Sovereign Sanctuary" to verify the widget appears in the gallery.
