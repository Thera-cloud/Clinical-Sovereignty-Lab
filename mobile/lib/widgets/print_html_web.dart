import 'dart:html' as html;
import 'dart:js_util' as js_util;

Object? openPrintWindow() {
  return html.window.open('about:blank', 'coach_practice_print');
}

bool _assignBlob(Object handle, String url) {
  try {
    final loc = js_util.getProperty(handle, 'location');
    if (loc != null) {
      js_util.setProperty(loc, 'href', url);
      return true;
    }
  } catch (_) {}
  return false;
}

void writePrintHtml(Object? handle, String htmlDoc) {
  final blob = html.Blob(<Object>[htmlDoc], 'text/html');
  final url = html.Url.createObjectUrlFromBlob(blob);
  if (handle != null && _assignBlob(handle, url)) {
    return;
  }
  closePrintWindow(handle);
  final iframe = html.IFrameElement()
    ..src = url
    ..setAttribute(
        'style', 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;');
  html.document.body?.append(iframe);
  iframe.onLoad.listen((_) {
    final win = iframe.contentWindow;
    if (win != null) {
      try {
        js_util.callMethod(win, 'print', <Object>[]);
      } catch (_) {}
    }
    Future<void>.delayed(const Duration(seconds: 60), () {
      iframe.remove();
      html.Url.revokeObjectUrl(url);
    });
  });
}

void closePrintWindow(Object? handle) {
  if (handle == null) return;
  try {
    js_util.callMethod(handle, 'close', <Object>[]);
  } catch (_) {}
}
