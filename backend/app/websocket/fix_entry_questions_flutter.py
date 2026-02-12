#!/usr/bin/env python3
"""
Flutter Fix: Sanctuary Entry Questions UI
=========================================
Adds entry questionnaire overlay before users enter sanctuary.

Run from anywhere
"""

import os
import shutil
from datetime import datetime

FILE_PATH = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def apply_fixes():
    print("=" * 60)
    print("Flutter Fix: Sanctuary Entry Questions")
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
    # FIX 1: Add state variables for entry questions
    # =========================================================================
    
    if "_showEntryQuestions" not in content:
        old_state = "  bool _sanctuaryPaused = false;"
        new_state = """  bool _sanctuaryPaused = false;
  
  // Entry Questions state
  bool _showEntryQuestions = false;
  List<Map<String, dynamic>> _entryQuestions = [];
  Map<String, dynamic> _entryResponses = {};
  int _feelingScale = 5;"""
        
        if old_state in content:
            content = content.replace(old_state, new_state)
            fixes_applied.append("1. Added entry questions state variables")
    
    # =========================================================================
    # FIX 2: Add handlers for entry question messages
    # =========================================================================
    
    entry_handlers = '''
      // ENTRY QUESTIONS
      case 'sanctuary_entry_questions':
        print('>>> SANCTUARY: Entry questions received');
        setState(() {
          _showEntryQuestions = true;
          _entryQuestions = (data['questions'] as List<dynamic>?)
              ?.map((q) => Map<String, dynamic>.from(q as Map))
              .toList() ?? [];
          _entryResponses = {};
          _feelingScale = 5;
        });
        break;
        
      case 'sanctuary_entry_complete':
        print('>>> SANCTUARY: Entry complete');
        // Entry questions submitted, waiting for entry_ready
        break;
        
      case 'sanctuary_entry_ready':
        print('>>> SANCTUARY: Entry ready - loading sanctuary');
        setState(() {
          _showEntryQuestions = false;
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          _members = _parseMembersList(data['members']);
        });
        // Load message history
        final entryMessages = data['messages'] as List<dynamic>?;
        if (entryMessages != null && entryMessages.isNotEmpty) {
          setState(() {
            _messages = entryMessages.map((m) => Map<String, dynamic>.from(m as Map)).toList();
          });
        }
        _addSystemMessage(data['message'] ?? 'Welcome to the sanctuary!');
        break;
'''
    
    # Find where to insert - after sanctuary_joined handler
    insert_marker = "case 'sanctuary_joined':"
    if insert_marker in content and "case 'sanctuary_entry_questions':" not in content:
        # Find the break; after sanctuary_joined
        idx = content.find(insert_marker)
        # Find next case statement
        next_case = content.find("\n      case '", idx + len(insert_marker))
        if next_case > 0:
            content = content[:next_case] + entry_handlers + content[next_case:]
            fixes_applied.append("2. Added entry question message handlers")
    
    # =========================================================================
    # FIX 3: Add entry questions widget method
    # =========================================================================
    
    entry_widget = '''
  // Entry Questions Overlay
  Widget _buildEntryQuestionsOverlay() {
    if (!_showEntryQuestions) return const SizedBox.shrink();
    
    return Container(
      color: Colors.black.withOpacity(0.9),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Icon(Icons.favorite, color: Colors.cyan, size: 48),
              const SizedBox(height: 16),
              const Text(
                'Before We Begin',
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Help Little Nate understand where you\\'re at 💙',
                style: TextStyle(color: Colors.grey),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 32),
              
              // Questions
              ..._entryQuestions.map((q) => _buildEntryQuestionWidget(q)).toList(),
              
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _canSubmitEntryQuestions() ? _submitEntryResponses : null,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.cyan,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: const Text(
                    'Begin Sanctuary Session',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
  
  Widget _buildEntryQuestionWidget(Map<String, dynamic> question) {
    final id = question['id'] as String;
    final type = question['type'] as String;
    final questionText = question['question'] as String;
    
    return Container(
      margin: const EdgeInsets.only(bottom: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            questionText,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: 12),
          
          if (type == 'text')
            TextField(
              onChanged: (val) => setState(() => _entryResponses[id] = val),
              style: const TextStyle(color: Colors.white),
              maxLines: 3,
              decoration: InputDecoration(
                hintText: question['placeholder'] as String? ?? '',
                hintStyle: TextStyle(color: Colors.grey[600]),
                filled: true,
                fillColor: const Color(0xFF1a1a2e),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide.none,
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: Colors.grey, width: 0.5),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: Colors.cyan, width: 1),
                ),
              ),
            )
          else if (type == 'scale')
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF1a1a2e),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        question['min_label'] as String? ?? '1',
                        style: const TextStyle(color: Colors.grey, fontSize: 12),
                      ),
                      Text(
                        question['max_label'] as String? ?? '10',
                        style: const TextStyle(color: Colors.grey, fontSize: 12),
                      ),
                    ],
                  ),
                  Slider(
                    value: _feelingScale.toDouble(),
                    min: (question['min'] as int? ?? 1).toDouble(),
                    max: (question['max'] as int? ?? 10).toDouble(),
                    divisions: (question['max'] as int? ?? 10) - (question['min'] as int? ?? 1),
                    activeColor: _getScaleColor(_feelingScale),
                    inactiveColor: Colors.grey[700],
                    onChanged: (val) {
                      setState(() {
                        _feelingScale = val.round();
                        _entryResponses[id] = _feelingScale;
                      });
                    },
                  ),
                  Text(
                    '$_feelingScale',
                    style: TextStyle(
                      color: _getScaleColor(_feelingScale),
                      fontSize: 32,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  Text(
                    _getScaleLabel(_feelingScale),
                    style: const TextStyle(color: Colors.grey),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
  
  Color _getScaleColor(int value) {
    if (value <= 3) return Colors.red;
    if (value <= 5) return Colors.orange;
    if (value <= 7) return Colors.yellow;
    return Colors.green;
  }
  
  String _getScaleLabel(int value) {
    if (value <= 2) return 'Very upset';
    if (value <= 4) return 'Upset';
    if (value <= 6) return 'Neutral';
    if (value <= 8) return 'Calm';
    return 'Very calm';
  }
  
  bool _canSubmitEntryQuestions() {
    for (var q in _entryQuestions) {
      if (q['required'] == true) {
        final id = q['id'] as String;
        final response = _entryResponses[id];
        if (q['type'] == 'text' && (response == null || response.toString().trim().isEmpty)) {
          return false;
        }
      }
    }
    return true;
  }
  
  void _submitEntryResponses() {
    // Ensure feeling scale is included
    _entryResponses['feeling_scale'] = _feelingScale;
    
    _sendSanctuaryMessage({
      'type': 'sanctuary_entry_responses',
      'sanctuary_id': _sanctuaryId,
      'responses': _entryResponses,
    });
  }
'''
    
    # Find insertion point - before _buildPausedOverlay or _showError
    if "_buildEntryQuestionsOverlay" not in content:
        insert_before = "void _showError("
        if insert_before in content:
            idx = content.find(insert_before)
            content = content[:idx] + entry_widget + "\n  " + content[idx:]
            fixes_applied.append("3. Added entry questions widget methods")
    
    # =========================================================================
    # FIX 4: Add entry questions overlay to build method
    # =========================================================================
    
    # Find the Stack in the sanctuary build and add entry questions overlay
    old_stack_children = '''children: [
            _buildSanctuaryChat(),
            _buildPausedOverlay(),'''
    
    new_stack_children = '''children: [
            _buildSanctuaryChat(),
            _buildPausedOverlay(),
            _buildEntryQuestionsOverlay(),'''
    
    if old_stack_children in content and "_buildEntryQuestionsOverlay()," not in content:
        content = content.replace(old_stack_children, new_stack_children)
        fixes_applied.append("4. Added entry questions overlay to Stack")
    
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
        print("ENTRY QUESTIONS UI:")
        print("  • Shows before entering sanctuary")
        print("  • 4 questions: why, what's happening, goals, feeling scale")
        print("  • Color-coded feeling scale (red→green)")
        print("  • Submit button enables when required fields filled")
        print("")
        print("NEXT: Hot restart Flutter and test")
    else:
        print("⚠️  No fixes applied - manual intervention may be needed")
    
    return True

if __name__ == "__main__":
    apply_fixes()
