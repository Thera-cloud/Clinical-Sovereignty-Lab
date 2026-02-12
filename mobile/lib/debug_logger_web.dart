import 'debug_logger_iface.dart';

/// Debug logger for web - disabled in production builds.
/// The local development server (127.0.0.1:7242) is only available during development.
/// To enable debug logging, set kDebugMode = true and run a local ingest server.
class DebugLoggerImpl implements DebugLogger {
  // Set to true only during local development with an ingest server running
  static const bool kDebugMode = false;

  @override
  Future<void> log(Map<String, dynamic> payload) async {
    // No-op in production to avoid ERR_CONNECTION_REFUSED errors
    // Debug logging is disabled unless kDebugMode is true
    if (!kDebugMode) return;
    
    // Development-only logging would go here
    // ignore: avoid_print
    print('[DEBUG] ${payload.toString()}');
  }
}
