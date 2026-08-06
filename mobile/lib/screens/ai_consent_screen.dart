import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class _D {
  static const bgVoid = Color(0xFF050505);
  static const bgCard = Color(0xFF111111);
  static const bgElevated = Color(0xFF1A1A1A);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const border = Color(0xFF252525);
}

/// Screen shown once before a client can use chat with Little Nate.
/// Requires explicit consent to AI data processing.
class AiConsentScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String username;
  final String password;
  final Widget Function() buildNextScreen;

  const AiConsentScreen({
    super.key,
    required this.profile,
    required this.username,
    required this.password,
    required this.buildNextScreen,
  });

  @override
  State<AiConsentScreen> createState() => _AiConsentScreenState();
}

class _AiConsentScreenState extends State<AiConsentScreen> {
  bool _agreed = false;
  bool _submitting = false;

  Future<void> _grantConsent() async {
    if (_submitting) return;
    setState(() => _submitting = true);

    final now = DateTime.now().toUtc().toIso8601String();

    // Store locally
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('ai_consent_granted_at', now);

    // Sync to backend
    try {
      final token = widget.profile['token'] ?? '';
      await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/client/ai-consent'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({'ai_consent_granted_at': now}),
      ).timeout(const Duration(seconds: 10));
    } catch (_) {
      // Local consent is sufficient — backend will sync on next opportunity
    }

    widget.profile['ai_consent_granted_at'] = now;

    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => widget.buildNextScreen()),
    );
  }

  void _decline() {
    final p = widget.profile;
    final u = widget.username;
    final pw = widget.password;
    final next = widget.buildNextScreen;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => _AiConsentDeclinedScreen(
        profile: p,
        username: u,
        password: pw,
        buildNextScreen: next,
      )),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 16),
                    Center(
                      child: Container(
                        width: 56, height: 56,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          border: Border.all(color: _D.gold.withOpacity(0.4), width: 1.5),
                          color: _D.bgElevated,
                        ),
                        child: const Icon(Icons.psychology_alt, color: _D.gold, size: 28),
                      ),
                    ),
                    const SizedBox(height: 24),
                    const Center(
                      child: Text(
                        'How Little Nate Works',
                        style: TextStyle(
                          color: _D.goldBright,
                          fontSize: 24,
                          fontWeight: FontWeight.w600,
                          fontFamily: 'Cormorant Garamond',
                          letterSpacing: 0.5,
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    const Text(
                      'Little Nate is an AI therapeutic companion. To provide personalized '
                      'responses, your conversations are processed by secure AI services.',
                      style: TextStyle(color: _D.textPrimary, fontSize: 15, height: 1.6),
                    ),
                    const SizedBox(height: 28),

                    _sectionCard(
                      icon: Icons.chat_bubble_outline,
                      title: 'What is shared',
                      body: 'Your text messages and voice audio during conversations',
                    ),
                    const SizedBox(height: 14),
                    _sectionCard(
                      icon: Icons.cloud_outlined,
                      title: 'Who processes it',
                      body: 'xAI (Grok) and Microsoft Azure OpenAI \u2014 our AI inference providers',
                    ),
                    const SizedBox(height: 14),
                    _sectionCard(
                      icon: Icons.lock_outline,
                      title: 'How your data is protected',
                      body: null,
                      bullets: const [
                        'Data is encrypted in transit (TLS 1.2+); selected credentials use application-layer encryption',
                        'Conversation transcripts are stored in our database (hosting-provider disk encryption — not per-message AES-256)',
                        'Your conversations are not used to train AI providers\' general models',
                        'Message content you type (including identifiers you include) is sent to AI providers on the primary chat path',
                      ],
                    ),
                    const SizedBox(height: 14),
                    _sectionCard(
                      icon: Icons.verified_user_outlined,
                      title: 'Your rights',
                      body: null,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'You can delete all your data at any time from Settings.',
                            style: TextStyle(color: _D.textSecondary, fontSize: 13, height: 1.5),
                          ),
                          const SizedBox(height: 4),
                          GestureDetector(
                            onTap: () => launchUrl(
                              Uri.parse('https://sovereignsanctuary.net/privacy'),
                              mode: LaunchMode.externalApplication,
                            ),
                            child: const Text(
                              'Review our full Privacy Policy',
                              style: TextStyle(
                                color: _D.cyan,
                                fontSize: 13,
                                decoration: TextDecoration.underline,
                                decorationColor: _D.cyan,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 32),
                  ],
                ),
              ),
            ),

            Container(
              padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
              decoration: BoxDecoration(
                color: _D.bgCard,
                border: Border(top: BorderSide(color: _D.border, width: 0.5)),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  GestureDetector(
                    onTap: () => setState(() => _agreed = !_agreed),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          width: 22, height: 22,
                          margin: const EdgeInsets.only(top: 1),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(
                              color: _agreed ? _D.gold : _D.goldDim,
                              width: 1.5,
                            ),
                            color: _agreed ? _D.gold.withOpacity(0.15) : Colors.transparent,
                          ),
                          child: _agreed
                              ? const Icon(Icons.check, size: 16, color: _D.gold)
                              : null,
                        ),
                        const SizedBox(width: 12),
                        const Expanded(
                          child: Text(
                            'I understand and consent to my conversations being processed '
                            'by AI services as described above',
                            style: TextStyle(
                              color: _D.textPrimary,
                              fontSize: 13,
                              height: 1.5,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    height: 48,
                    child: ElevatedButton(
                      onPressed: _agreed && !_submitting ? _grantConsent : null,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _agreed ? _D.gold : _D.goldDim.withOpacity(0.3),
                        disabledBackgroundColor: _D.goldDim.withOpacity(0.2),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        elevation: 0,
                      ),
                      child: _submitting
                          ? const SizedBox(
                              width: 20, height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                            )
                          : Text(
                              'Continue',
                              style: TextStyle(
                                color: _agreed ? Colors.black : _D.textSecondary,
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                                fontFamily: 'Cormorant Garabond',
                              ),
                            ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionCard({
    required IconData icon,
    required String title,
    String? body,
    List<String>? bullets,
    Widget? child,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _D.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _D.border, width: 0.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: _D.gold, size: 18),
              const SizedBox(width: 10),
              Text(
                title,
                style: const TextStyle(
                  color: _D.goldBright,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  fontFamily: 'Cormorant Garamond',
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (body != null)
            Text(body, style: const TextStyle(color: _D.textSecondary, fontSize: 13, height: 1.5)),
          if (bullets != null)
            ...bullets.map((b) => Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 5, height: 5,
                    margin: const EdgeInsets.only(top: 6, right: 10),
                    decoration: const BoxDecoration(shape: BoxShape.circle, color: _D.goldDim),
                  ),
                  Expanded(
                    child: Text(b, style: const TextStyle(color: _D.textSecondary, fontSize: 13, height: 1.5)),
                  ),
                ],
              ),
            )),
          if (child != null) child,
        ],
      ),
    );
  }
}

