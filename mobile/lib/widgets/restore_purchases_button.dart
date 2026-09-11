import 'package:flutter/material.dart';

import '../services/payment_service.dart';

/// Distinct user-tapped Restore control required by App Store Guideline 3.1.1.
class RestorePurchasesButton extends StatefulWidget {
  final String? userId;
  final String? authToken;
  final bool outlined;
  final Color gold;
  final Color goldDim;
  final Color textSecondary;

  const RestorePurchasesButton({
    super.key,
    required this.userId,
    required this.authToken,
    this.outlined = true,
    this.gold = const Color(0xFFC9A962),
    this.goldDim = const Color(0xFF8B7355),
    this.textSecondary = const Color(0xFF888888),
  });

  @override
  State<RestorePurchasesButton> createState() => _RestorePurchasesButtonState();
}

class _RestorePurchasesButtonState extends State<RestorePurchasesButton> {
  bool _busy = false;

  Future<void> _restore() async {
    if (_busy) return;
    final uid = widget.userId ?? '';
    final token = widget.authToken ?? '';
    if (uid.isEmpty || token.isEmpty) {
      _toast('Sign in to restore purchases', error: true);
      return;
    }
    setState(() => _busy = true);
    PaymentService.instance.setAuthContext(uid, token);
    final result = await PaymentService.instance.restorePurchases(authToken: token);
    if (!mounted) return;
    setState(() => _busy = false);
    if (result.status == PaymentStatus.error) {
      _toast(result.error ?? 'Restore failed', error: true);
      return;
    }
    if (result.restoreData?['empty'] == true) {
      _toast('No previous purchases found');
      return;
    }
    _toast('Purchases restored');
  }

  void _toast(String message, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message),
      backgroundColor: error ? const Color(0xFFEF4444) : const Color(0xFF1A1A1A),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final label = _busy ? 'Restoring…' : 'Restore Purchases';
    if (widget.outlined) {
      return SizedBox(
        width: double.infinity,
        child: OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            side: BorderSide(color: widget.goldDim),
            padding: const EdgeInsets.symmetric(vertical: 12),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          ),
          icon: _busy
              ? SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: widget.goldDim),
                )
              : Icon(Icons.restore, color: widget.goldDim, size: 16),
          label: Text(label, style: TextStyle(color: widget.goldDim, fontSize: 13, fontWeight: FontWeight.w600)),
          onPressed: _busy ? null : _restore,
        ),
      );
    }
    return TextButton(
      onPressed: _busy ? null : _restore,
      child: Text(
        label,
        style: TextStyle(
          color: widget.gold,
          fontSize: 13,
          fontWeight: FontWeight.w600,
          decoration: TextDecoration.underline,
        ),
      ),
    );
  }
}
