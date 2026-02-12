// =============================================================================
// SETTINGS SCREENS — Client & Coach
// =============================================================================

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import '../main.dart' show LobbyScreen, defaultWsUrl;

// =============================================================================
// DESIGN TOKENS
// =============================================================================
class _Design {
  static const bgVoid = Color(0xFF050505);
  static const bgCard = Color(0xFF111111);
  static const bgElevated = Color(0xFF1A1A1A);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
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
    _voiceModeDefault = _profile['voice_mode_default'] ?? false;
  }

  @override
  void dispose() {
    _emailCtrl.dispose();
    _phoneCtrl.dispose();
    _emergencyCtrl.dispose();
    _timezoneCtrl.dispose();
    super.dispose();
  }

  bool get _isSovereignCircle {
    final plan = (_profile['subscription_plan'] ?? _profile['tier'] ?? '').toString().toUpperCase();
    return plan.contains('TOP') || plan.contains('SOVEREIGN') || plan.contains('FAMILY');
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

  // ---- Change Plan (Upgrade or Downgrade) ----
  void _showChangePlanSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _ChangePlanSheet(
        currentPlanKey: _currentPlanKey,
        currentPlanRank: _currentPlanRank,
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

            // 30-day billing policy box
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
                  const Text('30-Day Billing Policy', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 6),
                  if (isUpgrade) ...[
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
              _sendWs({
                'type': 'change_subscription',
                'plan': planKey,
              });
              setState(() {
                _profile['subscription_plan'] = planKey;
              });
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(isUpgrade
                      ? 'Upgraded to $newName!'
                      : 'Plan change scheduled — $currentName access continues this cycle'),
                  backgroundColor: const Color(0xFF1A1A1A),
                ),
              );
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
      const downloadLink = 'https://sovereignsanctuary.net/download';
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

  // ---- Family Invite (Sovereign Circle) ----
  void _showFamilyInviteDialog() {
    final nameCtrl = TextEditingController();
    final contactCtrl = TextEditingController();
    String role = 'SPOUSE';

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _Design.bgCard,
          title: const Text('Invite Family Member', style: TextStyle(color: _Design.gold, fontFamily: 'Courier')),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildDialogField('Name', nameCtrl),
                const SizedBox(height: 12),
                _buildDialogField('Phone or Email', contactCtrl),
                const SizedBox(height: 12),
                const Text('Role', style: TextStyle(color: _Design.textSecondary, fontSize: 12)),
                const SizedBox(height: 6),
                DropdownButton<String>(
                  value: role,
                  dropdownColor: _Design.bgElevated,
                  style: const TextStyle(color: _Design.textPrimary),
                  items: const [
                    DropdownMenuItem(value: 'SPOUSE', child: Text('Spouse (Free)')),
                    DropdownMenuItem(value: 'DEPENDENT', child: Text('Dependent (1st Free, then \$75/mo)')),
                    DropdownMenuItem(value: 'ADDITIONAL', child: Text('Additional Member (\$75/mo)')),
                  ],
                  onChanged: (v) => setDialogState(() => role = v!),
                ),
                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: _Design.bgVoid,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: _Design.border),
                  ),
                  child: const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Billing Info', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                      SizedBox(height: 4),
                      Text('• Spouse: Free (first one)', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                      Text('• First Dependent: Free', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                      Text('• Additional members: \$75/month', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                      Text('• All charges billed to Head of Household', style: TextStyle(color: _Design.textSecondary, fontSize: 10)),
                    ],
                  ),
                ),
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
              onPressed: () => _sendFamilyInvite(ctx, nameCtrl, contactCtrl, role),
              child: const Text('Send Invite', style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _sendFamilyInvite(BuildContext dialogCtx, TextEditingController nameCtrl,
      TextEditingController contactCtrl, String role) async {
    final name = nameCtrl.text.trim();
    final contact = contactCtrl.text.trim();
    if (name.isEmpty || contact.isEmpty) return;

    Navigator.pop(dialogCtx);

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('Generating invite...'),
      duration: Duration(seconds: 2),
    ));

    WebSocketChannel? inviteSocket;
    StreamSubscription? sub;
    final completer = Completer<Map<String, dynamic>?>();

    try {
      final wsUrl = defaultWsUrl;
      inviteSocket = WebSocketChannel.connect(Uri.parse(wsUrl));

      sub = inviteSocket.stream.listen((raw) {
        if (completer.isCompleted) return;
        try {
          final data = jsonDecode(raw) as Map<String, dynamic>;
          final type = (data['type'] ?? '').toString();
          if (type == 'family_invite_token_generated') {
            completer.complete(data);
          } else if (type == 'family_invite_error') {
            completer.completeError(data['message'] ?? 'Invite failed');
          } else if (type == 'connected') {
            inviteSocket?.sink.add(jsonEncode({
              'type': 'auth',
              'token': _profile['token'] ?? widget.profile['token'] ?? '',
              'hardware_id': _profile['hardware_id'] ?? widget.profile['hardware_id'] ?? '',
            }));
          } else if (type == 'auth_success' || type == 'login_success') {
            inviteSocket?.sink.add(jsonEncode({
              'type': 'generate_family_invite_token',
              'invitee_name': name,
              'invitee_contact': contact,
              'role': role,
            }));
          }
        } catch (_) {}
      }, onError: (e) {
        if (!completer.isCompleted) completer.completeError(e);
      }, onDone: () {
        if (!completer.isCompleted) completer.completeError('Connection closed');
      });

      // Auth is sent when we receive 'connected' from the stream listener

      final result = await completer.future.timeout(
        const Duration(seconds: 15),
        onTimeout: () => throw TimeoutException('Request timed out'),
      );

      try { await sub.cancel(); } catch (_) {}
      try { await inviteSocket.sink.close(); } catch (_) {}

      if (!mounted) return;
      final token = (result?['token'] ?? '').toString();
      final notifSent = result?['notification_sent'] == true;
      final notifMethod = (result?['notification_method'] ?? '').toString();
      final inviterName = _profile['name'] ?? 'Your family';
      final inviteUrl = 'https://app.sovereignsanctuary.net/family-invite?code=$token';
      final shareMsg =
          "$inviterName has invited you to join their Family Circle on Sovereign Sanctuary.\n\n"
          "Accept here: $inviteUrl\n\n"
          "Invite code: $token";
      await _safeShare(shareMsg, subject: 'Sovereign Sanctuary Family Invite');
      if (mounted) {
        final statusMsg = notifSent
            ? 'Invite sent via ${notifMethod == "sms" ? "text message" : "email"}! Code: $token'
            : 'Invite code generated: $token (message could not be delivered — share manually)';
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(statusMsg),
          backgroundColor: notifSent ? _Design.green : Colors.orange,
          duration: const Duration(seconds: 5),
        ));
      }
    } catch (e) {
      try { sub?.cancel(); } catch (_) {}
      try { inviteSocket?.sink.close(); } catch (_) {}
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not generate invite: ${e.toString().replaceAll('TimeoutException:', '').trim()}'),
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
                      'https://sovereignsanctuary.net/download',
                      style: TextStyle(color: _Design.cyan, fontSize: 12, fontFamily: 'Courier'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  InkWell(
                    onTap: () {
                      Clipboard.setData(const ClipboardData(text: 'https://sovereignsanctuary.net/download'));
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
              _actionRow(Icons.group_add, 'Invite Family Member', 'Add spouse or dependent to your plan', _showFamilyInviteDialog),
              _infoRow('Plan', 'Sovereign Circle — Head of Household'),
            ]),
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
          ]),
          const SizedBox(height: 20),

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
          ]),
          const SizedBox(height: 20),

          // --- Legal & Privacy ---
          _sectionHeader('LEGAL & PRIVACY', Icons.gavel),
          _settingsCard([
            _actionRow(Icons.description, 'Terms, Privacy & Waivers', 'Full legal agreement', _showLegalAgreement),
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

          // --- Account ---
          _sectionHeader('ACCOUNT', Icons.manage_accounts),
          _settingsCard([
            _actionRow(Icons.delete_forever, 'Delete My Account', '30-day recovery window', _requestAccountDeletion, danger: true),
            _actionRow(Icons.logout, 'Logout', null, () {
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
  final void Function(String planKey, bool isUpgrade) onSelect;

  const _ChangePlanSheet({
    required this.currentPlanKey,
    required this.currentPlanRank,
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

            // 30-day policy reminder
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
                      const Text('30-Day Billing Policy', style: TextStyle(color: _Design.gold, fontSize: 11, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Upgrades take effect immediately. Downgrades keep your current access through the end of your billing cycle. '
                    'You are always billed at the highest tier used during each 30-day period. '
                    'Your conversation history, metrics, and all data are never deleted when changing plans.',
                    style: TextStyle(color: _Design.textSecondary, fontSize: 11, height: 1.5),
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
                              ? OutlinedButton(
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

  const CoachSettingsScreen({
    super.key,
    required this.profile,
    this.socket,
    this.onLogout,
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
      final wsUrl = defaultWsUrl;
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
          ]),
          const SizedBox(height: 20),

          // --- Subscription ---
          _sectionHeader('SUBSCRIPTION', Icons.workspace_premium),
          _settingsCard([
            _infoRow('Tier', tier.toString().replaceAll('_', ' ')),
            _statusRow('Certification', certStatus, certStatus == 'APPROVED' ? _Design.green : _Design.gold),
          ]),
          const SizedBox(height: 20),

          // --- Legal & Privacy ---
          _sectionHeader('LEGAL & PRIVACY', Icons.gavel),
          _settingsCard([
            _actionRow(Icons.description, 'Terms, Privacy & Waivers', 'Full legal agreement', _showLegalAgreement),
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

    final wsUrl = defaultWsUrl;
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
              'Data is processed via Azure OpenAI (Microsoft) under enterprise data protection agreements — your data is NOT used to train OpenAI\'s general models. Payments via Stripe. All data encrypted in transit and at rest.'),
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
