// =============================================================================
// DISTRESS BEACON SCREEN — Emergency Support
// =============================================================================

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:url_launcher/url_launcher.dart';
import 'dart:convert';
import 'dart:async';
import '../config/app_config.dart';

// =============================================================================
// DESIGN TOKENS
// =============================================================================
class _Design {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const green = Color(0xFF00FF88);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
}

// =============================================================================
// DISTRESS BEACON SCREEN
// =============================================================================
class DistressBeaconScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final WebSocketChannel? socket;

  const DistressBeaconScreen({
    super.key,
    required this.profile,
    this.socket,
  });

  @override
  State<DistressBeaconScreen> createState() => _DistressBeaconScreenState();
}

class _DistressBeaconScreenState extends State<DistressBeaconScreen>
    with SingleTickerProviderStateMixin {
  WebSocketChannel? _ownSocket;
  StreamSubscription? _socketSubscription;
  bool _beaconActivated = false;
  bool _isActivating = false;
  String? _acknowledgmentMessage;
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    _connectOwnSocket();
    _setupPulseAnimation();
  }

  void _setupPulseAnimation() {
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    )..repeat(reverse: true);

    _pulseAnimation = Tween<double>(begin: 1.0, end: 1.2).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
  }

  void _connectOwnSocket() {
    try {
      _ownSocket = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _socketSubscription = _ownSocket!.stream.listen(
        (message) {
          try {
            final data = jsonDecode(message);
            _handleSocketMessage(data);
          } catch (e) {
            print('Error parsing socket message: $e');
          }
        },
        onError: (error) {
          if (mounted) {
            setState(() {
              _acknowledgmentMessage = 'Connection error. Please try again or use emergency resources below.';
            });
          }
        },
      );
    } catch (e) {
      if (mounted) {
        setState(() => _acknowledgmentMessage = 'Failed to connect: $e');
      }
    }
  }

  WebSocketChannel? get _activeSocket => _ownSocket;

  void _handleSocketMessage(Map<String, dynamic> data) {
    if (!mounted) return;

    switch (data['type']) {
      case 'distress_beacon_ack':
        setState(() {
          _beaconActivated = true;
          _isActivating = false;
          _acknowledgmentMessage = data['message'] as String? ??
              'Your distress signal has been received. Support is on the way.';
          _pulseController.stop();
        });
        break;

      case 'error':
        setState(() {
          _isActivating = false;
          _acknowledgmentMessage = data['message'] as String? ??
              'Failed to send distress signal. Please use emergency resources below.';
        });
        break;
    }
  }

  void _activateBeacon() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: _Design.bgElevated,
        title: const Text(
          'Are you in distress?',
          style: TextStyle(color: _Design.textPrimary, fontWeight: FontWeight.bold),
        ),
        content: const Text(
          'This will send an emergency distress signal. Support will be notified immediately.',
          style: TextStyle(color: _Design.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text(
              'Cancel',
              style: TextStyle(color: _Design.textSecondary),
            ),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.of(context).pop();
              _sendDistressSignal();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: _Design.red,
              foregroundColor: _Design.textPrimary,
            ),
            child: const Text('Yes, Activate'),
          ),
        ],
      ),
    );
  }

  void _sendDistressSignal() {
    setState(() {
      _isActivating = true;
      _beaconActivated = false;
      _acknowledgmentMessage = null;
    });

    _activeSocket?.sink.add(jsonEncode({
      'type': 'distress_beacon',
      'fibre_id': 'client_beacon',
      'severity': 'high',
      'reason': 'Client activated distress beacon',
    }));
  }

  void _cancelBeacon() {
    setState(() {
      _beaconActivated = false;
      _acknowledgmentMessage = null;
      _pulseController.repeat(reverse: true);
    });
  }

  Future<void> _call988() async {
    final uri = Uri.parse('tel:988');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    }
  }

  Future<void> _text988() async {
    final uri = Uri.parse('sms:988');
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    }
  }

  @override
  void dispose() {
    _socketSubscription?.cancel();
    _ownSocket?.sink.close();
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber,
        elevation: 0,
        title: const Text(
          'Distress Beacon',
          style: TextStyle(
            color: _Design.textPrimary,
            fontSize: 20,
            fontWeight: FontWeight.bold,
          ),
        ),
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 32),

            // Main emergency button
            Center(
              child: AnimatedBuilder(
                animation: _pulseAnimation,
                builder: (context, child) {
                  return Transform.scale(
                    scale: _beaconActivated ? 1.0 : _pulseAnimation.value,
                    child: GestureDetector(
                      onTap: _beaconActivated ? null : _activateBeacon,
                      child: Container(
                        width: 200,
                        height: 200,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: _beaconActivated
                              ? _Design.green.withOpacity(0.3)
                              : _Design.red,
                          boxShadow: [
                            BoxShadow(
                              color: (_beaconActivated ? _Design.green : _Design.red)
                                  .withOpacity(0.5),
                              blurRadius: 30,
                              spreadRadius: 10,
                            ),
                          ],
                        ),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              _beaconActivated ? Icons.check_circle : Icons.warning,
                              size: 80,
                              color: _Design.textPrimary,
                            ),
                            const SizedBox(height: 16),
                            Text(
                              _beaconActivated ? 'ACTIVATED' : 'ACTIVATE',
                              style: const TextStyle(
                                color: _Design.textPrimary,
                                fontSize: 20,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 2,
                              ),
                            ),
                            if (_isActivating) ...[
                              const SizedBox(height: 8),
                              const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(_Design.textPrimary),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),

            const SizedBox(height: 32),

            // Status message
            if (_acknowledgmentMessage != null)
              Container(
                padding: const EdgeInsets.all(16),
                margin: const EdgeInsets.only(bottom: 24),
                decoration: BoxDecoration(
                  color: _beaconActivated
                      ? _Design.green.withOpacity(0.2)
                      : _Design.red.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: _beaconActivated ? _Design.green : _Design.red,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      _beaconActivated ? Icons.check_circle : Icons.info_outline,
                      color: _beaconActivated ? _Design.green : _Design.red,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        _acknowledgmentMessage!,
                        style: TextStyle(
                          color: _beaconActivated ? _Design.green : _Design.red,
                          fontSize: 14,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

            // Cancel button (if activated)
            if (_beaconActivated)
              Padding(
                padding: const EdgeInsets.only(bottom: 24),
                child: OutlinedButton(
                  onPressed: _cancelBeacon,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: _Design.textSecondary,
                    side: const BorderSide(color: _Design.textSecondary),
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: const Text(
                    "I'm OK",
                    style: TextStyle(fontSize: 16),
                  ),
                ),
              ),

            // Crisis resources section
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: _Design.bgElevated,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _Design.goldDim),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.emergency, color: _Design.red, size: 24),
                      SizedBox(width: 8),
                      Text(
                        'Crisis Resources',
                        style: TextStyle(
                          color: _Design.textPrimary,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    '988 Suicide & Crisis Lifeline',
                    style: TextStyle(
                      color: _Design.textPrimary,
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 4),
                  const Text(
                    'Free, confidential support available 24/7',
                    style: TextStyle(
                      color: _Design.textSecondary,
                      fontSize: 14,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: _call988,
                          icon: const Icon(Icons.phone, size: 20),
                          label: const Text('Call 988'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _Design.red,
                            foregroundColor: _Design.textPrimary,
                            padding: const EdgeInsets.symmetric(vertical: 12),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _text988,
                          icon: const Icon(Icons.message, size: 20),
                          label: const Text('Text 988'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: _Design.red,
                            side: const BorderSide(color: _Design.red),
                            padding: const EdgeInsets.symmetric(vertical: 12),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  const Divider(color: _Design.goldDim),
                  const SizedBox(height: 12),
                  _buildResourceItem(
                    'Crisis Text Line',
                    'Text HOME to 741741',
                    Icons.chat_bubble_outline,
                  ),
                  const SizedBox(height: 12),
                  _buildResourceItem(
                    'National Suicide Prevention Lifeline',
                    '1-800-273-8255',
                    Icons.phone_in_talk,
                  ),
                  const SizedBox(height: 12),
                  _buildResourceItem(
                    'Emergency Services',
                    '911',
                    Icons.local_hospital,
                  ),
                ],
              ),
            ),

            const SizedBox(height: 24),

            // Safety information
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: _Design.bgChamber,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'You are not alone.',
                    style: TextStyle(
                      color: _Design.gold,
                      fontSize: 14,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  SizedBox(height: 8),
                  Text(
                    'Help is available. If you are in immediate danger, call 911 or go to your nearest emergency room.',
                    style: TextStyle(
                      color: _Design.textSecondary,
                      fontSize: 12,
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

  Widget _buildResourceItem(String title, String contact, IconData icon) {
    return Row(
      children: [
        Icon(icon, color: _Design.goldDim, size: 20),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: _Design.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                contact,
                style: const TextStyle(
                  color: _Design.textSecondary,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
