import 'debug_logger_iface.dart';
import 'debug_logger_stub.dart'
    if (dart.library.html) 'debug_logger_web.dart'
    if (dart.library.io) 'debug_logger_io.dart';

DebugLogger getDebugLogger() => DebugLoggerImpl();
