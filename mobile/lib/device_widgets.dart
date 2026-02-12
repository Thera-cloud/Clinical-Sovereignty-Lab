// =============================================================================
// DEVICE MANAGEMENT WIDGETS
// Add to metrics_widgets.dart or create separate file
// =============================================================================

import 'package:flutter/material.dart';

// =============================================================================
// DEVICE BLOCKED DIALOG
// Shown when user tries to login from unregistered device at limit
// =============================================================================

class DeviceBlockedDialog extends StatelessWidget {
  final int deviceLimit;
  final List<String> existingDevices;
  final bool upgradeAvailable;
  final VoidCallback? onUpgrade;
  final VoidCallback? onContactSupport;
  final VoidCallback onDismiss;

  const DeviceBlockedDialog({
    super.key,
    required this.deviceLimit,
    required this.existingDevices,
    required this.upgradeAvailable,
    this.onUpgrade,
    this.onContactSupport,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF0A0A0F),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Warning Icon
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFFFF4757).withOpacity(0.2),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.devices_other,
                color: Color(0xFFFF4757),
                size: 48,
              ),
            ),
            
            const SizedBox(height: 20),
            
            const Text(
              "DEVICE LIMIT REACHED",
              style: TextStyle(
                color: Color(0xFFFF4757),
                fontWeight: FontWeight.bold,
                fontSize: 18,
                letterSpacing: 2,
              ),
            ),
            
            const SizedBox(height: 16),
            
            Text(
              "Your plan allows $deviceLimit device${deviceLimit > 1 ? 's' : ''}.\nYou must remove an existing device to login here.",
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey[400], fontSize: 14),
            ),
            
            const SizedBox(height: 20),
            
            // Existing Devices List
            if (existingDevices.isNotEmpty) ...[
              const Text(
                "REGISTERED DEVICES:",
                style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1),
              ),
              const SizedBox(height: 8),
              ...existingDevices.map((device) => Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.05),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.white.withOpacity(0.1)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.smartphone, color: Colors.grey, size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        device,
                        style: const TextStyle(color: Colors.white70, fontSize: 13),
                      ),
                    ),
                  ],
                ),
              )).toList(),
              const SizedBox(height: 16),
            ],
            
            // Upgrade Option (for Standard users)
            if (upgradeAvailable && onUpgrade != null) ...[
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      const Color(0xFFFFD700).withOpacity(0.1),
                      const Color(0xFFFF006E).withOpacity(0.1),
                    ],
                  ),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
                ),
                child: Column(
                  children: [
                    const Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.workspace_premium, color: Color(0xFFFFD700), size: 20),
                        SizedBox(width: 8),
                        Text(
                          "UPGRADE TO PREMIUM",
                          style: TextStyle(
                            color: Color(0xFFFFD700),
                            fontWeight: FontWeight.bold,
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      "Get up to 3 devices + metrics & family plans",
                      style: TextStyle(color: Colors.grey[400], fontSize: 12),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    ElevatedButton(
                      onPressed: onUpgrade,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFFD700),
                        foregroundColor: Colors.black,
                        minimumSize: const Size(double.infinity, 44),
                      ),
                      child: const Text("UPGRADE NOW"),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
            
            // Contact Support
            OutlinedButton.icon(
              onPressed: onContactSupport,
              icon: const Icon(Icons.support_agent, size: 18),
              label: const Text("CONTACT SUPPORT"),
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.grey,
                side: const BorderSide(color: Colors.grey),
                minimumSize: const Size(double.infinity, 44),
              ),
            ),
            
            const SizedBox(height: 12),
            
            TextButton(
              onPressed: onDismiss,
              child: const Text("DISMISS", style: TextStyle(color: Colors.grey)),
            ),
          ],
        ),
      ),
    );
  }
}

// =============================================================================
// DEVICE MANAGEMENT SCREEN (For Premium Users)
// =============================================================================

class DeviceManagementSheet extends StatelessWidget {
  final List<Map<String, dynamic>> devices;
  final int deviceLimit;
  final Function(String deviceId) onRemoveDevice;
  final VoidCallback onLogoutAll;

