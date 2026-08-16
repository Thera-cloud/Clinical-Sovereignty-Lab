/// Browser mic for coach interview. Stub on non-web.
library;
export 'coach_web_recorder_stub.dart'
    if (dart.library.html) 'coach_web_recorder_web.dart';
