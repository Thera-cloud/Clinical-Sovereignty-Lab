import 'dart:convert';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:home_widget/home_widget.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

const _appGroupId = 'group.net.sovereignsanctuary.littlenate';
const _iOSWidgetName = 'NateWidget';
const _androidWidgetName = 'NateWidgetProvider';

class NateWidgetService {
  NateWidgetService._();

  static Future<void> initialize() async {
    if (kIsWeb) return;
    HomeWidget.setAppGroupId(_appGroupId);
    HomeWidget.registerInteractivityCallback(backgroundCallback);
  }

  static Future<void> fetchAndUpdate(String token) async {
    if (kIsWeb) return;
    try {
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/sse-client/widget');
      final resp = await http.get(uri, headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      }).timeout(const Duration(seconds: 10));
      if (resp.statusCode != 200) return;

      final data = json.decode(resp.body) as Map<String, dynamic>;
      await HomeWidget.saveWidgetData<String>('widget_type', data['type'] ?? 'single_word');
      await HomeWidget.saveWidgetData<String>('widget_primary_text', data['primary_text'] ?? 'Breathe');
      await HomeWidget.saveWidgetData<String>('widget_secondary_text', data['secondary_text'] ?? '');
      await HomeWidget.saveWidgetData<String>('widget_background_color', data['background_color'] ?? '#1a2332');

      final imageUrl = data['image_url'] as String? ?? '';
      await HomeWidget.saveWidgetData<String>('widget_image_url', imageUrl);
      if (imageUrl.isNotEmpty) {
        try {
          final imgResp = await http.get(Uri.parse(imageUrl)).timeout(const Duration(seconds: 15));
          if (imgResp.statusCode == 200) {
            await HomeWidget.saveWidgetData<String>(
                'widget_image_data', base64Encode(imgResp.bodyBytes));
          }
        } catch (_) {}
      } else {
        await HomeWidget.saveWidgetData<String>('widget_image_data', '');
      }
      await HomeWidget.saveWidgetData<String>('widget_action', data['action'] ?? 'open_chat');
      await HomeWidget.saveWidgetData<String>('widget_action_id', data['action_id'] ?? '');

      await HomeWidget.updateWidget(
        iOSName: _iOSWidgetName,
        androidName: _androidWidgetName,
      );
    } catch (_) {
      // Keep existing cached data on failure
    }
  }

  static Future<void> handleWidgetAction(Uri? uri) async {
    // Widget taps route through the app's deep link handler
    if (uri == null) return;
  }
}

@pragma('vm:entry-point')
Future<void> backgroundCallback(Uri? uri) async {
  // Called when the widget is tapped — handled by the app's main routing
}
