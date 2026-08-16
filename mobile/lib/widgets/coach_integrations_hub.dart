// Coach Command Integrations hub — Workspace, LinkedIn, Voice, Studio, Vault.
import 'dart:async';
import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';
import '../services/coach_web_recorder.dart';
import 'google_calendar_section.dart';
import 'google_workspace_section.dart';

class CoachIntegrationsHub extends StatefulWidget {
  final String token;
  const CoachIntegrationsHub({super.key, required this.token});

  @override
  State<CoachIntegrationsHub> createState() => _CoachIntegrationsHubState();
}

class _CoachIntegrationsHubState extends State<CoachIntegrationsHub>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs;
  Map<String, dynamic>? _hub;
  String? _error;
  bool _loading = true;
  final _chatCtrl = TextEditingController();
  final _campaignTitleCtrl = TextEditingController(text: 'Campaign');
  int _lengthDays = 7;

  static const _gold = Color(0xFFC9A962);
  static const _goldDim = Color(0xFF8B7355);
  static const _text = Color(0xFFE8D5A3);
  static const _muted = Color(0xFF8B7355);
  static const _card = Color(0xFF111111);

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 8, vsync: this);
    _load();
  }

  @override
  void dispose() {
    _tabs.dispose();
    _chatCtrl.dispose();
    _campaignTitleCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/hub'),
        headers: _h,
      );
      if (r.statusCode != 200) {
        setState(() {
          _error = 'Hub unavailable (${r.statusCode})';
          _loading = false;
        });
        return;
      }
      setState(() {
        _hub = json.decode(r.body) as Map<String, dynamic>;
        _chatCtrl.text = (_hub?['chat_webhook_url'] ?? '').toString();
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TabBar(
          controller: _tabs,
          isScrollable: true,
          indicatorColor: _gold,
          labelColor: _gold,
          unselectedLabelColor: Colors.grey,
          tabs: const [
            Tab(text: 'OVERVIEW'),
            Tab(text: 'WORKSPACE'),
            Tab(text: 'LINKEDIN'),
            Tab(text: 'VOICE'),
            Tab(text: 'VIDEO'),
            Tab(text: 'CAMPAIGN'),
            Tab(text: 'STUDIO'),
            Tab(text: 'VAULT'),
          ],
        ),
        Expanded(
          child: _loading
              ? const Center(
                  child: CircularProgressIndicator(color: _gold, strokeWidth: 2))
              : TabBarView(
                  controller: _tabs,
                  children: [
                    _overview(),
                    _workspace(),
                    _linkedin(),
                    _voice(),
                    _video(),
                    _CampaignQueue(
                      token: widget.token,
                      isMaster: _hub?['supervision']?['is_master'] == true,
                    ),
                    _studio(),
                    _vault(),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _overview() {
    final cards = List<Map<String, dynamic>>.from(_hub?['cards'] ?? []);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (_error != null)
          Text(_error!, style: const TextStyle(color: Colors.redAccent)),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: cards
              .map((c) => _statCard(
                    (c['title'] ?? '').toString(),
                    (c['detail'] ?? '').toString(),
                  ))
              .toList(),
        ),
        const SizedBox(height: 16),
        const Text(
          'Connect, update, and disconnect each coach slice from these tabs. '
          'Google Calendar (session sync) is separate from Google Workspace '
          '(Gmail drafts + Drive). LinkedIn is your coach page, never Nate’s SkyEye.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 12),
        _supervisionCard(),
        const SizedBox(height: 12),
        _draftsCard(),
        const SizedBox(height: 12),
        _morningBriefCard(),
        const SizedBox(height: 12),
        _flagPanels(),
      ],
    );
  }

  Widget _flagPanels() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _CreateTaskCard(token: widget.token),
        const SizedBox(height: 12),
        _RemoteListCard(
          token: widget.token,
          title: 'OPEN TASKS',
          icon: Icons.checklist,
          path: '/api/workspace/google/tasks',
          keyName: 'tasks',
          labelOf: (m) => (m['title'] ?? '').toString(),
        ),
        const SizedBox(height: 12),
        _RemoteListCard(
          token: widget.token,
          title: 'PRACTICE LIBRARY',
          icon: Icons.menu_book_outlined,
          path: '/api/workspace/google/libraries',
          keyName: 'templates',
          labelOf: (m) => (m['title'] ?? m['name'] ?? '').toString(),
        ),
        const SizedBox(height: 12),
        _RemoteListCard(
          token: widget.token,
          title: 'CREDENTIALS',
          icon: Icons.badge_outlined,
          path: '/api/workspace/google/credentials',
          keyName: 'credentials',
          labelOf: (m) => (m['label'] ?? m['name'] ?? m['credential_type'] ?? '').toString(),
        ),
      ],
    );
  }

  Widget _supervisionCard() {
    final sup = Map<String, dynamic>.from(_hub?['supervision'] ?? {});
    final isMaster = sup['is_master'] == true;
    final assistants = List<Map<String, dynamic>>.from(sup['assistants'] ?? []);
    return _panel(
      'MASTER COACH / SUPERVISION',
      Icons.supervisor_account,
      [
        Text(
          isMaster
              ? 'You are a master coach (${assistants.length} active assistants on coach_hierarchy). Same roster as ASSISTANTS.'
              : 'No active assistants under this hardware_id. ASSISTANTS still lists coaches you can invite.',
          style: const TextStyle(color: _muted, fontSize: 12),
        ),
        if (assistants.isNotEmpty) ...[
          const SizedBox(height: 8),
          ...assistants.take(12).map((a) => Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '${a['name'] ?? ''}  ·  ${a['username'] ?? ''}',
                  style: const TextStyle(color: _text, fontSize: 13),
                ),
              )),
        ],
      ],
    );
  }

  Widget _statCard(String title, String detail) {
    return Container(
      width: 200,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _goldDim.withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title.toUpperCase(),
              style: const TextStyle(
                  color: _gold, fontSize: 11, letterSpacing: 1.1)),
          const SizedBox(height: 8),
          Text(detail, style: const TextStyle(color: _text, fontSize: 14)),
        ],
      ),
    );
  }

  Widget _workspace() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        GoogleCalendarSection(token: widget.token),
        GoogleWorkspaceSection(token: widget.token, forceShow: true),
        const SizedBox(height: 12),
        _chatWebhookCard(),
      ],
    );
  }

  Widget _chatWebhookCard() {
    return _panel(
      'GOOGLE CHAT WEBHOOK',
      Icons.chat_outlined,
      [
        TextField(
          controller: _chatCtrl,
          style: const TextStyle(color: _text, fontSize: 13),
          decoration: const InputDecoration(
            hintText: 'https://chat.googleapis.com/...',
            hintStyle: TextStyle(color: _muted),
            enabledBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: _goldDim)),
          ),
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: _gold),
          onPressed: () async {
            final r = await http.put(
              Uri.parse(
                  '${AppConfig.apiBaseUrl}/api/coach/integrations/chat-webhook'),
              headers: _h,
              body: json.encode({'url': _chatCtrl.text.trim()}),
            );
            if (!mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                content: Text(r.statusCode == 200
                    ? 'Chat webhook saved'
                    : 'Save failed (${r.statusCode})')));
            _load();
          },
          child: const Text('Save webhook',
              style: TextStyle(color: Colors.black)),
        ),
      ],
    );
  }

  Widget _linkedin() {
    final li = Map<String, dynamic>.from(_hub?['linkedin'] ?? {});
    final connected = li['connected'] == true;
    final urn = (li['person_urn'] ?? '').toString();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _panel(
          'COACH LINKEDIN',
          Icons.work_outline,
          [
            Text(
              connected
                  ? 'Connected${urn.isNotEmpty ? ': $urn' : ''}. Campaigns publish with this token only — never Nate’s SkyEye page.'
                  : 'Sign in with YOUR LinkedIn. Each coach connects their own account. Campaigns publish with that token — never Nate’s SkyEye page.',
              style: const TextStyle(color: _muted, fontSize: 12),
            ),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              icon: const Icon(Icons.link, color: Colors.black, size: 18),
              label: Text(connected ? 'Reconnect LinkedIn' : 'Connect LinkedIn',
                  style: const TextStyle(color: Colors.black)),
              onPressed: _connectLinkedIn,
            ),
            if (connected)
              TextButton(
                onPressed: _disconnectLinkedIn,
                child: const Text('Disconnect LinkedIn',
                    style: TextStyle(color: Colors.redAccent)),
              ),
          ],
        ),
      ],
    );
  }

  Future<void> _disconnectLinkedIn() async {
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/linkedin/disconnect'),
      headers: _h,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'LinkedIn disconnected'
            : 'Disconnect failed (${r.statusCode})')));
    _load();
  }

  Future<void> _connectLinkedIn() async {
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/linkedin/connect'),
      headers: _h,
    );
    if (r.statusCode != 200) {
      if (!mounted) return;
      var detail = 'Connect failed (${r.statusCode})';
      try {
        final j = json.decode(r.body);
        if (j is Map && j['detail'] != null) detail = j['detail'].toString();
      } catch (_) {}
      if (r.statusCode == 503) {
        detail =
            'LinkedIn app credentials missing on the server.';
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(detail)));
      return;
    }
    final url = (json.decode(r.body) as Map)['oauth_url']?.toString() ?? '';
    if (url.isNotEmpty) {
      await launchUrl(Uri.parse(url),
          mode: LaunchMode.externalApplication, webOnlyWindowName: '_blank');
    }
  }

  bool get _isMaster => _hub?['supervision']?['is_master'] == true;

  Widget _lengthPicker() {
    final types = (_hub?['flags']?['ENABLE_COACH_NEWSLETTER'] == true) ? 3 : 2;
    final windows = _isMaster ? 2 : 1;
    final drafts = _lengthDays * types * windows;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Campaign length: $_lengthDays days',
            style: const TextStyle(color: _text, fontSize: 13)),
        Slider(
          value: _lengthDays.toDouble(),
          min: 1,
          max: 36,
          divisions: 35,
          activeColor: _gold,
          label: '$_lengthDays',
          onChanged: (v) => setState(() => _lengthDays = v.round()),
        ),
        Text(
          'About $drafts drafts (days × $types types × $windows window${windows == 1 ? '' : 's'}). Unique copy per day. Never auto-publishes.',
          style: const TextStyle(color: _muted, fontSize: 11),
        ),
      ],
    );
  }

  Widget _voice() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _panel(
          'VOICE CAMPAIGN',
          Icons.mic_none,
          [
            const Text(
              'Client vault_sync audio only. Therapy Twilio calls are not used here.',
              style: TextStyle(color: _muted, fontSize: 12),
            ),
            Text('Recordings: ${_hub?['voice_recordings'] ?? 0}',
                style: const TextStyle(color: _text, fontSize: 13)),
            Text(
              _hub?['has_voice_presence'] == true
                  ? 'Spoken presence stored — used in Generate and Rewrite'
                  : 'Spoken presence: record in VIDEO to capture pace and warmth',
              style: const TextStyle(color: _goldDim, fontSize: 12),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _campaignTitleCtrl,
              style: const TextStyle(color: _text, fontSize: 13),
              decoration: const InputDecoration(
                labelText: 'Campaign title',
                labelStyle: TextStyle(color: _muted),
              ),
            ),
            _lengthPicker(),
            const SizedBox(height: 8),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: () => _generateCampaign(audience: 'clients'),
              child: const Text('Generate for clients',
                  style: TextStyle(color: Colors.black)),
            ),
            if (_isMaster) ...[
              const SizedBox(height: 8),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _goldDim),
                onPressed: () =>
                    _generateCampaign(audience: 'assistant_coaches'),
                child: const Text('Generate for assistant coaches',
                    style: TextStyle(color: Colors.black)),
              ),
            ],
            const SizedBox(height: 16),
            _VoiceIngest(token: widget.token),
          ],
        ),
      ],
    );
  }

  Widget _video() {
    final videoOn = _hub?['flags']?['ENABLE_COACH_VIDEO_INGEST'] == true;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _panel(
          'VIDEO INTERVIEW',
          Icons.videocam_outlined,
          [
            const Text(
              'Record in the browser, paste answers, or upload mp4/mov/webm/audio. Little Nate transcribes, captures spoken presence (pace/warmth/pauses), and builds a style profile. Not a therapy call. Meet/Drive ingest is off.',
              style: TextStyle(color: _muted, fontSize: 12),
            ),
            if (!videoOn)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text('ENABLE_COACH_VIDEO_INGEST is off — video blocked; audio still works on VOICE.',
                    style: TextStyle(color: Colors.orangeAccent, fontSize: 12)),
              ),
            const SizedBox(height: 12),
            _VideoIngest(token: widget.token, videoEnabled: videoOn),
          ],
        ),
      ],
    );
  }

  Future<void> _generateCampaign({required String audience}) async {
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/generate'),
      headers: _h,
      body: json.encode({
        'title': _campaignTitleCtrl.text.trim(),
        'length_days': _lengthDays,
        'audience': audience,
      }),
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Queued for review — open CAMPAIGN to approve'
            : 'Generate failed (${r.statusCode})')));
    _load();
  }

  Widget _studio() {
    final studio = Map<String, dynamic>.from(_hub?['studio'] ?? {});
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _panel(
          'STUDIO WEBHOOK SECRET',
          Icons.key,
          [
            Text(
              studio['configured'] == true
                  ? 'Fingerprint ${studio['fingerprint']}. Plaintext is show-once; rotate to replace.'
                  : 'Generate a HMAC secret for Studio intake/engagement hooks. No plaintext recovery.',
              style: const TextStyle(color: _muted, fontSize: 12),
            ),
            const SizedBox(height: 12),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _rotateStudio,
              child: const Text('Rotate secret',
                  style: TextStyle(color: Colors.black)),
            ),
            const SizedBox(height: 16),
            const Text('Studio POST URLs (HMAC required)',
                style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
            const SizedBox(height: 6),
            ...List<String>.from(
                    (_hub?['studio_hooks']?['paths'] as List?) ??
                        ['intake-analysis', 'engagement', 'client-digest'])
                .map((p) {
              final url = '${AppConfig.apiBaseUrl}/api/v1/hooks/$p';
              return Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    Expanded(
                      child: SelectableText(url,
                          style: const TextStyle(color: _text, fontSize: 12)),
                    ),
                    IconButton(
                      icon: const Icon(Icons.copy, color: _gold, size: 16),
                      tooltip: 'Copy URL',
                      onPressed: () {
                        Clipboard.setData(ClipboardData(text: url));
                        ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Copied')));
                      },
                    ),
                  ],
                ),
              );
            }),
            const SizedBox(height: 8),
            const Text(
              'Headers: X-Coach-Id = your hardware_id, X-Studio-Signature = HMAC-SHA256 of the body. '
              'Engagement is idempotent.',
              style: TextStyle(color: _muted, fontSize: 12),
            ),
          ],
        ),
      ],
    );
  }

  Future<void> _rotateStudio() async {
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/studio/rotate-secret'),
      headers: _h,
    );
    if (!mounted) return;
    if (r.statusCode != 200) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Rotate failed (${r.statusCode})')));
      return;
    }
    final j = json.decode(r.body) as Map<String, dynamic>;
    final secret = (j['secret'] ?? '').toString();
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _card,
        title: const Text('Copy now — shown once',
            style: TextStyle(color: _gold)),
        content: SelectableText(secret,
            style: const TextStyle(color: _text, fontSize: 13)),
        actions: [
          TextButton(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: secret));
              Navigator.pop(ctx);
            },
            child: const Text('Copy', style: TextStyle(color: _gold)),
          ),
        ],
      ),
    );
    _load();
  }

  Widget _vault() {
    return _VaultSyncList(token: widget.token);
  }

  Widget _draftsCard() {
    return FutureBuilder<http.Response>(
      future: http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/drafts'),
        headers: _h,
      ),
      builder: (context, snap) {
        var n = 0;
        var rows = <Map<String, dynamic>>[];
        if (snap.hasData && snap.data!.statusCode == 200) {
          final j = json.decode(snap.data!.body) as Map<String, dynamic>;
          rows = List<Map<String, dynamic>>.from(j['drafts'] ?? []);
          n = rows.length;
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _statCard('Drafts waiting', '$n in Gmail / queue'),
            if (rows.isNotEmpty)
              ...rows.take(8).map((d) => Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${d['status']}: ${d['subject'] ?? '(no subject)'} → ${d['to_email'] ?? ''}',
                      style: const TextStyle(color: _text, fontSize: 12),
                    ),
                  )),
          ],
        );
      },
    );
  }

  Widget _morningBriefCard() {
    return FutureBuilder<http.Response>(
      future: http.get(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/morning-brief'),
        headers: _h,
      ),
      builder: (context, snap) {
        if (!snap.hasData || snap.data!.statusCode != 200) {
          return const SizedBox.shrink();
        }
        final j = json.decode(snap.data!.body) as Map<String, dynamic>;
        return _panel(
          'MORNING AUDIO BRIEF',
          Icons.headphones,
          [
            Text((j['script'] ?? '').toString(),
                style: const TextStyle(color: _text, fontSize: 13)),
          ],
        );
      },
    );
  }

  Widget _panel(String title, IconData icon, List<Widget> children) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _goldDim.withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(icon, color: _gold, size: 20),
            const SizedBox(width: 8),
            Text(title,
                style: const TextStyle(
                    color: _gold,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    letterSpacing: 1.1)),
          ]),
          const SizedBox(height: 10),
          ...children,
        ],
      ),
    );
  }
}

