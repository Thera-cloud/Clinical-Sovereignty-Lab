"""
FAMILY SANCTUARY WEBSOCKET HANDLERS
Add these handlers to bridge_server.py handle_client() function

Insert after line 2947 (after "ask_nate_coaching" handler)
"""

# ============================================================================
# FAMILY SANCTUARY HANDLERS
# ============================================================================

elif t == "sanctuary_create":
    """
    Create new Family Sanctuary session
    Restricted to: TOP_TIER Head of Household only
    """
    if current_profile.get('subscription_plan') != 'TOP_TIER':
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Family Sanctuary requires TOP_TIER subscription"
        }))
        continue
    
    if current_profile.get('role') != 'CLIENT':
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Only clients can create Family Sanctuaries"
        }))
        continue
    
    # Extract data
    family_id = current_profile.get('family_id')
    invited_members = d.get('invited_members', [])  # List of user IDs
    initial_topic = d.get('initial_topic', '')
    consent_data = d.get('consent', {})
    
    # Create sanctuary session
    sanctuary_id = await sanctuary_engine.create_sanctuary(
        family_id=family_id,
        head_of_household=current_profile['hardware_id'],
        invited_members=invited_members,
        topic=initial_topic,
        consent_data=consent_data
    )
    
    # Charge base fee
    base_fee_success = await sanctuary_engine.charge_base_fee(
        sanctuary_id=sanctuary_id,
        stripe_customer_id=current_profile.get('stripe_customer_id')
    )
    
    if not base_fee_success:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Payment failed. Please check your payment method."
        }))
        continue
    
    # Send invitations to family members
    for member_id in invited_members:
        # TODO: Send push notifications
        pass
    
    await websocket.send(json.dumps({
        "type": "sanctuary_created",
        "sanctuary_id": sanctuary_id,
        "status": "WAITING_FOR_MEMBERS",
        "invited_count": len(invited_members),
        "base_fee_charged": 20.00
    }))

elif t == "sanctuary_join":
    """
    Family member joins existing sanctuary
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # Verify invitation
    if not await sanctuary_engine.verify_invitation(
        sanctuary_id, current_profile['hardware_id']
    ):
        await websocket.send(json.dumps({
            "type": "error",
            "message": "You are not invited to this sanctuary"
        }))
        continue
    
    # Add member to session
    await sanctuary_engine.add_member(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id'],
        websocket=websocket
    )
    
    # Get current members list
    members_list = sanctuary_engine.get_member_list(sanctuary_id)
    
    # Send onboarding message from Little Nate
    onboarding_message = f"""Welcome to Family Sanctuary, {current_profile['name']}. I'm Little Nate, and I'll be facilitating this conversation to help your family find connection and understanding.

Currently in the sanctuary:
{chr(10).join(['• ' + name for name in members_list])}

Before we begin, please share:
1. What brought you to this Family Sanctuary today?
2. What's your goal for this conversation?
3. What concerns or issues are you experiencing?

