import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import '../config/app_config.dart';
import '../main.dart' show ClientScheduleScreen;
import '../updated_screens.dart' show NeuralInterfaceV2;

// =============================================================================
// C2: Inner Chamber / Sovereign Circle Welcome Walkthrough
// 8-slide walkthrough for paid users (STANDARD or TOP_TIER)
// =============================================================================

class OnboardingPaidScreen extends StatefulWidget {
  final Map<String, dynamic> profileWithToken;
  final String username;
  final String password;
  final String tier; // "STANDARD" or "TOP_TIER"
  final bool isFoundingMember;
  final WebSocketChannel? existingSocket;

  const OnboardingPaidScreen({
    super.key,
    required this.profileWithToken,
    required this.username,
    required this.password,
    required this.tier,
    this.isFoundingMember = false,
    this.existingSocket,
  });

  @override
  State<OnboardingPaidScreen> createState() => _OnboardingPaidScreenState();
}

class _OnboardingPaidScreenState extends State<OnboardingPaidScreen>
    with TickerProviderStateMixin {
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
  int get _totalSlides => widget.tier.toUpperCase().contains('TOP') ? 8 : 7;
  final List<AnimationController> _slideControllers = [];

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    _connectWebSocket();
    for (int i = 0; i < 8; i++) {
      _slideControllers.add(AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 600),
      )..value = 0);
    }
    _slideControllers[0].forward();
  }

  void _connectWebSocket() {
    if (widget.existingSocket != null) {
      _socket = widget.existingSocket;
      return;
    }
    try {
      _socket = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _socket!.stream.listen(
        (_) {},
        onError: (e) => debugPrint('[Onboarding] WS error: $e'),
        onDone: () => _socket = null,
      );
      _socket!.sink.add(jsonEncode({
        'type': 'login_request',
        'username': widget.username,
        'password': widget.password,
      }));
    } catch (e) {
      debugPrint('[Onboarding] WS connect error: $e');
    }
  }

  void _onPageChanged(int index) {
    for (int i = 0; i < _slideControllers.length; i++) {
      if (i == index) {
        _slideControllers[i].forward();
      }
    }
  }

  void _completeAndDismiss() async {
    final userId = (widget.profileWithToken['hardware_id'] ?? widget.profileWithToken['id'] ?? '').toString();
    final wsConnected = _socket != null;
    if (wsConnected) {
      try {
        _socket!.sink.add(jsonEncode({
          'type': 'set_paid_onboarding_seen',
          'user_id': userId,
        }));
      } catch (_) {
        await _savePaidOnboardingSeenHttp(userId);
      }
    } else {
      await _savePaidOnboardingSeenHttp(userId);
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

  Future<void> _savePaidOnboardingSeenHttp(String userId) async {
    try {
      final apiBaseUrl = AppConfig.apiBaseUrl;
      await http.post(
        Uri.parse('$apiBaseUrl/api/v1/user/paid-onboarding-seen'),
        headers: {'X-User-Id': userId, 'Content-Type': 'application/json'},
        body: jsonEncode({'seen': true}),
      ).timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  String get _tierName => widget.tier.toUpperCase().contains('TOP') ? 'Sovereign Circle' : 'Inner Chamber';
  bool get _isSovereignCircle => widget.tier.toUpperCase().contains('TOP');

  @override
  void dispose() {
    for (final c in _slideControllers) {
      c.dispose();
    }
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
              children: _buildSlides(),
            ),
            Positioned(
              top: 8,
              right: 16,
              child: TextButton(
                onPressed: _completeAndDismiss,
                child: Text('Skip', style: TextStyle(color: _goldDim, fontSize: 14, fontFamily: 'DM Sans')),
              ),
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 32,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(_totalSlides, (i) {
                  return AnimatedBuilder(
                    animation: _pageController,
                    builder: (_, __) {
                      final page = _pageController.hasClients ? _pageController.page ?? 0 : 0;
                      final active = (page - i).abs() < 0.5;
                      return Container(
                        margin: const EdgeInsets.symmetric(horizontal: 3),
                        width: active ? 10 : 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: active ? _gold : _goldDim.withOpacity(0.4),
                          borderRadius: BorderRadius.circular(3),
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

  List<Widget> _buildSlides() {
    final slides = <Widget>[
      _buildSlide1(),
      _buildSlide2(),
      _buildSlide3(),
      _buildSlide4(),
      _buildSlide5(),
      _buildSlide6(),
    ];
    if (_isSovereignCircle) {
      slides.add(_buildSlide7());
    }
    slides.add(_buildSlide8());
    return slides;
  }

  Widget _wrapSlide(int index, Widget child) {
    return _PaidSlideWrapper(
      controller: _slideControllers[index],
      child: child,
    );
  }

  Widget _buildSlide1() {
    return _wrapSlide(0, Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _KeyTurnAnimation(),
        if (widget.isFoundingMember) ...[
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: _goldDim.withOpacity(0.2),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: _gold),
            ),
            child: Text(
              'Founding Member',
              style: TextStyle(color: _gold, fontFamily: 'DM Sans', fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ),
        ],
        const SizedBox(height: 32),
        Text(
          'Your Sanctuary is Unlocked',
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
            'Welcome to $_tierName. Your full suite of tools is ready.',
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
    ));
  }

  Widget _buildSlide2() {
    final storage = _isSovereignCircle ? '50 GB' : '1 GB';
    return _wrapSlide(1, Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _VaultDoorAnimation(),
        const SizedBox(height: 32),
        Text(
          'Your Sovereign Vault',
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
            'Store conversations, uploads, reports, and memories. Everything organized automatically.',
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
          '$storage included',
          style: TextStyle(color: _cyan, fontFamily: 'DM Sans', fontSize: 14),
        ),
      ],
    ));
  }

  Widget _buildSlide3() {
    return _wrapSlide(2, Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _DocumentSparkleAnimation(),
        const SizedBox(height: 32),
        Text(
          'Files in Your Conversations',
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
            'Upload PDFs, documents, and images. Nate reads them and weaves their content into your sessions.',
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
          'Preview windows let you reference files without leaving the conversation',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: _goldDim,
            fontFamily: 'DM Sans',
            fontSize: 13,
            fontStyle: FontStyle.italic,
          ),
        ),
      ],
    ));
  }

  Widget _buildSlide4() {
    return _wrapSlide(3, Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _CrystalRotationAnimation(),
        const SizedBox(height: 32),
        Text(
          'Bring Your History',
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
            'Import conversations from ChatGPT, Claude, or other AI platforms. Nate synthesizes your history into a Transfer Crystal — a deep profile that helps sessions start where you left off.',
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
    ));
  }

  Widget _buildSlide5() {
    return _wrapSlide(4, SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _FamilyGroupAnimation(),
          const SizedBox(height: 32),
          Text(
            'Your Family Benefits',
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
            'Spouse: Always free. First child under 12: Free. Additional members: \$75, \$60, \$45, \$30 — by join order.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _textSecondary,
              fontFamily: 'DM Sans',
              fontSize: 16,
              height: 1.6,
            ),
          ),
        ],
      ),
    ));
  }

  Widget _buildSlide6() {
    final reports = _isSovereignCircle ? '8 reports/mo' : '2 reports/mo';
    final forecasts = _isSovereignCircle ? 'unlimited forecasts' : '4 forecasts/mo';
    return _wrapSlide(5, Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _ChartAnimation(),
        const SizedBox(height: 32),
        Text(
          'Clinical Intelligence',
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
            'Nevedal Reports map your emotional patterns with quantum precision. Foresight Forecasts predict future emotional trajectories.',
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
          '$reports, $forecasts',
          style: TextStyle(color: _purple, fontFamily: 'DM Sans', fontSize: 14),
        ),
      ],
    ));
  }

  Widget _buildSlide7() {
    return _wrapSlide(6, SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _CrownAnimation(),
          const SizedBox(height: 32),
          Text(
            'Sovereign Circle Exclusives',
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
            'Pattern Engine, Me2Me Avatar, Archivist Chapters, Legacy Letters, Voice-Over-Image, Realtime Voice with Nate, and unlimited everything.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _textSecondary,
              fontFamily: 'DM Sans',
              fontSize: 16,
              height: 1.6,
            ),
          ),
        ],
      ),
    ));
  }

  Widget _buildSlide8() {
    final idx = _isSovereignCircle ? 7 : 6;
    return _wrapSlide(idx, Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(
          'Your Journey Continues',
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
            'Explore your vault, talk to Nate, or browse your tools.',
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
        _ShimmerGoldButton(label: "Meet Little Nate", onPressed: _startIntake),
      ],
    ));
  }

  void _startIntake() {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => _IntakeConversationScreen(
        profileWithToken: widget.profileWithToken,
        onComplete: () {
          Navigator.of(context).pop();
          _completeAndDismiss();
        },
      ),
    ));
  }
}

