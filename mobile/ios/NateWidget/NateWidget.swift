import WidgetKit
import SwiftUI

struct NateWidgetEntry: TimelineEntry {
    let date: Date
    let type: String
    let primaryText: String
    let secondaryText: String
    let backgroundColor: Color
    let action: String
    let actionId: String
}

struct NateTimelineProvider: TimelineProvider {
    private let defaults = UserDefaults(suiteName: "group.net.sovereignsanctuary.littlenate")

    func placeholder(in context: Context) -> NateWidgetEntry {
        NateWidgetEntry(date: .now, type: "single_word", primaryText: "Breathe",
                        secondaryText: "", backgroundColor: Color(hex: "#1a2332"),
                        action: "open_chat", actionId: "")
    }

    func getSnapshot(in context: Context, completion: @escaping (NateWidgetEntry) -> Void) {
        completion(readEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NateWidgetEntry>) -> Void) {
        let entry = readEntry()
        let next = Calendar.current.date(byAdding: .minute, value: 30, to: .now)!
        completion(Timeline(entries: [entry], policy: .after(next)))
    }

    private func readEntry() -> NateWidgetEntry {
        let d = defaults
        let type = d?.string(forKey: "widget_type") ?? "single_word"
        let primary = d?.string(forKey: "widget_primary_text") ?? "Breathe"
        let secondary = d?.string(forKey: "widget_secondary_text") ?? ""
        let bg = d?.string(forKey: "widget_background_color") ?? "#1a2332"
        let action = d?.string(forKey: "widget_action") ?? "open_chat"
        let actionId = d?.string(forKey: "widget_action_id") ?? ""
        return NateWidgetEntry(date: .now, type: type, primaryText: primary,
                               secondaryText: secondary, backgroundColor: Color(hex: bg),
                               action: action, actionId: actionId)
    }
}

// MARK: - Small Widget

struct NateWidgetSmallView: View {
    let entry: NateWidgetEntry

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            entry.backgroundColor
            VStack(alignment: .leading, spacing: 4) {
                Spacer()
                Text(entry.primaryText)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.white)
                    .lineLimit(3)
                if !entry.secondaryText.isEmpty {
                    Text(entry.secondaryText)
                        .font(.system(size: 11))
                        .foregroundColor(Color(hex: "#C9A962"))
                        .lineLimit(1)
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)

            Text("👁")
                .font(.system(size: 14))
                .padding(8)
                .opacity(0.6)
        }
        .widgetURL(URL(string: "littlenate://widget?action=\(entry.action)&id=\(entry.actionId)"))
    }
}

// MARK: - Medium Widget

struct NateWidgetMediumView: View {
    let entry: NateWidgetEntry

    var body: some View {
        HStack(spacing: 0) {
            // Left: biome gradient
            ZStack {
                entry.backgroundColor.opacity(0.8)
                LinearGradient(colors: [entry.backgroundColor, entry.backgroundColor.opacity(0.4)],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
                Text("👁")
                    .font(.system(size: 22))
                    .opacity(0.5)
            }
            .frame(maxWidth: .infinity)

            // Right: text content
            VStack(alignment: .leading, spacing: 6) {
                Spacer()
                Text(entry.primaryText)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.white)
                    .lineLimit(3)
                if !entry.secondaryText.isEmpty {
                    Text(entry.secondaryText)
                        .font(.system(size: 11))
                        .foregroundColor(Color(hex: "#C9A962"))
                        .lineLimit(1)
                }
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(entry.backgroundColor)
        .widgetURL(URL(string: "littlenate://widget?action=\(entry.action)&id=\(entry.actionId)"))
    }
}

// MARK: - Widget Configuration

struct NateWidget: Widget {
    let kind: String = "NateWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: NateTimelineProvider()) { entry in
            if #available(iOS 17.0, *) {
                NateWidgetSmallView(entry: entry)
                    .containerBackground(entry.backgroundColor, for: .widget)
            } else {
                NateWidgetSmallView(entry: entry)
            }
        }
        .configurationDisplayName("Sovereign Sanctuary")
        .description("Daily therapeutic touchpoint")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

// MARK: - Color hex extension

extension Color {
    init(hex: String) {
        let h = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: h).scanHexInt64(&int)
        let r, g, b: Double
        switch h.count {
        case 6:
            r = Double((int >> 16) & 0xFF) / 255
            g = Double((int >> 8) & 0xFF) / 255
            b = Double(int & 0xFF) / 255
        default:
            r = 0; g = 0; b = 0
        }
        self.init(red: r, green: g, blue: b)
    }
}
