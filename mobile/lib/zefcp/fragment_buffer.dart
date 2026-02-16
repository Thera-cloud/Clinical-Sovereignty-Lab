/// ZEFCP Fragment Buffer — Fragment Accumulation and Reassembly
/// Accumulates fragments by observation_id and attempts Reed-Solomon reconstruction
/// Layer 1 Physical Transport: Fragment assembly coordination

import 'dart:async';
import 'dart:typed_data';
import 'dart:collection';
import 'constants.dart';

/// Accumulated observation data
class AssembledObservation {
  /// Observation ID
  final int observationId;
  
  /// Complete assembled payload bytes
  final Uint8List payload;
  
  /// Timestamp when assembly completed
  final DateTime assembledAt;
  
  /// Number of fragments used in assembly
  final int fragmentCount;
  
  /// Whether Reed-Solomon reconstruction was used
  final bool usedReedSolomon;
  
  AssembledObservation({
    required this.observationId,
    required this.payload,
    required this.assembledAt,
    required this.fragmentCount,
    this.usedReedSolomon = false,
  });
}

/// Fragment data for accumulation
class FragmentData {
  /// Sequence number (0-based)
  final int sequence;
  
  /// Total number of fragments in observation
  final int total;
  
  /// Payload bytes for this fragment
  final Uint8List payload;
  
  /// Timestamp when fragment was received
  final DateTime receivedAt;
  
  /// Fragment type
  final FragmentType type;
  
  FragmentData({
    required this.sequence,
    required this.total,
    required this.payload,
    DateTime? receivedAt,
    this.type = FragmentType.standard,
  }) : receivedAt = receivedAt ?? DateTime.now();
}

/// Fragment buffer for accumulating and reassembling observations
/// 
/// Accumulates fragments by observation_id, tracks sequence numbers,
/// and attempts assembly when enough fragments arrive (>= MIN_ASSEMBLY_THRESHOLD).
/// 
/// Features:
/// - Fragment accumulation by observation_id
/// - Sequence number tracking
/// - Reed-Solomon reconstruction support
/// - Auto-purge expired assemblies
/// - Maximum pending assemblies limit
/// - Thread-safe design considerations
class FragmentBuffer {
  /// Map of observation_id -> list of fragments
  final Map<int, List<FragmentData>> _fragments = {};
  
  /// Map of observation_id -> assembly metadata
  final Map<int, _AssemblyMetadata> _metadata = {};
  
  /// Stream controller for assembled observations
  final StreamController<AssembledObservation> _assemblyController = 
      StreamController<AssembledObservation>.broadcast();
  
  Timer? _purgeTimer;
  
  /// Stream of assembled observations
  Stream<AssembledObservation> get assembledObservations => _assemblyController.stream;
  
  /// Number of pending assemblies
  int get pendingAssemblyCount => _fragments.length;
  
  /// Initialize buffer and start purge timer
  FragmentBuffer() {
    // Start periodic purge of expired assemblies
    _purgeTimer = Timer.periodic(
      const Duration(seconds: 60),
      (_) => _purgeExpiredAssemblies(),
    );
  }
  
  /// Add a fragment to the buffer
  /// 
  /// [observationId] Observation ID (from fragment)
  /// [sequence] Sequence number (0-based)
  /// [total] Total number of fragments
  /// [payload] Payload bytes for this fragment
  /// [fragmentType] Fragment type (default: standard)
  /// 
  /// Returns true if fragment was added, false if duplicate or invalid
  bool addFragment({
    required int observationId,
    required int sequence,
    required int total,
    required Uint8List payload,
    FragmentType fragmentType = FragmentType.standard,
  }) {
    // Check pending assemblies limit
    if (_fragments.length >= maxPendingAssemblies && 
        !_fragments.containsKey(observationId)) {
      print('[Fragment Buffer] Max pending assemblies reached, dropping fragment');
      return false;
    }
    
    // Initialize observation if needed
    if (!_fragments.containsKey(observationId)) {
      _fragments[observationId] = [];
      _metadata[observationId] = _AssemblyMetadata(
        observationId: observationId,
        totalFragments: total,
        firstFragmentAt: DateTime.now(),
      );
    }
    
    final fragments = _fragments[observationId]!;
    final metadata = _metadata[observationId]!;
    
    // Check for duplicate
    if (fragments.any((f) => f.sequence == sequence)) {
      return false; // Duplicate fragment
    }
    
    // Validate sequence number
    if (sequence < 0 || sequence >= total) {
      print('[Fragment Buffer] Invalid sequence: $sequence (total: $total)');
      return false;
    }
    
    // Update metadata
    if (total != metadata.totalFragments) {
      // Total changed (shouldn't happen, but handle gracefully)
      metadata.totalFragments = total;
    }
    
    // Add fragment
    fragments.add(FragmentData(
      sequence: sequence,
      total: total,
      payload: payload,
      type: fragmentType,
    ));
    
    // Sort by sequence
    fragments.sort((a, b) => a.sequence.compareTo(b.sequence));
    
    print('[Fragment Buffer] Added fragment $sequence/$total for observation $observationId (have: ${fragments.length})');
    
    // Check if we have enough fragments for assembly
    final fragmentRatio = fragments.length / total;
    if (fragmentRatio >= minAssemblyThreshold) {
      _attemptAssembly(observationId);
    }
    
    return true;
  }
  
