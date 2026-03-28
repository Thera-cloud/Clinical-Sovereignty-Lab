/**
 * Blue-Green-Orange Build Protocol Types — Phase 6f
 * Sovereign Sanctuary · Little Nate Infrastructure
 *
 * TypeScript type definitions for the versioned deployment system.
 * These types mirror the Python dataclasses in build_protocol.py (Phase 5c).
 *
 * File: vscode-extension/src/types/buildProtocol.ts
 * Add to existing types.ts or create as separate module.
 */

// =============================================================================
// BUILD VERSION
// =============================================================================

/** Semantic version with 4 components: breaking.major.minor.patch */
export interface BuildVersion {
  breaking: number;
  major: number;
  minor: number;
  patch: number;
  /** String representation: "v1.0.0.1" */
  display: string;
}

// =============================================================================
// BUILD STATUS
// =============================================================================

export type BuildPhase =
  | "idle"            // No build in progress
  | "building"        // Phase 1: Code being written
  | "testing_local"   // Phase 2: Local test suite running
  | "verifying"       // Phase 3: Orange cross-CLI verification
  | "promoting_blue"  // Phase 4a: Blue promoting
  | "soaking"         // Phase 4a: Blue soak period
  | "promoting_green" // Phase 4b: Green promoting
  | "rolling_back"    // Phase 5: Rollback in progress
  | "failed"          // Build failed at some stage
  | "complete";       // Both CLIs promoted successfully

export type BuildRole = "blue" | "green" | "orange";

export interface BuildStatus {
  phase: BuildPhase;
  current_version: string;       // e.g. "v1.0.0.0"
  building_version: string | null; // e.g. "v1.0.0.1" or null if idle
  my_role: BuildRole;
  peer_role: BuildRole | null;
  soak_remaining_seconds: number | null;
  last_error: string | null;
  started_at: string | null;     // ISO datetime
}

// =============================================================================
// TEST RESULTS
// =============================================================================

export interface TestResult {
  name: string;
  passed: boolean;
  duration_ms: number;
  error_message: string | null;
}

export interface TestSuiteResults {
  all_passed: boolean;
  tests: TestResult[];
  total_duration_ms: number;
  tested_version: string;
  tested_by: BuildRole;
  tested_at: string; // ISO datetime
}

// =============================================================================
// WEBSOCKET MESSAGE TYPES — Bridge ↔ Extension
// =============================================================================

/**
 * build_verify_request: Blue → Green (via bridge)
 * Sent when Blue has passed local tests and needs cross-CLI verification.
 */
export interface BuildVerifyRequest {
  type: "build_verify_request";
  version: string;
  diff_bundle: string;          // Compressed unified diff
  new_files: string[];
  deleted_files: string[];
  migrations: string[];
  test_results_blue: TestSuiteResults;
  checksum: string;             // SHA-256 of diff_bundle
  build_rules_version: string;
}

/**
 * build_verify_result: Green → Blue (via bridge)
 * Green's independent verification result.
 */
export interface BuildVerifyResult {
  type: "build_verify_result";
  version: string;
  verified: boolean;
  test_results_green: TestSuiteResults;
  rejection_reason: string | null;
  verified_at: string; // ISO datetime
}

/**
 * build_promote_green: Blue → Green
 * After Blue's soak period passes, signals Green to promote.
 */
export interface BuildPromoteGreen {
  type: "build_promote_green";
  version: string;
  soak_duration_seconds: number;
  soak_errors: number;
  blue_promoted_at: string; // ISO datetime
}

/**
 * build_promote_complete: Green → Blue
 * Green confirms it has promoted successfully.
 */
export interface BuildPromoteComplete {
  type: "build_promote_complete";
  version: string;
  migrations_applied: string[];
  green_promoted_at: string; // ISO datetime
}

/**
 * build_rollback: Either direction
 * Emergency rollback signal.
 */
export interface BuildRollback {
  type: "build_rollback";
  from_version: string;
  to_version: string;
  reason: string;
  initiated_by: BuildRole;
}

/**
 * build_status: Either direction (read-only, in _SENTINEL_SKIP)
 * Status query/response for the chat panel build indicator.
 */
export interface BuildStatusMessage {
  type: "build_status";
  status: BuildStatus;
}

/**
 * Union of all build-related WebSocket messages.
 */
export type BuildMessage =
  | BuildVerifyRequest
  | BuildVerifyResult
  | BuildPromoteGreen
  | BuildPromoteComplete
  | BuildRollback
  | BuildStatusMessage;

// =============================================================================
// EXTENSION STATE
// =============================================================================

/**
 * Build state tracked by the extension for UI rendering.
 * Updated via build_status messages from the bridge.
 */
export interface BuildPanelState {
  isBuilding: boolean;
  phase: BuildPhase;
  currentVersion: string;
  buildingVersion: string | null;
  myRole: BuildRole;
  testResults: TestSuiteResults | null;
  soakRemaining: number | null;
  lastError: string | null;
}
