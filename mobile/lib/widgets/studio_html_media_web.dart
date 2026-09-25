import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';
import 'studio_media_handle.dart';

class StudioHtmlMediaPlayer extends StatefulWidget {
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
  State<StudioHtmlMediaPlayer> createState() => _StudioHtmlMediaPlayerState();
}

class _StudioHtmlMediaPlayerState extends State<StudioHtmlMediaPlayer> {
  late final String _viewType;
  html.MediaElement? _el;
  bool _playing = false;

  @override
  void initState() {
    super.initState();
    _viewType = 'studio-trim-${identityHashCode(this)}';
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int id) {
      late final html.MediaElement el;
      if (widget.isAudio) {
        el = html.AudioElement()..controls = widget.showNativeControls;
      } else {
        final video = html.VideoElement()..controls = widget.showNativeControls;
        video.style.objectFit = 'contain';
        el = video;
      }
      el.style.width = '100%';
      el.style.height = '100%';
      el.style.backgroundColor = '#050505';
      el.setAttribute('playsinline', 'true');
      el.src = widget.url;
      el.onLoadedMetadata.listen((_) {
        final d = el.duration.toDouble();
        if (d.isFinite) widget.onDuration?.call(d);
      });
      el.onTimeUpdate.listen((_) {
        final t = el.currentTime.toDouble();
        widget.onTime?.call(t);
        final end = widget.loopEnd;
        if (end != null && t >= end - 0.04) {
          el.pause();
          _playing = false;
        }
      });
      el.onPlay.listen((_) => _playing = true);
      el.onPause.listen((_) => _playing = false);
      _el = el;
      return el;
    });
    final h = widget.handle;
    if (h != null) {
      h.play = () {
        _el?.play();
        _playing = true;
      };
      h.pause = () {
        _el?.pause();
        _playing = false;
      };
      h.seek = (t) {
        if (_el != null) _el!.currentTime = t;
      };
      h.playing = () => _playing;
    }
  }

  @override
  void didUpdateWidget(covariant StudioHtmlMediaPlayer old) {
    super.didUpdateWidget(old);
    if (old.url != widget.url && _el != null) {
      _el!.src = widget.url;
      _el!.load();
    }
    if (old.loopStart != widget.loopStart &&
        widget.loopStart != null &&
        _el != null) {
      _el!.currentTime = widget.loopStart!;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.url.isEmpty) {
      return const ColoredBox(
        color: Color(0xFF0A0A0A),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.play_circle_filled, color: Color(0xFFC9A962), size: 56),
              SizedBox(height: 8),
              Text('Select Media',
                  style: TextStyle(
                      color: Color(0xFF8B7355),
                      fontSize: 28,
                      fontWeight: FontWeight.w300)),
            ],
          ),
        ),
      );
    }
    return HtmlElementView(viewType: _viewType);
  }
}
