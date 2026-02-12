import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:extension_google_sign_in_as_googleapis_auth/extension_google_sign_in_as_googleapis_auth.dart';
import 'package:googleapis/drive/v3.dart' as drive;
import 'package:flutter_appauth/flutter_appauth.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'web_download.dart' as web_dl;

// =============================================================================
// Design tokens (mirrors the app design system)
// =============================================================================
class _ExportDesign {
  static const bgVoid = Color(0xFF050505);
  static const bgCard = Color(0xFF111111);
  static const bgElevated = Color(0xFF1A1A1A);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const cyan = Color(0xFF4ECDC4);
  static const green = Color(0xFF00FF88);
  static const red = Color(0xFFEF4444);
  static const purple = Color(0xFF9D4EDD);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

// =============================================================================
// CONVERSATION EXPORT SERVICE
// =============================================================================
class ConversationExportService {
  // ---------------------------------------------------------------------------
  // Google Drive configuration
  // ---------------------------------------------------------------------------
  // NOTE: Replace with your actual Google Cloud OAuth client ID.
  // For iOS, also add the reversed client ID as a URL scheme in Info.plist.
  // For Android, add the SHA-1 fingerprint in Google Cloud Console.
  static const String _googleClientId = '';  // Set via env or config
  static const List<String> _googleScopes = [drive.DriveApi.driveFileScope];

  static final GoogleSignIn _googleSignIn = GoogleSignIn(
    scopes: _googleScopes,
  );

  // ---------------------------------------------------------------------------
  // OneDrive / Microsoft configuration
  // ---------------------------------------------------------------------------
  // NOTE: Replace with your Azure AD app registration client ID.
  static const String _msClientId = '';  // Set via env or config
  static const String _msRedirectUri = 'net.sovereignsanctuary.app://oauth2redirect';
  static const String _msAuthority = 'https://login.microsoftonline.com/common';
  static const String _msTokenEndpoint = '$_msAuthority/oauth2/v2.0/token';
  static const String _msAuthEndpoint = '$_msAuthority/oauth2/v2.0/authorize';
  static const List<String> _msScopes = ['Files.ReadWrite', 'User.Read'];

  static final FlutterAppAuth _appAuth = const FlutterAppAuth();

  // Cached OneDrive access token
  static String? _msAccessToken;

  // ---------------------------------------------------------------------------
  // PUBLIC API
  // ---------------------------------------------------------------------------

  /// Save content to Google Drive inside a "Sovereign Sanctuary" folder.
  Future<bool> saveToGoogleDrive(String content, String filename) async {
    try {
      GoogleSignInAccount? account = _googleSignIn.currentUser;
      account ??= await _googleSignIn.signIn();
      if (account == null) {
        debugPrint('[ExportService] Google sign-in cancelled');
        return false;
      }

      final authClient = await _googleSignIn.authenticatedClient();
      if (authClient == null) {
        debugPrint('[ExportService] Could not get authenticated Google client');
        return false;
      }

      final driveApi = drive.DriveApi(authClient);

      // Find or create the "Sovereign Sanctuary" folder
      final folderId = await _getOrCreateGoogleFolder(driveApi, 'Sovereign Sanctuary');

      // Upload the file
      final media = drive.Media(
        Stream.value(utf8.encode(content)),
        utf8.encode(content).length,
      );
      final driveFile = drive.File()
        ..name = filename
        ..parents = [folderId]
        ..mimeType = 'text/plain';

      await driveApi.files.create(driveFile, uploadMedia: media);
      debugPrint('[ExportService] Saved to Google Drive: $filename');
      return true;
    } catch (e) {
      debugPrint('[ExportService] Google Drive error: $e');
      return false;
    }
  }

  /// Save content to OneDrive inside a "Sovereign Sanctuary" folder.
  Future<bool> saveToOneDrive(String content, String filename) async {
    try {
      // Authenticate if needed
      if (_msAccessToken == null) {
        final result = await _appAuth.authorizeAndExchangeCode(
          AuthorizationTokenRequest(
            _msClientId,
            _msRedirectUri,
            serviceConfiguration: AuthorizationServiceConfiguration(
              authorizationEndpoint: _msAuthEndpoint,
              tokenEndpoint: _msTokenEndpoint,
            ),
            scopes: _msScopes,
          ),
        );

        if (result == null || result.accessToken == null) {
          debugPrint('[ExportService] OneDrive auth cancelled');
          return false;
        }
        _msAccessToken = result.accessToken;
      }

      // Upload via Microsoft Graph API
      final url = Uri.parse(
        'https://graph.microsoft.com/v1.0/me/drive/root:'
        '/Sovereign Sanctuary/$filename:/content',
      );

      final response = await http.put(
        url,
        headers: {
          'Authorization': 'Bearer $_msAccessToken',
          'Content-Type': 'text/plain',
        },
        body: content,
      );

      if (response.statusCode == 200 || response.statusCode == 201) {
        debugPrint('[ExportService] Saved to OneDrive: $filename');
        return true;
      } else if (response.statusCode == 401) {
        // Token expired — clear and retry once
        _msAccessToken = null;
        return saveToOneDrive(content, filename);
      } else {
        debugPrint('[ExportService] OneDrive error: ${response.statusCode} ${response.body}');
        return false;
      }
    } catch (e) {
      debugPrint('[ExportService] OneDrive error: $e');
      return false;
    }
  }

