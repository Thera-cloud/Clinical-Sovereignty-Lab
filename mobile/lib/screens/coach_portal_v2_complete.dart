// =============================================================================
// COACH PORTAL v2.0 - PHASE 1 ENHANCEMENT
// Part 1: Main Coach Portal with Tab Navigation
// =============================================================================

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:async';
import 'dart:convert';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:http/http.dart' as http;
import 'settings_screen.dart';
import '../config/app_config.dart' as central_config;

// -----------------------------------------------------------------------------
// CONFIGURATION
// -----------------------------------------------------------------------------
class AppConfig {
  static String get serverUrl => central_config.AppConfig.wsUrl;
  static const String appName = 'Sovereign Sanctuary';
  static const String consentVersion = 'v13.0_2026';
}

// =============================================================================
// MAIN COACH PORTAL WITH TAB NAVIGATION
// =============================================================================
class CoachPortalScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String username;
  final String password;

  const CoachPortalScreen({
    super.key,
    required this.currentUserProfile,
    required this.username,
    required this.password,
  });

  @override
  State<CoachPortalScreen> createState() => _CoachPortalScreenState();
}

class _CoachPortalScreenState extends State<CoachPortalScreen> {
  WebSocketChannel? _socket;
  int _currentTabIndex = 0;
  
  List<dynamic> _clients = [];
  List<dynamic> _schedule = [];
  List<dynamic> _sessions = [];
  List<dynamic> _sessionHistory = [];
  bool _isLoading = true;
  String _statusMessage = "Initializing...";

  final List<_TabItem> _tabs = [
    _TabItem(icon: Icons.people, label: 'Clients'),
    _TabItem(icon: Icons.calendar_today, label: 'Calendar'),
    _TabItem(icon: Icons.videocam, label: 'Sessions'),
    _TabItem(icon: Icons.psychology, label: 'Nate AI'),
    _TabItem(icon: Icons.account_balance, label: 'QuickBooks'),
  ];

  @override
  void initState() {
    super.initState();
    _connectToBridge();
  }

  int _reconnectAttempts = 0;
  final StreamController<Map<String, dynamic>> _messageController = StreamController<Map<String, dynamic>>.broadcast();

  void _connectToBridge() {
    setState(() => _statusMessage = "Connecting to HQ...");
    try {
      _socket = WebSocketChannel.connect(Uri.parse(AppConfig.serverUrl));
      _socket!.stream.listen(
        _handleSocketMessage,
        onError: (e) {
          debugPrint('[CoachPortal] WebSocket error: $e');
          if (mounted) {
            setState(() => _statusMessage = "Connection Failed. Reconnecting...");
            _scheduleReconnect();
          }
        },
        onDone: () {
          debugPrint('[CoachPortal] WebSocket closed');
          if (mounted) {
            setState(() => _statusMessage = "Disconnected. Reconnecting...");
            _scheduleReconnect();
          }
        },
      );

      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": widget.username,
        "password": widget.password,
        "expected_role": "COACH",
      }));
      _reconnectAttempts = 0;
    } catch (e) {
      debugPrint('[CoachPortal] Connection error: $e');
      if (mounted) setState(() => _statusMessage = "Connection Error");
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_reconnectAttempts >= 5) {
      if (mounted) setState(() => _statusMessage = "Unable to reach server.");
      return;
    }
    _reconnectAttempts++;
    final delay = Duration(milliseconds: 500 * (1 << (_reconnectAttempts - 1)).clamp(1, 16));
    Future.delayed(delay, () {
      if (mounted) _connectToBridge();
    });
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final data = jsonDecode(message);
      if (data is Map<String, dynamic>) {
        _messageController.add(data);
      }
      
      switch (data['type']) {
        case 'login_success':
          _fetchAllData();
          break;
        case 'coach_dashboard_data':
          if (mounted) {
            setState(() {
              _clients = data['data']['clients'] ?? [];
              _schedule = data['data']['schedule'] ?? [];
              _isLoading = false;
            });
          }
          break;
        case 'coach_sessions_data':
          if (mounted) {
            setState(() => _sessions = data['data']['sessions'] ?? []);
          }
          break;
        case 'coach_calendar_data':
          if (mounted) {
            setState(() => _schedule = data['data']['schedule'] ?? []);
          }
          break;
        case 'session_history_data':
          if (mounted) {
            setState(() => _sessionHistory = data['data']?['sessions'] ?? data['sessions'] ?? []);
          }
          break;
        case 'error':
          if (mounted) {
            setState(() => _statusMessage = "Error: ${data['message']}");
          }
          break;
      }
    } catch (e) {
      print("Error parsing socket message: $e");
    }
  }

  void _fetchAllData() {
    _socket?.sink.add(jsonEncode({"type": "fetch_coach_dashboard"}));
    _socket?.sink.add(jsonEncode({"type": "fetch_coach_sessions"}));
    _socket?.sink.add(jsonEncode({"type": "fetch_coach_calendar"}));
  }

  void _sendMessage(Map<String, dynamic> msg) {
    _socket?.sink.add(jsonEncode(msg));
  }

  @override
  void dispose() {
    _messageController.close();
    _socket?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      appBar: _buildAppBar(),
      body: _isLoading ? _buildLoadingState() : _buildCurrentTab(),
      bottomNavigationBar: _buildBottomNav(),
    );
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      title: const Text(
        "COACH PORTAL",
        style: TextStyle(
          fontFamily: 'Courier',
          color: Color(0xFFFFD700),
          fontWeight: FontWeight.bold,
          letterSpacing: 2,
        ),
      ),
      backgroundColor: const Color(0xFF1A1A2E),
      elevation: 0,
      actions: [
        IconButton(
          icon: const Icon(Icons.refresh, color: Colors.grey),
          onPressed: () {
            setState(() => _isLoading = true);
            _fetchAllData();
          },
        ),
        IconButton(
          icon: const Icon(Icons.settings, color: Color(0xFFC9A962)),
          tooltip: 'Settings',
          onPressed: () {
            Navigator.push(context, MaterialPageRoute(
              builder: (_) => CoachSettingsScreen(
                profile: widget.currentUserProfile,
                socket: _socket,
                onLogout: _logout,
                messageStream: _messageController.stream,
              ),
            ));
          },
        ),
        IconButton(
          icon: const Icon(Icons.power_settings_new, color: Colors.red),
          onPressed: _logout,
        ),
      ],
    );
  }

  Widget _buildLoadingState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const CircularProgressIndicator(color: Color(0xFFFFD700)),
          const SizedBox(height: 20),
          Text(_statusMessage, style: const TextStyle(color: Colors.grey)),
        ],
      ),
    );
  }

  Widget _buildCurrentTab() {
    switch (_currentTabIndex) {
      case 0:
        return ClientsTab(
          clients: _clients,
          onClientTap: _showClientActions,
        );
      case 1:
        return CalendarTab(
          schedule: _schedule,
          onSessionTap: _showSessionActions,
          onAddAvailability: _showSchedulingDialog,
        );
      case 2:
        return SessionsTab(
          sessions: _sessions,
          onSessionTap: _showSessionDetails,
        );
      case 3:
        return AskNateTab(
          socket: _socket,
          coachProfile: widget.currentUserProfile,
        );
      case 4:
        return CoachQuickBooksTab(
          coachProfile: widget.currentUserProfile,
        );
      default:
        return const Center(child: Text("Unknown Tab"));
    }
  }

  Widget _buildBottomNav() {
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xFF111111),
        border: Border(top: BorderSide(color: Color(0xFF222222))),
      ),
      child: Row(
        children: _tabs.asMap().entries.map((entry) {
          final index = entry.key;
          final tab = entry.value;
          final isActive = index == _currentTabIndex;
          
          return Expanded(
            child: InkWell(
              onTap: () => setState(() => _currentTabIndex = index),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  border: Border(
                    top: BorderSide(
                      color: isActive ? const Color(0xFFFFD700) : Colors.transparent,
                      width: 2,
                    ),
                  ),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      tab.icon,
                      color: isActive ? const Color(0xFFFFD700) : Colors.grey,
                      size: 20,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      tab.label,
                      style: TextStyle(
                        color: isActive ? const Color(0xFFFFD700) : Colors.grey,
                        fontSize: 10,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  void _showClientActions(Map<String, dynamic> client) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF1A1A1A),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => ClientActionsSheet(
        client: client,
        onAskNate: () {
          Navigator.pop(ctx);
          setState(() => _currentTabIndex = 3);
        },
        onPreSessionBrief: () {
          Navigator.pop(ctx);
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => PreSessionBriefScreen(
                client: client,
                socket: _socket,
              ),
            ),
          );
        },
        onViewHistory: () {
          Navigator.pop(ctx);
          _showClientHistory(client);
        },
      ),
    );
  }

  void _showSessionActions(Map<String, dynamic> session) {
    showDialog(
      context: context,
      builder: (ctx) => SessionActionsDialog(
        session: session,
        onJoin: () {
          Navigator.pop(ctx);
          _joinSession(session);
        },
        onCancel: () {
          Navigator.pop(ctx);
          _showCancelDialog(session);
        },
        onReschedule: () {
          Navigator.pop(ctx);
          _showRescheduleDialog(session);
        },
      ),
    );
  }

  void _showSessionDetails(Map<String, dynamic> session) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => CoachingAdviceScreen(
          session: session,
          socket: _socket,
        ),
      ),
    );
  }

  void _joinSession(Map<String, dynamic> session) async {
    final zoomUrl = session['zoom_url'] ?? session['meeting_url'] ?? session['join_url'];
    if (zoomUrl != null && zoomUrl.toString().isNotEmpty) {
      final uri = Uri.parse(zoomUrl.toString());
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text("Could not open: $zoomUrl")),
          );
        }
      }
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("No meeting URL available for this session.")),
        );
      }
    }
  }

  void _showCancelDialog(Map<String, dynamic> session) {
    showDialog(
      context: context,
      builder: (ctx) => CancelSessionDialog(
        session: session,
        onConfirm: (reason, sendReschedule) {
          _sendMessage({
            "type": "cancel_session",
            "session_id": session['id'],
            "reason": reason,
            "send_reschedule_link": sendReschedule,
          });
          Navigator.pop(ctx);
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text("Session cancelled. Client notified.")),
          );
        },
      ),
    );
  }

  void _showClientHistory(Map<String, dynamic> client) {
    _sendMessage({
      "type": "get_session_history",
      "client_id": client['id']?.toString() ?? '',
    });
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        title: Text(
          "Session History — ${client['name'] ?? 'Client'}",
          style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16),
        ),
        content: SizedBox(
          width: double.maxFinite,
          height: 300,
          child: (_sessionHistory.isEmpty)
            ? const Center(child: Text('No session history yet.', style: TextStyle(color: Colors.grey)))
            : ListView.builder(
                itemCount: _sessionHistory.length,
                itemBuilder: (_, i) {
                  final s = _sessionHistory[i];
                  return ListTile(
                    leading: Icon(
                      s['status'] == 'completed' ? Icons.check_circle : Icons.pending,
                      color: s['status'] == 'completed' ? Colors.green : Colors.orange,
                      size: 20,
                    ),
                    title: Text(
                      s['date']?.toString() ?? s['scheduled_at']?.toString() ?? 'Unknown date',
                      style: const TextStyle(color: Colors.white, fontSize: 13),
                    ),
                    subtitle: Text(
                      '${s['duration_minutes'] ?? '?'} min — ${s['status'] ?? 'unknown'}',
                      style: const TextStyle(color: Colors.grey, fontSize: 11),
                    ),
                  );
                },
              ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close', style: TextStyle(color: Color(0xFFC9A962))),
          ),
        ],
      ),
    );
  }

  void _showRescheduleDialog(Map<String, dynamic> session) {
    DateTime selectedDate = DateTime.now().add(const Duration(days: 1));
    TimeOfDay selectedTime = const TimeOfDay(hour: 10, minute: 0);

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF1A1A1A),
          title: const Text('Reschedule Session', style: TextStyle(color: Color(0xFFC9A962))),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.calendar_today, color: Color(0xFFC9A962)),
                title: Text(
                  '${selectedDate.month}/${selectedDate.day}/${selectedDate.year}',
                  style: const TextStyle(color: Colors.white),
                ),
                onTap: () async {
                  final picked = await showDatePicker(
                    context: ctx,
                    initialDate: selectedDate,
                    firstDate: DateTime.now(),
                    lastDate: DateTime.now().add(const Duration(days: 90)),
                  );
                  if (picked != null) setDialogState(() => selectedDate = picked);
                },
              ),
              ListTile(
                leading: const Icon(Icons.access_time, color: Color(0xFFC9A962)),
                title: Text(
                  selectedTime.format(ctx),
                  style: const TextStyle(color: Colors.white),
                ),
                onTap: () async {
                  final picked = await showTimePicker(context: ctx, initialTime: selectedTime);
                  if (picked != null) setDialogState(() => selectedTime = picked);
                },
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962)),
              onPressed: () {
                final dt = DateTime(
                  selectedDate.year, selectedDate.month, selectedDate.day,
                  selectedTime.hour, selectedTime.minute,
                );
                _sendMessage({
                  "type": "reschedule_session",
                  "session_id": session['id'],
                  "new_datetime": dt.toIso8601String(),
                });
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text("Session rescheduled. Client notified.")),
                );
              },
              child: const Text('Reschedule', style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  void _showSchedulingDialog() {
    showDialog(
      context: context,
      builder: (ctx) => SchedulerDialog(
        onPublish: (slot) {
          _sendMessage({
            "type": "update_availability",
            "slots": [slot],
          });
          Navigator.pop(ctx);
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text("Availability published")),
          );
        },
      ),
    );
  }

  void _logout() {
    _socket?.sink.close();
    Navigator.of(context).pushReplacementNamed('/lobby');
  }
}

class _TabItem {
  final IconData icon;
  final String label;
  _TabItem({required this.icon, required this.label});
}
// =============================================================================
// COACH PORTAL v2.0 - Part 2: Clients Tab & Calendar Tab
// =============================================================================

// TAB 1: CLIENTS TAB
class ClientsTab extends StatelessWidget {
  final List<dynamic> clients;
  final Function(Map<String, dynamic>) onClientTap;