  /// Attempt to assemble an observation
  void _attemptAssembly(int observationId) {
    final fragments = _fragments[observationId];
    final metadata = _metadata[observationId];
    
    if (fragments == null || metadata == null) return;
    
    final total = metadata.totalFragments;
    final fragmentRatio = fragments.length / total;
    
    // Check if we have all fragments (perfect assembly)
    if (fragments.length == total) {
      _performAssembly(observationId, useReedSolomon: false);
      return;
    }
    
    // Check if we have enough for Reed-Solomon reconstruction
    if (fragmentRatio >= reconstructionThreshold) {
      _performAssembly(observationId, useReedSolomon: true);
      return;
    }
    
    // Not enough fragments yet
    print('[Fragment Buffer] Not enough fragments for observation $observationId (have: ${fragments.length}/$total, need: ${(total * minAssemblyThreshold).ceil()})');
  }
  
  /// Perform assembly (with or without Reed-Solomon)
  void _performAssembly(int observationId, {required bool useReedSolomon}) {
    final fragments = _fragments[observationId];
    final metadata = _metadata[observationId];
    
    if (fragments == null || metadata == null) return;
    
    try {
      Uint8List payload;
      
      if (useReedSolomon) {
        // Reed-Solomon reconstruction
        payload = _reedSolomonReconstruct(fragments, metadata.totalFragments);
      } else {
        // Simple concatenation (all fragments present)
        payload = _simpleConcatenate(fragments);
      }
      
      // Create assembled observation
      final assembled = AssembledObservation(
        observationId: observationId,
        payload: payload,
        assembledAt: DateTime.now(),
        fragmentCount: fragments.length,
        usedReedSolomon: useReedSolomon,
      );
      
      // Emit assembled observation
      _assemblyController.add(assembled);
      
      print('[Fragment Buffer] Assembled observation $observationId (${fragments.length} fragments, RS: $useReedSolomon)');
      
      // Remove from buffer
      _fragments.remove(observationId);
      _metadata.remove(observationId);
    } catch (e) {
      print('[Fragment Buffer] Assembly failed for observation $observationId: $e');
      // Keep fragments for retry
    }
  }
  
  /// Simple concatenation (all fragments present)
  Uint8List _simpleConcatenate(List<FragmentData> fragments) {
    final totalLength = fragments.fold<int>(
      0,
      (sum, frag) => sum + frag.payload.length,
    );
    
    final result = Uint8List(totalLength);
    int offset = 0;
    
    for (final fragment in fragments) {
      result.setRange(offset, offset + fragment.payload.length, fragment.payload);
      offset += fragment.payload.length;
    }
    
    return result;
  }
  
  /// Reed-Solomon reconstruction (partial fragments)
  /// 
  /// Note: This is a simplified implementation. A full Reed-Solomon
  /// decoder would require a proper error correction library.
  Uint8List _reedSolomonReconstruct(List<FragmentData> fragments, int totalFragments) {
    // For now, use simple concatenation with zero-padding for missing fragments
    // In production, integrate a proper Reed-Solomon library like:
    // - reedsolomon package
    // - Custom implementation based on backend's reed_solomon.py
    
    final expectedFragments = totalFragments;
    final fragmentMap = <int, FragmentData>{};
    
    for (final frag in fragments) {
      fragmentMap[frag.sequence] = frag;
    }
    
    // Estimate payload size from available fragments
    final avgPayloadSize = fragments.isEmpty 
        ? 0 
        : fragments.fold<int>(0, (sum, f) => sum + f.payload.length) ~/ fragments.length;
    
    final estimatedTotalSize = avgPayloadSize * expectedFragments;
    final result = Uint8List(estimatedTotalSize);
    int offset = 0;
    
    // Fill in available fragments
    for (int seq = 0; seq < expectedFragments; seq++) {
      if (fragmentMap.containsKey(seq)) {
        final frag = fragmentMap[seq]!;
        result.setRange(offset, offset + frag.payload.length, frag.payload);
        offset += frag.payload.length;
      } else {
        // Missing fragment - pad with zeros (simplified)
        // Real RS decoder would reconstruct from parity fragments
        offset += avgPayloadSize;
      }
    }
    
    // Trim to actual size
    return result.sublist(0, offset);
  }
  
  /// Purge expired assemblies
  void _purgeExpiredAssemblies() {
    final now = DateTime.now();
    final expiredIds = <int>[];
    
    for (final entry in _metadata.entries) {
      final age = now.difference(entry.value.firstFragmentAt);
      if (age.inSeconds > fragmentTimeoutSeconds) {
        expiredIds.add(entry.key);
      }
    }
    
    for (final id in expiredIds) {
      _fragments.remove(id);
      _metadata.remove(id);
      print('[Fragment Buffer] Purged expired assembly: $id');
    }
  }
  
  /// Clear all pending assemblies
  void clear() {
    _fragments.clear();
    _metadata.clear();
    print('[Fragment Buffer] Cleared all assemblies');
  }
  
  /// Dispose resources
  void dispose() {
    _purgeTimer?.cancel();
    _purgeTimer = null;
    _assemblyController.close();
    clear();
  }
}

/// Assembly metadata
class _AssemblyMetadata {
  final int observationId;
  int totalFragments;
  final DateTime firstFragmentAt;
  
  _AssemblyMetadata({
    required this.observationId,
    required this.totalFragments,
    required this.firstFragmentAt,
  });
}
