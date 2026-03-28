// LITTLE NATE — Shared WebSocket Manager
//
// Singleton that provides a single, resilient WebSocket connection
// shared across all screens. Features:
//   - Exponential backoff with jitter (1-32s, max 5 auto-retries)
//   - App-level heartbeat (30s ping, 10s pong timeout)
//   - Message queue for critical messages (resent on reconnect)
//   - Connection state stream for UI observation
//   - Auth token management (auto-re-auth on reconnect)

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:web_socket_channel/web_socket_channel.dart';

/// Connection lifecycle states exposed to UI layers.
enum WsConnectionState {
  disconnected,
  connecting,
  authenticating,
  connected,
  reconnecting,
}

/// A queued outbound message awaiting acknowledgement.
class _PendingMessage {
  final String msgId;
  final Map<String, dynamic> payload;
  final DateTime enqueuedAt;
  int attempts;

  _PendingMessage({
    required this.msgId,
    required this.payload,
    required this.enqueuedAt,
    this.attempts = 0, // ignore: unused_element_parameter
  });
}

class WsManager {
  // ---------------------------------------------------------------------------
  // Singleton
  // ---------------------------------------------------------------------------
  WsManager._internal();
  static final WsManager instance = WsManager._internal();

  // ---------------------------------------------------------------------------
  // Configuration (set before calling connect())
  // ---------------------------------------------------------------------------
  String _wsUrl = '';
  String _authToken = '';
  String _hardwareId = '';
  String _expectedRole = '';
  String? _username;
  String? _recoveryToken;

  void configure({
    required String wsUrl,
    required String authToken,
    required String hardwareId,
    String expectedRole = '',
    String? username,
  }) {
    _wsUrl = wsUrl;
    _authToken = authToken;
    _hardwareId = hardwareId;
    _expectedRole = expectedRole;
    _username = username;
  }

  // ---------------------------------------------------------------------------
  // Connection state
  // ---------------------------------------------------------------------------
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  WsConnectionState _state = WsConnectionState.disconnected;

  final _stateController = StreamController<WsConnectionState>.broadcast();
  Stream<WsConnectionState> get stateStream => _stateController.stream;
  WsConnectionState get currentState => _state;
  bool get isConnected => _state == WsConnectionState.connected;

  void _setState(WsConnectionState s) {
    if (_state == s) return;
    _state = s;
    _stateController.add(s);
  }

  // ---------------------------------------------------------------------------
  // Inbound message stream (broadcast so multiple screens can listen)
  // ---------------------------------------------------------------------------
  final _messageController =
      StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get messages => _messageController.stream;

  // ---------------------------------------------------------------------------
  // Heartbeat
  // ---------------------------------------------------------------------------
  static const _pingInterval = Duration(seconds: 30);
  static const _pongTimeout = Duration(seconds: 10);

  Timer? _pingTimer;
  Timer? _pongTimer;

  void _startHeartbeat() {
    _pingTimer?.cancel();
    _pongTimer?.cancel();
    _pingTimer = Timer.periodic(_pingInterval, (_) => _sendPing());
  }

  void _sendPing() {
    if (_state != WsConnectionState.connected) return;
    try {
      _channel?.sink.add(jsonEncode({'type': 'ping'}));
      _pongTimer?.cancel();
      _pongTimer = Timer(_pongTimeout, () {
        // No pong received within timeout — connection is dead
        _onConnectionLost('pong timeout');
      });
    } catch (_) {
      _onConnectionLost('ping send failed');
    }
  }

  void _onPong() {
    _pongTimer?.cancel();
  }

  // ---------------------------------------------------------------------------
  // Reconnection with exponential backoff + jitter
  // ---------------------------------------------------------------------------
  static const int _maxAutoRetries = 5;
  int _retryCount = 0;
  Timer? _reconnectTimer;
  final _random = Random();

  Duration _backoffDuration() {
    final attempt = _retryCount.clamp(0, 10);
    final baseMs = (1000 * pow(2, attempt)).toInt().clamp(1000, 32000);
    final jitterMs = (_random.nextDouble() * baseMs * 0.3).toInt();
    return Duration(milliseconds: baseMs + jitterMs);
  }