  const ClientsTab({
    super.key,
    required this.clients,
    required this.onClientTap,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                "ASSIGNED CLIENTS",
                style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFD700).withOpacity(0.2),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  "${clients.length} Active",
                  style: const TextStyle(color: Color(0xFFFFD700), fontSize: 10),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: clients.isEmpty
              ? const Center(
                  child: Text("No clients assigned yet.",
                      style: TextStyle(color: Colors.grey, fontStyle: FontStyle.italic)),
                )
              : ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: clients.length,
                  itemBuilder: (ctx, i) => _buildClientCard(clients[i]),
                ),
        ),
      ],
    );
  }

  Widget _buildClientCard(dynamic client) {
    final Map<String, dynamic> c = client is Map<String, dynamic> 
        ? client : {'name': 'Unknown', 'id': 'N/A'};
    final bool isTopTier = c['tier'] == 'TOP_TIER';
    final String? nextSession = c['next_session'];

    return Card(
      color: isTopTier ? const Color(0xFF1A1810) : const Color(0xFF1A1A1A),
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: isTopTier ? const Color(0xFFFFD700).withOpacity(0.3) : const Color(0xFF252525),
        ),
      ),
      child: InkWell(
        onTap: () => onClientTap(c),
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            children: [
              Row(
                children: [
                  CircleAvatar(
                    backgroundColor: isTopTier ? const Color(0xFFFFD700) : Colors.blueAccent,
                    child: const Icon(Icons.person, color: Colors.white),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(c['name'] ?? 'Unknown',
                                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 14)),
                            if (isTopTier) ...[
                              const SizedBox(width: 6),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                decoration: BoxDecoration(
                                  gradient: const LinearGradient(colors: [Color(0xFFFFD700), Color(0xFFFF8C00)]),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: const Text("⭐ TOP TIER",
                                    style: TextStyle(color: Colors.black, fontSize: 8, fontWeight: FontWeight.bold)),
                              ),
                            ],
                          ],
                        ),
                        Text("ID: ${c['id'] ?? 'N/A'}", style: const TextStyle(color: Colors.grey, fontSize: 11)),
                      ],
                    ),
                  ),
                  if (nextSession != null)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.green.withOpacity(0.1),
                        border: Border.all(color: Colors.green.withOpacity(0.3)),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text("Next: $nextSession", style: const TextStyle(color: Colors.green, fontSize: 10)),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Builder(builder: (ctx) => Row(
                children: [
                  _buildActionButton(Icons.videocam, "Join Session", Colors.green, () {
                    final link = client['zoom_link'] ?? client['meeting_url'] ?? '';
                    if (link.toString().isNotEmpty) {
                      launchUrl(Uri.parse(link.toString()));
                    } else {
                      ScaffoldMessenger.of(ctx).showSnackBar(
                        const SnackBar(content: Text('No session link available')),
                      );
                    }
                  }),
                  const SizedBox(width: 8),
                  _buildActionButton(Icons.chat, "Ask Nate", Colors.cyan, () {
                    onClientTap(client);
                  }),
                  const SizedBox(width: 8),
                  _buildActionButton(Icons.description, "Pre-Brief", const Color(0xFFC9A962), () {
                    onClientTap(client);
                  }),
                  const SizedBox(width: 8),
                  _buildActionButton(Icons.history, "History", Colors.grey, () {
                    onClientTap(client);
                  }),
                ],
              )),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildActionButton(IconData icon, String label, Color color, VoidCallback onTap) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: color.withOpacity(0.1),
            border: Border.all(color: color.withOpacity(0.3)),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            children: [
              Icon(icon, color: color, size: 16),
              const SizedBox(height: 4),
              Text(label, style: TextStyle(color: color, fontSize: 9), textAlign: TextAlign.center),
            ],
          ),
        ),
      ),
    );
  }
}

// TAB 2: CALENDAR TAB
class CalendarTab extends StatefulWidget {
  final List<dynamic> schedule;
  final Function(Map<String, dynamic>) onSessionTap;
  final VoidCallback onAddAvailability;

  const CalendarTab({
    super.key,
    required this.schedule,
    required this.onSessionTap,
    required this.onAddAvailability,
  });

  @override
  State<CalendarTab> createState() => _CalendarTabState();
}

class _CalendarTabState extends State<CalendarTab> {
  DateTime _selectedMonth = DateTime.now();
  int? _selectedDay;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildCalendarHeader(),
          const SizedBox(height: 16),
          _buildCalendarGrid(),
          const SizedBox(height: 20),
          _buildTodaysSessions(),
        ],
      ),
    );
  }

  Widget _buildCalendarHeader() {
    final monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
                        'July', 'August', 'September', 'October', 'November', 'December'];
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Row(
          children: [
            IconButton(
              icon: const Icon(Icons.chevron_left, color: Color(0xFFFFD700)),
              onPressed: () => setState(() => _selectedMonth = DateTime(_selectedMonth.year, _selectedMonth.month - 1)),
            ),
            Text("${monthNames[_selectedMonth.month - 1]} ${_selectedMonth.year}",
                style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600)),
            IconButton(
              icon: const Icon(Icons.chevron_right, color: Color(0xFFFFD700)),
              onPressed: () => setState(() => _selectedMonth = DateTime(_selectedMonth.year, _selectedMonth.month + 1)),
            ),
          ],
        ),
        ElevatedButton.icon(
          onPressed: widget.onAddAvailability,
          icon: const Icon(Icons.add, size: 16),
          label: const Text("Add Availability", style: TextStyle(fontSize: 11)),
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFFFFD700).withOpacity(0.1),
            foregroundColor: const Color(0xFFFFD700),
            side: BorderSide(color: const Color(0xFFFFD700).withOpacity(0.3)),
          ),
        ),
      ],
    );
  }

  Widget _buildCalendarGrid() {
    final dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    final firstDay = DateTime(_selectedMonth.year, _selectedMonth.month, 1);
    final lastDay = DateTime(_selectedMonth.year, _selectedMonth.month + 1, 0);
    final startWeekday = firstDay.weekday % 7;
    final today = DateTime.now();

    List<Widget> cells = [];

    for (var day in dayNames) {
      cells.add(Center(child: Text(day, style: const TextStyle(color: Colors.grey, fontSize: 10))));
    }

    final prevMonth = DateTime(_selectedMonth.year, _selectedMonth.month, 0);
    for (int i = startWeekday - 1; i >= 0; i--) {
      cells.add(_buildDayCell(prevMonth.day - i, isOtherMonth: true));
    }

    for (int day = 1; day <= lastDay.day; day++) {
      final isToday = today.year == _selectedMonth.year && today.month == _selectedMonth.month && today.day == day;
      final hasSessions = _dayHasSessions(day);
      cells.add(_buildDayCell(day, isToday: isToday, hasSessions: hasSessions, isSelected: _selectedDay == day,
          onTap: () => setState(() => _selectedDay = day)));
    }

    final remaining = 42 - cells.length;
    for (int i = 1; i <= remaining; i++) {
      cells.add(_buildDayCell(i, isOtherMonth: true));
    }

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF151515),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF252525)),
      ),
      padding: const EdgeInsets.all(8),
      child: GridView.count(crossAxisCount: 7, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), children: cells),
    );
  }

  Widget _buildDayCell(int day, {bool isOtherMonth = false, bool isToday = false, bool hasSessions = false, bool isSelected = false, VoidCallback? onTap}) {
    return InkWell(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.all(2),
        decoration: BoxDecoration(
          color: isToday ? const Color(0xFFFFD700).withOpacity(0.2) : isSelected ? Colors.blue.withOpacity(0.2) : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: isToday ? Border.all(color: const Color(0xFFFFD700)) : null,
        ),
        child: Stack(
          alignment: Alignment.center,
          children: [
            Text(day.toString(), style: TextStyle(color: isOtherMonth ? Colors.grey.shade800 : Colors.white, fontSize: 12)),
            if (hasSessions)
              Positioned(bottom: 4, child: Container(width: 6, height: 6, decoration: const BoxDecoration(color: Colors.green, shape: BoxShape.circle))),
          ],
        ),
      ),
    );
  }

  bool _dayHasSessions(int day) {
    return widget.schedule.any((s) {
      final dateStr = s['date'] ?? '';
      if (dateStr.isEmpty) return false;
      try {
        final date = DateTime.parse(dateStr);
        return date.day == day && date.month == _selectedMonth.month && date.year == _selectedMonth.year;
      } catch (e) {
        return false;
      }
    });
  }

  Widget _buildTodaysSessions() {
    final todaySessions = widget.schedule.where((s) {
      final dateStr = s['date'] ?? '';
      if (dateStr.isEmpty) return false;
      try {
        final date = DateTime.parse(dateStr);
        final today = DateTime.now();
        return date.day == today.day && date.month == today.month && date.year == today.year;
      } catch (e) {
        return false;
      }
    }).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("TODAY'S SESSIONS", style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5)),
        const SizedBox(height: 12),
        if (todaySessions.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(border: Border.all(color: Colors.white10), borderRadius: BorderRadius.circular(8)),
            child: const Center(child: Text("No sessions scheduled for today.", style: TextStyle(color: Colors.grey, fontStyle: FontStyle.italic))),
          )
        else
          ...todaySessions.map((s) => _buildSessionCard(s)).toList(),
      ],
    );
  }

  Widget _buildSessionCard(dynamic session) {
    final Map<String, dynamic> s = session is Map<String, dynamic> ? session : {'time': 'Unknown', 'client': 'Unknown'};
    final isConfirmed = s['status'] == 'confirmed';

    return Card(
      color: const Color(0xFF1A1A1A),
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: const BorderSide(color: Color(0xFF252525))),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(s['time'] ?? 'Unknown', style: const TextStyle(color: Color(0xFFFFD700), fontSize: 16, fontWeight: FontWeight.w600)),
                    Text("Today, ${DateTime.now().month}/${DateTime.now().day}", style: const TextStyle(color: Colors.grey, fontSize: 11)),
                  ],
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: isConfirmed ? Colors.green.withOpacity(0.2) : Colors.orange.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(isConfirmed ? "Confirmed" : "Pending", style: TextStyle(color: isConfirmed ? Colors.green : Colors.orange, fontSize: 10, fontWeight: FontWeight.w500)),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                const CircleAvatar(radius: 18, backgroundColor: Color(0xFFFFD700), child: Icon(Icons.person, color: Colors.white, size: 18)),
                const SizedBox(width: 10),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(s['client'] ?? 'Unknown', style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500)),
                    Text("${s['type'] ?? 'Individual'} • ${s['duration'] ?? '50'} min", style: const TextStyle(color: Colors.grey, fontSize: 10)),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => widget.onSessionTap(s),
                    icon: const Icon(Icons.videocam, size: 16),
                    label: Text("Join ${s['platform'] ?? 'Zoom'}"),
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(vertical: 10)),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () {
                      showDialog(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          backgroundColor: const Color(0xFF111111),
                          title: const Text('Cancel Session', style: TextStyle(color: Colors.red)),
                          content: Text(
                            'Cancel session with ${s['client'] ?? 'this client'}? 24-hour cancellation policy applies.',
                            style: const TextStyle(color: Colors.white70, fontSize: 13),
                          ),
                          actions: [
                            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Keep', style: TextStyle(color: Colors.grey))),
                            ElevatedButton(
                              style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                              onPressed: () {
                                Navigator.pop(ctx);
                                widget.onSessionTap({'action': 'cancel', ...s});
                              },
                              child: const Text('Cancel Session', style: TextStyle(color: Colors.white)),
                            ),
                          ],
                        ),
                      );
                    },
                    icon: const Icon(Icons.close, size: 16),
                    label: const Text("Cancel"),
                    style: OutlinedButton.styleFrom(foregroundColor: Colors.red, side: const BorderSide(color: Colors.red), padding: const EdgeInsets.symmetric(vertical: 10)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(children: const [
              Icon(Icons.fiber_manual_record, color: Colors.red, size: 10),
              SizedBox(width: 6),
              Text("Little Nate will observe & record biometrics", style: TextStyle(color: Colors.grey, fontSize: 10)),
            ]),
          ],
        ),
      ),
    );
  }
}
// =============================================================================
// COACH PORTAL v2.0 - Part 3: Sessions Tab & Ask Nate Tab
// =============================================================================

// TAB 3: SESSIONS TAB (Top Tier Sessions / Recordings)
class SessionsTab extends StatelessWidget {
  final List<dynamic> sessions;
  final Function(Map<String, dynamic>) onSessionTap;

  const SessionsTab({super.key, required this.sessions, required this.onSessionTap});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _buildFilterBar(),
        Expanded(
          child: sessions.isEmpty
              ? const Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.videocam_off, color: Colors.grey, size: 48),
                      SizedBox(height: 16),
                      Text("No recorded sessions yet.", style: TextStyle(color: Colors.grey)),
                    ],
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: sessions.length,
                  itemBuilder: (ctx, i) => _buildSessionItem(context, sessions[i]),
                ),
        ),
      ],
    );
  }

  Widget _buildFilterBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(color: Color(0xFF111111), border: Border(bottom: BorderSide(color: Color(0xFF222222)))),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            _buildFilterChip("All Sessions", true),
            _buildFilterChip("This Week", false),
            _buildFilterChip("Family Only", false),
            _buildFilterChip("Needs Review", false),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterChip(String label, bool isActive) {
    return Container(
      margin: const EdgeInsets.only(right: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        color: isActive ? const Color(0xFFFFD700).withOpacity(0.2) : Colors.white.withOpacity(0.05),
        border: Border.all(color: isActive ? const Color(0xFFFFD700).withOpacity(0.5) : Colors.white.withOpacity(0.1)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Text(label, style: TextStyle(color: isActive ? const Color(0xFFFFD700) : Colors.grey, fontSize: 11)),
    );
  }

  Widget _buildSessionItem(BuildContext context, dynamic session) {
    final Map<String, dynamic> s = session is Map<String, dynamic> ? session : {'client': 'Unknown', 'date': 'Unknown'};
    final isTopTier = s['tier'] == 'TOP_TIER';
    final bool isFamily = s['type'] == 'FAMILY';

    return Card(
      color: isTopTier ? const Color(0xFF1A1810) : const Color(0xFF1A1A1A),
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: isTopTier ? const Color(0xFFFFD700).withOpacity(0.3) : const Color(0xFF252525)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(backgroundColor: isFamily ? Colors.orange : const Color(0xFFFFD700),
                    child: Icon(isFamily ? Icons.family_restroom : Icons.person, color: Colors.white)),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(s['client'] ?? 'Unknown', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500, fontSize: 14)),
                          if (isTopTier) const Padding(padding: EdgeInsets.only(left: 6), child: Text("⭐", style: TextStyle(fontSize: 12))),
                          if (isFamily) ...[
                            const SizedBox(width: 6),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(color: Colors.orange.withOpacity(0.2), borderRadius: BorderRadius.circular(8)),
                              child: const Text("FAMILY", style: TextStyle(color: Colors.orange, fontSize: 9)),
                            ),
                          ],
                        ],
                      ),
                      Text(s['date'] ?? 'Unknown date', style: const TextStyle(color: Colors.grey, fontSize: 11)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(color: Colors.white.withOpacity(0.1), borderRadius: BorderRadius.circular(6)),
                  child: Text("${s['duration'] ?? '50'} min", style: const TextStyle(color: Colors.grey, fontSize: 10)),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                _buildMetaItem(Icons.videocam, s['platform'] ?? 'Zoom'),
                const SizedBox(width: 12),
                _buildMetaItem(Icons.bar_chart, "Biometrics captured"),
                const SizedBox(width: 12),
                _buildMetaItem(Icons.psychology, "AI analyzed"),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => onSessionTap(s),
                    icon: const Icon(Icons.psychology, size: 16),
                    label: const Text("Get Coaching Advice"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.purple.withOpacity(0.2),
                      foregroundColor: Colors.purple.shade200,
                      side: BorderSide(color: Colors.purple.withOpacity(0.3)),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => onSessionTap({'action': 'playback', ...s}),
                    icon: const Icon(Icons.play_arrow, size: 16),
                    label: const Text("Playback"),
                    style: OutlinedButton.styleFrom(foregroundColor: Colors.grey, side: const BorderSide(color: Colors.grey), padding: const EdgeInsets.symmetric(vertical: 10)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMetaItem(IconData icon, String text) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: Colors.grey, size: 12),
        const SizedBox(width: 4),
        Text(text, style: const TextStyle(color: Colors.grey, fontSize: 10)),
      ],
    );
  }
}

// TAB 4: ASK NATE TAB (Coach AI Chat)
class AskNateTab extends StatefulWidget {
  final WebSocketChannel? socket;
  final Map<String, dynamic> coachProfile;

