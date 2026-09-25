import 'package:flutter/material.dart';
import 'studio_media_handle.dart';

class StudioHtmlMediaPlayer extends StatelessWidget {
  final String url;
  final bool isAudio;
  final double? loopStart;
  final double? loopEnd;
  final ValueChanged<double>? onDuration;
  final ValueChanged<double>? onTime;
  final StudioMediaHandle? handle;
  final bool showNativeControls;

  const StudioHtmlMediaPlayer({
    super.key,
    required this.url,
    this.isAudio = false,
    this.loopStart,
    this.loopEnd,
    this.onDuration,
    this.onTime,
    this.handle,
    this.showNativeControls = true,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFF0A0A0A),
      alignment: Alignment.center,
      child: Text(
        url.isEmpty
            ? 'Select Media'
            : 'Open Coach Command in a browser to preview media.',
        style: const TextStyle(color: Color(0xFF8B7355), fontSize: 12),
        textAlign: TextAlign.center,
      ),
    );
  }
}
