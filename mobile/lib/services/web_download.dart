/// Conditional export: uses the web implementation when dart:html is available,
/// otherwise falls back to the stub.
export 'web_download_stub.dart'
    if (dart.library.html) 'web_download_web.dart';