class _VaultSyncList extends StatefulWidget {
  final String token;
  const _VaultSyncList({required this.token});

  @override
  State<_VaultSyncList> createState() => _VaultSyncListState();
}

class _VaultSyncListState extends State<_VaultSyncList> {
  List<Map<String, dynamic>> _clients = [];
  bool _loading = true;
  String _query = '';

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/clients'),
      headers: _h,
    );
    if (!mounted) return;
    if (r.statusCode == 200) {
      final j = json.decode(r.body) as Map<String, dynamic>;
      setState(() {
        _clients = List<Map<String, dynamic>>.from(j['clients'] ?? []);
        _loading = false;
      });
    } else {
      setState(() => _loading = false);
    }
  }

  Future<void> _set(String hw, bool on) async {
    await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/clients/$hw/vault-sync'),
      headers: _h,
      body: json.encode({'vault_sync': on}),
    );
    _load();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(
          child: CircularProgressIndicator(color: Color(0xFFC9A962)));
    }
    if (_clients.isEmpty) {
      return const Center(
          child: Text('No assigned clients',
              style: TextStyle(color: Color(0xFF8B7355))));
    }
    final q = _query.trim().toLowerCase();
    final shown = q.isEmpty
        ? _clients
        : _clients.where((c) {
            final blob =
                '${c['name'] ?? ''} ${c['username'] ?? ''} ${c['hardware_id'] ?? ''}'
                    .toLowerCase();
            return blob.contains(q);
          }).toList();
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: TextField(
            style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13),
            decoration: const InputDecoration(
              hintText: 'Search clients',
              hintStyle: TextStyle(color: Color(0xFF8B7355)),
              prefixIcon: Icon(Icons.search, color: Color(0xFFC9A962), size: 18),
            ),
            onChanged: (v) => setState(() => _query = v),
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: shown.length,
            itemBuilder: (context, i) {
              final c = shown[i];
              final on = c['vault_sync'] == true;
              final rel = (c['relationship_class'] ?? 'coaching').toString();
              return SwitchListTile(
                activeColor: const Color(0xFFC9A962),
                title: Text((c['name'] ?? c['username'] ?? '').toString(),
                    style: const TextStyle(color: Color(0xFFE8D5A3))),
                subtitle: Text(
                  on
                      ? 'Vault sync on · $rel — Google may carry client-identifiable content'
                      : 'Vault sync off · $rel — titles redacted, no Gmail/Drive PII',
                  style: const TextStyle(color: Color(0xFF8B7355), fontSize: 12),
                ),
                value: on,
                onChanged: (v) => _set((c['hardware_id'] ?? '').toString(), v),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _VoiceIngest extends StatefulWidget {
  final String token;
  const _VoiceIngest({required this.token});

  @override
  State<_VoiceIngest> createState() => _VoiceIngestState();
}

class _VoiceIngestState extends State<_VoiceIngest> {
  String? _clientHw;
  List<Map<String, dynamic>> _clients = [];
  bool _busy = false;
  bool _recording = false;
  final _recorder = CoachWebRecorder();
  Timer? _tick;
  int _secs = 0;

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _loadClients();
  }

  @override
  void dispose() {
    _tick?.cancel();
    if (_recording) {
      _recorder.stop();
    }
    super.dispose();
  }

  Future<void> _toggleRecord() async {
    if (!CoachWebRecorder.isSupported) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('In-app record is available on web')));
      return;
    }
    if (_clientHw == null || _clientHw!.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Select a vault_sync client')));
      return;
    }
    if (_recording) {
      _tick?.cancel();
      setState(() {
        _recording = false;
        _busy = true;
      });
      try {
        final bytes = await _recorder.stop();
        if (bytes.isEmpty) {
          if (!mounted) return;
          setState(() => _busy = false);
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('No audio captured')));
          return;
        }
        final r = await http.post(
          Uri.parse(
              '${AppConfig.apiBaseUrl}/api/coach/integrations/voice/recordings'),
          headers: _h,
          body: json.encode({
            'client_id': _clientHw,
            'audio_b64': base64Encode(bytes),
            'content_type': _recorder.contentType,
            'media_kind': 'audio',
          }),
        );
        if (!mounted) return;
        setState(() => _busy = false);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(r.statusCode == 200
                ? 'Recording stored (not published)'
                : 'Ingest failed (${r.statusCode})')));
      } catch (e) {
        if (!mounted) return;
        setState(() => _busy = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Record failed: $e')));
      }
      return;
    }
    try {
      await _recorder.start();
      _secs = 0;
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted) return;
        setState(() => _secs += 1);
        if (_secs >= 180) {
          _toggleRecord();
        }
      });
      setState(() => _recording = true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Mic failed: $e')));
    }
  }

  Future<void> _loadClients() async {
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/clients'),
      headers: _h,
    );
    if (!mounted || r.statusCode != 200) return;
    final j = json.decode(r.body) as Map<String, dynamic>;
    final all = List<Map<String, dynamic>>.from(j['clients'] ?? []);
    setState(() {
      _clients = all.where((c) => c['vault_sync'] == true).toList();
    });
  }

  Future<void> _pickAndUpload() async {
    if (_clientHw == null || _clientHw!.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Select a vault_sync client')));
      return;
    }
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['wav', 'mp3', 'm4a', 'ogg', 'webm'],
      withData: true,
    );
    if (picked == null || picked.files.isEmpty) return;
    final bytes = picked.files.first.bytes;
    if (bytes == null || bytes.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not read audio bytes')));
      return;
    }
    if (bytes.length > 15 * 1024 * 1024) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Audio over 15 MB')));
      return;
    }
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/voice/recordings'),
      headers: _h,
      body: json.encode({
        'client_id': _clientHw,
        'audio_b64': base64Encode(bytes),
      }),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    String extra = '';
    if (r.statusCode == 200) {
      try {
        final j = json.decode(r.body) as Map<String, dynamic>;
        if (j['transcribed'] == true) {
          extra = ' · transcribed';
        }
      } catch (_) {}
    }
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Recording stored (not published)$extra'
            : 'Ingest failed (${r.statusCode})')));
  }

  @override
  Widget build(BuildContext context) {
    if (_clients.isEmpty) {
      return const Text(
        'No vault_sync clients. Turn vault sync on in VAULT before ingest.',
        style: TextStyle(color: Color(0xFF8B7355), fontSize: 12),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        DropdownButton<String>(
          value: _clientHw,
          hint: const Text('Vault-sync client',
              style: TextStyle(color: Color(0xFF8B7355))),
          dropdownColor: const Color(0xFF111111),
          isExpanded: true,
          items: _clients
              .map((c) => DropdownMenuItem(
                    value: (c['hardware_id'] ?? '').toString(),
                    child: Text(
                      (c['name'] ?? c['username'] ?? '').toString(),
                      style: const TextStyle(color: Color(0xFFE8D5A3)),
                    ),
                  ))
              .toList(),
          onChanged: (v) => setState(() => _clientHw = v),
        ),
        const SizedBox(height: 8),
        if (CoachWebRecorder.isSupported) ...[
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
                backgroundColor: _recording
                    ? const Color(0xFFEF4444)
                    : const Color(0xFFC9A962)),
            onPressed: _busy ? null : _toggleRecord,
            icon: Icon(_recording ? Icons.stop : Icons.mic,
                color: Colors.black, size: 18),
            label: Text(
                _recording
                    ? 'Stop recording ${_secs}s'
                    : 'Record in browser',
                style: const TextStyle(color: Colors.black)),
          ),
          const SizedBox(height: 8),
        ],
        ElevatedButton.icon(
          style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962)),
          onPressed: _busy ? null : _pickAndUpload,
          icon: const Icon(Icons.upload_file, color: Colors.black, size: 18),
          label: Text(_busy ? 'Uploading…' : 'Upload voice recording',
              style: const TextStyle(color: Colors.black)),
        ),
      ],
    );
  }
}