  const AskNateTab({super.key, required this.socket, required this.coachProfile});

  @override
  State<AskNateTab> createState() => _AskNateTabState();
}

class _AskNateTabState extends State<AskNateTab> {
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<Map<String, String>> _messages = [];
  String? _selectedClient;
  bool _isTyping = false;

  final SpeechToText _speech = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  bool _speechAvailable = false;
  bool _isListening = false;
  bool _dictationArmed = false;
  bool _isSpeaking = false;
  bool _ttsUnlocked = false;
  bool _restartScheduled = false;
  DateTime? _suppressSpeechUntil;
  DateTime? _voiceCommandCooldownUntil;
  String _dictationBaseText = '';
  String _dictationSessionText = '';
  int? _selectionStart;
  int? _selectionEnd;

  final List<String> _quickQuestions = ["Recent breakthroughs?", "Family dynamics", "Emotional patterns", "Session themes", "Risk indicators"];

  WebSocketChannel? _ownSocket;
  StreamSubscription? _socketSub;

  @override
  void initState() {
    super.initState();
    _connectOwnSocket();
    _initSpeechToText();
    _initTts();
    _inputController.addListener(_onDraftChanged);
  }

  void _connectOwnSocket() {
    try {
      _ownSocket = WebSocketChannel.connect(Uri.parse(AppConfig.serverUrl));
      _socketSub = _ownSocket!.stream.listen(
        _handleResponse,
        onError: (e) {
          debugPrint('[AskNate] WebSocket error: $e');
          if (mounted) {
            setState(() {
              _isTyping = false;
              _messages.add({'role': 'system', 'content': 'Connection lost. Reconnecting...'});
            });
            Future.delayed(const Duration(seconds: 2), () {
              if (mounted) _connectOwnSocket();
            });
          }
        },
        onDone: () {
          debugPrint('[AskNate] WebSocket closed');
          Future.delayed(const Duration(seconds: 2), () {
            if (mounted) _connectOwnSocket();
          });
        },
      );
    } catch (e) {
      debugPrint('[AskNate] Connection failed: $e');
    }
  }

  void _onDraftChanged() {
    if (!_isListening) {
      _dictationBaseText = _inputController.text;
      if (mounted) setState(() {});
    }
    _clearSelection();
  }

  void _handleResponse(dynamic message) {
    try {
      final data = jsonDecode(message);
      if (data['type'] == 'nate_response') {
        setState(() {
          _isTyping = false;
          _messages.add({'role': 'nate', 'content': data['text'] ?? '...'});
        });
        _scrollToBottom();
      }
    } catch (e) {
      print("Error handling response: $e");
    }
  }

  void _sendQuery(String query) {
    if (query.trim().isEmpty) return;
    setState(() {
      _messages.add({'role': 'user', 'content': query});
      _isTyping = true;
    });
    _ownSocket?.sink.add(jsonEncode({
      "type": "coach_nate_query",
      "nate_query": query,
      "client_context": _selectedClient,
      "coach_id": widget.coachProfile['hardware_id'],
    }));
    _inputController.clear();
    _scrollToBottom();
  }

  // ================================
  // TTS (Read Back)
  // ================================

  Future<void> _initTts() async {
    try {
      await _tts.setLanguage('en-US');
    } catch (_) {}
    try {
      await _tts.setSpeechRate(0.48);
    } catch (_) {}
    try {
      await _tts.setPitch(1.0);
    } catch (_) {}
    try {
      await _tts.setVolume(1.0);
    } catch (_) {}

    _tts.setStartHandler(() {
      if (mounted) setState(() => _isSpeaking = true);
    });
    _tts.setCompletionHandler(() {
      if (mounted) setState(() => _isSpeaking = false);
      if (_dictationArmed) _scheduleDictationRestart(delayMs: 400);
    });
    _tts.setCancelHandler(() {
      if (mounted) setState(() => _isSpeaking = false);
      if (_dictationArmed) _scheduleDictationRestart(delayMs: 400);
    });
    _tts.setErrorHandler((_) {
      if (mounted) setState(() => _isSpeaking = false);
      if (_dictationArmed) _scheduleDictationRestart(delayMs: 400);
    });
  }

  Future<void> _unlockTtsOnce() async {
    if (_ttsUnlocked) return;
    _ttsUnlocked = true;
    try {
      await _tts.speak(' ');
      await _tts.stop();
    } catch (_) {}
  }

  String _draftForReadback({int? sentenceNumber}) {
    final full = _inputController.text.trim();
    if (full.isEmpty) return '';
    final start = _selectionStart;
    final end = _selectionEnd;
    if (sentenceNumber == null &&
        start != null &&
        end != null &&
        start >= 0 &&
        end <= full.length &&
        start < end) {
      return full.substring(start, end).trim();
    }
    if (sentenceNumber != null) {
      final spans = _sentenceSpans(full);
      if (sentenceNumber <= 0 || sentenceNumber > spans.length) return '';
      final span = spans[sentenceNumber - 1];
      return full.substring(span.start, span.end).trim();
    }
    return full;
  }

