"""
REPLACE sanctuary_coaching_accept AND ADD THESE HANDLERS to bridge_server.py
Location: After sanctuary_message handler (around line 3346)
"""

# REPLACE existing sanctuary_coaching_accept with this:

            elif t == "sanctuary_coaching_accept":
                sanctuary_id = d.get('sanctuary_id')
                intervention_id = d.get('intervention_id')
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                count = sanctuary_engine.get_member_coaching_count(sanctuary_id, member_id)
                charge = 0.00 if count == 0 else 5.00
                is_free = count == 0
                
                if not is_free:
                    result = await sanctuary_engine.charge_coaching(sanctuary_id, intervention_id, member_id, charge)
                    if not result[0]:
                        await websocket.send(json.dumps({"type": "error", "message": "Payment failed."}))
                        continue
                
                session = sanctuary_engine.start_private_coaching(sanctuary_id, member_id, intervention_id)
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                result = await cortex.process_private_coaching(current_profile, sanctuary_data, session, "coaching_start")
                sanctuary_engine.add_coaching_message(sanctuary_id, member_id, "assistant", result["response"])
                
                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_started", "sanctuary_id": sanctuary_id,
                    "is_free": is_free, "charge_amount": charge,
                    "message": "🎁 First coaching FREE!" if is_free else f"💰 ${charge:.2f}",
                    "coaching_message": {"role": "assistant", "content": result["response"], "attempt_number": 1}
                }))
                
                await sanctuary_engine.broadcast_to_sanctuary(sanctuary_id, {
                    "type": "sanctuary_member_coaching", "member_id": member_id, "member_name": member_name,
                    "message": f"{member_name} is receiving private support. Sanctuary paused."
                }, exclude_user_id=member_id)

# ADD these new handlers after sanctuary_coaching_accept:

            elif t == "sanctuary_coaching_message":
                sanctuary_id = d.get('sanctuary_id')
                msg = d.get('message', '').strip()
                if not msg: continue
                
                member_id = current_profile['hardware_id']
                sanctuary_engine.add_coaching_message(sanctuary_id, member_id, "user", msg)
                
                session = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                if not session:
                    await websocket.send(json.dumps({"type": "error", "message": "No coaching session."}))
                    continue
                
                session["attempt_number"] = session.get("attempt_number", 0) + 1
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                result = await cortex.process_private_coaching(current_profile, sanctuary_data, session, "coaching_response")
                sanctuary_engine.add_coaching_message(sanctuary_id, member_id, "assistant", result["response"])
                sanctuary_engine.update_coaching_session(sanctuary_id, member_id, {"attempt_number": session["attempt_number"], "is_deescalated": result.get("is_deescalated", False)})
                
                resp = {"type": "sanctuary_coaching_response", "sanctuary_id": sanctuary_id,
                        "coaching_message": {"role": "assistant", "content": result["response"], "attempt_number": session["attempt_number"]},
                        "is_deescalated": result.get("is_deescalated", False), "attempts_remaining": max(0, 5 - session["attempt_number"])}
                if result.get("should_offer_assisted"):
                    resp["offer_assisted_response"] = True
                    resp["assisted_response_cost"] = 3.00
                await websocket.send(json.dumps(resp))

            elif t == "sanctuary_coaching_complete":
                sanctuary_id = d.get('sanctuary_id')
                want_assisted = d.get('request_assisted_response', False)
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                session = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                assisted = None
                
                if want_assisted and session:
                    charge_result = await sanctuary_engine.charge_coaching(sanctuary_id, session.get("intervention_id", ""), member_id, 3.00)
                    if charge_result[0]:
                        sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                        result = await cortex.process_private_coaching(current_profile, sanctuary_data, session, "generate_assisted_response")
                        r = result.get("response", "")
                        if "SUGGESTED_RESPONSE:" in r:
                            p = r.split("SUGGESTED_RESPONSE:")[1]
                            assisted = p.split("EXPLANATION:")[0].strip() if "EXPLANATION:" in p else p.strip()
                
                sanctuary_engine.end_coaching_session(sanctuary_id, member_id)
                await websocket.send(json.dumps({"type": "sanctuary_coaching_completed", "sanctuary_id": sanctuary_id, "message": f"Welcome back, {member_name}.", "assisted_response": assisted}))
                await sanctuary_engine.broadcast_to_sanctuary(sanctuary_id, {"type": "sanctuary_member_returned", "member_id": member_id, "member_name": member_name, "message": f"{member_name} has returned."})
                
                if not sanctuary_engine.get_active_coaching_sessions(sanctuary_id):
                    await sanctuary_engine.broadcast_to_sanctuary(sanctuary_id, {"type": "sanctuary_resumed", "message": "Everyone is back. Sanctuary resumed. 💙"})

            elif t == "sanctuary_request_assisted_response":
                sanctuary_id = d.get('sanctuary_id')
                member_id = current_profile['hardware_id']
                
                session = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                if not session:
                    await websocket.send(json.dumps({"type": "error", "message": "No coaching session."}))
                    continue
                
                charge_result = await sanctuary_engine.charge_coaching(sanctuary_id, session.get("intervention_id", ""), member_id, 3.00)
                if not charge_result[0]:
                    await websocket.send(json.dumps({"type": "error", "message": "Payment failed."}))
                    continue
                
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                result = await cortex.process_private_coaching(current_profile, sanctuary_data, session, "generate_assisted_response")
                r = result.get("response", "")
                assisted, explanation = r, ""
                if "SUGGESTED_RESPONSE:" in r:
                    p = r.split("SUGGESTED_RESPONSE:")[1]
                    if "EXPLANATION:" in p:
                        s = p.split("EXPLANATION:")
                        assisted, explanation = s[0].strip(), s[1].strip()
                    else:
                        assisted = p.strip()
                
                await websocket.send(json.dumps({"type": "sanctuary_assisted_response_generated", "sanctuary_id": sanctuary_id, "assisted_response": assisted, "explanation": explanation, "charge_amount": 3.00}))
