// =============================================================================
// LITTLE NATE — Billing & Subscription Screens
// Phase 7: E-Commerce & Billing — Flutter Client UI
//
// Screens:
//   1. MembershipSelectionScreen — Tier cards, comparison, Stripe checkout
//   2. FamilyManagementScreen — Invite/remove family, billing summary
//   3. CoachingPackScreen — Purchase packs, view credits, book/cancel sessions
//   4. PaymentMethodsScreen — Manage cards, view invoices
//   5. TrialBannerWidget — Countdown banner for trial users
// =============================================================================

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../main.dart' show defaultApiBaseUrl;

/// Build standard auth headers for REST API calls.
/// Backend auth accepts X-User-Id as a fallback for service/internal calls.
Map<String, String> _authHeaders(String userId, {bool json = false}) {
  final h = <String, String>{'X-User-Id': userId};
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

// =============================================================================
// Design Tokens — matches project design system
// =============================================================================
class _D {
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
// 1. MEMBERSHIP SELECTION SCREEN
// =============================================================================

class MembershipSelectionScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final WebSocketChannel? socket;

  const MembershipSelectionScreen({
    super.key,
    required this.currentUserProfile,
    this.socket,
  });

  @override
  State<MembershipSelectionScreen> createState() =>
      _MembershipSelectionScreenState();
}

class _MembershipSelectionScreenState extends State<MembershipSelectionScreen> {
  bool _showComparison = false;
  bool _loading = false;
  String? _error;

  String get _currentPlan =>
      (widget.currentUserProfile['subscription_plan'] ?? 'TRIAL')
          .toString()
          .toUpperCase();

  int _planRank(String plan) {
    switch (plan) {
      case 'COACH_ONLY':
        return 0;
      case 'TRIAL':
      case 'THRESHOLD':
        return 1;
      case 'STANDARD':
      case 'INNER_CHAMBER':
        return 2;
      case 'TOP_TIER':
      case 'SOVEREIGN_CIRCLE':
        return 3;
      default:
        return 1;
    }
  }

  void _sendWs(Map<String, dynamic> msg) {
    try {
      widget.socket?.sink.add(jsonEncode(msg));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: const Text('Connection lost'),
          backgroundColor: _D.red,
        ));
      }
    }
  }

  Future<void> _selectPlan(String planKey) async {
    final currentRank = _planRank(_currentPlan);
    final newRank = _planRank(planKey);
    if (newRank == currentRank) return;

    final isUpgrade = newRank > currentRank;
    final names = {
      'COACH_ONLY': 'Coach Only',
      'TRIAL': 'Threshold',
      'STANDARD': 'Inner Chamber',
      'TOP_TIER': 'Sovereign Circle',
    };

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _D.bgCard,
        title: Text(
          isUpgrade
              ? 'Upgrade to ${names[planKey]}'
              : 'Downgrade to ${names[planKey]}',
          style: TextStyle(
            color: isUpgrade ? _D.gold : _D.cyan,
            fontFamily: 'Cormorant Garamond',
            fontSize: 20,
          ),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              isUpgrade
                  ? 'Your new plan takes effect immediately with full access to upgraded features.'
                  : 'You will retain current access through the end of your billing cycle.',
              style: const TextStyle(
                  color: _D.textSecondary, fontSize: 13, height: 1.5),
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: _D.green.withOpacity(0.08),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Row(children: [
                Icon(Icons.shield, color: _D.green, size: 16),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Your history and data are always preserved.',
                    style: TextStyle(color: _D.green, fontSize: 11),
                  ),
                ),
              ]),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel',
                style: TextStyle(color: _D.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: isUpgrade ? _D.gold : _D.cyan,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              isUpgrade ? 'Confirm Upgrade' : 'Confirm Downgrade',
              style:
                  const TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
            ),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    setState(() => _loading = true);

    // Request checkout URL via WebSocket
    _sendWs({
      'type': 'get_checkout_url',
      'plan': planKey,
      'success_url': 'https://app.sovereignsanctuary.net/billing/success',
      'cancel_url': 'https://app.sovereignsanctuary.net/billing/cancel',
    });

    // Also attempt REST upgrade/downgrade
    try {
      final endpoint = isUpgrade ? 'upgrade' : 'downgrade';
      final userId =
          widget.currentUserProfile['hardware_id'] ?? '';
      final resp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/subscription/$endpoint'),
        headers: _authHeaders(userId, json: true),
        body: jsonEncode({
          'user_id': userId,
          'new_plan': planKey,
        }),
      );
      if (resp.statusCode == 200) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(isUpgrade
                ? 'Upgraded to ${names[planKey]}!'
                : 'Plan change to ${names[planKey]} scheduled'),
            backgroundColor: _D.bgElevated,
          ));
          Navigator.pop(context, planKey);
        }
      } else {
        final body = jsonDecode(resp.body);
        setState(() {
          _error = body['detail'] ?? 'Plan change failed';
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = 'Network error: $e';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgCard,
        title: const Text(
          'CHOOSE YOUR PATH',
          style: TextStyle(
            color: _D.gold,
            fontSize: 16,
            fontWeight: FontWeight.bold,
            letterSpacing: 3,
            fontFamily: 'Cormorant Garamond',
          ),
        ),
        centerTitle: true,
        iconTheme: const IconThemeData(color: _D.textPrimary),
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: _D.gold))
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 40),
              children: [
                if (_error != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    margin: const EdgeInsets.only(bottom: 16),
                    decoration: BoxDecoration(
                      color: _D.red.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: _D.red.withOpacity(0.3)),
                    ),
                    child: Text(_error!,
                        style: const TextStyle(color: _D.red, fontSize: 12)),
                  ),
                ],
                // Toggle comparison
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    onPressed: () =>
                        setState(() => _showComparison = !_showComparison),
                    icon: Icon(
                      _showComparison ? Icons.view_agenda : Icons.compare,
                      color: _D.gold,
                      size: 16,
                    ),
                    label: Text(
                      _showComparison ? 'Card View' : 'Compare Plans',
                      style: const TextStyle(color: _D.gold, fontSize: 12),
                    ),
                  ),
                ),
                if (_showComparison)
                  _buildComparisonTable()
                else ...[
                  _buildTierCard(
                    name: 'Coach Only',
                    subtitle: 'No AI Access',
                    price: 'Free',
                    priceSub: '',
                    planKey: 'COACH_ONLY',
                    color: _D.textSecondary,
                    features: [
                      'Coach scheduling only',
                      'No Little Nate access',
                      'No AI tokens',
                    ],
                  ),
                  const SizedBox(height: 14),
                  _buildTierCard(
                    name: 'Threshold',
                    subtitle: 'Trial — 14 Days',
                    price: 'Free',
                    priceSub: '14 days',
                    planKey: 'TRIAL',
                    color: _D.textSecondary,
                    features: [
                      '10,000 AI tokens',
                      '30 minutes AI conversation',
                      'Basic text conversations',
                    ],
                  ),
                  const SizedBox(height: 14),
                  _buildTierCard(
                    name: 'Inner Chamber',
                    subtitle: 'Standard',
                    price: '\$49',
                    priceSub: '/month',
                    planKey: 'STANDARD',
                    color: _D.cyan,
                    features: [
                      '50,000 AI tokens/month',
                      '300 min voice + text',
                      'Voice biometrics & emotional tracking',
                      'Family Sanctuary access',
                      '1 GB Legacy Vault storage',
                      '4 coaching sessions/month',
                      'Session history & metrics',
                    ],
                  ),
                  const SizedBox(height: 14),
                  _buildTierCard(
                    name: 'Sovereign Circle',
                    subtitle: 'Top Tier',
                    price: '\$149',
                    priceSub: '/month',
                    planKey: 'TOP_TIER',
                    color: _D.gold,
                    recommended: true,
                    features: [
                      'Unlimited AI minutes',
                      '200,000 tokens/month',
                      'Everything in Inner Chamber',
                      'Me-2-Me identity system',
                      'Avatar Mode (3D companion)',
                      '50 GB Legacy Vault storage',
                      '8 coaching sessions/month',
                      'Priority support',
                    ],
                  ),
                ],
                const SizedBox(height: 24),
                // Yearly savings note
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: _D.gold.withOpacity(0.06),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: _D.gold.withOpacity(0.2)),
                  ),
                  child: const Row(children: [
                    Icon(Icons.savings, color: _D.gold, size: 18),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Save ~17% with annual billing — '
                        'Inner Chamber \$490/yr · Sovereign Circle \$1,490/yr',
                        style: TextStyle(
                            color: _D.goldBright, fontSize: 11, height: 1.4),
                      ),
                    ),
                  ]),
                ),
              ],
            ),
    );
  }

  Widget _buildTierCard({
    required String name,
    required String subtitle,
    required String price,
    required String priceSub,
    required String planKey,
    required Color color,
    required List<String> features,
    bool recommended = false,
  }) {
    final isCurrent = _planRank(_currentPlan) == _planRank(planKey);
    final isUpgrade = _planRank(planKey) > _planRank(_currentPlan);
    final isDowngrade = _planRank(planKey) < _planRank(_currentPlan);

    return Container(
      decoration: BoxDecoration(
        color: isCurrent ? color.withOpacity(0.08) : _D.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: isCurrent
              ? color
              : (recommended ? _D.gold.withOpacity(0.4) : _D.border),
          width: isCurrent || recommended ? 1.5 : 1,
        ),
      ),
      child: Column(children: [
        if (recommended && !isCurrent)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(
              color: _D.gold.withOpacity(0.15),
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(12)),
            ),
            child: const Text(
              'RECOMMENDED',
              style: TextStyle(
                  color: _D.gold,
                  fontSize: 10,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 2),
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
                          Text(name,
                              style: TextStyle(
                                  color: color,
                                  fontSize: 18,
                                  fontWeight: FontWeight.bold,
                                  fontFamily: 'Cormorant Garamond')),
                          Text(subtitle,
                              style: const TextStyle(
                                  color: _D.textSecondary, fontSize: 11)),
                        ]),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Text(price,
                            style: const TextStyle(
                                color: _D.textPrimary,
                                fontSize: 26,
                                fontWeight: FontWeight.bold)),
                        Text(priceSub,
                            style: const TextStyle(
                                color: _D.textSecondary, fontSize: 12)),
                      ],
                    ),
                  ]),
              const SizedBox(height: 14),
              ...features.map((f) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(children: [
                      Icon(Icons.check, color: color, size: 14),
                      const SizedBox(width: 8),
                      Expanded(
                          child: Text(f,
                              style: const TextStyle(
                                  color: _D.textPrimary, fontSize: 12))),
                    ]),
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
                          style: TextStyle(
                              color: color,
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 1),
                          textAlign: TextAlign.center,
                        ),
                      )
                    : isUpgrade
                        ? ElevatedButton(
                            style: ElevatedButton.styleFrom(
                              backgroundColor: color,
                              padding:
                                  const EdgeInsets.symmetric(vertical: 12),
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(8)),
                            ),
                            onPressed: () => _selectPlan(planKey),
                            child: Text(
                              'Upgrade to $name',
                              style: const TextStyle(
                                  color: Colors.black,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13),
                            ),
                          )
                        : isDowngrade
                            ? OutlinedButton(
                                style: OutlinedButton.styleFrom(
                                  side:
                                      BorderSide(color: color.withOpacity(0.5)),
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 12),
                                  shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(8)),
                                ),
                                onPressed: () => _selectPlan(planKey),
                                child: Text(
                                  'Downgrade to $name',
                                  style:
                                      TextStyle(color: color, fontSize: 13),
                                ),
                              )
                            : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      ]),
    );
  }

  Widget _buildComparisonTable() {
    const features = [
      'AI Tokens/mo',
      'AI Minutes',
      'Voice + Text',
      'Voice Biometrics',
      'Family Sanctuary',
      'Me-2-Me',
      'Legacy Vault',
      'Coaching Sessions',
      'Avatar Mode',
      'Priority Support',
    ];

    const tiers = ['TRIAL', 'STANDARD', 'TOP_TIER'];
    const tierNames = ['Threshold', 'Inner Chamber', 'Sovereign Circle'];
    const tierColors = [_D.textSecondary, _D.cyan, _D.gold];

    Map<String, List<String>> featureValues = {
      'AI Tokens/mo': ['10K', '50K', '200K'],
      'AI Minutes': ['30', '300', '∞'],
      'Voice + Text': ['Text only', '✓', '✓'],
      'Voice Biometrics': ['✗', '✓', '✓'],
      'Family Sanctuary': ['✗', '✓', '✓'],
      'Me-2-Me': ['✗', '✗', '✓'],
      'Legacy Vault': ['✗', '1 GB', '50 GB'],
      'Coaching Sessions': ['0', '4/mo', '8/mo'],
      'Avatar Mode': ['✗', '✗', '✓'],
      'Priority Support': ['✗', '✗', '✓'],
    };

    return Container(
      margin: const EdgeInsets.only(top: 8),
      decoration: BoxDecoration(
        color: _D.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _D.border),
      ),
      child: Column(children: [
        // Header row
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            const SizedBox(width: 100),
            ...List.generate(
                3,
                (i) => Expanded(
                      child: Text(
                        tierNames[i],
                        style: TextStyle(
                            color: tierColors[i],
                            fontSize: 11,
                            fontWeight: FontWeight.bold),
                        textAlign: TextAlign.center,
                      ),
                    )),
          ]),
        ),
        const Divider(color: _D.border, height: 1),
        // Feature rows
        ...features.map((f) {
          final vals = featureValues[f]!;
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: _D.border, width: 0.5)),
            ),
            child: Row(children: [
              SizedBox(
                  width: 100,
                  child: Text(f,
                      style: const TextStyle(
                          color: _D.textSecondary, fontSize: 11))),
              ...List.generate(
                  3,
                  (i) => Expanded(
                        child: Text(
                          vals[i],
                          style: TextStyle(
                            color: vals[i] == '✗'
                                ? _D.textSecondary.withOpacity(0.4)
                                : _D.textPrimary,
                            fontSize: 11,
                            fontWeight: FontWeight.w500,
                          ),
                          textAlign: TextAlign.center,
                        ),
                      )),
            ]),
          );
        }),
        // Price row
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: _D.bgElevated,
            borderRadius:
                const BorderRadius.vertical(bottom: Radius.circular(12)),
          ),
          child: Row(children: [
            const SizedBox(
                width: 100,
                child: Text('Price',
                    style: TextStyle(
                        color: _D.gold,
                        fontSize: 12,
                        fontWeight: FontWeight.bold))),
            ...['Free', '\$49/mo', '\$149/mo'].map((p) => Expanded(
                  child: Text(p,
                      style: const TextStyle(
                          color: _D.textPrimary,
                          fontSize: 12,
                          fontWeight: FontWeight.bold),
                      textAlign: TextAlign.center),
                )),
          ]),
        ),
      ]),
    );
  }
}

