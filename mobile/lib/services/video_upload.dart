/// Conditional export: uses the web implementation when dart:html is available,
/// otherwise falls back to the stub.
library;
export 'video_upload_stub.dart'
    if (dart.library.html) 'video_upload_web.dart';