  const DeviceManagementSheet({
    super.key,
    required this.devices,
    required this.deviceLimit,
    required this.onRemoveDevice,
    required this.onLogoutAll,
  });

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      minChildSize: 0.3,
      maxChildSize: 0.9,
      expand: false,
      builder: (context, scrollController) => Container(
        decoration: const BoxDecoration(
          color: Color(0xFF0A0A0F),
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: SingleChildScrollView(
          controller: scrollController,
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Handle
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey[600],
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              
              const SizedBox(height: 20),
              
              // Header
              Row(
                children: [
                  const Icon(Icons.devices, color: Color(0xFF00FFFF), size: 28),
                  const SizedBox(width: 12),
                  const Text(
                    "MY DEVICES",
                    style: TextStyle(
                      color: Color(0xFF00FFFF),
                      fontWeight: FontWeight.bold,
                      fontSize: 18,
                      letterSpacing: 2,
                    ),
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      "${devices.length} / $deviceLimit",
                      style: const TextStyle(color: Colors.white70, fontSize: 12),
                    ),
                  ),
                ],
              ),
              
              const SizedBox(height: 8),
              Text(
                "Manage devices connected to your account",
                style: TextStyle(color: Colors.grey[500], fontSize: 13),
              ),
              
              const SizedBox(height: 24),
              
              // Device List
              ...devices.map((device) => _buildDeviceCard(context, device)).toList(),
              
              if (devices.isEmpty)
                Container(
                  padding: const EdgeInsets.all(40),
                  child: Column(
                    children: [
                      Icon(Icons.smartphone, color: Colors.grey[700], size: 48),
                      const SizedBox(height: 12),
                      Text(
                        "No devices registered",
                        style: TextStyle(color: Colors.grey[500]),
                      ),
                    ],
                  ),
                ),
              
              const SizedBox(height: 24),
              
              // Logout All Devices
              if (devices.length > 1)
                OutlinedButton.icon(
                  onPressed: () {
                    showDialog(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        backgroundColor: const Color(0xFF1A1A2E),
                        title: const Text("Logout All Devices?", style: TextStyle(color: Colors.white)),
                        content: const Text(
                          "This will require re-authentication on all devices including this one.",
                          style: TextStyle(color: Colors.grey),
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(ctx),
                            child: const Text("CANCEL"),
                          ),
                          ElevatedButton(
                            onPressed: () {
                              Navigator.pop(ctx);
                              onLogoutAll();
                            },
                            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                            child: const Text("LOGOUT ALL"),
                          ),
                        ],
                      ),
                    );
                  },
                  icon: const Icon(Icons.logout, size: 18),
                  label: const Text("LOGOUT ALL DEVICES"),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.red,
                    side: const BorderSide(color: Colors.red),
                    minimumSize: const Size(double.infinity, 48),
                  ),
                ),
              
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDeviceCard(BuildContext context, Map<String, dynamic> device) {
    final bool isCurrentDevice = device['is_current'] ?? false;
    final String deviceName = device['device_name'] ?? 'Unknown Device';
    final String lastSeen = device['last_seen'] ?? '';
    final String deviceId = device['device_id'] ?? '';
    
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: isCurrentDevice 
            ? const Color(0xFF00FFFF).withOpacity(0.1) 
            : const Color(0xFF1A1A2E),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isCurrentDevice 
              ? const Color(0xFF00FFFF).withOpacity(0.3)
              : Colors.transparent,
        ),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.05),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(
              _getDeviceIcon(deviceName),
              color: isCurrentDevice ? const Color(0xFF00FFFF) : Colors.grey,
              size: 24,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        deviceName,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w500,
                          fontSize: 14,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (isCurrentDevice) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFF00FFFF).withOpacity(0.2),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          "THIS DEVICE",
                          style: TextStyle(
                            color: Color(0xFF00FFFF),
                            fontSize: 8,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  "Last active: ${_formatLastSeen(lastSeen)}",
                  style: TextStyle(color: Colors.grey[500], fontSize: 11),
                ),
              ],
            ),
          ),
          if (!isCurrentDevice)
            IconButton(
              onPressed: () {
                showDialog(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    backgroundColor: const Color(0xFF1A1A2E),
                    title: const Text("Remove Device?", style: TextStyle(color: Colors.white)),
                    content: Text(
                      "Remove '$deviceName' from your account? They will need to re-authenticate.",
                      style: const TextStyle(color: Colors.grey),
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(ctx),
                        child: const Text("CANCEL"),
                      ),
                      ElevatedButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          onRemoveDevice(deviceId);
                        },
                        style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                        child: const Text("REMOVE"),
                      ),
                    ],
                  ),
                );
              },
              icon: const Icon(Icons.delete_outline, color: Colors.red, size: 20),
            ),
        ],
      ),
    );
  }

  IconData _getDeviceIcon(String deviceName) {
    final lower = deviceName.toLowerCase();
    if (lower.contains('iphone') || lower.contains('android') || lower.contains('phone')) {
      return Icons.smartphone;
    } else if (lower.contains('ipad') || lower.contains('tablet')) {
      return Icons.tablet;
    } else if (lower.contains('mac') || lower.contains('windows') || lower.contains('desktop')) {
      return Icons.computer;
    } else if (lower.contains('web') || lower.contains('browser')) {
      return Icons.web;
    }
    return Icons.devices_other;
  }

  String _formatLastSeen(String isoDate) {
    if (isoDate.isEmpty) return "Never";
    try {
      final dt = DateTime.parse(isoDate);
      final now = DateTime.now();
      final diff = now.difference(dt);
      
      if (diff.inMinutes < 5) return "Just now";
      if (diff.inMinutes < 60) return "${diff.inMinutes} min ago";
      if (diff.inHours < 24) return "${diff.inHours} hours ago";
      if (diff.inDays < 7) return "${diff.inDays} days ago";
      return "${dt.month}/${dt.day}/${dt.year}";
    } catch (e) {
      return isoDate;
    }
  }
}

// =============================================================================
// NEW DEVICE ALERT BANNER
// Shown when user logs in from a new device
// =============================================================================

class NewDeviceAlertBanner extends StatelessWidget {
  final VoidCallback onDismiss;
  final VoidCallback onViewDevices;

  const NewDeviceAlertBanner({
    super.key,
    required this.onDismiss,
    required this.onViewDevices,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            const Color(0xFF00F5D4).withOpacity(0.2),
            const Color(0xFF00FFFF).withOpacity(0.2),
          ],
        ),
        border: const Border(
          bottom: BorderSide(color: Color(0xFF00F5D4), width: 1),
        ),
      ),
      child: Row(
        children: [
          const Icon(Icons.verified_user, color: Color(0xFF00F5D4), size: 20),
          const SizedBox(width: 12),
          const Expanded(
            child: Text(
              "New device registered to your account",
              style: TextStyle(color: Colors.white, fontSize: 13),
            ),
          ),
          TextButton(
            onPressed: onViewDevices,
            child: const Text(
              "VIEW",
              style: TextStyle(color: Color(0xFF00F5D4), fontWeight: FontWeight.bold),
            ),
          ),
          IconButton(
            onPressed: onDismiss,
            icon: const Icon(Icons.close, color: Colors.grey, size: 18),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(),
          ),
        ],
      ),
    );
  }
}
