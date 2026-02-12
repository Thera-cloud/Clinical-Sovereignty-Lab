import 'dart:convert';
import 'dart:io';

import 'debug_logger_iface.dart';

class DebugLoggerImpl implements DebugLogger {
  static const _logPath =
      '/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/.cursor/debug.log';

  @override
  Future<void> log(Map<String, dynamic> payload) async {
    try {
      final line = jsonEncode(payload);
      File(_logPath).writeAsStringSync('$line\n',
          mode: FileMode.append, flush: true);
    } catch (_) {}
  }
}
