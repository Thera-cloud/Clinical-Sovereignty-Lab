#!/usr/bin/env python3
import os

def main():
    print("Fixing sanctuary_complete handler...")
    
    with open("bridge_server.py", 'r') as f:
        content = f.read()
    
    # Add handler for sanctuary_complete if missing or broken
    handler = '''
            # COMPLETE SESSION
            elif t == "sanctuary_complete":
                sanctuary_id = data.get("sanctuary_id")
                print(f">>> [SANCTUARY] Completing session {sanctuary_id}")
                
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                
                if sanctuary_data:
                    # Store to history before deleting
                    import os as os_mod
                    history_dir = os_mod.path.join(DATA_DIR, "sanctuary_history")
                    os_mod.makedirs(history_dir, exist_ok=True)
                    
                    sanctuary_data["completed_at"] = datetime.datetime.now().isoformat()
                    sanctuary_data["status"] = "COMPLETED"
                    
                    history_path = os_mod.path.join(history_dir, f"{sanctuary_id}.json")
                    with open(history_path, 'w') as hf:
                        json.dump(sanctuary_data, hf, indent=2, default=str)
                    
                    # Remove from active sanctuaries
                    del sanctuary_engine.data["active_sanctuaries"][sanctuary_id]
                    sanctuary_engine._save_data()
                    
                    # Notify all members
                    for mid, ws in list(sanctuary_websockets.get(sanctuary_id, {}).items()):
                        try:
                            await ws.send(json.dumps({
                                "type": "sanctuary_completed",
                                "sanctuary_id": sanctuary_id,
                                "message": "Session complete. Thank you for participating."
                            }))
                        except:
                            pass
                    
                    # Clear websocket registry
                    if sanctuary_id in sanctuary_websockets:
                        del sanctuary_websockets[sanctuary_id]
                    
                    print(f">>> [SANCTUARY] Session {sanctuary_id} completed and archived")
                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Sanctuary not found"
                    }))

'''
    
    # Check if there's a broken handler
    if "sanctuary_complete" in content and "calculate_duration" in content:
        # Find and replace the broken handler
        import re
        # Remove the broken section
        pattern = r'elif t == "sanctuary_complete":.*?(?=elif t == "|$)'
        content = re.sub(pattern, '', content, flags=re.DOTALL)
        print("Removed broken handler")
    
    if 'elif t == "sanctuary_complete":' not in content or "calculate_duration" in content:
        # Add the new handler
        marker = 'elif t == "sanctuary_entry_responses":'
        if marker in content:
            idx = content.find(marker)
            content = content[:idx] + handler + "            " + content[idx:]
            print("Added sanctuary_complete handler")
    
    with open("bridge_server.py", 'w') as f:
        f.write(content)
    
    print("Done! Restart backend.")

if __name__ == "__main__":
    main()
