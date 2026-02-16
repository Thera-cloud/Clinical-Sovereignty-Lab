/// ZEFCP Mesh Bridge — WebSocket/REST/Offline Transport Layer
/// Layer 1 Physical Transport: Bridge between mobile BLE scanner and backend
/// 
/// Handles fragment forwarding with graceful degradation:
/// 1. WebSocket (preferred) → 2. REST API → 3. Offline buffer

import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../config/app_config.dart';
import 'secure_key_store.dart';
import 'offline_buffer.dart' show OfflineBuffer, BufferEntryType;

/// Connection state for the mesh bridge
enum ZefcpConnectionState {
  disconnected,
  connecting,
  connected,
  degraded, // WebSocket failed, using REST
  offline,  // All connections failed, using buffer
}

/// Result of sending a fragment
class FragmentSendResult {
  final bool success;
  final String? error;
  final bool buffered; // True if stored offline
  final String? fragmentId;

  FragmentSendResult({
    required this.success,
    this.error,
    this.buffered = false,
    this.fragmentId,
  });
}

/// Embed queue entry
class EmbedQueueEntry {
  final String fragmentId;
  final String observationId;
  final int sequenceNumber;
  final int totalFragments;
  final String payloadB64;
  final Map<String, dynamic>? metadata;

  EmbedQueueEntry({
    required this.fragmentId,
    required this.observationId,
    required this.sequenceNumber,
    required this.totalFragments,
    required this.payloadB64,
    this.metadata,
  });

  factory EmbedQueueEntry.fromJson(Map<String, dynamic> json) {
    return EmbedQueueEntry(
      fragmentId: json['fragment_id'] as String,
      observationId: json['observation_id'] as String,
      sequenceNumber: json['sequence_number'] as int,
      totalFragments: json['total_fragments'] as int,
      payloadB64: json['payload_b64'] as String,
      metadata: json['metadata'] as Map<String, dynamic>?,
    );
  }
}

/// Capacity query result
class CapacityResult {
  final String endpointId;
  final int pendingAssemblies;
  final int totalFragmentsDetected;
  final int maxFragmentSize;
  final bool available;

  CapacityResult({
    required this.endpointId,
    required this.pendingAssemblies,
    required this.totalFragmentsDetected,
    required this.maxFragmentSize,
    required this.available,
  });

  factory CapacityResult.fromJson(Map<String, dynamic> json) {
    return CapacityResult(
      endpointId: json['endpoint_id'] as String? ?? 'primary',
      pendingAssemblies: json['pending_assemblies'] as int? ?? 0,
      totalFragmentsDetected: json['total_fragments_detected'] as int? ?? 0,
      maxFragmentSize: json['max_fragment_size'] as int? ?? 27,
      available: json['available'] as bool? ?? false,
    );
  }
}

/// ZEFCP Mesh Bridge — manages WebSocket/REST/Offline transport
class ZefcpMeshBridge {
  static final ZefcpMeshBridge _instance = ZefcpMeshBridge._internal();
  factory ZefcpMeshBridge() => _instance;
  ZefcpMeshBridge._internal();

  WebSocketChannel? _wsChannel;
  StreamSubscription? _wsSubscription;
  ZefcpConnectionState _state = ZefcpConnectionState.disconnected;
  final StreamController<ZefcpConnectionState> _stateController =
      StreamController<ZefcpConnectionState>.broadcast();
  
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;
  static const int _maxReconnectAttempts = 5;
  static const Duration _initialReconnectDelay = Duration(seconds: 2);
  
  final OfflineBuffer _offlineBuffer = OfflineBuffer();
  final SecureKeyStore _keyStore = SecureKeyStore();
  
  String? _fibreId;
  String? _endpointId;

  /// Current connection state
  ZefcpConnectionState get state => _state;

  /// Stream of connection state changes
  Stream<ZefcpConnectionState> get stateStream => _stateController.stream;

  /// Check if bridge is connected (WebSocket or REST)
  bool get isConnected => _state == ZefcpConnectionState.connected ||
                          _state == ZefcpConnectionState.degraded;

  /// Initialize the bridge (loads fibre ID from secure storage)
  Future<void> initialize() async {
    _fibreId = await _keyStore.getFibreId();
    _endpointId = await _keyStore.getTransportConfig()
        .then((config) => config?['endpoint_id'] as String?)
        .catchError((_) => null) ?? 'primary';
    
    // Attempt to flush any pending offline fragments
    await _flushOfflineBuffer();
  }

