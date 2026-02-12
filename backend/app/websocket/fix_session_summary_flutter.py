#!/usr/bin/env python3
"""
Flutter Fix: Sanctuary Session Summary UI
=========================================
Adds session summary display when sanctuary ends.

Run from anywhere
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Flutter Fix: Session Summary UI")
    print("=" * 60)
    
    if not os.path.exists(FILE_PATH):
        print(f"❌ File not found: {FILE_PATH}")
        return False
    
    # Backup
    backup_path = FILE_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FILE_PATH, backup_path)
    print(f"📦 Backup: {backup_path}")
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # =========================================================================
    # FIX 1: Add state variables for session summary
    # =========================================================================
    
    if "_showSessionSummary" not in content:
        # Find a good place to add state variables
        old_state = "  bool _sanctuaryPaused = false;"
        new_state = """  bool _sanctuaryPaused = false;
  
  // Session Summary state
  bool _showSessionSummary = false;
  bool _generatingSummary = false;
  Map<String, dynamic>? _sessionSummary;
  Map<String, dynamic>? _sessionStats;"""
        
        if old_state in content:
            content = content.replace(old_state, new_state)
            fixes_applied.append("1. Added session summary state variables")
        else:
            # Try alternate location
            alt_state = "bool _inPrivateCoaching = false;"
            if alt_state in content:
                content = content.replace(alt_state, alt_state + """
  
  // Session Summary state
  bool _showSessionSummary = false;
  bool _generatingSummary = false;
  Map<String, dynamic>? _sessionSummary;
  Map<String, dynamic>? _sessionStats;""")
                fixes_applied.append("1. Added session summary state variables")
    
    # =========================================================================
    # FIX 2: Add handlers for summary messages
    # =========================================================================
    
    summary_handlers = '''
      // SESSION SUMMARY
      case 'sanctuary_generating_summary':
        print('>>> SANCTUARY: Generating summary...');
        setState(() {
          _generatingSummary = true;
        });
        break;
        
      case 'sanctuary_summary':
        print('>>> SANCTUARY: Summary received');
        setState(() {
          _generatingSummary = false;
          _showSessionSummary = true;
          _sessionSummary = data['summary'] as Map<String, dynamic>?;
          _sessionStats = data['session_stats'] as Map<String, dynamic>?;
        });
        break;
'''
    
    if "case 'sanctuary_generating_summary':" not in content:
        # Find insertion point - after sanctuary_resumed or another handler
        insert_marker = "case 'sanctuary_resumed':"
        if insert_marker in content:
            idx = content.find(insert_marker)
            # Find the break after this case
            break_idx = content.find("break;", idx)
            if break_idx > 0:
                insert_point = break_idx + len("break;")
                content = content[:insert_point] + summary_handlers + content[insert_point:]
                fixes_applied.append("2. Added summary message handlers")
    
    # =========================================================================
    # FIX 3: Add summary widget methods
    # =========================================================================
    
    summary_methods = '''
  // ==========================================================================
  // SESSION SUMMARY UI
  // ==========================================================================
  
  void _requestSessionSummary() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: const Text('End Session?', style: TextStyle(color: Colors.white)),
        content: const Text(
          'This will generate a summary of your conversation with insights for each family member.\\n\\nAll members will receive the summary.',
          style: TextStyle(color: Colors.grey),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              _sendSanctuaryMessage({
                'type': 'sanctuary_end_session',
                'sanctuary_id': _sanctuaryId,
              });
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.cyan),
            child: const Text('End & Get Summary'),
          ),
        ],
      ),
    );
  }
  
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
              Text(
                'Little Nate is preparing your\\nsession summary...',
                style: TextStyle(color: Colors.white, fontSize: 18),
                textAlign: TextAlign.center,
              ),
              SizedBox(height: 8),
              Text('💙', style: TextStyle(fontSize: 32)),
            ],
          ),
        ),
      );
    }
    
    if (!_showSessionSummary || _sessionSummary == null) {
      return const SizedBox.shrink();
    }
    
    final summary = _sessionSummary!;
    final stats = _sessionStats ?? {};
    
    return Container(
      color: Colors.black.withOpacity(0.95),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              const Row(
                children: [
                  Icon(Icons.summarize, color: Colors.cyan, size: 32),
                  SizedBox(width: 12),
                  Text(
                    'Session Summary',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              const Text(
                'Take time to reflect on these insights. 💙',
                style: TextStyle(color: Colors.grey),
              ),
              
              // Stats bar
              Container(
                margin: const EdgeInsets.symmetric(vertical: 16),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF1a1a2e),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _summaryStatItem('Duration', '${stats['duration_minutes'] ?? 0} min'),
                    _summaryStatItem('Messages', '${stats['total_messages'] ?? 0}'),
                    _summaryStatItem('Coaching', '${stats['coaching_sessions'] ?? 0}'),
                    _summaryStatItem('Progress', '${summary['overall_progress'] ?? 5}/10'),
                  ],
                ),
              ),
              
              // Progress bar
              _buildSummaryProgressBar(summary['overall_progress'] ?? 5),
              
              const SizedBox(height: 24),
              
              // Key Conflicts
              _buildSummarySection(
                'Key Conflicts Identified',
                Icons.warning_amber_rounded,
                Colors.orange,
                (summary['key_conflicts'] as List<dynamic>?) ?? [],
              ),
              
              // Points of Agreement
              _buildSummarySection(
                'Points of Agreement',
                Icons.handshake,
                Colors.green,
                (summary['points_of_agreement'] as List<dynamic>?) ?? [],
              ),
              
              // Healing Moments
              _buildSummarySection(
                'Healing Moments',
                Icons.favorite,
                Colors.pink,
                (summary['corrective_experiences'] as List<dynamic>?) ?? [],
              ),
              
              // Personal Insights
              if (summary['your_insights'] != null) ...[
                const SizedBox(height: 24),
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [Colors.cyan.withOpacity(0.2), Colors.blue.withOpacity(0.1)],
                    ),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.cyan.withOpacity(0.5)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.person, color: Colors.cyan),
                          SizedBox(width: 8),
                          Text(
                            'Your Personal Insights',
                            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.cyan),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      _buildSummaryInsightCard('Patterns Observed', summary['your_insights']['patterns_observed']),
                      _buildSummaryInsightCard('Areas for Growth', summary['your_insights']['growth_areas']),
                      _buildSummaryInsightCard('Strengths Shown', summary['your_insights']['strengths_shown']),
                      _buildSummaryInsightCard('Focus Moving Forward', summary['your_insights']['suggested_focus']),
                    ],
                  ),
                ),
              ],
              
              // Next Steps
              _buildSummarySection(
                'Recommended Next Steps',
                Icons.arrow_forward,
                Colors.blue,
                (summary['next_steps'] as List<dynamic>?) ?? [],
              ),
              
              const SizedBox(height: 32),
              
              // Close button
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _closeSummaryAndExit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.cyan,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: const Text('Close Session', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
  
  Widget _summaryStatItem(String label, String value) {
    return Column(
      children: [
        Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)),
        Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
      ],
    );
  }
  
  Widget _buildSummaryProgressBar(int progress) {
    Color progressColor;
    String progressLabel;
    
    if (progress <= 3) {
      progressColor = Colors.red;
      progressLabel = 'Needs attention';
    } else if (progress <= 5) {
      progressColor = Colors.orange;
      progressLabel = 'Some progress';
    } else if (progress <= 7) {
      progressColor = Colors.yellow;
      progressLabel = 'Good progress';
    } else {
      progressColor = Colors.green;
      progressLabel = 'Excellent progress';
    }
    
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text('Session Progress', style: TextStyle(color: Colors.white)),
            Text(progressLabel, style: TextStyle(color: progressColor)),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: progress / 10,
            backgroundColor: Colors.grey[800],
            valueColor: AlwaysStoppedAnimation<Color>(progressColor),
            minHeight: 8,
          ),
        ),
      ],
    );
  }
  
  Widget _buildSummarySection(String title, IconData icon, Color color, List<dynamic> items) {
    if (items.isEmpty) return const SizedBox.shrink();
    
    return Padding(
      padding: const EdgeInsets.only(top: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 20),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white)),
            ],
          ),
          const SizedBox(height: 12),
          ...items.map((item) => Padding(
            padding: const EdgeInsets.only(left: 28, bottom: 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('• ', style: TextStyle(color: color)),
                Expanded(child: Text(item.toString(), style: TextStyle(color: Colors.grey[300]))),
              ],
            ),
          )).toList(),
        ],
      ),
    );
  }
  
  Widget _buildSummaryInsightCard(String title, dynamic content) {
    if (content == null || content.toString().isEmpty) return const SizedBox.shrink();
    
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.black26,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: Colors.cyan, fontWeight: FontWeight.bold, fontSize: 13)),
          const SizedBox(height: 4),
          Text(content.toString(), style: const TextStyle(color: Colors.white)),
        ],
      ),
    );
  }
  
  void _closeSummaryAndExit() {
    setState(() {
      _showSessionSummary = false;
      _generatingSummary = false;
      _sessionSummary = null;
      _sessionStats = null;
      _sanctuaryId = null;
      _messages = [];
      _members = [];
    });
    // Navigate back
    if (Navigator.canPop(context)) {
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
  }

'''
    
    if "_buildSessionSummaryOverlay" not in content:
        # Find insertion point - before _showError or at end of class methods
        insert_before = "  void _showError("
        if insert_before in content:
            idx = content.find(insert_before)
            content = content[:idx] + summary_methods + content[idx:]
            fixes_applied.append("3. Added session summary widget methods")
        else:
            # Try alternate insertion point
            alt_insert = "  void _exitSanctuary("
            if alt_insert in content:
                idx = content.find(alt_insert)
                content = content[:idx] + summary_methods + content[idx:]
                fixes_applied.append("3. Added session summary widget methods")
    
    # =========================================================================
    # FIX 4: Add summary overlay to build method Stack
    # =========================================================================
    
    # Look for the Stack children in sanctuary screen
    if "_buildSessionSummaryOverlay()," not in content:
        # Try to find where overlays are added
        old_overlay = "_buildPausedOverlay(),"
        new_overlay = "_buildPausedOverlay(),\n            _buildSessionSummaryOverlay(),"
        
        if old_overlay in content:
            content = content.replace(old_overlay, new_overlay)
            fixes_applied.append("4. Added session summary overlay to Stack")
    
    # =========================================================================
    # WRITE CHANGES
    # =========================================================================
    
    if fixes_applied:
        with open(FILE_PATH, 'w') as f:
            f.write(content)
        
        print("")
        print("✅ FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"   • {fix}")
        
        print("")
        print("SESSION SUMMARY UI FEATURES:")
        print("  • Loading state while AI generates")
        print("  • Stats: duration, messages, coaching, progress")
        print("  • Progress bar with color coding")
        print("  • Sections: Conflicts, Agreement, Healing")
        print("  • Personal insights card")
        print("  • Next steps recommendations")
        print("")
        print("MANUAL STEP NEEDED:")
        print("  Add 'End Session' to sanctuary menu if not present")
        print("")
        print("NEXT: Hot restart Flutter")
    else:
        print("⚠️  No fixes applied - check patterns manually")
    
    return True

if __name__ == "__main__":
    apply_fixes()
