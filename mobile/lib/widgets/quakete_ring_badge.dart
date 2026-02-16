/// Quakete Ring Badge Widget
///
/// Displays the current Quakete Layer 8 solidarity status as a badge.
/// Shows: current mode, ring membership, active boosts, distress state.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/zefcp_provider.dart';
import '../quakete/constants.dart';

/// Badge showing Quakete solidarity status and ring membership.
class QuaketeRingBadge extends ConsumerWidget {
  /// Compact mode shows only the icon and mode label.
  final bool compact;

  const QuaketeRingBadge({
    super.key,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final modeAsync = ref.watch(quaketeModeProvider);
    final isDistressed = ref.watch(isInDistressProvider);

    return modeAsync.when(
      data: (mode) => _buildBadge(context, mode, isDistressed),
      loading: () => _buildInactiveBadge(),
      error: (_, __) => _buildInactiveBadge(),
    );
  }

  Widget _buildBadge(BuildContext context, QuaketeMode mode, bool isDistressed) {
    final config = _modeConfig(mode, isDistressed);

    if (compact) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: config.color.withOpacity(0.15),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: config.color.withOpacity(0.3),
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(config.icon, color: config.color, size: 14),
            const SizedBox(width: 4),
            Text(
              config.label,
              style: TextStyle(
                color: config.color,
                fontSize: 10,
                fontFamily: 'DM Sans',
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0A),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: config.color.withOpacity(0.3),
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Animated ring icon
          _buildRingIcon(config),
          const SizedBox(height: 8),

          // Mode label
          Text(
            config.label,
            style: TextStyle(
              color: config.color,
              fontSize: 12,
              fontFamily: 'DM Sans',
              fontWeight: FontWeight.w700,
            ),
          ),

          // Description
          Text(
            config.description,
            style: TextStyle(
              color: const Color(0xFF8B7355),
              fontSize: 10,
              fontFamily: 'DM Sans',
            ),
            textAlign: TextAlign.center,
          ),

          // Distress indicator
          if (isDistressed) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: const Color(0xFFEF4444).withOpacity(0.2),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.warning_amber,
                    color: Color(0xFFEF4444),
                    size: 12,
                  ),
                  const SizedBox(width: 4),
                  const Text(
                    'DISTRESS ACTIVE',
                    style: TextStyle(
                      color: Color(0xFFEF4444),
                      fontSize: 9,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildRingIcon(_ModeConfig config) {
    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(
          color: config.color.withOpacity(0.5),
          width: 2,
        ),
        color: config.color.withOpacity(0.1),
      ),
      child: Icon(
        config.icon,
        color: config.color,
        size: 24,
      ),
    );
  }

  Widget _buildInactiveBadge() {
    if (compact) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.radio_button_unchecked, color: Color(0xFF8B7355), size: 14),
            SizedBox(width: 4),
            Text(
              'Quakete',
              style: TextStyle(
                color: Color(0xFF8B7355),
                fontSize: 10,
                fontFamily: 'DM Sans',
              ),
            ),
          ],
        ),
      );
    }

    return const SizedBox.shrink();
  }

  _ModeConfig _modeConfig(QuaketeMode mode, bool isDistressed) {
    if (isDistressed) {
      return _ModeConfig(
        icon: Icons.sos,
        label: 'EMERGENCY',
        description: 'Distress beacon active — swarm responding',
        color: const Color(0xFFEF4444),
      );
    }

    switch (mode) {
      case QuaketeMode.DORMANT:
        return _ModeConfig(
          icon: Icons.nightlight_round,
          label: 'DORMANT',
          description: 'Solidarity protocol inactive',
          color: const Color(0xFF8B7355),
        );
      case QuaketeMode.LISTENING:
        return _ModeConfig(
          icon: Icons.hearing,
          label: 'LISTENING',
          description: 'Receiving trail emissions',
          color: const Color(0xFF4ECDC4),
        );
      case QuaketeMode.RESONATING:
        return _ModeConfig(
          icon: Icons.waves,
          label: 'RESONATING',
          description: 'Active in solidarity network',
          color: const Color(0xFFC9A962),
        );
      case QuaketeMode.TRANSFERRING:
        return _ModeConfig(
          icon: Icons.bolt,
          label: 'TRANSFERRING',
          description: 'Energy transfer in progress',
          color: const Color(0xFFE8D5A3),
        );
      case QuaketeMode.EMERGENCY:
        return _ModeConfig(
          icon: Icons.sos,
          label: 'EMERGENCY',
          description: 'Ramp-up protocol active',
          color: const Color(0xFFEF4444),
        );
      case QuaketeMode.MEMORIAL:
        return _ModeConfig(
          icon: Icons.auto_awesome,
          label: 'MEMORIAL',
          description: 'Preserving Fibre wisdom',
          color: const Color(0xFF9D4EDD),
        );
    }
  }
}

class _ModeConfig {
  final IconData icon;
  final String label;
  final String description;
  final Color color;

  const _ModeConfig({
    required this.icon,
    required this.label,
    required this.description,
    required this.color,
  });
}