// --- Intake Conversation Screen (10-turn Identity Forge) ---

class _IntakeConversationScreen extends StatefulWidget {
  final Map<String, dynamic> profileWithToken;
  final VoidCallback onComplete;
  const _IntakeConversationScreen({required this.profileWithToken, required this.onComplete});
  @override State<_IntakeConversationScreen> createState() => _IntakeCSState();
}

class _IntakeCSState extends State<_IntakeConversationScreen> {
  static const _bg = Color(0xFF050505), _cy = Color(0xFF4ECDC4), _gd = Color(0xFFC9A962), _ts = Color(0xFF888888);
  final _ctrl = TextEditingController();
  final _scr = ScrollController();
  final List<Map<String, String>> _msgs = [];
  List<Map<String, dynamic>> _hist = [];
  int _turn = 1; bool _busy = false, _done = false;
  String get _uid => (widget.profileWithToken['hardware_id'] ?? widget.profileWithToken['id'] ?? '').toString();
  String get _name => (widget.profileWithToken['name'] ?? widget.profileWithToken['username'] ?? 'friend').toString();
  String get _tok => (widget.profileWithToken['token'] ?? '').toString();
  @override void initState() { super.initState();
    final p = "Hi $_name. I'm Little Nate. Before we begin, I want to take a few minutes to get to know you — not through a form, but through a conversation. That's how I work. Is that okay?";
    _msgs.add({'role': 'assistant', 'text': p}); _hist.add({'role': 'assistant', 'content': p});
  }
  Future<void> _send() async {
    final t = _ctrl.text.trim(); if (t.isEmpty || _busy || _done) return;
    setState(() { _msgs.add({'role': 'user', 'text': t}); _busy = true; }); _ctrl.clear(); _down();
    try {
      final r = await http.post(Uri.parse('${AppConfig.apiBaseUrl}/api/sse/intake/turn'),
        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer $_tok'},
        body: jsonEncode({'user_id': _uid, 'user_name': _name, 'turn': _turn, 'user_message': t, 'conversation_history': _hist}),
      ).timeout(const Duration(seconds: 30));
      if (r.statusCode >= 200 && r.statusCode < 300) {
        final d = jsonDecode(r.body);
        setState(() { _turn = d['turn'] ?? _turn + 1; _msgs.add({'role': 'assistant', 'text': d['nate_message'] ?? ''});
          _hist = List<Map<String, dynamic>>.from(d['conversation_history'] ?? _hist); _done = d['complete'] == true; });
        _down(); if (_done) { await Future.delayed(const Duration(seconds: 3)); if (mounted) widget.onComplete(); }
      }
    } catch (e) { debugPrint('[Intake] $e'); }
    if (mounted) setState(() => _busy = false);
  }
  void _down() => Future.delayed(const Duration(milliseconds: 100), () {
    if (_scr.hasClients) _scr.animateTo(_scr.position.maxScrollExtent, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
  });
  @override void dispose() { _ctrl.dispose(); _scr.dispose(); super.dispose(); }
  @override Widget build(BuildContext context) => Scaffold(backgroundColor: _bg,
    appBar: AppBar(backgroundColor: _bg, elevation: 0,
      title: Text('Getting to know you — $_turn/10', style: const TextStyle(color: _ts, fontSize: 14, fontFamily: 'DM Sans')),
      leading: IconButton(icon: const Icon(Icons.close, color: _ts), onPressed: () => Navigator.pop(context))),
    body: Column(children: [
      LinearProgressIndicator(value: _turn / 10, backgroundColor: Colors.white10, valueColor: const AlwaysStoppedAnimation(_cy), minHeight: 2),
      Expanded(child: ListView.builder(controller: _scr, padding: const EdgeInsets.all(16), itemCount: _msgs.length, itemBuilder: (_, i) {
        final m = _msgs[i]; final n = m['role'] == 'assistant';
        return Padding(padding: const EdgeInsets.only(bottom: 12), child: Row(crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: n ? MainAxisAlignment.start : MainAxisAlignment.end, children: [
            if (n) Container(width: 32, height: 32, margin: const EdgeInsets.only(right: 8),
              decoration: const BoxDecoration(shape: BoxShape.circle, color: _cy),
              child: const Center(child: Text('N', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14)))),
            Flexible(child: Container(padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: n ? const Color(0xFF111111) : _gd.withOpacity(0.15), borderRadius: BorderRadius.circular(12)),
              child: Text(m['text'] ?? '', style: TextStyle(color: n ? Colors.white : _gd, fontSize: 15, fontFamily: 'DM Sans', height: 1.5)))),
        ]));
      })),
      if (!_done) Container(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        decoration: const BoxDecoration(color: Color(0xFF0A0A0A), border: Border(top: BorderSide(color: Color(0xFF222222)))),
        child: Row(children: [
          Expanded(child: TextField(controller: _ctrl, style: const TextStyle(color: Colors.white, fontSize: 15), maxLines: 3, minLines: 1,
            decoration: InputDecoration(hintText: 'Share with Nate...', hintStyle: TextStyle(color: _ts.withOpacity(0.5)),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(20), borderSide: BorderSide.none),
              filled: true, fillColor: const Color(0xFF111111), contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10)),
            onSubmitted: (_) => _send())),
          const SizedBox(width: 8),
          IconButton(icon: Icon(_busy ? Icons.hourglass_top : Icons.send, color: _cy), onPressed: _busy ? null : _send),
        ])),
    ]));
}