// =============================================================================
// 2. FAMILY MANAGEMENT SCREEN
// =============================================================================

class FamilyManagementScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final WebSocketChannel? socket;

  const FamilyManagementScreen({
    super.key,
    required this.currentUserProfile,
    this.socket,
  });

  @override
  State<FamilyManagementScreen> createState() => _FamilyManagementScreenState();
}

class _FamilyManagementScreenState extends State<FamilyManagementScreen> {
  List<Map<String, dynamic>> _members = [];
  bool _loading = true;
  String? _error;
  final _inviteContactCtrl = TextEditingController();
  final _inviteNameCtrl = TextEditingController();
  String _inviteRelationship = 'SPOUSE';
  String _inviteMethod = 'email';

  String get _familyId =>
      widget.currentUserProfile['family_id']?.toString() ?? '';
  String get _userId =>
      widget.currentUserProfile['hardware_id']?.toString() ?? '';
  String get _userPlan =>
      (widget.currentUserProfile['subscription_plan'] ?? '')
          .toString()
          .toUpperCase();

  @override
  void initState() {
    super.initState();
    _loadMembers();
  }

  @override
  void dispose() {
    _inviteContactCtrl.dispose();
    _inviteNameCtrl.dispose();
    super.dispose();
  }

  void _sendWs(Map<String, dynamic> msg) {
    try {
      widget.socket?.sink.add(jsonEncode(msg));
    } catch (_) {}
  }

