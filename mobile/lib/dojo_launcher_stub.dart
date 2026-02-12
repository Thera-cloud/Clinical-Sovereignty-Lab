// Used on mobile (iOS/Android) - opens URL via url_launcher

import 'package:url_launcher/url_launcher.dart';

void openDojoUrl(String url) {
  launchUrl(Uri.parse(url));
}
