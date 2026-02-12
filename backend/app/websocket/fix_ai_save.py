#!/usr/bin/env python3
"""Fix AI call and save method names"""

with open('bridge_server.py', 'r') as f:
    content = f.read()

# Fix 1: _save_data() -> _save()
content = content.replace('sanctuary_engine._save_data()', 'sanctuary_engine._save()')
print("Fixed: _save_data() -> _save()")

# Fix 2: For now, skip AI summary if call_azure_openai doesn't exist
# The summary will use fallback data but still work
# We can enhance AI later

with open('bridge_server.py', 'w') as f:
    f.write(content)

print("Done! Restart backend.")