  void _scheduleReconnect() {
    if (_retryCount >= _maxAutoRetries) {
      _setState(WsConnectionState.disconnected);
      return;
    }
    _setState(WsConnectionState.reconnecting);
    final delay = _backoffDuration();
    _retryCount++;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () => _doConnect());
  }

  // ---------------------------------------------------------------------------
  // Message queue (critical messages survive reconnects)
  // ---------------------------------------------------------------------------
  final List<_PendingMessage> _pendingQueue = [];
  static const int _maxQueueSize = 50;
  // ACK timeout reserved for Phase 2 bridge-side ACK system
  // static const _ackTimeout = Duration(seconds: 10);

  /// Send a message. If [critical] is true, the message gets a `msg_id`
  /// and is queued until the server ACKs it.
  void send(Map<String, dynamic> payload, {bool critical = false}) {
    if (critical) {
      final msgId = _generateMsgId();
      payload['msg_id'] = msgId;
      if (_pendingQueue.length < _maxQueueSize) {
        _pendingQueue.add(_PendingMessage(
          msgId: msgId,
          payload: payload,
          enqueuedAt: DateTime.now(),
        ));
      }
    }
    _rawSend(payload);
  }

  void _rawSend(Map<String, dynamic> payload) {
    if (_state != WsConnectionState.connected || _channel == null) return;
    try {
      _channel!.sink.add(jsonEncode(payload));
    } catch (_) {
      _onConnectionLost('send failed');
    }
  }

  void _onAck(String msgId) {
    _pendingQueue.removeWhere((m) => m.msgId == msgId);
  }

  void _resendPendingQueue() {
    final now = DateTime.now();
    _pendingQueue.removeWhere(
      (m) => now.difference(m.enqueuedAt) > const Duration(minutes: 5),
    );
    for (final msg in _pendingQueue) {
      msg.attempts++;
      _rawSend(msg.payload);
    }
  }

  String _generateMsgId() {
    final ts = DateTime.now().millisecondsSinceEpoch;
    final r = _random.nextInt(0xFFFF).toRadixString(16).padLeft(4, '0');
    return '$ts-$r';
  }

  // ---------------------------------------------------------------------------
  // Connect / disconnect
  // ---------------------------------------------------------------------------

  /// Initiate connection. Call [configure] first.
  void connect() {
    if (_state == WsConnectionState.connecting ||
        _state == WsConnectionState.authenticating) {
      return;
    }
    _retryCount = 0;
    _doConnect();
  }

  void _doConnect() {
    if (_wsUrl.isEmpty || _authToken.isEmpty) return;
    _cleanup();
    _setState(WsConnectionState.connecting);

    try {
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
    } catch (e) {
      _scheduleReconnect();
      return;
    }

    _subscription = _channel!.stream.listen(
      _onRawMessage,
      onError: (_) => _onConnectionLost('stream error'),
      onDone: () => _onConnectionLost('stream closed'),
    );

    _setState(WsConnectionState.authenticating);
    _sendAuth();
  }

  void _sendAuth() {
    // Try session recovery first (avoids full re-login after brief disconnect)
    if (_recoveryToken != null && _retryCount > 0) {
      try {
        _channel?.sink.add(jsonEncode({
          'type': 'session_recover',
          'recovery_token': _recoveryToken,
        }));
        return;
      } catch (_) {
        // Fall through to full login
      }
    }

    final authPayload = <String, dynamic>{
      'type': 'login_request',
      'token': _authToken,
      'hardware_id': _hardwareId,
    };
    if (_expectedRole.isNotEmpty) {
      authPayload['expected_role'] = _expectedRole;
    }
    if (_username != null && _username!.isNotEmpty) {
      authPayload['username'] = _username;
    }
    try {
      _channel?.sink.add(jsonEncode(authPayload));
    } catch (_) {
      _onConnectionLost('auth send failed');
    }
  }

  /// Gracefully close the connection. No auto-reconnect.
  void disconnect() {
    _retryCount = _maxAutoRetries; // prevent auto-reconnect
    _recoveryToken = null;
    _cleanup();
    _setState(WsConnectionState.disconnected);
  }

  void _cleanup() {
    _pingTimer?.cancel();
    _pongTimer?.cancel();
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    try {
      _channel?.sink.close();
    } catch (_) {}
    _channel = null;
  }

  void _onConnectionLost(String reason) {
    _cleanup();
    _scheduleReconnect();
  }

  // ---------------------------------------------------------------------------
  // Inbound message handling
  // ---------------------------------------------------------------------------

  void _onRawMessage(dynamic raw) {
    try {
      final data = jsonDecode(raw.toString()) as Map<String, dynamic>;
      final type = data['type'] as String? ?? '';

      // Internal protocol messages
      if (type == 'pong') {
        _onPong();
        return;
      }
      if (type == 'ack') {
        final msgId = data['msg_id'] as String? ?? '';
        if (msgId.isNotEmpty) _onAck(msgId);
        return;
      }
      if (type == 'connected' && data['status'] == 'ready') {
        // Bridge handshake received — auth message already sent
        return;
      }
      if (type == 'login_success') {
        _setState(WsConnectionState.connected);
        _retryCount = 0;
        _recoveryToken = data['recovery_token'] as String?;
        _startHeartbeat();
        _resendPendingQueue();
      }
      if (type == 'session_recovered') {
        _setState(WsConnectionState.connected);
        _retryCount = 0;
        _startHeartbeat();
        _resendPendingQueue();
      }
      if (type == 'session_recovery_failed') {
        _recoveryToken = null;
        _sendAuth(); // fall back to full login
        return;
      }
      if (type == 'login_failed' || type == 'WRONG_PORTAL') {
        _recoveryToken = null;
        _cleanup();
        _setState(WsConnectionState.disconnected);
      }

      _messageController.add(data);
    } catch (_) {
      // Malformed message — ignore
    }
  }

  // ---------------------------------------------------------------------------
  // Convenience
  // ---------------------------------------------------------------------------

  /// True when authentication has been confirmed by the bridge.
  bool get isAuthenticated => _state == WsConnectionState.connected;

  /// Force a reconnect (e.g., user-initiated "Pull to retry").
  void retryNow() {
    _retryCount = 0;
    _reconnectTimer?.cancel();
    _doConnect();
  }

  /// Update auth credentials without reconnecting (e.g., after token refresh).
  void updateCredentials({
    String? authToken,
    String? hardwareId,
    String? expectedRole,
    String? username,
  }) {
    if (authToken != null) _authToken = authToken;
    if (hardwareId != null) _hardwareId = hardwareId;
    if (expectedRole != null) _expectedRole = expectedRole;
    if (username != null) _username = username;
  }

  /// Tear down the singleton (call on app termination only).
  void dispose() {
    _cleanup();
    _stateController.close();
    _messageController.close();
  }
}
