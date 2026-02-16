/// ZEFCP Protocol Constants — Synchronized with backend
/// Zero-Energy Parasitic BLE Communication Protocol
/// Layer 1 Physical Transport Constants

/// Protocol version
const int zefcpVersion = 1;

/// Maximum fragment size (BLE advertising payload limit)
const int maxFragmentSize = 27;

/// Signature rotation period (5 minutes = 300 seconds)
const int signaturePeriodSeconds = 300;

/// CRC-8 polynomial: x^8 + x^2 + x + 1 (0x07)
const int crc8Polynomial = 0x07;

/// CRC-8 initial value
const int crc8Init = 0x00;

/// Spider Web false positive threshold (0.1%)
const double spiderWebFalsePositiveThreshold = 0.001;

/// Minimum assembly threshold (70% fragments required for Reed-Solomon decode)
const double minAssemblyThreshold = 0.7;

/// Fragment timeout (1 hour)
const int fragmentTimeoutSeconds = 3600;

/// Maximum pending assemblies
const int maxPendingAssemblies = 256;

/// Adaptive redundancy factors
const double adaptiveRedundancyLow = 0.1;
const double adaptiveRedundancyMedium = 0.3;
const double adaptiveRedundancyHigh = 0.5;

/// BLE scan modes
enum BleScanMode {
  /// Passive scanning (low power, no connection requests)
  passive,
  
  /// Active scanning (sends scan requests)
  active,
  
  /// Promiscuous mode (scans ALL devices, not just specific UUIDs)
  promiscuous,
}

/// Fragment types
enum FragmentType {
  /// Standard 8-byte fragment
  standard,
  
  /// Extended 12-byte fragment
  extended,
  
  /// Parity fragment for Reed-Solomon FEC
  parity,
}

/// Standard fragment sizes
const int standardLeadingBytes = 4;
const int standardTrailingBytes = 4;
const int standardPayloadSize = 2;
const int standardTotalBytes = 8;

/// Extended fragment sizes
const int extendedLeadingBytes = 6;
const int extendedTrailingBytes = 6;
const int extendedPayloadSize = 5;
const int extendedTotalBytes = 12;

/// Maximum fragments per observation
const int maxFragmentsPerObservation = 255;

/// Trail emission flag mask
const int trailFlagMask = 0b10000000;

/// Reed-Solomon error correction constants
const double defaultRedundancyFactor = 0.3;
const double minRedundancyFactor = 0.1;
const double maxRedundancyFactor = 0.5;
const double reconstructionThreshold = 0.7;
const int parityInterleaveInterval = 4;

/// Fragment buffer constants
const int maxPendingObservations = 256;
const int duplicateDetectionWindow = 60; // seconds

/// Embedding & detection rates
const int maxEmbeddingRate = 10; // fragments per second
const int cloudForwardingBatchSize = 50;
const int cloudForwardingIntervalSeconds = 5;

/// Encryption constants
const String encryptionAlgorithm = "AES-128-CTR";
const int keyLengthBytes = 16; // 128-bit AES key
const int nonceLengthBytes = 16; // CTR mode nonce
const String keyDerivationInfoPrefix = "fibre-obs-";

/// Performance thresholds
const int densityUrbanDense = 500; // handshakes/min
const int densityUrbanStandard = 200;
const int densitySuburban = 100;
const int densityClinic = 50;
const int densityRural = 15;

/// False positive budget
const double maxFalsePositiveRate = 0.0001; // 0.01%
const double expectedFalsePositiveRate = 0.0000228; // 0.00228%

/// Metrics reporting interval
const int metricsReportingIntervalSeconds = 60;

/// Exploitable BLE AD Types (commonly carry exploitable overhead)
const Set<int> exploitableAdTypes = {
  0xFF, // Manufacturer Specific Data
  0x16, // Service Data - 16-bit UUID
  0x21, // Service Data - 128-bit UUID
  0x02, // Incomplete List of 16-bit Service UUIDs
  0x06, // Incomplete List of 128-bit Service UUIDs
  0x09, // Complete Local Name (trailing bytes after name)
};

/// Minimum functional bytes per AD type (must remain untouched)
const Map<int, int> minimumFunctionalBytes = {
  0xFF: 2,  // Company ID (2 bytes) must be preserved
  0x16: 2,  // UUID (2 bytes) must be preserved
  0x21: 16, // UUID (16 bytes) must be preserved
  0x02: 0,  // UUID list — trailing entries are "incomplete" by definition
  0x06: 0,  // UUID list — trailing entries are "incomplete" by definition
  0x09: 1,  // At least first character of name must be preserved
};

/// Signature rotation period (15 minutes)
const int signatureRotationMinutes = 15;

/// Signature window periods (accept current ± 1)
const int signatureWindowPeriods = 3;
