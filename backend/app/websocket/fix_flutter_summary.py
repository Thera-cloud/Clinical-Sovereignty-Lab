#!/usr/bin/env python3
import os

FLUTTER = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

with open(FLUTTER, 'r') as f:
    content = f.read()

handlers = '''
      case 'sanctuary_generating_summary':
        print('>>> SANCTUARY: Generating summary...');
        setState(() {
          _generatingSummary = true;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Generating session summary... 💙'), backgroundColor: Colors.blue),
        );
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

# Find insertion point - after sanctuary_resumed
marker = "case 'sanctuary_resumed':"
if marker in content and "cas'sanctuary_generating_summary':" not in content:
    idx = content.find(marker)
    break_idx = content.find("break;", idx)
    if break_idx > 0:
        content = content[:break_idx + 6] + handlers + content[break_idx + 6:]
        print("Added summary handlers")

# Check if state variables exist
if "_showSessionSummary" not in content:
    old = "bool _sanctuaryPaused = false;"
    new = """bool _sanctuaryPaused = false;
  bool _showSessionSummary = false;
  bool _generatingSummary = false;
  Map<String, dynamic>? _sessionSummary;
  Map<String, dynamic>? _sessionStats;"""
    content = content.replace(old, new)
    print("Added state variables")

with open(FLUTTER, 'w') as f:
    f.write(content)

print("Done! Hot restart Flutter.")