/// Shown when the user declines AI consent.
class _AiConsentDeclinedScreen extends StatelessWidget {
  final Map<String, dynamic> profile;
  final String username;
  final String password;
  final Widget Function() buildNextScreen;

  const _AiConsentDeclinedScreen({
    required this.profile,
    required this.username,
    required this.password,
    required this.buildNextScreen,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 64, height: 64,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _D.bgElevated,
                  border: Border.all(color: _D.border),
                ),
                child: const Icon(Icons.info_outline, color: _D.goldDim, size: 32),
              ),
              const SizedBox(height: 24),
              const Text(
                'AI Processing Required',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: _D.goldBright,
                  fontSize: 22,
                  fontWeight: FontWeight.w600,
                  fontFamily: 'Cormorant Garamond',
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'Little Nate requires AI processing to provide therapeutic responses. '
                'Without consent, the chat feature cannot be used.\n\n'
                'You can still access scheduling, settings, and other non-AI features.',
                textAlign: TextAlign.center,
                style: TextStyle(color: _D.textSecondary, fontSize: 14, height: 1.6),
              ),
              const SizedBox(height: 32),
              SizedBox(
                width: double.infinity,
                height: 48,
                child: ElevatedButton(
                  onPressed: () {
                    Navigator.pushReplacement(
                      context,
                      MaterialPageRoute(builder: (_) => AiConsentScreen(
                        profile: profile,
                        username: username,
                        password: password,
                        buildNextScreen: buildNextScreen,
                      )),
                    );
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _D.gold,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    elevation: 0,
                  ),
                  child: const Text(
                    'Go Back & Review',
                    style: TextStyle(color: Colors.black, fontSize: 15, fontWeight: FontWeight.w600),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text(
                  'Continue Without Chat',
                  style: TextStyle(color: _D.textSecondary, fontSize: 13),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