This information is confidential and will help me provide better support."""
    
    await websocket.send(json.dumps({
        "type": "sanctuary_onboarding",
        "sanctuary_id": sanctuary_id,
        "message": onboarding_message,
        "current_members": members_list
    }))

elif t == "sanctuary_onboarding_complete":
    """
    Member completes onboarding questions
    """
    sanctuary_id = d.get('sanctuary_id')
    responses = d.get('responses', {})
    
    # Store confidential responses
    await sanctuary_engine.store_member_input(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id'],
        initial_reason=responses.get('reason', ''),
        personal_goal=responses.get('goal', ''),
        family_concerns=responses.get('concerns', '')
    )
    
    await websocket.send(json.dumps({
        "type": "sanctuary_onboarding_complete",
        "message": "Thank you for sharing. Waiting for other members..."
    }))
    
    # Check if all members joined
    if await sanctuary_engine.all_members_joined(sanctuary_id):
        # Start session
        await sanctuary_engine.start_session(sanctuary_id)

elif t == "sanctuary_message":
    """
    Member sends message in sanctuary
    """
    sanctuary_id = d.get('sanctuary_id')
    message = d.get('message', '')
    
    if not message.strip():
        continue
    
    # Store message
    message_id = await sanctuary_engine.add_message(
        sanctuary_id=sanctuary_id,
        sender_id=current_profile['hardware_id'],
        content=message
    )
    
    # Broadcast to all members
    await sanctuary_engine.broadcast_to_sanctuary(
        sanctuary_id=sanctuary_id,
        message_data={
            "type": "sanctuary_message",
            "message_type": "MEMBER_MESSAGE",
            "sender_id": current_profile['hardware_id'],
            "sender_name": current_profile['name'],
            "content": message,
            "timestamp": datetime.now().isoformat()
        }
    )
    
    # CRITICAL: Monitor for escalation
    escalation_detected = await sanctuary_engine.detect_escalation(
        sanctuary_id=sanctuary_id,
        message_id=message_id,
        message_content=message,
        sender_id=current_profile['hardware_id']
    )
    
    if escalation_detected:
        # Trigger intervention
        await sanctuary_engine.trigger_intervention(
            sanctuary_id=sanctuary_id,
            triggered_by_message_id=message_id
        )

elif t == "sanctuary_coaching_accept":
    """
    Member accepts individual coaching offer
    """
    sanctuary_id = d.get('sanctuary_id')
    intervention_id = d.get('intervention_id')
    wants_assisted_response = d.get('assisted_response', False)
    
    # Check if this is member's first coaching
    member_coaching_count = sanctuary_engine.get_member_coaching_count(
        sanctuary_id, current_profile['hardware_id']
    )
    
    if member_coaching_count == 0:
        # FIRST COACHING - FREE!
        charge_amount = 0.00
        charge_success = True
        is_free = True
        
        # Notify member it's free
        await websocket.send(json.dumps({
            "type": "sanctuary_coaching_notification",
            "message": "🎁 Your first coaching is FREE! Subsequent coaching will be $5 each."
        }))
    else:
        # SUBSEQUENT COACHING - CHARGE
        charge_amount = 5.00 if not wants_assisted_response else 8.00
        is_free = False
        
        # Get Head of Household for billing
        sanctuary = sanctuary_engine.get_session(sanctuary_id)
        hoh_profile = load_user_profile(sanctuary['head_of_household_id'])
        
        charge_success = await sanctuary_engine.charge_coaching(
            sanctuary_id=sanctuary_id,
            intervention_id=intervention_id,
            member_id=current_profile['hardware_id'],
            amount=charge_amount,
            stripe_customer_id=hoh_profile.get('stripe_customer_id')
        )
        
        if not charge_success:
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Payment failed. Please try again."
            }))
            continue
    
    # Generate coaching content
    coaching_content = await sanctuary_engine.generate_coaching(
        sanctuary_id=sanctuary_id,
        intervention_id=intervention_id,
        member_id=current_profile['hardware_id'],
        include_drafted_response=wants_assisted_response
    )
    
    # Increment coaching count for this member
    await sanctuary_engine.increment_coaching_count(
        sanctuary_id, current_profile['hardware_id']
    )
    
    # Send coaching
    await websocket.send(json.dumps({
        "type": "sanctuary_coaching",
        "intervention_id": intervention_id,
        "coaching_content": coaching_content,
        "charge_amount": charge_amount,
        "is_free": is_free,
        "coaching_number": member_coaching_count + 1
    }))

elif t == "sanctuary_exit":
    """
    Member wants to exit sanctuary
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # Little Nate checks in first
    checkin_message = f"""Hi {current_profile['name']},

I notice you want to leave the sanctuary. That's okay. This might be overwhelming.

Before you go, can you help me understand?
• Are you feeling unsafe?
• Is this too much to handle right now?
• Do you need a break but want to come back later?

Your feelings matter. 💙"""
    
    await websocket.send(json.dumps({
        "type": "sanctuary_exit_checkin",
        "message": checkin_message
    }))

elif t == "sanctuary_exit_confirm":
    """
    Member confirms exit after check-in
    """
    sanctuary_id = d.get('sanctuary_id')
    reason = d.get('reason', '')
    inform_family = d.get('inform_family', True)
    
    # Mark member as exited
    await sanctuary_engine.member_exit(
        sanctuary_id=sanctuary_id,
        member_id=current_profile['hardware_id'],
        reason=reason
    )
    
    # Notify family if requested
    if inform_family:
        exit_message = f"{current_profile['name']} is taking a break from the sanctuary. They can rejoin anytime they're ready. 💙"
        
        await sanctuary_engine.broadcast_to_sanctuary(
            sanctuary_id=sanctuary_id,
            message_data={
                "type": "sanctuary_member_exited",
                "member_id": current_profile['hardware_id'],
                "message": exit_message
            }
        )
    
    await websocket.send(json.dumps({
        "type": "sanctuary_exited",
        "can_rejoin": True
    }))

elif t == "sanctuary_extend":
    """
    Extend sanctuary for another 24-hour cycle
    24-hour check-in from Little Nate
    """
    sanctuary_id = d.get('sanctuary_id')
    member_wants_continue = d.get('continue', False)
    
    # Record member's response
    # TODO: Implement extension voting logic
    
    await websocket.send(json.dumps({
        "type": "sanctuary_extend_recorded",
        "message": "Your response has been recorded. Waiting for other members..."
    }))

elif t == "sanctuary_complete":
    """
    End sanctuary session
    Head of Household only
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # Verify Head of Household
    sanctuary = sanctuary_engine.get_session(sanctuary_id)
    if sanctuary['head_of_household_id'] != current_profile['hardware_id']:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Only Head of Household can complete the sanctuary"
        }))
        continue
    
    # Generate summary
    summary = f"""Beautiful work, everyone. 💙

Your family showed courage in having these difficult conversations.

Session Summary:
• Duration: {calculate_duration(sanctuary)}
• Total messages: {sanctuary['metrics']['total_messages']}
• Breakthrough moments: {sanctuary['metrics']['breakthrough_moments']}
• Final charges: ${sanctuary['billing']['total_charges']:.2f}

This sanctuary session is now archived and accessible for future reference."""
    
    # Complete session
    await sanctuary_engine.complete_session(sanctuary_id)
    
    # Send summary to all members
    await sanctuary_engine.broadcast_to_sanctuary(
        sanctuary_id=sanctuary_id,
        message_data={
            "type": "sanctuary_completed",
            "summary": summary,
            "total_charges": sanctuary['billing']['total_charges'],
            "archive_url": f"SANC_{sanctuary_id}_archived"
        }
    )

elif t == "sanctuary_request_coach":
    """
    Request live coach escalation
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # TODO: Generate coach summary and notify coach
    
    await websocket.send(json.dumps({
        "type": "coach_notified",
        "message": "A coach will be notified within 24 hours."
    }))
