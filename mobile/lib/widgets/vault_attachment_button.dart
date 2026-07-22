// =============================================================================
// VAULT ATTACHMENT BUTTON — Paperclip in chat input bar
// Upload File | Browse Vault | Transfer Crystal
// Disabled for TRIAL tier (upgrade prompt)
// =============================================================================

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'dart:typed_data';
import '../io_file_stub.dart' if (dart.library.io) 'dart:io' show File;
import '../config/app_config.dart';
import '../screens/vault_browser_screen.dart';
import '../screens/settings_screen.dart';
import '../services/vault_entitlement.dart';
import 'upload_progress_indicator.dart';

class _AttachmentDesign {
  static const gold = Color(0xFFC9A962);
  static const goldDim = Color(0xFF8B7355);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
}

class VaultAttachmentButton extends StatefulWidget {
  final Map<String, dynamic>? profile;
  final WebSocketChannel? socket;
  final ValueChanged<String?>? onVaultItemSelected;
  final ValueChanged<UploadProgressState>? onUploadProgress;

  const VaultAttachmentButton({
    super.key,
    required this.profile,
    this.socket,
    this.onVaultItemSelected,
    this.onUploadProgress,
  });

  @override
  State<VaultAttachmentButton> createState() => _VaultAttachmentButtonState();
}

class _VaultAttachmentButtonState extends State<VaultAttachmentButton> {
  bool _showProgress = false;
  UploadProgressState _progressState = UploadProgressState.idle();

  bool get _isVaultEnabled =>
      AppConfig.ENABLE_SOVEREIGN_VAULT && VaultEntitlement.canUseVault(widget.profile);

  bool get _hasVaultAccess => VaultEntitlement.canUseVault(widget.profile);

  @override
  Widget build(BuildContext context) {
    if (!AppConfig.ENABLE_SOVEREIGN_VAULT) return const SizedBox.shrink();
    if (!_hasVaultAccess) {
      return IconButton(
        icon: const Icon(Icons.attach_file, color: _AttachmentDesign.goldDim),
        tooltip: 'Upgrade to Inner Chamber for Vault access',
        onPressed: () => _showUpgradePrompt(),
      );
    }
    return IconButton(
      icon: const Icon(Icons.attach_file, color: _AttachmentDesign.gold),
      tooltip: 'Attach from Vault',
      onPressed: _showOptionsSheet,
    );
  }

