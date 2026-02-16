// =============================================================================
// VAULT PREVIEW WINDOW — Bottom sheet overlay when item referenced in chat
// Icon + filename + date, content preview, action buttons
// =============================================================================

import 'package:flutter/material.dart';

class _PreviewDesign {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const cyan = Color(0xFF4ECDC4);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

/// Extra action button data for VaultPreviewWindow.
class VaultExtraAction {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;
  const VaultExtraAction({required this.icon, required this.label, required this.color, required this.onTap});
}

class VaultPreviewWindow extends StatelessWidget {
  final Map<String, dynamic> item;
  final VoidCallback onOpenInVault;
  final VoidCallback onAskNate;
  final VoidCallback onStar;
  final List<VaultExtraAction>? extraActions;

  const VaultPreviewWindow({
    super.key,
    required this.item,
    required this.onOpenInVault,
    required this.onAskNate,
    required this.onStar,
    this.extraActions,
  });

  @override
  Widget build(BuildContext context) {
    final name = item['display_name'] ?? 'Untitled';
    final date = item['created_at'] ?? item['updated_at'] ?? '';
    final ct = (item['content_type'] ?? 'document').toString();
    final starred = item['starred'] ?? false;
    final preview = item['extracted_text_preview'] ?? item['summary'] ?? '';
    final isImage = ct.contains('image') || ct.contains('upload_image');
    final isReport = ct.contains('report');

    return Container(
      decoration: BoxDecoration(
        color: _PreviewDesign.bgChamber,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
        border: const Border(
          top: BorderSide(color: _PreviewDesign.gold, width: 2),
          left: BorderSide(color: _PreviewDesign.gold, width: 1),
          right: BorderSide(color: _PreviewDesign.gold, width: 1),
        ),
      ),
      child: DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) => Column(
          children: [
            // Handle bar
            Container(
              margin: const EdgeInsets.only(top: 12),
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: _PreviewDesign.gold.withOpacity(0.5),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            // Header: icon + filename + date
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: _PreviewDesign.gold.withOpacity(0.2),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(
                      isImage ? Icons.image : (isReport ? Icons.assessment : Icons.description),
                      color: _PreviewDesign.gold,
                      size: 28,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          style: const TextStyle(
                            color: _PreviewDesign.textPrimary,
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _formatDate(date),
                          style: const TextStyle(
                            color: _PreviewDesign.textSecondary,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    icon: Icon(
                      starred ? Icons.star : Icons.star_border,
                      color: starred ? _PreviewDesign.gold : _PreviewDesign.textSecondary,
                    ),
                    onPressed: onStar,
                  ),
                ],
              ),
            ),
            const Divider(color: _PreviewDesign.border, height: 1),
            // Content area
            Expanded(
              child: SingleChildScrollView(
                controller: scrollController,
                padding: const EdgeInsets.all(16),
                child: _buildContentArea(isImage, preview),
              ),
            ),
            const Divider(color: _PreviewDesign.border, height: 1),
            // Action buttons
            Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: onOpenInVault,
                          icon: const Icon(Icons.folder_open, size: 18, color: _PreviewDesign.gold),
                          label: const Text(
                            'Open in Vault',
                            style: TextStyle(color: _PreviewDesign.gold, fontSize: 12),
                          ),
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: _PreviewDesign.gold),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: onAskNate,
                          icon: const Icon(Icons.chat, size: 18, color: Colors.black),
                          label: const Text(
                            'Ask Nate About This',
                            style: TextStyle(color: Colors.black, fontSize: 12, fontWeight: FontWeight.w600),
                          ),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _PreviewDesign.cyan,
                          ),
                        ),
                      ),
                    ],
                  ),
                  // Extra action buttons (e.g. "Organize with Nate" for Sovereign Circle)
                  if (extraActions != null && extraActions!.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    ...extraActions!.map((action) {
                      return Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: SizedBox(
                          width: double.infinity,
                          child: ElevatedButton.icon(
                            onPressed: action.onTap,
                            icon: Icon(action.icon, size: 18, color: Colors.black),
                            label: Text(
                              action.label,
                              style: const TextStyle(color: Colors.black, fontSize: 12, fontWeight: FontWeight.w600),
                            ),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: action.color,
                              padding: const EdgeInsets.symmetric(vertical: 12),
                            ),
                          ),
                        ),
                      );
                    }),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildContentArea(bool isImage, String preview) {
    if (isImage) {
      return Center(
        child: Container(
          constraints: const BoxConstraints(maxHeight: 200, maxWidth: 300),
          decoration: BoxDecoration(
            color: _PreviewDesign.bgElevated,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: _PreviewDesign.border),
          ),
          child: const Icon(
            Icons.image,
            color: _PreviewDesign.gold,
            size: 64,
          ),
        ),
      );
    }
    if (preview.isNotEmpty) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: _PreviewDesign.bgElevated,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: _PreviewDesign.border),
        ),
        child: Text(
          preview.length > 500 ? '${preview.substring(0, 500)}…' : preview,
          style: const TextStyle(
            color: _PreviewDesign.textSecondary,
            fontSize: 13,
            height: 1.4,
          ),
        ),
      );
    }
    return Center(
      child: Text(
        'No preview available',
        style: TextStyle(color: _PreviewDesign.textSecondary.withOpacity(0.7), fontSize: 13),
      ),
    );
  }

  String _formatDate(dynamic d) {
    if (d == null) return '';
    final s = d.toString();
    if (s.length >= 10) return s.substring(0, 10);
    return s;
  }
}