  Future<void> _readBackDraft() async {
    final text = _draftForReadback();
    if (text.isEmpty) return;
    await _stopSpeechAndSuppressLateResults();
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = true);
    try {
      await _tts.speak(text);
    } catch (_) {
      if (mounted) setState(() => _isSpeaking = false);
    }
  }

  Future<void> _readBackSentence(int sentenceNumber) async {
    final text = _draftForReadback(sentenceNumber: sentenceNumber);
    if (text.isEmpty) return;
    await _stopSpeechAndSuppressLateResults();
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = true);
    try {
      await _tts.speak(text);
    } catch (_) {
      if (mounted) setState(() => _isSpeaking = false);
    }
  }

  Future<void> _stopReading() async {
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = false);
  }

  // ================================
  // STT + Voice Commands
  // ================================

  void _scheduleDictationRestart({int delayMs = 150}) {
    if (_restartScheduled) return;
    _restartScheduled = true;
    Future.delayed(Duration(milliseconds: delayMs), () {
      _restartScheduled = false;
      if (!mounted) return;
      if (_dictationArmed && !_isListening && !_isSpeaking) {
        _startListeningSession();
      }
    });
  }

  Future<void> _initSpeechToText() async {
    try {
      _speechAvailable = await _speech.initialize(
        onError: (_) {
          if (mounted) setState(() => _isListening = false);
        },
        onStatus: (status) {
          if (status == 'done' || status == 'notListening') {
            if (mounted) setState(() => _isListening = false);
            if (_dictationArmed) _scheduleDictationRestart(delayMs: 50);
          }
        },
      );
      if (mounted) setState(() {});
    } catch (_) {
      _speechAvailable = false;
    }
  }

  Future<void> _stopSpeechAndSuppressLateResults() async {
    _suppressSpeechUntil = DateTime.now().add(const Duration(milliseconds: 800));
    if (_isListening) {
      try {
        await _speech.stop();
      } catch (_) {}
      try {
        await _speech.cancel();
      } catch (_) {}
      if (mounted) setState(() => _isListening = false);
    }
  }

  void _toggleListening() async {
    if (!_speechAvailable) return;
    if (_dictationArmed) {
      _dictationArmed = false;
      await _stopSpeechAndSuppressLateResults();
      return;
    }
    _dictationArmed = true;
    await _startListeningSession();
  }

  Future<void> _startListeningSession() async {
    if (!_speechAvailable) return;
    _dictationBaseText = _inputController.text;
    _dictationSessionText = '';
    setState(() => _isListening = true);
    await _speech.listen(
      onResult: (result) {
        if (!_isListening) return;
        final until = _suppressSpeechUntil;
        if (until != null && DateTime.now().isBefore(until)) return;

        final raw = result.recognizedWords.trim();
        if (raw.isEmpty) return;

        final cmd = _extractVoiceCommand(raw);
        bool isCommandLikeUtterance(String s) {
          final t = s.toLowerCase().trimRight().replaceAll(RegExp(r'[.!,;:]+$'), '');
          return RegExp(
            r'^(send|send it|send message|message sent|sent|read|read it|read it back|read back|read sentence|stop|stop reading|stop speaking|clear|start over|delete|undo|scratch that|replace|select)\b',
            caseSensitive: false,
          ).hasMatch(t);
        }
        if (cmd != null) {
          if (result.finalResult || isCommandLikeUtterance(raw)) {
            _handleVoiceCommand(cmd.type, body: cmd.body);
            return;
          }
        }

        final normalized = _normalizeDictation(raw);
        if (mounted) {
          setState(() {
            if (result.finalResult) {
              final committed = _postProcessFinalDictation(normalized);
              _dictationBaseText = _composeDictation(_dictationBaseText, committed);
              _dictationSessionText = '';
              _inputController.text = _dictationBaseText;
              _clearSelection();
            } else {
              _dictationSessionText = normalized;
              _inputController.text = _composeDictation(_dictationBaseText, _dictationSessionText);
            }
          });
        }
      },
      listenFor: const Duration(seconds: 60),
      pauseFor: const Duration(seconds: 6),
      partialResults: true,
      cancelOnError: true,
      listenMode: ListenMode.dictation,
    );
  }

  String _composeDictation(String base, String addition) {
    final b = base;
    final a = addition;
    if (b.trim().isEmpty) return a;
    if (a.trim().isEmpty) return b;
    if (b.endsWith(' ') || b.endsWith('\n') || b.endsWith('\t')) return '$b$a';
    return '$b $a';
  }

  String _deleteLastWord(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final m = RegExp(r'^(.*?)(\S+)\s*$').firstMatch(s);
    if (m == null) return '';
    return (m.group(1) ?? '').trimRight();
  }

  String _deleteLastSentence(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final matches = RegExp(r'[.!?]+').allMatches(s).toList();
    if (matches.isEmpty) {
      final nl = s.lastIndexOf('\n');
      if (nl != -1) return s.substring(0, nl).trimRight();
      return '';
    }
    if (matches.length == 1) return '';
    final prev = matches[matches.length - 2];
    var cut = prev.end;
    while (cut < s.length && s[cut] == ' ') cut++;
    return s.substring(0, cut).trimRight();
  }

  String _replaceLastOccurrenceCaseInsensitive(String input, String from, String to) {
    final hay = input;
    final needle = from.trim();
    if (needle.isEmpty) return hay;
    final lowerHay = hay.toLowerCase();
    final lowerNeedle = needle.toLowerCase();
    final idx = lowerHay.lastIndexOf(lowerNeedle);
    if (idx == -1) return hay;
    return hay.substring(0, idx) + to + hay.substring(idx + needle.length);
  }

  int? _parseSmallNumber(String raw) {
    final t = raw.trim().toLowerCase();
    final asInt = int.tryParse(t);
    if (asInt != null) return asInt;
    const map = <String, int>{
      'one': 1,
      'two': 2,
      'three': 3,
      'four': 4,
      'five': 5,
      'six': 6,
      'seven': 7,
      'eight': 8,
      'nine': 9,
      'ten': 10,
      'eleven': 11,
      'twelve': 12,
      'thirteen': 13,
      'fourteen': 14,
      'fifteen': 15,
      'sixteen': 16,
      'seventeen': 17,
      'eighteen': 18,
      'nineteen': 19,
      'twenty': 20,
    };
    return map[t];
  }

  List<({int start, int end})> _sentenceSpans(String input) {
    final s = input;
    final spans = <({int start, int end})>[];
    int start = 0;
    for (final m in RegExp(r'[.!?]+').allMatches(s)) {
      final end = m.end;
      spans.add((start: start, end: end));
      start = end;
      while (start < s.length && s[start] == ' ') start++;
    }
    if (start < s.length) spans.add((start: start, end: s.length));
    return spans;
  }

  void _selectLastPhrase(String phrase) {
    final p = phrase.trim();
    if (p.isEmpty) return;
    final hay = _inputController.text;
    final idx = hay.toLowerCase().lastIndexOf(p.toLowerCase());
    if (idx == -1) return;
    _selectionStart = idx;
    _selectionEnd = idx + p.length;
  }

  void _clearSelection() {
    _selectionStart = null;
    _selectionEnd = null;
  }

  String _autoFormat(String input) {
    var s = input;
    if (s.trim().isEmpty) return s;
    s = s.replaceAll(RegExp(r'[ \t]{2,}'), ' ');
    s = s.replaceAllMapped(RegExp(r'\bi\b'), (m) => 'I');
    s = s.replaceAllMapped(RegExp(r"\bi(['’]m)\b", caseSensitive: false), (m) => "I'm");
    s = s.replaceAllMapped(RegExp(r"\bi(['’]ll)\b", caseSensitive: false), (m) => "I'll");
    s = s.replaceAllMapped(RegExp(r"\bi(['’]ve)\b", caseSensitive: false), (m) => "I've");
    s = s.replaceAllMapped(RegExp(r"\bi(['’]d)\b", caseSensitive: false), (m) => "I'd");
    String capAt(String str, int idx) {
      if (idx < 0 || idx >= str.length) return str;
      final ch = str[idx];
      if (!RegExp(r'[A-Za-z]').hasMatch(ch)) return str;
      return str.substring(0, idx) + ch.toUpperCase() + str.substring(idx + 1);
    }
    final firstAlpha = RegExp(r'[A-Za-z]').firstMatch(s);
    if (firstAlpha != null) s = capAt(s, firstAlpha.start);
    for (final m in RegExp(r'([.!?]\s+|\n+)([A-Za-z])').allMatches(s).toList().reversed) {
      final idx = m.start + (m.group(1)?.length ?? 0);
      s = capAt(s, idx);
    }
    return s;
  }

  String _postProcessFinalDictation(String input) {
    var s = input;
    s = _autoFormat(s);
    return s;
  }

  String _normalizeDictation(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final rules = <MapEntry<RegExp, String>>[
      MapEntry(RegExp(r'\bquestion mark\b', caseSensitive: false), '?'),
      MapEntry(RegExp(r'\bexclamation point\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation mark\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bfull stop\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bperiod\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bdot\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bcomma\b', caseSensitive: false), ','),
      MapEntry(RegExp(r'\bcolon\b', caseSensitive: false), ':'),
      MapEntry(RegExp(r'\bsemicolon\b', caseSensitive: false), ';'),
      MapEntry(RegExp(r'\bdash\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bhyphen\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bat sign\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bat symbol\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bhash\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bhashtag\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bpound sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bnumber sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bdollar sign\b', caseSensitive: false), r'\$'),
      MapEntry(RegExp(r'\bpercent\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bpercent sign\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bampersand\b', caseSensitive: false), '&'),
      MapEntry(RegExp(r'\bunderscore\b', caseSensitive: false), '_'),
      MapEntry(RegExp(r'\bplus\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bplus sign\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bequals\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\bequal sign\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\bless than\b', caseSensitive: false), '<'),
      MapEntry(RegExp(r'\bgreater than\b', caseSensitive: false), '>'),
      MapEntry(RegExp(r'\bopen parenthesis\b', caseSensitive: false), '('),
      MapEntry(RegExp(r'\bclose parenthesis\b', caseSensitive: false), ')'),
      MapEntry(RegExp(r'\bopen paren\b', caseSensitive: false), '('),
      MapEntry(RegExp(r'\bclose paren\b', caseSensitive: false), ')'),
      MapEntry(RegExp(r'\bopen bracket\b', caseSensitive: false), '['),
      MapEntry(RegExp(r'\bclose bracket\b', caseSensitive: false), ']'),
      MapEntry(RegExp(r'\bopen brace\b', caseSensitive: false), '{'),
      MapEntry(RegExp(r'\bclose brace\b', caseSensitive: false), '}'),
      MapEntry(RegExp(r'\bslash\b', caseSensitive: false), '/'),
      MapEntry(RegExp(r'\bforward slash\b', caseSensitive: false), '/'),
      MapEntry(RegExp(r'\bbackslash\b', caseSensitive: false), '\\\\'),
      MapEntry(RegExp(r'\bcaret\b', caseSensitive: false), '^'),
      MapEntry(RegExp(r'\btilde\b', caseSensitive: false), '~'),
      MapEntry(RegExp(r'\bnew line\b', caseSensitive: false), '\n'),
      MapEntry(RegExp(r'\bnew paragraph\b', caseSensitive: false), '\n\n'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+dot\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+dash\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+hyphen\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+hash\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+plus\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+equals\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+quote\b', caseSensitive: false), '"'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+asterisk\b', caseSensitive: false), '*'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+star\b', caseSensitive: false), '*'),
    ];
    for (final r in rules) {
      s = s.replaceAll(r.key, r.value);
    }
    s = s.replaceAllMapped(RegExp(r'\s+([?.!,;:])'), (m) => m.group(1) ?? '');
    s = s.replaceAllMapped(RegExp(r'([?.!,;:])(?=\w)'), (m) => '${m.group(1) ?? ''} ');
    s = s.replaceAll(RegExp(r' {2,}'), ' ');
    return s;
  }

  ({String type, String body})? _extractVoiceCommand(String raw) {
    String stripWake(String s) {
      return s
          .trim()
          .replaceFirst(
            RegExp(r'^(?:hey\s+)?(?:little\s+nate|nate)\s*[, ]+\s*', caseSensitive: false),
            '',
          )
          .trim();
    }
    final cmdText = stripWake(raw.trim());
    final lower = cmdText.toLowerCase();
    final cooldown = _voiceCommandCooldownUntil;
    if (cooldown != null && DateTime.now().isBefore(cooldown)) return null;

    final clearExact = RegExp(
      r'^(delete message and start over|delete message|clear message|start over|clear)$',
      caseSensitive: false,
    );
    final deleteLastSentence = RegExp(
      r'^(delete last sentence|remove last sentence|delete last line|undo that|scratch that|undo)$',
      caseSensitive: false,
    );
    final deleteLastWord = RegExp(
      r'^(delete last word|remove last word)$',
      caseSensitive: false,
    );
    final stopReadingAnywhere = RegExp(
      r'\b(stop reading|stop speaking|cancel reading)\b|\b(stop)\b$',
      caseSensitive: false,
    );
    final readSentenceAnywhere = RegExp(
      r'\bread sentence (.+?)\b',
      caseSensitive: false,
    );
    final readBackAnywhere = RegExp(
      r'\b(read it back|read that back|read back|read message|read draft|read it|read that)\b',
      caseSensitive: false,
    );
    final sendTrail = RegExp(
      r'(?:\b(send message|send it|send this|send|message sent)\b)[\s,.;:!?]*$',
      caseSensitive: false,
    );
    final clearAnywhere = RegExp(
      r'\b(delete message and start over|delete message|clear message|start over|clear)\b',
      caseSensitive: false,
    );
    final deleteLastSentenceAnywhere = RegExp(
      r'\b(delete last sentence|remove last sentence|delete last line|undo that|scratch that|undo)\b',
      caseSensitive: false,
    );
    final deleteLastWordAnywhere = RegExp(
      r'\b(delete last word|remove last word)\b',
      caseSensitive: false,
    );
    final replaceAllCmd =
        RegExp(r'\breplace\s+all\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final replaceFirstCmd =
        RegExp(r'\breplace\s+first\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final replaceLastCmd =
        RegExp(r'\breplace\s+last\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final replaceSentenceCmd =
        RegExp(r'\breplace\s+sentence\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final deleteSentenceCmd =
        RegExp(r'\bdelete\s+sentence\s+(.+?)\s*$', caseSensitive: false);
    final selectCmd = RegExp(r'\bselect\s+(.+?)\s*$', caseSensitive: false);
    final replaceThatCmd = RegExp(r'\breplace\s+that\s+with\s+(.+?)\s*$', caseSensitive: false);
    final deleteThatCmd = RegExp(r'\bdelete\s+that\s*$', caseSensitive: false);
    final replaceCmd = RegExp(r'\breplace\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);

    if (clearExact.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLastSentence.hasMatch(lower)) return (type: 'delete_last_sentence', body: '');
    if (deleteLastWord.hasMatch(lower)) return (type: 'delete_last_word', body: '');
    if (stopReadingAnywhere.hasMatch(lower)) return (type: 'stop_reading', body: '');
    if (clearAnywhere.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLastSentenceAnywhere.hasMatch(lower)) return (type: 'delete_last_sentence', body: '');
    if (deleteLastWordAnywhere.hasMatch(lower)) return (type: 'delete_last_word', body: '');
    final rsm = readSentenceAnywhere.firstMatch(cmdText);
    if (rsm != null) return (type: 'read_sentence:${(rsm.group(1) ?? '').trim()}', body: '');
    if (lower == 'sent') return (type: 'send', body: '');
    final sm = sendTrail.firstMatch(cmdText);
    if (sm != null) {
      final body = cmdText.substring(0, sm.start).trim();
      return (type: 'send', body: body);
    }
    final rbm = readBackAnywhere.firstMatch(cmdText);
    if (rbm != null) {
      final body = cmdText.substring(0, rbm.start).trim();
      return (type: 'read_back', body: body);
    }
    Match? rm;
    rm = replaceAllCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_all:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = replaceFirstCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_first:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = replaceLastCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_last:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = replaceSentenceCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_sentence:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = deleteSentenceCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'delete_sentence:${(rm.group(1) ?? '').trim()}', body: '');
    rm = selectCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'select:${(rm.group(1) ?? '').trim()}', body: '');
    rm = replaceThatCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_that:${(rm.group(1) ?? '').trim()}', body: '');
    if (deleteThatCmd.hasMatch(lower)) return (type: 'delete_that', body: '');
    rm = replaceCmd.firstMatch(cmdText);
    if (rm != null) {
      final from = (rm.group(1) ?? '').trim();
      final to = (rm.group(2) ?? '').trim();
      if (from.isNotEmpty) return (type: 'replace_last:$from=>$to', body: '');
    }
    return null;
  }

  Future<void> _handleVoiceCommand(String type, {String body = ''}) async {
    _voiceCommandCooldownUntil = DateTime.now().add(const Duration(seconds: 2));
    if (type == 'send') {
      final b = body.trim();
      if (b.isNotEmpty) {
        final normalized = _postProcessFinalDictation(_normalizeDictation(b));
        setState(() {
          _inputController.text = _composeDictation(_dictationBaseText, normalized);
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
      _sendQuery(_inputController.text);
    } else if (type == 'clear_all') {
      setState(() {
        _inputController.clear();
        _dictationBaseText = '';
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'delete_last_sentence') {
      setState(() {
        _inputController.text = _deleteLastSentence(_inputController.text);
        _dictationBaseText = _inputController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'delete_last_word') {
      setState(() {
        _inputController.text = _deleteLastWord(_inputController.text);
        _dictationBaseText = _inputController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'read_back') {
      final b = body.trim();
      if (b.isNotEmpty) {
        final normalized = _postProcessFinalDictation(_normalizeDictation(b));
        setState(() {
          _inputController.text = _composeDictation(_dictationBaseText, normalized);
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
      await _readBackDraft();
    } else if (type == 'stop_reading') {
      await _stopReading();
    } else if (type.startsWith('select:')) {
      final phrase = type.substring('select:'.length).trim();
      setState(() => _selectLastPhrase(phrase));
    } else if (type.startsWith('replace_that:')) {
      final to = type.substring('replace_that:'.length);
      final start = _selectionStart;
      final end = _selectionEnd;
      if (start != null && end != null && start >= 0 && end <= _inputController.text.length && start < end) {
        setState(() {
          final t = _inputController.text;
          _inputController.text = t.substring(0, start) + to + t.substring(end);
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type == 'delete_that') {
      final start = _selectionStart;
      final end = _selectionEnd;
      if (start != null && end != null && start >= 0 && end <= _inputController.text.length && start < end) {
        setState(() {
          final t = _inputController.text;
          _inputController.text = (t.substring(0, start) + t.substring(end)).trimRight();
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type.startsWith('replace_sentence:')) {
      final payload = type.substring('replace_sentence:'.length);
      final parts = payload.split('=>');
      final idxRaw = parts.isNotEmpty ? parts[0] : '';
      final replacement = parts.length > 1 ? parts[1] : '';
      final idx = _parseSmallNumber(idxRaw);
      final spans = _sentenceSpans(_inputController.text);
      if (idx != null && idx > 0 && idx <= spans.length) {
        final span = spans[idx - 1];
        setState(() {
          final t = _inputController.text;
          _inputController.text =
              (t.substring(0, span.start) + replacement + t.substring(span.end)).trimRight();
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type.startsWith('delete_sentence:')) {
      final idxRaw = type.substring('delete_sentence:'.length);
      final idx = _parseSmallNumber(idxRaw);
      final spans = _sentenceSpans(_inputController.text);
      if (idx != null && idx > 0 && idx <= spans.length) {
        final span = spans[idx - 1];
        setState(() {
          final t = _inputController.text;
          _inputController.text = (t.substring(0, span.start) + t.substring(span.end)).trimRight();
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type.startsWith('replace_all:') ||
        type.startsWith('replace_first:') ||
        type.startsWith('replace_last:')) {
      final mode = type.split(':').first;
      final payload = type.substring(mode.length + 1);
      final parts = payload.split('=>');
      final from = parts.isNotEmpty ? parts[0] : '';
      final to = parts.length > 1 ? parts[1] : '';
      setState(() {
        final t = _inputController.text;
        if (from.trim().isEmpty) return;
        if (mode == 'replace_all') {
          final rx = RegExp(RegExp.escape(from), caseSensitive: false);
          _inputController.text = t.replaceAll(rx, to);
        } else if (mode == 'replace_first') {
          final rx = RegExp(RegExp.escape(from), caseSensitive: false);
          _inputController.text = t.replaceFirst(rx, to);
        } else {
          _inputController.text = _replaceLastOccurrenceCaseInsensitive(t, from, to);
        }
        _dictationBaseText = _inputController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type.startsWith('read_sentence:')) {
      final rawIdx = type.substring('read_sentence:'.length);
      final idx = _parseSmallNumber(rawIdx);
      if (idx != null) await _readBackSentence(idx);
    }

    if (_dictationArmed) {
      await _stopSpeechAndSuppressLateResults();
      _scheduleDictationRestart(delayMs: 150);
    }
  }

  // ================================
  // TTS (Read Back)
  // ================================

  Future<void> _initTts() async {
    try {
      await _tts.setLanguage('en-US');
    } catch (_) {}
    try {
      await _tts.setSpeechRate(0.48);
    } catch (_) {}
    try {
      await _tts.setPitch(1.0);
    } catch (_) {}
    try {
      await _tts.setVolume(1.0);
    } catch (_) {}

    _tts.setStartHandler(() {
      if (mounted) setState(() => _isSpeaking = true);
    });
    _tts.setCompletionHandler(() {
      if (mounted) setState(() => _isSpeaking = false);
      if (_dictationArmed) _scheduleDictationRestart(delayMs: 400);
    });
    _tts.setCancelHandler(() {
      if (mounted) setState(() => _isSpeaking = false);
      if (_dictationArmed) _scheduleDictationRestart(delayMs: 400);
    });
    _tts.setErrorHandler((_) {
      if (mounted) setState(() => _isSpeaking = false);
      if (_dictationArmed) _scheduleDictationRestart(delayMs: 400);
    });
  }

  Future<void> _unlockTtsOnce() async {
    if (_ttsUnlocked) return;
    _ttsUnlocked = true;
    try {
      await _tts.speak(' ');
      await _tts.stop();
    } catch (_) {}
  }

  String _draftForReadback({int? sentenceNumber}) {
    final full = _inputController.text.trim();
    if (full.isEmpty) return '';
    final start = _selectionStart;
    final end = _selectionEnd;
    if (sentenceNumber == null &&
        start != null &&
        end != null &&
        start >= 0 &&
        end <= full.length &&
        start < end) {
      return full.substring(start, end).trim();
    }
    if (sentenceNumber != null) {
      final spans = _sentenceSpans(full);
      if (sentenceNumber <= 0 || sentenceNumber > spans.length) return '';
      final span = spans[sentenceNumber - 1];
      return full.substring(span.start, span.end).trim();
    }
    return full;
  }

  Future<void> _readBackDraft() async {
    final text = _draftForReadback();
    if (text.isEmpty) return;
    await _stopSpeechAndSuppressLateResults();
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = true);
    try {
      await _tts.speak(text);
    } catch (_) {
      if (mounted) setState(() => _isSpeaking = false);
    }
  }

  Future<void> _readBackSentence(int sentenceNumber) async {
    final text = _draftForReadback(sentenceNumber: sentenceNumber);
    if (text.isEmpty) return;
    await _stopSpeechAndSuppressLateResults();
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = true);
    try {
      await _tts.speak(text);
    } catch (_) {
      if (mounted) setState(() => _isSpeaking = false);
    }
  }

  Future<void> _stopReading() async {
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = false);
  }

  // ================================
  // STT + Voice Commands
  // ================================

  void _scheduleDictationRestart({int delayMs = 150}) {
    if (_restartScheduled) return;
    _restartScheduled = true;
    Future.delayed(Duration(milliseconds: delayMs), () {
      _restartScheduled = false;
      if (!mounted) return;
      if (_dictationArmed && !_isListening && !_isSpeaking) {
        _startListeningSession();
      }
    });
  }

  Future<void> _initSpeechToText() async {
    try {
      _speechAvailable = await _speech.initialize(
        onError: (_) {
          if (mounted) setState(() => _isListening = false);
        },
        onStatus: (status) {
          if (status == 'done' || status == 'notListening') {
            if (mounted) setState(() => _isListening = false);
            if (_dictationArmed) _scheduleDictationRestart(delayMs: 50);
          }
        },
      );
      if (mounted) setState(() {});
    } catch (_) {
      _speechAvailable = false;
    }
  }

  Future<void> _stopSpeechAndSuppressLateResults() async {
    _suppressSpeechUntil = DateTime.now().add(const Duration(milliseconds: 800));
    if (_isListening) {
      try {
        await _speech.stop();
      } catch (_) {}
      try {
        await _speech.cancel();
      } catch (_) {}
      if (mounted) setState(() => _isListening = false);
    }
  }

  void _toggleListening() async {
    if (!_speechAvailable) return;
    if (_dictationArmed) {
      _dictationArmed = false;
      await _stopSpeechAndSuppressLateResults();
      return;
    }
    _dictationArmed = true;
    await _startListeningSession();
  }

  Future<void> _startListeningSession() async {
    if (!_speechAvailable) return;
    _dictationBaseText = _inputController.text;
    _dictationSessionText = '';
    setState(() => _isListening = true);
    await _speech.listen(
      onResult: (result) {
        if (!_isListening) return;
        final until = _suppressSpeechUntil;
        if (until != null && DateTime.now().isBefore(until)) return;

        final raw = result.recognizedWords.trim();
        if (raw.isEmpty) return;

        final cmd = _extractVoiceCommand(raw);
        bool isCommandLikeUtterance(String s) {
          final t = s.toLowerCase().trimRight().replaceAll(RegExp(r'[.!,;:]+$'), '');
          return RegExp(
            r'^(send|send it|send message|message sent|sent|read|read it|read it back|read back|read sentence|stop|stop reading|stop speaking|clear|start over|delete|undo|scratch that|replace|select)\b',
            caseSensitive: false,
          ).hasMatch(t);
        }
        if (cmd != null) {
          if (result.finalResult || isCommandLikeUtterance(raw)) {
            _handleVoiceCommand(cmd.type, body: cmd.body);
            return;
          }
        }

        final normalized = _normalizeDictation(raw);
        if (mounted) {
          setState(() {
            if (result.finalResult) {
              final committed = _postProcessFinalDictation(normalized);
              _dictationBaseText = _composeDictation(_dictationBaseText, committed);
              _dictationSessionText = '';
              _inputController.text = _dictationBaseText;
              _clearSelection();
            } else {
              _dictationSessionText = normalized;
              _inputController.text = _composeDictation(_dictationBaseText, _dictationSessionText);
            }
          });
        }
      },
      listenFor: const Duration(seconds: 60),
      pauseFor: const Duration(seconds: 6),
      partialResults: true,
      cancelOnError: true,
      listenMode: ListenMode.dictation,
    );
  }

  String _composeDictation(String base, String addition) {
    final b = base;
    final a = addition;
    if (b.trim().isEmpty) return a;
    if (a.trim().isEmpty) return b;
    if (b.endsWith(' ') || b.endsWith('\n') || b.endsWith('\t')) return '$b$a';
    return '$b $a';
  }

  String _deleteLastWord(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final m = RegExp(r'^(.*?)(\S+)\s*$').firstMatch(s);
    if (m == null) return '';
    return (m.group(1) ?? '').trimRight();
  }

  String _deleteLastSentence(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final matches = RegExp(r'[.!?]+').allMatches(s).toList();
    if (matches.isEmpty) {
      final nl = s.lastIndexOf('\n');
      if (nl != -1) return s.substring(0, nl).trimRight();
      return '';
    }
    if (matches.length == 1) return '';
    final prev = matches[matches.length - 2];
    var cut = prev.end;
    while (cut < s.length && s[cut] == ' ') cut++;
    return s.substring(0, cut).trimRight();
  }

  String _replaceLastOccurrenceCaseInsensitive(String input, String from, String to) {
    final hay = input;
    final needle = from.trim();
    if (needle.isEmpty) return hay;
    final lowerHay = hay.toLowerCase();
    final lowerNeedle = needle.toLowerCase();
    final idx = lowerHay.lastIndexOf(lowerNeedle);
    if (idx == -1) return hay;
    return hay.substring(0, idx) + to + hay.substring(idx + needle.length);
  }

  int? _parseSmallNumber(String raw) {
    final t = raw.trim().toLowerCase();
    final asInt = int.tryParse(t);
    if (asInt != null) return asInt;
    const map = <String, int>{
      'one': 1,
      'two': 2,
      'three': 3,
      'four': 4,
      'five': 5,
      'six': 6,
      'seven': 7,
      'eight': 8,
      'nine': 9,
      'ten': 10,
      'eleven': 11,
      'twelve': 12,
      'thirteen': 13,
      'fourteen': 14,
      'fifteen': 15,
      'sixteen': 16,
      'seventeen': 17,
      'eighteen': 18,
      'nineteen': 19,
      'twenty': 20,
    };
    return map[t];
  }

  List<({int start, int end})> _sentenceSpans(String input) {
    final s = input;
    final spans = <({int start, int end})>[];
    int start = 0;
    for (final m in RegExp(r'[.!?]+').allMatches(s)) {
      final end = m.end;
      spans.add((start: start, end: end));
      start = end;
      while (start < s.length && s[start] == ' ') start++;
    }
    if (start < s.length) spans.add((start: start, end: s.length));
    return spans;
  }

  void _selectLastPhrase(String phrase) {
    final p = phrase.trim();
    if (p.isEmpty) return;
    final hay = _inputController.text;
    final idx = hay.toLowerCase().lastIndexOf(p.toLowerCase());
    if (idx == -1) return;
    _selectionStart = idx;
    _selectionEnd = idx + p.length;
  }

  void _clearSelection() {
    _selectionStart = null;
    _selectionEnd = null;
  }

  String _autoFormat(String input) {
    var s = input;
    if (s.trim().isEmpty) return s;
    s = s.replaceAll(RegExp(r'[ \t]{2,}'), ' ');
    s = s.replaceAllMapped(RegExp(r'\bi\b'), (m) => 'I');
    s = s.replaceAllMapped(RegExp(r"\bi(['’]m)\b", caseSensitive: false), (m) => "I'm");
    s = s.replaceAllMapped(RegExp(r"\bi(['’]ll)\b", caseSensitive: false), (m) => "I'll");
    s = s.replaceAllMapped(RegExp(r"\bi(['’]ve)\b", caseSensitive: false), (m) => "I've");
    s = s.replaceAllMapped(RegExp(r"\bi(['’]d)\b", caseSensitive: false), (m) => "I'd");
    String capAt(String str, int idx) {
      if (idx < 0 || idx >= str.length) return str;
      final ch = str[idx];
      if (!RegExp(r'[A-Za-z]').hasMatch(ch)) return str;
      return str.substring(0, idx) + ch.toUpperCase() + str.substring(idx + 1);
    }
    final firstAlpha = RegExp(r'[A-Za-z]').firstMatch(s);
    if (firstAlpha != null) s = capAt(s, firstAlpha.start);
    for (final m in RegExp(r'([.!?]\s+|\n+)([A-Za-z])').allMatches(s).toList().reversed) {
      final idx = m.start + (m.group(1)?.length ?? 0);
      s = capAt(s, idx);
    }
    return s;
  }

  String _postProcessFinalDictation(String input) {
    var s = input;
    s = _autoFormat(s);
    return s;
  }

  String _normalizeDictation(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final rules = <MapEntry<RegExp, String>>[
      MapEntry(RegExp(r'\bquestion mark\b', caseSensitive: false), '?'),
      MapEntry(RegExp(r'\bexclamation point\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation mark\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bfull stop\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bperiod\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bdot\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bcomma\b', caseSensitive: false), ','),
      MapEntry(RegExp(r'\bcolon\b', caseSensitive: false), ':'),
      MapEntry(RegExp(r'\bsemicolon\b', caseSensitive: false), ';'),
      MapEntry(RegExp(r'\bdash\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bhyphen\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bat sign\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bat symbol\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bhash\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bhashtag\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bpound sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bnumber sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bdollar sign\b', caseSensitive: false), r'\$'),
      MapEntry(RegExp(r'\bpercent\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bpercent sign\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bampersand\b', caseSensitive: false), '&'),
      MapEntry(RegExp(r'\bunderscore\b', caseSensitive: false), '_'),
      MapEntry(RegExp(r'\bplus\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bplus sign\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bequals\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\bequal sign\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\bless than\b', caseSensitive: false), '<'),
      MapEntry(RegExp(r'\bgreater than\b', caseSensitive: false), '>'),
      MapEntry(RegExp(r'\bopen parenthesis\b', caseSensitive: false), '('),
      MapEntry(RegExp(r'\bclose parenthesis\b', caseSensitive: false), ')'),
      MapEntry(RegExp(r'\bopen paren\b', caseSensitive: false), '('),
      MapEntry(RegExp(r'\bclose paren\b', caseSensitive: false), ')'),
      MapEntry(RegExp(r'\bopen bracket\b', caseSensitive: false), '['),
      MapEntry(RegExp(r'\bclose bracket\b', caseSensitive: false), ']'),
      MapEntry(RegExp(r'\bopen brace\b', caseSensitive: false), '{'),
      MapEntry(RegExp(r'\bclose brace\b', caseSensitive: false), '}'),
      MapEntry(RegExp(r'\bslash\b', caseSensitive: false), '/'),
      MapEntry(RegExp(r'\bforward slash\b', caseSensitive: false), '/'),
      MapEntry(RegExp(r'\bbackslash\b', caseSensitive: false), '\\\\'),
      MapEntry(RegExp(r'\bcaret\b', caseSensitive: false), '^'),
      MapEntry(RegExp(r'\btilde\b', caseSensitive: false), '~'),
      MapEntry(RegExp(r'\bnew line\b', caseSensitive: false), '\n'),
      MapEntry(RegExp(r'\bnew paragraph\b', caseSensitive: false), '\n\n'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+dot\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+dash\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+hyphen\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+hash\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+plus\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+equals\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+quote\b', caseSensitive: false), '"'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+asterisk\b', caseSensitive: false), '*'),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+star\b', caseSensitive: false), '*'),
    ];
    for (final r in rules) {
      s = s.replaceAll(r.key, r.value);
    }
    s = s.replaceAllMapped(RegExp(r'\s+([?.!,;:])'), (m) => m.group(1) ?? '');
    s = s.replaceAllMapped(RegExp(r'([?.!,;:])(?=\w)'), (m) => '${m.group(1) ?? ''} ');
    s = s.replaceAll(RegExp(r' {2,}'), ' ');
    return s;
  }

  ({String type, String body})? _extractVoiceCommand(String raw) {
    String stripWake(String s) {
      return s
          .trim()
          .replaceFirst(
            RegExp(r'^(?:hey\s+)?(?:little\s+nate|nate)\s*[, ]+\s*', caseSensitive: false),
            '',
          )
          .trim();
    }
    final cmdText = stripWake(raw.trim());
    final lower = cmdText.toLowerCase();
    final cooldown = _voiceCommandCooldownUntil;
    if (cooldown != null && DateTime.now().isBefore(cooldown)) return null;

    final clearExact = RegExp(
      r'^(delete message and start over|delete message|clear message|start over|clear)$',
      caseSensitive: false,
    );
    final deleteLastSentence = RegExp(
      r'^(delete last sentence|remove last sentence|delete last line|undo that|scratch that|undo)$',
      caseSensitive: false,
    );
    final deleteLastWord = RegExp(
      r'^(delete last word|remove last word)$',
      caseSensitive: false,
    );
    final stopReadingAnywhere = RegExp(
      r'\b(stop reading|stop speaking|cancel reading)\b|\b(stop)\b$',
      caseSensitive: false,
    );
    final readSentenceAnywhere = RegExp(
      r'\bread sentence (.+?)\b',
      caseSensitive: false,
    );
    final readBackAnywhere = RegExp(
      r'\b(read it back|read that back|read back|read message|read draft|read it|read that)\b',
      caseSensitive: false,
    );
    final sendTrail = RegExp(
      r'(?:\b(send message|send it|send this|send|message sent)\b)[\s,.;:!?]*$',
      caseSensitive: false,
    );
    final clearAnywhere = RegExp(
      r'\b(delete message and start over|delete message|clear message|start over|clear)\b',
      caseSensitive: false,
    );
    final deleteLastSentenceAnywhere = RegExp(
      r'\b(delete last sentence|remove last sentence|delete last line|undo that|scratch that|undo)\b',
      caseSensitive: false,
    );
    final deleteLastWordAnywhere = RegExp(
      r'\b(delete last word|remove last word)\b',
      caseSensitive: false,
    );
    final replaceAllCmd =
        RegExp(r'\breplace\s+all\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final replaceFirstCmd =
        RegExp(r'\breplace\s+first\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final replaceLastCmd =
        RegExp(r'\breplace\s+last\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final replaceSentenceCmd =
        RegExp(r'\breplace\s+sentence\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);
    final deleteSentenceCmd =
        RegExp(r'\bdelete\s+sentence\s+(.+?)\s*$', caseSensitive: false);
    final selectCmd = RegExp(r'\bselect\s+(.+?)\s*$', caseSensitive: false);
    final replaceThatCmd = RegExp(r'\breplace\s+that\s+with\s+(.+?)\s*$', caseSensitive: false);
    final deleteThatCmd = RegExp(r'\bdelete\s+that\s*$', caseSensitive: false);
    final replaceCmd = RegExp(r'\breplace\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);

    if (clearExact.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLastSentence.hasMatch(lower)) return (type: 'delete_last_sentence', body: '');
    if (deleteLastWord.hasMatch(lower)) return (type: 'delete_last_word', body: '');
    if (stopReadingAnywhere.hasMatch(lower)) return (type: 'stop_reading', body: '');
    if (clearAnywhere.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLastSentenceAnywhere.hasMatch(lower)) return (type: 'delete_last_sentence', body: '');
    if (deleteLastWordAnywhere.hasMatch(lower)) return (type: 'delete_last_word', body: '');
    final rsm = readSentenceAnywhere.firstMatch(cmdText);
    if (rsm != null) return (type: 'read_sentence:${(rsm.group(1) ?? '').trim()}', body: '');
    if (lower == 'sent') return (type: 'send', body: '');
    final sm = sendTrail.firstMatch(cmdText);
    if (sm != null) {
      final body = cmdText.substring(0, sm.start).trim();
      return (type: 'send', body: body);
    }
    final rbm = readBackAnywhere.firstMatch(cmdText);
    if (rbm != null) {
      final body = cmdText.substring(0, rbm.start).trim();
      return (type: 'read_back', body: body);
    }
    Match? rm;
    rm = replaceAllCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_all:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = replaceFirstCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_first:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = replaceLastCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_last:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = replaceSentenceCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_sentence:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}', body: '');
    rm = deleteSentenceCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'delete_sentence:${(rm.group(1) ?? '').trim()}', body: '');
    rm = selectCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'select:${(rm.group(1) ?? '').trim()}', body: '');
    rm = replaceThatCmd.firstMatch(cmdText);
    if (rm != null) return (type: 'replace_that:${(rm.group(1) ?? '').trim()}', body: '');
    if (deleteThatCmd.hasMatch(lower)) return (type: 'delete_that', body: '');
    rm = replaceCmd.firstMatch(cmdText);
    if (rm != null) {
      final from = (rm.group(1) ?? '').trim();
      final to = (rm.group(2) ?? '').trim();
      if (from.isNotEmpty) return (type: 'replace_last:$from=>$to', body: '');
    }
    return null;
  }

  Future<void> _handleVoiceCommand(String type, {String body = ''}) async {
    _voiceCommandCooldownUntil = DateTime.now().add(const Duration(seconds: 2));
    if (type == 'send') {
      final b = body.trim();
      if (b.isNotEmpty) {
        final normalized = _postProcessFinalDictation(_normalizeDictation(b));
        setState(() {
          _inputController.text = _composeDictation(_dictationBaseText, normalized);
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
      _sendQuery(_inputController.text);
    } else if (type == 'clear_all') {
      setState(() {
        _inputController.clear();
        _dictationBaseText = '';
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'delete_last_sentence') {
      setState(() {
        _inputController.text = _deleteLastSentence(_inputController.text);
        _dictationBaseText = _inputController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'delete_last_word') {
      setState(() {
        _inputController.text = _deleteLastWord(_inputController.text);
        _dictationBaseText = _inputController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'read_back') {
      final b = body.trim();
      if (b.isNotEmpty) {
        final normalized = _postProcessFinalDictation(_normalizeDictation(b));
        setState(() {
          _inputController.text = _composeDictation(_dictationBaseText, normalized);
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
      await _readBackDraft();
    } else if (type == 'stop_reading') {
      await _stopReading();
    } else if (type.startsWith('select:')) {
      final phrase = type.substring('select:'.length).trim();
      setState(() => _selectLastPhrase(phrase));
    } else if (type.startsWith('replace_that:')) {
      final to = type.substring('replace_that:'.length);
      final start = _selectionStart;
      final end = _selectionEnd;
      if (start != null && end != null && start >= 0 && end <= _inputController.text.length && start < end) {
        setState(() {
          final t = _inputController.text;
          _inputController.text = t.substring(0, start) + to + t.substring(end);
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type == 'delete_that') {
      final start = _selectionStart;
      final end = _selectionEnd;
      if (start != null && end != null && start >= 0 && end <= _inputController.text.length && start < end) {
        setState(() {
          final t = _inputController.text;
          _inputController.text = (t.substring(0, start) + t.substring(end)).trimRight();
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type.startsWith('replace_sentence:')) {
      final payload = type.substring('replace_sentence:'.length);
      final parts = payload.split('=>');
      final idxRaw = parts.isNotEmpty ? parts[0] : '';
      final replacement = parts.length > 1 ? parts[1] : '';
      final idx = _parseSmallNumber(idxRaw);
      final spans = _sentenceSpans(_inputController.text);
      if (idx != null && idx > 0 && idx <= spans.length) {
        final span = spans[idx - 1];
        setState(() {
          final t = _inputController.text;
          _inputController.text =
              (t.substring(0, span.start) + replacement + t.substring(span.end)).trimRight();
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type.startsWith('delete_sentence:')) {
      final idxRaw = type.substring('delete_sentence:'.length);
      final idx = _parseSmallNumber(idxRaw);
      final spans = _sentenceSpans(_inputController.text);
      if (idx != null && idx > 0 && idx <= spans.length) {
        final span = spans[idx - 1];
        setState(() {
          final t = _inputController.text;
          _inputController.text = (t.substring(0, span.start) + t.substring(span.end)).trimRight();
          _dictationBaseText = _inputController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
    } else if (type.startsWith('replace_all:') ||
        type.startsWith('replace_first:') ||
        type.startsWith('replace_last:')) {
      final mode = type.split(':').first;
      final payload = type.substring(mode.length + 1);
      final parts = payload.split('=>');
      final from = parts.isNotEmpty ? parts[0] : '';
      final to = parts.length > 1 ? parts[1] : '';
      setState(() {
        final t = _inputController.text;
        if (from.trim().isEmpty) return;
        if (mode == 'replace_all') {
          final rx = RegExp(RegExp.escape(from), caseSensitive: false);
          _inputController.text = t.replaceAll(rx, to);
        } else if (mode == 'replace_first') {
          final rx = RegExp(RegExp.escape(from), caseSensitive: false);
          _inputController.text = t.replaceFirst(rx, to);
        } else {
          _inputController.text = _replaceLastOccurrenceCaseInsensitive(t, from, to);
        }
        _dictationBaseText = _inputController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type.startsWith('read_sentence:')) {
      final rawIdx = type.substring('read_sentence:'.length);
      final idx = _parseSmallNumber(rawIdx);
      if (idx != null) await _readBackSentence(idx);
    }

    if (_dictationArmed) {
      await _stopSpeechAndSuppressLateResults();
      _scheduleDictationRestart(delayMs: 150);
    }
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      _scrollController.animateTo(_scrollController.position.maxScrollExtent, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
    }
  }

  @override
  void dispose() {
    _socketSub?.cancel();
    _ownSocket?.sink.close();
    _tts.stop();
    _speech.stop();
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _buildClientContext(),
        Expanded(child: _buildChatArea()),
        _buildInputArea(),
      ],
    );
  }

  Widget _buildClientContext() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: const Color(0xFFFFD700).withOpacity(0.1), border: const Border(bottom: BorderSide(color: Color(0xFF333300)))),
      child: Row(
        children: [
          const CircleAvatar(radius: 16, backgroundColor: Color(0xFFFFD700), child: Icon(Icons.person, color: Colors.white, size: 16)),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("ASKING ABOUT", style: TextStyle(color: Color(0xFFFFD700), fontSize: 10, letterSpacing: 1)),
              Text(_selectedClient ?? "All Clients", style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500)),
            ],
          ),
          const Spacer(),
          TextButton(onPressed: _showClientSelector, child: const Text("Change", style: TextStyle(color: Color(0xFFFFD700), fontSize: 12))),
        ],
      ),
    );
  }

  void _showClientSelector() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF1A1A1A),
      builder: (ctx) => Container(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Select Client Context", style: TextStyle(color: Colors.white, fontSize: 16)),
            const SizedBox(height: 16),
            ListTile(
              leading: const Icon(Icons.people, color: Colors.cyan),
              title: const Text("All Clients", style: TextStyle(color: Colors.white)),
              onTap: () {
                setState(() => _selectedClient = null);
                Navigator.pop(ctx);
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildChatArea() {
    return Container(
      color: const Color(0xFF0A0A0A),
      child: Column(
        children: [
          if (_messages.isEmpty) _buildQuickQuestions(),
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.all(16),
              itemCount: _messages.length + (_isTyping ? 1 : 0),
              itemBuilder: (ctx, i) {
                if (_isTyping && i == _messages.length) return _buildTypingIndicator();
                return _buildMessage(_messages[i]);
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildQuickQuestions() {
    return Container(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("QUICK QUESTIONS", style: TextStyle(color: Colors.grey, fontSize: 10, letterSpacing: 1)),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _quickQuestions.map((q) => InkWell(
              onTap: () => _sendQuery(q),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: Colors.cyan.withOpacity(0.05),
                  border: Border.all(color: Colors.cyan.withOpacity(0.2)),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(q, style: const TextStyle(color: Colors.cyan, fontSize: 11)),
              ),
            )).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildMessage(Map<String, String> message) {
    final isUser = message['role'] == 'user';
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          if (!isUser) ...[
            Container(
              width: 28, height: 28,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: const RadialGradient(colors: [Color(0xFF001A33), Colors.black]),
                boxShadow: [BoxShadow(color: Colors.cyan.withOpacity(0.3), blurRadius: 8)],
              ),
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [CircleAvatar(radius: 3, backgroundColor: Colors.white), SizedBox(width: 4), CircleAvatar(radius: 3, backgroundColor: Colors.white)],
              ),
            ),
            const SizedBox(width: 10),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: isUser ? const Color(0xFFFFD700) : Colors.cyan.withOpacity(0.1),
                border: isUser ? null : Border.all(color: Colors.cyan.withOpacity(0.2)),
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(16), topRight: const Radius.circular(16),
                  bottomLeft: Radius.circular(isUser ? 16 : 4), bottomRight: Radius.circular(isUser ? 4 : 16),
                ),
              ),
              child: SelectableText(message['content'] ?? '', style: TextStyle(color: isUser ? Colors.black : Colors.white, fontSize: 13, height: 1.5)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTypingIndicator() {
    return Row(
      children: [
        Container(width: 28, height: 28, decoration: const BoxDecoration(shape: BoxShape.circle, color: Color(0xFF001A33))),
        const SizedBox(width: 10),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: Colors.cyan.withOpacity(0.05), borderRadius: BorderRadius.circular(16)),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: List.generate(3, (i) => Container(
              margin: const EdgeInsets.symmetric(horizontal: 2),
              width: 6, height: 6,
              decoration: const BoxDecoration(color: Colors.cyan, shape: BoxShape.circle),
            )),
          ),
        ),
      ],
    );
  }

  Widget _buildInputArea() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(color: Color(0xFF111111), border: Border(top: BorderSide(color: Color(0xFF222222)))),
      child: Row(
        children: [
          IconButton(
            icon: Icon(
              (_dictationArmed || _isListening) ? Icons.mic : Icons.mic_none,
              color: _isListening ? Colors.red : (_dictationArmed ? Colors.amber : Colors.white70),
            ),
            onPressed: _speechAvailable
                ? () async {
                    await _unlockTtsOnce();
                    _toggleListening();
                  }
                : null,
            tooltip: _dictationArmed ? "Stop dictation" : "Speak your message",
          ),
          IconButton(
            icon: Icon(_isSpeaking ? Icons.stop_circle : Icons.volume_up, color: Colors.white70),
            onPressed: _isSpeaking
                ? _stopReading
                : () async {
                    await _unlockTtsOnce();
                    await _readBackDraft();
                  },
            tooltip: _isSpeaking ? "Stop reading" : "Read draft aloud",
          ),
          const SizedBox(width: 6),
          Expanded(
            child: TextField(
              controller: _inputController,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                hintText: "Ask Nate about this client...",
                hintStyle: const TextStyle(color: Colors.grey),
                filled: true,
                fillColor: Colors.white.withOpacity(0.05),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
              ),
              readOnly: _isListening,
              keyboardType: TextInputType.multiline,
              minLines: 1,
              maxLines: 4,
              onSubmitted: _sendQuery,
            ),
          ),
          const SizedBox(width: 10),
          FloatingActionButton(
            mini: true,
            backgroundColor: Colors.cyan,
            onPressed: () => _sendQuery(_inputController.text),
            child: const Icon(Icons.arrow_forward, color: Colors.black),
          ),
        ],
      ),
    );
  }
}
// =============================================================================
// COACH PORTAL v2.0 - Part 4: Pre-Session Brief Screen
// =============================================================================

class PreSessionBriefScreen extends StatefulWidget {
  final Map<String, dynamic> client;
  final WebSocketChannel? socket;
  const PreSessionBriefScreen({super.key, required this.client, required this.socket});
  @override
  State<PreSessionBriefScreen> createState() => _PreSessionBriefScreenState();
}

class _PreSessionBriefScreenState extends State<PreSessionBriefScreen> {
  Map<String, dynamic>? _briefData;
  bool _isLoading = true;
  String? _error;
  StreamSubscription? _briefSub;

  @override
  void initState() {
    super.initState();
    _fetchBrief();
  }

  void _fetchBrief() {
    if (widget.socket == null) {
      setState(() { _isLoading = false; _error = 'No connection'; });
      return;
    }

    _briefSub = widget.socket!.stream.listen((msg) {
      try {
        final data = jsonDecode(msg);
        if (data['type'] == 'presession_brief') {
          if (mounted) setState(() { _briefData = data['brief'] ?? data; _isLoading = false; });
          _briefSub?.cancel();
        } else if (data['type'] == 'error' && (data['context'] ?? '').toString().contains('brief')) {
          if (mounted) setState(() { _error = data['message'] ?? 'Failed to load brief'; _isLoading = false; });
        }
      } catch (_) {}
    }, onError: (_) {
      if (mounted) setState(() { _error = 'Connection error'; _isLoading = false; });
    });

    widget.socket!.sink.add(jsonEncode({"type": "fetch_presession_brief", "client_id": widget.client['id']}));

    Future.delayed(const Duration(seconds: 8), () {
      if (mounted && _isLoading) {
        setState(() { _isLoading = false; _error = 'Request timed out'; });
      }
    });
  }

  @override
  void dispose() {
    _briefSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      appBar: AppBar(
        title: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text("📋 Pre-Session Brief", style: TextStyle(color: Color(0xFFFFD700), fontSize: 16, fontWeight: FontWeight.w600)),
          Text("Summary suggestions from Little Nate", style: TextStyle(color: Colors.grey, fontSize: 11)),
        ]),
        backgroundColor: const Color(0xFF1A1A10),
        leading: IconButton(icon: const Icon(Icons.arrow_back, color: Color(0xFFFFD700)), onPressed: () => Navigator.pop(context)),
      ),
      body: _isLoading ? const Center(child: CircularProgressIndicator(color: Color(0xFFFFD700))) : _buildContent(),
    );
  }

  Widget _buildContent() {
    if (_error != null || _briefData == null) {
      return Center(
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(_error ?? "Failed to load brief", style: const TextStyle(color: Colors.grey, fontSize: 14)),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: () { setState(() { _isLoading = true; _error = null; }); _fetchBrief(); },
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962)),
            child: const Text('Retry', style: TextStyle(color: Colors.black)),
          ),
        ]),
      );
    }
    return SingleChildScrollView(
      child: Column(children: [
        _buildSessionAlert(),
        Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _buildClientProfile(),
          const SizedBox(height: 14), _buildMoodIndicator(),
          const SizedBox(height: 14), _buildTopicsCard(),
          const SizedBox(height: 14), _buildBreakthroughsCard(),
          const SizedBox(height: 14), _buildFamilyCard(),
          const SizedBox(height: 14), _buildNateSuggestion(),
        ])),
      ]),
    );
  }

  Widget _buildSessionAlert() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(gradient: LinearGradient(colors: [Colors.green.withOpacity(0.2), Colors.green.withOpacity(0.1)]), border: Border.all(color: Colors.green.withOpacity(0.3))),
      child: Row(children: [
        const Text("🎥", style: TextStyle(fontSize: 24)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text("UPCOMING SESSION", style: TextStyle(color: Colors.green, fontSize: 12, fontWeight: FontWeight.w600)),
          Text(_briefData!['next_session'] ?? 'Unknown', style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w500)),
        ])),
        ElevatedButton(onPressed: () async {
          final zoomLink = _briefData?['zoom_link'] ?? _briefData?['meeting_url'] ?? '';
          if (zoomLink.toString().isNotEmpty) {
            final uri = Uri.parse(zoomLink.toString());
            if (await canLaunchUrl(uri)) {
              await launchUrl(uri, mode: LaunchMode.externalApplication);
            }
          } else {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('No Zoom link available for this session'), backgroundColor: Color(0xFF333333)),
              );
            }
          }
        }, style: ElevatedButton.styleFrom(backgroundColor: Colors.green, padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10)), child: const Text("Join Zoom", style: TextStyle(fontSize: 11))),
      ]),
    );
  }

  Widget _buildClientProfile() {
    final isTopTier = _briefData!['tier'] == 'TOP_TIER';
    return Row(children: [
      const CircleAvatar(radius: 28, backgroundColor: Color(0xFFFFD700), child: Text("👤", style: TextStyle(fontSize: 24))),
      const SizedBox(width: 14),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(_briefData!['client_name'] ?? 'Unknown', style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600)),
          if (isTopTier) Container(margin: const EdgeInsets.only(left: 8), padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(gradient: const LinearGradient(colors: [Color(0xFFFFD700), Color(0xFFFF8C00)]), borderRadius: BorderRadius.circular(10)),
            child: const Text("⭐ TOP TIER", style: TextStyle(color: Colors.black, fontSize: 9, fontWeight: FontWeight.bold))),
        ]),
        Text("${_briefData!['sessions_total']} sessions total • Client since ${_briefData!['client_since']}", style: const TextStyle(color: Colors.grey, fontSize: 11)),
      ])),
    ]);
  }

  Widget _buildMoodIndicator() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.cyan.withOpacity(0.05), border: Border.all(color: Colors.cyan.withOpacity(0.2)), borderRadius: BorderRadius.circular(10)),
      child: Row(children: [
        const Text("📊", style: TextStyle(fontSize: 20)),
        const SizedBox(width: 8),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text("RECENT AI SESSION MOOD", style: TextStyle(color: Colors.cyan, fontSize: 10, letterSpacing: 1)),
          Text("${_briefData!['recent_mood']} (${_briefData!['mood_date']})", style: const TextStyle(color: Colors.white, fontSize: 12)),
        ])),
      ]),
    );
  }

  Widget _buildTopicsCard() {
    final topics = _briefData!['topics'] as List<dynamic>? ?? [];
    return _buildCard(icon: "🎯", title: "Topics to Address", child: Column(children: topics.map((t) {
      final type = t['type'] ?? 'normal';
      Color dotColor = type == 'caution' ? Colors.orange : type == 'positive' ? Colors.green : const Color(0xFFFFD700);
      return Padding(padding: const EdgeInsets.only(bottom: 10), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(width: 6, height: 6, margin: const EdgeInsets.only(top: 6), decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle)),
        const SizedBox(width: 10),
        Expanded(child: Text(t['text'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 12, height: 1.5))),
      ]));
    }).toList()));
  }

  Widget _buildBreakthroughsCard() {
    final breakthroughs = _briefData!['breakthroughs'] as List<dynamic>? ?? [];
    return _buildCard(icon: "⚡", title: "Recent Breakthroughs", child: Column(children: breakthroughs.map((b) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(width: 6, height: 6, margin: const EdgeInsets.only(top: 6), decoration: const BoxDecoration(color: Colors.green, shape: BoxShape.circle)),
        const SizedBox(width: 10),
        Expanded(child: Text(b.toString(), style: const TextStyle(color: Colors.white70, fontSize: 12, height: 1.5))),
      ]),
    )).toList()));
  }

  Widget _buildFamilyCard() {
    final family = _briefData!['family'] as List<dynamic>? ?? [];
    return Container(
      decoration: BoxDecoration(color: Colors.orange.withOpacity(0.1), border: Border.all(color: Colors.orange.withOpacity(0.3)), borderRadius: BorderRadius.circular(14)),
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(children: [Text("👨‍👩‍👧", style: TextStyle(fontSize: 18)), SizedBox(width: 10), Text("Family Context", style: TextStyle(color: Color(0xFFFFD700), fontSize: 13, fontWeight: FontWeight.w600))]),
        const SizedBox(height: 12),
        ...family.map((f) => Container(
          margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: Colors.white.withOpacity(0.03), borderRadius: BorderRadius.circular(8)),
          child: Row(children: [
            CircleAvatar(radius: 16, backgroundColor: Colors.orange.withOpacity(0.3), child: const Text("👤", style: TextStyle(fontSize: 14))),
            const SizedBox(width: 10),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(f['name'] ?? 'Unknown', style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w500)),
              Text(f['relation'] ?? '', style: const TextStyle(color: Colors.grey, fontSize: 10)),
              if (f['note'] != null) Text("⚠️ ${f['note']}", style: const TextStyle(color: Colors.orange, fontSize: 10)),
            ])),
          ]),
        )).toList(),
      ]),
    );
  }

  Widget _buildNateSuggestion() {
    return Container(
      decoration: BoxDecoration(gradient: const LinearGradient(colors: [Color(0xFF0A1A1A), Color(0xFF051515)]), border: Border.all(color: Colors.cyan.withOpacity(0.3)), borderRadius: BorderRadius.circular(14)),
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 32, height: 32, decoration: BoxDecoration(shape: BoxShape.circle, gradient: const RadialGradient(colors: [Color(0xFF001A33), Colors.black]),
            boxShadow: [BoxShadow(color: Colors.cyan.withOpacity(0.3), blurRadius: 12)]),
            child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [CircleAvatar(radius: 3, backgroundColor: Colors.white), SizedBox(width: 6), CircleAvatar(radius: 3, backgroundColor: Colors.white)])),
          const SizedBox(width: 10),
          const Text("Little Nate's Suggestion", style: TextStyle(color: Colors.cyan, fontSize: 13, fontWeight: FontWeight.w600)),
        ]),
        const SizedBox(height: 12),
        Text(_briefData!['nate_suggestion'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 12, height: 1.6)),
      ]),
    );
  }

  Widget _buildCard({required String icon, required String title, required Widget child}) {
    return Container(
      decoration: BoxDecoration(gradient: const LinearGradient(colors: [Color(0xFF1A1A1A), Color(0xFF151515)]), border: Border.all(color: const Color(0xFF252525)), borderRadius: BorderRadius.circular(14)),
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Text(icon, style: const TextStyle(fontSize: 18)), const SizedBox(width: 10), Text(title, style: const TextStyle(color: Color(0xFFFFD700), fontSize: 13, fontWeight: FontWeight.w600))]),
        const SizedBox(height: 12),
        child,
      ]),
    );
  }
}
// =============================================================================
// COACH PORTAL v2.0 - Part 5: Coaching Advice Screen & Dialogs
// =============================================================================