class _VideoIngest extends StatefulWidget {
  final String token;
  final bool videoEnabled;
  const _VideoIngest({required this.token, required this.videoEnabled});

  @override
  State<_VideoIngest> createState() => _VideoIngestState();
}

class _VideoIngestState extends State<_VideoIngest> {
  bool _busy = false;
  bool _recording = false;
  List<String> _prompts = const [];
  String _preview = '';
  final _answers = TextEditingController();
  final _recorder = CoachWebRecorder();
  Timer? _tick;
  int _secs = 0;

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _loadPrompts();
  }

  @override
  void dispose() {
    _tick?.cancel();
    if (_recording) {
      _recorder.stop();
    }
    _answers.dispose();
    super.dispose();
  }

  Future<void> _toggleRecord() async {
    if (!CoachWebRecorder.isSupported) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('In-app record is available on web')));
      return;
    }
    if (_recording) {
      _tick?.cancel();
      setState(() {
        _recording = false;
        _busy = true;
      });
      try {
        final bytes = await _recorder.stop();
        if (bytes.isEmpty) {
          if (!mounted) return;
          setState(() => _busy = false);
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('No audio captured')));
          return;
        }
        await _post(
          bytes: bytes,
          mediaKind: 'audio',
          contentType: _recorder.contentType,
          transcript: _answers.text.trim(),
        );
      } catch (e) {
        if (!mounted) return;
        setState(() => _busy = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Record failed: $e')));
      }
      return;
    }
    try {
      await _recorder.start();
      _secs = 0;
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted) return;
        setState(() => _secs += 1);
        if (_secs >= 180) {
          _toggleRecord();
        }
      });
      setState(() => _recording = true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Mic failed: $e')));
    }
  }

  Future<void> _loadPrompts() async {
    final r = await http.get(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/voice/interview-prompts'),
      headers: _h,
    );
    if (!mounted || r.statusCode != 200) return;
    final j = json.decode(r.body) as Map<String, dynamic>;
    setState(() {
      _prompts = List<String>.from(j['prompts'] ?? const []);
    });
  }

  Future<void> _post({
    List<int>? bytes,
    String mediaKind = 'audio',
    String contentType = '',
    required String transcript,
  }) async {
    setState(() => _busy = true);
    final body = <String, dynamic>{
      'media_kind': mediaKind,
      'transcript': transcript,
    };
    if (bytes != null && bytes.isNotEmpty) {
      body['media_b64'] = base64Encode(bytes);
      body['content_type'] = contentType;
    }
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/voice/recordings'),
      headers: _h,
      body: json.encode(body),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    String preview = '';
    var presence = false;
    if (r.statusCode == 200) {
      try {
        final j = json.decode(r.body) as Map<String, dynamic>;
        preview = (j['transcript_preview'] ?? '').toString();
        presence = j['biometrics'] == true;
      } catch (_) {}
    }
    setState(() => _preview = preview);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? (preview.isEmpty
                ? 'Interview stored (not published)'
                : (presence
                    ? 'Interview stored · transcribed · presence captured'
                    : 'Interview stored · transcribed'))
            : 'Ingest failed (${r.statusCode})')));
  }

  Future<void> _saveAnswers() async {
    final text = _answers.text.trim();
    if (text.length < 40) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Write at least 40 characters of answers')));
      return;
    }
    await _post(transcript: text, mediaKind: 'audio');
  }

  Future<void> _pickAndUpload() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['mp4', 'mov', 'webm', 'wav', 'mp3', 'm4a'],
      withData: true,
    );
    if (picked == null || picked.files.isEmpty) return;
    final file = picked.files.first;
    final bytes = file.bytes;
    if (bytes == null || bytes.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not read media bytes')));
      return;
    }
    final ext = (file.extension ?? '').toLowerCase();
    final isVideo = const {'mp4', 'mov', 'webm'}.contains(ext);
    if (isVideo && !widget.videoEnabled) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Video ingest is off')));
      return;
    }
    final limit = isVideo ? 40 * 1024 * 1024 : 15 * 1024 * 1024;
    if (bytes.length > limit) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(isVideo
              ? 'Video over 40 MB — paste transcript instead'
              : 'Audio over 15 MB')));
      return;
    }
    final ctype = {
      'mp4': 'video/mp4',
      'mov': 'video/quicktime',
      'webm': 'video/webm',
      'wav': 'audio/wav',
      'mp3': 'audio/mpeg',
      'm4a': 'audio/m4a',
    }[ext] ?? (isVideo ? 'video/mp4' : 'audio/webm');
    await _post(
      bytes: bytes,
      mediaKind: isVideo ? 'video' : 'audio',
      contentType: ctype,
      transcript: _answers.text.trim(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_prompts.isNotEmpty) ...[
          const Text('NATE INTERVIEW',
              style: TextStyle(
                  color: Color(0xFFC9A962), fontSize: 11, letterSpacing: 1)),
          const SizedBox(height: 6),
          ..._prompts.asMap().entries.map((e) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('${e.key + 1}. ${e.value}',
                    style: const TextStyle(
                        color: Color(0xFFE8D5A3), fontSize: 12)),
              )),
          const SizedBox(height: 8),
        ],
        TextField(
          controller: _answers,
          maxLines: 6,
          style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13),
          decoration: const InputDecoration(
            labelText: 'Answers or pasted transcript',
            labelStyle: TextStyle(color: Color(0xFF8B7355)),
          ),
        ),
        const SizedBox(height: 8),
        if (CoachWebRecorder.isSupported) ...[
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
                backgroundColor: _recording
                    ? const Color(0xFFEF4444)
                    : const Color(0xFFC9A962)),
            onPressed: _busy ? null : _toggleRecord,
            icon: Icon(_recording ? Icons.stop : Icons.mic,
                color: Colors.black, size: 18),
            label: Text(
                _recording
                    ? 'Stop interview ${_secs}s'
                    : 'Record interview',
                style: const TextStyle(color: Colors.black)),
          ),
          const SizedBox(height: 8),
        ],
        ElevatedButton.icon(
          style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962)),
          onPressed: _busy ? null : _saveAnswers,
          icon: const Icon(Icons.save_outlined, color: Colors.black, size: 18),
          label: Text(_busy ? 'Saving…' : 'Save interview answers',
              style: const TextStyle(color: Colors.black)),
        ),
        const SizedBox(height: 8),
        ElevatedButton.icon(
          style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF8B7355)),
          onPressed: _busy ? null : _pickAndUpload,
          icon: const Icon(Icons.upload_file, color: Colors.black, size: 18),
          label: Text(_busy ? 'Uploading…' : 'Upload interview file',
              style: const TextStyle(color: Colors.black)),
        ),
        if (_preview.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text(_preview,
                style: const TextStyle(color: Color(0xFF8B7355), fontSize: 12)),
          ),
      ],
    );
  }
}

