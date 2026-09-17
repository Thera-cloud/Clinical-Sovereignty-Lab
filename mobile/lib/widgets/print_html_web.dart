import 'dart:html' as html;
import 'dart:js_util' as js_util;

/// Print uses a hidden iframe only. A click-opened about:blank stays empty
/// after the report fetch and becomes a leftover tab next to the print dialog.
Object? openPrintWindow() => null;

void writePrintHtml(Object? handle, String htmlDoc) {
  closePrintWindow(handle);
  final blob = html.Blob(<Object>[htmlDoc], 'text/html');
  final url = html.Url.createObjectUrlFromBlob(blob);
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
