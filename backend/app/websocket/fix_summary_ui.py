#!/usr/bin/env python3
import os

FLUTTER = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

with open(FLUTTER, 'r') as f:
    content = f.read()

# Add the summary overlay widget
widget = '''
  Widget _buildSessionSummaryOverlay() {
    if (_generatingSummary) {
      return Container(
        color: Colors.black87,
        child: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(color: Colors.cyan),
              SizedBox(height: 24),
              Text('Generating session summary...', style: TextStyle(color: Colors.white, fontSize: 18)),
              Text('💙', style: TextStyle(fontSize: 32)),
            ],
          ),
        ),
      );
    }
    if (!_showSessionSummary || _sessionSummary == null) return const SizedBox.shrink();
    
    final summary = _sessionSummary!;
    final stats = _sessionStats ?? {};
    final insights = summary['your_insights'] as Map<String, namic>? ?? {};
    
    return Container(
      color: Colors.black.withOpacity(0.95),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(children: [
                Icon(Icons.summarize, color: Colors.cyan, size: 32),
                SizedBox(width: 12),
                Text('Session Summary', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white)),
              ]),
              const SizedBox(height: 16),
              // Stats
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: const Color(0xFF1a1a2e), borderRadius: BorderRadius.circular(12)),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    Column(children: [Text('${stats['duration_minutes'] ?? 0}m', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)), const Text('Duration', style: TextStyle(color: Colors.grey, fontSize: 12))]),
                    Column(children: [Text('${stats['total_messages'] ?? 0}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)), const Text('Messages', style: TextStyle(color: Colors.grey, fontSize: 12))]),
                    Column(children: [Text('${summary['overall_progress'] ?? 5}/10', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)), const Text('Progress', style: TextStyle(color: Colors.grey, fontSize: 12))]),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              // Conflicts
              if ((summary['key_conflicts'] as List?)?.isNotEmpty ?? false) ...[
                const Row(children: [Icon(Icons.warning_amber, color: Colors.orange, size: 20), SizedBox(width: 8), Text('Key Conflicts', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
                const SizedBox(height: 8),
                ...((summary['key_conflicts'] as List?) ?? []).map((c) => Padding(padding: const EdgeInsets.only(left: 28, bottom: 4), child: Text('• $c', style: const TextStyle(lor: Colors.grey)))),
                const SizedBox(height: 16),
              ],
              // Agreement
              if ((summary['points_of_agreement'] as List?)?.isNotEmpty ?? false) ...[
                const Row(children: [Icon(Icons.handshake, color: Colors.green, size: 20), SizedBox(width: 8), Text('Points of Agreement', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
                const SizedBox(height: 8),
                ...((summary['points_of_agreement'] as List?) ?? []).map((c) => Padding(padding: const EdgeInsets.only(left: 28, bottom: 4), child: Text('• $c', style: const TextStyle(color: Colors.grey)))),
                const SizedBox(height: 16),
              ],
              // Your Insights
              if (insights.isNotEmpty) ...[
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(colors: [lors.cyan.withOpacity(0.2), Colors.blue.withOpacity(0.1)]),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.cyan.withOpacity(0.5)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(children: [Icon(Icons.person, color: Colors.cyan), SizedBox(width: 8), Text('Your Personal Insights', style: TextStyle(color: Colors.cyan, fontWeight: FontWeight.bold, fontSize: 16))]),
                      const SizedBox(height: 12),
                      if (insights['patterns_observed'] != null) _insightRow('Patterns', insights['patterns_observed']),
                      if (insights['growth_areas'] != null) _insightRow('Growth Areas', insights['growth_areas']),
                      if (insights['strengths_shown'] != null) _insightRow('Strengths', insights['strengths_shown']),
                      if (insights['suggested_focus'] != null) _insightRow('Focus', insights['suggested_focus']),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
              ],
              // Next Steps
              if ((summary['next_steps'] as List?)?.isNotEmpty ?? false) ...[
                const Row(children: [Icon(Icons.arrow_forward, color: Colors.blue, size: 20), SizedBox(width: 8), Text('Next Steps', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
                const SizedBox(height: 8),
                ...((summary['next_steps'] as List?) ?? []).map((c) => Padding(padding: const EdgeInsets.only(left: 28, bottom: 4), child: Text('• $c', style: const TextStyle(color: Colors.grey)))),
              ],
              const SizedBox(height: 24),
              SizedBox(
                widt double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    setState(() { _showSessionSummary = false; _sessionSummary = null; });
                    Navigator.of(context).pop();
                  },
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.cyan, padding: const EdgeInsets.symmetric(vertical: 16)),
                  child: const Text('Close & Exit', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
  
  Widget _insightRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: Colors.cyan, fontSize: 12, fontWeight: FontWeight.bold)),
          Text(value, style: const TextStyle(color: Colors.white)),
        ],
      ),
    );
  }

'''

# Add widget before _exitSanctuary
if "_buildSessionSummaryOverlay" not in content:
    marker = "void _exitSanctuary("
    if marker in content:
        idx = content.find(marker)
        content = content[:idx] + widget + "  " + content[idx:]
        print("Added _buildSessionSummaryOverlay widget")

# Add to Stack
if "_buildSessionSummaryOverlay()," not in content:
    old = "_buildEntryQuestionsOverlay(),"
    new = "_buildEntryQuestionsOverlay(),\n            _buildSessionSummaryOverlay(),"
    if old in content:
        content = content.replace(old, new)
        print("Added to Stack")

with open(FLUTTER, 'w') as f:
    f.write(content)

print("Done! Hot restart Flutter.")
