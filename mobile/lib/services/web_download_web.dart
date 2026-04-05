// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:convert';
import 'package:http/http.dart' as http;

/// Triggers a browser file download for the given [content] and [filename].
void downloadFileToDevice(String content, String filename) {
  final bytes = utf8.encode(content);
  final blob = html.Blob([bytes], 'text/plain');
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.AnchorElement(href: url)..download = filename..click();
  html.Url.revokeObjectUrl(url);
}

/// Fetches a remote URL as bytes, creates a blob, and triggers a save dialog.
Future<void> downloadUrlToDevice(String remoteUrl, String filename) async {
  final response = await http.get(Uri.parse(remoteUrl));
  final blob = html.Blob([response.bodyBytes], 'image/png');
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.AnchorElement(href: url)..download = filename..click();
  html.Url.revokeObjectUrl(url);
}
