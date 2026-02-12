#!/usr/bin/env python3
import os

def main():
    print("Adding entry questions SEND logic...")
    
    with open("bridge_server.py", 'r') as f:
        content = f.read()
    
    # Find where sanctuary_joined is sent and add entry questions check
    old_pattern = '''"type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,'''
    
    # We need to find where JOINED response is sent and wrap it
    # Let's search for the connection_type == "JOINED" section
    
    send_questions_code = '''
                        # Check if member needs entry questions
                        member_entry = sanctuary_data.get("entry_responses", {}).get(member_id)
                        if member_entry is None:
                            # Send entry questions first
                            await websocket.send(json.dumps({
                                "type": "sanctuary_entry_questions",
                                "sanctuary_id": sanctuary_id,
                                "questions": [
                                    {"id": "why_entering", "type": "text", "question": "Why are you entering the Family Sanctuary today?", "placeholder": "What brings you here?", "required": True},
                                    {"id": "whats_happening", "type": "text", "question": "What is happening right now in your family?", "placeholder": "Describe the situation...", "required": True},
                                    {"id": "goals", "type": "text", "question": "What do you hope to achieve?", "placeholder": "What would success look like?", "required": True},
                                    {"id": "feeling_scale", "type": "scale", "question": "How are you feeling right now?", "min": 1, "max": 10, "min_label": "Very upset", "max_label": "Completely calm", "required": True}
                                ],
                                "message": "Before we begin, help Little Nate understand where you are at."
                            }))
                            print(f">>> [SANCTUARY] Sent entry questions to {member_name}")
                        else:
'''
    
    # Find "JOINED" and add the check before sending sanctuary_joined
    if "sanctuary_entry_questions" not in content or "questions" not in content:
        # Find where we send sanctuary_joined for new members
        marker = 'connection_type = "JOINED"'
        if marker in content:
            idx = content.find(marker)
            # Find the await websocket.send after this
            send_idx = content.find("await websocket.send", idx)
            if send_idx > 0:
                # Insert before the send
                content = content[:send_idx] + send_questions_code + "                        " + content[send_idx:]
                print("Added entry questions send logic for JOINED")
        
        with open("bridge_server.py", 'w') as f:
            f.write(content)
        print("Done!")
    else:
        print("Entry questions send already exists")

if __name__ == "__main__":
    main()
