import 'dart:html' as html;

/// Same-tab navigation. Never popup-blocked (unlike window.open / url_launcher).
bool openCheckoutHref(String url) {
  html.window.location.assign(url);
  return true;
}
