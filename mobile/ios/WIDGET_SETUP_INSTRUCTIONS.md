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

## Known Issue

The `StaticConfiguration` in `NateWidget.swift` currently renders `NateWidgetSmallView`
for both `.systemSmall` and `.systemMedium` families. `NateWidgetMediumView` exists but
is not wired. To fix, update the configuration closure to check the widget family:

```swift
StaticConfiguration(kind: kind, provider: NateTimelineProvider()) { entry in
    if #available(iOS 17.0, *) {
        switch entry.widgetFamily {
        case .systemMedium: NateWidgetMediumView(entry: entry).containerBackground(entry.backgroundColor, for: .widget)
        default: NateWidgetSmallView(entry: entry).containerBackground(entry.backgroundColor, for: .widget)
        }
    } else {
        NateWidgetSmallView(entry: entry)
    }
}
```

This requires adding `@Environment(\.widgetFamily) var widgetFamily` to `NateWidgetEntry`
or passing the family through the provider. Deferred to post-Xcode-setup.

## Pre-Flight Checklist

- [ ] Runner.xcworkspace opens without errors
- [ ] NateWidget target added with correct bundle ID (`net.sovereignsanctuary.littlenate.NateWidget`)
- [ ] App Group `group.net.sovereignsanctuary.littlenate` added to BOTH Runner and NateWidget
- [ ] Our Swift files dragged into NateWidget group (Copy items unchecked, target NateWidget checked)
- [ ] Xcode auto-generated template files deleted from NateWidget group
- [ ] Deployment target matches Runner (iOS 15.0)
- [ ] Build succeeds on device (no signing or compilation errors)
- [ ] Widget appears in widget gallery as "Sovereign Sanctuary"