  Future<void> _loadMembers() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    // Request family members via WebSocket
    _sendWs({'type': 'sanctuary_get_members', 'family_id': _familyId});

    // Also try REST fallback
    try {
      final resp = await http.get(
        Uri.parse(
            '$defaultApiBaseUrl/api/billing/family/members?family_id=$_familyId'),
        headers: _authHeaders(_userId),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (mounted) {
          setState(() {
            _members = List<Map<String, dynamic>>.from(data['members'] ?? []);
            _loading = false;
          });
        }
        return;
      }
    } catch (_) {}

    // If REST fails, use profile data
    if (mounted) {
      final familyMembers =
          widget.currentUserProfile['family_members'] as List? ?? [];
      setState(() {
        _members = familyMembers.cast<Map<String, dynamic>>();
        _loading = false;
      });
    }
  }

  void _showInviteDialog() {
    _inviteContactCtrl.clear();
    _inviteNameCtrl.clear();
    _inviteRelationship = 'SPOUSE';
    _inviteMethod = 'email';

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _D.bgCard,
          title: const Text('Invite Family Member',
              style: TextStyle(color: _D.gold, fontFamily: 'Cormorant Garamond')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _inviteNameCtrl,
                style: const TextStyle(color: _D.textPrimary),
                decoration: InputDecoration(
                  labelText: 'Name',
                  labelStyle: const TextStyle(color: _D.textSecondary),
                  enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: _D.border),
                  ),
                  focusedBorder: const OutlineInputBorder(
                    borderSide: BorderSide(color: _D.gold),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setDialogState(() {
                        _inviteMethod = 'email';
                        _inviteContactCtrl.clear();
                      }),
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        decoration: BoxDecoration(
                          color: _inviteMethod == 'email'
                              ? _D.gold.withOpacity(0.2)
                              : _D.bgElevated,
                          borderRadius: const BorderRadius.horizontal(left: Radius.circular(8)),
                          border: Border.all(
                            color: _inviteMethod == 'email' ? _D.gold : _D.border,
                          ),
                        ),
                        child: Center(
                          child: Text('Email',
                              style: TextStyle(
                                color: _inviteMethod == 'email' ? _D.gold : _D.textSecondary,
                                fontWeight: FontWeight.w600, fontSize: 13,
                              )),
                        ),
                      ),
                    ),
                  ),
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setDialogState(() {
                        _inviteMethod = 'sms';
                        _inviteContactCtrl.clear();
                      }),
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        decoration: BoxDecoration(
                          color: _inviteMethod == 'sms'
                              ? _D.gold.withOpacity(0.2)
                              : _D.bgElevated,
                          borderRadius: const BorderRadius.horizontal(right: Radius.circular(8)),
                          border: Border.all(
                            color: _inviteMethod == 'sms' ? _D.gold : _D.border,
                          ),
                        ),
                        child: Center(
                          child: Text('SMS',
                              style: TextStyle(
                                color: _inviteMethod == 'sms' ? _D.gold : _D.textSecondary,
                                fontWeight: FontWeight.w600, fontSize: 13,
                              )),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _inviteContactCtrl,
                style: const TextStyle(color: _D.textPrimary),
                keyboardType: _inviteMethod == 'email'
                    ? TextInputType.emailAddress
                    : TextInputType.phone,
                decoration: InputDecoration(
                  labelText: _inviteMethod == 'email' ? 'Email Address' : 'Phone Number',
                  hintText: _inviteMethod == 'email' ? 'name@example.com' : '+1 (555) 123-4567',
                  hintStyle: TextStyle(color: _D.textSecondary.withOpacity(0.4)),
                  labelStyle: const TextStyle(color: _D.textSecondary),
                  enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: _D.border),
                  ),
                  focusedBorder: const OutlineInputBorder(
                    borderSide: BorderSide(color: _D.gold),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: _inviteRelationship,
                dropdownColor: _D.bgCard,
                style: const TextStyle(color: _D.textPrimary),
                decoration: InputDecoration(
                  labelText: 'Relationship',
                  labelStyle: const TextStyle(color: _D.textSecondary),
                  enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: _D.border),
                  ),
                ),
                items: const [
                  DropdownMenuItem(value: 'SPOUSE', child: Text('Spouse/Partner')),
                  DropdownMenuItem(value: 'DEPENDENT', child: Text('Dependent')),
                  DropdownMenuItem(value: 'CHILD', child: Text('Child')),
                  DropdownMenuItem(value: 'PARENT', child: Text('Parent')),
                ],
                onChanged: (v) =>
                    setDialogState(() => _inviteRelationship = v ?? 'SPOUSE'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel',
                  style: TextStyle(color: _D.textSecondary)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
              onPressed: () {
                final name = _inviteNameCtrl.text.trim();
                final contact = _inviteContactCtrl.text.trim();
                if (name.isEmpty || contact.isEmpty) return;

                final payload = <String, dynamic>{
                  'type': 'family_invite',
                  'family_id': _familyId,
                  'name': name,
                  'relationship': _inviteRelationship,
                };
                if (_inviteMethod == 'email') {
                  payload['email'] = contact;
                } else {
                  payload['phone'] = contact;
                }
                _sendWs(payload);

                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text('Invitation sent via ${_inviteMethod == 'email' ? 'email' : 'SMS'}'),
                  backgroundColor: _D.bgElevated,
                ));
                Future.delayed(
                    const Duration(seconds: 2), () => _loadMembers());
              },
              child: const Text('Send Invitation',
                  style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  void _confirmRemove(Map<String, dynamic> member) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _D.bgCard,
        title: const Text('Remove Family Member',
            style: TextStyle(color: _D.red)),
        content: Text(
          'Remove ${member['name'] ?? 'this member'} from your Family Sanctuary? '
          'They will lose access to shared features.',
          style: const TextStyle(color: _D.textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel',
                style: TextStyle(color: _D.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _D.red),
            onPressed: () {
              Navigator.pop(ctx);
              _sendWs({
                'type': 'sanctuary_remove_member',
                'family_id': _familyId,
                'member_id': member['hardware_id'] ?? member['id'] ?? '',
              });
              setState(() {
                _members.removeWhere((m) =>
                    (m['hardware_id'] ?? m['id']) ==
                    (member['hardware_id'] ?? member['id']));
              });
            },
            child: const Text('Remove',
                style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isPlanEligible = _userPlan == 'STANDARD' ||
        _userPlan == 'INNER_CHAMBER' ||
        _userPlan == 'TOP_TIER' ||
        _userPlan == 'SOVEREIGN_CIRCLE';

    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgCard,
        title: const Text('FAMILY SANCTUARY',
            style: TextStyle(
                color: _D.gold,
                fontSize: 16,
                letterSpacing: 3,
                fontFamily: 'Cormorant Garamond')),
        centerTitle: true,
        iconTheme: const IconThemeData(color: _D.textPrimary),
      ),
      body: !isPlanEligible
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.lock, color: _D.gold.withOpacity(0.5), size: 48),
                    const SizedBox(height: 16),
                    const Text(
                      'Family Sanctuary requires\nInner Chamber or Sovereign Circle',
                      style: TextStyle(
                          color: _D.textSecondary,
                          fontSize: 14,
                          height: 1.5),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 20),
                    ElevatedButton(
                      style:
                          ElevatedButton.styleFrom(backgroundColor: _D.gold),
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => MembershipSelectionScreen(
                            currentUserProfile: widget.currentUserProfile,
                            socket: widget.socket,
                          ),
                        ),
                      ),
                      child: const Text('View Plans',
                          style: TextStyle(color: Colors.black)),
                    ),
                  ],
                ),
              ),
            )
          : _loading
              ? const Center(
                  child: CircularProgressIndicator(color: _D.gold))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    // Family billing summary
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: _D.bgCard,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: _D.border),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Billing Summary',
                              style: TextStyle(
                                  color: _D.gold,
                                  fontSize: 14,
                                  fontWeight: FontWeight.bold)),
                          const SizedBox(height: 10),
                          _summaryRow('Base Subscription',
                              _userPlan == 'TOP_TIER' || _userPlan == 'SOVEREIGN_CIRCLE' ? '\$149/mo' : '\$49/mo'),
                          _summaryRow('Family Members',
                              '${_members.where((m) => (m['family_role'] ?? m['role'] ?? '').toString().toUpperCase() != 'HEAD').length} member(s)'),
                          _summaryRow('Spouse/Partner', 'Free'),
                          _summaryRow('First child', 'Free'),
                          _summaryRow('Additional members', 'from \$75/mo'),
                          const Divider(color: _D.border),
                          Builder(builder: (_) {
                            final baseCents = (_userPlan == 'TOP_TIER' || _userPlan == 'SOVEREIGN_CIRCLE') ? 14900 : 4900;
                            int addonCents = 0;
                            for (final m in _members) {
                              final r = (m['family_role'] ?? m['role'] ?? '').toString().toUpperCase();
                              if (r == 'HEAD') continue;
                              addonCents += (m['family_billing_price_cents'] as int?) ?? 0;
                            }
                            final totalCents = baseCents + addonCents;
                            return _summaryRow('Total', '\$${(totalCents / 100).toStringAsFixed(0)}/mo', bold: true);
                          }),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Members list
                    if (_members.isEmpty)
                      Container(
                        padding: const EdgeInsets.all(24),
                        decoration: BoxDecoration(
                          color: _D.bgCard,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: _D.border),
                        ),
                        child: const Column(children: [
                          Icon(Icons.people_outline,
                              color: _D.textSecondary, size: 40),
                          SizedBox(height: 12),
                          Text('No family members yet',
                              style: TextStyle(
                                  color: _D.textSecondary, fontSize: 13)),
                          SizedBox(height: 4),
                          Text(
                              'Invite your spouse, partner, or dependents to share your sanctuary.',
                              style: TextStyle(
                                  color: _D.textSecondary, fontSize: 11),
                              textAlign: TextAlign.center),
                        ]),
                      )
                    else
                      ..._members.map((m) => Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: _D.bgCard,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: _D.border),
                            ),
                            child: Row(children: [
                              CircleAvatar(
                                backgroundColor:
                                    _D.gold.withOpacity(0.15),
                                radius: 20,
                                child: Text(
                                  (m['name'] ?? '?')[0].toUpperCase(),
                                  style: const TextStyle(
                                      color: _D.gold, fontSize: 16),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Text(m['name'] ?? 'Unknown',
                                        style: const TextStyle(
                                            color: _D.textPrimary,
                                            fontSize: 14,
                                            fontWeight: FontWeight.w500)),
                                    Text(
                                      (m['family_role'] ?? m['role'] ?? m['relationship'] ?? 'MEMBER')
                                          .toString()
                                          .toUpperCase(),
                                      style: const TextStyle(
                                          color: _D.textSecondary,
                                          fontSize: 10,
                                          letterSpacing: 1),
                                    ),
                                  ],
                                ),
                              ),
                              if ((m['family_role'] ?? m['role'] ?? '').toString().toUpperCase() != 'HEAD') ...[
                                Text(
                                  () {
                                    final cents = (m['family_billing_price_cents'] as int?) ?? 0;
                                    return cents > 0 ? '\$${(cents / 100).toStringAsFixed(0)}/mo' : 'Free';
                                  }(),
                                  style: TextStyle(
                                    color: ((m['family_billing_price_cents'] as int?) ?? 0) > 0 ? _D.textSecondary : const Color(0xFF4ECDC4),
                                    fontSize: 11,
                                  ),
                                ),
                                IconButton(
                                  onPressed: () => _confirmRemove(m),
                                  icon: const Icon(Icons.remove_circle_outline,
                                      color: _D.red, size: 20),
                                ),
                              ],
                            ]),
                          )),

                    const SizedBox(height: 16),
                    // Invite button
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _D.gold,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10)),
                        ),
                        onPressed: _showInviteDialog,
                        icon: const Icon(Icons.person_add,
                            color: Colors.black, size: 18),
                        label: const Text('Invite Family Member',
                            style: TextStyle(
                                color: Colors.black,
                                fontWeight: FontWeight.bold,
                                fontSize: 14)),
                      ),
                    ),
                  ],
                ),
    );
  }

  Widget _summaryRow(String label, String value, {bool bold = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label,
              style: TextStyle(
                  color: bold ? _D.textPrimary : _D.textSecondary,
                  fontSize: 12,
                  fontWeight: bold ? FontWeight.bold : FontWeight.normal)),
          Text(value,
              style: TextStyle(
                  color: bold ? _D.gold : _D.textPrimary,
                  fontSize: 12,
                  fontWeight: bold ? FontWeight.bold : FontWeight.normal)),
        ],
      ),
    );
  }
}

