import 'dart:html' as html;
import 'dart:js_util' as js_util;

Object? openPrintWindow() {
  return html.window.open('about:blank', 'coach_practice_print');
}

void writePrintHtml(Object? handle, String htmlDoc) {
  if (handle != null) {
    try {
      final doc = js_util.getProperty(handle, 'document');
      if (doc != null) {
        js_util.callMethod(doc, 'open', <Object>[]);
        js_util.callMethod(doc, 'write', <Object>[htmlDoc]);
        js_util.callMethod(doc, 'close', <Object>[]);
        return;
      }
    } catch (_) {}
  }
  final iframe = html.IFrameElement()
    ..srcdoc = htmlDoc
    ..setAttribute(
        'style', 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;');
  html.document.body?.append(iframe);
  iframe.onLoad.listen((_) {
    final win = iframe.contentWindow;
    if (win == null) return;
    try {
      js_util.callMethod(win, 'print', <Object>[]);
    } catch (_) {}
  });
}

void closePrintWindow(Object? handle) {
  if (handle == null) return;
  try {
    js_util.callMethod(handle, 'close', <Object>[]);
  } catch (_) {}
}