class _CampaignQueue extends StatefulWidget {
  final String token;
  final bool isMaster;
  const _CampaignQueue({required this.token, this.isMaster = false});

  @override
  State<_CampaignQueue> createState() => _CampaignQueueState();
}

class _CampaignQueueState extends State<_CampaignQueue> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  int? _busyId;
  final _titleCtrl = TextEditingController(text: 'Campaign');
  int _lengthDays = 7;
  static const _gold = Color(0xFFC9A962);
  static const _goldDim = Color(0xFF8B7355);
  static const _text = Color(0xFFE8D5A3);

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns'),
      headers: _h,
    );
    if (!mounted) return;
    setState(() {
      _data = r.statusCode == 200
          ? json.decode(r.body) as Map<String, dynamic>
          : {'error': r.statusCode};
      _loading = false;
    });
  }

  Future<void> _generateWindow(String audience) async {
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/generate'),
      headers: _h,
      body: json.encode({
        'title': _titleCtrl.text.trim(),
        'length_days': _lengthDays,
        'audience': audience,
      }),
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Queued for review'
            : 'Generate failed (${r.statusCode})')));
    _load();
  }

  Future<void> _review(int id, String status) async {
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id/review'),
      headers: _h,
      body: json.encode({'status': status}),
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200 ? status : 'Review failed')));
    _load();
  }

  Future<void> _publish(int id) async {
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id/publish'),
      headers: _h,
    );
    if (!mounted) return;
    var msg = 'Publish failed (${r.statusCode})';
    if (r.statusCode == 200) {
      final j = json.decode(r.body) as Map<String, dynamic>;
      if (j['reason'] == 'connect_linkedin') {
        msg = 'Connect LinkedIn first — item stays approved';
      } else if (j['published'] == true || j['ok'] == true) {
        msg = 'Published';
      } else {
        msg = (j['reason'] ?? 'Not published').toString();
      }
    }
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    _load();
  }

  String _heroUrl(int id) =>
      '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id/hero';

  Widget _heroThumb(int id, Map<String, dynamic> item, {double size = 72}) {
    if ((item['hero_image_url'] ?? '').toString().isEmpty) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 4),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: _AuthHeroImage(
          url: _heroUrl(id),
          token: widget.token,
          height: size,
          width: size,
        ),
      ),
    );
  }

  Future<void> _showPreview(Map<String, dynamic> item) async {
    final id = int.tryParse('${item['id']}') ?? 0;
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: Text((item['title'] ?? 'Preview').toString(),
            style: const TextStyle(color: _gold, fontSize: 16)),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text((item['content_type'] ?? '').toString().toUpperCase(),
                    style: const TextStyle(
                        color: _goldDim, fontSize: 11, letterSpacing: 1.1)),
                _heroThumb(id, item, size: 220),
                const SizedBox(height: 8),
                Text((item['draft_body'] ?? '').toString(),
                    style: const TextStyle(color: _text, fontSize: 13, height: 1.45)),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close', style: TextStyle(color: _gold)),
          ),
        ],
      ),
    );
  }

  Future<void> _showEdit(Map<String, dynamic> item) async {
    final id = int.tryParse('${item['id']}') ?? 0;
    final titleCtrl =
        TextEditingController(text: (item['title'] ?? '').toString());
    final bodyCtrl =
        TextEditingController(text: (item['draft_body'] ?? '').toString());
    final noteCtrl = TextEditingController();
    var rewriting = false;
    final saved = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: const Text('Edit draft',
              style: TextStyle(color: _gold, fontSize: 16)),
          content: SizedBox(
            width: 420,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: titleCtrl,
                    style: const TextStyle(color: _text, fontSize: 13),
                    decoration: const InputDecoration(
                      labelText: 'Title',
                      labelStyle: TextStyle(color: _goldDim),
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: bodyCtrl,
                    maxLines: 8,
                    style: const TextStyle(color: _text, fontSize: 13),
                    decoration: const InputDecoration(
                      labelText: 'Body — edit by hand anytime',
                      labelStyle: TextStyle(color: _goldDim),
                      alignLabelWithHint: true,
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: noteCtrl,
                    maxLines: 4,
                    style: const TextStyle(color: _text, fontSize: 13),
                    decoration: const InputDecoration(
                      labelText: 'Tell Nate what to change',
                      hintText:
                          'e.g. Shorter. Open with presence. End with one question.',
                      labelStyle: TextStyle(color: _goldDim),
                      hintStyle: TextStyle(color: _goldDim, fontSize: 12),
                      alignLabelWithHint: true,
                    ),
                  ),
                  if (rewriting)
                    const Padding(
                      padding: EdgeInsets.only(top: 10),
                      child: LinearProgressIndicator(color: _gold),
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: rewriting ? null : () => Navigator.pop(ctx, false),
              child: const Text('Cancel', style: TextStyle(color: _goldDim)),
            ),
            TextButton(
              onPressed: rewriting
                  ? null
                  : () async {
                      final note = noteCtrl.text.trim();
                      if (note.length < 8) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                            content: Text(
                                'Write at least 8 characters for Nate to rewrite')));
                        return;
                      }
                      setLocal(() => rewriting = true);
                      try {
                        final r = await http
                            .post(
                              Uri.parse(
                                  '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id/rewrite'),
                              headers: _h,
                              body: json.encode({
                                'instruction': note,
                                'title': titleCtrl.text.trim(),
                                'draft_body': bodyCtrl.text,
                              }),
                            )
                            .timeout(const Duration(seconds: 60));
                        if (!ctx.mounted) return;
                        if (r.statusCode == 200) {
                          final j =
                              json.decode(r.body) as Map<String, dynamic>;
                          titleCtrl.text =
                              (j['title'] ?? titleCtrl.text).toString();
                          bodyCtrl.text =
                              (j['draft_body'] ?? bodyCtrl.text).toString();
                          ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text(
                                      'Rewritten in your voice — edit or Save')));
                        } else {
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                              content:
                                  Text('Rewrite failed (${r.statusCode})')));
                        }
                      } catch (e) {
                        if (ctx.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('Rewrite failed: $e')));
                        }
                      } finally {
                        if (ctx.mounted) setLocal(() => rewriting = false);
                      }
                    },
              child: Text(rewriting ? 'Rewriting…' : 'Rewrite in my voice',
                  style: const TextStyle(color: _gold)),
            ),
            TextButton(
              onPressed: rewriting ? null : () => Navigator.pop(ctx, true),
              child: const Text('Save', style: TextStyle(color: _gold)),
            ),
          ],
        ),
      ),
    );
    if (saved != true) {
      titleCtrl.dispose();
      bodyCtrl.dispose();
      noteCtrl.dispose();
      return;
    }
    final r = await http.put(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id'),
      headers: _h,
      body: json.encode({
        'title': titleCtrl.text.trim(),
        'draft_body': bodyCtrl.text,
      }),
    );
    titleCtrl.dispose();
    bodyCtrl.dispose();
    noteCtrl.dispose();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200 ? 'Saved' : 'Save failed (${r.statusCode})')));
    _load();
  }

  Future<void> _showPhoto(Map<String, dynamic> item) async {
    final id = int.tryParse('${item['id']}') ?? 0;
    final promptCtrl = TextEditingController(
        text: (item['hero_image_prompt'] ?? '').toString());
    var generating = false;
    var hasImage = (item['hero_image_url'] ?? '').toString().isNotEmpty;
    var bust = DateTime.now().millisecondsSinceEpoch;
    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: const Text('Campaign photo',
              style: TextStyle(color: _gold, fontSize: 16)),
          content: SizedBox(
            width: 420,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (hasImage)
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: _AuthHeroImage(
                        url: '${_heroUrl(id)}?t=$bust',
                        token: widget.token,
                        height: 180,
                        width: 380,
                      ),
                    )
                  else
                    const Text('No image yet — describe the still, then Generate.',
                        style: TextStyle(color: _goldDim, fontSize: 12)),
                  const SizedBox(height: 10),
                  TextField(
                    controller: promptCtrl,
                    maxLines: 5,
                    style: const TextStyle(color: _text, fontSize: 13),
                    decoration: const InputDecoration(
                      labelText: 'Image descriptor',
                      labelStyle: TextStyle(color: _goldDim),
                      alignLabelWithHint: true,
                    ),
                  ),
                  if (generating)
                    const Padding(
                      padding: EdgeInsets.only(top: 12),
                      child: LinearProgressIndicator(color: _gold),
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: generating ? null : () => Navigator.pop(ctx),
              child: const Text('Close', style: TextStyle(color: _goldDim)),
            ),
            TextButton(
              onPressed: generating
                  ? null
                  : () async {
                      final r = await http.put(
                        Uri.parse(
                            '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id'),
                        headers: _h,
                        body: json.encode(
                            {'hero_image_prompt': promptCtrl.text.trim()}),
                      );
                      if (!ctx.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                          content: Text(r.statusCode == 200
                              ? 'Descriptor saved'
                              : 'Save failed')));
                    },
              child: const Text('Save descriptor',
                  style: TextStyle(color: _gold)),
            ),
            TextButton(
              onPressed: generating
                  ? null
                  : () async {
                      setLocal(() => generating = true);
                      setState(() => _busyId = id);
                      try {
                        final r = await http
                            .post(
                              Uri.parse(
                                  '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/$id/generate-image'),
                              headers: _h,
                              body: json.encode(
                                  {'prompt': promptCtrl.text.trim()}),
                            )
                            .timeout(const Duration(seconds: 90));
                        if (!ctx.mounted) return;
                        if (r.statusCode == 200) {
                          setLocal(() {
                            hasImage = true;
                            bust = DateTime.now().millisecondsSinceEpoch;
                          });
                          ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('Photo ready')));
                        } else {
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                              content: Text(
                                  'Generate failed (${r.statusCode})')));
                        }
                      } catch (e) {
                        if (ctx.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('Generate failed: $e')));
                        }
                      } finally {
                        if (ctx.mounted) setLocal(() => generating = false);
                        if (mounted) setState(() => _busyId = null);
                      }
                    },
              child: const Text('Generate photo',
                  style: TextStyle(color: _gold)),
            ),
          ],
        ),
      ),
    );
    promptCtrl.dispose();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(
          child: CircularProgressIndicator(color: Color(0xFFC9A962)));
    }
    final queue =
        List<Map<String, dynamic>>.from(_data?['review_queue'] ?? []);
    final approved =
        List<Map<String, dynamic>>.from(_data?['approved_unpublished'] ?? []);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: _titleCtrl,
          style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13),
          decoration: const InputDecoration(
            labelText: 'Campaign title',
            labelStyle: TextStyle(color: Color(0xFF8B7355)),
          ),
        ),
        Text('Campaign length: $_lengthDays days',
            style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13)),
        Slider(
          value: _lengthDays.toDouble(),
          min: 1,
          max: 36,
          divisions: 35,
          activeColor: const Color(0xFFC9A962),
          label: '$_lengthDays',
          onChanged: (v) => setState(() => _lengthDays = v.round()),
        ),
        const SizedBox(height: 8),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962)),
          onPressed: () => _generateWindow('clients'),
          child: const Text('Generate for clients',
              style: TextStyle(color: Colors.black)),
        ),
        if (widget.isMaster) ...[
          const SizedBox(height: 8),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF8B7355)),
            onPressed: () => _generateWindow('assistant_coaches'),
            child: const Text('Generate for assistant coaches',
                style: TextStyle(color: Colors.black)),
          ),
        ],
        const SizedBox(height: 16),
        const Text('REVIEW QUEUE',
            style: TextStyle(
                color: Color(0xFFC9A962), letterSpacing: 1.1, fontSize: 12)),
        if (queue.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: Text('Nothing pending review',
                style: TextStyle(color: Color(0xFF8B7355))),
          ),
        ...queue.map((item) => _itemCard(item, review: true)),
        const SizedBox(height: 16),
        const Text('APPROVED — WAITING PUBLISH',
            style: TextStyle(
                color: Color(0xFFC9A962), letterSpacing: 1.1, fontSize: 12)),
        if (approved.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: Text('No approved LinkedIn posts waiting',
                style: TextStyle(color: Color(0xFF8B7355))),
          ),
        ...approved.map((item) => _itemCard(item, review: false)),
      ],
    );
  }

  String _scheduleLabel(Map<String, dynamic> item) {
    final meta = item['generation_meta'];
    String day = '';
    if (meta is Map && meta['day_n'] != null) {
      day = ' · day ${meta['day_n']}';
    }
    final sched = (item['scheduled_at'] ?? '').toString();
    if (sched.isEmpty) return day;
    return '$day · $sched';
  }

  Widget _itemCard(Map<String, dynamic> item, {required bool review}) {
    final id = int.tryParse('${item['id']}') ?? 0;
    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF8B7355).withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text((item['title'] ?? '').toString(),
              style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 14)),
          Text(
              '${item['content_type'] ?? ''}'
              '${item['audience'] != null ? ' · ${item['audience']}' : ''}'
              '${_scheduleLabel(item)}',
              style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11)),
          _heroThumb(id, item),
          if ((item['draft_body'] ?? '').toString().isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text((item['draft_body'] ?? '').toString(),
                  style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 12),
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis),
            ),
          const SizedBox(height: 4),
          Wrap(
            spacing: 0,
            children: [
              TextButton(
                  onPressed: () => _showPreview(item),
                  child: const Text('Preview',
                      style: TextStyle(color: Color(0xFFC9A962)))),
              TextButton(
                  onPressed: () => _showEdit(item),
                  child: const Text('Edit',
                      style: TextStyle(color: Color(0xFFC9A962)))),
              TextButton(
                  onPressed: _busyId == id ? null : () => _showPhoto(item),
                  child: Text(_busyId == id ? 'Generating…' : 'Photo',
                      style: const TextStyle(color: Color(0xFFC9A962)))),
            ],
          ),
          if (review)
            Row(children: [
              TextButton(
                  onPressed: () => _review(id, 'approved'),
                  child: const Text('Approve',
                      style: TextStyle(color: Color(0xFFC9A962)))),
              TextButton(
                  onPressed: () => _review(id, 'rejected'),
                  child: const Text('Reject',
                      style: TextStyle(color: Colors.redAccent))),
            ])
          else if ((item['content_type'] ?? '') == 'linkedin_post')
            TextButton(
                onPressed: () => _publish(id),
                child: const Text('Publish to LinkedIn',
                    style: TextStyle(color: Color(0xFFC9A962)))),
        ],
      ),
    );
  }
}

