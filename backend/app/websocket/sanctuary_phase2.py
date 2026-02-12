#!/usr/bin/env python3
import os
import shutil
from datetime import datetime

def main():
    print("SANCTUARY PHASE 2 INSTALLER")
    
    backend = "bridge_server.py"
    
    if not os.path.exists(backend):
        print("ERROR: Run from websocket folder!")
        return
    
    shutil.copy(backend, backend + ".bak")
    print("Backed up bridge_server.py")
    
    with open(backend, 'r') as f:
        content = f.read()
    
    handler = '''
            # ENTRY QUESTIONS
            elif t == "sanctuary_entry_responses":
                sanctuary_id = data.get("sanctuary_id")
                responses = data.get("responses", {})
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                if sanctuary_data:
                    if "entry_responses" not in sanctuary_data:
                        sanctuary_data["entry_responses"] = {}
                    sanctuary_data["entry_responses"][member_id] = {
                        **responses,
                        "member_name": member_name,
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                    sanctuary_engine._save_data()
                    print(f">>> [SANCTUARY] Entry responses saved for {member_name}")
                    await websocket.send(json.dumps({
                        "type": "sanctuary_entry_complete",
                        "sanctuary_id": sanctuary_id,
                        "message": "Thank you for sharing."
                    }))
                    members = [{"user_id": m.get("user_id"), "name": m.get("name")} for m in sanctuary_data.get("members", [])]
                    await websocket.send(json.dumps({
                        "type": "sanctuary_entry_ready",
                        "sanctuary_id": sanctuary_id,
                        "status": sanctuary_data.get("status", "ACTIVE"),
                        "members": members,
                        "messages": sanctuary_data.get("messages", [])[-50:]
                    }))

'''
    
    if "sanctuary_entry_responses" not in content:
        marker = 'elif t == "sanctuary_exit":'
        if marker in content:
            idx = content.find(marker)
            content = content[:idx] + handler + "            " + content[idx:]
            print("Added entry questions handler")
        else:
            print("Could not find insertion point")
    else:
        print("Entry handler already exists")
    
    with open(backend, 'w') as f:
        f.write(content)
    
    print("Done!")

if __name__ == "__main__":
    main()
