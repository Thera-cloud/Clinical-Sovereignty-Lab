// Used on web - opens URL in new tab via dart:html (no url_launcher)

import 'dart:html' as html;

void openDojoUrl(String url) {
  html.window.open(url, '_blank');
}