// --- Helper widgets ---

class _PaidSlideWrapper extends StatelessWidget {
  final AnimationController controller;
  final Widget child;

  const _PaidSlideWrapper({required this.controller, required this.child});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (_, child) {
        return Opacity(
          opacity: 0.3 + (controller.value * 0.7),
          child: Transform.translate(
            offset: Offset(20 * (1 - controller.value), 0),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

class _KeyTurnAnimation extends StatefulWidget {
  @override
  State<_KeyTurnAnimation> createState() => _KeyTurnAnimationState();
}

class _KeyTurnAnimationState extends State<_KeyTurnAnimation>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
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
          angle: -0.2 + (_controller.value * 0.4),
          child: const Icon(Icons.key, size: 80, color: Color(0xFFC9A962)),
        );
      },
    );
  }
}

class _VaultDoorAnimation extends StatefulWidget {
  @override
  State<_VaultDoorAnimation> createState() => _VaultDoorAnimationState();
}

class _VaultDoorAnimationState extends State<_VaultDoorAnimation>
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
        return Transform.scale(
          scale: 0.9 + (_controller.value * 0.1),
          child: Opacity(
            opacity: 0.7 + (_controller.value * 0.3),
            child: const Icon(Icons.lock_open, size: 80, color: Color(0xFFC9A962)),
          ),
        );
      },
    );
  }
}

