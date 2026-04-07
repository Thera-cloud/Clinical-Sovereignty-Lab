import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class PaymentConfirmationScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String checkoutType;

  static bool pendingCheckout = false;
  static String pendingCheckoutType = 'plan_upgrade';

  const PaymentConfirmationScreen({super.key, required this.profile, this.checkoutType = 'plan_upgrade'});

  @override
  State<PaymentConfirmationScreen> createState() => _PaymentConfirmationScreenState();
}

class _PaymentConfirmationScreenState extends State<PaymentConfirmationScreen> {
  String _status = 'checking';
  Timer? _pollTimer;
  int _elapsed = 0;
  final String _origTier = '';
  int _origTokens = 0;

  @override
  void initState() {
    super.initState();
    _origTokens = (widget.profile['token_balance'] ?? 0) as int;
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) => _check());
    _check();
  }

  Future<void> _check() async {
    _elapsed += 3;
    final token = widget.profile['token'] ?? '';
    try {
      final resp = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/client/health-check'),
        headers: {'Authorization': 'Bearer $token'},
      ).timeout(const Duration(seconds: 5));
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final newTokens = (data['token_balance'] ?? _origTokens) as int;
        final tierChanged = data['tier'] != null && data['tier'] != (widget.profile['tier'] ?? '');
        if (newTokens > _origTokens || tierChanged) {
          _pollTimer?.cancel();
          setState(() => _status = 'success');
          return;
        }
      }
    } catch (_) {}
    if (_elapsed >= 30) { _pollTimer?.cancel(); setState(() => _status = 'timeout'); }
    else if (_elapsed >= 10 && _status == 'checking') { setState(() => _status = 'processing'); }
  }

  @override
  void dispose() { _pollTimer?.cancel(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      body: Center(child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_status == 'checking' || _status == 'processing')
            const CircularProgressIndicator(color: Color(0xFFC9A962)),
          if (_status == 'success')
            const Icon(Icons.check_circle, color: Color(0xFF4ECDC4), size: 64),
          if (_status == 'timeout')
            const Icon(Icons.info_outline, color: Color(0xFFC9A962), size: 64),
          const SizedBox(height: 24),
          Text(
            _status == 'checking' ? 'Confirming your payment...'
            : _status == 'processing' ? 'Still processing — this usually takes a moment.'
            : _status == 'success' ? (widget.checkoutType == 'token_purchase' ? 'Tokens added to your account!' : 'Payment confirmed!')
            : 'Something may have gone wrong.',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 18, fontFamily: 'Cormorant Garamond'),
          ),
          const SizedBox(height: 16),
          if (_status == 'timeout')
            Text('Check your email for a receipt, or contact support.',
              textAlign: TextAlign.center, style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 14)),
          const SizedBox(height: 24),
          if (_status == 'success' || _status == 'timeout')
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962)),
              onPressed: () => Navigator.pop(context),
              child: const Text('Continue', style: TextStyle(color: Colors.black)),
            ),
          if (_status == 'processing')
            TextButton(
              onPressed: () { _elapsed = 0; setState(() => _status = 'checking'); _pollTimer?.cancel();
                _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) => _check()); _check(); },
              child: const Text('Retry', style: TextStyle(color: Color(0xFFC9A962))),
            ),
        ]),
      )),
    );
  }
}