// =============================================================================
// 3. COACHING PACK SCREEN
// =============================================================================

class CoachingPackScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final WebSocketChannel? socket;

  const CoachingPackScreen({
    super.key,
    required this.currentUserProfile,
    this.socket,
  });

  @override
  State<CoachingPackScreen> createState() => _CoachingPackScreenState();
}

class _CoachingPackScreenState extends State<CoachingPackScreen> {
  List<Map<String, dynamic>> _packs = [];
  List<Map<String, dynamic>> _sessions = [];
  int _totalCredits = 0;
  bool _loading = true;

  String get _userId =>
      widget.currentUserProfile['hardware_id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  void _sendWs(Map<String, dynamic> msg) {
    try {
      widget.socket?.sink.add(jsonEncode(msg));
    } catch (_) {}
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
    try {
      // Load packs
      final packsResp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/coaching/packs/$_userId'),
        headers: _authHeaders(_userId),
      );
      if (packsResp.statusCode == 200) {
        final data = jsonDecode(packsResp.body);
        _packs = List<Map<String, dynamic>>.from(data['packs'] ?? []);
        _totalCredits = data['total_remaining_credits'] ?? 0;
      }

      // Load sessions
      final sessResp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/coaching/sessions/$_userId'),
        headers: _authHeaders(_userId),
      );
      if (sessResp.statusCode == 200) {
        final data = jsonDecode(sessResp.body);
        _sessions = List<Map<String, dynamic>>.from(data['sessions'] ?? []);
      }
    } catch (_) {}

    if (mounted) setState(() => _loading = false);
  }

  void _purchasePack(String packType, String label, int price) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _D.bgCard,
        title: Text('Purchase $label',
            style: const TextStyle(color: _D.gold, fontFamily: 'Cormorant Garamond')),
        content: Text(
          'You are purchasing the $label for \$$price. '
          'You will be redirected to Stripe to complete payment.',
          style: const TextStyle(color: _D.textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel',
                style: TextStyle(color: _D.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _D.gold),
            onPressed: () {
              Navigator.pop(ctx);
              _sendWs({
                'type': 'get_checkout_url',
                'pack_type': packType,
                'success_url':
                    'https://app.sovereignsanctuary.net/coaching/success',
                'cancel_url':
                    'https://app.sovereignsanctuary.net/coaching/cancel',
              });
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text('Opening Stripe checkout...'),
                backgroundColor: _D.bgElevated,
              ));
            },
            child: const Text('Continue to Payment',
                style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  void _cancelSession(Map<String, dynamic> session) {
    final scheduledAt = session['scheduled_at'] ?? '';
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _D.bgCard,
        title: const Text('Cancel Session',
            style: TextStyle(color: _D.red)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Cancel your coaching session scheduled for $scheduledAt?',
              style: const TextStyle(color: _D.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: _D.red.withOpacity(0.08),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Row(children: [
                Icon(Icons.warning_amber, color: _D.red, size: 16),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Sessions must be cancelled at least 24 hours before the scheduled time.',
                    style: TextStyle(color: _D.red, fontSize: 11),
                  ),
                ),
              ]),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Keep Session',
                style: TextStyle(color: _D.textSecondary)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _D.red),
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                final resp = await http.post(
                  Uri.parse(
                      '$defaultApiBaseUrl/api/billing/coaching/cancel/${session['session_id']}'),
                  headers: _authHeaders(_userId, json: true),
                  body: jsonEncode({
                    'user_id': _userId,
                    'reason': 'Client requested cancellation',
                  }),
                );
                if (resp.statusCode == 200) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                      content: Text('Session cancelled. Credit refunded.'),
                      backgroundColor: _D.bgElevated,
                    ));
                    _loadData();
                  }
                } else {
                  final body = jsonDecode(resp.body);
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                      content: Text(body['detail'] ?? 'Cancellation failed'),
                      backgroundColor: _D.red,
                    ));
                  }
                }
              } catch (e) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text('Error: $e'),
                    backgroundColor: _D.red,
                  ));
                }
              }
            },
            child: const Text('Cancel Session',
                style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgCard,
        title: const Text('COACHING',
            style: TextStyle(
                color: _D.cyan,
                fontSize: 16,
                letterSpacing: 3,
                fontFamily: 'Cormorant Garamond')),
        centerTitle: true,
        iconTheme: const IconThemeData(color: _D.textPrimary),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _D.cyan))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Credits summary
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: _D.bgCard,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: _D.cyan.withOpacity(0.3)),
                  ),
                  child: Row(children: [
                    Container(
                      width: 48,
                      height: 48,
                      decoration: BoxDecoration(
                        color: _D.cyan.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child:
                          const Icon(Icons.token, color: _D.cyan, size: 24),
                    ),
                    const SizedBox(width: 14),
                    Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('$_totalCredits',
                              style: const TextStyle(
                                  color: _D.textPrimary,
                                  fontSize: 28,
                                  fontWeight: FontWeight.bold)),
                          const Text('Session Credits Remaining',
                              style: TextStyle(
                                  color: _D.textSecondary, fontSize: 11)),
                        ]),
                  ]),
                ),

                const SizedBox(height: 20),
                const Text('BUY SESSION PACK',
                    style: TextStyle(
                        color: _D.gold,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 2)),
                const SizedBox(height: 12),

                // Pack options
                _packCard('single', 'Single Session', 175, 1,
                    'One coaching session'),
                const SizedBox(height: 10),
                _packCard('pack_4', '4-Session Pack', 600, 4,
                    'Save \$100 — \$150/session'),
                const SizedBox(height: 10),
                _packCard('pack_8', '8-Session Pack', 1120, 8,
                    'Save \$280 — \$140/session'),

                const SizedBox(height: 24),
                const Text('YOUR SESSIONS',
                    style: TextStyle(
                        color: _D.gold,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 2)),
                const SizedBox(height: 12),

                if (_sessions.isEmpty)
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: _D.bgCard,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: _D.border),
                    ),
                    child: const Center(
                      child: Text('No sessions yet',
                          style: TextStyle(
                              color: _D.textSecondary, fontSize: 13)),
                    ),
                  )
                else
                  ..._sessions.map((s) => Container(
                        margin: const EdgeInsets.only(bottom: 8),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: _D.bgCard,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _D.border),
                        ),
                        child: Row(children: [
                          Icon(
                            s['status'] == 'booked'
                                ? Icons.event
                                : s['status'] == 'cancelled'
                                    ? Icons.event_busy
                                    : Icons.event_available,
                            color: s['status'] == 'booked'
                                ? _D.cyan
                                : s['status'] == 'cancelled'
                                    ? _D.red
                                    : _D.green,
                            size: 20,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  s['scheduled_at'] ?? 'TBD',
                                  style: const TextStyle(
                                      color: _D.textPrimary, fontSize: 13),
                                ),
                                Text(
                                  'Coach: ${s['coach_id'] ?? 'TBD'} · ${(s['status'] ?? 'unknown').toString().toUpperCase()}',
                                  style: const TextStyle(
                                      color: _D.textSecondary, fontSize: 10),
                                ),
                              ],
                            ),
                          ),
                          if (s['status'] == 'booked')
                            IconButton(
                              onPressed: () => _cancelSession(s),
                              icon: const Icon(Icons.cancel_outlined,
                                  color: _D.red, size: 18),
                            ),
                        ]),
                      )),
              ],
            ),
    );
  }

  Widget _packCard(
      String type, String label, int price, int sessions, String subtitle) {
    return InkWell(
      onTap: () => _purchasePack(type, label, price),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: _D.bgCard,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: _D.cyan.withOpacity(0.3)),
        ),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(
                        color: _D.textPrimary,
                        fontSize: 15,
                        fontWeight: FontWeight.bold)),
                const SizedBox(height: 2),
                Text(subtitle,
                    style:
                        const TextStyle(color: _D.textSecondary, fontSize: 11)),
              ],
            ),
          ),
          Column(children: [
            Text('\$$price',
                style: const TextStyle(
                    color: _D.cyan,
                    fontSize: 20,
                    fontWeight: FontWeight.bold)),
            Text('$sessions session${sessions > 1 ? 's' : ''}',
                style:
                    const TextStyle(color: _D.textSecondary, fontSize: 10)),
          ]),
          const SizedBox(width: 8),
          const Icon(Icons.arrow_forward_ios,
              color: _D.textSecondary, size: 14),
        ]),
      ),
    );
  }
}

