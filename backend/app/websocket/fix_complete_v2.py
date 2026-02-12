#!/usr/bin/env python3

with open('bridge_server.py', 'r') as f:
    content = f.read()

handler = '''
            # COMPLETE SESSION
            elif t == "sanctuary_complete":
                sid = message_data.get("sanctuary_id")
                print(f">>> [SANCTUARY] Completing session {sid}")
                sdata = sanctuary_engine.data["active_sanctuaries"].get(sid, {})
                if sdata:
                    import os as os2
                    hdir = os2.path.join(DATA_DIR, "sanctuary_history")
                    os2.makedirs(hdir, exist_ok=True)
                    sdata["completed_at"] = datetime.datetime.now().isoformat()
                    sdata["status"] = "COMPLETED"
                    with open(os2.path.join(hdir, f"{sid}.json"), "w") as hf:
                        json.dump(sdata, hf, indent=2, default=str)
                    del sanctuary_engine.data["active_sanctuaries"][sid]
                    sanctuary_engine._save_data()
                    for mid, ws in list(sanctuary_websockets.get(sid, {}).items()):
                        try:
                            await ws.send(json.dumps({"type": "sanctuary_completed", "sanctuary_id": sid}))
                        except: pass
                    if sid in sanctuary_websockets:
                        del sanctuary_websockets[sid]
                    print(f">>> [SANCTUARY] Session {sid} archived")

'''

# Remove old broken handler first
import re
content = re.sub(r'# COMPLETE SESSION\s+elif t == "sanctuary_complete":.*?(?=\n            elif t == ")', '', content, flags=re.DOTALL)

# Add new handler
marker = 'elif t == "sanctuary_entry_responses":'
if marker in content:
    idx = content.find(marker)
    content = content[:idx] + handler + "            " + content[idx:]
    print("Added handler")

with open('bridge_server.py', 'w') as f:
    f.write(content)

print("Done!")
