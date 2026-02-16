/// Fragment Buffer Test
///
/// Tests fragment accumulation, assembly detection, and timeout purging.
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Fragment Buffer Logic', () {
    late _TestFragmentBuffer buffer;

    setUp(() {
      buffer = _TestFragmentBuffer(
        maxPending: 256,
        timeoutSeconds: 3600,
        assemblyThreshold: 0.7,
      );
    });

    test('accepts first fragment for a new observation', () {
      final accepted = buffer.addFragment(
        observationId: 'obs-001',
        sequenceNumber: 0,
        totalFragments: 10,
        payload: List.filled(20, 0x42),
      );
      expect(accepted, true);
      expect(buffer.pendingCount, 1);
    });

    test('accumulates multiple fragments for same observation', () {
      for (int i = 0; i < 5; i++) {
        buffer.addFragment(
          observationId: 'obs-002',
          sequenceNumber: i,
          totalFragments: 10,
          payload: List.filled(20, i),
        );
      }
      expect(buffer.pendingCount, 1);
      expect(buffer.fragmentCountFor('obs-002'), 5);
    });

    test('detects assembly ready at threshold', () {
      // With threshold 0.7 and total 10, need 7 fragments
      for (int i = 0; i < 6; i++) {
        final result = buffer.addFragment(
          observationId: 'obs-003',
          sequenceNumber: i,
          totalFragments: 10,
          payload: List.filled(20, i),
        );
        expect(result, true);
      }
      expect(buffer.isReadyToAssemble('obs-003'), false);

      // Add 7th fragment (meets 0.7 threshold)
      buffer.addFragment(
        observationId: 'obs-003',
        sequenceNumber: 6,
        totalFragments: 10,
        payload: List.filled(20, 6),
      );
      expect(buffer.isReadyToAssemble('obs-003'), true);
    });

    test('complete assembly with all fragments', () {
      for (int i = 0; i < 10; i++) {
        buffer.addFragment(
          observationId: 'obs-004',
          sequenceNumber: i,
          totalFragments: 10,
          payload: List.filled(20, i),
        );
      }
      expect(buffer.isReadyToAssemble('obs-004'), true);
      expect(buffer.fragmentCountFor('obs-004'), 10);
    });

    test('rejects duplicate fragments', () {
      buffer.addFragment(
        observationId: 'obs-005',
        sequenceNumber: 0,
        totalFragments: 5,
        payload: List.filled(20, 0),
      );
      final dup = buffer.addFragment(
        observationId: 'obs-005',
        sequenceNumber: 0,
        totalFragments: 5,
        payload: List.filled(20, 0),
      );
      expect(dup, false); // Duplicate rejected
      expect(buffer.fragmentCountFor('obs-005'), 1);
    });

    test('enforces max pending assemblies', () {
      for (int i = 0; i < 256; i++) {
        buffer.addFragment(
          observationId: 'obs-overflow-$i',
          sequenceNumber: 0,
          totalFragments: 10,
          payload: List.filled(20, i & 0xFF),
        );
      }
      expect(buffer.pendingCount, 256);

      // 257th should be rejected or trigger eviction
      final overflow = buffer.addFragment(
        observationId: 'obs-overflow-256',
        sequenceNumber: 0,
        totalFragments: 10,
        payload: List.filled(20, 0),
      );
      // Buffer should handle overflow (either reject or evict oldest)
      expect(buffer.pendingCount, lessThanOrEqualTo(256));
    });

    test('purges expired assemblies', () {
      buffer.addFragment(
        observationId: 'obs-expire',
        sequenceNumber: 0,
        totalFragments: 10,
        payload: List.filled(20, 0),
      );
      expect(buffer.pendingCount, 1);

      // Simulate time passing
      buffer.simulateTimeAdvance(Duration(seconds: 3601));
      buffer.purgeExpired();
      expect(buffer.pendingCount, 0);
    });
  });
}

// ─── Test Buffer Implementation ──────────────────────────────────────────────

class _PendingAssembly {
  final String observationId;
  final int totalFragments;
  final Map<int, List<int>> fragments;
  DateTime createdAt;

  _PendingAssembly({
    required this.observationId,
    required this.totalFragments,
    required this.createdAt,
  }) : fragments = {};
}

class _TestFragmentBuffer {
  final int maxPending;
  final int timeoutSeconds;
  final double assemblyThreshold;
  final Map<String, _PendingAssembly> _pending = {};
  DateTime _now = DateTime.now();

  _TestFragmentBuffer({
    required this.maxPending,
    required this.timeoutSeconds,
    required this.assemblyThreshold,
  });

  int get pendingCount => _pending.length;

  int fragmentCountFor(String observationId) {
    return _pending[observationId]?.fragments.length ?? 0;
  }

  bool addFragment({
    required String observationId,
    required int sequenceNumber,
    required int totalFragments,
    required List<int> payload,
  }) {
    var assembly = _pending[observationId];
    if (assembly == null) {
      if (_pending.length >= maxPending) {
        return false; // Overflow
      }
      assembly = _PendingAssembly(
        observationId: observationId,
        totalFragments: totalFragments,
        createdAt: _now,
      );
      _pending[observationId] = assembly;
    }

    // Reject duplicates
    if (assembly.fragments.containsKey(sequenceNumber)) {
      return false;
    }

    assembly.fragments[sequenceNumber] = payload;
    return true;
  }

  bool isReadyToAssemble(String observationId) {
    final assembly = _pending[observationId];
    if (assembly == null) return false;
    return assembly.fragments.length >=
        (assembly.totalFragments * assemblyThreshold).ceil();
  }

  void simulateTimeAdvance(Duration duration) {
    _now = _now.add(duration);
  }

  void purgeExpired() {
    _pending.removeWhere((_, assembly) {
      return _now.difference(assembly.createdAt).inSeconds > timeoutSeconds;
    });
  }
}