class _DocumentSparkleAnimation extends StatefulWidget {
  @override
  State<_DocumentSparkleAnimation> createState() => _DocumentSparkleAnimationState();
}

class _DocumentSparkleAnimationState extends State<_DocumentSparkleAnimation>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
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
        return Stack(
          alignment: Alignment.center,
          children: [
            const Icon(Icons.description, size: 80, color: Color(0xFFC9A962)),
            Positioned(
              top: 10,
              right: 20,
              child: Opacity(
                opacity: 0.4 + (_controller.value * 0.6),
                child: const Icon(Icons.auto_awesome, size: 24, color: Color(0xFFE8D5A3)),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _CrystalRotationAnimation extends StatefulWidget {
  @override
  State<_CrystalRotationAnimation> createState() => _CrystalRotationAnimationState();
}

class _CrystalRotationAnimationState extends State<_CrystalRotationAnimation>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
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
        return Transform.rotate(
          angle: _controller.value * 2 * 3.14159,
          child: const Icon(Icons.diamond, size: 80, color: Color(0xFF9D4EDD)),
        );
      },
    );
  }
}

class _FamilyGroupAnimation extends StatefulWidget {
  @override
  State<_FamilyGroupAnimation> createState() => _FamilyGroupAnimationState();
}

class _FamilyGroupAnimationState extends State<_FamilyGroupAnimation>
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
            Transform.translate(offset: Offset(-offset, 0), child: _person()),
            Transform.translate(offset: Offset(0, -offset), child: _person()),
            Transform.translate(offset: Offset(offset, 0), child: _person()),
          ],
        );
      },
    );
  }

  Widget _person() => const Icon(Icons.family_restroom, size: 64, color: Color(0xFFC9A962));
}

class _ChartAnimation extends StatefulWidget {
  @override
  State<_ChartAnimation> createState() => _ChartAnimationState();
}

class _ChartAnimationState extends State<_ChartAnimation>
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
        return Opacity(
          opacity: 0.5 + (_controller.value * 0.5),
          child: const Icon(Icons.show_chart, size: 80, color: Color(0xFF9D4EDD)),
        );
      },
    );
  }
}

class _CrownAnimation extends StatefulWidget {
  @override
  State<_CrownAnimation> createState() => _CrownAnimationState();
}

class _CrownAnimationState extends State<_CrownAnimation>
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
        return Transform.scale(
          scale: 1.0 + (_controller.value * 0.15),
          child: const Icon(Icons.workspace_premium, size: 80, color: Color(0xFFC9A962)),
        );
      },
    );
  }
}

class _ShimmerGoldButton extends StatefulWidget {
  final String label;
  final VoidCallback onPressed;

  const _ShimmerGoldButton({required this.label, required this.onPressed});

  @override
  State<_ShimmerGoldButton> createState() => _ShimmerGoldButtonState();
}

class _ShimmerGoldButtonState extends State<_ShimmerGoldButton>
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
