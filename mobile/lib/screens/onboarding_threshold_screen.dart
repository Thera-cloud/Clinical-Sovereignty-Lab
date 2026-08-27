import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'dart:math';
import '../config/app_config.dart';
import '../main.dart' show ClientScheduleScreen;
import '../updated_screens.dart' show NeuralInterfaceV2;

// =============================================================================
// C1: Threshold (Trial) Welcome Walkthrough
// 6-slide animated walkthrough for trial users
// =============================================================================

class OnboardingThresholdScreen extends StatefulWidget {
  final Map<String, dynamic> profileWithToken;
  final String username;
  final String password;
  final WebSocketChannel? existingSocket;

  const OnboardingThresholdScreen({
    super.key,
    required this.profileWithToken,
    required this.username,
    required this.password,
    this.existingSocket,
  });

  @override
  State<OnboardingThresholdScreen> createState() => _OnboardingThresholdScreenState();
}

class _OnboardingThresholdScreenState extends State<OnboardingThresholdScreen>
    with TickerProviderStateMixin {
  // Design tokens
  static const _bgVoid = Color(0xFF050505);
  static const _bgChamber = Color(0xFF0A0A0A);
  static const _bgElevated = Color(0xFF111111);
  static const _gold = Color(0xFFC9A962);
  static const _goldBright = Color(0xFFE8D5A3);
  static const _goldDim = Color(0xFF8B7355);
  static const _cyan = Color(0xFF4ECDC4);
  static const _purple = Color(0xFF9D4EDD);
  static const _textPrimary = Color(0xFFFFFFFF);
  static const _textSecondary = Color(0xFF888888);

  late PageController _pageController;
  WebSocketChannel? _socket;
  final List<AnimationController> _slideControllers = [];
  AnimationController? _particleController;

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    _connectWebSocket();
    for (int i = 0; i < 6; i++) {
      _slideControllers.add(AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 600),
      )..value = 0);
    }
    _slideControllers[0].forward(); // Animate first slide immediately
    _particleController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat();
  }

  void _connectWebSocket() {
    if (widget.existingSocket != null) {
      _socket = widget.existingSocket;
      return;
    }
    try {
      _socket = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _socket!.stream.listen(
        (msg) {
          try {
            final data = jsonDecode(msg);
            if (data['type'] == 'connected' || data['status'] == 'ready') {
              _socket!.sink.add(jsonEncode({
                'type': 'login_request',
                'username': widget.username,
                'password': widget.password,
              }));
            }
          } catch (_) {}
        },
        onError: (e) {
          debugPrint('[Onboarding] WS error: $e');
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('Connection error. Please go back and try again.'),
                backgroundColor: Color(0xFFEF4444),
              ),
            );
          }
        },
        onDone: () {
          _socket = null;
        },
      );
    } catch (e) {
      debugPrint('[Onboarding] WS connect error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Unable to connect. Please go back and try again.'),
            backgroundColor: Color(0xFFEF4444),
          ),
        );
      }
    }
  }

  String _computeTrialDay() {
    try {
      final createdAt = widget.profileWithToken['created_at'] ?? widget.profileWithToken['trial_start'] ?? '';
      if (createdAt.toString().isNotEmpty) {
        final start = DateTime.tryParse(createdAt.toString());
        if (start != null) {
          final day = DateTime.now().difference(start).inDays + 1;
          return 'Day ${day.clamp(1, 14)} of 14';
        }
      }
    } catch (_) {}
    return 'Day 1 of 14';
  }

  void _onPageChanged(int index) {
    for (int i = 0; i < _slideControllers.length; i++) {
      if (i == index) {
        _slideControllers[i].forward();
      }
    }
  }

  Future<void> _saveOnboardingSeenHttp(String userId) async {
    try {
      await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/users/$userId/onboarding_seen'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'user_id': userId}),
      );
    } catch (e) {
      debugPrint('[Onboarding] HTTP fallback error: $e');
    }
  }

  void _completeAndDismiss() async {
    final userId = (widget.profileWithToken['hardware_id'] ?? widget.profileWithToken['id'] ?? '').toString();
    final wsConnected = _socket != null;
    if (wsConnected) {
      try {
        _socket!.sink.add(jsonEncode({
          'type': 'set_onboarding_seen',
          'user_id': userId,
        }));
      } catch (_) {
        await _saveOnboardingSeenHttp(userId);
      }
    } else {
      await _saveOnboardingSeenHttp(userId);
    }
    final profile = {...widget.profileWithToken, "token": widget.profileWithToken['token'] ?? ''};
    final plan = (widget.profileWithToken['subscription_plan'] ?? '').toString().toUpperCase();
    final canAccessNate = widget.profileWithToken['can_access_nate'] ?? true;
    Widget nextScreen;
    if (plan == 'COACH_ONLY' || canAccessNate == false) {
      nextScreen = ClientScheduleScreen(currentUserProfile: profile, username: widget.username, password: widget.password);
    } else {
      nextScreen = NeuralInterfaceV2(currentUserProfile: profile, username: widget.username, password: widget.password);
    }
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => nextScreen),
      (route) => false,
    );
  }

  @override
  void dispose() {
    for (final c in _slideControllers) {
      c.dispose();
    }
    _particleController?.dispose();
    _pageController.dispose();
    if (widget.existingSocket == null) {
      _socket?.sink.close();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgVoid,
      body: SafeArea(
        child: Stack(
          children: [
            PageView(
              controller: _pageController,
              onPageChanged: _onPageChanged,
              children: [
                _buildSlide1(),
                _buildSlide2(),
                _buildSlide3(),
                _buildSlide4(),
                _buildSlide5(),
                _buildSlide6(),
              ],
            ),
            // Skip button
            Positioned(
              top: 8,
              right: 16,
              child: TextButton(
                onPressed: _completeAndDismiss,
                child: Text('Skip', style: TextStyle(color: _goldDim, fontSize: 14, fontFamily: 'DM Sans')),
              ),
            ),
            // Dot indicator
            Positioned(
              left: 0,
              right: 0,
              bottom: 32,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(6, (i) {
                  return AnimatedBuilder(
                    animation: _pageController,
                    builder: (_, __) {
                      final page = _pageController.hasClients ? _pageController.page ?? 0 : 0;
                      final active = (page - i).abs() < 0.5;
                      return Container(
                        margin: const EdgeInsets.symmetric(horizontal: 4),
                        width: active ? 12 : 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: active ? _gold : _goldDim.withOpacity(0.4),
                          borderRadius: BorderRadius.circular(4),
                        ),
                      );
                    },
                  );
                }),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSlide1() {
    return _SlideWrapper(
      controller: _slideControllers[0],
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Gold particle background (simplified as gradient overlay)
          AnimatedBuilder(
            animation: _particleController!,
            builder: (_, __) {
              return CustomPaint(
                painter: _GoldParticlePainter(_particleController!.value),
                size: const Size(200, 200),
              );
            },
          ),
          const SizedBox(height: 24),
          Icon(Icons.shield_outlined, size: 80, color: _gold),
          const SizedBox(height: 32),
          Text(
            'Welcome to the Sanctuary',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _gold,
              fontFamily: 'Cormorant Garamond',
              fontSize: 28,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 20),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              "You've stepped into something rare — a space where your emotional truth is protected, explored, and honored.",
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _textSecondary,
                fontFamily: 'DM Sans',
                fontSize: 16,
                height: 1.6,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSlide2() {
    return _SlideWrapper(
      controller: _slideControllers[1],
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _PulsingCyanOrb(),
          const SizedBox(height: 32),
          Text(
            'Meet Little Nate',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _gold,
              fontFamily: 'Cormorant Garamond',
              fontSize: 28,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 20),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              'Your AI companion for wellness and growth. Nate listens without judgment, remembers what matters, and helps you discover patterns you might miss.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _textSecondary,
                fontFamily: 'DM Sans',
                fontSize: 16,
                height: 1.6,
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            'Available 24/7 during your trial',
            style: TextStyle(
              color: _cyan,
              fontFamily: 'DM Sans',
              fontSize: 14,
              fontStyle: FontStyle.italic,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSlide3() {
    return _SlideWrapper(
      controller: _slideControllers[2],
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Week 1 vs Week 2 visual
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _WeekPhase(isBright: true, label: 'Week 1'),
                const SizedBox(width: 24),
                _WeekPhase(isBright: false, label: 'Week 2'),
              ],
            ),
            const SizedBox(height: 32),
            Text(
              'Your Trial Structure',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _gold,
                fontFamily: 'Cormorant Garamond',
                fontSize: 28,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              'Full access for 7 days — 10,000 AI tokens, text conversations with Little Nate. Experience the Sanctuary before choosing your plan.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _textSecondary,
                fontFamily: 'DM Sans',
                fontSize: 16,
                height: 1.6,
              ),
            ),
            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              decoration: BoxDecoration(
                color: _bgElevated,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _goldDim),
              ),
              child: Text(
                _computeTrialDay(),
                style: TextStyle(color: _gold, fontFamily: 'DM Sans', fontSize: 14),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSlide4() {
    return _SlideWrapper(
      controller: _slideControllers[3],
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _PaperclipAnimation(),
          const SizedBox(height: 32),
          Text(
            'Share Files with Nate',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _gold,
              fontFamily: 'Cormorant Garamond',
              fontSize: 28,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 20),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              'Upload documents, images, and notes directly in chat. Nate reads and understands your files to provide deeper insights.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _textSecondary,
                fontFamily: 'DM Sans',
                fontSize: 16,
                height: 1.6,
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            'Trial uploads are available for 24 hours',
            style: TextStyle(
              color: _goldDim,
              fontFamily: 'DM Sans',
              fontSize: 13,
              fontStyle: FontStyle.italic,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSlide5() {
    return _SlideWrapper(
      controller: _slideControllers[4],
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _FamilyIconAnimation(),
            const SizedBox(height: 32),
            Text(
              'Bring Your Family',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _gold,
                fontFamily: 'Cormorant Garamond',
                fontSize: 28,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              'When you upgrade: Your spouse joins FREE. Your first child under 12 joins FREE. Additional members start at just \$30/mo.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _textSecondary,
                fontFamily: 'DM Sans',
                fontSize: 16,
                height: 1.6,
              ),
            ),
            const SizedBox(height: 24),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              alignment: WrapAlignment.center,
              children: [
                _PricingPill(label: 'Spouse: FREE'),
                _PricingPill(label: '1st child <12: FREE'),
                _PricingPill(label: 'Additional: \$30/mo'),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSlide6() {
    return _SlideWrapper(
      controller: _slideControllers[5],
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            "You're Ready",
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _gold,
              fontFamily: 'Cormorant Garamond',
              fontSize: 28,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 20),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              'Start talking to Nate. Your sanctuary awaits.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _textSecondary,
                fontFamily: 'DM Sans',
                fontSize: 16,
                height: 1.6,
              ),
            ),
          ),
          const SizedBox(height: 40),
          _AnimatedGoldButton(
            label: 'Begin',
            onPressed: _completeAndDismiss,
          ),
        ],
      ),
    );
  }
}

// --- Helper widgets ---

class _SlideWrapper extends StatelessWidget {
  final AnimationController controller;
  final Widget child;

  const _SlideWrapper({required this.controller, required this.child});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (_, child) {
        return Opacity(
          opacity: 0.3 + (controller.value * 0.7),
          child: Transform.scale(
            scale: 0.9 + (controller.value * 0.1),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

class _GoldParticlePainter extends CustomPainter {
  final double value;

  _GoldParticlePainter(this.value);

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = const Color(0xFFC9A962).withOpacity(0.15);
    final random = Random(42);
    for (int i = 0; i < 30; i++) {
      final x = (random.nextDouble() * size.width) + (value * 20) % size.width;
      final y = (random.nextDouble() * size.height) + (value * 15) % size.height;
      canvas.drawCircle(Offset(x, y), 1.5, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _GoldParticlePainter old) => old.value != value;
}

class _PulsingCyanOrb extends StatefulWidget {
  @override
  State<_PulsingCyanOrb> createState() => _PulsingCyanOrbState();
}

class _PulsingCyanOrbState extends State<_PulsingCyanOrb>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (_, __) {
        final s = 1.0 + (_controller.value * 0.15);
        return Transform.scale(
          scale: s,
          child: Container(
            width: 100,
            height: 100,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: const RadialGradient(
                colors: [Color(0xFF4ECDC4), Color(0xFF001A33)],
                stops: [0.3, 1.0],
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF4ECDC4).withOpacity(0.5),
                  blurRadius: 30,
                  spreadRadius: 5,
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _WeekPhase extends StatelessWidget {
  final bool isBright;
  final String label;

  const _WeekPhase({required this.isBright, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
      decoration: BoxDecoration(
        color: isBright ? const Color(0xFF111111) : const Color(0xFF0A0A0A),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isBright ? const Color(0xFFC9A962) : const Color(0xFF8B7355),
          width: isBright ? 2 : 1,
        ),
      ),
      child: Column(
        children: [
          Icon(
            Icons.calendar_today,
            color: isBright ? const Color(0xFFE8D5A3) : const Color(0xFF8B7355),
            size: 32,
          ),
          const SizedBox(height: 8),
          Text(
            label,
            style: TextStyle(
              color: isBright ? const Color(0xFFE8D5A3) : const Color(0xFF8B7355),
              fontFamily: 'DM Sans',
              fontSize: 14,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _PaperclipAnimation extends StatefulWidget {
  @override
  State<_PaperclipAnimation> createState() => _PaperclipAnimationState();
}

class _PaperclipAnimationState extends State<_PaperclipAnimation>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (_, __) {
        return Transform.rotate(
          angle: -0.1 + (_controller.value * 0.2),
          child: const Icon(Icons.attach_file, size: 80, color: Color(0xFFC9A962)),
        );
      },
    );
  }
}

class _FamilyIconAnimation extends StatefulWidget {
  @override
  State<_FamilyIconAnimation> createState() => _FamilyIconAnimationState();
}

class _FamilyIconAnimationState extends State<_FamilyIconAnimation>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (_, __) {
        final offset = _controller.value * 4;
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Transform.translate(offset: Offset(-offset, 0), child: _buildPerson()),
            Transform.translate(offset: Offset(0, -offset), child: _buildPerson()),
            Transform.translate(offset: Offset(offset, 0), child: _buildPerson()),
          ],
        );
      },
    );
  }

  Widget _buildPerson() => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          shape: BoxShape.circle,
          border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.5)),
        ),
        child: const Icon(Icons.person, color: Color(0xFFC9A962), size: 32),
      );
}

class _PricingPill extends StatelessWidget {
  final String label;

  const _PricingPill({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.6)),
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: Color(0xFFC9A962),
          fontFamily: 'DM Sans',
          fontSize: 13,
        ),
      ),
    );
  }
}

class _AnimatedGoldButton extends StatefulWidget {
  final String label;
  final VoidCallback onPressed;

  const _AnimatedGoldButton({required this.label, required this.onPressed});

  @override
  State<_AnimatedGoldButton> createState() => _AnimatedGoldButtonState();
}

class _AnimatedGoldButtonState extends State<_AnimatedGoldButton>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (_, __) {
        return GestureDetector(
          onTap: widget.onPressed,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 18),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  const Color(0xFFC9A962),
                  const Color(0xFFE8D5A3),
                  const Color(0xFFC9A962),
                ],
                stops: [
                  0.0,
                  0.3 + (_controller.value * 0.4),
                  1.0,
                ],
              ),
              borderRadius: BorderRadius.circular(12),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFFC9A962).withOpacity(0.4),
                  blurRadius: 16,
                  spreadRadius: 2,
                ),
              ],
            ),
            child: Text(
              widget.label,
              style: const TextStyle(
                color: Color(0xFF050505),
                fontFamily: 'Cormorant Garamond',
                fontSize: 20,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        );
      },
    );
  }
}