// COACHING ADVICE SCREEN (Post-Session Analysis)
class CoachingAdviceScreen extends StatefulWidget {
  final Map<String, dynamic> session;
  final WebSocketChannel? socket;
  const CoachingAdviceScreen({super.key, required this.session, required this.socket});
  @override
  State<CoachingAdviceScreen> createState() => _CoachingAdviceScreenState();
}

class _CoachingAdviceScreenState extends State<CoachingAdviceScreen> {
  Map<String, dynamic>? _adviceData;
  bool _isLoading = true;
  String? _error;
  StreamSubscription? _adviceSub;

  @override
  void initState() {
    super.initState();
    _fetchAdvice();
  }

  void _fetchAdvice() {
    if (widget.socket == null) {
      setState(() { _isLoading = false; _error = 'No connection'; });
      return;
    }

    _adviceSub = widget.socket!.stream.listen((msg) {
      try {
        final data = jsonDecode(msg);
        if (data['type'] == 'coaching_advice' || data['type'] == 'session_advice') {
          if (mounted) setState(() { _adviceData = data['advice'] ?? data; _isLoading = false; });
          _adviceSub?.cancel();
        } else if (data['type'] == 'error' && (data['context'] ?? '').toString().contains('advice')) {
          if (mounted) setState(() { _error = data['message'] ?? 'Failed to load advice'; _isLoading = false; });
        }
      } catch (_) {}
    }, onError: (_) {
      if (mounted) setState(() { _error = 'Connection error'; _isLoading = false; });
    });

    final sessionId = widget.session['id'] ?? widget.session['session_id'] ?? '';
    final clientId = widget.session['client_id'] ?? widget.session['client_hardware_id'] ?? '';
    widget.socket!.sink.add(jsonEncode({
      "type": "fetch_coaching_advice",
      "session_id": sessionId,
      "client_id": clientId,
    }));

    Future.delayed(const Duration(seconds: 10), () {
      if (mounted && _isLoading) {
        setState(() { _isLoading = false; _error = 'Request timed out'; });
      }
    });
  }