class _AuthHeroImage extends StatelessWidget {
  final String url;
  final String token;
  final double height;
  final double width;

  const _AuthHeroImage({
    required this.url,
    required this.token,
    required this.height,
    required this.width,
  });

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<http.Response>(
      future: http.get(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer $token'},
      ),
      builder: (context, snap) {
        if (!snap.hasData || snap.data!.statusCode != 200) {
          return SizedBox(height: height, width: width);
        }
        return Image.memory(
          snap.data!.bodyBytes,
          height: height,
          width: width,
          fit: BoxFit.cover,
        );
      },
    );
  }
}

class _RemoteListCard extends StatelessWidget {
  final String token;
  final String title;
  final IconData icon;
  final String path;
  final String keyName;
  final String Function(Map<String, dynamic>) labelOf;

  const _RemoteListCard({
    required this.token,
    required this.title,
    required this.icon,
    required this.path,
    required this.keyName,
    required this.labelOf,
  });

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<http.Response>(
      future: http.get(
        Uri.parse('${AppConfig.apiBaseUrl}$path'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
      ),
      builder: (context, snap) {
        var lines = <String>[];
        if (snap.hasData && snap.data!.statusCode == 200) {
          final j = json.decode(snap.data!.body) as Map<String, dynamic>;
          final list = List<Map<String, dynamic>>.from(j[keyName] ?? []);
          lines = list.map(labelOf).where((s) => s.isNotEmpty).toList();
        } else if (snap.hasData && snap.data!.statusCode == 403) {
          lines = ['Temporarily unavailable'];
        }
        return Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFF111111),
            borderRadius: BorderRadius.circular(12),
            border:
                Border.all(color: const Color(0xFF8B7355).withOpacity(0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(icon, color: const Color(0xFFC9A962), size: 18),
                const SizedBox(width: 8),
                Text(title,
                    style: const TextStyle(
                        color: Color(0xFFC9A962),
                        fontSize: 12,
                        letterSpacing: 1.1)),
              ]),
              const SizedBox(height: 8),
              if (lines.isEmpty)
                const Text('None',
                    style: TextStyle(color: Color(0xFF8B7355), fontSize: 12))
              else
                ...lines.take(8).map((t) => Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(t,
                          style: const TextStyle(
                              color: Color(0xFFE8D5A3), fontSize: 13)),
                    )),
            ],
          ),
        );
      },
    );
  }
}

