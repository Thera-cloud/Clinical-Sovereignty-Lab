#!/usr/bin/env python3
"""Fix websocket calls to use sanctuary_engine methods"""

with open('bridge_server.py', 'r') as f:
    content = f.read()

# Fix 1: Use broadcast for "generating summary" message
old1 = '''for mid, ws in list(sanctuary_websockets.get(sanctuary_id, {}).items()):
                    try:
                        await ws.send(json.dumps({
                            "type": "sanctuary_generating_summary",
                            "sanctuary_id": sanctuary_id,
                            "message": "Little Nate is preparing your session summary... 💙"
                        }))
                    except:
                        pass'''

new1 = '''await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_generating_summary",
                        "sanctuary_id": sanctuary_id,
                        "message": "Little Nate is preparing your session summary... 💙"
                }
                )'''

content = content.replace(old1, new1)

# Fix 2: Use get_member_websocket for personalized summaries
old2 = '''ws = sanctuary_websockets.get(sanctuary_id, {}).get(m_id)'''
new2 = '''ws = sanctuary_engine.get_member_websocket(sanctuary_id, m_id)'''
content = content.replace(old2, new2)

# Fix 3: Remove the del sanctuary_websockets line
old3 = '''if sanctuary_id in sanctuary_websockets:
                    del sanctuary_websockets[sanctuary_id]'''
new3 = '''# Websockets managed by sanctuary_engine'''
content = content.replace(old3, new3)

with open('bridge_server.py', 'w') as f:
    f.write(content)

print("Fixed websocket calls!")