  @override
  void dispose() {
    _adviceSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      appBar: AppBar(
        title: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text("🧠 Coaching Advice", style: TextStyle(color: Colors.purple, fontSize: 16)),
          Text("AI-generated session analysis", style: TextStyle(color: Colors.grey, fontSize: 11)),
        ]),
        backgroundColor: const Color(0xFF1A0A1A),
        leading: IconButton(icon: const Icon(Icons.arrow_back, color: Colors.purple), onPressed: () => Navigator.pop(context)),
        actions: [Container(margin: const EdgeInsets.only(right: 16), width: 36, height: 36,
          decoration: BoxDecoration(shape: BoxShape.circle, gradient: const RadialGradient(colors: [Color(0xFF001A33), Colors.black]),
            boxShadow: [BoxShadow(color: Colors.cyan.withOpacity(0.3), blurRadius: 15)]),
          child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [CircleAvatar(radius: 3, backgroundColor: Colors.white), SizedBox(width: 6), CircleAvatar(radius: 3, backgroundColor: Colors.white)]))],
      ),
      body: _isLoading ? const Center(child: CircularProgressIndicator(color: Colors.purple)) : _buildContent(),
      bottomNavigationBar: _buildActions(),
    );
  }

  Widget _buildContent() {
    if (_error != null || _adviceData == null) {
      return Center(
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(_error ?? "Failed to load advice", style: const TextStyle(color: Colors.grey, fontSize: 14)),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: () { setState(() { _isLoading = true; _error = null; }); _fetchAdvice(); },
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF9D4EDD)),
            child: const Text('Retry', style: TextStyle(color: Colors.white)),
          ),
        ]),
      );
    }
    return SingleChildScrollView(child: Column(children: [
      _buildSessionContext(),
      Padding(padding: const EdgeInsets.all(16), child: Column(children: [
        _buildKeyObservations(),
        const SizedBox(height: 16), _buildBiometrics(),
        const SizedBox(height: 16), _buildNotableMoments(),
        const SizedBox(height: 16), _buildNextSessionSuggestions(),
      ])),
    ]));
  }

  Widget _buildSessionContext() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.purple.withOpacity(0.1), border: const Border(bottom: BorderSide(color: Color(0xFF333033)))),
      child: Row(children: [
        const CircleAvatar(backgroundColor: Color(0xFFFFD700), child: Text("👤")),
        const SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text("${_adviceData!['client_name']} ⭐", style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500)),
          Text("Session: ${_adviceData!['session_date']} • ${_adviceData!['duration']} min", style: const TextStyle(color: Colors.grey, fontSize: 10)),
        ]),
      ]),
    );
  }

  Widget _buildKeyObservations() {
    return Container(
      decoration: BoxDecoration(gradient: const LinearGradient(colors: [Color(0xFF1A1020), Color(0xFF150A15)]), border: Border.all(color: Colors.purple.withOpacity(0.3)), borderRadius: BorderRadius.circular(16)),
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(children: [Text("💡", style: TextStyle(fontSize: 24)), SizedBox(width: 10), Text("Key Observations", style: TextStyle(color: Colors.purple, fontSize: 14, fontWeight: FontWeight.w600))]),
        const SizedBox(height: 12),
        Text(_adviceData!['key_observation'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 13, height: 1.6)),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: Colors.purple.withOpacity(0.15), borderRadius: BorderRadius.circular(8), border: Border(left: BorderSide(color: Colors.purple.shade200, width: 3))),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text("Recommendation: ", style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
            Expanded(child: Text(_adviceData!['recommendation'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 12))),
          ]),
        ),
      ]),
    );
  }

  Widget _buildBiometrics() {
    final biometrics = _adviceData!['biometrics'] as Map<String, dynamic>? ?? {};
    return Container(
      decoration: BoxDecoration(color: Colors.white.withOpacity(0.03), borderRadius: BorderRadius.circular(12)),
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text("SESSION BIOMETRICS", style: TextStyle(color: Colors.grey, fontSize: 10, letterSpacing: 1)),
        const SizedBox(height: 12),
        _buildMetricRow("Engagement", biometrics['engagement'] ?? 0, Colors.green),
        _buildMetricRow("Emotional Range", biometrics['emotional_range'] ?? 0, Colors.green),
        _buildMetricRow("Stress Level", biometrics['stress_level'] ?? 0, Colors.orange),
        _buildMetricRow("Openness", biometrics['openness'] ?? 0, Colors.green),
      ]),
    );
  }

  Widget _buildMetricRow(String label, int value, Color color) {
    return Padding(padding: const EdgeInsets.only(bottom: 10), child: Row(children: [
      SizedBox(width: 100, child: Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11))),
      Expanded(child: Container(height: 6, decoration: BoxDecoration(color: Colors.white.withOpacity(0.1), borderRadius: BorderRadius.circular(3)),
        child: FractionallySizedBox(alignment: Alignment.centerLeft, widthFactor: value / 100,
          child: Container(decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3)))))),
      const SizedBox(width: 12),
      SizedBox(width: 40, child: Text("$value%", style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w500), textAlign: TextAlign.right)),
    ]));
  }

  Widget _buildNotableMoments() {
    final moments = _adviceData!['notable_moments'] as List<dynamic>? ?? [];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text("NOTABLE MOMENTS", style: TextStyle(color: Colors.grey, fontSize: 10, letterSpacing: 1)),
      const SizedBox(height: 10),
      ...moments.map((m) => Container(
        margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: Colors.white.withOpacity(0.03), borderRadius: BorderRadius.circular(8)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), decoration: BoxDecoration(color: Colors.cyan.withOpacity(0.1), borderRadius: BorderRadius.circular(6)),
            child: Text(m['time'] ?? '', style: const TextStyle(color: Colors.cyan, fontSize: 10, fontFamily: 'monospace'))),
          const SizedBox(width: 10),
          Expanded(child: Text(m['desc'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 11, height: 1.4))),
        ]),
      )).toList(),
    ]);
  }

  Widget _buildNextSessionSuggestions() {
    final suggestions = _adviceData!['next_session_suggestions'] as List<dynamic>? ?? [];
    return Container(
      decoration: BoxDecoration(gradient: const LinearGradient(colors: [Color(0xFF1A1020), Color(0xFF150A15)]), border: Border.all(color: Colors.purple.withOpacity(0.3)), borderRadius: BorderRadius.circular(16)),
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(children: [Text("📋", style: TextStyle(fontSize: 24)), SizedBox(width: 10), Text("For Next Session", style: TextStyle(color: Colors.purple, fontSize: 14, fontWeight: FontWeight.w600))]),
        const SizedBox(height: 12),
        ...suggestions.map((s) => Padding(padding: const EdgeInsets.only(bottom: 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text("• ", style: TextStyle(color: Colors.white70)),
            Expanded(child: Text(s.toString(), style: const TextStyle(color: Colors.white70, fontSize: 12, height: 1.4))),
          ]))).toList(),
      ]),
    );
  }

  Widget _buildActions() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(color: Color(0xFF111111), border: Border(top: BorderSide(color: Color(0xFF222222)))),
      child: Row(children: [
        Expanded(child: ElevatedButton.icon(onPressed: () {
          // Save coaching advice to client file via WebSocket
          widget.socket?.sink.add(jsonEncode({
            'type': 'coach_live_note',
            'client_id': widget.session['client_id'] ?? widget.session['id'] ?? '',
            'note_type': 'coaching_advice',
            'note': jsonEncode(_adviceData),
            'session_date': widget.session['date'] ?? '',
          }));
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Saved to client file'), backgroundColor: Color(0xFF1A1A1A)),
            );
          }
        }, icon: const Icon(Icons.save, size: 16), label: const Text("Save to Client File"),
          style: ElevatedButton.styleFrom(backgroundColor: Colors.purple, padding: const EdgeInsets.symmetric(vertical: 14)))),
        const SizedBox(width: 10),
        Expanded(child: OutlinedButton.icon(onPressed: () {
          // Export coaching advice — format as text and trigger share sheet
          final buf = StringBuffer()
            ..writeln('Coaching Advice — ${_adviceData?['client_name'] ?? 'Unknown'}')
            ..writeln('Session Date: ${_adviceData?['session_date'] ?? ''}')
            ..writeln('Duration: ${_adviceData?['duration'] ?? ''} min')
            ..writeln()
            ..writeln('KEY OBSERVATION:')
            ..writeln(_adviceData?['key_observation'] ?? '')
            ..writeln()
            ..writeln('RECOMMENDATION:')
            ..writeln(_adviceData?['recommendation'] ?? '')
            ..writeln()
            ..writeln('NEXT SESSION SUGGESTIONS:');
          for (final s in (_adviceData?['next_session_suggestions'] as List? ?? [])) {
            buf.writeln('• $s');
          }
          // Send as WebSocket message for server-side export
          widget.socket?.sink.add(jsonEncode({
            'type': 'save_recording',
            'client_id': widget.session['client_id'] ?? widget.session['id'] ?? '',
            'content': buf.toString(),
            'filename': 'coaching_advice_${widget.session['client'] ?? 'session'}.txt',
          }));
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Export sent'), backgroundColor: Color(0xFF1A1A1A)),
            );
          }
        }, icon: const Icon(Icons.upload, size: 16), label: const Text("Export"),
          style: OutlinedButton.styleFrom(foregroundColor: Colors.grey, side: const BorderSide(color: Colors.grey), padding: const EdgeInsets.symmetric(vertical: 14)))),
      ]),
    );
  }
}