  void _showUpgradePrompt() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _AttachmentDesign.bgElevated,
        title: const Text(
          'Sovereign Vault',
          style: TextStyle(color: _AttachmentDesign.gold),
        ),
        content: const Text(
          'The Sovereign Vault is available for Inner Chamber and Sovereign Circle members. '
          'Upgrade your plan to store documents, images, and share them with Nate.',
          style: TextStyle(color: _AttachmentDesign.textPrimary, fontSize: 14),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Later', style: TextStyle(color: _AttachmentDesign.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _AttachmentDesign.gold),
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => ClientSettingsScreen(profile: widget.profile ?? {}, socket: widget.socket),
              ));
            },
            child: const Text('Upgrade', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  void _showOptionsSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _AttachmentDesign.bgChamber,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Attach to Chat',
                style: TextStyle(
                  color: _AttachmentDesign.gold,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 16),
              ListTile(
                leading: const Icon(Icons.upload_file, color: _AttachmentDesign.gold),
                title: const Text('Upload File', style: TextStyle(color: _AttachmentDesign.textPrimary)),
                subtitle: const Text('Camera, gallery, or files', style: TextStyle(color: _AttachmentDesign.textSecondary, fontSize: 12)),
                onTap: () {
                  Navigator.pop(ctx);
                  _uploadFile();
                },
              ),
              ListTile(
                leading: const Icon(Icons.folder_open, color: _AttachmentDesign.gold),
                title: const Text('Browse Vault', style: TextStyle(color: _AttachmentDesign.textPrimary)),
                subtitle: const Text('Choose from your stored items', style: TextStyle(color: _AttachmentDesign.textSecondary, fontSize: 12)),
                onTap: () {
                  Navigator.pop(ctx);
                  _browseVault();
                },
              ),
              ListTile(
                leading: const Icon(Icons.diamond, color: Color(0xFF9D4EDD)),
                title: const Text('Transfer Crystal', style: TextStyle(color: _AttachmentDesign.textPrimary)),
                subtitle: const Text('Import from another source', style: TextStyle(color: _AttachmentDesign.textSecondary, fontSize: 12)),
                onTap: () {
                  Navigator.pop(ctx);
                  _transferCrystal();
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _uploadFile() async {
    PlatformFile? file;
    try {
      final result = await FilePicker.platform.pickFiles(allowMultiple: false);
      if (result == null || result.files.isEmpty) return;
      file = result.files.single;
      final bytes = file.bytes;
      if (bytes == null && file.path == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Could not read that file. Try again or use the mobile app.'),
              backgroundColor: _AttachmentDesign.goldDim,
            ),
          );
        }
        return;
      }

      final userId = (widget.profile?['hardware_id'] ?? widget.profile?['id'] ?? '').toString();
      final token = (widget.profile?['token'] ?? '').toString();
      final baseUrl = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      final uri = Uri.parse('$baseUrl/api/v1/upload');

      final fileName = file.name.isNotEmpty ? file.name : 'file';
      setState(() {
        _progressState = UploadProgressState.uploading(
          filename: fileName,
          progress: 0,
        );
      });
      widget.onUploadProgress?.call(_progressState);

      Uint8List data = bytes ?? Uint8List(0);
      if (data.isEmpty && file.path != null && !kIsWeb) {
        data = Uint8List.fromList(await File(file.path!).readAsBytes());
      }
      if (data.isEmpty) {
        setState(() => _progressState = UploadProgressState.error(fileName, 'File is empty'));
        widget.onUploadProgress?.call(_progressState);
        return;
      }

      final request = http.MultipartRequest('POST', uri);
      request.headers['X-User-Id'] = userId;
      if (token.isNotEmpty) request.headers['Authorization'] = 'Bearer $token';
      request.files.add(http.MultipartFile.fromBytes('file', data, filename: fileName));
      final streamed = await request.send().timeout(const Duration(seconds: 60));
      final resp = await http.Response.fromStream(streamed);

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        setState(() => _progressState = UploadProgressState.success(fileName));
        String? itemId;
        try {
          final body = jsonDecode(resp.body) as Map<String, dynamic>;
          itemId = (body['item_id'] ?? body['upload_id'])?.toString();
        } catch (_) {}
        if (itemId != null && itemId.isNotEmpty) {
          widget.onVaultItemSelected?.call(itemId);
        }
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                itemId != null
                    ? 'Saved to Vault (Documents folder). Tap Send to ask Nate.'
                    : 'Saved to Vault. Check Documents in Browse Vault.',
              ),
              backgroundColor: _AttachmentDesign.gold,
              duration: const Duration(seconds: 4),
            ),
          );
        }
      } else {
        String errorMsg = 'Upload failed (${resp.statusCode})';
        try {
          final body = resp.body;
          if (body.contains('detail')) {
            final detail = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(body);
            if (detail != null) errorMsg = detail.group(1) ?? errorMsg;
          }
        } catch (_) {}
        setState(() => _progressState = UploadProgressState.error(fileName, errorMsg));
      }
    } catch (e) {
      setState(() => _progressState = UploadProgressState.error(
        file?.name ?? 'file',
        e.toString().length > 50 ? 'Upload failed — check connection' : e.toString(),
      ));
    }
    widget.onUploadProgress?.call(_progressState);
  }

  void _browseVault() {
    final profile = widget.profile ?? {};
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => VaultBrowserScreen(profile: profile),
      ),
    ).then((selected) {
      if (selected != null) {
        final s = selected is String ? selected : (selected as Map?)?['id']?.toString();
        if (s != null && s.isNotEmpty) {
          widget.onVaultItemSelected?.call(s);
        }
      }
    });
  }

  void _transferCrystal() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _AttachmentDesign.bgElevated,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Transfer Crystal', style: TextStyle(color: _AttachmentDesign.gold, fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            const Text('Import AI chat history from another platform.', style: TextStyle(color: _AttachmentDesign.textSecondary, fontSize: 12)),
            const SizedBox(height: 16),
            ...[
              ('ChatGPT (OpenAI)', 'chatgpt', Icons.chat_bubble),
              ('Claude (Anthropic)', 'claude', Icons.psychology),
              ('Gemini (Google)', 'gemini', Icons.auto_awesome),
              ('Replika', 'replika', Icons.favorite),
            ].map((s) => ListTile(
              leading: Icon(s.$3, color: _AttachmentDesign.gold),
              title: Text(s.$1, style: const TextStyle(color: _AttachmentDesign.textPrimary)),
              onTap: () { Navigator.pop(ctx); _doTransferCrystalImport(s.$2); },
            )),
            ListTile(
              leading: const Icon(Icons.auto_fix_high, color: _AttachmentDesign.gold),
              title: const Text('Auto-Detect', style: TextStyle(color: _AttachmentDesign.textPrimary)),
              onTap: () { Navigator.pop(ctx); _doTransferCrystalImport('auto'); },
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _doTransferCrystalImport(String source) async {
    try {
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: false,
        type: FileType.custom,
        allowedExtensions: ['zip', 'json', 'csv'],
      );
      if (result == null || result.files.isEmpty) return;
      final picked = result.files.single;
      Uint8List? bytes = picked.bytes;
      if (bytes == null && picked.path != null && !kIsWeb) {
        bytes = Uint8List.fromList(await File(picked.path!).readAsBytes());
      }
      if (bytes == null) return;

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Importing... this may take a moment'), backgroundColor: _AttachmentDesign.gold),
        );
      }

      final token = (widget.profile?['token'] ?? '').toString();
      final baseUrl = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      final uri = Uri.parse('$baseUrl/api/v1/vault/import');
      final request = http.MultipartRequest('POST', uri);
      if (token.isNotEmpty) request.headers['Authorization'] = 'Bearer $token';
      request.fields['source'] = source;
      request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: picked.name));
      final streamed = await request.send().timeout(const Duration(seconds: 120));
      final resp = await http.Response.fromStream(streamed);

      if (!mounted) return;
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Transfer Crystal created successfully!'), backgroundColor: _AttachmentDesign.gold),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Import failed: ${resp.statusCode}'), backgroundColor: _AttachmentDesign.gold),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: _AttachmentDesign.gold),
        );
      }
    }
  }
}
