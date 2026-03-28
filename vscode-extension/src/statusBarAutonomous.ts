/**
 * Autonomous Status Bar Integration — Phase 7d
 * Sovereign Sanctuary · Little Nate Infrastructure
 *
 * Extends the existing statusBar.ts to show autonomous health indicators.
 * Reads health_status WebSocket messages from the bridge.
 *
 * Current: ⚡ LN: Local
 * After:   ⚡ LN: Local | 10/10 LEARN | 47 crystals
 *          ⚠ LN: Local | 8/10 FIX (db_pool, redis)
 *
 * File: vscode-extension/src/statusBarAutonomous.ts
 * Lines: ~80
 *
 * INTEGRATION:
 * In your existing statusBar.ts or chatPanel.ts, add a WebSocket message handler:
 *
 *   case "health_status":
 *     updateAutonomousStatus(msg);
 *     break;
 *
 * The str_replace for statusBar.ts is shown at the bottom of this file.
 */

import * as vscode from "vscode";

// Types matching the Python HealthReport.to_dict() output
interface HealthStatusMessage {
  type: "health_status";
  score: number;
  total: number;
  all_passed: boolean;
  mode: "LEARN" | "FIX" | "ERROR" | "STARTING";
  cycles: number;
  total_crystals: number;
  failed: string[];
  gates: Array<{
    name: string;
    passed: boolean;
    detail: string;
    duration_ms: number;
  }>;
}

let healthStatusItem: vscode.StatusBarItem | undefined;
let lastHealthMessage: HealthStatusMessage | undefined;

/**
 * Create the autonomous health status bar item.
 * Call once during extension activation, after the main status bar item.
 *
 * Priority should be slightly lower than the main LN: Local/Cloud item
 * so it appears to the right of it.
 */
export function createHealthStatusBarItem(
  priority: number = 99
): vscode.StatusBarItem {
  healthStatusItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    priority
  );
  healthStatusItem.text = "$(loading~spin) Health: ...";
  healthStatusItem.tooltip = "Autonomous health gates — waiting for first check";
  healthStatusItem.command = "sovereign-sanctuary.showHealthDetails";
  healthStatusItem.show();
  return healthStatusItem;
}

/**
 * Update the status bar with a new health report.
 * Called from the WebSocket message handler when type === "health_status".
 */
export function updateAutonomousStatus(msg: HealthStatusMessage): void {
  lastHealthMessage = msg;
  if (!healthStatusItem) return;

  const { score, total, mode, total_crystals, failed } = msg;

  if (mode === "LEARN") {
    healthStatusItem.text = `$(pass) ${score}/${total} LEARN | ${total_crystals} crystals`;
    healthStatusItem.backgroundColor = undefined; // Default
    healthStatusItem.tooltip = formatTooltip(msg);
  } else if (mode === "FIX") {
    const failedStr = failed.slice(0, 3).join(", ");
    healthStatusItem.text = `$(warning) ${score}/${total} FIX (${failedStr})`;
    healthStatusItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
    healthStatusItem.tooltip = formatTooltip(msg);
  } else if (mode === "ERROR") {
    healthStatusItem.text = `$(error) Health: ERROR`;
    healthStatusItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground"
    );
    healthStatusItem.tooltip = "Autonomous controller encountered an error";
  } else {
    healthStatusItem.text = `$(loading~spin) Health: starting...`;
    healthStatusItem.tooltip = "Waiting for first health check";
  }
}

/**
 * Format detailed tooltip showing all gate results.
 */
function formatTooltip(msg: HealthStatusMessage): string {
  const lines = [
    `Autonomous Mode: ${msg.mode}`,
    `Health: ${msg.score}/${msg.total}`,
    `Crystals today: ${msg.total_crystals}`,
    `Cycles: ${msg.cycles}`,
    "",
    "Gates:",
  ];
  for (const gate of msg.gates) {
    const icon = gate.passed ? "✓" : "✗";
    lines.push(`  ${icon} ${gate.name}: ${gate.detail} (${gate.duration_ms}ms)`);
  }
  if (msg.failed.length > 0) {
    lines.push("");
    lines.push("Click to view pending fixes");
  }
  return lines.join("\n");
}

/**
 * Get the last health message for use in other components.
 */
export function getLastHealthStatus(): HealthStatusMessage | undefined {
  return lastHealthMessage;
}

/**
 * Dispose the status bar item on deactivation.
 */
export function disposeHealthStatusBar(): void {
  healthStatusItem?.dispose();
}

// =============================================================================
// COMMAND: Show Health Details
// =============================================================================

/**
 * Register the command that shows full health details in a quick pick.
 * Call during extension activation:
 *   context.subscriptions.push(registerHealthDetailsCommand());
 */
export function registerHealthDetailsCommand(): vscode.Disposable {
  return vscode.commands.registerCommand(
    "sovereign-sanctuary.showHealthDetails",
    async () => {
      if (!lastHealthMessage) {
        vscode.window.showInformationMessage(
          "No health data yet — waiting for first autonomous check."
        );
        return;
      }
      const items = lastHealthMessage.gates.map((g) => ({
        label: `${g.passed ? "$(pass)" : "$(error)"} ${g.name}`,
        description: g.detail,
        detail: `${g.duration_ms}ms`,
      }));
      await vscode.window.showQuickPick(items, {
        title: `Health: ${lastHealthMessage.score}/${lastHealthMessage.total} — ${lastHealthMessage.mode}`,
        placeHolder: "Gate details (read-only)",
      });
    }
  );
}


// =============================================================================
// STR_REPLACE INSTRUCTIONS for statusBar.ts
// =============================================================================

/*
 * To integrate into your existing extension:
 *
 * 1. In extension.ts activate():
 *
 *    import { createHealthStatusBarItem, registerHealthDetailsCommand,
 *             disposeHealthStatusBar } from './statusBarAutonomous';
 *
 *    // After creating the main status bar item:
 *    const healthBar = createHealthStatusBarItem(99);
 *    context.subscriptions.push(healthBar);
 *    context.subscriptions.push(registerHealthDetailsCommand());
 *
 * 2. In your WebSocket message handler (chatPanel.ts or wherever you handle bridge messages):
 *
 *    import { updateAutonomousStatus } from './statusBarAutonomous';
 *
 *    // In the message switch:
 *    case "health_status":
 *      updateAutonomousStatus(msg);
 *      break;
 *
 * 3. In extension.ts deactivate():
 *
 *    disposeHealthStatusBar();
 */
