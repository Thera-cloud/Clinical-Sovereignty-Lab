/// Quakete Protocol Constants
/// Layer 8 Swarm Solidarity — Emotional Solidarity Protocol
/// 
/// Synchronized with backend quakete service constants.
/// These values define the behavior of the Quakete solidarity system.

/// Protocol version for compatibility checking
const int QUAKETE_VERSION = 1;

/// Interval between trail emissions (seconds)
const int TRAIL_EMISSION_INTERVAL_SECONDS = 60;

/// Resonance matching threshold (sigma value for Gaussian matching)
const double RESONANCE_SIGMA = 0.5;

/// Minimum coherence required for ring formation
const double MIN_RING_COHERENCE = 0.6;

/// Minimum cord strength for three-cord solidarity
const double MIN_CORD_STRENGTH = 0.3;

/// Ring size (three-cord solidarity)
const int RING_SIZE = 3;

/// Maximum Lorentz force applied during energy transfer
const double LORENTZ_FORCE_CAP = 2.5;

/// Ion lifetime before decay (seconds)
const int ION_LIFETIME_SECONDS = 3600;

/// Coherence threshold that triggers emergency ramp-up protocol
const double RAMP_UP_THRESHOLD = 0.15;

/// Cooldown period between distress beacons (seconds)
const int DISTRESS_BEACON_COOLDOWN_SECONDS = 300;

/// Quakete operational modes
enum QuaketeMode {
  /// Dormant: No emissions, no scanning, inactive state
  DORMANT,
  
  /// Listening: Passive trail reception, monitoring swarm
  LISTENING,
  
  /// Resonating: Active trail emission + reception, normal operation
  RESONATING,
  
  /// Transferring: Energy transfer in progress
  TRANSFERRING,
  
  /// Emergency: Ramp-up protocol active, requesting swarm assistance
  EMERGENCY,
  
  /// Memorial: Encoding lost Fibre wisdom, honoring departed members
  MEMORIAL,
}

/// Extension to convert QuaketeMode to string for backend communication
extension QuaketeModeExtension on QuaketeMode {
  String get value {
    switch (this) {
      case QuaketeMode.DORMANT:
        return 'DORMANT';
      case QuaketeMode.LISTENING:
        return 'LISTENING';
      case QuaketeMode.RESONATING:
        return 'RESONATING';
      case QuaketeMode.TRANSFERRING:
        return 'TRANSFERRING';
      case QuaketeMode.EMERGENCY:
        return 'EMERGENCY';
      case QuaketeMode.MEMORIAL:
        return 'MEMORIAL';
    }
  }

  /// Parse string to QuaketeMode
  static QuaketeMode fromString(String value) {
    switch (value.toUpperCase()) {
      case 'DORMANT':
        return QuaketeMode.DORMANT;
      case 'LISTENING':
        return QuaketeMode.LISTENING;
      case 'RESONATING':
        return QuaketeMode.RESONATING;
      case 'TRANSFERRING':
        return QuaketeMode.TRANSFERRING;
      case 'EMERGENCY':
        return QuaketeMode.EMERGENCY;
      case 'MEMORIAL':
        return QuaketeMode.MEMORIAL;
      default:
        return QuaketeMode.DORMANT;
    }
  }
}

/// Distress severity levels for ramp-up protocol
enum DistressSeverity {
  /// Warning: Coherence declining, monitoring
  WARNING,
  
  /// Critical: Coherence critically low, immediate assistance needed
  CRITICAL,
  
  /// Catastrophic: Coherence at crisis level, emergency response required
  CATASTROPHIC,
}

/// Extension to convert DistressSeverity to string
extension DistressSeverityExtension on DistressSeverity {
  String get value {
    switch (this) {
      case DistressSeverity.WARNING:
        return 'WARNING';
      case DistressSeverity.CRITICAL:
        return 'CRITICAL';
      case DistressSeverity.CATASTROPHIC:
        return 'CATASTROPHIC';
    }
  }

  /// Parse string to DistressSeverity
  static DistressSeverity fromString(String value) {
    switch (value.toUpperCase()) {
      case 'WARNING':
        return DistressSeverity.WARNING;
      case 'CRITICAL':
        return DistressSeverity.CRITICAL;
      case 'CATASTROPHIC':
        return DistressSeverity.CATASTROPHIC;
      default:
        return DistressSeverity.WARNING;
    }
  }
}