  /// Connect to the backend via WebSocket
  Future<bool> connect() async {
    if (_state == ZefcpConnectionState.connected ||
        _state == ZefcpConnectionState.connecting) {
      return _state == ZefcpConnectionState.connected;
    }

    _updateState(ZefcpConnectionState.connecting);
    _reconnectAttempts = 0;

    try {
      final wsUrl = AppConfig.wsUrl;
      _wsChannel = WebSocketChannel.connect(Uri.parse(wsUrl));

      // Wait for connection to establish
      await Future.delayed(const Duration(milliseconds: 500));

      // Listen for messages
      _wsSubscription = _wsChannel!.stream.listen(
        _handleWebSocketMessage,
        onError: _handleWebSocketError,
        onDone: _handleWebSocketDone,
        cancelOnError: false,
      );

      // Send auth message if we have fibre credentials
      if (_fibreId != null) {
        _wsChannel!.sink.add(jsonEncode({
          'type': 'zefcp_auth',
          'fibre_id': _fibreId,
          'endpoint_id': _endpointId,
        }));
      }

      _updateState(ZefcpConnectionState.connected);
      _reconnectAttempts = 0;
      
      // Flush offline buffer now that we're connected
      await _flushOfflineBuffer();
      
      return true;
    } catch (e) {
      print('[ZEFCP Bridge] WebSocket connect failed: $e');
      _updateState(ZefcpConnectionState.degraded);
      return false;
    }
  }

  /// Disconnect from the backend
  Future<void> disconnect() async {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    
    await _wsSubscription?.cancel();
    _wsSubscription = null;
    
    await _wsChannel?.sink.close();
    _wsChannel = null;
    
    _updateState(ZefcpConnectionState.disconnected);
  }

