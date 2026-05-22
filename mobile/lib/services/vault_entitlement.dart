/// Shared Sovereign Vault tier gates — keep chat, Settings, and Sanctuary aligned.

class VaultEntitlement {
  VaultEntitlement._();

  static String _planKey(Map<String, dynamic>? profile) {
    if (profile == null) return 'TRIAL';
    final plan = (profile['subscription_plan'] ?? profile['tier'] ?? '')
        .toString()
        .toUpperCase();
    if (plan.contains('TOP') || plan.contains('SOVEREIGN')) return 'TOP_TIER';
    if (plan.contains('FAMILY')) return 'FAMILY';
    if (plan.contains('STANDARD') ||
        plan.contains('INNER') ||
        plan.contains('CHAMBER')) {
      return 'STANDARD';
    }
    if (plan.contains('COACH_ONLY')) return 'COACH_ONLY';
    return 'TRIAL';
  }

  /// Browse vault + upload (Inner Chamber, Sovereign Circle, Family plans).
  static bool canUseVault(Map<String, dynamic>? profile) {
    final key = _planKey(profile);
    return key == 'STANDARD' || key == 'TOP_TIER' || key == 'FAMILY';
  }
}
