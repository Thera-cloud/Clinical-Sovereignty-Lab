import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

Object? openStudioRoomPlaceholder() => null;

void navigateStudioRoomTab(Object? win, String url) {
  if (url.isEmpty) return;
  launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
}

class StudioLiveKitRoomEmbed extends StatelessWidget {
  final String src;
  const StudioLiveKitRoomEmbed({super.key, required this.src});

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
