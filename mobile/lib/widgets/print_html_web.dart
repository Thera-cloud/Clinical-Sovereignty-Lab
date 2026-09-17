import 'dart:html' as html;

Object? openPrintWindow() {
  return html.window.open('about:blank', 'coach_practice_print');
}

void writePrintHtml(Object? handle, String htmlDoc) {
  if (handle is html.Window) {
    handle.document.open();
    handle.document.write(htmlDoc);
    handle.document.close();
    return;
  }
  final iframe = html.IFrameElement()
    ..srcdoc = htmlDoc
    ..setAttribute(
        'style', 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;');
  html.document.body?.append(iframe);
  iframe.onLoad.listen((_) {
    iframe.contentWindow?.print();
  });
}

void closePrintWindow(Object? handle) {
  if (handle is html.Window) {
    try {
      handle.close();
    } catch (_) {}
  }
}
