# =============================================================================
# FAMILY SANCTUARY HANDLERS - UPDATED
# Add/replace this section in bridge_server.py
# =============================================================================

# Find the existing sanctuary_get_or_create handler and REPLACE it with this:

elif t == "sanctuary_get_or_create":
    """
    Smart handler that:
    1. Finds existing sanctuary for family OR creates new one
    2. Handles reconnection without duplicates
    3. Notifies other members only for true new joins
    """
    if not current_profile:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Not authenticated"
        }))
        continue
    
    family_id = current_profile.get('family_id')
    member_id = current_profile.get('hardware_id')
    member_name = current_profile.get('name')
    
    print(f">>> [SANCTUARY] Processing get_or_create for {member_name} ({member_id}) in family {family_id}")
    
    # Check for existing sanctuary
    existing = sanctuary_engine.get_active_sanctuary_for_family(family_id)
    
    if existing:
        sanctuary_id = existing['sanctuary_id']
        print(f">>> [SANCTUARY] Found existing sanctuary: {sanctuary_id}")
        
        # Add or reconnect member
        result = await sanctuary_engine.add_or_reconnect_member(
            sanctuary_id=sanctuary_id,
            user_id=member_id,
            user_name=member_name,
            websocket=websocket
        )
        
        if not result['success']:
            await websocket.send(json.dumps({
                "type": "error",
                "message": result.get('error', 'Failed to join')
            }))
            continue
        
        members = sanctuary_engine.get_member_list(sanctuary_id)
        action = result['action']
        
        if action == "JOINED":
            # Truly new member
            await websocket.send(json.dumps({
                "type": "sanctuary_joined",
                "sanctuary_id": sanctuary_id,
                "status": existing.get('status', 'ACTIVE'),
                "members": members
            }))
            
            # Notify others
            await sanctuary_engine.broadcast_to_sanctuary(
                sanctuary_id=sanctuary_id,
                message_data={
                    "type": "sanctuary_member_joined",
                    "member": {"id": member_id, "name": member_name}
                },
                exclude_user_id=member_id
            )
            
        elif action in ["RECONNECTED", "REFRESHED"]:
            # Returning member (page refresh or reconnecting)
            await websocket.send(json.dumps({
                "type": "sanctuary_reconnected",
                "sanctuary_id": sanctuary_id,
                "status": existing.get('status', 'ACTIVE'),
                "members": members,
                "message": f"Welcome back, {member_name}!"
            }))
            
        elif action == "RETURNED":
            # Member who had exited is returning
            await websocket.send(json.dumps({
                "type": "sanctuary_rejoined",
                "sanctuary_id": sanctuary_id,
                "status": existing.get('status', 'ACTIVE'),
                "members": members,
                "message": f"Welcome back to the sanctuary, {member_name}!"
            }))
            
            # Notify others that member returned
            await sanctuary_engine.broadcast_to_sanctuary(
                sanctuary_id=sanctuary_id,
                message_data={
                    "type": "sanctuary_member_returned",
                    "member": {"id": member_id, "name": member_name}
                },
                exclude_user_id=member_id
            )
    else:
        print(f">>> [SANCTUARY] No existing sanctuary, creating new one for family {family_id}")
        
        # Create new sanctuary
        sanctuary_id = await sanctuary_engine.create_sanctuary(
            family_id=family_id,
            head_of_household_id=member_id,
            invited_members=[],
            initial_topic='',
            consent_data={}
        )
        
        # Add creator as first member
        await sanctuary_engine.add_or_reconnect_member(
            sanctuary_id=sanctuary_id,
            user_id=member_id,
            user_name=member_name,
            websocket=websocket
        )
        
        await websocket.send(json.dumps({
            "type": "sanctuary_created",
            "sanctuary_id": sanctuary_id,
            "status": "WAITING_FOR_MEMBERS",
            "base_fee_charged": 20.00
        }))


# =============================================================================
# Also update the connection close handler to mark members as PAUSED
# Find where you handle websocket close (in the finally block or exception handler)
# Add this call:
# =============================================================================

# In the finally block or ConnectionClosed handler, add:
# 
# # Handle sanctuary member disconnect
# for sanctuary_id in list(sanctuary_engine._websocket_registry.keys()):
#     for user_id, ws in list(sanctuary_engine._websocket_registry.get(sanctuary_id, {}).items()):
#         if ws == websocket:
#             sanctuary_engine.member_disconnect(sanctuary_id, user_id)
#             break
