// =============================================================================
// SETTINGS SCREENS — Client & Coach
// =============================================================================

import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'dart:typed_data';
import '../io_file_stub.dart' if (dart.library.io) 'dart:io' show File;
import '../main.dart' show LobbyScreen, HardwareIdentity, ClientScheduleScreen, isNativeIOS;
import 'billing_screens.dart';
import '../config/app_config.dart';
import '../services/payment_service.dart';
import 'vault_browser_screen.dart';
import 'nate_organizer_screen.dart';
import 'quiz_screen.dart';
import 'nevedal_reports_screen.dart';
import 'distress_beacon_screen.dart';
import 'secure_search_screen.dart';
import 'coaching_mesh_screen.dart';
import 'community_mesh_screen.dart';
import 'night_school_screen.dart';
import 'ai_modes_screen.dart';

// =============================================================================
// DESIGN TOKENS
// =============================================================================
class _Design {
  static const bgVoid = Color(0xFF050505);
  static const bgCard = Color(0xFF111111);
  static const bgElevated = Color(0xFF1A1A1A);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const red = Color(0xFFEF4444);
  static const green = Color(0xFF00FF88);
  static const purple = Color(0xFF9D4EDD);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

// =============================================================================
// CLIENT SETTINGS SCREEN
// =============================================================================
class ClientSettingsScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final WebSocketChannel? socket;
  final VoidCallback? onLogout;

  const ClientSettingsScreen({
    super.key,
    required this.profile,
    this.socket,
    this.onLogout,
  });

  @override
  State<ClientSettingsScreen> createState() => _ClientSettingsScreenState();
}

class _ClientSettingsScreenState extends State<ClientSettingsScreen> {
  late Map<String, dynamic> _profile;
  bool _editingProfile = false;
  final _emailCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _emergencyCtrl = TextEditingController();
  final _timezoneCtrl = TextEditingController();

  // Notification prefs
  bool _notifPush = true;
  bool _notifSessionReminders = true;
  bool _notifCrisisAlerts = true;
  bool _voiceModeDefault = false;
  String _preferredContact = 'email';

  // Vault stats (for STANDARD+ tiers)
  int? _vaultUsageBytes;
  int? _vaultLimitBytes;

  // Family members roster
  List<Map<String, dynamic>> _familyMembers = [];
  List<Map<String, dynamic>> _pendingInvites = [];
  bool _familyLoading = false;
  // Family members fetched via REST (see _fetchFamilyMembers)

  // Biometric login toggle
  final HardwareIdentity _bioIdentity = HardwareIdentity();
  bool _biometricEnabled = false;
  bool _biometricAvailable = false;

  // Assigned coach info
  String _coachName = '';
  String _coachEmail = '';
  List<dynamic> _coachSpecializations = [];
  bool _coachInfoLoaded = false;

  @override
  void initState() {
    super.initState();
    _profile = Map<String, dynamic>.from(widget.profile);
    _emailCtrl.text = _profile['email'] ?? '';
    _phoneCtrl.text = _profile['phone'] ?? '';
    _emergencyCtrl.text = _profile['emergency_contact'] ?? '';
    _timezoneCtrl.text = _profile['timezone'] ?? 'America/New_York';
    _notifPush = _profile['notif_push'] ?? true;
    _notifSessionReminders = _profile['notif_session_reminders'] ?? true;
    _notifCrisisAlerts = _profile['notif_crisis_alerts'] ?? true;
    _voiceModeDefault = _profile['voice_mode_default'] ??
        (_profile['notification_prefs'] is Map ? _profile['notification_prefs']['voice_mode_default'] : null) ?? false;
    _preferredContact = _profile['preferred_contact'] ?? 'email';
    if (AppConfig.ENABLE_SOVEREIGN_VAULT && _hasVaultAccess) _loadVaultStats();
    if (_isSovereignCircle) _fetchFamilyMembers();
    _loadBiometricState();
    _fetchCoachInfo();
  }

  Future<void> _loadBiometricState() async {
    final enabled = await _bioIdentity.isBiometricEnabled();
    final available = await _bioIdentity.isBiometricAvailable();
    if (mounted) {
      setState(() {
        _biometricEnabled = enabled;
        _biometricAvailable = available;
      });
    }
  }

