/// Coach interview mic. Web MediaRecorder, native `record`, else stub.
library;
export 'coach_web_recorder_stub.dart'
    if (dart.library.html) 'coach_web_recorder_web.dart'
    if (dart.library.io) 'coach_web_recorder_io.dart';
