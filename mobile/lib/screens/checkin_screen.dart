import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class CheckinScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  const CheckinScreen({super.key, required this.profile});

  @override
  State<CheckinScreen> createState() => _CheckinScreenState();
}

class _CheckinScreenState extends State<CheckinScreen> {
  bool _submitted = false;
  String _responseMsg = '';

  Future<void> _submit(String emotion) async {
    if (_submitted) return;
    setState(() => _submitted = true);

    final token = widget.profile['token'] ?? '';
    try {
      final resp = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/sse-client/checkin'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
        body: json.encode({'emotion': emotion}),
      ).timeout(const Duration(seconds: 8));
      if (resp.statusCode == 200) {
        final data = json.decode(resp.body);
        setState(() => _responseMsg = data['message'] ?? 'Thanks for checking in.');
      } else {
        setState(() => _responseMsg = 'Thanks for checking in. I\'m here.');
      }
    } catch (_) {
      setState(() => _responseMsg = 'Thanks for checking in. I\'m here.');
    }

    await Future.delayed(const Duration(seconds: 2));
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      body: SafeArea(
        child: Center(
          child: _submitted
              ? _buildConfirmation()
              : _buildEmotionPicker(),
        ),
      ),
    );
  }

  Widget _buildEmotionPicker() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('How are you today?',
              style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w600)),
          const SizedBox(height: 32),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            alignment: WrapAlignment.center,
            children: [
              _emotionButton('😊', 'Good', 'good'),
              _emotionButton('😐', 'Okay', 'okay'),
              _emotionButton('😔', 'Hard', 'hard'),
              _emotionButton('😣', 'Struggling', 'struggling'),
            ],
          ),
          const SizedBox(height: 24),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Not now', style: TextStyle(color: Color(0xFF888888))),
          ),
        ],
      ),
    );
  }

  Widget _emotionButton(String emoji, String label, String value) {
    return GestureDetector(
      onTap: () => _submit(value),
      child: Container(
        width: 80,
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFF252525)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(emoji, style: const TextStyle(fontSize: 32)),
            const SizedBox(height: 6),
            Text(label, style: const TextStyle(color: Color(0xFFC9A962), fontSize: 12)),
          ],
        ),
      ),
    );
  }

  Widget _buildConfirmation() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text('👁', style: TextStyle(fontSize: 40)),
        const SizedBox(height: 16),
        Text(_responseMsg,
            style: const TextStyle(color: Colors.white, fontSize: 16),
            textAlign: TextAlign.center),
      ],
    );
  }
}
