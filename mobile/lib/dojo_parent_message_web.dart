import 'dart:html' as html;
import 'package:flutter/foundation.dart';

VoidCallback registerDojoBackListener(void Function() onBack) {
  void handler(html.Event e) {
    final ev = e as html.MessageEvent;
    final data = ev.data;
    if (data is Map && data['type'] == 'ln_dojo_back') {
      onBack();
    }
  }

  html.window.addEventListener('message', handler);
  return () => html.window.removeEventListener('message', handler);
}