  /// Save content to the device's local storage and optionally share.
  Future<bool> saveToLocal(String content, String filename) async {
    try {
      if (kIsWeb) {
        // Web: trigger a browser file download via anchor element
        web_dl.downloadFileToDevice(content, filename);
        debugPrint('[ExportService] Web download triggered: $filename');
        return true;
      }

      // Mobile: write to app documents then share
      final dir = await getApplicationDocumentsDirectory();
      final file = File('${dir.path}/$filename');
      await file.writeAsString(content);

      // Open the system share sheet so user can save to Files, etc.
      await Share.shareXFiles(
        [XFile(file.path)],
        subject: filename,
        text: 'Sovereign Sanctuary conversation export',
      );
      debugPrint('[ExportService] Saved locally: ${file.path}');
      return true;
    } catch (e) {
      debugPrint('[ExportService] Local save error: $e');
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // DESTINATION PICKER BOTTOM SHEET
  // ---------------------------------------------------------------------------

  /// Show a styled bottom sheet and return the chosen destination key.
  /// Returns: "google_drive", "onedrive", "local", or null if dismissed.
  static Future<String?> showDestinationPicker(
    BuildContext context, {
    String? suggested,
  }) async {
    return showModalBottomSheet<String>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (ctx) => _DestinationPickerSheet(suggested: suggested),
    );
  }

  // ---------------------------------------------------------------------------
  // HELPERS
  // ---------------------------------------------------------------------------

  Future<String> _getOrCreateGoogleFolder(
    drive.DriveApi driveApi,
    String folderName,
  ) async {
    // Search for existing folder
    final result = await driveApi.files.list(
      q: "name = '$folderName' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
      spaces: 'drive',
    );

    if (result.files != null && result.files!.isNotEmpty) {
      return result.files!.first.id!;
    }

    // Create the folder
    final folder = drive.File()
      ..name = folderName
      ..mimeType = 'application/vnd.google-apps.folder';

    final created = await driveApi.files.create(folder);
    return created.id!;
  }
}

// =============================================================================
// DESTINATION PICKER WIDGET
// =============================================================================
class _DestinationPickerSheet extends StatelessWidget {
  final String? suggested;

  const _DestinationPickerSheet({this.suggested});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: _ExportDesign.bgCard,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        border: Border(
          top: BorderSide(color: _ExportDesign.gold, width: 1),
          left: BorderSide(color: _ExportDesign.gold, width: 0.5),
          right: BorderSide(color: _ExportDesign.gold, width: 0.5),
        ),
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Drag handle
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: _ExportDesign.textSecondary.withOpacity(0.4),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 16),

              // Title
              const Text(
                'Save Conversation',
                style: TextStyle(
                  color: _ExportDesign.goldBright,
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                  fontFamily: 'Cormorant Garamond',
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Choose where to save your export',
                style: TextStyle(
                  color: _ExportDesign.textSecondary,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 20),

              // Google Drive
              _destinationTile(
                context,
                icon: Icons.cloud,
                iconColor: _ExportDesign.cyan,
                title: 'Google Drive',
                subtitle: 'Save to your Drive',
                value: 'google_drive',
                isSuggested: suggested == 'google_drive',
              ),
              const SizedBox(height: 10),

              // OneDrive
              _destinationTile(
                context,
                icon: Icons.cloud_queue,
                iconColor: _ExportDesign.purple,
                title: 'OneDrive',
                subtitle: 'Save to Microsoft OneDrive',
                value: 'onedrive',
                isSuggested: suggested == 'onedrive',
              ),
              const SizedBox(height: 10),

              // Local / Device
              _destinationTile(
                context,
                icon: kIsWeb ? Icons.computer : Icons.phone_android,
                iconColor: _ExportDesign.green,
                title: kIsWeb ? 'Save to Computer' : 'Save to Phone',
                subtitle: kIsWeb ? 'Download to your computer' : 'Download to your device',
                value: 'local',
                isSuggested: suggested == 'local',
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }

  Widget _destinationTile(
    BuildContext context, {
    required IconData icon,
    required Color iconColor,
    required String title,
    required String subtitle,
    required String value,
    bool isSuggested = false,
  }) {
    return InkWell(
      onTap: () => Navigator.of(context).pop(value),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: isSuggested
              ? _ExportDesign.gold.withOpacity(0.08)
              : _ExportDesign.bgElevated,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSuggested ? _ExportDesign.gold.withOpacity(0.4) : _ExportDesign.border,
            width: isSuggested ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: iconColor.withOpacity(0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(icon, color: iconColor, size: 22),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      color: _ExportDesign.textPrimary,
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: const TextStyle(
                      color: _ExportDesign.textSecondary,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            if (isSuggested)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: _ExportDesign.gold.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Text(
                  'Suggested',
                  style: TextStyle(
                    color: _ExportDesign.gold,
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            const SizedBox(width: 8),
            Icon(
              Icons.chevron_right,
              color: _ExportDesign.textSecondary.withOpacity(0.5),
              size: 20,
            ),
          ],
        ),
      ),
    );
  }
}