// =============================================================================
// 4. PAYMENT METHODS & INVOICES SCREEN
// =============================================================================

class PaymentMethodsScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final int initialTab;

  const PaymentMethodsScreen({
    super.key,
    required this.currentUserProfile,
    this.initialTab = 0,
  });

  @override
  State<PaymentMethodsScreen> createState() => _PaymentMethodsScreenState();
}

class _PaymentMethodsScreenState extends State<PaymentMethodsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabCtrl;
  List<Map<String, dynamic>> _methods = [];
  List<Map<String, dynamic>> _invoices = [];
  List<Map<String, dynamic>> _scholarships = [];
  bool _loadingMethods = true;
  bool _loadingInvoices = true;
  bool _loadingScholarships = true;
  bool _addingCard = false;
  bool _addingBank = false;
  String? _appliedSchoolName;
  String? _appliedCompanyName;
  String? _discountCodeError;
  String? _discountCodeSuccess;
  final _schoolCodeCtrl = TextEditingController();
  final _corporateCodeCtrl = TextEditingController();

  String get _userId =>
      widget.currentUserProfile['hardware_id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: 4, vsync: this, initialIndex: widget.initialTab);
    _loadPaymentMethods();
    _loadInvoices();
    _loadScholarships();
  }

  @override
  void dispose() {
    _tabCtrl.dispose();
    _schoolCodeCtrl.dispose();
    _corporateCodeCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadPaymentMethods() async {
    try {
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/payment-methods/$_userId'),
        headers: _authHeaders(_userId),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (mounted) {
          setState(() {
            _methods =
                List<Map<String, dynamic>>.from(data['payment_methods'] ?? []);
            _loadingMethods = false;
          });
        }
        return;
      }
    } catch (_) {}
    if (mounted) setState(() => _loadingMethods = false);
  }

  Future<void> _loadInvoices() async {
    try {
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/invoices/$_userId'),
        headers: _authHeaders(_userId),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (mounted) {
          setState(() {
            _invoices =
                List<Map<String, dynamic>>.from(data['invoices'] ?? []);
            _loadingInvoices = false;
          });
        }
        return;
      }
    } catch (_) {}
    if (mounted) setState(() => _loadingInvoices = false);
  }

  Future<void> _deleteMethod(String pmId) async {
    try {
      final resp = await http.delete(
        Uri.parse(
            '$defaultApiBaseUrl/api/billing/payment-methods/$pmId?user_id=$_userId'),
        headers: _authHeaders(_userId),
      );
      if (resp.statusCode == 200) {
        setState(() => _methods.removeWhere((m) => m['id'] == pmId));
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Payment method removed'),
            backgroundColor: _D.bgElevated,
          ));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Error: $e'),
          backgroundColor: _D.red,
        ));
      }
    }
  }

  Future<void> _loadScholarships() async {
    try {
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/scholarship/user/$_userId'),
        headers: _authHeaders(_userId),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (mounted) {
          setState(() {
            _scholarships = List<Map<String, dynamic>>.from(data['scholarships'] ?? []);
            _loadingScholarships = false;
          });
        }
        return;
      }
    } catch (_) {}
    if (mounted) setState(() => _loadingScholarships = false);
  }

  Future<void> _setDefaultPaymentMethod(String pmId) async {
    try {
      final resp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/payment-method/default'),
        headers: _authHeaders(_userId, json: true),
        body: jsonEncode({'user_id': _userId, 'payment_method_id': pmId}),
      );
      if (resp.statusCode == 200) {
        setState(() {
          for (var m in _methods) {
            m['is_default'] = m['id'] == pmId;
          }
        });
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Default payment method updated'), backgroundColor: _D.bgElevated),
          );
        }
      }
    } catch (_) {}
  }

  Future<void> _applySchoolCode(String code) async {
    setState(() { _discountCodeError = null; _discountCodeSuccess = null; });
    try {
      final verifyResp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/verify-school-code/${Uri.encodeComponent(code)}'),
        headers: _authHeaders(_userId),
      );
      if (verifyResp.statusCode != 200) {
        final err = jsonDecode(verifyResp.body);
        setState(() => _discountCodeError = err['detail'] ?? 'Invalid code');
        return;
      }
      final applyResp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/apply-school-code'),
        headers: _authHeaders(_userId, json: true),
        body: jsonEncode({'user_id': _userId, 'school_code': code}),
      );
      if (applyResp.statusCode == 200) {
        final data = jsonDecode(applyResp.body);
        setState(() {
          _appliedSchoolName = data['school_name'];
          _discountCodeSuccess = '${data["discount_percent"]}% student discount applied!';
        });
      } else {
        final err = jsonDecode(applyResp.body);
        setState(() => _discountCodeError = err['detail'] ?? 'Failed to apply');
      }
    } catch (e) {
      setState(() => _discountCodeError = 'Connection error');
    }
  }

  Future<void> _applyCorporateCode(String code) async {
    setState(() { _discountCodeError = null; _discountCodeSuccess = null; });
    try {
      final verifyResp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/verify-corporate-code/${Uri.encodeComponent(code)}'),
        headers: _authHeaders(_userId),
      );
      if (verifyResp.statusCode != 200) {
        final err = jsonDecode(verifyResp.body);
        setState(() => _discountCodeError = err['detail'] ?? 'Invalid code');
        return;
      }
      final applyResp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/apply-corporate-code'),
        headers: _authHeaders(_userId, json: true),
        body: jsonEncode({'user_id': _userId, 'sponsor_code': code}),
      );
      if (applyResp.statusCode == 200) {
        final data = jsonDecode(applyResp.body);
        setState(() {
          _appliedCompanyName = data['company_name'];
          _discountCodeSuccess = data['pays_full'] == true
              ? 'Fully sponsored by ${data["company_name"]}!'
              : 'Corporate discount applied!';
        });
      } else {
        final err = jsonDecode(applyResp.body);
        setState(() => _discountCodeError = err['detail'] ?? 'Failed to apply');
      }
    } catch (e) {
      setState(() => _discountCodeError = 'Connection error');
    }
  }

  Future<void> _downloadSuperbill({String? month}) async {
    final m = month ?? DateTime.now().toString().substring(0, 7);
    try {
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/superbill/$_userId?month=$m'),
        headers: _authHeaders(_userId),
      );
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body);
        final sb = data['superbill'] ?? {};
        showDialog(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: _D.bgCard,
            title: const Text('Superbill', style: TextStyle(color: _D.gold)),
            content: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('Billing Period: ${sb["billing_period"] ?? m}',
                      style: const TextStyle(color: _D.textSecondary, fontSize: 12)),
                  Text('Client: ${sb["client"]?["name"] ?? ""}',
                      style: const TextStyle(color: _D.textPrimary, fontSize: 13)),
                  const SizedBox(height: 10),
                  ...(sb['services'] as List? ?? []).map((s) => Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Expanded(child: Text(
                          '${s["date"]} — ${s["cpt_code"]}',
                          style: const TextStyle(color: _D.textPrimary, fontSize: 12),
                        )),
                        Text('\$${((s["amount_cents"] ?? 0) / 100).toStringAsFixed(2)}',
                            style: const TextStyle(color: _D.gold, fontSize: 12)),
                      ],
                    ),
                  )),
                  const Divider(color: _D.border),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Total', style: TextStyle(color: _D.textPrimary, fontWeight: FontWeight.bold)),
                      Text(sb['total_formatted'] ?? '\$0.00',
                          style: const TextStyle(color: _D.gold, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Text(sb['disclaimer'] ?? '', style: const TextStyle(color: _D.textSecondary, fontSize: 10)),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Close', style: TextStyle(color: _D.gold)),
              ),
            ],
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to load superbill'), backgroundColor: _D.red),
        );
      }
    }
  }

  Future<void> _addPaymentMethod(String type) async {
    if (type == 'card' && _addingCard) return;
    if (type == 'bank' && _addingBank) return;
    setState(() {
      if (type == 'card') _addingCard = true;
      if (type == 'bank') _addingBank = true;
    });
    try {
      final resp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/payment-method/add-checkout'),
        headers: _authHeaders(_userId, json: true),
        body: jsonEncode({'user_id': _userId, 'method_type': type}),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final url = data['checkout_url'] as String?;
        if (url != null && url.isNotEmpty) {
          final uri = Uri.parse(url);
          if (await canLaunchUrl(uri)) {
            await launchUrl(uri, mode: LaunchMode.externalApplication);
          }
        }
      } else {
        final err = jsonDecode(resp.body);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(err['detail']?.toString() ?? 'Failed to start setup'),
            backgroundColor: _D.red,
          ));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Connection error: $e'),
          backgroundColor: _D.red,
        ));
      }
    }
    if (mounted) {
      setState(() {
        _addingCard = false;
        _addingBank = false;
      });
      _loadPaymentMethods();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgCard,
        title: const Text('BILLING',
            style: TextStyle(
                color: _D.gold,
                fontSize: 16,
                letterSpacing: 3,
                fontFamily: 'Cormorant Garamond')),
        centerTitle: true,
        iconTheme: const IconThemeData(color: _D.textPrimary),
        bottom: TabBar(
          controller: _tabCtrl,
          indicatorColor: _D.gold,
          labelColor: _D.gold,
          unselectedLabelColor: _D.textSecondary,
          isScrollable: true,
          tabs: const [
            Tab(text: 'Methods'),
            Tab(text: 'Invoices'),
            Tab(text: 'Discounts'),
            Tab(text: 'Scholarships'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabCtrl,
        children: [
          // Payment Methods tab
          _loadingMethods
              ? const Center(child: CircularProgressIndicator(color: _D.gold))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    // Billing summary
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: _D.bgCard,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: _D.border),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Current Plan',
                              style: TextStyle(
                                  color: _D.textSecondary, fontSize: 11)),
                          const SizedBox(height: 4),
                          Text(
                            _planDisplayName(widget
                                    .currentUserProfile['subscription_plan'] ??
                                'TRIAL'),
                            style: const TextStyle(
                                color: _D.gold,
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                fontFamily: 'Cormorant Garamond'),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Next billing date: ${widget.currentUserProfile['next_billing_date'] ?? 'N/A'}',
                            style: const TextStyle(
                                color: _D.textSecondary, fontSize: 11),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Add Payment Method buttons
                    Row(
                      children: [
                        Expanded(
                          child: _AddPaymentButton(
                            icon: Icons.credit_card,
                            label: 'Add Card',
                            loading: _addingCard,
                            onTap: () => _addPaymentMethod('card'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: _AddPaymentButton(
                            icon: Icons.account_balance,
                            label: 'Add Bank Account',
                            loading: _addingBank,
                            onTap: () => _addPaymentMethod('bank'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    if (_methods.isEmpty)
                      Container(
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                          color: _D.bgCard,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _D.border),
                        ),
                        child: const Center(
                          child: Text('No payment methods on file',
                              style: TextStyle(
                                  color: _D.textSecondary, fontSize: 13)),
                        ),
                      )
                    else
                      ..._methods.map((m) {
                        final isBank = m['type'] == 'us_bank_account';
                        final isDefault = m['is_default'] == true;
                        return Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: _D.bgCard,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(
                                color: isDefault
                                    ? _D.gold.withOpacity(0.5)
                                    : _D.border,
                              ),
                            ),
                            child: Row(children: [
                              Icon(
                                isBank ? Icons.account_balance : Icons.credit_card,
                                color: isDefault ? _D.gold : _D.textSecondary,
                                size: 24,
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      isBank
                                          ? '${(m['bank_name'] ?? 'Bank').toString()} •••• ${m['last4'] ?? '????'}'
                                          : '${(m['brand'] ?? 'Card').toString().toUpperCase()} •••• ${m['last4'] ?? '????'}',
                                      style: const TextStyle(
                                          color: _D.textPrimary,
                                          fontSize: 14,
                                          fontWeight: FontWeight.w500),
                                    ),
                                    Text(
                                      isBank
                                          ? 'ACH Direct Debit${isDefault ? ' · Default' : ''}'
                                          : 'Exp ${m['exp_month'] ?? '??'}/${m['exp_year'] ?? '??'}${isDefault ? ' · Default' : ''}',
                                      style: const TextStyle(
                                          color: _D.textSecondary,
                                          fontSize: 11),
                                    ),
                                  ],
                                ),
                              ),
                              if (!isDefault)
                                IconButton(
                                  onPressed: () => _setDefaultPaymentMethod(m['id'] ?? ''),
                                  icon: const Icon(Icons.star_border,
                                      color: _D.textSecondary, size: 18),
                                  tooltip: 'Set as default',
                                ),
                              IconButton(
                                onPressed: () => _deleteMethod(m['id'] ?? ''),
                                icon: const Icon(Icons.delete_outline,
                                    color: _D.red, size: 18),
                              ),
                            ]),
                          );
                      }),
                  ],
                ),

          // Invoices tab
          _loadingInvoices
              ? const Center(child: CircularProgressIndicator(color: _D.gold))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (_invoices.isEmpty)
                      Container(
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                          color: _D.bgCard,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _D.border),
                        ),
                        child: const Center(
                          child: Text('No invoices yet',
                              style: TextStyle(
                                  color: _D.textSecondary, fontSize: 13)),
                        ),
                      )
                    else
                      ..._invoices.map((inv) => Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: _D.bgCard,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: _D.border),
                            ),
                            child: Row(children: [
                              Icon(
                                inv['status'] == 'paid'
                                    ? Icons.check_circle
                                    : Icons.pending,
                                color: inv['status'] == 'paid'
                                    ? _D.green
                                    : _D.textSecondary,
                                size: 20,
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '\$${inv['amount_paid'] ?? inv['amount_due'] ?? '0.00'}',
                                      style: const TextStyle(
                                          color: _D.textPrimary,
                                          fontSize: 14,
                                          fontWeight: FontWeight.bold),
                                    ),
                                    Text(
                                      '${inv['created'] ?? inv['timestamp'] ?? ''} · ${(inv['status'] ?? '').toString().toUpperCase()}',
                                      style: const TextStyle(
                                          color: _D.textSecondary,
                                          fontSize: 10),
                                    ),
                                  ],
                                ),
                              ),
                              if (inv['pdf_url'] != null)
                                IconButton(
                                  onPressed: () async {
                                    final url = Uri.parse(inv['pdf_url']);
                                    if (await canLaunchUrl(url)) {
                                      await launchUrl(url,
                                          mode:
                                              LaunchMode.externalApplication);
                                    }
                                  },
                                  icon: const Icon(Icons.download,
                                      color: _D.gold, size: 18),
                                ),
                            ]),
                          )),
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: _D.bgCard,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: _D.border),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.medical_services_outlined, color: _D.cyan, size: 20),
                          const SizedBox(width: 10),
                          const Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('HSA/FSA Superbill', style: TextStyle(color: _D.textPrimary, fontSize: 13, fontWeight: FontWeight.w500)),
                                Text('Download for insurance reimbursement', style: TextStyle(color: _D.textSecondary, fontSize: 11)),
                              ],
                            ),
                          ),
                          TextButton(
                            onPressed: () => _downloadSuperbill(),
                            child: const Text('Download', style: TextStyle(color: _D.gold, fontSize: 12)),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),

          // Discounts tab
          ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (_appliedSchoolName != null)
                _discountBadge(Icons.school, 'Student Discount', _appliedSchoolName!),
              if (_appliedCompanyName != null)
                _discountBadge(Icons.business, 'Corporate Plan', _appliedCompanyName!),
              if (_discountCodeSuccess != null) ...[
                Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: _D.green.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: _D.green.withOpacity(0.3)),
                  ),
                  child: Text(_discountCodeSuccess!, style: const TextStyle(color: _D.green, fontSize: 13)),
                ),
              ],
              if (_discountCodeError != null) ...[
                Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: _D.red.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: _D.red.withOpacity(0.3)),
                  ),
                  child: Text(_discountCodeError!, style: const TextStyle(color: _D.red, fontSize: 13)),
                ),
              ],
              _discountCodeSection(
                icon: Icons.school,
                title: 'Student Discount',
                subtitle: 'Enter your school code for a student discount',
                hintText: 'School code (e.g. STANFORD2026)',
                controller: _schoolCodeCtrl,
                onApply: _applySchoolCode,
              ),
              const SizedBox(height: 12),
              _discountCodeSection(
                icon: Icons.business,
                title: 'Corporate Sponsor',
                subtitle: 'Enter your employer code for corporate benefits',
                hintText: 'Corporate code (e.g. ACME100)',
                controller: _corporateCodeCtrl,
                onApply: _applyCorporateCode,
              ),
            ],
          ),

          // Scholarships tab
          _loadingScholarships
              ? const Center(child: CircularProgressIndicator(color: _D.gold))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (_scholarships.isEmpty)
                      Container(
                        padding: const EdgeInsets.all(24),
                        decoration: BoxDecoration(
                          color: _D.bgCard,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: _D.border),
                        ),
                        child: const Column(
                          children: [
                            Icon(Icons.volunteer_activism, color: _D.textSecondary, size: 36),
                            SizedBox(height: 10),
                            Text('No active scholarships',
                                style: TextStyle(color: _D.textSecondary, fontSize: 14)),
                            SizedBox(height: 4),
                            Text('Scholarships cover service costs before your card is charged.',
                                style: TextStyle(color: _D.textSecondary, fontSize: 11),
                                textAlign: TextAlign.center),
                          ],
                        ),
                      )
                    else
                      ..._scholarships.map((s) => Container(
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: _D.bgCard,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _D.purple.withOpacity(0.3)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(children: [
                              const Icon(Icons.volunteer_activism, color: _D.purple, size: 20),
                              const SizedBox(width: 8),
                              Expanded(child: Text(
                                s['fund_name']?.toString() ?? 'Scholarship',
                                style: const TextStyle(color: _D.textPrimary, fontSize: 14, fontWeight: FontWeight.w600),
                              )),
                            ]),
                            const SizedBox(height: 6),
                            if (s['sponsor_name'] != null)
                              Text('Sponsored by ${s["sponsor_name"]}',
                                  style: const TextStyle(color: _D.purple, fontSize: 12)),
                            const SizedBox(height: 6),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(
                                  'Fund balance: \$${((s["fund_balance_cents"] ?? 0) / 100).toStringAsFixed(2)}',
                                  style: const TextStyle(color: _D.gold, fontSize: 12),
                                ),
                                if (s['monthly_limit_cents'] != null)
                                  Text(
                                    'Monthly limit: \$${((s["monthly_limit_cents"] ?? 0) / 100).toStringAsFixed(2)}',
                                    style: const TextStyle(color: _D.textSecondary, fontSize: 11),
                                  ),
                              ],
                            ),
                            if (s['monthly_limit_cents'] != null) ...[
                              const SizedBox(height: 4),
                              LinearProgressIndicator(
                                value: (s['monthly_limit_cents'] ?? 1) > 0
                                    ? (s['used_this_month'] ?? 0) / (s['monthly_limit_cents'] ?? 1)
                                    : 0,
                                backgroundColor: _D.border,
                                valueColor: const AlwaysStoppedAnimation<Color>(_D.purple),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                'Used this month: \$${((s["used_this_month"] ?? 0) / 100).toStringAsFixed(2)}',
                                style: const TextStyle(color: _D.textSecondary, fontSize: 10),
                              ),
                            ],
                          ],
                        ),
                      )),
                  ],
                ),
        ],
      ),
    );
  }

  Widget _discountBadge(IconData icon, String label, String value) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _D.bgCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _D.gold.withOpacity(0.3)),
      ),
      child: Row(children: [
        Icon(icon, color: _D.gold, size: 20),
        const SizedBox(width: 10),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(color: _D.gold, fontSize: 12, fontWeight: FontWeight.w600)),
            Text(value, style: const TextStyle(color: _D.textPrimary, fontSize: 13)),
          ],
        )),
        const Icon(Icons.check_circle, color: _D.green, size: 18),
      ]),
    );
  }

  Widget _discountCodeSection({
    required IconData icon,
    required String title,
    required String subtitle,
    required String hintText,
    required TextEditingController controller,
    required Future<void> Function(String) onApply,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _D.bgCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _D.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(icon, color: _D.textSecondary, size: 20),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(color: _D.textPrimary, fontSize: 14, fontWeight: FontWeight.w500)),
          ]),
          const SizedBox(height: 4),
          Text(subtitle, style: const TextStyle(color: _D.textSecondary, fontSize: 11)),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: TextField(
                controller: controller,
                style: const TextStyle(color: _D.textPrimary, fontSize: 13),
                decoration: InputDecoration(
                  hintText: hintText,
                  hintStyle: const TextStyle(color: _D.textSecondary, fontSize: 12),
                  filled: true,
                  fillColor: _D.bgElevated,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                ),
              ),
            ),
            const SizedBox(width: 8),
            ElevatedButton(
              onPressed: () {
                if (controller.text.trim().isNotEmpty) onApply(controller.text.trim());
              },
              style: ElevatedButton.styleFrom(backgroundColor: _D.bgElevated),
              child: const Text('Apply', style: TextStyle(color: _D.gold, fontSize: 12)),
            ),
          ]),
        ],
      ),
    );
  }

  String _planDisplayName(String plan) {
    switch (plan.toUpperCase()) {
      case 'COACH_ONLY':
        return 'Coach Only';
      case 'TRIAL':
      case 'THRESHOLD':
        return 'Threshold (Trial)';
      case 'STANDARD':
      case 'INNER_CHAMBER':
        return 'Inner Chamber';
      case 'TOP_TIER':
      case 'SOVEREIGN_CIRCLE':
        return 'Sovereign Circle';
      default:
        return plan;
    }
  }
}

