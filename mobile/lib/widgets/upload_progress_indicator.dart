// =============================================================================
// UPLOAD PROGRESS INDICATOR — Compact bar for file uploads
// Gold progress bar, filename, cancel, success/error states
// =============================================================================

import 'package:flutter/material.dart';

class _ProgressDesign {
  static const gold = Color(0xFFC9A962);
  static const red = Color(0xFFEF4444);
  static const green = Color(0xFF00FF88);
  static const bgElevated = Color(0xFF111111);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
}

/// State for an upload operation.
class UploadProgressState {
  final bool isIdle;
  final bool isUploading;
  final bool isSuccess;
  final bool isError;
  final String filename;
  final double progress;
  final String? errorMessage;

  const UploadProgressState._({
    this.isIdle = false,
    this.isUploading = false,
    this.isSuccess = false,
    this.isError = false,
    this.filename = '',
    this.progress = 0,
    this.errorMessage,
  });

  factory UploadProgressState.idle() =>
      const UploadProgressState._(isIdle: true);

  factory UploadProgressState.uploading({
    required String filename,
    double progress = 0,
  }) =>
      UploadProgressState._(
        isUploading: true,
        filename: filename,
        progress: progress.clamp(0.0, 1.0),
      );

  factory UploadProgressState.success(String filename) =>
      UploadProgressState._(isSuccess: true, filename: filename);

  factory UploadProgressState.error(String filename, String message) =>
      UploadProgressState._(isError: true, filename: filename, errorMessage: message);

  bool get isVisible => !isIdle;
}

class UploadProgressIndicator extends StatefulWidget {
  final UploadProgressState state;
  final VoidCallback? onCancel;
  final VoidCallback? onDismiss;

  const UploadProgressIndicator({
    super.key,
    required this.state,
    this.onCancel,
    this.onDismiss,
  });

  @override
  State<UploadProgressIndicator> createState() => _UploadProgressIndicatorState();
}

class _UploadProgressIndicatorState extends State<UploadProgressIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.state.isVisible) return const SizedBox.shrink();

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: _ProgressDesign.bgElevated,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _ProgressDesign.gold.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          _buildStatusIcon(),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _truncateFilename(widget.state.filename),
                  style: const TextStyle(
                    color: _ProgressDesign.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (widget.state.isUploading) ...[
                  const SizedBox(height: 4),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(2),
                    child: LinearProgressIndicator(
                      value: widget.state.progress > 0 ? widget.state.progress : null,
                      minHeight: 4,
                      backgroundColor: _ProgressDesign.gold.withOpacity(0.2),
                      valueColor: const AlwaysStoppedAnimation<Color>(_ProgressDesign.gold),
                    ),
                  ),
                ],
                if (widget.state.isError && widget.state.errorMessage != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    widget.state.errorMessage!,
                    style: const TextStyle(
                      color: _ProgressDesign.red,
                      fontSize: 10,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          if (widget.state.isUploading)
            IconButton(
              icon: const Icon(Icons.close, size: 18, color: _ProgressDesign.textSecondary),
              onPressed: widget.onCancel,
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
            )
          else if (widget.state.isSuccess || widget.state.isError)
            IconButton(
              icon: const Icon(Icons.close, size: 18, color: _ProgressDesign.textSecondary),
              onPressed: widget.onDismiss,
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
            ),
        ],
      ),
    );
  }

  Widget _buildStatusIcon() {
    if (widget.state.isUploading) {
      return SizedBox(
        width: 24,
        height: 24,
        child: CircularProgressIndicator(
          strokeWidth: 2,
          color: _ProgressDesign.gold,
        ),
      );
    }
    if (widget.state.isSuccess) {
      return const Icon(Icons.check_circle, color: _ProgressDesign.green, size: 24);
    }
    if (widget.state.isError) {
      return const Icon(Icons.error, color: _ProgressDesign.red, size: 24);
    }
    return const SizedBox.shrink();
  }

  String _truncateFilename(String name) {
    if (name.length <= 20) return name;
    final ext = name.contains('.') ? name.substring(name.lastIndexOf('.')) : '';
    final base = name.substring(0, name.length - ext.length);
    if (base.length <= 16) return name;
    return '${base.substring(0, 12)}…$ext';
  }
}