  Future<void> _fetchCoachInfo() async {
    final coachId = (_profile['coach_id'] ?? _profile['assigned_coach_id'] ?? '').toString();
    if (coachId.isEmpty) {
      if (mounted) setState(() { _coachName = 'Not Assigned'; _coachInfoLoaded = true; });
      return;
    }
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    try {
      final token = _profile['token']?.toString() ?? widget.profile['token']?.toString() ?? '';
      final resp = await http.get(
        Uri.parse('$base/api/client/coach-info/$coachId'),
        headers: {
          'Content-Type': 'application/json',
          if (token.isNotEmpty) 'Authorization': 'Bearer $token',
        },
      ).timeout(const Duration(seconds: 8));
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _coachName = (data['coach_name'] ?? 'Coach').toString();
          _coachEmail = (data['coach_email'] ?? '').toString();
          _coachSpecializations = data['specializations'] as List<dynamic>? ?? [];
          _coachInfoLoaded = true;
        });
      } else if (mounted) {
        setState(() { _coachName = 'Unavailable'; _coachInfoLoaded = true; });
      }
    } catch (_) {
      if (mounted) setState(() { _coachName = 'Unavailable'; _coachInfoLoaded = true; });
    }
  }

  bool get _hasVaultAccess {
    final key = _currentPlanKey;
    return key == 'STANDARD' || key == 'TOP_TIER' || key == 'FAMILY';
  }

  Future<void> _loadVaultStats() async {
    final userId = (_profile['hardware_id'] ?? _profile['id'] ?? '').toString();
    if (userId.isEmpty) return;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    try {
      final uri = Uri.parse('$base/api/v1/vault/stats').replace(queryParameters: {'user_id': userId});
      final resp = await http.get(
        uri,
        headers: {'X-User-Id': userId, 'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 5));
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body) as Map;
        setState(() {
          _vaultUsageBytes = data['total_size_bytes'] as int?;
          _vaultLimitBytes = data['limit_bytes'] as int? ?? (5 * 1024 * 1024 * 1024);
        });
      }
    } catch (_) {}
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} GB';
  }

  @override
  void dispose() {
    _emailCtrl.dispose();
    _phoneCtrl.dispose();
    _emergencyCtrl.dispose();
    _timezoneCtrl.dispose();
    super.dispose();
  }

  // ---- Fetch family members + pending invites via REST ----
  Future<void> _fetchFamilyMembers() async {
    if (_familyLoading) return;
    setState(() => _familyLoading = true);

    final hwId = (_profile['hardware_id'] ?? widget.profile['hardware_id'] ?? '').toString();
    final token = (_profile['token'] ?? widget.profile['token'] ?? '').toString();
    if (hwId.isEmpty || token.isEmpty) {
      if (mounted) setState(() => _familyLoading = false);
      return;
    }

    try {
      final url = '${AppConfig.apiBaseUrl}/api/client/family/members/$hwId';
      final resp = await http.get(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer $token'},
      ).timeout(const Duration(seconds: 10));

      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _familyMembers = List<Map<String, dynamic>>.from(
            (data['members'] as List?)?.map((e) => Map<String, dynamic>.from(e)) ?? [],
          );
          _pendingInvites = List<Map<String, dynamic>>.from(
            (data['pending_invites'] as List?)?.map((e) => Map<String, dynamic>.from(e)) ?? [],
          );
          _familyLoading = false;
        });
      } else {
        setState(() => _familyLoading = false);
      }
    } catch (_) {
      if (mounted) setState(() => _familyLoading = false);
    }
  }

  // ---- Remove family member via WebSocket ----
  Future<void> _removeFamilyMember(String memberId, String memberName, bool isMinor) async {
    final action = isMinor ? 'Release' : 'Remove';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: Text('$action $memberName?', style: const TextStyle(color: _Design.red, fontFamily: 'Courier')),
        content: Text(
          isMinor
              ? '$memberName is a minor. Releasing them will remove them from your family plan and revoke their access to Sovereign Sanctuary.'
              : 'Are you sure you want to remove $memberName from your family plan? They will lose access to Sovereign Sanctuary.',
          style: const TextStyle(color: _Design.textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(action, style: const TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    WebSocketChannel? sock;
    StreamSubscription? sub;
    final completer = Completer<Map<String, dynamic>?>();

    try {
      sock = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      sub = sock.stream.listen((raw) {
        try {
          final data = jsonDecode(raw) as Map<String, dynamic>;
          final type = (data['type'] ?? '').toString();
          if (type == 'connected') {
            sock?.sink.add(jsonEncode({
              'type': 'auth',
              'token': _profile['token'] ?? widget.profile['token'] ?? '',
              'hardware_id': _profile['hardware_id'] ?? widget.profile['hardware_id'] ?? '',
            }));
          } else if (type == 'auth_success' || type == 'login_success') {
            sock?.sink.add(jsonEncode({
              'type': 'remove_family_member',
              'member_id': memberId,
              'reason': isMinor ? 'release' : 'delete',
            }));
          } else if (type == 'family_member_removed') {
            if (!completer.isCompleted) completer.complete(data);
          } else if (type == 'family_member_remove_error') {
            if (!completer.isCompleted) completer.completeError(data['message'] ?? 'Failed');
          }
        } catch (_) {}
      }, onError: (e) {
        if (!completer.isCompleted) completer.completeError(e);
      }, onDone: () {
        if (!completer.isCompleted) completer.completeError('Connection closed');
      });

      await completer.future.timeout(const Duration(seconds: 15), onTimeout: () => throw TimeoutException('Timed out'));

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('$memberName has been removed from your family.'),
          backgroundColor: _Design.green,
        ));
        _fetchFamilyMembers();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not remove member: ${e.toString().replaceAll('TimeoutException:', '').trim()}'),
          backgroundColor: _Design.red,
        ));
      }
    }

    try { sub?.cancel(); } catch (_) {}
    try { sock?.sink.close(); } catch (_) {}
  }

  // ---- Cancel a pending family invite ----
  Future<void> _cancelFamilyInvite(String token, String inviteeName) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: const Text('Cancel Invite?', style: TextStyle(color: _Design.gold, fontFamily: 'Courier')),
        content: Text(
          'Cancel the pending invitation for $inviteeName? They will no longer be able to join your family.',
          style: const TextStyle(color: _Design.textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Keep', style: TextStyle(color: _Design.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Cancel Invite', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    WebSocketChannel? sock;
    StreamSubscription? sub;
    final completer = Completer<void>();

    try {
      sock = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      sub = sock.stream.listen((raw) {
        try {
          final data = jsonDecode(raw) as Map<String, dynamic>;
          final type = (data['type'] ?? '').toString();
          if (type == 'connected') {
            sock?.sink.add(jsonEncode({
              'type': 'auth',
              'token': _profile['token'] ?? widget.profile['token'] ?? '',
              'hardware_id': _profile['hardware_id'] ?? widget.profile['hardware_id'] ?? '',
            }));
          } else if (type == 'auth_success' || type == 'login_success') {
            sock?.sink.add(jsonEncode({
              'type': 'cancel_family_invite',
              'invite_token': token,
            }));
          } else if (type == 'family_invite_cancelled') {
            if (!completer.isCompleted) completer.complete();
          }
        } catch (_) {}
      }, onError: (_) {
        if (!completer.isCompleted) completer.complete();
      }, onDone: () {
        if (!completer.isCompleted) completer.complete();
      });

      await completer.future.timeout(const Duration(seconds: 10), onTimeout: () {});

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Invite for $inviteeName cancelled.'),
          backgroundColor: _Design.gold,
        ));
        _fetchFamilyMembers();
      }
    } catch (_) {}

    try { sub?.cancel(); } catch (_) {}
    try { sock?.sink.close(); } catch (_) {}
  }

  bool get _isSovereignCircle {
    final plan = (_profile['subscription_plan'] ?? _profile['tier'] ?? '').toString().toUpperCase();
    return plan == 'TOP_TIER' || plan.contains('SOVEREIGN') || plan == 'TOP';
  }

  String get _currentPlanKey {
    final plan = (_profile['subscription_plan'] ?? _profile['tier'] ?? '').toString().toUpperCase();
    if (plan.contains('TOP') || plan.contains('SOVEREIGN')) return 'TOP_TIER';
    if (plan.contains('FAMILY')) return 'FAMILY';
    if (plan.contains('STANDARD') || plan.contains('INNER') || plan.contains('CHAMBER')) return 'STANDARD';
    if (plan.contains('COACH_ONLY')) return 'COACH_ONLY';
    return 'TRIAL';
  }

  int get _currentPlanRank {
    switch (_currentPlanKey) {
      case 'TRIAL': return 0;
      case 'STANDARD': return 1;
      case 'TOP_TIER': return 2;
      case 'FAMILY': return 3;
      default: return 0;
    }
  }

  bool get _canDowngradeToTrial {
    final prev = (_profile['previous_plan'] ?? '').toString().toUpperCase();
    final current = _currentPlanKey;
    if (current == 'STANDARD' || current == 'TOP_TIER') return false;
    if (prev == 'STANDARD' || prev == 'TOP_TIER') return false;
    final trialEnd = (_profile['trial_end_date'] ?? '').toString();
    if (trialEnd.isNotEmpty) {
      try {
        final end = DateTime.parse(trialEnd);
        if (end.isBefore(DateTime.now())) return false;
      } catch (_) {}
    }
    return true;
  }

  // ---- Buy Tokens ----

  static const _tokenPackIapMap = <String, String>{
    'light': PaymentService.tokenLight,
    'standard': PaymentService.tokenStandard,
    'power': PaymentService.tokenPower,
    'ultimate': PaymentService.tokenUltimate,
  };

  void _showBuyTokensSheet() {
    final packs = [
      {'id': 'light', 'label': 'Light Pack', 'tokens': '15,000', 'price': '\$3.00', 'icon': Icons.flash_on},
      {'id': 'standard', 'label': 'Standard Pack', 'tokens': '50,000', 'price': '\$7.00', 'icon': Icons.bolt},
      {'id': 'power', 'label': 'Power Pack', 'tokens': '150,000', 'price': '\$20.00', 'icon': Icons.local_fire_department},
      {'id': 'ultimate', 'label': 'Ultimate Pack', 'tokens': '1,000,000', 'price': '\$125.00', 'icon': Icons.diamond},
    ];
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => Container(
        decoration: const BoxDecoration(
          color: Color(0xFF111111),
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(2))),
            ),
            const SizedBox(height: 16),
            const Text('Buy Token Packs', style: TextStyle(color: Color(0xFFC9A962), fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            const Text('Add tokens to your balance instantly.', style: TextStyle(color: Colors.white54, fontSize: 13)),
            const SizedBox(height: 20),
            ...packs.map((pack) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () {
                  Navigator.pop(ctx);
                  _purchaseTokenPack(pack['id'] as String);
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                  decoration: BoxDecoration(
                    color: const Color(0xFF0A0A0A),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.3)),
                  ),
                  child: Row(
                    children: [
                      Icon(pack['icon'] as IconData, color: const Color(0xFFC9A962), size: 28),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(pack['label'] as String, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14)),
                            Text('${pack['tokens']} tokens', style: const TextStyle(color: Colors.white60, fontSize: 12)),
                          ],
                        ),
                      ),
                      Text(pack['price'] as String, style: const TextStyle(color: Color(0xFFC9A962), fontWeight: FontWeight.bold, fontSize: 16)),
                    ],
                  ),
                ),
              ),
            )),
            const SizedBox(height: 10),
          ],
        ),
      ),
    );
  }

  Future<void> _purchaseTokenPack(String packId) async {
    if (isNativeIOS) {
      final iapId = _tokenPackIapMap[packId];
      if (iapId != null) {
        final uid = _profile['hardware_id'] ?? _profile['username'] ?? '';
        final token = _profile['token'] as String?;
        PaymentService.instance.setAuthContext(uid, token);
        await PaymentService.instance.purchase(iapId);
      }
      return;
    }

    try {
      final token = _profile['token'] ?? '';
      final username = _profile['username'] ?? '';
      final resp = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/billing/token-packs/purchase'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'pack_id': packId,
          'username': username,
        }),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final url = data['checkout_url'];
        if (url != null && mounted) {
          await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Purchase failed: ${resp.body}'), backgroundColor: Colors.red),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  // ---- Change Plan (Upgrade or Downgrade) ----
  void _showChangePlanSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _ChangePlanSheet(
        currentPlanKey: _currentPlanKey,
        currentPlanRank: _currentPlanRank,
        canDowngradeToTrial: _canDowngradeToTrial,
        onSelect: (planKey, isUpgrade) {
          Navigator.pop(ctx);
          _confirmPlanChange(planKey, isUpgrade);
        },
      ),
    );
  }

  void _confirmPlanChange(String planKey, bool isUpgrade) {
    final names = {
      'TRIAL': 'Threshold',
      'STANDARD': 'Inner Chamber',
      'TOP_TIER': 'Sovereign Circle',
    };
    final prices = {
      'TRIAL': 'Free',
      'STANDARD': '\$49/month',
      'TOP_TIER': '\$149/month',
    };
    final currentName = names[_currentPlanKey] ?? _currentPlanKey;
    final newName = names[planKey] ?? planKey;
    final newPrice = prices[planKey] ?? '';

    // Determine which tier is higher for the 30-day billing policy
    final higherTier = isUpgrade ? newName : currentName;
    final higherPrice = isUpgrade ? newPrice : (prices[_currentPlanKey] ?? '');

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: Text(
          isUpgrade ? 'Upgrade to $newName' : 'Downgrade to $newName',
          style: TextStyle(
            color: isUpgrade ? _Design.gold : _Design.cyan,
            fontFamily: 'Courier',
          ),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              isUpgrade
                  ? 'You are upgrading from $currentName to $newName ($newPrice).'
                  : 'You are downgrading from $currentName to $newName ($newPrice).',
              style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
            ),
            const SizedBox(height: 14),

            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.bgVoid,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.gold.withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(isNativeIOS ? 'Subscription Info' : '30-Day Billing Policy',
                      style: const TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 6),
                  if (isNativeIOS) ...[
                    Text(
                      isUpgrade
                          ? 'Your upgrade will be processed through the App Store. Any remaining value from your current plan is prorated.'
                          : 'To manage or downgrade your subscription, go to Settings > Apple ID > Subscriptions on your device.',
                      style: const TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.4),
                    ),
                  ] else if (isUpgrade) ...[
                    const Text(
                      'Your new plan takes effect immediately with full access to upgraded features.',
                      style: TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.4),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'You will be billed at the $newName rate ($newPrice) for the remainder of this billing cycle.',
                      style: const TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.4),
                    ),
                  ] else ...[
                    Text(
                      'You will retain full $currentName access for the remainder of your current 30-day billing cycle.',
                      style: const TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.4),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'You are still billed at the $higherTier rate ($higherPrice) this month. The $newName rate starts on your next billing date.',
                      style: const TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.4),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 14),

            // Data preservation notice
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: _Design.green.withOpacity(0.08),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(Icons.shield, color: _Design.green, size: 16),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'Your conversation history, metrics, sessions, and all data are always preserved.',
                      style: TextStyle(color: _Design.green, fontSize: 11),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: isUpgrade ? _Design.gold : _Design.cyan,
            ),
            onPressed: () {
              Navigator.pop(ctx);
              if (isNativeIOS) {
                if (isUpgrade) {
                  _processUpgradeViaIAP(planKey);
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('To downgrade, go to Settings > Apple ID > Subscriptions on your device.'),
                      backgroundColor: Color(0xFF1A1A1A),
                      duration: Duration(seconds: 5),
                    ),
                  );
                }
              } else {
                _openStripeCheckoutForPlanChange(planKey, newName, isUpgrade);
              }
            },
            child: Text(
              isUpgrade ? 'Confirm Upgrade' : 'Confirm Downgrade',
              style: const TextStyle(color: Colors.black, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _openStripeCheckoutForPlanChange(String planKey, String planName, bool isUpgrade) async {
    final token = _profile['token'] ?? '';
    final username = _profile['username'] ?? '';
    if (username.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('User not found. Please re-login.'), backgroundColor: Colors.red),
        );
      }
      return;
    }

    try {
      final resp = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/billing/checkout'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'tier': planKey,
          'success_url': 'https://app.sovereignsanctuary.net/payment-success',
          'cancel_url': 'https://app.sovereignsanctuary.net/payment-cancel',
        }),
      ).timeout(const Duration(seconds: 15));

      if (!mounted) return;

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final url = data['checkout_url'];
        if (url != null) {
          await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Complete your ${isUpgrade ? "upgrade" : "plan change"} in the browser'),
              backgroundColor: const Color(0xFF1A1A1A),
            ),
          );
        }
      } else {
        final body = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${body['detail'] ?? 'Could not start checkout'}'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Connection error: $e'), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _processUpgradeViaIAP(String planKey) async {
    final iapIds = <String, String>{
      'STANDARD': PaymentService.innerChamberMonthly,
      'TOP_TIER': PaymentService.sovereignCircleMonthly,
    };
    final iapId = iapIds[planKey];
    if (iapId == null) return;
    final uid = _profile['hardware_id'] ?? _profile['username'] ?? '';
    final token = _profile['token'] as String?;
    PaymentService.instance.setAuthContext(uid, token);
    await PaymentService.instance.purchase(iapId);
  }

  void _sendWs(Map<String, dynamic> msg) {
    try {
      widget.socket?.sink.add(jsonEncode(msg));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Connection lost. Please go back and try again.'),
          backgroundColor: _Design.red,
        ));
      }
    }
  }

  Widget _billingLink(IconData icon, String label, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          color: _Design.bgVoid,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: _Design.border),
        ),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, color: _Design.gold, size: 18),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 10)),
        ]),
      ),
    );
  }

  void _saveProfile() {
    _sendWs({
      'type': 'update_profile',
      'email': _emailCtrl.text.trim(),
      'phone': _phoneCtrl.text.trim(),
      'timezone': _timezoneCtrl.text.trim(),
      'emergency_contact': _emergencyCtrl.text.trim(),
    });
    setState(() => _editingProfile = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Profile updated'), backgroundColor: Color(0xFF1A1A1A)),
    );
  }

  void _saveNotificationPrefs() {
    _sendWs({
      'type': 'update_notification_prefs',
      'push_enabled': _notifPush,
      'session_reminders': _notifSessionReminders,
      'crisis_alerts': _notifCrisisAlerts,
    });
  }

  void _saveVoicePref() {
    _sendWs({
      'type': 'update_voice_preference',
      'voice_mode_default': _voiceModeDefault,
    });
  }

  // ---- Web-safe share: clipboard fallback for Flutter web ----
  Future<void> _safeShare(String text, {String subject = ''}) async {
    if (kIsWeb) {
      // Share.share() throws MissingPluginException on Flutter web.
      // Copy to clipboard and show confirmation instead.
      await Clipboard.setData(ClipboardData(text: text));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Invite message copied to clipboard!'),
          backgroundColor: _Design.green,
          duration: Duration(seconds: 3),
        ));
      }
    } else {
      await Share.share(text, subject: subject);
    }
  }

  // ---- Invite a Friend ----
  void _inviteFriend() {
    try {
      const downloadLink = 'https://app.sovereignsanctuary.net';
      const message =
          "Hey! I've been working with Little Nate — an AI companion that's "
          "helped me understand myself in ways I didn't expect. If you're "
          "curious, try it out: $downloadLink\n\nHe's waiting for you.";
      _safeShare(message, subject: 'Meet Little Nate');
    } catch (e, st) {
      debugPrint('[Settings] Invite a Friend Share error: $e\n$st');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not open share: ${e.toString()}'),
          backgroundColor: Colors.red.shade700,
        ));
      }
    }
  }

  // ---- Family Invite (Sovereign Circle) — Batch ----
  void _showFamilyInviteDialog() {
    final members = <Map<String, dynamic>>[
      {'name': TextEditingController(), 'contact': TextEditingController(), 'role': 'SPOUSE'},
    ];

    String _billingSummary(List<Map<String, dynamic>> m) {
      int free = 0;
      int paid = 0;
      bool hasSpouse = false;
      bool hasFirstDep = false;
      for (final entry in m) {
        final r = entry['role'] as String;
        if (r == 'SPOUSE' && !hasSpouse) { free++; hasSpouse = true; }
        else if (r == 'SPOUSE') { paid++; }
        else if (r == 'DEPENDENT' && !hasFirstDep) { free++; hasFirstDep = true; }
        else { paid++; }
      }
      if (paid == 0) return 'Estimated: Free';
      return 'Estimated: $free free + $paid x \$75/mo = \$${paid * 75}/mo';
    }

    bool _validate(List<Map<String, dynamic>> m) {
      int spouseCount = 0;
      for (final entry in m) {
        if (entry['role'] == 'SPOUSE') spouseCount++;
      }
      return spouseCount <= 1;
    }

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('Invite Family Members', style: TextStyle(color: _Design.gold, fontFamily: 'Courier')),
          content: SizedBox(
            width: double.maxFinite,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Add each family member below. Assign a role and provide their phone or email so they receive the invitation.',
                    style: TextStyle(color: _Design.textSecondary, fontSize: 11)),
                  const SizedBox(height: 16),
                  ...List.generate(members.length, (i) {
                    final entry = members[i];
                    return Container(
                      margin: const EdgeInsets.only(bottom: 12),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _Design.bgVoid,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: _Design.border),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Text('Member ${i + 1}', style: const TextStyle(color: _Design.gold, fontSize: 12, fontWeight: FontWeight.w600)),
                              const Spacer(),
                              if (members.length > 1)
                                GestureDetector(
                                  onTap: () => setDialogState(() => members.removeAt(i)),
                                  child: const Icon(Icons.close, color: _Design.red, size: 18),
                                ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          _buildDialogField('Name', entry['name'] as TextEditingController),
                          const SizedBox(height: 8),
                          _buildDialogField('Phone or Email', entry['contact'] as TextEditingController),
                          const SizedBox(height: 8),
                          DropdownButton<String>(
                            value: entry['role'] as String,
                            dropdownColor: _Design.bgElevated,
                            isExpanded: true,
                            style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                            items: const [
                              DropdownMenuItem(value: 'SPOUSE', child: Text('Spouse (Free)')),
                              DropdownMenuItem(value: 'DEPENDENT', child: Text('Dependent (1st Free, then \$75/mo)')),
                              DropdownMenuItem(value: 'ADDITIONAL', child: Text('Additional Member (\$75/mo)')),
                            ],
                            onChanged: (v) => setDialogState(() => entry['role'] = v!),
                          ),
                        ],
                      ),
                    );
                  }),
                  if (members.length < 10)
                    TextButton.icon(
                      onPressed: () => setDialogState(() {
                        members.add({'name': TextEditingController(), 'contact': TextEditingController(), 'role': 'DEPENDENT'});
                      }),
                      icon: const Icon(Icons.add_circle_outline, color: _Design.gold, size: 18),
                      label: const Text('Add Another Member', style: TextStyle(color: _Design.gold, fontSize: 12)),
                    ),
                  const SizedBox(height: 12),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: _Design.bgElevated,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: _Design.border),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Billing Summary', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                        const SizedBox(height: 4),
                        const Text('\u2022 Spouse: Free (first one)', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                        const Text('\u2022 First Dependent: Free', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                        const Text('\u2022 Additional members: \$75/month each', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                        const Text('\u2022 All charges billed to Head of Household', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                        const SizedBox(height: 8),
                        Text(_billingSummary(members), style: const TextStyle(color: _Design.gold, fontSize: 12, fontWeight: FontWeight.w600)),
                      ],
                    ),
                  ),
                  if (!_validate(members))
                    const Padding(
                      padding: EdgeInsets.only(top: 8),
                      child: Text('Only one Spouse is allowed per family.', style: TextStyle(color: _Design.red, fontSize: 11)),
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
              onPressed: !_validate(members) ? null : () => _sendFamilyInviteBatch(ctx, members),
              child: Text(
                members.length == 1 ? 'Send Invite' : 'Send All ${members.length} Invites',
                style: const TextStyle(color: Colors.black),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _sendFamilyInviteBatch(BuildContext dialogCtx, List<Map<String, dynamic>> members) async {
    final validMembers = <Map<String, String>>[];
    for (final m in members) {
      final name = (m['name'] as TextEditingController).text.trim();
      final contact = (m['contact'] as TextEditingController).text.trim();
      final role = m['role'] as String;
      if (name.isNotEmpty && contact.isNotEmpty) {
        validMembers.add({'name': name, 'contact': contact, 'role': role});
      }
    }
    if (validMembers.isEmpty) return;

    Navigator.pop(dialogCtx);

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('Sending ${validMembers.length} invite${validMembers.length > 1 ? 's' : ''}...'),
      duration: const Duration(seconds: 3),
    ));

    WebSocketChannel? inviteSocket;
    StreamSubscription? sub;
    final completer = Completer<Map<String, dynamic>?>();

    try {
      final wsUrl = AppConfig.wsUrl;
      inviteSocket = WebSocketChannel.connect(Uri.parse(wsUrl));

      sub = inviteSocket.stream.listen((raw) {
        if (completer.isCompleted) return;
        try {
          final data = jsonDecode(raw) as Map<String, dynamic>;
          final type = (data['type'] ?? '').toString();
          if (type == 'family_invite_batch_result') {
            completer.complete(data);
          } else if (type == 'family_invite_error') {
            completer.completeError(data['message'] ?? 'Batch invite failed');
          } else if (type == 'connected') {
            inviteSocket?.sink.add(jsonEncode({
              'type': 'auth',
              'token': _profile['token'] ?? widget.profile['token'] ?? '',
              'hardware_id': _profile['hardware_id'] ?? widget.profile['hardware_id'] ?? '',
            }));
          } else if (type == 'auth_success' || type == 'login_success') {
            inviteSocket?.sink.add(jsonEncode({
              'type': 'generate_family_invite_tokens_batch',
              'members': validMembers,
            }));
          }
        } catch (_) {}
      }, onError: (e) {
        if (!completer.isCompleted) completer.completeError(e);
      }, onDone: () {
        if (!completer.isCompleted) completer.completeError('Connection closed');
      });

      final result = await completer.future.timeout(
        const Duration(seconds: 30),
        onTimeout: () => throw TimeoutException('Request timed out'),
      );

      try { await sub.cancel(); } catch (_) {}
      try { await inviteSocket.sink.close(); } catch (_) {}

      if (!mounted) return;
      final results = (result?['results'] as List<dynamic>?) ?? [];
      final sentCount = results.where((r) => r['notification_sent'] == true).length;
      final totalCount = results.length;
      final inviterName = _profile['name'] ?? 'Your family';

      final shareLines = <String>[];
      shareLines.add('$inviterName has invited you to join their Family Circle on Sovereign Sanctuary.\n');
      for (final r in results) {
        final token = (r['token'] ?? '').toString();
        final name = (r['name'] ?? '').toString();
        final url = 'https://app.sovereignsanctuary.net/family-invite?code=$token';
        shareLines.add('$name: $url (code: $token)');
      }
      shareLines.add('\nDownload: https://app.sovereignsanctuary.net');
      await _safeShare(shareLines.join('\n'), subject: 'Sovereign Sanctuary Family Invites');

      if (mounted) {
        final emailCount = results.where((r) => r['notification_method'] == 'email').length;
        final smsCount = results.where((r) => r['notification_method'] == 'sms').length;
        final parts = <String>[];
        if (emailCount > 0) parts.add('$emailCount email');
        if (smsCount > 0) parts.add('$smsCount SMS');
        final method = parts.isNotEmpty ? ' (${parts.join(', ')})' : '';
        final statusMsg = sentCount > 0
            ? '$sentCount of $totalCount invite${totalCount > 1 ? 's' : ''} sent$method'
            : '$totalCount invite code${totalCount > 1 ? 's' : ''} generated (share manually)';
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(statusMsg),
          backgroundColor: sentCount > 0 ? _Design.green : Colors.orange,
          duration: const Duration(seconds: 5),
        ));
      }
    } catch (e) {
      try { sub?.cancel(); } catch (_) {}
      try { inviteSocket?.sink.close(); } catch (_) {}
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not send invites: ${e.toString().replaceAll('TimeoutException:', '').trim()}'),
          backgroundColor: _Design.red,
          duration: const Duration(seconds: 5),
        ));
      }
    }
  }

  Widget _buildDialogField(String label, TextEditingController ctrl) {
    return TextField(
      controller: ctrl,
      style: const TextStyle(color: _Design.textPrimary, fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: _Design.textSecondary, fontSize: 12),
        enabledBorder: const UnderlineInputBorder(borderSide: BorderSide(color: _Design.border)),
        focusedBorder: const UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)),
      ),
    );
  }

  // ---- Upgrade to Coach ----
  void _requestCoachUpgrade() {
    final upgradeStatus = _profile['upgrade_to_coach_status'] ?? '';
    if (upgradeStatus == 'PENDING') {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Your coach upgrade request is pending admin approval'), backgroundColor: Color(0xFFC9A962)),
      );
      return;
    }
    final dojoPrices = <String, double>{
      'therapist': 175.0, 'project_pm': 250.0, 'business': 325.0,
      'cnc': 150.0, 'mcat': 500.0, 'teacher': 225.0, 'judge': 2100.0,
    };
    final dojoLabels = <String, String>{
      'therapist': 'Therapist', 'project_pm': 'Project PM', 'business': 'Business',
      'cnc': 'CNC', 'mcat': 'MCAT', 'teacher': 'Teacher', 'judge': 'Judge',
    };
    final selected = <String>{};
    final feeCtrl = TextEditingController();
    final zoomCtrl = TextEditingController();
    final emailCtrl = TextEditingController(text: _profile['email'] ?? '');
    final phoneCtrl = TextEditingController(text: _profile['phone'] ?? '');

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setDlgState) {
        final nonJudge = selected.where((d) => d != 'judge').length;
        final discounts = [0, 0, 10, 15, 20, 25, 30];
        final disc = nonJudge < discounts.length ? discounts[nonJudge] : 30;
        double total = 0;
        for (final d in selected) {
          final price = dojoPrices[d] ?? 0;
          total += d == 'judge' ? price : price * (1 - disc / 100);
        }

        return AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('UPGRADE TO COACH', style: TextStyle(color: _Design.gold, fontFamily: 'Courier', fontSize: 16)),
          content: SizedBox(
            width: double.maxFinite,
            child: SingleChildScrollView(child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Select your DOJO mentoring domains:', style: TextStyle(color: Colors.grey[400], fontSize: 13)),
                const SizedBox(height: 8),
                ...dojoPrices.entries.map((e) {
                  final key = e.key;
                  final price = e.value;
                  final label = dojoLabels[key] ?? key;
                  return CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    activeColor: _Design.gold,
                    checkColor: Colors.black,
                    value: selected.contains(key),
                    onChanged: (v) => setDlgState(() { v == true ? selected.add(key) : selected.remove(key); }),
                    title: Text('$label — \$${price.toStringAsFixed(0)}/mo', style: const TextStyle(color: Colors.white, fontSize: 13)),
                  );
                }),
                if (disc > 0)
                  Padding(padding: const EdgeInsets.only(top: 4),
                    child: Text('$disc% multi-DOJO discount applied', style: const TextStyle(color: _Design.cyan, fontSize: 11))),
                if (selected.contains('judge'))
                  const Padding(padding: EdgeInsets.only(top: 2),
                    child: Text('Judge (\$2,100/mo) is always full price', style: TextStyle(color: Colors.orange, fontSize: 11))),
                Padding(padding: const EdgeInsets.only(top: 8),
                  child: Text('Monthly total: \$${total.toStringAsFixed(2)}', style: const TextStyle(color: _Design.gold, fontSize: 14, fontWeight: FontWeight.bold))),
                const SizedBox(height: 16),
                TextField(controller: feeCtrl, style: const TextStyle(color: Colors.white, fontSize: 13),
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Your Coaching Fee (\$/hr)', labelStyle: TextStyle(color: Colors.grey, fontSize: 12),
                    enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFF252525))),
                    focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)))),
                const SizedBox(height: 8),
                TextField(controller: zoomCtrl, style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: const InputDecoration(labelText: 'Zoom Meeting Link (optional)', labelStyle: TextStyle(color: Colors.grey, fontSize: 12),
                    enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFF252525))),
                    focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)))),
                const SizedBox(height: 8),
                TextField(controller: emailCtrl, style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: const InputDecoration(labelText: 'Professional Email', labelStyle: TextStyle(color: Colors.grey, fontSize: 12),
                    enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFF252525))),
                    focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)))),
                const SizedBox(height: 8),
                TextField(controller: phoneCtrl, style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: const InputDecoration(labelText: 'Phone Number', labelStyle: TextStyle(color: Colors.grey, fontSize: 12),
                    enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFF252525))),
                    focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)))),
                const SizedBox(height: 12),
                Text('Your existing session history and data will be preserved. Admin approval required.',
                  style: TextStyle(color: Colors.grey[600], fontSize: 11)),
              ],
            )),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.grey))),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
              onPressed: selected.isEmpty ? null : () async {
                Navigator.pop(ctx);
                if (isNativeIOS) {
                  _sendWs({
                    'type': 'request_coach_upgrade',
                    'selected_dojos': selected.toList(),
                    'coaching_fee': double.tryParse(feeCtrl.text) ?? 0,
                    'zoom_link': zoomCtrl.text.trim(),
                    'email': emailCtrl.text.trim(),
                    'phone': phoneCtrl.text.trim(),
                  });
                  setState(() { _profile['upgrade_to_coach_status'] = 'PENDING'; });
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Coach upgrade request submitted for admin approval.'),
                        backgroundColor: Color(0xFFC9A962),
                      ),
                    );
                  }
                } else {
                  await _launchCoachUpgradeCheckout(
                    selected.toList(),
                    coaching_fee: double.tryParse(feeCtrl.text) ?? 0,
                    zoomLink: zoomCtrl.text.trim(),
                    email: emailCtrl.text.trim(),
                    phone: phoneCtrl.text.trim(),
                  );
                }
              },
              child: Text(isNativeIOS ? 'Submit Request' : 'Continue to Payment',
                  style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
            ),
          ],
        );
      }),
    );
  }

  Future<void> _launchCoachUpgradeCheckout(
    List<String> selectedDojos, {
    double coaching_fee = 0,
    String zoomLink = '',
    String email = '',
    String phone = '',
  }) async {
    final token = _profile['token'] ?? '';
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base/api/registration/checkout/coach-upgrade');

    try {
      final resp = await http.post(uri,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'selected_dojos': selectedDojos,
          'coaching_fee': coaching_fee,
          'zoom_link': zoomLink,
          'email': email,
          'phone': phone,
        }),
      ).timeout(const Duration(seconds: 15));

      if (!mounted) return;

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final url = data['checkout_url'] as String?;
        if (url != null && url.isNotEmpty) {
          await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
          setState(() { _profile['upgrade_to_coach_status'] = 'PAYMENT_IN_PROGRESS'; });
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('No checkout URL received'), backgroundColor: Colors.red),
          );
        }
      } else {
        final body = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: ${body['detail'] ?? resp.statusCode}'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Connection error: $e'), backgroundColor: Colors.red),
      );
    }
  }

  // ---- Account Deletion ----
  void _requestAccountDeletion() {
    showDialog(
      context: context,
      builder: (ctx) {
        final confirmCtrl = TextEditingController();
        return AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('Delete Your Account', style: TextStyle(color: _Design.red, fontFamily: 'Courier')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Your data will be held for 30 days. If you sign back in within '
                'that window, your account will be restored. After 30 days, all '
                'data is permanently purged.',
                style: TextStyle(color: _Design.textSecondary, fontSize: 12),
              ),
              const SizedBox(height: 16),
              const Text('Type DELETE to confirm:', style: TextStyle(color: _Design.textPrimary, fontSize: 12)),
              const SizedBox(height: 8),
              TextField(
                controller: confirmCtrl,
                style: const TextStyle(color: _Design.red, fontFamily: 'Courier'),
                decoration: const InputDecoration(
                  hintText: 'DELETE',
                  hintStyle: TextStyle(color: Color(0xFF333333)),
                  enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.border)),
                  focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.red)),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _Design.red),
              onPressed: () {
                if (confirmCtrl.text.trim().toUpperCase() != 'DELETE') {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Please type DELETE to confirm')),
                  );
                  return;
                }
                Navigator.pop(ctx);
                _sendWs({'type': 'request_account_deletion'});
                // Logout
                widget.onLogout?.call();
                Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const LobbyScreen()),
                  (_) => false,
                );
              },
              child: const Text('Delete Account', style: TextStyle(color: Colors.white)),
            ),
          ],
        );
      },
    );
  }

  // ---- Weekly Coherence Brief ----
  void _showWeeklyBrief() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _WeeklyBriefDialog(profile: _profile),
    );
  }

  // ---- Data Export ----
  void _requestDataExport() async {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: const Text('Download My Data', style: TextStyle(color: _Design.gold, fontFamily: 'Courier')),
        content: const Text(
          'This will export all your personal data including:\n\n'
          '• Profile information\n'
          '• Session summaries\n'
          '• Coherence metrics\n'
          '• Wisdom extractions\n'
          '• Community attendance records\n'
          '• Billing history\n\n'
          'The export will be downloaded as a JSON file.',
          style: TextStyle(color: Colors.white70, fontSize: 14),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
            onPressed: () async {
              Navigator.pop(ctx);
              final userId = _profile['hardware_id'] ?? _profile['user_id'] ?? '';
              final token = _profile['token'] ?? '';
              try {
                final url = Uri.parse('${AppConfig.apiBaseUrl}/api/users/$userId/data-export');
                final response = await http.get(url, headers: {'Authorization': 'Bearer $token'});
                if (response.statusCode == 200) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Data exported successfully'), backgroundColor: Colors.green),
                  );
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Export failed: ${response.statusCode}'), backgroundColor: Colors.red),
                  );
                }
              } catch (e) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Export error: $e'), backgroundColor: Colors.red),
                );
              }
            },
            child: const Text('Export Data', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  // ---- Legal Viewer ----
  void _showLegalAgreement() {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => const _LegalAgreementScreen(),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final name = _profile['name'] ?? _profile['username'] ?? 'User';
    final plan = _profile['subscription_plan'] ?? _profile['tier'] ?? 'STANDARD';
    final tokenBalance = _profile['token_balance'] ?? 0;
    final tokenUsage = _profile['token_usage_month'] ?? 0;
    final tokenUsageToday = _profile['token_usage_today'] ?? 0;
    final consentVersion = _profile['consent_version'] ?? 'Unknown';

    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        title: const Text('Settings', style: TextStyle(fontFamily: 'Courier', color: _Design.gold, letterSpacing: 2)),
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // --- Profile Header ---
          _buildProfileHeader(name, plan.toString()),
          const SizedBox(height: 24),

          // --- Profile Section ---
          _sectionHeader('PROFILE', Icons.person_outline),
          _settingsCard([
            _editableRow('Email', _emailCtrl, _editingProfile),
            _editableRow('Phone', _phoneCtrl, _editingProfile),
            _editableRow('Emergency Contact', _emergencyCtrl, _editingProfile),
            _editableRow('Timezone', _timezoneCtrl, _editingProfile),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (_editingProfile) ...[
                  TextButton(
                    onPressed: () => setState(() => _editingProfile = false),
                    child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(backgroundColor: _Design.gold, padding: const EdgeInsets.symmetric(horizontal: 20)),
                    onPressed: _saveProfile,
                    child: const Text('Save', style: TextStyle(color: Colors.black, fontSize: 12)),
                  ),
                ] else
                  TextButton.icon(
                    icon: const Icon(Icons.edit, size: 14, color: _Design.gold),
                    label: const Text('Edit', style: TextStyle(color: _Design.gold, fontSize: 12)),
                    onPressed: () => setState(() => _editingProfile = true),
                  ),
              ],
            ),
          ]),
          const SizedBox(height: 20),

          // --- Share / Invite ---
          _sectionHeader('SHARE', Icons.share),
          _settingsCard([
            _actionRow(Icons.person_add, 'Invite a Friend', 'Share Little Nate via text message', _inviteFriend),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _Design.bgElevated,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.border),
              ),
              child: Row(
                children: [
                  const Icon(Icons.link, color: _Design.cyan, size: 16),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: SelectableText(
                      'https://app.sovereignsanctuary.net',
                      style: TextStyle(color: _Design.cyan, fontSize: 12, fontFamily: 'Courier'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  InkWell(
                    onTap: () {
                      Clipboard.setData(const ClipboardData(text: 'https://app.sovereignsanctuary.net'));
                      if (mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('Link copied!'),
                          backgroundColor: _Design.green,
                          duration: Duration(seconds: 2),
                        ));
                      }
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: _Design.gold.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: const Text('Copy', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.w600)),
                    ),
                  ),
                ],
              ),
            ),
          ]),
          const SizedBox(height: 20),

          // --- Family (Sovereign Circle only) ---
          if (_isSovereignCircle) ...[
            _sectionHeader('FAMILY', Icons.family_restroom),
            _settingsCard([
              _actionRow(Icons.group_add, 'Invite Family Members', 'Add spouse and dependents to your plan', _showFamilyInviteDialog),
              _infoRow('Plan', 'Sovereign Circle — Head of Household'),
            ]),
            const SizedBox(height: 12),

            // Current family members roster
            if (_familyLoading)
              const Center(child: Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: _Design.gold)),
              ))
            else if (_familyMembers.isNotEmpty || _pendingInvites.isNotEmpty) ...[
              Container(
                decoration: BoxDecoration(
                  color: _Design.bgCard,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: _Design.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Header
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      decoration: const BoxDecoration(
                        border: Border(bottom: BorderSide(color: _Design.border)),
                      ),
                      child: Row(
                        children: const [
                          Icon(Icons.people, color: _Design.gold, size: 16),
                          SizedBox(width: 8),
                          Text('Current Members', style: TextStyle(color: _Design.gold, fontSize: 12, fontWeight: FontWeight.bold, fontFamily: 'Courier')),
                        ],
                      ),
                    ),
                    // Column headers
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                      decoration: const BoxDecoration(
                        color: Color(0xFF0D0D0D),
                        border: Border(bottom: BorderSide(color: _Design.border)),
                      ),
                      child: Row(
                        children: const [
                          Expanded(flex: 3, child: Text('Name', style: TextStyle(color: _Design.textSecondary, fontSize: 10, fontWeight: FontWeight.w600))),
                          Expanded(flex: 2, child: Text('Role', style: TextStyle(color: _Design.textSecondary, fontSize: 10, fontWeight: FontWeight.w600))),
                          SizedBox(width: 40, child: Text('', style: TextStyle(fontSize: 10))),
                        ],
                      ),
                    ),
                    // Active members
                    ..._familyMembers.map((m) {
                      final name = (m['name'] ?? 'Unknown').toString();
                      final role = (m['family_role'] ?? m['role'] ?? '').toString().toUpperCase();
                      final isHead = role == 'HEAD';
                      final isMinor = m['is_minor'] == true;
                      final memberId = (m['id'] ?? m['hardware_id'] ?? '').toString();
                      final myId = (_profile['hardware_id'] ?? '').toString();
                      final isMe = memberId == myId;

                      Color roleColor = _Design.textSecondary;
                      if (role == 'HEAD') roleColor = _Design.gold;
                      else if (role == 'SPOUSE') roleColor = _Design.cyan;
                      else if (role == 'DEPENDENT') roleColor = _Design.purple;

                      return Container(
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                        decoration: const BoxDecoration(
                          border: Border(bottom: BorderSide(color: Color(0xFF1A1A1A))),
                        ),
                        child: Row(
                          children: [
                            Expanded(flex: 3, child: Text(
                              isMe ? '$name (You)' : name,
                              style: TextStyle(color: _Design.textPrimary, fontSize: 12, fontWeight: isMe ? FontWeight.w600 : FontWeight.normal),
                              overflow: TextOverflow.ellipsis,
                            )),
                            Expanded(flex: 2, child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: roleColor.withOpacity(0.12),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(role, style: TextStyle(color: roleColor, fontSize: 10, fontWeight: FontWeight.w600), textAlign: TextAlign.center),
                            )),
                            SizedBox(width: 40, child: (isHead || isMe)
                                ? const SizedBox.shrink()
                                : GestureDetector(
                                    onTap: () => _removeFamilyMember(memberId, name, isMinor),
                                    child: Icon(
                                      isMinor ? Icons.exit_to_app : Icons.person_remove,
                                      color: _Design.red.withOpacity(0.7),
                                      size: 18,
                                    ),
                                  ),
                            ),
                          ],
                        ),
                      );
                    }),
                    // Pending invites
                    if (_pendingInvites.isNotEmpty) ...[
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                        decoration: const BoxDecoration(
                          color: Color(0xFF0D0D0D),
                          border: Border(bottom: BorderSide(color: _Design.border)),
                        ),
                        child: Row(
                          children: const [
                            Icon(Icons.hourglass_top, color: _Design.textSecondary, size: 12),
                            SizedBox(width: 6),
                            Text('Pending Invites', style: TextStyle(color: _Design.textSecondary, fontSize: 10, fontWeight: FontWeight.w600)),
                          ],
                        ),
                      ),
                      ..._pendingInvites.map((inv) {
                        final name = (inv['name'] ?? 'Unknown').toString();
                        final contact = (inv['contact'] ?? '').toString();
                        final role = (inv['role'] ?? '').toString().toUpperCase();
                        final token = (inv['token'] ?? '').toString();

                        return Container(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                          decoration: const BoxDecoration(
                            border: Border(bottom: BorderSide(color: Color(0xFF1A1A1A))),
                          ),
                          child: Row(
                            children: [
                              Expanded(flex: 3, child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(name, style: const TextStyle(color: _Design.textSecondary, fontSize: 12, fontStyle: FontStyle.italic), overflow: TextOverflow.ellipsis),
                                  if (contact.isNotEmpty)
                                    Text(contact, style: const TextStyle(color: _Design.textSecondary, fontSize: 9), overflow: TextOverflow.ellipsis),
                                ],
                              )),
                              Expanded(flex: 2, child: Container(
                                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                decoration: BoxDecoration(
                                  color: Colors.orange.withOpacity(0.12),
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text('PENDING', style: TextStyle(color: Colors.orange.shade300, fontSize: 10, fontWeight: FontWeight.w600), textAlign: TextAlign.center),
                              )),
                              SizedBox(width: 40, child: GestureDetector(
                                onTap: () => _cancelFamilyInvite(token, name),
                                child: Icon(Icons.cancel_outlined, color: _Design.red.withOpacity(0.7), size: 18),
                              )),
                            ],
                          ),
                        );
                      }),
                    ],
                  ],
                ),
              ),
            ],
            const SizedBox(height: 20),
          ],

          // --- Subscription ---
          _sectionHeader('SUBSCRIPTION', Icons.workspace_premium),
          _settingsCard([
            _infoRow('Current Plan', _tierDisplayName(plan.toString())),
            _infoRow('Token Balance', '$tokenBalance tokens'),
            _infoRow('Usage This Month', '$tokenUsage tokens'),
            // Show pending downgrade if one is scheduled
            if ((_profile['pending_plan'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: _Design.cyan.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: _Design.cyan.withOpacity(0.3)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.schedule, color: _Design.cyan, size: 16),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Switching to ${_tierDisplayName(_profile['pending_plan'])} on ${_profile['pending_plan_effective'] ?? 'next billing date'}',
                        style: const TextStyle(color: _Design.cyan, fontSize: 11),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: _Design.gold,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                ),
                icon: const Icon(Icons.swap_vert, color: Colors.black, size: 18),
                label: const Text('Change Plan', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 13)),
                onPressed: _showChangePlanSheet,
              ),
            ),
            const SizedBox(height: 10),
            // Quick links to billing screens
            Row(children: [
              Expanded(child: _billingLink(Icons.credit_card, 'Payments', () {
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => PaymentMethodsScreen(currentUserProfile: _profile),
                ));
              })),
              const SizedBox(width: 8),
              Expanded(child: _billingLink(Icons.people, 'Family', () {
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => FamilyManagementScreen(
                    currentUserProfile: _profile,
                    socket: widget.socket,
                  ),
                ));
              })),
              const SizedBox(width: 8),
              Expanded(child: _billingLink(Icons.school, 'Coaching', () {
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => CoachingPackScreen(
                    currentUserProfile: _profile,
                    socket: widget.socket,
                  ),
                ));
              })),
            ]),
          ]),
          const SizedBox(height: 20),

          // --- Token Vault ---
          _sectionHeader('TOKEN VAULT', Icons.toll),
          _settingsCard([
            Container(
              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [_Design.gold.withOpacity(0.15), _Design.bgElevated],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Balance', style: TextStyle(color: _Design.textSecondary, fontSize: 11)),
                      const SizedBox(height: 2),
                      Text(
                        '${tokenBalance.toString().replaceAllMapped(RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'), (m) => '${m[1]},')} tokens',
                        style: const TextStyle(color: _Design.gold, fontSize: 22, fontWeight: FontWeight.bold, fontFamily: 'Courier'),
                      ),
                    ],
                  ),
                  const Icon(Icons.toll, color: _Design.gold, size: 32),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: _Design.bgElevated,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Column(children: [
                      const Text('Today', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                      const SizedBox(height: 4),
                      Text('$tokenUsageToday', style: const TextStyle(color: _Design.cyan, fontSize: 16, fontWeight: FontWeight.bold)),
                    ]),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: _Design.bgElevated,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Column(children: [
                      const Text('This Month', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                      const SizedBox(height: 4),
                      Text('$tokenUsage', style: const TextStyle(color: _Design.cyan, fontSize: 16, fontWeight: FontWeight.bold)),
                    ]),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: _Design.gold,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                ),
                icon: const Icon(Icons.add_circle_outline, color: Colors.black, size: 18),
                label: const Text('Buy Tokens', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 13)),
                onPressed: _showBuyTokensSheet,
              ),
            ),
          ]),
          const SizedBox(height: 20),

          // --- Sovereign Vault (STANDARD / TOP_TIER only) ---
          if (AppConfig.ENABLE_SOVEREIGN_VAULT && _hasVaultAccess) ...[
            _sectionHeader('SOVEREIGN VAULT', Icons.folder),
            _settingsCard([
              if (_vaultUsageBytes != null && _vaultLimitBytes != null) ...[
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '${_formatBytes(_vaultUsageBytes!)} of ${_formatBytes(_vaultLimitBytes!)}',
                      style: const TextStyle(
                        color: _Design.textSecondary,
                        fontSize: 12,
                        fontFamily: 'Courier',
                      ),
                    ),
                    Text(
                      '${((_vaultUsageBytes! / _vaultLimitBytes!).clamp(0.0, 1.0) * 100).toInt()}%',
                      style: const TextStyle(color: _Design.gold, fontSize: 12, fontFamily: 'Courier'),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: (_vaultUsageBytes! / _vaultLimitBytes!).clamp(0.0, 1.0),
                    minHeight: 6,
                    backgroundColor: _Design.bgElevated,
                    valueColor: AlwaysStoppedAnimation<Color>(
                      (_vaultUsageBytes! / _vaultLimitBytes!) > 0.9 ? _Design.red : _Design.gold,
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              _actionRow(Icons.folder_open, 'Browse Vault', 'View and manage your stored items', () {
                Navigator.push<String>(context, MaterialPageRoute(
                  builder: (_) => VaultBrowserScreen(profile: _profile),
                )).then((vaultItemId) {
                  if (vaultItemId != null && vaultItemId.isNotEmpty && mounted) {
                    Navigator.pop(context, {'askNateVault': vaultItemId});
                  }
                });
              }),
              _actionRow(Icons.diamond, 'Transfer Crystal', 'Import from another source', () {
                _showTransferCrystalFlow();
              }),
              if (_isSovereignCircle)
                _actionRow(Icons.auto_awesome, 'Organize with Nate', 'AI-guided content organization', () {
                  Navigator.push(context, MaterialPageRoute(
                    builder: (_) => NateOrganizerScreen(profile: _profile),
                  ));
                }),
            ]),
            const SizedBox(height: 20),
          ],

          // --- Preferences ---
          _sectionHeader('PREFERENCES', Icons.tune),
          _settingsCard([
            _toggleRow('Push Notifications', _notifPush, (v) {
              setState(() => _notifPush = v);
              _saveNotificationPrefs();
            }),
            _toggleRow('Session Reminders', _notifSessionReminders, (v) {
              setState(() => _notifSessionReminders = v);
              _saveNotificationPrefs();
            }),
            _toggleRow('Crisis Alerts', _notifCrisisAlerts, (v) {
              setState(() => _notifCrisisAlerts = v);
              _saveNotificationPrefs();
            }),
            const Divider(color: _Design.border, height: 24),
            _toggleRow('Voice Mode by Default', _voiceModeDefault, (v) {
              setState(() => _voiceModeDefault = v);
              _saveVoicePref();
            }),
            const Divider(color: _Design.border, height: 24),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Preferred Contact',
                            style: TextStyle(color: _Design.textPrimary, fontSize: 14)),
                        SizedBox(height: 2),
                        Text('How Little Nate reaches you for check-ins',
                            style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
                      ],
                    ),
                  ),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'email', label: Text('Email')),
                      ButtonSegment(value: 'sms', label: Text('SMS')),
                    ],
                    selected: {_preferredContact},
                    onSelectionChanged: (v) {
                      setState(() => _preferredContact = v.first);
                      _sendWs({
                        'type': 'update_profile',
                        'preferred_contact': _preferredContact,
                      });
                    },
                    style: ButtonStyle(
                      backgroundColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return _Design.gold.withValues(alpha: 0.3);
                        }
                        return _Design.bgElevated;
                      }),
                      foregroundColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return _Design.gold;
                        }
                        return _Design.textSecondary;
                      }),
                    ),
                  ),
                ],
              ),
            ),
          ]),
          const SizedBox(height: 20),

          // --- Your Tools ---
          _sectionHeader('YOUR TOOLS', Icons.dashboard),
          _settingsCard([
            _actionRow(Icons.quiz, 'Assessments', 'Take a quiz or self-assessment', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => QuizScreen(profile: _profile),
              ));
            }),
            _actionRow(Icons.insights, 'Coherence Reports', 'View your Nevedal coherence trends', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => NevedalReportsScreen(profile: _profile),
              ));
            }),
            _actionRow(Icons.auto_awesome, 'Weekly Brief', 'Your personalized coherence check-in', () {
              _showWeeklyBrief();
            }),
            _actionRow(Icons.history, 'Memory Search', 'Search past conversations with Nate', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => SecureSearchScreen(profile: _profile),
              ));
            }),
            _actionRow(Icons.sos, 'Distress Beacon', 'Emergency support resources', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => DistressBeaconScreen(profile: _profile, socket: widget.socket),
              ));
            }, danger: true),
          ]),
          const SizedBox(height: 20),

          if (!kIsWeb) ...[
            _sectionHeader('HOME WIDGET', Icons.widgets_outlined),
            _settingsCard([
              _actionRow(Icons.widgets_outlined, 'Set Up Home Widget', 'Daily encouragement on your home screen', () {
                showModalBottomSheet(context: context, backgroundColor: _Design.bgCard, shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))), builder: (_) {
                  final isIOS = defaultTargetPlatform == TargetPlatform.iOS;
                  return Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('Add Little Nate Widget', style: TextStyle(color: _Design.gold, fontSize: 18, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 16),
                    Text(isIOS ? '1. Long press your home screen\n2. Tap the + button (top left)\n3. Search "Little Nate"\n4. Choose Small or Medium size\n5. Tap "Add Widget"'
                        : '1. Long press your home screen\n2. Tap "Widgets"\n3. Find "Sovereign Sanctuary"\n4. Drag Little Nate widget to your screen',
                        style: const TextStyle(color: _Design.textPrimary, fontSize: 14, height: 1.6)),
                    const SizedBox(height: 24),
                  ]));
                });
              }),
            ]),
            const SizedBox(height: 20),
          ],

          // --- Assigned Coach ---
          _sectionHeader('ASSIGNED COACH', Icons.person_pin),
          _settingsCard([
            if (!_coachInfoLoaded)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16, horizontal: 16),
                child: Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: _Design.gold))),
              )
            else ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                child: Row(children: [
                  const Icon(Icons.person, color: _Design.gold, size: 28),
                  const SizedBox(width: 12),
                  Expanded(child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(_coachName, style: const TextStyle(color: _Design.textPrimary, fontSize: 16, fontWeight: FontWeight.bold)),
                      if (_coachEmail.isNotEmpty)
                        Text(_coachEmail, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
                      if (_coachSpecializations.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Wrap(
                            spacing: 6, runSpacing: 4,
                            children: _coachSpecializations.map((s) => Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                              decoration: BoxDecoration(color: _Design.gold.withOpacity(0.15), borderRadius: BorderRadius.circular(12)),
                              child: Text(s.toString(), style: const TextStyle(color: _Design.gold, fontSize: 11)),
                            )).toList(),
                          ),
                        ),
                    ],
                  )),
                ]),
              ),
              if (_coachName != 'Not Assigned' && _coachName != 'Unavailable')
                _actionRow(Icons.calendar_month, 'View Availability & Book Session', 'Schedule a live session with your coach', () {
                  Navigator.push(context, MaterialPageRoute(
                    builder: (_) => ClientScheduleScreen(
                      currentUserProfile: _profile,
                      username: (_profile['username'] ?? '').toString(),
                      password: (_profile['password'] ?? '').toString(),
                    ),
                  ));
                }),
            ],
          ]),
          const SizedBox(height: 20),

          // --- Coaching Tools ---
          _sectionHeader('COACHING TOOLS', Icons.fitness_center),
          _settingsCard([
            _actionRow(Icons.group_work, 'Group Session', 'Join a coach-led training mesh', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => CoachingMeshScreen(
                  profile: _profile,
                  token: _profile['token'] ?? '',
                  isMaster: false,
                ),
              ));
            }),
            _actionRow(Icons.diversity_3, 'Community Circle', 'Nate-to-Nate peer wisdom sessions', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => CommunityMeshScreen(
                  profile: _profile,
                ),
              ));
            }),
          ]),
          const SizedBox(height: 20),

          // --- Security ---
          _sectionHeader('SECURITY', Icons.security),
          _settingsCard([
            _toggleRow(
              _biometricAvailable
                  ? 'Biometric Login (Face ID / Fingerprint)'
                  : 'Quick Login',
              _biometricEnabled,
              (v) async {
                await _bioIdentity.setBiometricEnabled(v);
                if (v) await _bioIdentity.setBiometricDeclined(false);
                setState(() => _biometricEnabled = v);
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(v
                        ? 'Quick login enabled. Credentials will be saved on next sign-in.'
                        : 'Biometric login disabled. Credentials cleared.')),
                  );
                }
              },
            ),
            if (!_biometricAvailable && !kIsWeb)
              Padding(
                padding: const EdgeInsets.only(left: 16, bottom: 8),
                child: Text(
                  'Biometrics not available on this device. '
                  'Device PIN will be used as fallback.',
                  style: TextStyle(color: _Design.textSecondary, fontSize: 11),
                ),
              ),
            if (kIsWeb)
              Padding(
                padding: const EdgeInsets.only(left: 16, bottom: 8),
                child: Text(
                  'Biometric login is available on native mobile apps. '
                  'On web, credentials are stored securely for quick re-login.',
                  style: TextStyle(color: _Design.textSecondary, fontSize: 11),
                ),
              ),
          ]),
          const SizedBox(height: 20),

          // --- Legal & Privacy ---
          _sectionHeader('LEGAL & PRIVACY', Icons.gavel),
          _settingsCard([
            _actionRow(Icons.description, 'Terms, Privacy & Waivers', 'Full legal agreement', _showLegalAgreement),
            _actionRow(Icons.download, 'Download My Data', 'Export your personal data', _requestDataExport),
            _infoRow('Consent Version', consentVersion),
          ]),
          const SizedBox(height: 20),

          // --- About & Support ---
          _sectionHeader('ABOUT & SUPPORT', Icons.info_outline),
          _settingsCard([
            _infoRow('App Version', '1.0.1'),
            _actionRow(Icons.help_outline, 'Help & FAQ', 'Ask Little Nate anything', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => _HelpFAQScreen(role: 'CLIENT', profile: _profile),
              ));
            }),
            _actionRow(Icons.email_outlined, 'Contact Support', 'support@sovereignsanctuary.net', () {
              launchUrl(Uri.parse('mailto:support@sovereignsanctuary.net'));
            }),
          ]),
          const SizedBox(height: 20),

          // --- Become a Coach ---
          _sectionHeader('BECOME A COACH', Icons.school),
          _settingsCard([
            if (_profile['upgrade_to_coach_status'] == 'PENDING')
              _infoRow('Status', 'Upgrade pending admin approval')
            else if (_profile['upgrade_to_coach_status'] == 'REJECTED')
              _actionRow(Icons.refresh, 'Re-apply as Coach', 'Previous request was declined', _requestCoachUpgrade)
            else
              _actionRow(Icons.trending_up, 'Upgrade to Coach', 'Access DOJOs, mentoring, and client tools', _requestCoachUpgrade),
          ]),
          const SizedBox(height: 20),

          // --- Account ---
          _sectionHeader('ACCOUNT', Icons.manage_accounts),
          _settingsCard([
            _actionRow(Icons.delete_forever, 'Delete My Account', '30-day recovery window', _requestAccountDeletion, danger: true),
            _actionRow(Icons.logout, 'Logout', null, () {
              _bioIdentity.clearCredentials();
              widget.onLogout?.call();
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const LobbyScreen()),
                (_) => false,
              );
            }, danger: true),
          ]),
          const SizedBox(height: 40),
        ],
      ),
    );
  }

  // --- Reusable Widgets ---

  Widget _buildProfileHeader(String name, String plan) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _Design.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _Design.border),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 30,
            backgroundColor: _Design.gold.withOpacity(0.2),
            child: Text(
              name.isNotEmpty ? name[0].toUpperCase() : '?',
              style: const TextStyle(color: _Design.gold, fontSize: 24, fontWeight: FontWeight.bold),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: const TextStyle(color: _Design.textPrimary, fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: _Design.gold.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    plan.replaceAll('_', ' ').toUpperCase(),
                    style: const TextStyle(color: _Design.gold, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 1),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _sectionHeader(String title, IconData icon) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Icon(icon, color: _Design.gold, size: 16),
          const SizedBox(width: 8),
          Text(title, style: const TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 2)),
        ],
      ),
    );
  }

  Widget _settingsCard(List<Widget> children) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
    );
  }

  Widget _editableRow(String label, TextEditingController ctrl, bool editing) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(
            width: 120,
            child: Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
          ),
          Expanded(
            child: editing
                ? TextField(
                    controller: ctrl,
                    style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                    decoration: const InputDecoration(
                      isDense: true,
                      contentPadding: EdgeInsets.symmetric(vertical: 8),
                      enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.border)),
                      focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)),
                    ),
                  )
                : Text(ctrl.text.isEmpty ? '—' : ctrl.text, style: const TextStyle(color: _Design.textPrimary, fontSize: 13)),
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
          Flexible(child: Text(value, style: const TextStyle(color: _Design.textPrimary, fontSize: 13), textAlign: TextAlign.right)),
        ],
      ),
    );
  }

  // ─── Transfer Crystal Flow ───
  void _showTransferCrystalFlow() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _Design.bgCard,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Transfer Crystal', style: TextStyle(color: _Design.gold, fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            const Text('Import your AI chat history from another platform.', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
            const SizedBox(height: 16),
            _transferSourceTile(ctx, 'ChatGPT (OpenAI)', 'ZIP export from settings', Icons.chat_bubble, 'chatgpt'),
            _transferSourceTile(ctx, 'Claude (Anthropic)', 'JSON conversations export', Icons.psychology, 'claude'),
            _transferSourceTile(ctx, 'Gemini (Google)', 'Google Takeout export', Icons.auto_awesome, 'gemini'),
            _transferSourceTile(ctx, 'Replika', 'Data export (JSON or CSV)', Icons.favorite, 'replika'),
            const SizedBox(height: 8),
            ListTile(
              leading: const Icon(Icons.auto_fix_high, color: _Design.gold),
              title: const Text('Auto-Detect', style: TextStyle(color: _Design.textPrimary)),
              subtitle: const Text('Pick any file and we\'ll figure it out', style: TextStyle(color: _Design.textSecondary, fontSize: 11)),
              onTap: () { Navigator.pop(ctx); _pickAndUploadCrystal('auto'); },
            ),
          ],
        ),
      ),
    );
  }

  Widget _transferSourceTile(BuildContext ctx, String title, String subtitle, IconData icon, String source) {
    return ListTile(
      leading: Icon(icon, color: _Design.gold),
      title: Text(title, style: const TextStyle(color: _Design.textPrimary)),
      subtitle: Text(subtitle, style: const TextStyle(color: _Design.textSecondary, fontSize: 11)),
      onTap: () { Navigator.pop(ctx); _pickAndUploadCrystal(source); },
    );
  }

  Future<void> _pickAndUploadCrystal(String source) async {
    try {
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: false,
        type: FileType.custom,
        allowedExtensions: ['zip', 'json', 'csv'],
      );
      if (result == null || result.files.isEmpty) return;
      final file = result.files.single;
      Uint8List? bytes = file.bytes;
      if (bytes == null && file.path != null && !kIsWeb) {
        final f = File(file.path!);
        bytes = Uint8List.fromList(await f.readAsBytes());
      }
      if (bytes == null) return;

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Importing... this may take a moment'), backgroundColor: _Design.gold),
        );
      }

      final userId = (_profile['hardware_id'] ?? _profile['id'] ?? '').toString();
      final base = AppConfig.apiBaseUrl;
      final uri = Uri.parse('$base/api/v1/vault/import');
      final request = http.MultipartRequest('POST', uri);
      request.headers['X-User-Id'] = userId;
      request.fields['source'] = source;
      request.files.add(http.MultipartFile.fromBytes('file', bytes, filename: file.name));
      final streamed = await request.send().timeout(const Duration(seconds: 120));
      final resp = await http.Response.fromStream(streamed);

      if (!mounted) return;
      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        _showCrystalResult(data);
      } else {
        final detail = resp.body.contains('detail') ? jsonDecode(resp.body)['detail'] : 'Import failed';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $detail'), backgroundColor: _Design.red),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: _Design.red),
        );
      }
    }
  }

  void _showCrystalResult(Map<String, dynamic> data) {
    final crystal = data['crystal'];
    final stats = data['stats'];
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: const Text('Transfer Crystal Created', style: TextStyle(color: _Design.gold)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (stats != null) ...[
                Text('Source: ${data['source'] ?? 'auto'}', style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
                if (stats['conversations_imported'] != null)
                  Text('Conversations: ${stats['conversations_imported']}', style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
                if (stats['messages_imported'] != null)
                  Text('Messages: ${stats['messages_imported']}', style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
                const SizedBox(height: 12),
              ],
              if (crystal != null && crystal is Map) ...[
                const Text('Crystal Summary', style: TextStyle(color: _Design.gold, fontSize: 14, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Text(crystal['summary'] ?? crystal.toString(), style: const TextStyle(color: _Design.textPrimary, fontSize: 12)),
              ],
              if (crystal == null)
                const Text('Your chat history has been imported into the Sovereign Vault.', style: TextStyle(color: _Design.textPrimary, fontSize: 12)),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Done', style: TextStyle(color: _Design.gold)),
          ),
        ],
      ),
    );
  }

  Widget _actionRow(IconData icon, String title, String? subtitle, VoidCallback onTap, {bool danger = false}) {
    final color = danger ? _Design.red : _Design.textPrimary;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: TextStyle(color: color, fontSize: 13, fontWeight: FontWeight.w500)),
                  if (subtitle != null)
                    Text(subtitle, style: const TextStyle(color: _Design.textSecondary, fontSize: 10)),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: _Design.textSecondary.withOpacity(0.5), size: 18),
          ],
        ),
      ),
    );
  }

  Widget _toggleRow(String label, bool value, ValueChanged<bool> onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: _Design.textPrimary, fontSize: 13)),
          Switch(
            value: value,
            activeColor: _Design.gold,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }

  String _tierDisplayName(String raw) {
    final upper = raw.toUpperCase();
    if (upper.contains('TOP') || upper.contains('SOVEREIGN')) return 'Sovereign Circle';
    if (upper.contains('FAMILY')) return 'Family Sovereign';
    if (upper.contains('STANDARD') || upper.contains('INNER') || upper.contains('CHAMBER')) return 'Inner Chamber';
    if (upper.contains('COACH_ONLY')) return 'Coach Only';
    if (upper.contains('TRIAL') || upper.contains('THRESHOLD')) return 'Threshold (Trial)';
    return raw.replaceAll('_', ' ');
  }
}