class _CreateTaskCard extends StatefulWidget {
  final String token;
  const _CreateTaskCard({required this.token});

  @override
  State<_CreateTaskCard> createState() => _CreateTaskCardState();
}

class _CreateTaskCardState extends State<_CreateTaskCard> {
  List<Map<String, dynamic>> _clients = [];
  String? _clientHw;
  final _title = TextEditingController();
  bool _busy = false;

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/clients'),
      headers: _h,
    );
    if (!mounted || r.statusCode != 200) return;
    final j = json.decode(r.body) as Map<String, dynamic>;
    setState(() {
      _clients = List<Map<String, dynamic>>.from(j['clients'] ?? []);
    });
  }

  Future<void> _create() async {
    if (_clientHw == null || _title.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Pick a client and enter a title')));
      return;
    }
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/coach/integrations/tasks'),
      headers: _h,
      body: json.encode({'client_id': _clientHw, 'title': _title.text.trim()}),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Task created'
            : 'Create failed (${r.statusCode})')));
    if (r.statusCode == 200) _title.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF8B7355).withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(children: [
            Icon(Icons.add_task, color: Color(0xFFC9A962), size: 18),
            SizedBox(width: 8),
            Text('CREATE TASK',
                style: TextStyle(
                    color: Color(0xFFC9A962), fontSize: 12, letterSpacing: 1.1)),
          ]),
          const SizedBox(height: 8),
          DropdownButton<String>(
            value: _clientHw,
            hint: const Text('Client',
                style: TextStyle(color: Color(0xFF8B7355))),
            dropdownColor: const Color(0xFF111111),
            isExpanded: true,
            items: _clients
                .map((c) => DropdownMenuItem(
                      value: (c['hardware_id'] ?? '').toString(),
                      child: Text(
                        (c['name'] ?? c['username'] ?? '').toString(),
                        style: const TextStyle(color: Color(0xFFE8D5A3)),
                      ),
                    ))
                .toList(),
            onChanged: (v) => setState(() => _clientHw = v),
          ),
          TextField(
            controller: _title,
            style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13),
            decoration: const InputDecoration(
              hintText: 'Task title',
              hintStyle: TextStyle(color: Color(0xFF8B7355)),
            ),
          ),
          const SizedBox(height: 8),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFC9A962)),
            onPressed: _busy ? null : _create,
            child: Text(_busy ? 'Saving…' : 'Create task',
                style: const TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }
}
