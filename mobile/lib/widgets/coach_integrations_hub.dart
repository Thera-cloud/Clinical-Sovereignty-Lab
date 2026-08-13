// Coach Command Integrations hub — Workspace, LinkedIn, Voice, Studio, Vault.
import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';
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
    _tabs = TabController(length: 7, vsync: this);
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
                    _CampaignQueue(token: widget.token),
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
        Text(
          'Set up Google Workspace, LinkedIn, voice campaigns, Studio HMAC, '
          'Chat webhook, and per-client vault sync here. Workspace Connect stays '
          'hidden until Google verification.',
          style: const TextStyle(color: _muted, fontSize: 12),
        ),
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
    final flags = Map<String, dynamic>.from(_hub?['flags'] ?? {});
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (flags['ENABLE_COACH_TASKS'] == true)
          _RemoteListCard(
            token: widget.token,
            title: 'OPEN TASKS',
            icon: Icons.checklist,
            path: '/api/workspace/google/tasks',
            keyName: 'tasks',
            labelOf: (m) => (m['title'] ?? '').toString(),
          ),
        if (flags['ENABLE_PRACTICE_LIBRARIES'] == true) ...[
          const SizedBox(height: 12),
          _RemoteListCard(
            token: widget.token,
            title: 'PRACTICE LIBRARY',
            icon: Icons.menu_book_outlined,
            path: '/api/workspace/google/libraries',
            keyName: 'templates',
            labelOf: (m) => (m['title'] ?? m['name'] ?? '').toString(),
          ),
        ],
        const SizedBox(height: 12),
        _RemoteListCard(
          token: widget.token,
          title: 'CREDENTIALS',
          icon: Icons.badge_outlined,
          path: '/api/workspace/google/credentials',
          keyName: 'credentials',
          labelOf: (m) => (m['label'] ?? m['name'] ?? m['credential_type'] ?? '').toString(),
        ),
        if (flags['ENABLE_SUPERVISION_VIEW'] == true)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: Text(
              'Supervision roster stays on the ASSISTANTS tab (coach_hierarchy).',
              style: TextStyle(color: _muted, fontSize: 12),
            ),
          ),
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
    final visible = li['connect_visible'] == true;
    final connected = li['connected'] == true;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _panel(
          'COACH LINKEDIN',
          Icons.work_outline,
          [
            Text(
              connected
                  ? 'Connected${li['person_urn'] != null && li['person_urn'].toString().isNotEmpty ? ': ${li['person_urn']}' : ''}'
                  : visible
                      ? 'Campaigns publish with your LinkedIn token. Nate’s SkyEye page is never used.'
                      : 'Temporarily unavailable until ENABLE_COACH_LINKEDIN is on.',
              style: const TextStyle(color: _muted, fontSize: 12),
            ),
            const SizedBox(height: 12),
            if (visible && !connected)
              ElevatedButton.icon(
                style: ElevatedButton.styleFrom(backgroundColor: _gold),
                icon: const Icon(Icons.link, color: Colors.black, size: 18),
                label: const Text('Connect LinkedIn',
                    style: TextStyle(color: Colors.black)),
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
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Connect failed (${r.statusCode})')));
      return;
    }
    final url = (json.decode(r.body) as Map)['oauth_url']?.toString() ?? '';
    if (url.isNotEmpty) {
      await launchUrl(Uri.parse(url),
          mode: LaunchMode.externalApplication, webOnlyWindowName: '_blank');
    }
  }

  Widget _voice() {
    final flags = Map<String, dynamic>.from(_hub?['flags'] ?? {});
    final on = flags['ENABLE_VOICE_CAMPAIGN'] == true;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _panel(
          'VOICE CAMPAIGN',
          Icons.mic_none,
          [
            Text(
              on
                  ? 'Record (vault_sync clients only) then generate review-queue copy. Never auto-publishes.'
                  : 'Temporarily unavailable until ENABLE_VOICE_CAMPAIGN is on.',
              style: const TextStyle(color: _muted, fontSize: 12),
            ),
            Text('Recordings: ${_hub?['voice_recordings'] ?? 0}',
                style: const TextStyle(color: _text, fontSize: 13)),
            if (on) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _campaignTitleCtrl,
                style: const TextStyle(color: _text, fontSize: 13),
                decoration: const InputDecoration(
                  labelText: 'Campaign title',
                  labelStyle: TextStyle(color: _muted),
                ),
              ),
              const SizedBox(height: 8),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _gold),
                onPressed: () async {
                  final r = await http.post(
                    Uri.parse(
                        '${AppConfig.apiBaseUrl}/api/coach/integrations/campaigns/generate'),
                    headers: _h,
                    body: json.encode(
                        {'title': _campaignTitleCtrl.text.trim(), 'day_n': 0}),
                  );
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                      content: Text(r.statusCode == 200
                          ? 'Queued for review'
                          : 'Generate failed (${r.statusCode})')));
                  _load();
                },
                child: const Text('Generate review queue',
                    style: TextStyle(color: Colors.black)),
              ),
              const SizedBox(height: 16),
              const Text(
                'Voice ingest requires vault_sync on the selected client. '
                'Therapy Twilio calls are not used here.',
                style: TextStyle(color: _muted, fontSize: 12),
              ),
              const SizedBox(height: 8),
              _VoiceIngest(token: widget.token),
            ],
          ],
        ),
      ],
    );
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
                .map((p) => SelectableText(
                      '${AppConfig.apiBaseUrl}/api/v1/hooks/$p',
                      style: const TextStyle(color: _text, fontSize: 12),
                    )),
            const SizedBox(height: 8),
            const Text(
              'Headers: X-Coach-Id = your hardware_id, X-Studio-Signature = HMAC-SHA256 of the body. '
              'Flag ENABLE_STUDIO_WEBHOOKS must be on. Engagement is idempotent.',
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
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _clients.length,
      itemBuilder: (context, i) {
        final c = _clients[i];
        final on = c['vault_sync'] == true;
        return SwitchListTile(
          activeColor: const Color(0xFFC9A962),
          title: Text((c['name'] ?? c['username'] ?? '').toString(),
              style: const TextStyle(color: Color(0xFFE8D5A3))),
          subtitle: Text(
            on
                ? 'Vault sync on — Google may carry client-identifiable content'
                : 'Vault sync off — titles redacted, no Gmail/Drive PII',
            style: const TextStyle(color: Color(0xFF8B7355), fontSize: 12),
          ),
          value: on,
          onChanged: (v) => _set((c['hardware_id'] ?? '').toString(), v),
        );
      },
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

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _loadClients();
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
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Recording stored (not published)'
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

class _CampaignQueue extends StatefulWidget {
  final String token;
  const _CampaignQueue({required this.token});

  @override
  State<_CampaignQueue> createState() => _CampaignQueueState();
}

class _CampaignQueueState extends State<_CampaignQueue> {
  Map<String, dynamic>? _data;
  bool _loading = true;

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
          Text((item['content_type'] ?? '').toString(),
              style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11)),
          if ((item['draft_body'] ?? '').toString().isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text((item['draft_body'] ?? '').toString(),
                  style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 12),
                  maxLines: 6,
                  overflow: TextOverflow.ellipsis),
            ),
          const SizedBox(height: 8),
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
