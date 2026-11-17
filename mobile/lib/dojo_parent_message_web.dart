import 'dart:html' as html;
import 'package:flutter/foundation.dart';

VoidCallback registerDojoBackListener(void Function() onBack, {void Function()? onCoachNate}) {
  void handler(html.Event e) {
    final ev = e as html.MessageEvent;
    final data = ev.data;
    if (data is Map && data['type'] == 'ln_dojo_back') {
      onBack();
    } else if (data is Map && data['type'] == 'ln_open_coach_nate') {
      if (onCoachNate != null) onCoachNate();
    }
  }

  html.window.addEventListener('message', handler);
  return () => html.window.removeEventListener('message', handler);
}