// =============================================================================
// DIALOGS
// =============================================================================

class ClientActionsSheet extends StatelessWidget {
  final Map<String, dynamic> client;
  final VoidCallback onAskNate, onPreSessionBrief, onViewHistory;
  const ClientActionsSheet({super.key, required this.client, required this.onAskNate, required this.onPreSessionBrief, required this.onViewHistory});

  @override
  Widget build(BuildContext context) {
    return Container(padding: const EdgeInsets.all(20), child: Column(mainAxisSize: MainAxisSize.min, children: [
      Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey, borderRadius: BorderRadius.circular(2))),
      const SizedBox(height: 20),
      Text(client['name'] ?? 'Unknown', style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600)),
      const SizedBox(height: 20),
      _buildTile(Icons.videocam, "Join Session", Colors.green, () {}),
      _buildTile(Icons.chat, "Ask Nate", Colors.cyan, onAskNate),
      _buildTile(Icons.description, "Pre-Session Brief", const Color(0xFFFFD700), onPreSessionBrief),
      _buildTile(Icons.history, "View History", Colors.grey, onViewHistory),
      _buildTile(Icons.message, "Send Message", Colors.blue, () {}),
    ]));
  }

  Widget _buildTile(IconData icon, String label, Color color, VoidCallback onTap) {
    return ListTile(leading: Icon(icon, color: color), title: Text(label, style: const TextStyle(color: Colors.white)), onTap: onTap);
  }
}

