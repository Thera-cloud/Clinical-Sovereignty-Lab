#!/usr/bin/env python3
import os

FLUTTER = os.path.expanduser("~/Desktop/Clinical-Sovereignty-Lab-2/mobile/lib/main.dart")

def main():
    print("Fixing method name...")
    
    with open(FLUTTER, 'r') as f:
        content = f.read()
    
    # Find what the actual send method is called
    if "_sendToSanctuary(" in content:
        method = "_sendToSanctuary"
    elif "_sanctuaryChannel.sink.add" in content:
        method = "_sanctuaryChannel.sink.add"
    elif "_sanctuarySocket" in content:
        method = "_sanctuarySocket!.sink.add"
    else:
        # Search for the pattern
        import re
        match = re.search(r'void (_send\w+)\(Map', content)
        if match:
            method = match.group(1)
        else:
            print("Could not find send method. Searching...")
            # Look for how other messages are sent
            if "sink.add(json.encode" in content or "sink.add(jsonEncode" in content:
                method = "_sanctuaryChannel?.sink.add(jsonEncode"
                print(f"Found sink pattern")
            else:
                print("Please run: grep -n 'sink.add' main.dart")
                return
    
    print(f"Found method: {method}")
    
    # Replace the wrong method call
    old = "_sendSanctuaryMessage({'type': 'sanctuary_entry_responses'"
    
    if "_sanctuaryChannel" in method or "sink.add" in method:
        new = "_sanctuaryChannel?.sink.add(jsonEncode({'type': 'sanctuary_entry_responses'"
        # Also need to close the jsonEncode
        content = content.replace(
            "_sendSanctuaryMessage({'type': 'sanctuary_entry_responses', 'sanctuary_id': _sanctuaryId, 'responses': _entryResponses});",
            "_sanctuaryChannel?.sink.add(jsonEncode({'type': 'sanctuary_entry_responses', 'sanctuary_id': _sanctuaryId, 'responses': _entryResponses}));"
        )
    else:
        content = content.replace("_sendSanctuaryMessage(", f"{method}(")
    
    with open(FLUTTER, 'w') as f:
        f.write(content)
    
    print("Fixed! Try flutter run again.")

if __name__ == "__main__":
    main()