// =============================================================================
// CHANGE PLAN SHEET (Upgrade + Downgrade)
// =============================================================================
class _ChangePlanSheet extends StatelessWidget {
  final String currentPlanKey;
  final int currentPlanRank;
  final bool canDowngradeToTrial;
  final void Function(String planKey, bool isUpgrade) onSelect;

  const _ChangePlanSheet({
    required this.currentPlanKey,
    required this.currentPlanRank,
    this.canDowngradeToTrial = true,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.78,
      maxChildSize: 0.92,
      minChildSize: 0.5,
      builder: (ctx, scrollCtrl) => Container(
        decoration: const BoxDecoration(
          color: _Design.bgCard,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: ListView(
          controller: scrollCtrl,
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 40),
          children: [
            // Handle bar
            Center(
              child: Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 20),
                decoration: BoxDecoration(
                  color: _Design.textSecondary.withOpacity(0.3),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const Text(
              'CHOOSE YOUR PATH',
              style: TextStyle(
                color: _Design.gold,
                fontSize: 16,
                fontWeight: FontWeight.bold,
                letterSpacing: 3,
                fontFamily: 'Courier',
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 4),
            const Text(
              'Your history and data are always preserved',
              style: TextStyle(color: _Design.textSecondary, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),

            // --- Threshold (Trial) ---
            _tierCard(
              context,
              name: 'Threshold',
              subtitle: 'Trial',
              price: 'Free',
              priceSub: '14 days',
              planKey: 'TRIAL',
              rank: 0,
              features: [
                'Basic access to Little Nate',
                '10,000 tokens',
                'Text conversations',
              ],
              color: _Design.textSecondary,
              locked: !canDowngradeToTrial,
            ),
            const SizedBox(height: 16),

            // --- Inner Chamber ---
            _tierCard(
              context,
              name: 'Inner Chamber',
              subtitle: 'Standard',
              price: '\$49',
              priceSub: '/month',
              planKey: 'STANDARD',
              rank: 1,
              features: [
                'Full AI companion — voice & text',
                '50,000 tokens/month',
                'Voice biometrics & emotional tracking',
                'Session history & metrics',
                'Push notifications & reminders',
              ],
              color: _Design.cyan,
            ),
            const SizedBox(height: 16),

            // --- Sovereign Circle ---
            _tierCard(
              context,
              name: 'Sovereign Circle',
              subtitle: 'Top Tier',
              price: '\$149',
              priceSub: '/month',
              planKey: 'TOP_TIER',
              rank: 2,
              features: [
                'Everything in Inner Chamber',
                '200,000 tokens/month',
                'Avatar Mode (3D companion)',
                'Family Sanctuary (invite spouse + dependents)',
                '4 live coaching sessions/month',
                'Priority support',
              ],
              color: _Design.gold,
              recommended: true,
            ),
            const SizedBox(height: 24),

            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _Design.bgVoid,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.gold.withOpacity(0.2)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.info_outline, color: _Design.gold, size: 16),
                      const SizedBox(width: 8),
                      Text(isNativeIOS ? 'Subscription Info' : '30-Day Billing Policy',
                          style: const TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    isNativeIOS
                        ? 'Subscriptions are managed through the App Store. '
                          'The free trial cannot be reactivated after it expires or after upgrading to a paid plan. '
                          'Your conversation history, metrics, and all data are never deleted when changing plans.'
                        : 'Upgrades take effect immediately. Downgrades keep your current access through the end of your billing cycle. '
                          'The free trial cannot be reactivated after it expires or after upgrading to a paid plan. '
                          'Your conversation history, metrics, and all data are never deleted when changing plans.',
                    style: const TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.5),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _tierCard(
    BuildContext context, {
    required String name,
    required String subtitle,
    required String price,
    required String priceSub,
    required String planKey,
    required int rank,
    required List<String> features,
    required Color color,
    bool recommended = false,
    bool locked = false,
  }) {
    final isCurrent = currentPlanKey == planKey;
    final isUpgrade = rank > currentPlanRank;
    final isDowngrade = rank < currentPlanRank;

    return Container(
      decoration: BoxDecoration(
        color: isCurrent ? color.withOpacity(0.08) : _Design.bgVoid,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: isCurrent ? color : (recommended ? _Design.gold.withOpacity(0.4) : _Design.border),
          width: isCurrent || recommended ? 1.5 : 1,
        ),
      ),
      child: Column(
        children: [
          if (recommended && !isCurrent)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 6),
              decoration: BoxDecoration(
                color: _Design.gold.withOpacity(0.15),
                borderRadius: const BorderRadius.vertical(top: Radius.circular(12)),
              ),
              child: const Text(
                'RECOMMENDED',
                style: TextStyle(color: _Design.gold, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 2),
                textAlign: TextAlign.center,
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(name, style: TextStyle(color: color, fontSize: 18, fontWeight: FontWeight.bold)),
                        Text(subtitle, style: const TextStyle(color: _Design.textSecondary, fontSize: 11)),
                      ],
                    ),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Text(price, style: const TextStyle(color: _Design.textPrimary, fontSize: 26, fontWeight: FontWeight.bold)),
                        Text(priceSub, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                ...features.map((f) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    children: [
                      Icon(Icons.check, color: color, size: 14),
                      const SizedBox(width: 8),
                      Expanded(child: Text(f, style: const TextStyle(color: _Design.textPrimary, fontSize: 12))),
                    ],
                  ),
                )),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: isCurrent
                      ? Container(
                          padding: const EdgeInsets.symmetric(vertical: 10),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: color.withOpacity(0.5)),
                          ),
                          child: Text(
                            'CURRENT PLAN',
                            style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 1),
                            textAlign: TextAlign.center,
                          ),
                        )
                      : isUpgrade
                          ? ElevatedButton(
                              style: ElevatedButton.styleFrom(
                                backgroundColor: color,
                                padding: const EdgeInsets.symmetric(vertical: 12),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                              ),
                              onPressed: () => onSelect(planKey, true),
                              child: Text(
                                'Upgrade to $name',
                                style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 13),
                              ),
                            )
                          : isDowngrade
                              ? locked
                                  ? Container(
                                      padding: const EdgeInsets.symmetric(vertical: 10),
                                      decoration: BoxDecoration(
                                        borderRadius: BorderRadius.circular(8),
                                        border: Border.all(color: _Design.textSecondary.withOpacity(0.3)),
                                      ),
                                      child: const Text(
                                        'NO LONGER AVAILABLE',
                                        style: TextStyle(color: _Design.textSecondary, fontSize: 11, letterSpacing: 1),
                                        textAlign: TextAlign.center,
                                      ),
                                    )
                                  : OutlinedButton(
                                      style: OutlinedButton.styleFrom(
                                        side: BorderSide(color: color.withOpacity(0.5)),
                                        padding: const EdgeInsets.symmetric(vertical: 12),
                                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                                      ),
                                      onPressed: () => onSelect(planKey, false),
                                      child: Text(
                                        'Downgrade to $name',
                                        style: TextStyle(color: color, fontSize: 13),
                                      ),
                                    )
                              : const SizedBox.shrink(),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// COACH SETTINGS SCREEN
// =============================================================================
class CoachSettingsScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final WebSocketChannel? socket;
  final VoidCallback? onLogout;
  final Stream<Map<String, dynamic>>? messageStream;

  const CoachSettingsScreen({
    super.key,
    required this.profile,
    this.socket,
    this.onLogout,
    this.messageStream,
  });

  @override
  State<CoachSettingsScreen> createState() => _CoachSettingsScreenState();
}

class _CoachSettingsScreenState extends State<CoachSettingsScreen> {
  late Map<String, dynamic> _profile;
  bool _editingProfile = false;
  bool _editingPractice = false;

  // Profile fields
  final _emailCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _emergencyCtrl = TextEditingController();
  final _timezoneCtrl = TextEditingController();
  final _specialtiesCtrl = TextEditingController();
  final _zoomLinkCtrl = TextEditingController();
  String _coachingStyle = 'integrative';

  // Practice fields
  final _feeCtrl = TextEditingController();
  String _paymentMode = 'coach_handles';

  // Notification prefs
  bool _notifNewClient = true;
  bool _notifSessionReminders = true;
  bool _notifCrisisAlerts = true;
  bool _notifNightSchool = true;
  String _preferredContact = 'email';

  // Biometric login toggle
  final HardwareIdentity _bioIdentity = HardwareIdentity();
  bool _biometricEnabled = false;
  bool _biometricAvailable = false;

  // Coach hierarchy state
  List<Map<String, dynamic>> _assistants = [];
  Map<String, dynamic>? _masterCoach;
  bool _assistantsLoading = false;
  bool _masterLoading = false;
  List<Map<String, dynamic>> _supervisedHours = [];

  // Sheet-state callbacks so WS listener can rebuild open modals
  void Function(void Function())? _assistantsSheetState;
  void Function(void Function())? _masterSheetState;
  String _totalHours = '—';
  String _attestedHours = '—';
  String _pendingHours = '—';
  StreamSubscription? _wsSubscription;
  final Set<String> _consultationUsedToday = {};
  bool _consultationStarting = false;

  bool get _isMasterCoachApproved =>
      _profile['master_coach_approved'] == true ||
      _profile['master_coach_approved'] == 'true';

  bool get _isMasterCoachRequested =>
      _profile['master_coach_requested'] == true ||
      _profile['master_coach_requested'] == 'true';

  @override
  void initState() {
    super.initState();
    _profile = Map<String, dynamic>.from(widget.profile);
    _emailCtrl.text = _profile['email'] ?? '';
    _phoneCtrl.text = _profile['phone'] ?? '';
    _emergencyCtrl.text = _profile['emergency_contact'] ?? '';
    _timezoneCtrl.text = _profile['timezone'] ?? 'America/New_York';
    _specialtiesCtrl.text = (_profile['specialties'] ?? _profile['specialty'] ?? _profile['specializations'] ?? '').toString();
    _zoomLinkCtrl.text = _profile['zoom_link'] ?? '';
    _coachingStyle = _profile['coaching_style'] ?? 'integrative';
    _feeCtrl.text = (_profile['coaching_fee'] ?? '0').toString();
    _paymentMode = _profile['payment_mode'] ?? 'coach_handles';
    _notifNewClient = _profile['notif_new_client'] ?? true;
    _notifSessionReminders = _profile['notif_session_reminders'] ?? true;
    _notifCrisisAlerts = _profile['notif_crisis_alerts'] ?? true;
    _notifNightSchool = _profile['notif_night_school'] ?? true;
    _preferredContact = _profile['preferred_contact'] ?? 'email';
    _loadBiometricState();
    _setupHierarchyListener();
  }

  void _setupHierarchyListener() {
    _wsSubscription = widget.messageStream?.listen((data) {
      if (!mounted) return;
      try {
        final type = (data['type'] ?? '').toString();
        if (type == 'coach_hierarchy_assistants') {
          _assistants = List<Map<String, dynamic>>.from(data['assistants'] ?? []);
          _assistantsLoading = false;
          setState(() {});
          _assistantsSheetState?.call(() {});
        } else if (type == 'coach_master_info') {
          _masterCoach = data['master'] as Map<String, dynamic>?;
          _masterLoading = false;
          setState(() {});
          _masterSheetState?.call(() {});
        } else if (type == 'coach_hours_data') {
          setState(() {
            final hours = data['hours'] as List<dynamic>? ?? [];
            _supervisedHours = List<Map<String, dynamic>>.from(hours);
            final total = (data['total_hours'] ?? 0).toString();
            final attested = (data['attested_hours'] ?? 0).toString();
            final pending = (data['pending_hours'] ?? 0).toString();
            _totalHours = total;
            _attestedHours = attested;
            _pendingHours = pending;
          });
        } else if (type == 'master_status_response') {
          final status = (data['status'] ?? '').toString();
          if (status == 'requested') {
            setState(() {
              _profile['master_coach_requested'] = 'true';
            });
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Master coach status requested — awaiting admin approval')),
              );
            }
          } else if (status == 'already_approved') {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('You are already an approved master coach')),
              );
            }
          } else if (status == 'already_pending') {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Request already pending — awaiting admin approval')),
              );
            }
          }
        } else if (type == 'consultation_started') {
          setState(() {
            _consultationStarting = false;
            final session = data['session'] as Map<String, dynamic>?;
            final assistantId = session?['client_id']?.toString() ?? '';
            if (assistantId.isNotEmpty) _consultationUsedToday.add(assistantId);
          });
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(data['message']?.toString() ?? 'Consultation started'),
                backgroundColor: _Design.green,
              ),
            );
          }
        } else if (type == 'error' && (data['message'] == 'DAILY_LIMIT_REACHED' || data['message'] == 'MASTER_NOT_APPROVED' || data['message'] == 'NO_ACTIVE_HIERARCHY')) {
          setState(() => _consultationStarting = false);
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(data['detail']?.toString() ?? data['message']?.toString() ?? 'Consultation error'),
                backgroundColor: Colors.red,
              ),
            );
          }
        } else if (type == 'coach_hierarchy_error') {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text(data['message']?.toString() ?? 'Hierarchy error')),
            );
          }
        }
      } catch (_) {}
    });
  }

  void _requestMasterCoachStatus() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: const Text('Request Master Coach Status', style: TextStyle(color: _Design.gold)),
        content: const Text(
          'As a Master Coach, you can invite and manage assistant coaches under your supervision.\n\nThis request will be reviewed by an administrator.',
          style: TextStyle(color: Colors.white70, fontSize: 14),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.white54)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
            onPressed: () {
              Navigator.pop(ctx);
              _sendWs({'type': 'coach_request_master_status'});
            },
            child: const Text('Request', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  Future<void> _loadBiometricState() async {
    final enabled = await _bioIdentity.isBiometricEnabled();
    final available = await _bioIdentity.isBiometricAvailable();
    if (mounted) {
      setState(() {
        _biometricEnabled = enabled;
        _biometricAvailable = available;
      });
    }
  }

  @override
  void dispose() {
    _emailCtrl.dispose();
    _phoneCtrl.dispose();
    _emergencyCtrl.dispose();
    _timezoneCtrl.dispose();
    _specialtiesCtrl.dispose();
    _zoomLinkCtrl.dispose();
    _feeCtrl.dispose();
    _wsSubscription?.cancel();
    super.dispose();
  }

  void _sendWs(Map<String, dynamic> msg) {
    try {
      widget.socket?.sink.add(jsonEncode(msg));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Connection lost. Please go back and try again.'),
          backgroundColor: _Design.red,
        ));
      }
    }
  }

  void _saveProfile() {
    _sendWs({
      'type': 'update_profile',
      'email': _emailCtrl.text.trim(),
      'phone': _phoneCtrl.text.trim(),
      'timezone': _timezoneCtrl.text.trim(),
      'emergency_contact': _emergencyCtrl.text.trim(),
    });
    _sendWs({
      'type': 'update_coach_profile',
      'specialties': _specialtiesCtrl.text.trim(),
      'coaching_style': _coachingStyle,
      'zoom_link': _zoomLinkCtrl.text.trim(),
    });
    setState(() => _editingProfile = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Profile updated'), backgroundColor: Color(0xFF1A1A1A)),
    );
  }

  void _savePractice() {
    final fee = double.tryParse(_feeCtrl.text.trim()) ?? 0;
    _sendWs({'type': 'coach_set_fee', 'coaching_fee': fee});
    _sendWs({'type': 'coach_set_payment_mode', 'payment_mode': _paymentMode});
    setState(() => _editingPractice = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Practice settings updated'), backgroundColor: Color(0xFF1A1A1A)),
    );
  }

  void _saveNotificationPrefs() {
    _sendWs({
      'type': 'update_notification_prefs',
      'new_client_alerts': _notifNewClient,
      'session_reminders': _notifSessionReminders,
      'crisis_alerts': _notifCrisisAlerts,
      'night_school_updates': _notifNightSchool,
    });
  }

  void _showAssistantManagementPanel() {
    final inviteController = TextEditingController();
    setState(() => _assistantsLoading = true);
    _sendWs({'type': 'coach_list_assistants'});
    showModalBottomSheet(
      context: context,
      backgroundColor: _Design.bgCard,
      isScrollControlled: true,
      builder: (_) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          _assistantsSheetState = setSheetState;
          void refreshList() {
            _sendWs({'type': 'coach_list_assistants'});
            _assistantsLoading = true;
            setState(() {});
            setSheetState(() {});
          }
          return DraggableScrollableSheet(
            initialChildSize: 0.6,
            maxChildSize: 0.9,
            expand: false,
            builder: (_, scrollCtrl) => Container(
              padding: const EdgeInsets.all(16),
              child: ListView(
                controller: scrollCtrl,
                children: [
                  const Text('ASSISTANT COACHES', style: TextStyle(color: _Design.gold, fontSize: 18, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: inviteController,
                          style: const TextStyle(color: _Design.textPrimary),
                          decoration: const InputDecoration(
                            hintText: 'Coach username to invite',
                            hintStyle: TextStyle(color: _Design.textSecondary),
                            enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.goldDim)),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
                        onPressed: () {
                          if (inviteController.text.isNotEmpty && widget.socket != null) {
                            widget.socket!.sink.add(jsonEncode({
                              'type': 'coach_invite_assistant',
                              'assistant_username': inviteController.text.trim(),
                            }));
                            inviteController.clear();
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('Invitation submitted — awaiting admin approval'), backgroundColor: _Design.gold),
                            );
                            Future.delayed(const Duration(seconds: 1), refreshList);
                          }
                        },
                        child: const Text('Invite', style: TextStyle(color: Colors.black)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Current Assistants', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
                      IconButton(
                        icon: const Icon(Icons.refresh, color: _Design.gold, size: 18),
                        onPressed: refreshList,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_assistantsLoading)
                    const Center(child: Padding(
                      padding: EdgeInsets.all(20),
                      child: CircularProgressIndicator(color: _Design.gold),
                    ))
                  else if (_assistants.isEmpty)
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.all(20),
                        child: Text('No assistant coaches yet.\nInvite a coach above to get started.',
                            style: TextStyle(color: _Design.textSecondary), textAlign: TextAlign.center),
                      ),
                    )
                  else
                    ..._assistants.map((a) {
                      final aId = (a['hardware_id'] ?? a['assistant_id'] ?? '').toString();
                      final aUsername = (a['username'] ?? '').toString();
                      final isActive = a['status'] == 'active';
                      final usedToday = _consultationUsedToday.contains(aId);
                      return Container(
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _Design.bgElevated,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: _Design.border),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            isActive ? Icons.check_circle : Icons.pending,
                            color: isActive ? _Design.green : _Design.goldDim,
                            size: 20,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(a['display_name'] ?? aUsername, style: const TextStyle(color: _Design.textPrimary, fontWeight: FontWeight.w600)),
                                Text('@$aUsername', style: const TextStyle(color: _Design.textSecondary, fontSize: 11)),
                              ],
                            ),
                          ),
                          if (_isMasterCoachApproved && isActive)
                            Padding(
                              padding: const EdgeInsets.only(right: 8),
                              child: SizedBox(
                                height: 28,
                                child: ElevatedButton(
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: usedToday ? _Design.bgElevated : _Design.cyan,
                                    padding: const EdgeInsets.symmetric(horizontal: 10),
                                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                                  ),
                                  onPressed: (usedToday || _consultationStarting)
                                      ? null
                                      : () => _confirmConsultation(aId, aUsername, a['display_name'] ?? aUsername),
                                  child: Text(
                                    usedToday ? 'Used Today' : 'Consult',
                                    style: TextStyle(
                                      color: usedToday ? _Design.textSecondary : Colors.black,
                                      fontSize: 11,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: isActive ? _Design.green.withOpacity(0.15) : _Design.goldDim.withOpacity(0.15),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Text(
                              (a['status'] ?? 'unknown').toString().toUpperCase(),
                              style: TextStyle(color: isActive ? _Design.green : _Design.goldDim, fontSize: 10, fontWeight: FontWeight.bold),
                            ),
                          ),
                        ],
                      ),
                    );
                    }),
                ],
              ),
            ),
          );
        },
      ),
    ).whenComplete(() => _assistantsSheetState = null);
  }

  void _confirmConsultation(String assistantId, String assistantUsername, String displayName) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: const Text('Start Free Consultation', style: TextStyle(color: _Design.gold)),
        content: Text(
          'Start a free 15-minute consultation with $displayName?\n\nLittle Nate will be active during this session.',
          style: const TextStyle(color: _Design.textPrimary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.cyan),
            onPressed: () {
              Navigator.pop(ctx);
              setState(() => _consultationStarting = true);
              _sendWs({
                'type': 'master_consultation_request',
                'assistant_id': assistantId,
                'assistant_username': assistantUsername,
              });
            },
            child: const Text('Start Consultation', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  void _showMasterCoachPanel() {
    setState(() => _masterLoading = true);
    _sendWs({'type': 'coach_get_master'});
    showModalBottomSheet(
      context: context,
      backgroundColor: _Design.bgCard,
      builder: (_) => StatefulBuilder(
        builder: (ctx, setSheetState) {
          _masterSheetState = setSheetState;
          return Container(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('MASTER COACH', style: TextStyle(color: _Design.gold, fontSize: 18, fontWeight: FontWeight.bold)),
                const Divider(color: _Design.goldDim),
                const SizedBox(height: 12),
                if (_masterLoading)
                  const Center(child: Padding(
                    padding: EdgeInsets.all(20),
                    child: CircularProgressIndicator(color: _Design.gold),
                  ))
                else if (_masterCoach != null) ...[
                  ListTile(
                    leading: const Icon(Icons.star, color: _Design.gold),
                    title: Text(_masterCoach!['name'] ?? _masterCoach!['username'] ?? '', style: const TextStyle(color: _Design.textPrimary)),
                    subtitle: Text('@${_masterCoach!['username'] ?? ''}\nStatus: ${(_masterCoach!['status'] ?? 'active').toString().toUpperCase()}',
                        style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
                  ),
                ] else
                  const Center(
                    child: Padding(
                      padding: EdgeInsets.all(20),
                      child: Text('No master coach assigned yet.\nAccept an invitation to join a hierarchy.',
                          style: TextStyle(color: _Design.textSecondary), textAlign: TextAlign.center),
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    ).whenComplete(() => _masterSheetState = null);
  }

  void _showSupervisedHoursPanel() {
    _sendWs({
      'type': 'coach_get_hours',
      'assistant_id': _profile['hardware_id'],
    });
    showModalBottomSheet(
      context: context,
      backgroundColor: _Design.bgCard,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        maxChildSize: 0.9,
        expand: false,
        builder: (_, scrollCtrl) => Container(
          padding: const EdgeInsets.all(16),
          child: ListView(
            controller: scrollCtrl,
            children: [
              const Text('SUPERVISED HOURS', style: TextStyle(color: _Design.gold, fontSize: 18, fontWeight: FontWeight.bold)),
              const Divider(color: _Design.goldDim),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  _hoursStatCard('Total', _totalHours, _Design.gold),
                  _hoursStatCard('Attested', _attestedHours, _Design.green),
                  _hoursStatCard('Pending', _pendingHours, _Design.goldDim),
                ],
              ),
              const SizedBox(height: 20),
              const Center(
                child: Text('Hours are auto-logged from coaching mesh sessions\nand manually logged by your master coach.',
                    style: TextStyle(color: _Design.textSecondary, fontSize: 12),
                    textAlign: TextAlign.center),
              ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(side: const BorderSide(color: _Design.gold)),
                onPressed: () {
                  _sendWs({
                    'type': 'coach_get_hours',
                    'assistant_id': _profile['hardware_id'],
                  });
                },
                icon: const Icon(Icons.refresh, color: _Design.gold),
                label: const Text('Refresh Hours', style: TextStyle(color: _Design.gold)),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _hoursStatCard(String label, String value, Color color) {
    return Column(
      children: [
        Text(value, style: TextStyle(color: color, fontSize: 24, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 11)),
      ],
    );
  }

  void _requestAccountDeletion() {
    // Check for active clients
    final assignedClients = _profile['assigned_clients'] ?? [];
    if (assignedClients is List && assignedClients.isNotEmpty) {
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('Cannot Delete Account', style: TextStyle(color: _Design.red, fontFamily: 'Courier')),
          content: Text(
            'You have ${assignedClients.length} active client(s). Please transfer '
            'or unassign all clients before deleting your account.',
            style: const TextStyle(color: _Design.textSecondary, fontSize: 12),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('OK', style: TextStyle(color: _Design.gold)),
            ),
          ],
        ),
      );
      return;
    }

    // Same deletion dialog as client
    showDialog(
      context: context,
      builder: (ctx) {
        final confirmCtrl = TextEditingController();
        return AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('Delete Your Account', style: TextStyle(color: _Design.red, fontFamily: 'Courier')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Your data will be held for 30 days. If you sign back in within '
                'that window, your account will be restored. After 30 days, all '
                'data is permanently purged.',
                style: TextStyle(color: _Design.textSecondary, fontSize: 12),
              ),
              const SizedBox(height: 16),
              const Text('Type DELETE to confirm:', style: TextStyle(color: _Design.textPrimary, fontSize: 12)),
              const SizedBox(height: 8),
              TextField(
                controller: confirmCtrl,
                style: const TextStyle(color: _Design.red, fontFamily: 'Courier'),
                decoration: const InputDecoration(
                  hintText: 'DELETE',
                  hintStyle: TextStyle(color: Color(0xFF333333)),
                  enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.border)),
                  focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.red)),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _Design.red),
              onPressed: () {
                if (confirmCtrl.text.trim().toUpperCase() != 'DELETE') {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Please type DELETE to confirm')),
                  );
                  return;
                }
                Navigator.pop(ctx);
                _sendWs({'type': 'request_account_deletion'});
                widget.onLogout?.call();
                Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const LobbyScreen()),
                  (_) => false,
                );
              },
              child: const Text('Delete Account', style: TextStyle(color: Colors.white)),
            ),
          ],
        );
      },
    );
  }

  void _requestDataExport() async {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _Design.bgCard,
        title: const Text('Download My Data', style: TextStyle(color: _Design.gold, fontFamily: 'Courier')),
        content: const Text(
          'This will export all your personal data including:\n\n'
          '• Profile information\n'
          '• Session summaries & coaching records\n'
          '• Coherence metrics\n'
          '• Wisdom extractions\n'
          '• Billing history\n\n'
          'The export will be downloaded as a JSON file.',
          style: TextStyle(color: Colors.white70, fontSize: 14),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
            onPressed: () async {
              Navigator.pop(ctx);
              final userId = _profile['hardware_id'] ?? _profile['user_id'] ?? '';
              final token = _profile['token'] ?? '';
              try {
                final url = Uri.parse('${AppConfig.apiBaseUrl}/api/users/$userId/data-export');
                final response = await http.get(url, headers: {'Authorization': 'Bearer $token'});
                if (response.statusCode == 200) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Data exported successfully'), backgroundColor: Colors.green),
                  );
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Export failed: ${response.statusCode}'), backgroundColor: Colors.red),
                  );
                }
              } catch (e) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Export error: $e'), backgroundColor: Colors.red),
                );
              }
            },
            child: const Text('Export Data', style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  void _showLegalAgreement() {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => const _LegalAgreementScreen(),
    ));
  }

  Widget _buildCoachDialogField(String label, TextEditingController ctrl) {
    return TextField(
      controller: ctrl,
      style: const TextStyle(color: _Design.textPrimary, fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: _Design.textSecondary, fontSize: 12),
        enabledBorder: const UnderlineInputBorder(borderSide: BorderSide(color: _Design.border)),
        focusedBorder: const UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)),
      ),
    );
  }

  void _showCoachInviteClientDialog() {
    final nameCtrl = TextEditingController();
    final contactCtrl = TextEditingController();
    String tier = 'STANDARD';

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('Invite Client to Sign Up', style: TextStyle(color: _Design.gold, fontFamily: 'Courier')),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildCoachDialogField('Client Name', nameCtrl),
                const SizedBox(height: 12),
                _buildCoachDialogField('Email or Phone', contactCtrl),
                const SizedBox(height: 12),
                const Text('Suggested Tier', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
                const SizedBox(height: 6),
                DropdownButton<String>(
                  value: tier,
                  dropdownColor: _Design.bgElevated,
                  style: const TextStyle(color: _Design.textPrimary),
                  items: const [
                    DropdownMenuItem(value: 'STANDARD', child: Text('Standard (\$49/mo)')),
                    DropdownMenuItem(value: 'COACH_ONLY', child: Text('Coach Only (scheduling only)')),
                    DropdownMenuItem(value: 'SOVEREIGN_CIRCLE', child: Text('Sovereign Circle (\$149/mo)')),
                  ],
                  onChanged: (v) => setDialogState(() => tier = v!),
                ),
                const SizedBox(height: 12),
                const Text('Invitation will be sent via email or SMS.', style: TextStyle(color: _Design.textSecondary, fontSize: 11)),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _Design.gold),
              onPressed: () => _sendCoachInvite(ctx, nameCtrl, contactCtrl, tier),
              child: const Text('Send Invite', style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _sendCoachInvite(BuildContext dialogCtx, TextEditingController nameCtrl,
      TextEditingController contactCtrl, String tier) async {
    final contact = contactCtrl.text.trim();
    if (contact.isEmpty) return;

    Navigator.pop(dialogCtx);

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('Sending invite...'),
      duration: Duration(seconds: 2),
    ));

    WebSocketChannel? inviteSocket;
    StreamSubscription? sub;
    final completer = Completer<Map<String, dynamic>?>();

    try {
      final wsUrl = AppConfig.wsUrl;
      inviteSocket = WebSocketChannel.connect(Uri.parse(wsUrl));

      sub = inviteSocket.stream.listen((raw) {
        if (completer.isCompleted) return;
        try {
          final data = jsonDecode(raw) as Map<String, dynamic>;
          final type = (data['type'] ?? '').toString();
          if (type == 'coach_invite_sent') {
            completer.complete(data);
          } else if (type == 'coach_invite_error') {
            completer.completeError(data['message'] ?? 'Invite failed');
          } else if (type == 'connected') {
            inviteSocket?.sink.add(jsonEncode({
              'type': 'auth',
              'token': _profile['token'] ?? widget.profile['token'] ?? '',
              'hardware_id': _profile['hardware_id'] ?? widget.profile['hardware_id'] ?? '',
            }));
          } else if (type == 'auth_success' || type == 'login_success') {
            inviteSocket?.sink.add(jsonEncode({
              'type': 'coach_invite_client',
              'invitee_name': nameCtrl.text.trim(),
              'invitee_contact': contact,
              'tier': tier,
            }));
          }
        } catch (_) {}
      }, onError: (e) {
        if (!completer.isCompleted) completer.completeError(e);
      }, onDone: () {
        if (!completer.isCompleted) completer.completeError('Connection closed');
      });

      await completer.future.timeout(
        const Duration(seconds: 15),
        onTimeout: () => throw TimeoutException('Request timed out'),
      );

      try { await sub.cancel(); } catch (_) {}
      try { await inviteSocket.sink.close(); } catch (_) {}

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Invitation sent! The client will receive an email or SMS.'),
        backgroundColor: _Design.green,
      ));
    } catch (e) {
      try { sub?.cancel(); } catch (_) {}
      try { inviteSocket?.sink.close(); } catch (_) {}
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not send invite: ${e.toString().replaceAll('TimeoutException:', '').trim()}'),
          backgroundColor: _Design.red,
          duration: const Duration(seconds: 5),
        ));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final name = _profile['name'] ?? _profile['username'] ?? 'Coach';
    final tier = _profile['tier'] ?? _profile['subscription_plan'] ?? 'COACH';
    final certStatus = _profile['certification_status'] ?? 'PENDING';
    final consentVersion = _profile['consent_version'] ?? 'Unknown';
    final w9Status = (_profile['w9_submitted'] == true) ? 'Filed' : 'Missing';
    final requires1099 = (_profile['requires_1099'] == true) ? 'Required' : 'Below threshold';
    final platformFee = _profile['platform_fee_pct'] ?? 30;

    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        title: const Text('Coach Settings', style: TextStyle(fontFamily: 'Courier', color: _Design.gold, letterSpacing: 2)),
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // --- Profile Header ---
          _buildProfileHeader(name, certStatus),
          const SizedBox(height: 24),

          // --- Profile Section ---
          _sectionHeader('PROFILE', Icons.person_outline),
          _settingsCard([
            _editableRow('Email', _emailCtrl, _editingProfile),
            _editableRow('Phone', _phoneCtrl, _editingProfile),
            _editableRow('Specialties', _specialtiesCtrl, _editingProfile),
            if (_editingProfile) ...[
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    const SizedBox(width: 120, child: Text('Coaching Style', style: TextStyle(color: _Design.textSecondary, fontSize: 12))),
                    Expanded(
                      child: DropdownButton<String>(
                        value: _coachingStyle,
                        isExpanded: true,
                        dropdownColor: _Design.bgElevated,
                        style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                        items: const [
                          DropdownMenuItem(value: 'directive', child: Text('Directive')),
                          DropdownMenuItem(value: 'reflective', child: Text('Reflective')),
                          DropdownMenuItem(value: 'integrative', child: Text('Integrative')),
                        ],
                        onChanged: (v) => setState(() => _coachingStyle = v!),
                      ),
                    ),
                  ],
                ),
              ),
            ] else
              _infoRow('Coaching Style', _coachingStyle[0].toUpperCase() + _coachingStyle.substring(1)),
            _editableRow('Zoom Link', _zoomLinkCtrl, _editingProfile),
            _editableRow('Emergency Contact', _emergencyCtrl, _editingProfile),
            _editableRow('Timezone', _timezoneCtrl, _editingProfile),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (_editingProfile) ...[
                  TextButton(
                    onPressed: () => setState(() => _editingProfile = false),
                    child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(backgroundColor: _Design.gold, padding: const EdgeInsets.symmetric(horizontal: 20)),
                    onPressed: _saveProfile,
                    child: const Text('Save', style: TextStyle(color: Colors.black, fontSize: 12)),
                  ),
                ] else
                  TextButton.icon(
                    icon: const Icon(Icons.edit, size: 14, color: _Design.gold),
                    label: const Text('Edit', style: TextStyle(color: _Design.gold, fontSize: 12)),
                    onPressed: () => setState(() => _editingProfile = true),
                  ),
              ],
            ),
          ]),
          const SizedBox(height: 20),

          // --- Practice & Fees ---
          _sectionHeader('PRACTICE & FEES', Icons.attach_money),
          _settingsCard([
            _editableRow('Coaching Fee (\$/hr)', _feeCtrl, _editingPractice),
            if (_editingPractice) ...[
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    const SizedBox(width: 120, child: Text('Payment Mode', style: TextStyle(color: _Design.textSecondary, fontSize: 12))),
                    Expanded(
                      child: DropdownButton<String>(
                        value: _paymentMode,
                        isExpanded: true,
                        dropdownColor: _Design.bgElevated,
                        style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                        items: const [
                          DropdownMenuItem(value: 'coach_handles', child: Text('Coach Handles Billing')),
                          DropdownMenuItem(value: 'platform_handles', child: Text('Platform Handles Billing')),
                        ],
                        onChanged: (v) => setState(() => _paymentMode = v!),
                      ),
                    ),
                  ],
                ),
              ),
            ] else
              _infoRow('Payment Mode', _paymentMode == 'platform_handles' ? 'Platform Handles' : 'Coach Handles'),
            _infoRow('Platform Fee', '$platformFee% (min \$30)'),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (_editingPractice) ...[
                  TextButton(
                    onPressed: () => setState(() => _editingPractice = false),
                    child: const Text('Cancel', style: TextStyle(color: _Design.textSecondary)),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(backgroundColor: _Design.gold, padding: const EdgeInsets.symmetric(horizontal: 20)),
                    onPressed: _savePractice,
                    child: const Text('Save', style: TextStyle(color: Colors.black, fontSize: 12)),
                  ),
                ] else
                  TextButton.icon(
                    icon: const Icon(Icons.edit, size: 14, color: _Design.gold),
                    label: const Text('Edit', style: TextStyle(color: _Design.gold, fontSize: 12)),
                    onPressed: () => setState(() => _editingPractice = true),
                  ),
              ],
            ),
          ]),
          const SizedBox(height: 20),

          // --- Payments ---
          _sectionHeader('PAYMENTS', Icons.credit_card),
          _settingsCard([
            Row(children: [
              Expanded(child: _coachBillingLink(Icons.credit_card, 'Payment Methods', () {
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => PaymentMethodsScreen(currentUserProfile: widget.profile),
                ));
              })),
              const SizedBox(width: 8),
              Expanded(child: _coachBillingLink(Icons.receipt_long, 'Invoices', () {
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => PaymentMethodsScreen(currentUserProfile: widget.profile, initialTab: 1),
                ));
              })),
            ]),
          ]),
          const SizedBox(height: 20),

          // --- Invite Client ---
          _sectionHeader('CLIENTS', Icons.people_outline),
          _settingsCard([
            _actionRow(Icons.person_add, 'Invite Client to Sign Up', 'Send email or SMS invite for tier signup', _showCoachInviteClientDialog),
          ]),
          const SizedBox(height: 20),

          // --- Tax & Compliance ---
          _sectionHeader('TAX & COMPLIANCE', Icons.receipt_long),
          _settingsCard([
            _statusRow('W-9 Status', w9Status, w9Status == 'Filed' ? _Design.green : _Design.red),
            _statusRow('1099 Status', requires1099, requires1099 == 'Required' ? _Design.gold : _Design.textSecondary),
            _infoRow('Address Verified', (_profile['address_verified'] == true) ? 'Yes' : 'No'),
            _infoRow('TIN Document', (_profile['tin_doc_uploaded'] == true) ? 'Uploaded' : 'Not uploaded'),
          ]),
          const SizedBox(height: 20),

          // --- Preferences ---
          _sectionHeader('PREFERENCES', Icons.tune),
          _settingsCard([
            _toggleRow('New Client Alerts', _notifNewClient, (v) {
              setState(() => _notifNewClient = v);
              _saveNotificationPrefs();
            }),
            _toggleRow('Session Reminders', _notifSessionReminders, (v) {
              setState(() => _notifSessionReminders = v);
              _saveNotificationPrefs();
            }),
            _toggleRow('Crisis Alerts', _notifCrisisAlerts, (v) {
              setState(() => _notifCrisisAlerts = v);
              _saveNotificationPrefs();
            }),
            _toggleRow('Night School Updates', _notifNightSchool, (v) {
              setState(() => _notifNightSchool = v);
              _saveNotificationPrefs();
            }),
            const Divider(color: _Design.border, height: 24),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Preferred Contact',
                            style: TextStyle(color: _Design.textPrimary, fontSize: 14)),
                        SizedBox(height: 2),
                        Text('How Little Nate reaches you for check-ins',
                            style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
                      ],
                    ),
                  ),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'email', label: Text('Email')),
                      ButtonSegment(value: 'sms', label: Text('SMS')),
                    ],
                    selected: {_preferredContact},
                    onSelectionChanged: (v) {
                      setState(() => _preferredContact = v.first);
                      _sendWs({
                        'type': 'update_profile',
                        'preferred_contact': _preferredContact,
                      });
                    },
                    style: ButtonStyle(
                      backgroundColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return _Design.gold.withValues(alpha: 0.3);
                        }
                        return _Design.bgElevated;
                      }),
                      foregroundColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return _Design.gold;
                        }
                        return _Design.textSecondary;
                      }),
                    ),
                  ),
                ],
              ),
            ),
          ]),
          const SizedBox(height: 20),

          // --- Coach Tools ---
          _sectionHeader('COACH TOOLS', Icons.build_circle),
          _settingsCard([
            _actionRow(Icons.school, 'Night School', 'Wisdom entries, curriculum & training', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => NightSchoolScreen(profile: _profile),
              ));
            }),
            _actionRow(Icons.psychology_alt, 'AI Modes', 'Tri-Corder, Archivist, Guardian, Supervisor, Editor', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => AIModesSelectorScreen(sessionId: 'coach_session', profile: _profile),
              ));
            }),
          ]),
          const SizedBox(height: 20),

          // --- Coach Hierarchy ---
          _sectionHeader('COACH HIERARCHY', Icons.account_tree),
          _settingsCard([
            if (_isMasterCoachApproved) ...[
              _actionRow(Icons.people_alt, 'My Assistants', 'Manage assistant coaches under you', () {
                _showAssistantManagementPanel();
              }),
            ] else if (_isMasterCoachRequested) ...[
              _infoRow('Master Coach Status', 'Pending Approval'),
            ] else ...[
              _actionRow(Icons.star_border, 'Request Master Coach Status', 'Become a master coach to invite assistants', () {
                _requestMasterCoachStatus();
              }),
            ],
            _actionRow(Icons.supervisor_account, 'My Master Coach', 'View your supervising coach', () {
              _showMasterCoachPanel();
            }),
            _actionRow(Icons.access_time, 'Supervised Hours', 'Review and export logged hours', () {
              _showSupervisedHoursPanel();
            }),
          ]),
          const SizedBox(height: 20),

          // --- Subscription ---
          _sectionHeader('SUBSCRIPTION', Icons.workspace_premium),
          _settingsCard([
            _infoRow('Tier', tier.toString().replaceAll('_', ' ')),
            _statusRow('Certification', certStatus, certStatus == 'APPROVED' ? _Design.green : _Design.gold),
          ]),
          const SizedBox(height: 20),

          // --- Security ---
          _sectionHeader('SECURITY', Icons.security),
          _settingsCard([
            _toggleRow(
              _biometricAvailable
                  ? 'Biometric Login (Face ID / Fingerprint)'
                  : 'Quick Login',
              _biometricEnabled,
              (v) async {
                await _bioIdentity.setBiometricEnabled(v);
                if (v) await _bioIdentity.setBiometricDeclined(false);
                setState(() => _biometricEnabled = v);
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(v
                        ? 'Quick login enabled. Credentials will be saved on next sign-in.'
                        : 'Biometric login disabled. Credentials cleared.')),
                  );
                }
              },
            ),
            if (!_biometricAvailable && !kIsWeb)
              Padding(
                padding: const EdgeInsets.only(left: 16, bottom: 8),
                child: Text(
                  'Biometrics not available on this device. '
                  'Device PIN will be used as fallback.',
                  style: TextStyle(color: _Design.textSecondary, fontSize: 11),
                ),
              ),
            if (kIsWeb)
              Padding(
                padding: const EdgeInsets.only(left: 16, bottom: 8),
                child: Text(
                  'Biometric login is available on native mobile apps. '
                  'On web, credentials are stored securely for quick re-login.',
                  style: TextStyle(color: _Design.textSecondary, fontSize: 11),
                ),
              ),
          ]),
          const SizedBox(height: 20),

          // --- Legal & Privacy ---
          _sectionHeader('LEGAL & PRIVACY', Icons.gavel),
          _settingsCard([
            _actionRow(Icons.description, 'Terms, Privacy & Waivers', 'Full legal agreement', _showLegalAgreement),
            _actionRow(Icons.download, 'Download My Data', 'Export your personal data', _requestDataExport),
            _infoRow('Consent Version', consentVersion),
          ]),
          const SizedBox(height: 20),

          // --- About & Support ---
          _sectionHeader('ABOUT & SUPPORT', Icons.info_outline),
          _settingsCard([
            _infoRow('App Version', '1.0.1'),
            _actionRow(Icons.help_outline, 'Help & FAQ', 'Ask Little Nate anything', () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => _HelpFAQScreen(role: 'COACH', profile: _profile),
              ));
            }),
            _actionRow(Icons.email_outlined, 'Contact Support', 'support@sovereignsanctuary.net', () {
              launchUrl(Uri.parse('mailto:support@sovereignsanctuary.net'));
            }),
          ]),
          const SizedBox(height: 20),

          // --- Account ---
          _sectionHeader('ACCOUNT', Icons.manage_accounts),
          _settingsCard([
            _actionRow(Icons.delete_forever, 'Delete My Account', '30-day recovery window', _requestAccountDeletion, danger: true),
            _actionRow(Icons.logout, 'Logout', null, () {
              _bioIdentity.clearCredentials();
              widget.onLogout?.call();
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const LobbyScreen()),
                (_) => false,
              );
            }, danger: true),
          ]),
          const SizedBox(height: 40),
        ],
      ),
    );
  }

  // --- Reusable Widgets ---

  Widget _buildProfileHeader(String name, String certStatus) {
    final statusColor = certStatus == 'APPROVED' ? _Design.green : _Design.gold;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _Design.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _Design.border),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 30,
            backgroundColor: _Design.gold.withOpacity(0.2),
            child: const Icon(Icons.medical_services, color: _Design.gold, size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: const TextStyle(color: _Design.textPrimary, fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: statusColor.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    certStatus,
                    style: TextStyle(color: statusColor, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 1),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _sectionHeader(String title, IconData icon) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Icon(icon, color: _Design.gold, size: 16),
          const SizedBox(width: 8),
          Text(title, style: const TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 2)),
        ],
      ),
    );
  }

  Widget _settingsCard(List<Widget> children) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _Design.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
    );
  }

  Widget _coachBillingLink(IconData icon, String label, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          color: _Design.bgElevated,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: _Design.border),
        ),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(icon, color: _Design.gold, size: 20),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: _Design.textPrimary, fontSize: 11)),
        ]),
      ),
    );
  }

  Widget _editableRow(String label, TextEditingController ctrl, bool editing) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(
            width: 120,
            child: Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
          ),
          Expanded(
            child: editing
                ? TextField(
                    controller: ctrl,
                    style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                    decoration: const InputDecoration(
                      isDense: true,
                      contentPadding: EdgeInsets.symmetric(vertical: 8),
                      enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.border)),
                      focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: _Design.gold)),
                    ),
                  )
                : Text(ctrl.text.isEmpty ? '—' : ctrl.text, style: const TextStyle(color: _Design.textPrimary, fontSize: 13)),
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
          Flexible(child: Text(value, style: const TextStyle(color: _Design.textPrimary, fontSize: 13), textAlign: TextAlign.right)),
        ],
      ),
    );
  }

  Widget _statusRow(String label, String value, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: color.withOpacity(0.15),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(value, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Widget _actionRow(IconData icon, String title, String? subtitle, VoidCallback onTap, {bool danger = false}) {
    final color = danger ? _Design.red : _Design.textPrimary;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: TextStyle(color: color, fontSize: 13, fontWeight: FontWeight.w500)),
                  if (subtitle != null)
                    Text(subtitle, style: const TextStyle(color: _Design.textSecondary, fontSize: 10)),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: _Design.textSecondary.withOpacity(0.5), size: 18),
          ],
        ),
      ),
    );
  }

  Widget _toggleRow(String label, bool value, ValueChanged<bool> onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: _Design.textPrimary, fontSize: 13)),
          Switch(
            value: value,
            activeColor: _Design.gold,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// HELP & FAQ SCREEN — Powered by Little Nate (Role-aware)
// =============================================================================
class _HelpFAQScreen extends StatefulWidget {
  final String role; // "CLIENT" or "COACH"
  final Map<String, dynamic> profile;

  const _HelpFAQScreen({required this.role, required this.profile});

  @override
  State<_HelpFAQScreen> createState() => _HelpFAQScreenState();
}

class _HelpFAQScreenState extends State<_HelpFAQScreen> {
  final _questionCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  final List<Map<String, String>> _conversation = []; // {role: "user"|"nate", text: "..."}
  WebSocketChannel? _ws;
  bool _isLoading = false;
  String _streamingResponse = '';

  @override
  void initState() {
    super.initState();
    _conversation.add({
      'role': 'nate',
      'text': widget.role == 'CLIENT'
          ? "Hey there! I'm Little Nate — your platform guide. Ask me anything about how to use Sovereign Sanctuary, your settings, voice commands, metrics, Avatar Mode, Family Sanctuary, subscriptions, or anything else you need help with."
          : "Hey Coach! I'm Little Nate — your platform guide. Ask me about managing clients, scheduling sessions, the Dojo, Classroom, Zoom integration, Briefings, Financials, Night School, or anything else in your coach portal.",
    });
  }

  @override
  void dispose() {
    _questionCtrl.dispose();
    _scrollCtrl.dispose();
    _ws?.sink.close();
    super.dispose();
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _sendQuestion() {
    final text = _questionCtrl.text.trim();
    if (text.isEmpty) return;

    setState(() {
      _conversation.add({'role': 'user', 'text': text});
      _isLoading = true;
      _streamingResponse = '';
    });
    _questionCtrl.clear();
    _scrollToBottom();

    // Open a dedicated WS connection for help queries
    try {
      _ws?.sink.close();
    } catch (_) {}

    final wsUrl = AppConfig.wsUrl;
    _ws = WebSocketChannel.connect(Uri.parse(wsUrl));
    _ws!.stream.listen(
      (message) {
        final data = jsonDecode(message);
        final type = data['type'] ?? '';

        if (type == 'nate_help_response') {
          setState(() {
            _streamingResponse = data['text'] ?? '';
          });
          _scrollToBottom();
        } else if (type == 'nate_help_done') {
          setState(() {
            _isLoading = false;
            if (_streamingResponse.isNotEmpty) {
              _conversation.add({'role': 'nate', 'text': _streamingResponse});
            }
            _streamingResponse = '';
          });
          _scrollToBottom();
          try { _ws?.sink.close(); } catch (_) {}
        } else if (type == 'error') {
          setState(() {
            _isLoading = false;
            _conversation.add({'role': 'nate', 'text': 'Sorry, I had trouble answering that. Please try again.'});
            _streamingResponse = '';
          });
          _scrollToBottom();
        }
      },
      onError: (_) {
        setState(() {
          _isLoading = false;
          _conversation.add({'role': 'nate', 'text': 'Connection error. Please try again.'});
          _streamingResponse = '';
        });
      },
      onDone: () {
        if (_isLoading) {
          setState(() {
            _isLoading = false;
            if (_streamingResponse.isNotEmpty) {
              _conversation.add({'role': 'nate', 'text': _streamingResponse});
              _streamingResponse = '';
            }
          });
        }
      },
    );

    // Send the help query
    _ws!.sink.add(jsonEncode({
      'type': 'help_query',
      'text': text,
      'role': widget.role,
      'name': widget.profile['name'] ?? '',
    }));
  }

  // --- Static FAQ data ---
  List<Map<String, String>> get _faqs {
    if (widget.role == 'CLIENT') {
      return const [
        {
          'q': 'How do I start a conversation with Little Nate?',
          'a': 'From the main screen, simply type your message in the text box at the bottom and tap send. You can also tap the microphone icon to speak. Nate will respond with text (and voice if enabled).',
        },
        {
          'q': 'What voice commands can I use?',
          'a': '"send message" / "send it" — sends your draft\n"clear message" — clears the draft\n"delete last sentence" / "delete last word" — edits your draft\n"read it back" — reads your current draft aloud\n"replace [text] with [text]" — inline replacement',
        },
        {
          'q': 'What do the metrics (C_emo, GAP, Quantum) mean?',
          'a': 'C_emo is your Coherent Emotional Engagement score — how aligned your emotional state is. GAP measures growth potential. Quantum reflects the depth of emotional processing. Tap the metrics bar at the top for a full breakdown including mood history and session stats.',
        },
        {
          'q': 'How do I enable Avatar Mode?',
          'a': 'Avatar Mode is available for Sovereign Circle members. On the main screen, look for the Avatar toggle in the top-right area. When enabled, a 3D avatar of Nate will respond with facial expressions that match the conversation.',
        },
        {
          'q': 'What is Family Sanctuary and how do I use it?',
          'a': 'Family Sanctuary lets Sovereign Circle members invite family members to shared sessions. Tap the Family Sanctuary button on your main screen. The Head of Household can invite a spouse (free), first dependent (free), and additional members (\$75/month each).',
        },
        {
          'q': 'What are the subscription tiers?',
          'a': 'Threshold (Trial) — Basic access to Little Nate\nInner Chamber (\$49/month) — Full AI companion with voice and text\nSovereign Circle (\$149/month) — Everything plus Avatar Mode, Family Sanctuary, and priority support',
        },
        {
          'q': 'How do I invite a friend?',
          'a': 'Go to Settings > Share > "Invite a Friend." This opens your phone\'s native share sheet with a pre-written message introducing Little Nate and a download link.',
        },
        {
          'q': 'How do I delete my account?',
          'a': 'Go to Settings > Account > "Delete My Account." Type DELETE to confirm. Your data is held for 30 days — if you sign back in during that window, your account is restored. After 30 days, all data is permanently purged.',
        },
        {
          'q': 'How do I update my profile or preferences?',
          'a': 'Go to Settings > Profile and tap "Edit" to change your email, phone, emergency contact, or timezone. Under Preferences, toggle notifications and voice mode. All changes save instantly.',
        },
        {
          'q': 'What happens during a crisis alert?',
          'a': 'If Nate detects signs of crisis, the system activates crisis protocol. You will see emergency contact information: call 988 (Suicide & Crisis Lifeline) or 911. Nate is NOT an emergency service — always reach out to professional help in a crisis.',
        },
        {
          'q': 'What is Tri-Corder mode?',
          'a': 'Tri-Corder is a deep diagnostic scan of your emotional patterns — like a medical scanner for your inner world. It examines your coherence data, mood history, and behavioral markers to give you a detailed picture of where you are right now. Tap the mode picker icon (brain icon) in the chat bar to activate it.',
        },
        {
          'q': 'What is Archivist mode?',
          'a': 'Archivist mode weaves your therapeutic journey into a narrative, spotting themes, patterns, and turning points you might miss on your own. It draws from your full conversation history with Nate to tell the story of your growth. Activate it from the mode picker in the chat bar.',
        },
        {
          'q': 'What is Guardian mode?',
          'a': 'Guardian mode activates protective monitoring. Nate watches for risk indicators, emotional distress patterns, and safety concerns. It is designed to keep you safe by gently flagging when something feels off. You can turn it on from the mode picker icon in the chat bar.',
        },
        {
          'q': 'What is Supervisor mode?',
          'a': 'Supervisor mode reviews your progress through a clinical lens — like having a wise clinical supervisor looking over your journey. It evaluates therapeutic progress, identifies areas of growth, and suggests next steps. Activate it from the mode picker in the chat bar.',
        },
        {
          'q': 'How do I switch between Little Nate modes?',
          'a': 'Tap the brain/mode icon in the chat input bar (next to the microphone and send buttons). A picker will appear showing all available modes: Tri-Corder, Archivist, Guardian, Supervisor, and Editor. Tap one to activate it. Nate will let you know when the mode is active and when it deactivates.',
        },
        {
          'q': 'How do I read my stats and coherence reports?',
          'a': 'Your metrics bar at the top of the chat screen shows live C_emo (emotional coherence), GAP (growth potential), and Quantum (processing depth). For detailed trends, go to Settings > Your Tools > Coherence Reports. For a quick weekly summary, tap Settings > Your Tools > Weekly Brief.',
        },
        {
          'q': 'What is the Sovereign Vault?',
          'a': 'The Vault is your secure storage space (Inner Chamber and above). You can upload documents, images, and files that Nate can reference in conversations. Tap the paperclip icon in the chat bar to upload files, browse your vault, or import conversations from other AI platforms using Transfer Crystal.',
        },
        {
          'q': 'What is Night School?',
          'a': 'Night School is how Little Nate learns and grows. Your anonymized interactions help train Nate to be a better companion for everyone. No personal information is used — only patterns and insights. You can learn more in Settings > About.',
        },
      ];
    } else {
      return const [
        {
          'q': 'How do I view and manage my clients?',
          'a': 'Go to the Clients tab. You\'ll see all assigned clients with filters for ALL, FAMILY, COACH_ONLY, and COMPANY. Tap a client to view their details, get a pre-session brief, or start a live session.',
        },
        {
          'q': 'How do I schedule a session?',
          'a': 'Go to the Schedule tab and tap the "+" button. Select a client, set the date/time, choose the duration and session type (COACH, FAMILY, or GROUP). You can add notes and optionally disable recording.',
        },
        {
          'q': 'How do I start a live session with a client?',
          'a': 'From the Schedule tab, tap "Start" on a scheduled session. This opens the live session overlay with real-time notes, AI observations, and an assist mode toggle. If Zoom is configured, you can join as host directly.',
        },
        {
          'q': 'What is The Dojo and how does it work?',
          'a': 'The Dojo is an adversarial testing environment. Select a persona (like HOSTILE) and test your coaching responses against challenging prompts. It helps you sharpen your skills. You can share learnings with Night School.',
        },
        {
          'q': 'How do I upload and analyze session videos in the Classroom?',
          'a': 'Go to the Classroom tab and tap the upload button. Select a video recording and choose a learning focus. The system will transcribe and analyze the session, providing reflection prompts and progress tracking.',
        },
        {
          'q': 'How does Zoom integration work?',
          'a': 'Set your Zoom link in Settings > Profile > Zoom Link. When scheduling, sessions can auto-create Zoom meetings. During live sessions, you can join as host, check recording status, and archive transcripts.',
        },
        {
          'q': 'How do I manage my briefings and notes?',
          'a': 'The Briefings tab organizes notes by client and family folders. Tap a folder to view session notes. You can add new notes and share them with Nate for Night School learning.',
        },
        {
          'q': 'How do financials and fees work?',
          'a': 'Go to the Financials tab or Settings > Practice & Fees. Set your hourly coaching fee and choose whether you or the platform handles billing. The platform fee is 30% (minimum \$30).',
        },
        {
          'q': 'What is Night School?',
          'a': 'Night School is the AI training system. When you share session notes, Dojo learnings, or classroom analysis, the knowledge goes into Night School. This helps Nate become more insightful over time.',
        },
        {
          'q': 'How do I delete my account?',
          'a': 'Go to Settings > Account > "Delete My Account." You must first transfer or unassign all active clients. Type DELETE to confirm. Data is held for 30 days before permanent purge.',
        },
      ];
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        title: Text(
          widget.role == 'CLIENT' ? 'Help & FAQ' : 'Coach Help & FAQ',
          style: const TextStyle(fontFamily: 'Courier', color: _Design.gold, letterSpacing: 2),
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              controller: _scrollCtrl,
              padding: const EdgeInsets.all(16),
              children: [
                // === Ask Little Nate Section ===
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: _Design.bgCard,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: _Design.gold.withOpacity(0.4)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            width: 32,
                            height: 32,
                            decoration: BoxDecoration(
                              color: _Design.gold.withOpacity(0.2),
                              borderRadius: BorderRadius.circular(16),
                            ),
                            child: const Center(
                              child: Text('N', style: TextStyle(color: _Design.gold, fontWeight: FontWeight.bold, fontSize: 16)),
                            ),
                          ),
                          const SizedBox(width: 10),
                          const Text(
                            'ASK LITTLE NATE',
                            style: TextStyle(color: _Design.gold, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 2),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),

                      // Conversation history
                      ..._conversation.map((msg) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (msg['role'] == 'nate')
                              Container(
                                width: 24,
                                height: 24,
                                margin: const EdgeInsets.only(right: 8, top: 2),
                                decoration: BoxDecoration(
                                  color: _Design.gold.withOpacity(0.15),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: const Center(
                                  child: Text('N', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                                ),
                              ),
                            if (msg['role'] == 'user')
                              Container(
                                width: 24,
                                height: 24,
                                margin: const EdgeInsets.only(right: 8, top: 2),
                                decoration: BoxDecoration(
                                  color: _Design.cyan.withOpacity(0.15),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: const Center(
                                  child: Icon(Icons.person, color: _Design.cyan, size: 14),
                                ),
                              ),
                            Expanded(
                              child: Container(
                                padding: const EdgeInsets.all(10),
                                decoration: BoxDecoration(
                                  color: msg['role'] == 'nate'
                                      ? _Design.bgElevated
                                      : _Design.cyan.withOpacity(0.08),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  msg['text'] ?? '',
                                  style: TextStyle(
                                    color: msg['role'] == 'nate' ? _Design.textPrimary : _Design.cyan,
                                    fontSize: 12,
                                    height: 1.5,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      )),

                      // Streaming response
                      if (_streamingResponse.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Container(
                                width: 24,
                                height: 24,
                                margin: const EdgeInsets.only(right: 8, top: 2),
                                decoration: BoxDecoration(
                                  color: _Design.gold.withOpacity(0.15),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: const Center(
                                  child: Text('N', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                                ),
                              ),
                              Expanded(
                                child: Container(
                                  padding: const EdgeInsets.all(10),
                                  decoration: BoxDecoration(
                                    color: _Design.bgElevated,
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Text(
                                    _streamingResponse,
                                    style: const TextStyle(color: _Design.textPrimary, fontSize: 12, height: 1.5),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),

                      // Loading indicator
                      if (_isLoading && _streamingResponse.isEmpty)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Row(
                            children: [
                              Container(
                                width: 24,
                                height: 24,
                                margin: const EdgeInsets.only(right: 8),
                                decoration: BoxDecoration(
                                  color: _Design.gold.withOpacity(0.15),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: const Center(
                                  child: Text('N', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                                ),
                              ),
                              const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(_Design.gold),
                                ),
                              ),
                              const SizedBox(width: 8),
                              const Text('Thinking...', style: TextStyle(color: _Design.textSecondary, fontSize: 11)),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),

                // === FAQ Section ===
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Row(
                    children: [
                      const Icon(Icons.quiz_outlined, color: _Design.gold, size: 16),
                      const SizedBox(width: 8),
                      Text(
                        widget.role == 'CLIENT' ? 'FREQUENTLY ASKED QUESTIONS' : 'COACH FAQ',
                        style: const TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 2),
                      ),
                    ],
                  ),
                ),
                Container(
                  decoration: BoxDecoration(
                    color: _Design.bgCard,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: _Design.border),
                  ),
                  child: Column(
                    children: _faqs.asMap().entries.map((entry) {
                      final i = entry.key;
                      final faq = entry.value;
                      return Column(
                        children: [
                          Theme(
                            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                            child: ExpansionTile(
                              tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
                              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                              iconColor: _Design.gold,
                              collapsedIconColor: _Design.textSecondary,
                              title: Text(
                                faq['q']!,
                                style: const TextStyle(color: _Design.textPrimary, fontSize: 13, fontWeight: FontWeight.w500),
                              ),
                              children: [
                                Text(
                                  faq['a']!,
                                  style: const TextStyle(color: _Design.textSecondary, fontSize: 12, height: 1.5),
                                ),
                              ],
                            ),
                          ),
                          if (i < _faqs.length - 1)
                            const Divider(color: _Design.border, height: 1, indent: 16, endIndent: 16),
                        ],
                      );
                    }).toList(),
                  ),
                ),
                const SizedBox(height: 40),
              ],
            ),
          ),

          // === Input Bar (pinned at bottom) ===
          Container(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            decoration: const BoxDecoration(
              color: _Design.bgCard,
              border: Border(top: BorderSide(color: _Design.border)),
            ),
            child: SafeArea(
              top: false,
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _questionCtrl,
                      style: const TextStyle(color: _Design.textPrimary, fontSize: 13),
                      maxLines: 2,
                      minLines: 1,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _sendQuestion(),
                      decoration: InputDecoration(
                        hintText: widget.role == 'CLIENT'
                            ? 'Ask Nate about any feature...'
                            : 'Ask Nate about coach tools...',
                        hintStyle: const TextStyle(color: _Design.textSecondary, fontSize: 13),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(20),
                          borderSide: BorderSide(color: _Design.gold.withOpacity(0.3)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(20),
                          borderSide: const BorderSide(color: _Design.gold),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  GestureDetector(
                    onTap: _isLoading ? null : _sendQuestion,
                    child: Container(
                      width: 40,
                      height: 40,
                      decoration: BoxDecoration(
                        color: _isLoading ? _Design.textSecondary.withOpacity(0.3) : _Design.gold,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Icon(
                        Icons.send,
                        color: _isLoading ? _Design.textSecondary : Colors.black,
                        size: 18,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// LEGAL AGREEMENT VIEWER (Shared by Client & Coach)
// =============================================================================
class _LegalAgreementScreen extends StatelessWidget {
  const _LegalAgreementScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        title: const Text('Legal Agreement', style: TextStyle(fontFamily: 'Courier', color: _Design.gold, letterSpacing: 2)),
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Center(
              child: Text(
                'SOVEREIGN SANCTUARY',
                style: TextStyle(color: _Design.gold, fontSize: 20, fontWeight: FontWeight.bold, letterSpacing: 3),
              ),
            ),
            const SizedBox(height: 4),
            const Center(
              child: Text(
                'Terms of Use, Privacy Policy, and Therapeutic Waiver',
                style: TextStyle(color: _Design.textSecondary, fontSize: 12),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 4),
            const Center(
              child: Text(
                'Consent Version: v13.0_2026',
                style: TextStyle(color: _Design.gold, fontSize: 10, fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(height: 24),

            // PART I
            _partHeader('PART I — TERMS OF USE'),
            _section('1. PRIVATE MEMBERSHIP ASSOCIATION (1st AMENDMENT)',
              'You acknowledge that Sovereign Sanctuary operates as a Private Membership Association under the protections of the First Amendment to the United States Constitution. All interactions within this platform — between you and Little Nate (the AI companion), between you and your assigned coach, and between family members in the Family Sanctuary — are private exercises of speech and association.'),
            _section('2. AI IDENTITY AND LICENSING DISCLOSURE (CA AB 489)',
              '"Little Nate" is an artificial intelligence system. Little Nate is NOT a human being, NOT a licensed therapist, NOT a licensed psychologist, and NOT a licensed medical professional of any kind. Neither the AI nor the Sovereign Sanctuary application holds a medical license, therapy license, or counseling credential in any jurisdiction. Little Nate is designed to provide emotional support, self-awareness tools, and coaching companionship — NOT medical advice, clinical diagnoses, treatment plans, or prescriptions.'),
            _section('3. AUTOMATED PROFILING CONSENT',
              'This platform utilizes "Automated Profiling" as defined under various state data protection laws. The core function of Sovereign Sanctuary is the continuous analysis of your emotional state through text analysis, voice biometrics, and (where applicable) facial geometry. By proceeding, you explicitly and voluntarily WAIVE any state-level rights to "opt-out" of automated profiling.'),
            _section('4. AGE VERIFICATION AND FAMILY ACCOUNTS (CA SB 243)',
              'You affirm that you are at least eighteen (18) years of age. Minors (persons under 18) are strictly prohibited from creating primary accounts. Parents or legal guardians may create a family account and add minors as dependents under the Family Sanctuary feature.'),
            _section('5. TEXAS TRAIGA DISCLOSURE',
              'Pursuant to Texas law: This practitioner uses Generative Artificial Intelligence in the formulation of guidance plans, session summaries, coaching briefs, emotional coherence assessments, and all analytical outputs.'),
            _section('6. CRISIS PROTOCOL',
              'STOP. If you are in crisis, experiencing suicidal ideation, or in immediate danger:\n\n• Call 988 (Suicide & Crisis Lifeline) — available 24/7\n• Call 911 for immediate emergencies\n• Go to your nearest Emergency Room\n\nSovereign Sanctuary is NOT an emergency service.', highlight: true),
            _section('7. ZERO TOLERANCE POLICY',
              'Immediate and permanent account termination without refund for: Pornography, Solicitation, Illegal activity, Threats of violence, or Attempts to manipulate the AI system.'),
            _section('8. PLATFORM IMMUNITY',
              'Sovereign Sanctuary is a Technology Provider, NOT a clinic. Coaches are Independent Practitioners. For claims arising from live coaching sessions, you look solely to the individual Coach.'),
            _section('9. INTELLECTUAL PROPERTY AND PROPRIETARY TECHNOLOGY',
              'The platform incorporates proprietary algorithms subject to pending US provisional patent applications, including: the Nevedal Formula for Quantum Emotional Coherence, Voice Biometric Extraction, Predictability Model of Behavior, Family System Dynamics analysis, Night School AI training, and CEE Window detection. All algorithmic outputs are proprietary. You may not reproduce, reverse-engineer, or create derivative works from any algorithmic output.'),
            _section('10. ACCEPTABLE USE POLICY',
              'You agree to use Sovereign Sanctuary solely for its intended purpose: personal emotional growth, coaching support, and family wellness.'),
            _section('11. SERVICE AVAILABILITY',
              'Sovereign Sanctuary is provided on an "as-is" and "as-available" basis. We do not guarantee uptime or uninterrupted service.'),

            const SizedBox(height: 16),
            _partHeader('PART II — PRIVACY POLICY'),
            _section('12. DATA WE COLLECT',
              'Account information (name, email, phone, DOB), voice biometric data (pitch, energy, speech rate, pause ratio), facial geometry data (Sovereign Circle only, processed real-time, not stored as raw video), text and conversation data, emotional and analytical data (C_emo scores, CEE events, crisis assessments, PMB profiles), and technical/usage data.'),
            _section('13. HOW WE PROCESS YOUR DATA',
              'Data is processed via Azure OpenAI (Microsoft) under enterprise data protection agreements — your data is NOT used to train OpenAI\'s general models. ${isNativeIOS ? 'Payments processed securely.' : 'Payments via Stripe.'} All data encrypted in transit and at rest.'),
            _section('14. DATA RETENTION',
              'Active accounts: retained for duration of membership. Deleted accounts: held 30 days then permanently purged. Anonymized aggregate data may be retained indefinitely for research.'),
            _section('15. DATA SHARING',
              'Your data is NEVER sold. Shared only with: your assigned Coach (session summaries), Head of Household (aggregate family metrics, not individual content), law enforcement (only when legally compelled).'),
            _section('16. YOUR PRIVACY RIGHTS',
              'California (CCPA/CPRA): right to know, delete, opt out of sale. Illinois (BIPA): biometric consent provided herein. Texas (CUBI): biometric notification provided. Virginia, Colorado, Connecticut, Indiana, Kentucky, Rhode Island: access, correct, delete, port data. Right to Delete via Settings. Right to Data Export (transcripts; analytical overlays excluded as platform IP).'),
            _section('17. CHILDREN\'S PRIVACY (COPPA)',
              'We do not knowingly collect information from children under 13. Children 13-17 may only access via parent/guardian family account.'),

            const SizedBox(height: 16),
            _partHeader('PART III — THERAPEUTIC SETTING WAIVER'),
            _section('18. NATURE OF THE SERVICE',
              'The platform is NOT a licensed mental health provider. Little Nate is NOT a therapist. Coaches are independent practitioners. No doctor-patient or therapist-client privilege applies to AI interactions.'),
            _section('19. INFORMED CONSENT FOR EXPERIMENTAL METHODOLOGY',
              'The Nevedal Quantum Emotional Coherence framework is a research model and proprietary analytical methodology. It is NOT a clinically validated diagnostic tool. Terms like "quantum" and "coherence" are metaphorical frameworks for organizing biometric data. C_emo scores are algorithmic estimates, not clinical measurements.'),
            _section('20. ASSUMPTION OF EMOTIONAL RISK',
              'Emotional exploration carries inherent risk. Deep self-reflection, trauma processing, and confrontation of emotional patterns may cause temporary distress. You voluntarily assume this risk.'),
            _section('21. COACH RELATIONSHIP BOUNDARIES',
              'If your coach holds a professional license, their obligations are governed by their licensing board, not this platform. Mandatory reporting requirements apply to licensed coaches.'),

            const SizedBox(height: 16),
            _partHeader('PART IV — PATENT AND PROPRIETARY TECHNOLOGY NOTICE'),
            _section('22. PATENT PENDING TECHNOLOGY',
              'Technology covered by provisional patent applications includes: The Nevedal Formula (C_emo calculation), multi-modal biometric extraction, real-time emotional coherence scoring, CEE Window detection, crisis perception modeling, reactivity signature classification, family system dynamics, ventriloquism detection, Night School AI learning, and Judge Nate adversarial testing.'),
            _section('23. RESTRICTIONS',
              'Unauthorized use, reproduction, or reverse-engineering of patented technology may result in civil and criminal penalties.'),
            _section('24. RESEARCH PARTICIPATION',
              'You consent to the use of your de-identified, anonymized data in aggregate research, including academic publications and patent prosecution materials. Your identity will never be disclosed.'),

            const SizedBox(height: 16),
            _partHeader('PART V — WAIVERS AND DISPUTE RESOLUTION'),
            _section('25. HOLD HARMLESS AND LIMITATION OF LIABILITY',
              'You agree to hold Sovereign Sanctuary harmless from all claims arising from data breaches, coach interactions, AI outputs, emotional distress, technical failures, or inaccurate outputs. Liability capped at subscription fees paid in the prior 12 months.'),
            _section('26. INDEMNIFICATION',
              'You agree to indemnify Sovereign Sanctuary against third-party claims arising from your use of the platform.'),
            _section('27. BINDING ARBITRATION AND CLASS ACTION WAIVER',
              'All disputes resolved by binding individual arbitration (AAA, California). 30-day informal resolution period required first. You WAIVE your right to class action and jury trial.', highlight: true),
            _section('28-31. ADDITIONAL PROVISIONS',
              'Force Majeure: Not liable for causes beyond reasonable control. Severability: Invalid provisions enforced to maximum extent. Governing Law: State of California. Entire Agreement: This agreement constitutes the complete agreement.'),

            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: _Design.gold.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _Design.gold.withOpacity(0.3)),
              ),
              child: const Text(
                'Contact: support@sovereignsanctuary.net\nCrisis: Call 988 or 911 immediately',
                style: TextStyle(color: _Design.gold, fontSize: 11),
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }

  static Widget _partHeader(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(text, style: const TextStyle(color: _Design.gold, fontSize: 16, fontWeight: FontWeight.bold, letterSpacing: 1)),
    );
  }

  static Widget _section(String title, String body, {bool highlight = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: _Design.textPrimary, fontSize: 13, fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          Text(
            body,
            style: TextStyle(
              color: highlight ? Colors.redAccent : _Design.textSecondary,
              fontSize: 12,
              height: 1.5,
              fontWeight: highlight ? FontWeight.w500 : FontWeight.normal,
            ),
          ),
        ],
      ),
    );
  }
}


// =============================================================================
// WEEKLY COHERENCE BRIEF DIALOG
// =============================================================================

class _WeeklyBriefDialog extends StatefulWidget {
  final Map<String, dynamic> profile;
  const _WeeklyBriefDialog({required this.profile});

  @override
  State<_WeeklyBriefDialog> createState() => _WeeklyBriefDialogState();
}

class _WeeklyBriefDialogState extends State<_WeeklyBriefDialog> {
  bool _loading = true;
  String _briefText = '';
  String _goal = '';
  Map<String, dynamic> _moodSummary = {};
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchBrief();
  }

  Future<void> _fetchBrief() async {
    try {
      final userId = (widget.profile['hardware_id'] ?? widget.profile['id'] ?? '').toString();
      final baseUrl = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      final resp = await http.get(
        Uri.parse('$baseUrl/api/research/nevedal/reports/brief'),
        headers: {'X-User-Id': userId},
      ).timeout(const Duration(seconds: 35));

      if (resp.statusCode == 200) {
        final data = json.decode(resp.body);
        if (mounted) {
          setState(() {
            _briefText = data['brief'] ?? '';
            _goal = data['goal'] ?? '';
            _moodSummary = Map<String, dynamic>.from(data['mood_summary'] ?? {});
            _loading = false;
          });
        }
      } else {
        if (mounted) setState(() { _error = 'Could not load brief'; _loading = false; });
      }
    } catch (e) {
      if (mounted) setState(() { _error = 'Connection error'; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF0A0A0A),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 400, maxHeight: 600),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: _loading
            ? Column(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  SizedBox(height: 40),
                  CircularProgressIndicator(color: Color(0xFFC9A962)),
                  SizedBox(height: 16),
                  Text('Little Nate is preparing your brief...',
                    style: TextStyle(color: Color(0xFF888888), fontSize: 13)),
                  SizedBox(height: 40),
                ],
              )
            : _error != null
              ? Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.cloud_off, color: Color(0xFF888888), size: 40),
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Color(0xFF888888))),
                    const SizedBox(height: 16),
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('Close', style: TextStyle(color: Color(0xFFC9A962))),
                    ),
                  ],
                )
              : SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        children: const [
                          Icon(Icons.auto_awesome, color: Color(0xFFC9A962), size: 20),
                          SizedBox(width: 8),
                          Text('Weekly Brief',
                            style: TextStyle(color: Color(0xFFC9A962), fontSize: 18, fontWeight: FontWeight.bold)),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text('from Little Nate',
                        style: TextStyle(color: const Color(0xFF888888), fontSize: 12)),
                      const SizedBox(height: 16),
                      if (_moodSummary.isNotEmpty) ...[
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: const Color(0xFF111111),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceAround,
                            children: [
                              _metricChip('Sessions', '${_moodSummary['sessions'] ?? 0}'),
                              _metricChip('C_emo', '${(_moodSummary['avg_c_emo'] ?? 0).toStringAsFixed(2)}'),
                              _metricChip('CEE', '${_moodSummary['cee_windows'] ?? 0}'),
                              _metricChip('Trend', _trendIcon(_moodSummary['trend'] ?? 'stable')),
                            ],
                          ),
                        ),
                        const SizedBox(height: 16),
                      ],
                      Text(_briefText,
                        style: const TextStyle(color: Colors.white, fontSize: 14, height: 1.6)),
                      if (_goal.isNotEmpty) ...[
                        const SizedBox(height: 16),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: const Color(0xFFC9A962).withOpacity(0.1),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.3)),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(Icons.flag, color: Color(0xFFC9A962), size: 16),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(_goal,
                                  style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13, height: 1.4)),
                              ),
                            ],
                          ),
                        ),
                      ],
                      const SizedBox(height: 20),
                      Center(
                        child: TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('Close', style: TextStyle(color: Color(0xFFC9A962), fontSize: 14)),
                        ),
                      ),
                    ],
                  ),
                ),
        ),
      ),
    );
  }

  Widget _metricChip(String label, String value) {
    return Column(
      children: [
        Text(value, style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 2),
        Text(label, style: const TextStyle(color: Color(0xFF888888), fontSize: 10)),
      ],
    );
  }

  String _trendIcon(String trend) {
    switch (trend) {
      case 'improving': return '↑';
      case 'dipping': return '↓';
      default: return '→';
    }
  }
}
