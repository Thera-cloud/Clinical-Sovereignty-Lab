import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:photo_manager/photo_manager.dart';

/// Service for accessing device-local photos and memories.
///
/// On native platforms, uses photo_manager for gallery access.
/// On web, photo library scanning is unavailable (returns empty).
///
/// Privacy: thumbnails are ephemeral (sent via WebSocket, never persisted server-side).
/// Full-resolution images are only uploaded if the user explicitly adds them to the Vault.
class DeviceMemoryService {
  DeviceMemoryService._();
  static final DeviceMemoryService instance = DeviceMemoryService._();

  String _photoConsent = 'ask_each_time';
  bool _permissionGranted = false;

  Future<void> loadConsent() async {
    final prefs = await SharedPreferences.getInstance();
    _photoConsent = prefs.getString('nate_photo_access_consent') ?? 'ask_each_time';
  }

  String get photoConsent => _photoConsent;
  bool get hasPermission => _permissionGranted;

  Future<void> setPhotoConsent(String value) async {
    _photoConsent = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('nate_photo_access_consent', value);
  }

  /// Request photo library permission. Returns true if granted.
  Future<bool> requestPermission() async {
    if (kIsWeb) return false;
    try {
      final state = await PhotoManager.requestPermissionExtend();
      _permissionGranted = state.isAuth;
      return _permissionGranted;
    } catch (e) {
      if (kDebugMode) print('[DeviceMemory] Permission request error: $e');
      return false;
    }
  }

  /// Get recent photos from the device gallery as thumbnail metadata.
  /// Returns a list of maps with: id, filename, date, width, height, thumbnail (base64).
  ///
  /// On web, this is a no-op and returns empty.
  Future<List<Map<String, dynamic>>> getRecentPhotos({
    DateTime? dateFrom,
    DateTime? dateTo,
    int limit = 10,
  }) async {
    if (kIsWeb) return [];

    try {
      return await _getPhotosNative(dateFrom: dateFrom, dateTo: dateTo, limit: limit);
    } catch (e) {
      if (kDebugMode) print('[DeviceMemory] Photo access error: $e');
      return [];
    }
  }

  Future<List<Map<String, dynamic>>> _getPhotosNative({
    DateTime? dateFrom,
    DateTime? dateTo,
    int limit = 10,
  }) async {
    if (!_permissionGranted) {
      final granted = await requestPermission();
      if (!granted) return [];
    }

    final filterOption = FilterOptionGroup(
      imageOption: const FilterOption(
        sizeConstraint: SizeConstraint(ignoreSize: true),
      ),
      orders: [const OrderOption(type: OrderOptionType.createDate, asc: false)],
      createTimeCond: dateFrom != null || dateTo != null
          ? DateTimeCond(
              min: dateFrom ?? DateTime(2000),
              max: dateTo ?? DateTime.now(),
            )
          : DateTimeCond(min: DateTime(2000), max: DateTime.now()),
    );

    final albums = await PhotoManager.getAssetPathList(
      type: RequestType.image,
      filterOption: filterOption,
    );
    if (albums.isEmpty) return [];

    // Use the "Recent" or first album
    final recent = albums.firstWhere(
      (a) => a.isAll,
      orElse: () => albums.first,
    );

    final assets = await recent.getAssetListRange(start: 0, end: limit);
    final results = <Map<String, dynamic>>[];

    for (final asset in assets) {
      try {
        final thumbBytes = await asset.thumbnailDataWithSize(
          const ThumbnailSize(200, 200),
          quality: 70,
        );
        if (thumbBytes == null) continue;

        results.add({
          'id': asset.id,
          'filename': asset.title ?? 'photo_${asset.id}',
          'date': asset.createDateTime.toIso8601String(),
          'width': asset.width,
          'height': asset.height,
          'thumbnail': base64Encode(thumbBytes),
          'mime_type': asset.mimeType ?? 'image/jpeg',
        });
      } catch (e) {
        if (kDebugMode) print('[DeviceMemory] Thumbnail error for ${asset.id}: $e');
      }
    }

    return results;
  }

  /// Get full-resolution bytes for a specific photo asset.
  /// Used only when the user explicitly approves sending to Nate for analysis.
  Future<Uint8List?> getPhotoBytes(String assetId) async {
    if (kIsWeb) return null;
    try {
      final asset = await AssetEntity.fromId(assetId);
      if (asset == null) return null;
      final file = await asset.file;
      if (file == null) return null;
      return await file.readAsBytes();
    } catch (e) {
      if (kDebugMode) print('[DeviceMemory] getPhotoBytes error: $e');
      return null;
    }
  }

  /// Generate a base64 thumbnail from raw image bytes.
  /// Used when sending device photos to the bridge for Nate's analysis.
  String? bytesToBase64Thumbnail(Uint8List bytes) {
    try {
      return base64Encode(bytes);
    } catch (_) {
      return null;
    }
  }
}