  /// Send a captured fragment to the backend
  Future<FragmentSendResult> sendFragment({
    required String fragmentId,
    required String observationId,
    required int sequenceNumber,
    required int totalFragments,
    required List<int> payload,
    String? signature,
    String? endpointId,
  }) async {
    final targetEndpoint = endpointId ?? _endpointId ?? 'primary';
    final payloadB64 = base64Encode(payload);
    final signatureB64 = signature != null ? base64Encode(signature.codeUnits) : null;

    // Try WebSocket first
    if (_state == ZefcpConnectionState.connected && _wsChannel != null) {
      try {
        _wsChannel!.sink.add(jsonEncode({
          'type': 'zefcp_fragment',
          'fragment_id': fragmentId,
          'observation_id': observationId,
          'sequence_number': sequenceNumber,
          'total_fragments': totalFragments,
          'payload_b64': payloadB64,
          'endpoint_id': targetEndpoint,
          if (signatureB64 != null) 'signature_b64': signatureB64,
        }));

        return FragmentSendResult(
          success: true,
          fragmentId: fragmentId,
        );
      } catch (e) {
        print('[ZEFCP Bridge] WebSocket send failed: $e');
        // Fall through to REST fallback
      }
    }

    // Fallback to REST API
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/zefcp/fragments'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'fragment_id': fragmentId,
          'observation_id': observationId,
          'sequence_number': sequenceNumber,
          'total_fragments': totalFragments,
          'payload_b64': payloadB64,
          'endpoint_id': targetEndpoint,
          if (signatureB64 != null) 'signature_b64': signatureB64,
        }),
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200 || response.statusCode == 201) {
        _updateState(ZefcpConnectionState.degraded);
        return FragmentSendResult(
          success: true,
          fragmentId: fragmentId,
        );
      } else {
        throw Exception('REST API returned ${response.statusCode}');
      }
    } catch (e) {
      print('[ZEFCP Bridge] REST send failed: $e');
      // Fall through to offline buffer
    }

    // Final fallback: store offline
    final buffered = await _offlineBuffer.bufferFragment({
      'fragment_id': fragmentId,
      'observation_id': observationId,
      'sequence_number': sequenceNumber,
      'total_fragments': totalFragments,
      'payload_b64': payloadB64,
      'endpoint_id': targetEndpoint,
      if (signatureB64 != null) 'signature_b64': signatureB64,
    });

    _updateState(ZefcpConnectionState.offline);
    return FragmentSendResult(
      success: buffered,
      buffered: true,
      fragmentId: fragmentId,
      error: buffered ? null : 'Offline buffer is full',
    );
  }

  /// Get embed queue for this fibre (fragments to advertise via BLE)
  Future<List<EmbedQueueEntry>> getEmbedQueue({int maxFragments = 10}) async {
    if (_fibreId == null) {
      return [];
    }

    // Try WebSocket first
    if (_state == ZefcpConnectionState.connected && _wsChannel != null) {
      try {
        // Send request
        _wsChannel!.sink.add(jsonEncode({
          'type': 'zefcp_embed_request',
          'fibre_id': _fibreId,
          'max_fragments': maxFragments,
        }));

        // Wait for response (in real implementation, use a request/response pattern)
        // For now, fall through to REST
      } catch (e) {
        print('[ZEFCP Bridge] WebSocket embed request failed: $e');
      }
    }

    // Fallback to REST API
    try {
      final response = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/zefcp/embed-queue/$_fibreId')
            .replace(queryParameters: {'max_fragments': maxFragments.toString()}),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final fragments = data['fragments'] as List<dynamic>? ?? [];
        return fragments.map((f) => EmbedQueueEntry.fromJson(f as Map<String, dynamic>)).toList();
      }
    } catch (e) {
      print('[ZEFCP Bridge] REST embed queue failed: $e');
    }

    return [];
  }

  /// Query transport capacity for the endpoint
  Future<CapacityResult> queryCapacity({String? endpointId}) async {
    final targetEndpoint = endpointId ?? _endpointId ?? 'primary';

    // Try WebSocket first
    if (_state == ZefcpConnectionState.connected && _wsChannel != null) {
      try {
        _wsChannel!.sink.add(jsonEncode({
          'type': 'zefcp_capacity',
          'endpoint_id': targetEndpoint,
        }));

        // Wait for response (in real implementation, use a request/response pattern)
        // For now, fall through to REST
      } catch (e) {
        print('[ZEFCP Bridge] WebSocket capacity query failed: $e');
      }
    }

    // Fallback to REST API
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/zefcp/capacity'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'endpoint_id': targetEndpoint,
          'max_fragment_size': 27,
        }),
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return CapacityResult.fromJson(data);
      }
    } catch (e) {
      print('[ZEFCP Bridge] REST capacity query failed: $e');
    }

    // Return default capacity if all queries fail
    return CapacityResult(
      endpointId: targetEndpoint,
      pendingAssemblies: 0,
      totalFragmentsDetected: 0,
      maxFragmentSize: 27,
      available: false,
    );
  }

  /// Handle incoming WebSocket message
  void _handleWebSocketMessage(dynamic message) {
    try {
      final data = jsonDecode(message) as Map<String, dynamic>;
      final type = data['type'] as String?;

      switch (type) {
        case 'zefcp_embed_request':
          // Handle embed queue response (would need request/response correlation)
          break;
        case 'zefcp_capacity':
          // Handle capacity response (would need request/response correlation)
          break;
        case 'connected':
        case 'zefcp_auth_success':
          _updateState(ZefcpConnectionState.connected);
          break;
        default:
          // Ignore unknown message types
          break;
      }
    } catch (e) {
      print('[ZEFCP Bridge] Message parse error: $e');
    }
  }

  /// Handle WebSocket error
  void _handleWebSocketError(dynamic error) {
    print('[ZEFCP Bridge] WebSocket error: $error');
    _scheduleReconnect();
  }

  /// Handle WebSocket close
  void _handleWebSocketDone() {
    print('[ZEFCP Bridge] WebSocket closed');
    _scheduleReconnect();
  }

  /// Schedule reconnection with exponential backoff
  void _scheduleReconnect() {
    if (_reconnectAttempts >= _maxReconnectAttempts) {
      _updateState(ZefcpConnectionState.offline);
      return;
    }

    _reconnectTimer?.cancel();
    final delay = Duration(
      milliseconds: (_initialReconnectDelay.inMilliseconds *
              pow(2, _reconnectAttempts))
          .round(),
    );

    _reconnectTimer = Timer(delay, () {
      _reconnectAttempts++;
      connect();
    });
  }

  /// Flush offline buffer (send all buffered fragments)
  Future<void> _flushOfflineBuffer() async {
    if (_state != ZefcpConnectionState.connected &&
        _state != ZefcpConnectionState.degraded) {
      return;
    }

    final entries = await _offlineBuffer.getUnsynced();
    final syncedIds = <int>[];
    
    for (final entry in entries) {
      if (entry.type != BufferEntryType.fragment) continue;
      
      try {
        final fragment = entry.payloadJson;
        await sendFragment(
          fragmentId: fragment['fragment_id'] as String,
          observationId: fragment['observation_id'] as String,
          sequenceNumber: fragment['sequence_number'] as int,
          totalFragments: fragment['total_fragments'] as int,
          payload: base64Decode(fragment['payload_b64'] as String),
          signature: fragment['signature_b64'] != null
              ? String.fromCharCodes(base64Decode(fragment['signature_b64'] as String))
              : null,
          endpointId: fragment['endpoint_id'] as String?,
        );
        
        // Mark as synced after successful send
        if (entry.id != null) {
          syncedIds.add(entry.id!);
        }
      } catch (e) {
        print('[ZEFCP Bridge] Failed to flush fragment: $e');
        // Keep fragment in buffer for next attempt
      }
    }
    
    // Mark successfully sent fragments as synced
    if (syncedIds.isNotEmpty) {
      await _offlineBuffer.markSynced(syncedIds);
    }
  }

  /// Update connection state and notify listeners
  void _updateState(ZefcpConnectionState newState) {
    if (_state != newState) {
      _state = newState;
      _stateController.add(newState);
    }
  }

  /// Dispose resources
  void dispose() {
    disconnect();
    _stateController.close();
    _offlineBuffer.dispose();
  }
}
