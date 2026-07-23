import 'package:flutter/widgets.dart';

void setLnObserverIframePointerEvents(bool enabled) {}

void notifyLnObserverIframeAuth({
  required String token,
  required String hw,
  required String name,
  required String api,
  required String ws,
}) {}

void disposeLnObserverIframe() {}

void reloadLnObserverIframe() {}

Widget buildLnObserverIframe(String url) {
  return const Center(
    child: Text(
      'LN-Observer requires Flutter web.',
      style: TextStyle(color: Color(0xFF9d96bd)),
    ),
  );
}
