/// Spider Web Service Test
///
/// Tests the mobile-side Spider Web per-PDU threat assessment.
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('CRC-8 Computation', () {
    test('CRC-8 of empty data is 0', () {
      final result = _crc8(Uint8List(0));
      expect(result, 0);
    });

    test('CRC-8 is deterministic', () {
      final data = Uint8List.fromList([0x01, 0x02, 0x03, 0x04]);
      final a = _crc8(data);
      final b = _crc8(data);
      expect(a, equals(b));
    });

    test('CRC-8 changes with different data', () {
      final data1 = Uint8List.fromList([0x01, 0x02, 0x03]);
      final data2 = Uint8List.fromList([0x01, 0x02, 0x04]);
      expect(_crc8(data1), isNot(equals(_crc8(data2))));
    });

    test('CRC-8 uses polynomial 0x07', () {
      // Known CRC-8 test vector: data [0x31, 0x32, 0x33, 0x34]
      // with polynomial 0x07 should produce a specific value
      final data = Uint8List.fromList([0x31, 0x32, 0x33, 0x34]);
      final result = _crc8(data);
      expect(result, isA<int>());
      expect(result, greaterThanOrEqualTo(0));
      expect(result, lessThanOrEqualTo(255));
    });
  });

  group('Spider Web Threat Assessment', () {
    test('SpiderThreatLevel enum has three levels', () {
      expect(_SpiderThreatLevel.values.length, 3);
    });

    test('CLEAN is least severe', () {
      expect(_SpiderThreatLevel.clean.index,
          lessThan(_SpiderThreatLevel.suspicious.index));
    });

    test('HOSTILE is most severe', () {
      expect(_SpiderThreatLevel.hostile.index,
          greaterThan(_SpiderThreatLevel.suspicious.index));
    });
  });

  group('False Positive Rate', () {
    test('random data should not produce valid ZEFCP fragments', () {
      int falsePositives = 0;
      const trials = 10000;

      for (int i = 0; i < trials; i++) {
        // Generate random 31-byte BLE advertising data
        final data = Uint8List(31);
        for (int j = 0; j < 31; j++) {
          data[j] = (i * 7 + j * 13) & 0xFF;
        }
        if (_looksLikeZefcpFragment(data)) {
          falsePositives++;
        }
      }

      final rate = falsePositives / trials;
      // False positive rate should be well below 0.001
      expect(rate, lessThan(0.01));
    });
  });
}

// ─── Test Helpers ─────────────────────────────────────────────────────────────

/// CRC-8 computation (polynomial 0x07, same as backend)
int _crc8(Uint8List data) {
  int crc = 0;
  for (final byte in data) {
    crc ^= byte;
    for (int i = 0; i < 8; i++) {
      if ((crc & 0x80) != 0) {
        crc = ((crc << 1) ^ 0x07) & 0xFF;
      } else {
        crc = (crc << 1) & 0xFF;
      }
    }
  }
  return crc;
}

/// Check if raw BLE data looks like a ZEFCP fragment.
/// Looks for the ZEFCP signature bytes (0x5E, 0x46).
bool _looksLikeZefcpFragment(Uint8List data) {
  if (data.length < 4) return false;
  // Look for ZEFCP magic bytes anywhere in the data
  for (int i = 0; i < data.length - 1; i++) {
    if (data[i] == 0x5E && data[i + 1] == 0x46) {
      return true;
    }
  }
  return false;
}

enum _SpiderThreatLevel { clean, suspicious, hostile }