class SessionActionsDialog extends StatelessWidget {
  final Map<String, dynamic> session;
  final VoidCallback onJoin, onCancel, onReschedule;
  const SessionActionsDialog({super.key, required this.session, required this.onJoin, required this.onCancel, required this.onReschedule});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF1A1A1A),
      title: Text(session['client'] ?? 'Session', style: const TextStyle(color: Colors.white)),
      content: Text("${session['date']} at ${session['time']}", style: const TextStyle(color: Colors.grey)),
      actions: [
        TextButton(onPressed: onReschedule, child: const Text("Reschedule")),
        TextButton(onPressed: onCancel, child: const Text("Cancel", style: TextStyle(color: Colors.red))),
        ElevatedButton(onPressed: onJoin, style: ElevatedButton.styleFrom(backgroundColor: Colors.green), child: const Text("Join")),
      ],
    );
  }
}

class CancelSessionDialog extends StatefulWidget {
  final Map<String, dynamic> session;
  final Function(String reason, bool sendReschedule) onConfirm;
  const CancelSessionDialog({super.key, required this.session, required this.onConfirm});
  @override
  State<CancelSessionDialog> createState() => _CancelSessionDialogState();
}

class _CancelSessionDialogState extends State<CancelSessionDialog> {
  String _selectedReason = 'Schedule conflict';
  bool _sendRescheduleLink = true;
  final List<String> _reasons = ['Schedule conflict', 'Emergency', 'Illness', 'Client requested', 'Other'];

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF1A1A1A),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Text("⚠️", style: TextStyle(fontSize: 48)),
        const SizedBox(height: 16),
        const Text("Cancel Session", style: TextStyle(color: Colors.red, fontSize: 18, fontWeight: FontWeight.w600)),
        const Text("This action will notify the client", style: TextStyle(color: Colors.grey, fontSize: 12)),
        const SizedBox(height: 20),
        Container(padding: const EdgeInsets.all(14), decoration: BoxDecoration(color: Colors.white.withOpacity(0.05), border: Border.all(color: Colors.white.withOpacity(0.1)), borderRadius: BorderRadius.circular(12)),
          child: Column(children: [
            _buildInfoRow("Client", widget.session['client'] ?? 'Unknown'),
            _buildInfoRow("Date & Time", "${widget.session['date']} • ${widget.session['time']}"),
            _buildInfoRow("Session Type", "${widget.session['type'] ?? 'Individual'} (${widget.session['duration'] ?? '50'} min)"),
          ])),
        const SizedBox(height: 20),
        DropdownButtonFormField<String>(
          value: _selectedReason,
          decoration: const InputDecoration(labelText: "Reason for Cancellation", labelStyle: TextStyle(color: Colors.grey)),
          dropdownColor: const Color(0xFF2A2A2A),
          style: const TextStyle(color: Colors.white),
          items: _reasons.map((r) => DropdownMenuItem(value: r, child: Text(r))).toList(),
          onChanged: (v) => setState(() => _selectedReason = v ?? _selectedReason),
        ),
        const SizedBox(height: 16),
        CheckboxListTile(
          value: _sendRescheduleLink,
          onChanged: (v) => setState(() => _sendRescheduleLink = v ?? true),
          title: const Text("Send reschedule link to client", style: TextStyle(color: Colors.grey, fontSize: 11)),
          activeColor: Colors.blue,
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
        ),
        const SizedBox(height: 20),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: () => Navigator.pop(context),
            style: OutlinedButton.styleFrom(foregroundColor: Colors.grey, side: const BorderSide(color: Colors.grey), padding: const EdgeInsets.symmetric(vertical: 14)),
            child: const Text("Go Back"))),
          const SizedBox(width: 12),
          Expanded(child: ElevatedButton(onPressed: () => widget.onConfirm(_selectedReason, _sendRescheduleLink),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, padding: const EdgeInsets.symmetric(vertical: 14)),
            child: const Text("Cancel Session"))),
        ]),
      ])),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(padding: const EdgeInsets.only(bottom: 8), child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
      Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11)),
      Text(value, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w500)),
    ]));
  }
}

// =============================================================================
// COACH QUICKBOOKS TAB
// =============================================================================
class CoachQuickBooksTab extends StatefulWidget {
  final Map<String, dynamic> coachProfile;
  const CoachQuickBooksTab({super.key, required this.coachProfile});
  @override
  State<CoachQuickBooksTab> createState() => _CoachQuickBooksTabState();
}

class _CoachQuickBooksTabState extends State<CoachQuickBooksTab> {
  bool _loading = true;
  bool _connected = false;
  String? _companyName;
  String? _lastSync;
  bool _tokenExpired = false;
  String? _errorMessage;
  List<dynamic> _syncHistory = [];
  List<dynamic> _mappings = [];
  bool _syncing = false;

  String get _apiBase => central_config.AppConfig.apiBaseUrl;
  String get _token => widget.coachProfile['token'] ?? '';
  Map<String, String> get _headers => {'Authorization': 'Bearer $_token', 'Content-Type': 'application/json'};

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  Future<void> _loadStatus() async {
    setState(() => _loading = true);
    try {
      final resp = await http.get(Uri.parse('$_apiBase/api/coach/quickbooks/status'), headers: _headers);
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _connected = data['connected'] == true;
          _companyName = data['company_name'] as String?;
          _lastSync = data['last_sync_at'] as String?;
          _tokenExpired = data['token_expired'] == true;
          _errorMessage = data['error_message'] as String?;
          _loading = false;
        });
        if (_connected) {
          _loadSyncHistory();
          _loadMappings();
        }
      } else {
        setState(() { _loading = false; _connected = false; });
      }
    } catch (e) {
      debugPrint('[CoachQB] status error: $e');
      if (mounted) setState(() { _loading = false; _connected = false; });
    }
  }

  Future<void> _loadSyncHistory() async {
    try {
      final resp = await http.get(Uri.parse('$_apiBase/api/coach/quickbooks/sync/history?limit=20'), headers: _headers);
      if (resp.statusCode == 200 && mounted) {
        final parsed = jsonDecode(resp.body);
        if (parsed is List) setState(() => _syncHistory = parsed);
      }
    } catch (_) {}
  }

  Future<void> _loadMappings() async {
    try {
      final resp = await http.get(Uri.parse('$_apiBase/api/coach/quickbooks/account-mapping'), headers: _headers);
      if (resp.statusCode == 200 && mounted) {
        final parsed = jsonDecode(resp.body);
        if (parsed is List) setState(() => _mappings = parsed);
      }
    } catch (_) {}
  }

  Future<void> _connect() async {
    try {
      final resp = await http.get(Uri.parse('$_apiBase/api/coach/quickbooks/connect'), headers: _headers);
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        if (data['oauth_url'] != null) {
          final url = Uri.parse(data['oauth_url'] as String);
          if (await canLaunchUrl(url)) {
            await launchUrl(url, mode: LaunchMode.externalApplication);
          }
          return;
        }
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not get OAuth URL'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _disconnect() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        title: const Text('Disconnect QuickBooks?', style: TextStyle(color: Colors.white)),
        content: const Text('This will revoke your QuickBooks connection.', style: TextStyle(color: Colors.grey)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Disconnect', style: TextStyle(color: Colors.red))),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await http.post(Uri.parse('$_apiBase/api/coach/quickbooks/disconnect'), headers: _headers);
    } catch (_) {}
    _loadStatus();
  }

  Future<void> _syncNow() async {
    setState(() => _syncing = true);
    try {
      final resp = await http.post(Uri.parse('$_apiBase/api/coach/quickbooks/sync/trigger'), headers: _headers);
      if (!mounted) return;
      setState(() => _syncing = false);
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final total = data['total_synced'] ?? 0;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Sync complete: $total records'), backgroundColor: const Color(0xFF22C55E)),
        );
        _loadSyncHistory();
        _loadStatus();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Sync failed'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() => _syncing = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Sync error: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: Color(0xFFFFD700)));
    }
    return ListView(padding: const EdgeInsets.all(16), children: [
      _buildStatusCard(),
      const SizedBox(height: 16),
      if (_connected) ...[
        _buildMappingCard(),
        const SizedBox(height: 16),
        _buildSyncHistoryCard(),
      ],
    ]);
  }

  Widget _buildStatusCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: const Color(0xFF111111), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFF252525))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('QuickBooks Connection', style: TextStyle(color: Color(0xFFC9A962), fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 16),
        Row(children: [
          Icon(_connected ? Icons.check_circle : Icons.cancel, color: _connected ? const Color(0xFF22C55E) : Colors.grey, size: 20),
          const SizedBox(width: 8),
          Text(_connected ? 'Connected' : 'Not Connected', style: TextStyle(color: _connected ? const Color(0xFF22C55E) : Colors.grey, fontSize: 14)),
        ]),
        if (_connected && _companyName != null) ...[
          const SizedBox(height: 8),
          Text('Company: $_companyName', style: const TextStyle(color: Colors.white70, fontSize: 13)),
        ],
        if (_connected && _lastSync != null) ...[
          const SizedBox(height: 4),
          Text('Last Sync: ${_lastSync!.length >= 16 ? _lastSync!.substring(0, 16).replaceAll('T', ' ') : _lastSync!}', style: const TextStyle(color: Colors.grey, fontSize: 12)),
        ],
        if (_errorMessage != null) ...[
          const SizedBox(height: 8),
          Text(_errorMessage!, style: const TextStyle(color: Colors.red, fontSize: 12)),
        ],
        const SizedBox(height: 16),
        Wrap(spacing: 8, children: [
          if (!_connected)
            ElevatedButton.icon(onPressed: _connect, icon: const Icon(Icons.link, size: 16), label: const Text('Connect to QuickBooks'),
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF2CA01C), foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10))),
          if (_connected) ...[
            ElevatedButton.icon(
              onPressed: _syncing ? null : _syncNow,
              icon: _syncing ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black)) : const Icon(Icons.sync, size: 16),
              label: Text(_syncing ? 'Syncing...' : 'Sync Now'),
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962), foregroundColor: Colors.black, padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10))),
            OutlinedButton(onPressed: _disconnect, style: OutlinedButton.styleFrom(foregroundColor: Colors.red, side: const BorderSide(color: Colors.red), padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10)),
              child: const Text('Disconnect')),
          ],
        ]),
      ]),
    );
  }

  Widget _buildMappingCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: const Color(0xFF111111), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFF252525))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Account Mapping', style: TextStyle(color: Color(0xFFC9A962), fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        const Text('Map your coaching income categories to QuickBooks accounts.', style: TextStyle(color: Colors.grey, fontSize: 12)),
        const SizedBox(height: 12),
        if (_mappings.isEmpty)
          const Text('No mappings configured yet.', style: TextStyle(color: Colors.grey, fontSize: 13))
        else
          ..._mappings.map((m) => Padding(padding: const EdgeInsets.only(bottom: 6), child: Row(children: [
            Expanded(child: Text(m['internal_category'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 13))),
            Text('\u2192 ${m['qb_account_name'] ?? m['qb_account_id'] ?? ''}', style: const TextStyle(color: Color(0xFFC9A962), fontSize: 13)),
          ]))),
      ]),
    );
  }

  Widget _buildSyncHistoryCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: const Color(0xFF111111), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFF252525))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Sync History', style: TextStyle(color: Color(0xFFC9A962), fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        if (_syncHistory.isEmpty)
          const Text('No sync history yet.', style: TextStyle(color: Colors.grey, fontSize: 13))
        else
          ..._syncHistory.take(10).map((h) => Padding(padding: const EdgeInsets.only(bottom: 8), child: Row(children: [
            Icon(h['status'] == 'synced' ? Icons.check_circle_outline : Icons.error_outline, color: h['status'] == 'synced' ? const Color(0xFF22C55E) : Colors.red, size: 16),
            const SizedBox(width: 8),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(h['sync_type'] ?? '', style: const TextStyle(color: Colors.white70, fontSize: 12)),
              if (h['created_at'] != null)
                Text((h['created_at'] as String).length >= 16 ? (h['created_at'] as String).substring(0, 16).replaceAll('T', ' ') : h['created_at'] as String,
                    style: const TextStyle(color: Colors.grey, fontSize: 10)),
            ])),
            if (h['amount_cents'] != null)
              Text('\$${(h['amount_cents'] / 100).toStringAsFixed(2)}', style: const TextStyle(color: Color(0xFFC9A962), fontSize: 12)),
          ]))),
      ]),
    );
  }
}


class SchedulerDialog extends StatefulWidget {
  final Function(String slot) onPublish;
  const SchedulerDialog({super.key, required this.onPublish});
  @override
  State<SchedulerDialog> createState() => _SchedulerDialogState();
}

class _SchedulerDialogState extends State<SchedulerDialog> {
  final TextEditingController _slotController = TextEditingController();
  @override
  void dispose() { _slotController.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF1A1A1A),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      title: const Text("MANAGE AVAILABILITY", style: TextStyle(color: Colors.white, fontSize: 16)),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: _slotController, style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(labelText: "Add Slot (e.g. 'Mon 10:00 AM')", labelStyle: TextStyle(color: Colors.grey), hintText: "Tue 3:00 PM", hintStyle: TextStyle(color: Colors.grey))),
        const SizedBox(height: 20),
        SizedBox(width: double.infinity, child: ElevatedButton(
          onPressed: () { if (_slotController.text.isNotEmpty) widget.onPublish(_slotController.text); },
          style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFFD700), foregroundColor: Colors.black, padding: const EdgeInsets.symmetric(vertical: 14)),
          child: const Text("Publish Slot"))),
      ]),
    );
  }
}