// =============================================================================
// 5. TRIAL BANNER WIDGET — Countdown + Upgrade CTA
// =============================================================================

class TrialBannerWidget extends StatelessWidget {
  final Map<String, dynamic> userProfile;
  final VoidCallback? onUpgrade;

  const TrialBannerWidget({
    super.key,
    required this.userProfile,
    this.onUpgrade,
  });

  @override
  Widget build(BuildContext context) {
    final plan = (userProfile['subscription_plan'] ?? '').toString().toUpperCase();
    final status =
        (userProfile['subscription_status'] ?? '').toString().toUpperCase();

    // Only show for trial users
    if (plan != 'TRIAL' && plan != 'THRESHOLD' && plan != '') return const SizedBox.shrink();
    if (status == 'ACTIVE' && plan != 'TRIAL' && plan != 'THRESHOLD' && plan != '') {
      return const SizedBox.shrink();
    }

    // Calculate days remaining
    final trialStartStr = userProfile['trial_start_date'] ??
        userProfile['created_at'] ??
        '';
    int daysRemaining = 14;
    if (trialStartStr.toString().isNotEmpty) {
      try {
        final start = DateTime.parse(trialStartStr.toString());
        final end = start.add(const Duration(days: 14));
        daysRemaining = end.difference(DateTime.now()).inDays;
        if (daysRemaining < 0) daysRemaining = 0;
      } catch (_) {}
    }

    final isExpired = daysRemaining <= 0 || status == 'TRIAL_EXPIRED' || status == 'GRACE_EXPIRED';
    final isUrgent = daysRemaining <= 3;

    // Full-screen modal on expiry
    if (isExpired) {
      return _TrialExpiredBanner(onUpgrade: onUpgrade);
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: isUrgent ? _D.red.withOpacity(0.12) : _D.gold.withOpacity(0.08),
        border: Border(
          bottom: BorderSide(
            color: isUrgent ? _D.red.withOpacity(0.3) : _D.gold.withOpacity(0.2),
          ),
        ),
      ),
      child: Row(children: [
        Icon(
          isUrgent ? Icons.warning_amber : Icons.timer,
          color: isUrgent ? _D.red : _D.gold,
          size: 18,
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                isUrgent
                    ? 'Trial ends in $daysRemaining day${daysRemaining != 1 ? 's' : ''}!'
                    : '$daysRemaining days left in your trial',
                style: TextStyle(
                  color: isUrgent ? _D.red : _D.gold,
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                ),
              ),
              if (isUrgent)
                const Text(
                  'Upgrade now to keep your progress',
                  style: TextStyle(color: _D.textSecondary, fontSize: 10),
                ),
            ],
          ),
        ),
        TextButton(
          onPressed: onUpgrade,
          style: TextButton.styleFrom(
            backgroundColor: isUrgent ? _D.red : _D.gold,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
          ),
          child: const Text('Upgrade',
              style: TextStyle(
                  color: Colors.black,
                  fontSize: 11,
                  fontWeight: FontWeight.bold)),
        ),
      ]),
    );
  }
}

