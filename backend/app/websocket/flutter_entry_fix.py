#!/usr/bin/env python3
import os

FLUTTER = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def main():
    print("Adding Flutter entry questions UI...")
    
    if not os.path.exists(FLUTTER):
        print(f"ERROR: {FLUTTER} not found")
        return
    
    with open(FLUTTER, 'r') as f:
        content = f.read()
    
    # 1. Add state variables
    if "_showEntryQuestions" not in content:
        old = "  bool _sanctuaryPaused = false;"
        new = """  bool _sanctuaryPaused = false;
  bool _showEntryQuestions = false;
  List<Map<String, dynamic>> _entryQuestions = [];
  Map<String, dynamic> _entryResponses = {};
  int _feelingScale = 5;"""
        if old in content:
            content = content.replace(old, new)
            print("Added state variables")
    
    # 2. Add message handlers
    handlers = '''
      case 'sanctuary_entry_questions':
        print('>>> SANCTUARY: Entry questions received');
        setState(() {
          _showEntryQuestions = true;
          _entryQuestions = (data['questions'] as List<dynamic>?)?.map((q) => Map<String, dynamic>.from(q as Map)).toList() ?? [];
          _entryResponses = {};
          _feelingScale = 5;
        });
        break;
      case 'sanctuary_entry_complete':
        print('>>> SANCTUARY: Entry complete');
        break;
      case 'sanctuary_entry_ready':
        print('>>> SANCTUARY: Entry ready');
        setState(() {
          _showEntryQuestions = false;
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        if (data['messages'] != null) {
          setState(() { _messages = (data['messages'] as List).map((m) => Map<String, dynamic>.from(m)).toList(); });
        }
        _addSystemMessage('Welcome to the sanctuary!');
        break;
'''
    
    if "case 'sanctuary_entry_questions':" not in content:
        marker = "case 'sanctuary_resumed':"
        if marker in content:
            idx = content.find(marker)
            break_idx = content.find("break;", idx)
            if break_idx > 0:
                content = content[:break_idx+6] + handlers + content[break_idx+6:]
                print("Added message handlers")
    
    # 3. Add overlay to Stack
    if "_buildEntryQuestionsOverlay()," not in content:
        old_stack = "_buildPausedOverlay(),"
        new_stack = "_buildPausedOverlay(),\n            _buildEntryQuestionsOverlay(),"
        if old_stack in content:
            content = content.replace(old_stack, new_stack)
            print("Added overlay to Stack")
    
    # 4. Add widget method
    widget = '''
  Widget _buildEntryQuestionsOverlay() {
    if (!_showEntryQuestions) return const SizedBox.shrink();
    return Container(
      color: Colors.black.withOpacity(0.95),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Icon(Icons.favorite, color: Colors.cyan, size: 48),
              const SizedBox(height: 16),
              const Text('Before We Begin', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white)),
              const Text('Help Little Nate understand where you are', style: TextStyle(color: Colors.grey)),
              const SizedBox(height: 24),
              ..._entryQuestions.map((q) {
                final id = q['id'] as String;
                final type = q['type'] as String;
                return Container(
                  margin: const EdgeInsets.only(bottom: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(q['question'] as String, style: const TextStyle(color: Colors.white, fontSize: 16)),
                      const SizedBox(height: 8),
                      if (type == 'text')
                        TextField(
                          onChanged: (v) => setState(() => _entryResponses[id] = v),
                          style: const TextStyle(color: Colors.white),
                          maxLines: 2,
                          decoration: InputDecoration(
                            hintText: q['placeholder'] as String? ?? '',
                            hintStyle: const TextStyle(color: Colors.grey),
                            filled: true,
                            fillColor: const Color(0xFF1a1a2e),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                          ),
                        )
                      else if (type == 'scale')
                        Column(
                          children: [
                            Slider(
                              value: _feelingScale.toDouble(),
                              min: 1, max: 10, divisions: 9,
                              activeColor: _feelingScale <= 3 ? Colors.red : _feelingScale <= 6 ? Colors.orange : Colors.green,
                              onChanged: (v) => setState(() { _feelingScale = v.round(); _entryResponses[id] = _feelingScale; }),
                            ),
                            Text('$_feelingScale / 10', style: TextStyle(color: _feelingScale <= 3 ? Colors.red : _feelingScale <= 6 ? Colors.orange : Colors.green, fontSize: 24, fontWeight: FontWeight.bold)),
                          ],
                        ),
                    ],
                  ),
                );
              }).toList(),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    _entryResponses['feeling_scale'] = _feelingScale;
                    _sendSanctuaryMessage({'type': 'sanctuary_entry_responses', 'sanctuary_id': _sanctuaryId, 'responses': _entryResponses});
                  },
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.cyan, padding: const EdgeInsets.symmetric(vertical: 16)),
                  child: const Text('Begin Session', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

'''
    
    if "_buildEntryQuestionsOverlay()" not in content or "if (!_showEntryQuestions)" not in content:
        marker = "  void _exitSanctuary("
        if marker in content:
            idx = content.find(marker)
            content = content[:idx] + widget + content[idx:]
            print("Added entry questions widget")
    
    with open(FLUTTER, 'w') as f:
        f.write(content)
    
    print("Done! Hot restart Flutter.")

if __name__ == "__main__":
    main()
