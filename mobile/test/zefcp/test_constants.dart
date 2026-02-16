/// ZEFCP Constants Test
///
/// Validates that protocol constants are synchronized between
/// mobile and backend implementations.
import 'package:flutter_test/flutter_test.dart';
import 'package:sovereign_sanctuary/zefcp/constants.dart';

void main() {
  group('ZEFCP Constants', () {
    test('protocol version is 1', () {
      expect(zefcpVersion, 1);
    });

    test('max fragment size is 27 bytes (BLE ADV payload limit)', () {
      expect(maxFragmentSize, 27);
    });

    test('signature period is 300 seconds (5 minutes)', () {
      expect(signaturePeriodSeconds, 300);
    });

    test('CRC-8 polynomial is 0x07', () {
      expect(crc8Polynomial, 0x07);
    });

    test('false positive threshold is 0.001', () {
      expect(spiderWebFalsePositiveThreshold, closeTo(0.001, 0.0001));
    });

    test('min assembly threshold is 0.7', () {
      expect(minAssemblyThreshold, closeTo(0.7, 0.01));
    });

    test('fragment timeout is 3600 seconds', () {
      expect(fragmentTimeoutSeconds, 3600);
    });

    test('max pending assemblies is 256', () {
      expect(maxPendingAssemblies, 256);
    });

    test('BLE scan modes are defined', () {
      expect(BleScanMode.values.length, 3);
      expect(BleScanMode.values, contains(BleScanMode.passive));
      expect(BleScanMode.values, contains(BleScanMode.active));
      expect(BleScanMode.values, contains(BleScanMode.promiscuous));
    });

    test('Fragment types are defined', () {
      expect(FragmentType.values.length, 3);
      expect(FragmentType.values, contains(FragmentType.standard));
      expect(FragmentType.values, contains(FragmentType.extended));
      expect(FragmentType.values, contains(FragmentType.parity));
    });

    test('adaptive redundancy levels are ordered', () {
      expect(adaptiveRedundancyLow, lessThan(adaptiveRedundancyMedium));
      expect(adaptiveRedundancyMedium, lessThan(adaptiveRedundancyHigh));
    });
  });
}
