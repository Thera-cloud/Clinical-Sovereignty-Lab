import WidgetKit
import SwiftUI
import UIKit

private let appGroupID = "group.net.sovereignsanctuary.littlenate"

struct NateEntry: TimelineEntry {
    let date: Date
    let widgetType: String
    let primaryText: String
    let secondaryText: String
    let backgroundColor: Color
    let imageURL: String?
}

struct NateProvider: TimelineProvider {
    func placeholder(in context: Context) -> NateEntry {
        NateEntry(date: .now, widgetType: "journey_panel", primaryText: "Your journey continues…",
                  secondaryText: "Open Sovereign Sanctuary", backgroundColor: Color(hex: "#0A0A0A"), imageURL: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (NateEntry) -> Void) {
        completion(readEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NateEntry>) -> Void) {
        let entry = readEntry()
        let next = Calendar.current.date(byAdding: .minute, value: 30, to: entry.date)!
        completion(Timeline(entries: [entry], policy: .after(next)))
    }

    private func readEntry() -> NateEntry {
        let defaults = UserDefaults(suiteName: appGroupID)
        let wType   = defaults?.string(forKey: "widget_type") ?? "journey_panel"
        let primary = defaults?.string(forKey: "widget_primary_text") ?? "Your journey continues…"
        let secondary = defaults?.string(forKey: "widget_secondary_text") ?? ""
        let bgHex   = defaults?.string(forKey: "widget_background_color") ?? "#0A0A0A"
        let imgURL  = defaults?.string(forKey: "widget_image_url")
        return NateEntry(date: .now, widgetType: wType, primaryText: primary,
                         secondaryText: secondary, backgroundColor: Color(hex: bgHex), imageURL: imgURL)
    }
}

// MARK: - Small Widget View

struct NateWidgetSmallView: View {
    let entry: NateEntry

    var body: some View {
        ZStack {
            entry.backgroundColor
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Spacer()
                    Text("👁👁")
                        .font(.system(size: 14))
                        .opacity(0.6)
                }
                Spacer()
                Text(entry.primaryText)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.white)
                    .lineLimit(3)
            }
            .padding(12)
        }
    }
}

// MARK: - Medium Widget View

struct NateWidgetMediumView: View {
    let entry: NateEntry

    var body: some View {
        ZStack {
            entry.backgroundColor
            HStack(spacing: 12) {
                if let urlStr = entry.imageURL, let url = URL(string: urlStr),
                   let data = try? Data(contentsOf: url), let uiImage = UIImage(data: data) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: 120)
                        .clipped()
                        .cornerRadius(8)
                } else {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.white.opacity(0.08))
                        .frame(width: 120)
                        .overlay(
                            Text("👁👁")
                                .font(.system(size: 24))
                                .opacity(0.4)
                        )
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text(entry.primaryText)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(.white)
                        .lineLimit(3)
                    if !entry.secondaryText.isEmpty {
                        Text(entry.secondaryText)
                            .font(.system(size: 12))
                            .foregroundColor(Color(hex: "#8B7355"))
                            .lineLimit(2)
                    }
                    Spacer()
                }
                .padding(.vertical, 12)
                Spacer()
            }
            .padding(.leading, 12)
        }
    }
}

// MARK: - Widget Definition

struct NateWidget: Widget {
    let kind = "NateWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: NateProvider()) { entry in
            NateWidgetEntryView(entry: entry)
                .containerBackground(entry.backgroundColor, for: .widget)
        }
        .configurationDisplayName("Sovereign Sanctuary")
        .description("Daily therapeutic touchpoint")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

struct NateWidgetEntryView: View {
    @Environment(\.widgetFamily) var family
    let entry: NateEntry

    var body: some View {
        switch family {
        case .systemMedium:
            NateWidgetMediumView(entry: entry)
        default:
            NateWidgetSmallView(entry: entry)
        }
    }
}

// MARK: - Color Hex Extension

extension Color {
    init(hex: String) {
        let h = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        var rgb: UInt64 = 0
        Scanner(string: h).scanHexInt64(&rgb)
        let r = Double((rgb >> 16) & 0xFF) / 255
        let g = Double((rgb >> 8) & 0xFF) / 255
        let b = Double(rgb & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

#if DEBUG
struct NateWidget_Previews: PreviewProvider {
    static var previews: some View {
        let entry = NateEntry(date: .now, widgetType: "journey_panel",
                              primaryText: "A quiet path opens through the dark forest…",
                              secondaryText: "Tap to continue your journey",
                              backgroundColor: Color(hex: "#0A0A0A"), imageURL: nil)
        NateWidgetSmallView(entry: entry)
            .previewContext(WidgetPreviewContext(family: .systemSmall))
        NateWidgetMediumView(entry: entry)
            .previewContext(WidgetPreviewContext(family: .systemMedium))
    }
}
#endif
