/// ZEFCP Status Bar Widget
///
/// Displays real-time ZEFCP Layer 1 transport status in a compact bar.
/// Shows: provisioning state, scan activity, fragment counts, battery mode.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/zefcp_provider.dart';
import '../zefcp/zefcp_service.dart';
import '../zefcp/battery_manager.dart';

/// Compact status bar showing ZEFCP transport health.
class ZefcpStatusBar extends ConsumerWidget {
  const ZefcpStatusBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statusAsync = ref.watch(zefcpStatusProvider);
    final batteryAsync = ref.watch(batteryProfileProvider);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0A),
        border: Border(
          bottom: BorderSide(
            color: const Color(0xFFC9A962).withOpacity(0.2),
          ),
        ),
      ),
      child: statusAsync.when(
        data: (status) => _buildStatusRow(context, status, batteryAsync),
        loading: () => _buildLoadingRow(),
        error: (e, _) => _buildErrorRow(e.toString()),
      ),
    );
  }

  Widget _buildStatusRow(
    BuildContext context,
    ZefcpStatus status,
    AsyncValue<BatteryProfile> batteryAsync,
  ) {
    final isActive = status.isRunning;
    final isProvisioned = status.isProvisioned;

    return Row(
      children: [
        // ZEFCP indicator
        Icon(
          isActive ? Icons.bluetooth_searching : Icons.bluetooth_disabled,
          color: isActive
              ? const Color(0xFF4ECDC4)
              : const Color(0xFF8B7355),
          size: 16,
        ),
        const SizedBox(width: 6),
        Text(
          'ZEFCP',
          style: TextStyle(
            color: isActive
                ? const Color(0xFFE8D5A3)
                : const Color(0xFF8B7355),
            fontSize: 11,
            fontFamily: 'DM Sans',
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(width: 8),

        // Provisioning status
        if (!isProvisioned)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: const Color(0xFFEF4444).withOpacity(0.2),
              borderRadius: BorderRadius.circular(4),
            ),
            child: const Text(
              'NOT PROVISIONED',
              style: TextStyle(
                color: Color(0xFFEF4444),
                fontSize: 9,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),

        // Fragment counters
        if (isProvisioned) ...[
          _metricChip(
            Icons.download,
            '${status.fragmentsCaptured}',
            const Color(0xFF4ECDC4),
          ),
          const SizedBox(width: 4),
          _metricChip(
            Icons.upload,
            '${status.fragmentsSent}',
            const Color(0xFFC9A962),
          ),
        ],

        const Spacer(),

        // Battery mode
        batteryAsync.when(
          data: (profile) => _batteryIndicator(profile),
          loading: () => const SizedBox.shrink(),
          error: (_, __) => const SizedBox.shrink(),
        ),
      ],
    );
  }

  Widget _metricChip(IconData icon, String value, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: color.withOpacity(0.7), size: 12),
        const SizedBox(width: 2),
        Text(
          value,
          style: TextStyle(
            color: color,
            fontSize: 10,
            fontFamily: 'DM Sans',
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }

  Widget _batteryIndicator(BatteryProfile profile) {
    final Color color;
    final IconData icon;

    switch (profile.mode) {
      case BatteryMode.aggressive:
        color = const Color(0xFF4ECDC4);
        icon = Icons.battery_full;
        break;
      case BatteryMode.standard:
        color = const Color(0xFFC9A962);
        icon = Icons.battery_std;
        break;
      case BatteryMode.reduced:
        color = const Color(0xFFEF4444);
        icon = Icons.battery_alert;
        break;
      case BatteryMode.minimal:
        color = const Color(0xFFEF4444);
        icon = Icons.battery_0_bar;
        break;
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: color, size: 14),
        const SizedBox(width: 2),
        Text(
          '${profile.level}%',
          style: TextStyle(
            color: color,
            fontSize: 10,
            fontFamily: 'DM Sans',
          ),
        ),
      ],
    );
  }

  Widget _buildLoadingRow() {
    return Row(
      children: [
        const SizedBox(
          width: 12,
          height: 12,
          child: CircularProgressIndicator(
            strokeWidth: 1.5,
            color: Color(0xFF8B7355),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          'ZEFCP initializing...',
          style: TextStyle(
            color: const Color(0xFF8B7355),
            fontSize: 11,
            fontFamily: 'DM Sans',
          ),
        ),
      ],
    );
  }

  Widget _buildErrorRow(String error) {
    return Row(
      children: [
        const Icon(
          Icons.error_outline,
          color: Color(0xFFEF4444),
          size: 14,
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            'ZEFCP error: $error',
            style: const TextStyle(
              color: Color(0xFFEF4444),
              fontSize: 10,
              fontFamily: 'DM Sans',
            ),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}
