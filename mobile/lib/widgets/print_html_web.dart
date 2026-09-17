import 'dart:html' as html;

void openPrintHtml(String htmlDoc) {
  final blob = html.Blob([htmlDoc], 'text/html');
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.window.open(url, '_blank');
}
