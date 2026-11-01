/// Single source of truth for opening Stripe Checkout / Customer Portal /
/// other billing URLs from Flutter.
///
/// Why this exists: every Stripe redirect in the app shares the same flow
/// pattern — `await http.post(...)` followed by `launchUrl(url, externalApplication)`.
/// On Flutter Web that maps to `window.open(url, '_blank')` AFTER the user
/// gesture has been consumed by the awaited POST, which mobile Safari and
/// Chrome silently popup-block. The user clicks "Continue to Payment" and
/// nothing happens.
///
/// The fix is to navigate the current tab on Web instead. Same-tab redirects
/// are never blocked because they don't require a fresh user gesture.
///
/// Usage:
/// ```
/// final ok = await launchCheckoutUrl(checkoutUrl);
/// if (!ok) showSnackBar('Could not open payment page');
/// ```
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:url_launcher/url_launcher.dart';
import 'checkout_href.dart';

/// Open a billing URL (Stripe Checkout, Stripe Customer Portal, etc.).
///
/// On Flutter Web this assigns `window.location` (same tab). `url_launcher`'s
/// `window.open` is silently blocked on Safari/Chrome even with `_self`.
/// Native iOS / Android / desktop uses `LaunchMode.externalApplication`.
///
/// Returns `true` if the navigation/launch succeeded.
Future<bool> launchCheckoutUrl(String url) async {
  if (url.isEmpty) return false;
  if (kIsWeb) {
    return openCheckoutHref(url);
  }
  final uri = Uri.tryParse(url);
  if (uri == null) return false;
  return launchUrl(uri, mode: LaunchMode.externalApplication);
}
