import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';

class StudioLiveKitRoomEmbed extends StatefulWidget {
  final String src;
  const StudioLiveKitRoomEmbed({super.key, required this.src});

  @override
  State<StudioLiveKitRoomEmbed> createState() => _StudioLiveKitRoomEmbedState();
}

class _StudioLiveKitRoomEmbedState extends State<StudioLiveKitRoomEmbed> {
  late final String _viewType;

  @override
  void initState() {
    super.initState();
    _viewType = 'studio-lk-${identityHashCode(this)}';
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int id) {
      final iframe = html.IFrameElement()
        ..src = widget.src
        ..allow = 'camera; microphone; autoplay; fullscreen'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%';
      return iframe;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (widget.src.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      height: 620,
      width: double.infinity,
      child: HtmlElementView(viewType: _viewType),
    );
  }
}