class _TrialExpiredBanner extends StatelessWidget {
  final VoidCallback? onUpgrade;

  const _TrialExpiredBanner({this.onUpgrade});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _D.bgCard,
        border: Border.all(color: _D.red.withOpacity(0.3)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.hourglass_disabled, color: _D.red, size: 36),
          const SizedBox(height: 12),
          const Text(
            'Your Trial Has Ended',
            style: TextStyle(
              color: _D.textPrimary,
              fontSize: 18,
              fontWeight: FontWeight.bold,
              fontFamily: 'Cormorant Garamond',
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'Your conversations, progress, and insights are all waiting for you. '
            'Choose a plan to continue your journey.',
            style:
                TextStyle(color: _D.textSecondary, fontSize: 12, height: 1.5),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _planButton('Inner Chamber', '\$49/mo', _D.cyan, onUpgrade),
              const SizedBox(width: 12),
              _planButton('Sovereign Circle', '\$149/mo', _D.gold, onUpgrade),
            ],
          ),
        ],
      ),
    );
  }

  Widget _planButton(
      String name, String price, Color color, VoidCallback? onTap) {
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: color.withOpacity(0.12),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withOpacity(0.4)),
        ),
        child: Column(children: [
          Text(name,
              style: TextStyle(
                  color: color, fontSize: 12, fontWeight: FontWeight.bold)),
          Text(price,
              style: const TextStyle(color: _D.textSecondary, fontSize: 10)),
        ]),
      ),
    );
  }
}


class _AddPaymentButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool loading;
  final VoidCallback onTap;

  const _AddPaymentButton({
    required this.icon,
    required this.label,
    required this.loading,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: loading ? null : onTap,
      borderRadius: BorderRadius.circular(10),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: _D.bgCard,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: _D.gold.withOpacity(0.3)),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: loading
              ? [const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: _D.gold))]
              : [
                  Icon(icon, color: _D.gold, size: 18),
                  const SizedBox(width: 8),
                  Text(label, style: const TextStyle(color: _D.gold, fontSize: 13, fontWeight: FontWeight.w600)),
                ],
        ),
      ),
    );
  }
}
