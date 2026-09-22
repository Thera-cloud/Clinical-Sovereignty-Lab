import 'package:flutter/material.dart';

/// Thera-World panel image: tap to fullscreen pinch-zoom.
class TheraPanelImage extends StatelessWidget {
  final String url;
  final double height;
  final BorderRadius borderRadius;
  final bool showZoomHint;
  final VoidCallback? onZoomOpened;
  final VoidCallback? onZoomClosed;

  const TheraPanelImage({
    super.key,
    required this.url,
    this.height = 300,
    this.borderRadius = const BorderRadius.all(Radius.circular(12)),
    this.showZoomHint = true,
    this.onZoomOpened,
    this.onZoomClosed,
  });

  /// Fullscreen zoom on the root navigator so a vault sheet cannot trap the
  /// route, and so the chat ListView can restore scroll when this Future
  /// completes.
  static Future<void> openZoom(BuildContext context, String url) async {
    if (url.isEmpty) return;
    FocusManager.instance.primaryFocus?.unfocus();
    await Navigator.of(context, rootNavigator: true).push(
      PageRouteBuilder(
        opaque: true,
        barrierColor: Colors.black,
        pageBuilder: (_, __, ___) => TheraPanelZoomPage(url: url),
        transitionsBuilder: (_, anim, __, child) =>
            FadeTransition(opacity: anim, child: child),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (url.isEmpty) return const SizedBox.shrink();
    return SelectionContainer.disabled(
      child: GestureDetector(
        onTap: () async {
          onZoomOpened?.call();
          await openZoom(context, url);
          onZoomClosed?.call();
        },
        child: Stack(
          alignment: Alignment.bottomRight,
          children: [
            ClipRRect(
              borderRadius: borderRadius,
              child: Image.network(
                url,
                fit: BoxFit.cover,
                height: height,
                width: double.infinity,
                errorBuilder: (_, __, ___) => Container(
                  height: height,
                  color: Colors.black,
                  alignment: Alignment.center,
                  child: const Icon(Icons.broken_image_outlined,
                      color: Color(0xFF8B7355), size: 40),
                ),
              ),
            ),
            if (showZoomHint)
              Padding(
                padding: const EdgeInsets.all(8),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.55),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.zoom_in, color: Color(0xFFE8D5A3), size: 14),
                      SizedBox(width: 4),
                      Text('Tap to zoom',
                          style: TextStyle(
                              color: Color(0xFFE8D5A3), fontSize: 11)),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class TheraPanelZoomPage extends StatelessWidget {
  final String url;
  const TheraPanelZoomPage({super.key, required this.url});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SelectionContainer.disabled(
        child: Stack(
          children: [
            Center(
              child: InteractiveViewer(
                minScale: 0.8,
                maxScale: 5,
                panEnabled: true,
                scaleEnabled: true,
                child: Image.network(
                  url,
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => const Icon(
                      Icons.broken_image_outlined,
                      color: Color(0xFF8B7355),
                      size: 64),
                ),
              ),
            ),
            SafeArea(
              child: Align(
                alignment: Alignment.topRight,
                child: IconButton(
                  icon: const Icon(Icons.close, color: Colors.white, size: 28),
                  tooltip: 'Close',
                  onPressed: () => Navigator.pop(context),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
