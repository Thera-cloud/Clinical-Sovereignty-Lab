// =============================================================================
// COMMUNITY WISDOM SERVICE — Wisdom aggregation for community mesh
//
// Fetches and submits community insights, merges with personal wisdom.
// © 2026 Clinical Sovereignty Lab. All rights reserved.
// =============================================================================

import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

// =============================================================================
// MODELS
// =============================================================================

class WisdomInsight {
  final String id;
  final String? topic;
  final String text;
  final int convergenceCount;
  final DateTime? timestamp;

  WisdomInsight({
    required this.id,
    this.topic,
    required this.text,
    this.convergenceCount = 1,
    this.timestamp,
  });

  factory WisdomInsight.fromJson(Map<String, dynamic> json) {
    return WisdomInsight(
      id: json['id']?.toString() ?? '',
      topic: json['topic']?.toString(),
      text: json['insight_text']?.toString() ?? json['text']?.toString() ?? '',
      convergenceCount: (json['convergence_count'] as int?) ?? (json['convergenceCount'] as int?) ?? 1,
      timestamp: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : json['timestamp'] != null
              ? DateTime.tryParse(json['timestamp'].toString())
              : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'topic': topic,
        'text': text,
        'convergence_count': convergenceCount,
        'created_at': timestamp?.toIso8601String(),
      };
}

// =============================================================================
// COMMUNITY WISDOM SERVICE
// =============================================================================

/// ChangeNotifier for community wisdom aggregation: fetch insights, submit
/// wisdom, and merge with personal wisdom.
class CommunityWisdomService with ChangeNotifier {
  final List<WisdomInsight> _insights = [];
  bool _isLoading = false;
  String? _lastError;

  /// Community wisdom insights (topic, text, convergence count, timestamp).
  List<WisdomInsight> get insights => List.unmodifiable(_insights);

  /// Whether a fetch or submit is in progress.
  bool get isLoading => _isLoading;

  /// Last error message, if any.
  String? get lastError => _lastError;

  /// Base URL for API calls.
  String get _baseUrl => AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'));

  /// Fetch community wisdom insights. Supports topic filter and limit.
  Future<void> fetchInsights({
    String? topic,
    int limit = 20,
    String? token,
  }) async {
    _isLoading = true;
    _lastError = null;
    notifyListeners();

    try {
      var uri = Uri.parse('$_baseUrl/api/community/wisdom?limit=$limit');
      if (topic != null && topic.isNotEmpty) {
        uri = uri.replace(queryParameters: {'topic': topic, 'limit': limit.toString()});
      }

      final resp = await http.get(
        uri,
        headers: {
          if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
        },
      ).timeout(const Duration(seconds: AppConfig.apiTimeout));

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final list = (data['insights'] as List<dynamic>?) ?? [];
        _insights.clear();
        _insights.addAll(
          list.map((e) {
            final m = Map<String, dynamic>.from(e as Map);
            return WisdomInsight.fromJson(m);
          }),
        );
      } else {
        _lastError = 'Failed to load wisdom (${resp.statusCode})';
      }
    } catch (e) {
      _lastError = 'Network error: $e';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Submit wisdom from a session.
  Future<bool> submitWisdom({
    required String sessionId,
    required List<String> topicTags,
    required List<String> wisdomTexts,
    String? token,
  }) async {
    if (wisdomTexts.isEmpty) return false;

    _isLoading = true;
    _lastError = null;
    notifyListeners();

    try {
      final resp = await http.post(
        Uri.parse('$_baseUrl/api/community/wisdom'),
        headers: {
          'Content-Type': 'application/json',
          if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'session_id': sessionId,
          'topic_tags': topicTags,
          'anonymized_wisdom': wisdomTexts,
          'peer_count': 1,
        }),
      ).timeout(const Duration(seconds: AppConfig.apiTimeout));

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final count = (data['wisdom_count'] as int?) ?? wisdomTexts.length;
        for (var i = 0; i < count && i < wisdomTexts.length; i++) {
          _insights.insert(
            0,
            WisdomInsight(
              id: DateTime.now().millisecondsSinceEpoch.toString(),
              topic: topicTags.isNotEmpty ? topicTags.first : null,
              text: wisdomTexts[i],
              convergenceCount: 1,
              timestamp: DateTime.now(),
            ),
          );
        }
        notifyListeners();
        return true;
      } else {
        _lastError = 'Submit failed (${resp.statusCode})';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _lastError = 'Network error: $e';
      notifyListeners();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Merge community insights with personal wisdom into a combined list.
  /// Personal wisdom entries are marked with a synthetic topic if desired.
  List<WisdomInsight> mergeWithPersonalWisdom(List<WisdomInsight> personalWisdom) {
    final merged = <WisdomInsight>[];
    final seen = <String>{};

    for (final i in _insights) {
      final key = '${i.topic ?? ''}:${i.text}';
      if (!seen.contains(key)) {
        seen.add(key);
        merged.add(i);
      }
    }
    for (final i in personalWisdom) {
      final key = 'personal:${i.text}';
      if (!seen.contains(key)) {
        seen.add(key);
        merged.add(WisdomInsight(
          id: i.id,
          topic: i.topic ?? 'personal',
          text: i.text,
          convergenceCount: i.convergenceCount,
          timestamp: i.timestamp,
        ));
      }
    }

    merged.sort((a, b) {
      final ta = a.timestamp ?? DateTime(1970);
      final tb = b.timestamp ?? DateTime(1970);
      return tb.compareTo(ta);
    });
    return merged;
  }

  /// Clear last error.
  void clearError() {
    _lastError = null;
    notifyListeners();
  }
}
