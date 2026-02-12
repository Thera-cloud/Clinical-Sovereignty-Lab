# FAMILY SANCTUARY FEATURE SPECIFICATION
## Multi-Member Therapeutic Group Sessions with Little Nate

**Feature Name:** Family Sanctuary  
**Version:** 1.0  
**Created:** January 26, 2026 4:00 AM  
**Status:** 🆕 NEW FEATURE - Ready for Development  
**Subscription Tier:** TOP_TIER only

---

## 📋 TABLE OF CONTENTS

1. [Feature Overview](#feature-overview)
2. [Therapeutic Approach](#therapeutic-approach)
3. [User Flow](#user-flow)
4. [Billing System](#billing-system)
5. [Technical Architecture](#technical-architecture)
6. [Database Schema](#database-schema)
7. [WebSocket Handlers](#websocket-handlers)
8. [Little Nate AI Prompt Engineering](#little-nate-ai-prompt-engineering)
9. [UI/UX Specifications](#uiux-specifications)
10. [Implementation Checklist](#implementation-checklist)

---

## 🎯 FEATURE OVERVIEW

### What is Family Sanctuary?

Family Sanctuary is a **group therapeutic chat session** where multiple family members can engage in facilitated conflict resolution, emotional processing, and connection building with AI guidance from Little Nate over a 24-48 hour period.

### Key Features

- **Multi-member group chat** (minimum 2, no maximum)
- **24-hour active session** with optional extensions
- **Real-time AI moderation** by Little Nate
- **Pay-per-intervention billing** ($20 base + $5-$8 per coaching moment)
- **Confidentiality protected** (Little Nate knows individual histories but keeps private)
- **Multiple therapeutic modalities** (Family Systems, EFT, IFS, Legacy work)
- **Azure Blob storage** for session archives
- **Coach escalation** at $100 threshold or 7-day mark
- **Minor participation** (with parental consent)

### Use Cases

1. **Spousal Disputes** → EFT Couples Work
2. **Sibling Conflicts** → Connection & Understanding
3. **Generational Trauma** → Transgenerational Legacy Healing
4. **Family Grief** → Collective Mourning Support
5. **Parenting Disagreements** → Co-parenting Alignment
6. **Extended Family Issues** → Multi-generational Mediation

---

## 🧠 THERAPEUTIC APPROACH

### Core Modalities

**1. Family Systems Therapy**
- Focus: Family as interconnected system
- Techniques: Circular questioning, genograms, family mapping
- Goal: Understanding systemic patterns and roles

**2. Emotionally Focused Therapy (EFT)**
- Focus: Attachment and emotional bonds
- Techniques: Emotion identification, validation, re-framing
- Goal: Secure attachment and emotional connection

**3. Internal Family Systems (IFS)**
- Focus: Parts of self and internal conflicts
- Techniques: Parts work, self-leadership, unburdening
- Goal: Self-compassion and internal harmony

**4. Transgenerational Legacy Work**
- Focus: Inherited family patterns and beliefs
- Techniques: Legacy exploration, narrative reframing
- Goal: Breaking harmful cycles, honoring positive legacies

### Little Nate's Role

**Observer Mode:**
- Monitors all family member messages
- Analyzes emotional tone, escalation patterns
- Detects disconnection or misunderstanding
- Tracks individual and collective C_emo (Nevedal)

**Intervention Mode:**
- Pauses conversation when escalation detected
- Offers individual coaching to one member
- Provides grounding, perspective-taking
- Suggests response options (optional $3 add-on)
- Facilitates turn-taking and active listening

**Mediator Mode:**
- Reflects what each person is saying
- Highlights common ground
- Reframes accusations as needs/feelings
- Encourages empathy and understanding

---

## 👥 USER FLOW

### Phase 1: Sanctuary Creation (5-10 minutes)

```
1. TOP_TIER Head of Household initiates Family Sanctuary
   ↓
2. Selects family members to invite:
   - Spouse ✓
   - Child 1 (age 16) ✓
   - Child 2 (age 12) ✓ (requires parental consent check)
   - Mother-in-law ✓
   ↓
3. Sets initial topic/conflict:
   "We're having disagreements about holiday plans and 
    grandma's involvement. We need to find a resolution."
   ↓
4. Agrees to $20 base fee + pay-per-intervention billing
   ↓
5. Sanctuary CREATED
   Status: WAITING_FOR_MEMBERS
```

### Phase 2: Member Join & Orientation (10-15 minutes)

```
For each invited family member:

1. Receives notification:
   "Emma has invited you to a Family Sanctuary session.
    Topic: Holiday planning and family dynamics.
    Join now?"
   ↓
2. Clicks JOIN → Enters sanctuary
   ↓
3. Little Nate greets individually:
   "Welcome to Family Sanctuary, Sarah. I'm Little Nate,
    and I'll be facilitating this conversation to help your
    family find connection and understanding.
    
    Currently in the sanctuary:
    • Emma (Head of Household)
    • You (Sarah)
    
    Waiting to join:
    • Michael (age 16)
    • Sophie (age 12)
    • Grandma Rose
    
    Before we begin, please share:
    1. What brought you to this Family Sanctuary today?
    2. What's your goal for this conversation?
    3. What concerns or issues are you experiencing?"
   ↓
4. Member provides their perspective (stored separately)
   ↓
5. Little Nate acknowledges and holds confidentially:
   "Thank you for sharing, Sarah. I understand your perspective.
    I'll keep your individual reflections confidential while
    helping facilitate the family conversation."
```

### Phase 3: Active Sanctuary Session (24 hours - 7 days)

```
ALL MEMBERS JOINED → Session begins

Little Nate opens:
"Welcome everyone to Family Sanctuary. I'm honored to hold
space for this important conversation. 

Currently present:
• Emma (mom)
• David (dad)
• Michael (16)
• Sophie (12)
• Grandma Rose

I've heard each of your individual perspectives on why you're
here. Let's begin with Emma sharing what brought the family
together today, and then each person will have a turn to respond.

Remember: I'm here to help guide the conversation toward
connection and understanding. I may pause at times to offer
individual coaching or reflection. Let's begin..."

──────────────────────────────────────────────────────

CONVERSATION FLOW:

Emma: "I feel like we can't agree on anything about the 
       holidays. Rose always wants things her way, and I 
       feel like my voice doesn't matter."

[Little Nate OBSERVES - detects defensive tone]

Rose:  "That's not fair! I just want to spend time with
        my grandchildren. You're always making excuses."

[Little Nate DETECTS escalation - INTERVENTION TRIGGERED]

Little Nate PAUSES conversation:

  → Private message to Emma:
     "I notice the conversation is becoming tense. Would
      you like coaching on how to respond in a way that
      expresses your needs while staying connected to Rose?
      
      💰 Individual Coaching: $5.00
      
      [Yes, help me] [No, I'll respond myself]"
  
  Emma chooses: [Yes, help me]
  
  → Little Nate provides coaching (Emma only sees):
     "I hear you're feeling unheard and controlled. Rose
      is likely feeling excluded and defensive. 
      
      Consider this approach:
      'Rose, I want you to be involved. I think we both
      want the same thing - a joyful holiday together.
      Can we talk about what's most important to each of us?'
      
      This validates her while expressing your need.
      
      Would you like me to draft a response for you?
      💰 Assisted Response: +$3.00
      
      [Yes, draft it] [No, I'll use my own words]"

  Emma: [No, I'll use my own words]
  
  → Emma types her response:
     "Rose, I didn't mean to sound harsh. I do want you
      involved. I think I'm just feeling overwhelmed with
      all the planning. Can we start over and talk about
      what matters most to each of us?"

[Little Nate OBSERVES - detects de-escalation, validates]

Little Nate (to everyone):
"I notice Emma just made a beautiful repair. She
 acknowledged Rose's feelings and suggested a collaborative
 approach. Rose, how does that land with you?"

Rose: "I appreciate that, Emma. I guess I have been pushy.
       I just miss the kids and want to be included."

[Little Nate OBSERVES - breakthrough moment detected]

Little Nate:
"This is a meaningful moment. I'm sensing you both want
 connection and to honor each other. Michael and Sophie,
 I'd love to hear from you - what do you want for the
 holidays with grandma?"

[CONVERSATION CONTINUES...]

──────────────────────────────────────────────────────

BILLING EVENTS:
• $20.00 - Base fee (session start)
• $5.00 - Coaching for Emma (17:23)
• $5.00 - Coaching for Rose (18:45)
• $5.00 - Coaching for Emma (19:12)
→ Total so far: $35.00

[Emma receives notification: "Family Sanctuary charges: $35"]
```

### Phase 4: Overnight & Next Day (24-hour cycle)

```
Evening (10 PM):
Little Nate: "It's getting late. We've made good progress
              today. I'll be here overnight if anyone needs
              to process or share thoughts. We can continue
              in the morning. Rest well."

[Members can leave messages asynchronously]

Michael (11 PM): "I just want to say I think we're doing
                  better. I like seeing mom and grandma
                  talk things out."

[Little Nate OBSERVES - positive reflection, no intervention needed]

Little Nate: "Thank you for sharing, Michael. That's a loving
              observation. 💙"

Morning (8 AM - 24 hours elapsed):
Little Nate: "Good morning, family. Our first 24-hour cycle
              is complete. I'd like to check in with each of you.
              
              Do you feel we've made progress?
              Would you like to continue in the sanctuary?
              
              Please respond individually."

Emma: "Yes, I think we need more time."
Rose: "I'd like to keep talking."
Michael: "Sure."
Sophie: "Ok."

Little Nate: "Wonderful. The sanctuary will remain open for
              another 24 hours. Let's continue..."

[Session extended - new 24-hour cycle begins]
```

### Phase 5: Cost Threshold Check ($50, $100)

```
[BILLING REACHES $50]

Little Nate (private to Emma - Head of Household):
"💰 Family Sanctuary Update:
 
 Current charges: $50.00
 • Base fee: $20
 • Coaching interventions: 6 × $5 = $30
 
 You're making good progress. I wanted to check in about costs.
 Would you like to:
 
 [Continue sanctuary] 
 [Schedule live coach session]
 [End sanctuary and review]"

Emma: [Continue sanctuary]

Little Nate: "Thank you. I'll continue supporting your family."

──────────────────────────────────────────────────────

[BILLING REACHES $100]

Little Nate (private to Emma):
"💰 Family Sanctuary Milestone:
 
 Current charges: $100.00
 
 This is a significant investment in your family's healing.
 I want to make sure you're getting the support you need.
 
 At this level, you may benefit from a live coach who can
 provide specialized guidance. 
 
 Would you like to:
 
 [Continue with me in sanctuary] 
 [Schedule appointment with live coach - FREE consultation]
 [End sanctuary - I'll provide summary]"

Emma: [Schedule appointment with live coach]

Little Nate: "I'll notify Coach Hope that your family would
              benefit from a live session. In the meantime,
              shall we continue in the sanctuary?"
```

### Phase 6: 7-Day Extended Session (Coach Check-in)

```
[DAY 7 of continuous sanctuary]

Little Nate (to Emma - Head of Household):
"Family Check-in:
 
 Your family has been in sanctuary for 7 days. This shows
 deep commitment to working through challenges together.
 
 I want to make sure I'm providing the best support. I'm
 going to reach out to a live coach for supervision to
 ensure we're on the right track.
 
 Would you like:
 
 [Coach supervision - continue sanctuary]
 [Schedule live family session]
 [Complete sanctuary - review progress]"

[Little Nate sends summary to Coach Hope for review]

──────────────────────────────────────────────────────

COACH RECEIVES:
Subject: Family Sanctuary - 7 Day Check-in
Family: Thompson Family (Emma - HoH)

MEMBERS:
• Emma (mom, 42)
• David (dad, 45)  
• Michael (son, 16)
• Sophie (daughter, 12)
• Rose (grandmother, 68)

INITIAL CONFLICT:
Holiday planning, boundaries with grandmother, parenting
disagreements

EACH MEMBER'S PERSPECTIVE:
• Emma: Feels unheard, wants boundaries but connection
• David: Wants peace, avoids conflict
• Michael: Feels caught in the middle
• Sophie: Confused, wants everyone to be happy
• Rose: Feels excluded, wants more time with grandkids

PROGRESS SUMMARY:
• 47 interventions over 7 days
• Total cost: $255 ($20 base + $235 coaching)
• Breakthrough moments: 8
• Escalations: 12 (all de-escalated)
• Current C_emo: Family avg 0.71 (up from 0.58)
• Status: Making progress but needs deeper work

RECOMMENDATION:
Family would benefit from live session to address:
1. Boundary setting between generations
2. David's conflict avoidance pattern
3. Children's role in parental conflicts

Coach Hope reviews and responds:
"Schedule 90-minute family session. Little Nate did great
 holding space. I'll help with boundaries and patterns."
```

### Phase 7: Sanctuary Conclusion

```
SCENARIO A: Natural Resolution (2-3 days)

Little Nate: "Family, I notice we've reached a good stopping
              point. You've made incredible progress:
              
              ✓ Expressed needs clearly
              ✓ Heard each other's perspectives
              ✓ Found compromise on holiday plans
              ✓ Set boundaries with love
              
              Would you like to:
              
              [Complete sanctuary - save to archive]
              [Continue for another cycle]"

All members: [Complete sanctuary]

Little Nate: "Beautiful work, everyone. This sanctuary session
              is now saved to your Family Learning Center in
              Azure. You can revisit it anytime.
              
              SUMMARY:
              • Duration: 3 days
              • Total interventions: 18
              • Final cost: $110
              • Breakthrough moments: 5
              • Resolution: Holiday plan agreed upon ✓
              
              I'm proud of your family's courage. 💙"

──────────────────────────────────────────────────────

SCENARIO B: Live Coach Transition

Little Nate: "Based on our work together and my consultation
              with Coach Hope, I recommend transitioning to a
              live family session to address deeper patterns.
              
              I've prepared a complete summary for Coach Hope
              so she'll be ready to help you.
              
              After your session with Hope, you're welcome to
              return to sanctuary to continue the conversation.
              
              Shall I schedule the appointment?"

──────────────────────────────────────────────────────

SCENARIO C: Member Exit

Sophie (age 12) clicks [Exit Sanctuary]

Little Nate (private to Sophie):
"I notice you want to leave the sanctuary. That's okay.
 This might be overwhelming.
 
 Before you go, can you help me understand?
 • Are you feeling unsafe?
 • Is this too much to handle right now?
 • Do you need a break but want to come back later?
 
 Your feelings matter, Sophie. 💙"

Sophie: "It's just a lot. I feel better but I'm tired."

Little Nate: "That makes sense. You can take a break and
              come back whenever you're ready. The sanctuary
              will stay open for your family.
              
              Would you like me to let your parents know you're
              taking a break, or keep it private?"

Sophie: "You can tell them."

Little Nate (to family): "Sophie is taking a break from the
                          sanctuary. She's doing great and can
                          rejoin anytime she's ready. Let's give
                          her that space. 💙"
```

---

## 📜 LEGAL REQUIREMENTS & CONSENT

### Family Sanctuary Waiver & Consent Agreement

**Required Before Session Creation - Must be acknowledged by Head of Household**

#### FAMILY SANCTUARY TERMS OF SERVICE

**Version:** 1.0 - January 2026

**PLEASE READ CAREFULLY BEFORE CREATING A FAMILY SANCTUARY SESSION**

By clicking "I Agree and Create Sanctuary," you (the Head of Household) acknowledge and agree to the following terms on behalf of yourself and all invited family members:

---

**1. NATURE OF SERVICE**

Family Sanctuary is an **AI-facilitated group therapeutic session** powered by Little Nate, an artificial intelligence system. This service:

- ✅ Provides AI-generated therapeutic guidance and conflict mediation
- ✅ Uses evidence-based therapeutic approaches (Family Systems, EFT, IFS, etc.)
- ✅ Is NOT a substitute for professional human therapy or crisis intervention
- ✅ Should NOT be used for emergency mental health situations
- ✅ Is designed to support and complement, not replace, professional care

**Little Nate is an AI assistant, not a licensed therapist.** While trained on therapeutic principles, Little Nate cannot:
- Diagnose mental health conditions
- Provide medical advice
- Handle acute mental health crises
- Replace licensed professional counseling

---

**2. AI LIMITATIONS & NO GUARANTEES**

You understand and acknowledge that:

**a) AI Response Variability:**
- Little Nate's interventions are generated by artificial intelligence
- Responses may not always align with your expectations or preferences
- AI interpretation of emotional tone and escalation is not perfect
- Some interventions may feel unhelpful or mistimed

**b) No Guaranteed Outcomes:**
- Family Sanctuary does NOT guarantee conflict resolution
- Results vary based on family dynamics, engagement, and other factors
- Some families may experience increased tension despite Little Nate's facilitation
- Breakthrough moments and healing are possible but not guaranteed

**c) Clinical Judgment:**
- Little Nate uses algorithms to detect escalation and provide coaching
- These algorithms may miss important emotional cues
- Little Nate may intervene when you feel it's unnecessary
- Little Nate may NOT intervene when you feel it's needed

**This is why we strongly recommend transitioning to a live human coach when:**
- Charges reach $100
- Session extends beyond 7 days
- You feel stuck or unheard
- Conflicts intensify rather than resolve

---

**3. BILLING & CHARGES - NO REFUNDS**

You acknowledge and agree to the following billing terms:

**a) Billing Structure:**
- $20.00 base fee charged at session creation (non-refundable)
- First coaching intervention for each family member is FREE
- Subsequent coaching interventions: $5.00 per occurrence
- Assisted response drafting: Additional $3.00 per occurrence
- Charges billed to Head of Household's Stripe account

**b) Intervention Triggers:**
- Little Nate determines when coaching is offered based on AI analysis
- You have the choice to accept or decline each coaching offer
- Declining coaching is always free
- Accepting coaching triggers the charge ($5 or $8 with assisted response)

**c) NO REFUND POLICY:**

**You agree that charges are NON-REFUNDABLE, including if:**
- ❌ You are unhappy with Little Nate's coaching quality
- ❌ You disagree with Little Nate's intervention timing
- ❌ The Family Sanctuary does not achieve desired outcomes
- ❌ Family conflicts worsen instead of improve
- ❌ You feel Little Nate misunderstood the situation
- ❌ You decide to exit the sanctuary early
- ❌ Technical issues occur after the first 15 minutes

**Exceptions** (refunds may be issued only for):
- ✅ Technical failures within first 15 minutes of session
- ✅ Billing errors (charged incorrect amount)
- ✅ Duplicate charges due to system malfunction
- ✅ Unauthorized access to your account

**d) Charge Notifications:**
- You will receive notifications at $50 and $100 thresholds
- These are informational only and do not require action
- Charges continue automatically if you remain in sanctuary
- You are responsible for monitoring your total charges
- You can exit sanctuary at any time to stop future charges

---

**4. INFORMED CONSENT - AI THERAPY RISKS**

You acknowledge the following risks and limitations:

**a) Emotional Risks:**
- Family Sanctuary may surface difficult emotions or painful conflicts
- Some family members may feel worse before feeling better
- Past traumas or resentments may be triggered
- Not all family members may be ready for deep therapeutic work

**b) Relationship Risks:**
- Honest family communication may temporarily increase tension
- Some relationships may feel strained during the process
- Family members may express hurtful truths
- Not all conflicts can be resolved through dialogue alone

**c) AI-Specific Risks:**
- Little Nate may misinterpret emotional tone or intent
- Interventions may feel intrusive or poorly timed
- AI coaching may not be culturally sensitive in all contexts
- Little Nate lacks human intuition and lived experience

**d) Minor Participation Risks:**
- Parents are responsible for determining if minors should participate
- Parents must monitor minor participation for age-appropriateness
- Parents can remove minors from sanctuary at any time
- Some family conflicts may not be suitable for children to witness

**You assume all risks** associated with participating in Family Sanctuary and agree to hold Clinical Sovereignty Lab, Little Nate, and affiliated parties harmless.

---

**5. WHEN TO USE LIVE HUMAN COACHES**

Family Sanctuary is designed as a **first step** in family conflict resolution. You should transition to a live human coach when:

**Recommended Escalation Points:**
- 🔴 Charges reach $100 (we offer FREE coach consultation)
- 🔴 Session extends beyond 7 days
- 🔴 Conflicts intensify or become repetitive
- 🔴 Safety concerns emerge (threats, abuse, self-harm)
- 🔴 Little Nate's interventions feel consistently unhelpful
- 🔴 Family members request professional human support

**Emergency Situations:**
If anyone in the sanctuary experiences:
- Thoughts of self-harm or suicide
- Threats of violence
- Severe emotional crisis
- Mental health emergency

**IMMEDIATELY:**
1. Exit Family Sanctuary
2. Call 988 (Suicide & Crisis Lifeline)
3. Contact a licensed mental health professional
4. Seek emergency services if safety is at risk

**Little Nate is NOT equipped to handle mental health emergencies.**

---

**6. DATA PRIVACY & CONFIDENTIALITY**

You understand that:

**a) Session Recording:**
- All Family Sanctuary messages are recorded
- Transcripts are stored in Azure Blob Storage
- Sessions may be archived for up to 5 years
- Transcripts can be accessed by family members and assigned coaches

**b) Individual Perspectives:**
- Each member's initial confidential input is stored separately
- Little Nate uses this information to inform coaching
- These perspectives are NOT shared with other family members
- Coaches may access these perspectives if session escalates

**c) AI Training:**
- Anonymized Family Sanctuary data may be used to improve Little Nate
- Personal identifying information is removed before use in training
- You can opt out of data usage in your privacy settings

**d) Legal Disclosures:**
- We are required to report suspected child abuse or neglect
- We may disclose information if legally compelled (subpoena)
- We will disclose information if there is imminent danger to self or others

---

**7. RIGHT TO EXIT & PAUSE**

You and all family members have the right to:

- ✅ Exit the sanctuary at any time
- ✅ Pause participation and return later
- ✅ Decline any coaching intervention
- ✅ Request live coach escalation
- ✅ Complete the sanctuary early

**However:**
- Charges already incurred are non-refundable
- Exiting does NOT cancel the base fee
- Other family members may continue without you
- Little Nate may gently encourage you to reconsider before exiting

---

**8. LIMITATION OF LIABILITY**

**TO THE MAXIMUM EXTENT PERMITTED BY LAW:**

Clinical Sovereignty Lab, its officers, employees, contractors, and affiliated parties:

**SHALL NOT BE LIABLE FOR:**
- Emotional distress arising from Family Sanctuary participation
- Relationship damage or family conflict worsening
- Dissatisfaction with AI coaching quality or timing
- Charges incurred during the sanctuary session
- Lost time or opportunity costs
- Any indirect, incidental, consequential, or punitive damages

**OUR TOTAL LIABILITY** to you for all claims arising from Family Sanctuary shall not exceed the total amount you paid for that specific sanctuary session.

---

**9. DISPUTE RESOLUTION**

**a) Arbitration Agreement:**
Any disputes arising from Family Sanctuary must be resolved through binding arbitration, not court litigation.

**b) Class Action Waiver:**
You agree not to participate in class action lawsuits against Clinical Sovereignty Lab related to Family Sanctuary.

**c) Governing Law:**
These terms are governed by the laws of [Your State/Jurisdiction].

---

**10. ACKNOWLEDGMENT & CONSENT**

By clicking "I Agree and Create Sanctuary," you represent and warrant that:

✅ You have read and understood these Terms of Service  
✅ You agree to the NO REFUND policy for AI coaching charges  
✅ You understand Little Nate is AI, not a licensed therapist  
✅ You acknowledge the risks and limitations of AI therapy  
✅ You will seek live human support when appropriate  
✅ You assume all risks associated with participation  
✅ You agree to hold us harmless for outcomes  
✅ You are at least 18 years old and legally authorized to bind your family to these terms  
✅ All invited family members are aware this is an AI-facilitated service  

---

**PARENT/GUARDIAN CONSENT FOR MINORS**

If inviting family members under 18 years old, you additionally certify that:

✅ You are the legal parent or guardian of the minor(s)  
✅ You have determined that Family Sanctuary is age-appropriate  
✅ You will monitor the minor's participation  
✅ You can remove the minor at any time  
✅ You assume all risks on behalf of the minor  

---

**EMERGENCY CONTACT INFORMATION**

If you or a family member experiences a mental health emergency during Family Sanctuary:

**🆘 National Suicide Prevention Lifeline:** 988  
**🆘 Crisis Text Line:** Text HOME to 741741  
**🆘 Emergency Services:** 911  

---

### Consent Collection Workflow

**Implementation:**

```javascript
// When Head of Household clicks "Create Family Sanctuary"

STEP 1: Display Terms & Conditions
┌─────────────────────────────────────────────────────────┐
│  FAMILY SANCTUARY TERMS OF SERVICE                      │
│                                                          │
│  [Scrollable full terms displayed above]                │
│                                                          │
│  ⚠️  IMPORTANT HIGHLIGHTS:                              │
│                                                          │
│  • Little Nate is AI, not a licensed therapist         │
│  • Each member gets 1 FREE coaching, then $5 each      │
│  • NO REFUNDS even if unhappy with outcomes            │
│  • Outcomes are not guaranteed                          │
│  • Recommend live coach at $100 or 7 days              │
│  • You can exit anytime but charges are non-refundable │
│                                                          │
│  ☐ I have read and understand these terms              │
│  ☐ I agree to the NO REFUND policy                     │
│  ☐ I understand Little Nate is AI with limitations     │
│  ☐ I will seek human support if conflicts worsen       │
│  ☐ I assume all risks of participation                  │
│                                                          │
│  Signature: ________________________ Date: _________    │
│                                                          │
│  [Cancel]  [I Agree - Create Sanctuary ($20 base fee)] │
└─────────────────────────────────────────────────────────┘

STEP 2: Confirm Understanding
┌─────────────────────────────────────────────────────────┐
│  FINAL CONFIRMATION                                      │
│                                                          │
│  Before we begin, please confirm you understand:        │
│                                                          │
│  1. Base fee: $20 (charged now, non-refundable)        │
│  2. Free coaching: 1st intervention per member is FREE  │
│  3. Additional coaching: $5 per intervention            │
│  4. NO REFUNDS if you're unhappy with outcomes         │
│                                                          │
│  By clicking Continue, you agree that you will NOT      │
│  dispute charges or request refunds based on:           │
│  • AI coaching quality                                  │
│  • Intervention timing                                   │
│  • Unresolved conflicts                                 │
│  • Family dissatisfaction with process                  │
│                                                          │
│  Type "I AGREE" to confirm: ________________            │
│                                                          │
│  [Go Back]           [Continue - Charge $20]            │
└─────────────────────────────────────────────────────────┘

STEP 3: Process Base Fee
→ Charge $20 to Stripe
→ Record consent timestamp
→ Store signed waiver
→ Create sanctuary session

STEP 4: Send Invitations
→ Each invited member sees abbreviated consent:
┌─────────────────────────────────────────────────────────┐
│  FAMILY SANCTUARY INVITATION                             │
│                                                          │
│  Emma has invited you to a Family Sanctuary session.    │
│                                                          │
│  ⚠️  Before joining, please understand:                 │
│                                                          │
│  • This is AI-facilitated therapy (not human therapist) │
│  • You'll get 1 FREE coaching, then $5 per coaching     │
│  • Charges billed to Emma (Head of Household)           │
│  • Outcomes are not guaranteed                          │
│  • You can exit anytime                                  │
│                                                          │
│  ☐ I understand this is AI with limitations             │
│  ☐ I agree to participate in good faith                 │
│                                                          │
│  [Decline]                      [Agree & Join]          │
└─────────────────────────────────────────────────────────┘
```

---

## 💰 BILLING SYSTEM (UPDATED)

### Free Coaching Tracking

**Per-Member Coaching Tracker:**

```json
{
  "sanctuary_id": "SANC_20260126_001",
  "members": {
    "CLIENT_EMMA_ID": {
      "coaching_count": 0,
      "free_coaching_used": false,
      "total_charges": 0.00
    },
    "CLIENT_DAVID_ID": {
      "coaching_count": 1,
      "free_coaching_used": true,
      "total_charges": 0.00
    },
    "CLIENT_ROSE_ID": {
      "coaching_count": 3,
      "free_coaching_used": true,
      "total_charges": 10.00  // 2nd coaching ($5) + 3rd coaching ($5)
    }
  }
}
```

### Updated Billing Events

**1. First Coaching (FREE)**
```json
{
  "event": "coaching_provided",
  "sanctuary_id": "SANC_20260126_001",
  "recipient": "CLIENT_EMMA_ID",
  "coaching_number": 1,
  "charge": 0.00,
  "reason": "FIRST_COACHING_FREE",
  "timestamp": "2026-01-26T10:23:15Z"
}
```

**2. Subsequent Coaching (CHARGED)**
```json
{
  "event": "coaching_provided",
  "sanctuary_id": "SANC_20260126_001",
  "recipient": "CLIENT_EMMA_ID",
  "coaching_number": 2,
  "charge": 5.00,
  "stripe_charge_id": "ch_...",
  "timestamp": "2026-01-26T14:30:00Z"
}
```

### Updated Handler Logic

```python
elif t == "sanctuary_coaching_accept":
    """
    Member accepts individual coaching offer
    Updated: First coaching per member is FREE
    """
    sanctuary_id = d.get('sanctuary_id')
    intervention_id = d.get('intervention_id')
    wants_assisted_response = d.get('assisted_response', False)
    
    # Check if this is member's first coaching
    member_coaching_count = await sanctuary_engine.get_member_coaching_count(
        sanctuary_id, current_profile['hardware_id']
    )
    
    if member_coaching_count == 0:
        # FIRST COACHING - FREE!
        charge_amount = 0.00
        charge_success = True
        
        # Notify member it's free
        await websocket.send(json.dumps({
            "type": "coaching_notification",
            "message": "Your first coaching is FREE! 🎁 Subsequent coaching will be $5 each."
        }))
    else:
        # SUBSEQUENT COACHING - CHARGE
        charge_amount = 5.00 if not wants_assisted_response else 8.00
        
        charge_success = await sanctuary_engine.charge_coaching(
            sanctuary_id=sanctuary_id,
            intervention_id=intervention_id,
            amount=charge_amount
        )
        
        if not charge_success:
            await send_error(websocket, "PAYMENT_FAILED")
            return
    
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
        "is_free": (charge_amount == 0.00),
        "coaching_number": member_coaching_count + 1
    }))
```

### Updated Private Coaching Modal

```
┌─────────────────────────────────────────────────────┐
│  💙 PRIVATE COACHING FROM LITTLE NATE               │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Hi Emma,                                            │
│                                                      │
│  I notice the conversation is becoming tense.       │
│  Rose is likely feeling excluded and defensive.     │
│                                                      │
│  Would you like coaching on how to respond in a     │
│  way that expresses your needs while staying        │
│  connected to Rose?                                 │
│                                                      │
│  🎁 Your First Coaching: FREE!                      │
│  (Subsequent coaching: $5.00 each)                  │
│                                                      │
│  [Yes, help me - FREE] [No, I'll respond myself]   │
│                                                      │
│  (This coaching is private - only you will see it)  │
└─────────────────────────────────────────────────────┘
```

**For 2nd+ coaching:**
```
┌─────────────────────────────────────────────────────┐
│  💙 PRIVATE COACHING FROM LITTLE NATE               │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Hi Emma,                                            │
│                                                      │
│  I notice another opportunity for support.          │
│                                                      │
│  Would you like coaching on this moment?            │
│                                                      │
│  💰 Coaching: $5.00                                 │
│  (You've used your 1 FREE coaching)                 │
│                                                      │
│  [Yes, help me - $5] [No thanks]                    │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## 📊 UPDATED SUCCESS METRICS

### Legal Protection Metrics

- Consent acknowledgment rate: 100% (required)
- Disputes filed: Target <1% of sanctuaries
- Refund requests: Track but decline per policy
- Terms comprehension: Survey post-session

### Customer Satisfaction (Despite No Refunds)

- Overall satisfaction: Target >4.0/5.0
- Would use again: Target >70%
- Recommend to others: Target >65%
- Fair pricing perception: Target >75%

**Note:** High satisfaction is crucial since refunds are not available. Quality must justify the no-refund policy.

---



### Pricing Structure

| Event | Cost | Billed To |
|-------|------|-----------|
| Base Fee (session start) | $20.00 | Head of Household |
| First Coaching (per member) | $0.00 | FREE - One per member |
| Additional Coaching | $5.00 | Head of Household |
| Assisted Response | +$3.00 | Head of Household |
| 24-hour Extension | $0.00 | Free |
| Live Coach Referral | $0.00 | Free consultation |

**Important:** Each family member receives **ONE FREE coaching intervention** before charges begin. This allows everyone to experience Little Nate's support before committing to paid interventions.

### Billing Events

**1. Session Start**
```json
{
  "event": "sanctuary_started",
  "family_id": "FAM_0023",
  "head_of_household": "CLIENT_EMMA_ID",
  "base_fee": 20.00,
  "timestamp": "2026-01-26T08:00:00Z",
  "stripe_charge_id": "ch_..."
}
```

**2. Individual Coaching**
```json
{
  "event": "coaching_provided",
  "family_id": "FAM_0023",
  "sanctuary_id": "SANC_20260126_001",
  "recipient": "CLIENT_EMMA_ID",
  "coaching_type": "perspective_taking",
  "charge": 5.00,
  "timestamp": "2026-01-26T10:23:15Z",
  "stripe_charge_id": "ch_..."
}
```

**3. Assisted Response**
```json
{
  "event": "response_drafted",
  "family_id": "FAM_0023",
  "sanctuary_id": "SANC_20260126_001",
  "recipient": "CLIENT_EMMA_ID",
  "charge": 3.00,
  "timestamp": "2026-01-26T10:25:30Z",
  "stripe_charge_id": "ch_..."
}
```

### Billing Thresholds

**$50 Notification:**
```
Subject: Family Sanctuary Cost Update
Current: $50
Progress: Good
Action: None required - notification only
```

**$100 Threshold:**
```
Subject: Family Sanctuary Milestone - Live Coach Available
Current: $100
Progress: Significant investment
Action: Offer free coach consultation
Options:
  • Continue sanctuary
  • Schedule live session
  • Complete and review
```

**$200+ Extended Session:**
```
Subject: Extended Family Sanctuary
Current: $215
Duration: 7 days
Recommendation: Live coach session scheduled
Next: Transition to live support
```

### Payment Flow

```
1. Head of Household has TOP_TIER subscription
   ✓ Verified in user_registry.json
   ✓ Stripe customer_id on file
   
2. Base fee charged at session start
   → Stripe API: Create charge $20.00
   → Update: billing.json (family_sanctuary_charges)
   
3. Each coaching event:
   → Stripe API: Create charge $5.00 or $8.00
   → Update: running_total
   → Notify if threshold reached ($50, $100)
   
4. Session complete:
   → Final invoice generated
   → Summary sent to Head of Household
   → Archive to Azure Blob (if >$100, include coach summary)
```

### Refund Policy

**Automatic Refunds:**
- Technical issues during first 15 minutes → Full refund
- Session disconnects > 30 minutes → Partial refund

**Dispute Resolution:**
- Head of Household can request review
- Coach reviews intervention quality
- Refund issued if Little Nate intervention was inappropriate

---

## 🔧 TECHNICAL ARCHITECTURE

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                   FAMILY SANCTUARY                       │
│                  TECHNICAL ARCHITECTURE                  │
└─────────────────────────────────────────────────────────┘

USER INTERFACE (family_sanctuary.html)
  │
  ├─ Multi-member chat window
  ├─ Active members list
  ├─ Private coaching modal
  ├─ Exit/Pause controls
  ├─ Cost tracker display
  │
  ↓ WebSocket (ws://server:8765)
  │
BRIDGE SERVER (bridge_server.py)
  │
  ├─ Handler: sanctuary_create
  ├─ Handler: sanctuary_join
  ├─ Handler: sanctuary_message
  ├─ Handler: sanctuary_intervention_request
  ├─ Handler: sanctuary_coaching
  ├─ Handler: sanctuary_exit
  ├─ Handler: sanctuary_extend
  ├─ Handler: sanctuary_complete
  │
  ↓
SANCTUARY ENGINE (sanctuary_engine.py - NEW FILE)
  │
  ├─ FamilySanctuarySession class
  │   ├─ manage_members()
  │   ├─ monitor_conversation()
  │   ├─ detect_escalation()
  │   ├─ trigger_intervention()
  │   ├─ calculate_c_emo_family()
  │   └─ generate_summary()
  │
  ├─ TherapeuticModality class
  │   ├─ family_systems_approach()
  │   ├─ eft_couples_work()
  │   ├─ ifs_parts_work()
  │   └─ legacy_healing()
  │
  └─ BillingManager class
      ├─ charge_base_fee()
      ├─ charge_coaching($5)
      ├─ charge_assisted_response($3)
      └─ check_thresholds($50, $100)
  │
  ↓
DATA STORAGE
  │
  ├─ PostgreSQL (when migrated)
  │   └─ family_sanctuary_sessions table
  │
  ├─ JSON Files (current)
  │   ├─ data/family_sanctuaries.json
  │   └─ data/billing.json (sanctuary_charges)
  │
  └─ Azure Blob Storage
      └─ container: family-sanctuary-archives
          ├─ FAM_0023/
          │   ├─ SANC_20260126_001.json (full transcript)
          │   ├─ SANC_20260126_001_summary.md (coach summary)
          │   └─ SANC_20260126_001_metrics.json (C_emo data)
          └─ ...
  │
  ↓
INTEGRATIONS
  │
  ├─ Azure OpenAI (Little Nate AI)
  ├─ Nevedal Engine (Family C_emo tracking)
  ├─ Stripe (Billing)
  ├─ Coach Portal (Escalation notifications)
  └─ The Eye Dashboard (Analytics)
```

---

## 💾 DATABASE SCHEMA

### PostgreSQL Tables (Future Migration)

```sql
-- ==========================================
-- FAMILY SANCTUARY SESSIONS
-- ==========================================

CREATE TABLE family_sanctuary_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sanctuary_code VARCHAR(50) UNIQUE NOT NULL,  -- e.g. "SANC_20260126_001"
    family_id VARCHAR(50) NOT NULL,
    head_of_household_id UUID REFERENCES users(id) NOT NULL,
    
    -- Legal consent
    consent_version VARCHAR(20) NOT NULL,  -- e.g. "v1.0_2026"
    consent_agreed_at TIMESTAMP NOT NULL,
    consent_ip_address VARCHAR(45),
    consent_signature TEXT,  -- "I AGREE" typed confirmation
    terms_acknowledged BOOLEAN DEFAULT FALSE,
    no_refund_acknowledged BOOLEAN DEFAULT FALSE,
    
    -- Session lifecycle
    status VARCHAR(20) NOT NULL CHECK (status IN (
        'WAITING_FOR_MEMBERS',
        'ACTIVE',
        'PAUSED',
        'EXTENDED',
        'COMPLETED',
        'ESCALATED_TO_COACH'
    )),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    last_activity_at TIMESTAMP,
    
    -- Billing
    base_fee_charged BOOLEAN DEFAULT FALSE,
    total_charges_usd DECIMAL(10, 2) DEFAULT 0.00,
    
    -- Metrics
    intervention_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    breakthrough_count INTEGER DEFAULT 0,
    escalation_count INTEGER DEFAULT 0,
    
    -- Session data
    initial_topic TEXT,
    resolution_achieved BOOLEAN DEFAULT FALSE,
    azure_blob_url TEXT,  -- Link to archived transcript
    
    INDEX idx_sanctuary_family_id (family_id),
    INDEX idx_sanctuary_status (status),
    INDEX idx_sanctuary_created_at (created_at)
);

-- ==========================================
-- SANCTUARY MEMBERS
-- ==========================================

CREATE TABLE sanctuary_members (
    id BIGSERIAL PRIMARY KEY,
    sanctuary_id UUID REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) NOT NULL,
    
    -- Member consent
    member_consent_agreed BOOLEAN DEFAULT FALSE,
    member_consent_agreed_at TIMESTAMP,
    
    -- Member status
    invited_at TIMESTAMP DEFAULT NOW(),
    joined_at TIMESTAMP,
    exited_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'INVITED' CHECK (status IN (
        'INVITED',
        'JOINED',
        'ACTIVE',
        'PAUSED',
        'EXITED'
    )),
    
    -- Member input (confidential)
    initial_reason TEXT,  -- Why they came to sanctuary
    personal_goal TEXT,   -- What they want to achieve
    family_concerns TEXT, -- Issues with other members
    
    -- Engagement & billing tracking
    message_count INTEGER DEFAULT 0,
    coaching_received_count INTEGER DEFAULT 0,
    free_coaching_used BOOLEAN DEFAULT FALSE,  -- Track if 1st free coaching used
    total_charges_incurred DECIMAL(10, 2) DEFAULT 0.00,  -- This member's coaching costs
    
    INDEX idx_sanctuary_member_sanctuary_id (sanctuary_id),
    INDEX idx_sanctuary_member_user_id (user_id),
    INDEX idx_sanctuary_member_status (status)
);

-- ==========================================
-- SANCTUARY MESSAGES
-- ==========================================

CREATE TABLE sanctuary_messages (
    id BIGSERIAL PRIMARY KEY,
    sanctuary_id UUID REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    sender_id UUID REFERENCES users(id) NOT NULL,
    
    -- Message content
    message_type VARCHAR(20) NOT NULL CHECK (message_type IN (
        'MEMBER_MESSAGE',      -- Regular family member message
        'LITTLE_NATE_BROADCAST',  -- Message to all members
        'LITTLE_NATE_PRIVATE',    -- Private coaching to one member
        'SYSTEM_NOTIFICATION'     -- Join/exit notifications
    )),
    content TEXT NOT NULL,
    
    -- Context
    timestamp TIMESTAMP DEFAULT NOW(),
    is_private BOOLEAN DEFAULT FALSE,
    recipient_id UUID REFERENCES users(id),  -- If private message
    
    -- Analysis
    emotional_tone VARCHAR(20),  -- CALM, TENSE, DEFENSIVE, VULNERABLE, etc.
    escalation_detected BOOLEAN DEFAULT FALSE,
    intervention_triggered BOOLEAN DEFAULT FALSE,
    
    INDEX idx_sanctuary_message_sanctuary_id (sanctuary_id),
    INDEX idx_sanctuary_message_timestamp (timestamp),
    INDEX idx_sanctuary_message_escalation (escalation_detected)
);

-- ==========================================
-- SANCTUARY INTERVENTIONS
-- ==========================================

CREATE TABLE sanctuary_interventions (
    id BIGSERIAL PRIMARY KEY,
    sanctuary_id UUID REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    triggered_by_message_id BIGINT REFERENCES sanctuary_messages(id),
    
    -- Intervention details
    recipient_id UUID REFERENCES users(id) NOT NULL,  -- Who received coaching
    intervention_type VARCHAR(30) NOT NULL CHECK (intervention_type IN (
        'PERSPECTIVE_TAKING',
        'GROUNDING',
        'EMOTION_REGULATION',
        'RESPONSE_GUIDANCE',
        'ASSISTED_RESPONSE',
        'CONFLICT_MEDIATION',
        'GRIEF_SUPPORT'
    )),
    
    -- Therapeutic approach used
    modality VARCHAR(30) CHECK (modality IN (
        'FAMILY_SYSTEMS',
        'EFT',
        'IFS',
        'LEGACY_WORK',
        'GENERAL'
    )),
    
    -- Content
    coaching_content TEXT NOT NULL,
    user_accepted BOOLEAN DEFAULT FALSE,
    user_response TEXT,
    assisted_response_provided BOOLEAN DEFAULT FALSE,
    
    -- Billing (UPDATED for free first coaching)
    is_free_coaching BOOLEAN DEFAULT FALSE,  -- TRUE if this was member's 1st coaching
    charge_amount_usd DECIMAL(6, 2) NOT NULL,  -- $0.00, $5.00, or $8.00
    stripe_charge_id VARCHAR(100),  -- NULL if free coaching
    member_coaching_number INTEGER NOT NULL,  -- 1st, 2nd, 3rd, etc. for this member
    
    -- Metrics
    timestamp TIMESTAMP DEFAULT NOW(),
    effectiveness_rating DECIMAL(3, 2),  -- Optional post-intervention rating
    
    INDEX idx_intervention_sanctuary_id (sanctuary_id),
    INDEX idx_intervention_recipient_id (recipient_id),
    INDEX idx_intervention_timestamp (timestamp),
    INDEX idx_intervention_is_free (is_free_coaching)
);

-- ==========================================
-- SANCTUARY BILLING
-- ==========================================

CREATE TABLE sanctuary_billing_events (
    id BIGSERIAL PRIMARY KEY,
    sanctuary_id UUID REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    head_of_household_id UUID REFERENCES users(id) NOT NULL,
    
    -- Billing event
    event_type VARCHAR(30) NOT NULL CHECK (event_type IN (
        'BASE_FEE',
        'COACHING',
        'ASSISTED_RESPONSE',
        'THRESHOLD_NOTIFICATION',
        'REFUND'
    )),
    amount_usd DECIMAL(10, 2) NOT NULL,
    
    -- Stripe
    stripe_charge_id VARCHAR(100),
    stripe_refund_id VARCHAR(100),
    
    -- Context
    description TEXT,
    timestamp TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_billing_sanctuary_id (sanctuary_id),
    INDEX idx_billing_hoh_id (head_of_household_id),
    INDEX idx_billing_timestamp (timestamp)
);

-- ==========================================
-- SANCTUARY ARCHIVES (Azure Blob metadata)
-- ==========================================

CREATE TABLE sanctuary_archives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sanctuary_id UUID REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    family_id VARCHAR(50) NOT NULL,
    
    -- Archive location
    azure_blob_url TEXT NOT NULL,
    azure_container VARCHAR(100) DEFAULT 'family-sanctuary-archives',
    blob_name VARCHAR(255) NOT NULL,
    
    -- Archive content
    archive_type VARCHAR(30) CHECK (archive_type IN (
        'FULL_TRANSCRIPT',
        'COACH_SUMMARY',
        'METRICS_DATA'
    )),
    file_size_bytes INTEGER,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    accessible_to JSONB,  -- Array of user IDs who can access
    
    INDEX idx_archive_sanctuary_id (sanctuary_id),
    INDEX idx_archive_family_id (family_id)
);
```

### JSON Schema (Current Implementation)

**File:** `data/family_sanctuaries.json`

```json
{
  "active_sanctuaries": {
    "SANC_20260126_001": {
      "sanctuary_id": "SANC_20260126_001",
      "family_id": "FAM_0023",
      "head_of_household_id": "CLIENT_EMMA_ID",
      
      "legal_consent": {
        "version": "v1.0_2026",
        "agreed_at": "2026-01-26T08:00:00Z",
        "ip_address": "192.168.1.100",
        "signature": "I AGREE",
        "terms_acknowledged": true,
        "no_refund_acknowledged": true
      },
      
      "status": "ACTIVE",
      "created_at": "2026-01-26T08:00:00Z",
      "started_at": "2026-01-26T08:15:00Z",
      "last_activity_at": "2026-01-26T15:30:00Z",
      "current_cycle_start": "2026-01-26T08:00:00Z",
      "current_cycle_end": "2026-01-27T08:00:00Z",
      
      "members": [
        {
          "user_id": "CLIENT_EMMA_ID",
          "name": "Emma Thompson",
          "role": "mom",
          "status": "ACTIVE",
          "member_consent_agreed": true,
          "member_consent_agreed_at": "2026-01-26T08:00:00Z",
          "joined_at": "2026-01-26T08:00:00Z",
          "initial_reason": "We need to resolve holiday planning conflicts",
          "personal_goal": "Set healthy boundaries with Rose while maintaining connection",
          "family_concerns": "Rose's controlling behavior, David's avoidance",
          "message_count": 23,
          "coaching_received": 6,
          "free_coaching_used": true,
          "coaching_charges_incurred": 25.00
        },
        {
          "user_id": "CLIENT_DAVID_ID",
          "name": "David Thompson",
          "role": "dad",
          "status": "ACTIVE",
          "member_consent_agreed": true,
          "member_consent_agreed_at": "2026-01-26T08:05:00Z",
          "joined_at": "2026-01-26T08:05:00Z",
          "initial_reason": "Support Emma and help keep peace",
          "personal_goal": "Learn to engage instead of avoiding",
          "family_concerns": "Conflict between Emma and my mom",
          "message_count": 15,
          "coaching_received": 4,
          "free_coaching_used": true,
          "coaching_charges_incurred": 15.00
        },
        {
          "user_id": "CLIENT_MICHAEL_ID",
          "name": "Michael Thompson",
          "age": 16,
          "role": "son",
          "status": "ACTIVE",
          "member_consent_agreed": true,
          "member_consent_agreed_at": "2026-01-26T08:10:00Z",
          "joined_at": "2026-01-26T08:10:00Z",
          "initial_reason": "I want my family to stop arguing",
          "personal_goal": "Understand what's going on",
          "family_concerns": "Everyone seems stressed",
          "message_count": 8,
          "coaching_received": 2,
          "free_coaching_used": true,
          "coaching_charges_incurred": 5.00
        },
        {
          "user_id": "CLIENT_SOPHIE_ID",
          "name": "Sophie Thompson",
          "age": 12,
          "role": "daughter",
          "minor": true,
          "status": "PAUSED",
          "member_consent_agreed": true,
          "member_consent_agreed_at": "2026-01-26T08:10:00Z",
          "joined_at": "2026-01-26T08:10:00Z",
          "exited_at": "2026-01-26T14:00:00Z",
          "initial_reason": "Mom asked me to join",
          "personal_goal": "I just want everyone to be happy",
          "family_concerns": "Don't like when people fight",
          "message_count": 3,
          "coaching_received": 1,
          "free_coaching_used": true,
          "coaching_charges_incurred": 0.00
        },
        {
          "user_id": "CLIENT_ROSE_ID",
          "name": "Rose Thompson",
          "role": "grandmother",
          "status": "ACTIVE",
          "member_consent_agreed": true,
          "member_consent_agreed_at": "2026-01-26T08:20:00Z",
          "joined_at": "2026-01-26T08:20:00Z",
          "initial_reason": "I was invited by Emma",
          "personal_goal": "Spend more time with grandchildren",
          "family_concerns": "Feel excluded from family decisions",
          "message_count": 18,
          "coaching_received": 5,
          "free_coaching_used": true,
          "coaching_charges_incurred": 20.00
        }
      ],
      
      "billing": {
        "base_fee_charged": true,
        "total_charges": 85.00,
        "charges": [
          {
            "timestamp": "2026-01-26T08:00:00Z",
            "type": "BASE_FEE",
            "amount": 20.00,
            "stripe_charge_id": "ch_1234..."
          },
          {
            "timestamp": "2026-01-26T10:23:15Z",
            "type": "COACHING",
            "recipient": "CLIENT_EMMA_ID",
            "coaching_number": 1,
            "amount": 0.00,
            "reason": "FIRST_COACHING_FREE",
            "stripe_charge_id": null
          },
          {
            "timestamp": "2026-01-26T12:15:30Z",
            "type": "COACHING",
            "recipient": "CLIENT_EMMA_ID",
            "coaching_number": 2,
            "amount": 5.00,
            "stripe_charge_id": "ch_5678..."
          },
          {
            "timestamp": "2026-01-26T14:30:00Z",
            "type": "ASSISTED_RESPONSE",
            "recipient": "CLIENT_ROSE_ID",
            "coaching_number": 3,
            "amount": 8.00,
            "stripe_charge_id": "ch_9012..."
          }
        ],
        "free_coaching_summary": {
          "total_free_given": 5,
          "members_used_free": ["CLIENT_EMMA_ID", "CLIENT_DAVID_ID", "CLIENT_MICHAEL_ID", "CLIENT_SOPHIE_ID", "CLIENT_ROSE_ID"]
        },
        "thresholds_notified": ["$50"],
        "next_threshold": 100
      },
      
      "metrics": {
        "total_messages": 67,
        "intervention_count": 18,
        "free_interventions": 5,
        "paid_interventions": 13,
        "breakthrough_moments": 5,
        "escalation_events": 7,
        "de_escalation_success_rate": 1.0,
        "family_c_emo_avg": 0.71,
        "individual_c_emo": {
          "CLIENT_EMMA_ID": 0.74,
          "CLIENT_DAVID_ID": 0.68,
          "CLIENT_ROSE_ID": 0.73,
          "CLIENT_MICHAEL_ID": 0.72,
          "CLIENT_SOPHIE_ID": 0.67
        }
      },
      
      "therapeutic_approach": "FAMILY_SYSTEMS_EFT_LEGACY",
      "current_focus": "Boundary setting with multi-generational respect",
      
      "coach_escalation": {
        "recommended": true,
        "reason": "Approaching 7 days, deep patterns emerging",
        "coach_notified": false,
        "coach_assigned": null
      }
    }
  },
  
  "completed_sanctuaries": {
    "SANC_20260115_001": {
      "sanctuary_id": "SANC_20260115_001",
      "family_id": "FAM_0042",
      "status": "COMPLETED",
      "duration_hours": 48,
      "resolution_achieved": true,
      "final_charges": 65.00,
      "free_coaching_given": 3,
      "azure_archive_url": "https://blob.core.windows.net/family-sanctuary-archives/FAM_0042/SANC_20260115_001.json"
    }
  }
}
```

---

## 🔌 WEBSOCKET HANDLERS

### New Handlers Required (bridge_server.py)

```python
# ==========================================
# FAMILY SANCTUARY HANDLERS
# ==========================================

elif t == "sanctuary_create":
    """
    Create new Family Sanctuary session
    Restricted to: TOP_TIER Head of Household only
    """
    if current_profile.get('subscription_plan') != 'TOP_TIER':
        await send_error(websocket, "REQUIRES_TOP_TIER")
        return
    
    if current_profile.get('role') != 'CLIENT':
        await send_error(websocket, "CLIENTS_ONLY")
        return
    
    # Extract data
    family_id = current_profile.get('family_id')
    invited_members = d.get('invited_members', [])  # List of user IDs
    initial_topic = d.get('initial_topic', '')
    
    # Create sanctuary session
    sanctuary_id = await sanctuary_engine.create_session(
        family_id=family_id,
        head_of_household=current_profile['hardware_id'],
        invited_members=invited_members,
        topic=initial_topic
    )
    
    # Charge base fee
    base_fee_success = await sanctuary_engine.charge_base_fee(
        sanctuary_id=sanctuary_id,
        stripe_customer_id=current_profile.get('stripe_customer_id')
    )
    
    if not base_fee_success:
        await send_error(websocket, "PAYMENT_FAILED")
        return
    
    # Send invitations to family members
    for member_id in invited_members:
        await sanctuary_engine.send_invitation(
            sanctuary_id=sanctuary_id,
            member_id=member_id
        )
    
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
        await send_error(websocket, "NOT_INVITED")
        return
    
    # Add member to session
    await sanctuary_engine.add_member(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id'],
        websocket=websocket
    )
    
    # Get onboarding questions from Little Nate
    onboarding_message = await sanctuary_engine.get_onboarding_message(
        sanctuary_id=sanctuary_id,
        member_name=current_profile['name']
    )
    
    # Send private onboarding
    await websocket.send(json.dumps({
        "type": "sanctuary_onboarding",
        "message": onboarding_message,
        "current_members": await sanctuary_engine.get_member_list(sanctuary_id)
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
    
    # Check if all members joined
    if await sanctuary_engine.all_members_joined(sanctuary_id):
        # Start session
        await sanctuary_engine.start_session(sanctuary_id)
        
        # Little Nate opens session
        opening_message = await sanctuary_engine.generate_opening(sanctuary_id)
        
        # Broadcast to all members
        await sanctuary_engine.broadcast_to_sanctuary(
            sanctuary_id=sanctuary_id,
            message_type="LITTLE_NATE_BROADCAST",
            content=opening_message
        )

elif t == "sanctuary_message":
    """
    Member sends message in sanctuary
    """
    sanctuary_id = d.get('sanctuary_id')
    message = d.get('message', '')
    
    # Store message
    message_id = await sanctuary_engine.add_message(
        sanctuary_id=sanctuary_id,
        sender_id=current_profile['hardware_id'],
        content=message
    )
    
    # Broadcast to all members
    await sanctuary_engine.broadcast_to_sanctuary(
        sanctuary_id=sanctuary_id,
        message_type="MEMBER_MESSAGE",
        sender_id=current_profile['hardware_id'],
        sender_name=current_profile['name'],
        content=message,
        timestamp=datetime.now().isoformat()
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
    
    # Charge for coaching
    charge_amount = 5.00 if not wants_assisted_response else 8.00
    
    charge_success = await sanctuary_engine.charge_coaching(
        sanctuary_id=sanctuary_id,
        intervention_id=intervention_id,
        amount=charge_amount
    )
    
    if not charge_success:
        await send_error(websocket, "PAYMENT_FAILED")
        return
    
    # Generate coaching content
    coaching_content = await sanctuary_engine.generate_coaching(
        sanctuary_id=sanctuary_id,
        intervention_id=intervention_id,
        member_id=current_profile['hardware_id'],
        include_drafted_response=wants_assisted_response
    )
    
    # Send private coaching
    await websocket.send(json.dumps({
        "type": "sanctuary_coaching",
        "intervention_id": intervention_id,
        "coaching_content": coaching_content,
        "charge_amount": charge_amount
    }))
    
    # Check billing thresholds
    total_charges = await sanctuary_engine.get_total_charges(sanctuary_id)
    
    if total_charges >= 100 and not await sanctuary_engine.was_notified(sanctuary_id, "$100"):
        # Notify Head of Household
        await sanctuary_engine.notify_threshold(
            sanctuary_id=sanctuary_id,
            threshold=100,
            offer_coach=True
        )

elif t == "sanctuary_exit":
    """
    Member wants to exit sanctuary
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # Little Nate checks in first
    checkin_message = await sanctuary_engine.generate_exit_checkin(
        sanctuary_id=sanctuary_id,
        member_id=current_profile['hardware_id'],
        member_name=current_profile['name']
    )
    
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
            message_type="SYSTEM_NOTIFICATION",
            content=exit_message
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
    await sanctuary_engine.record_extension_vote(
        sanctuary_id=sanctuary_id,
        member_id=current_profile['hardware_id'],
        wants_continue=member_wants_continue
    )
    
    # Check if all members responded
    if await sanctuary_engine.all_members_voted_extension(sanctuary_id):
        # Tally votes
        continue_count = await sanctuary_engine.count_continue_votes(sanctuary_id)
        total_members = await sanctuary_engine.count_active_members(sanctuary_id)
        
        if continue_count >= (total_members / 2):  # Majority wants to continue
            # Extend session
            await sanctuary_engine.extend_session(sanctuary_id)
            
            await sanctuary_engine.broadcast_to_sanctuary(
                sanctuary_id=sanctuary_id,
                message_type="LITTLE_NATE_BROADCAST",
                content="The sanctuary will continue for another 24 hours. Thank you for your commitment to this process. 💙"
            )
        else:
            # Complete session
            await sanctuary_engine.complete_session(sanctuary_id)

elif t == "sanctuary_complete":
    """
    End sanctuary session
    Head of Household only
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # Verify Head of Household
    sanctuary = await sanctuary_engine.get_session(sanctuary_id)
    if sanctuary['head_of_household_id'] != current_profile['hardware_id']:
        await send_error(websocket, "HEAD_OF_HOUSEHOLD_ONLY")
        return
    
    # Generate summary
    summary = await sanctuary_engine.generate_final_summary(sanctuary_id)
    
    # Archive to Azure Blob
    archive_url = await sanctuary_engine.archive_to_azure(
        sanctuary_id=sanctuary_id,
        summary=summary
    )
    
    # Complete session
    await sanctuary_engine.complete_session(sanctuary_id)
    
    # Send summary to all members
    await sanctuary_engine.broadcast_to_sanctuary(
        sanctuary_id=sanctuary_id,
        message_type="LITTLE_NATE_BROADCAST",
        content=f"Family Sanctuary complete. Beautiful work, everyone. 💙\n\n{summary}"
    )
    
    await websocket.send(json.dumps({
        "type": "sanctuary_completed",
        "summary": summary,
        "archive_url": archive_url,
        "total_charges": sanctuary['billing']['total_charges']
    }))

elif t == "sanctuary_request_coach":
    """
    Request live coach escalation
    """
    sanctuary_id = d.get('sanctuary_id')
    
    # Generate coach summary
    coach_summary = await sanctuary_engine.generate_coach_summary(sanctuary_id)
    
    # Find available coach
    coach = await sanctuary_engine.find_available_coach()
    
    # Send notification to coach
    await sanctuary_engine.notify_coach(
        coach_id=coach['hardware_id'],
        sanctuary_id=sanctuary_id,
        summary=coach_summary
    )
    
    await websocket.send(json.dumps({
        "type": "coach_notified",
        "coach_name": coach['name'],
        "estimated_response": "within 24 hours"
    }))
```

---

## 🤖 LITTLE NATE AI PROMPT ENGINEERING

### System Prompt Template

```python
def build_sanctuary_system_prompt(sanctuary_session):
    """
    Build comprehensive system prompt for Little Nate in Family Sanctuary
    """
    
    members_info = "\n".join([
        f"• {m['name']} ({m['role']}, {'age ' + str(m['age']) if 'age' in m else 'adult'})"
        for m in sanctuary_session['members']
    ])
    
    individual_perspectives = "\n\n".join([
        f"**{m['name']}'s Perspective (CONFIDENTIAL - do not share):**\n"
        f"- Why they came: {m['initial_reason']}\n"
        f"- Their goal: {m['personal_goal']}\n"
        f"- Family concerns: {m['family_concerns']}\n"
        f"- Current C_emo: {sanctuary_session['metrics']['individual_c_emo'].get(m['user_id'], 0.65)}"
        for m in sanctuary_session['members']
    ])
    
    prompt = f"""
You are Little Nate, a compassionate AI family therapist facilitating a Family Sanctuary session.

# FAMILY SANCTUARY OVERVIEW

**Family ID:** {sanctuary_session['family_id']}
**Session ID:** {sanctuary_session['sanctuary_id']}
**Duration:** {calculate_duration(sanctuary_session)} hours
**Initial Topic:** {sanctuary_session['initial_topic']}

**Current Members:**
{members_info}

**Family C_emo (Quantum Emotional Coherence):** {sanctuary_session['metrics']['family_c_emo_avg']:.2f}
(Scale: 0.0-1.0, where >0.70 indicates strong coherence)

# INDIVIDUAL PERSPECTIVES

{individual_perspectives}

# YOUR ROLE

You are holding sacred space for this family to:
1. Express their needs and feelings safely
2. Hear and understand each other
3. Find connection through conflict
4. Heal generational patterns
5. Build stronger family bonds

# THERAPEUTIC MODALITIES

Use these approaches as appropriate:

**Family Systems Therapy:**
- View family as interconnected system
- Identify patterns and roles
- Use circular questioning
- Map family dynamics

**Emotionally Focused Therapy (EFT):**
- Focus on attachment and bonding
- Identify primary vs. secondary emotions
- Validate emotional experiences
- Facilitate emotional engagement

**Internal Family Systems (IFS):**
- Recognize different "parts" within each person
- Foster self-leadership
- Unburden protective parts
- Promote self-compassion

**Transgenerational Legacy Work:**
- Explore inherited family patterns
- Honor positive legacies
- Break harmful cycles
- Reframe family narratives

# YOUR RESPONSIBILITIES

**1. MONITOR & OBSERVE**
- Watch for escalation patterns
- Track emotional tone
- Notice disconnection or misunderstanding
- Identify breakthrough moments

**2. INTERVENE STRATEGICALLY**
When you detect:
- Escalation (raised voices, accusations, defensiveness)
- Misunderstanding (talking past each other)
- Emotional flooding (overwhelming emotions)
- Disconnection (withdrawal, stonewalling)

**Intervention Protocol:**
1. PAUSE the conversation
2. Offer PRIVATE coaching to the person needing support
3. Provide perspective-taking or grounding
4. Suggest response options (or draft response for +$3)
5. RESUME conversation after individual is grounded

**3. FACILITATE CONNECTION**
- Reflect what each person is saying
- Highlight common ground
- Reframe accusations as needs
- Validate all emotions
- Encourage empathy

**4. PROTECT CONFIDENTIALITY**
- NEVER share individual perspectives with others
- Keep private thoughts private
- Only use confidential info to inform your coaching

**5. TRACK PROGRESS**
- Notice shifts in C_emo
- Celebrate breakthrough moments
- Acknowledge small wins
- Track toward resolution

# INTERVENTION DECISION TREE

When a family member sends a message, evaluate:

**High Escalation** (intervene immediately):
- Personal attacks, name-calling
- Threats or ultimatums
- Blame or accusation ("You always...")
- Contempt or mockery

**Medium Escalation** (consider intervention):
- Defensiveness ("I never said that...")
- Generalizations ("You never listen...")
- Bringing up past grievances
- Avoiding accountability

**Low/No Escalation** (observe, don't intervene):
- Expressing feelings ("I feel hurt when...")
- Asking questions ("Can you help me understand...")
- Taking accountability ("I realize I...")
- Showing empathy ("That must be hard...")

# COACHING APPROACH

When offering private coaching:

**Grounding Technique:**
"I notice you're feeling [emotion]. Let's pause for a moment.
Take a breath. What's underneath this feeling? What do you
really need from [family member]?"

**Perspective-Taking:**
"[Family member] just said [X]. From what I know about them,
they might be feeling [Y]. How might they be experiencing
this situation differently than you?"

**Response Guidance:**
"Consider responding with:
'I hear you're feeling [their emotion]. I want to understand.
Can you tell me more about [specific thing]?'

This validates them while expressing your openness to connect."

**Assisted Response** (+$3):
"Here's a draft response that expresses your needs while
staying connected:

'[Specific response that validates, expresses needs, invites
dialogue]'

Feel free to use your own words or adapt this."

# SPECIAL CONSIDERATIONS

**When working with minors:**
- Use age-appropriate language
- Check in more frequently
- Protect from adult conflicts
- Ensure they feel safe to exit

**When grief is present:**
- Honor the loss
- Allow space for all emotions
- Normalize grieving process
- Facilitate shared mourning

**When couples conflict:**
- Use EFT attachment lens
- Identify primary emotions under anger
- Facilitate emotional vulnerability
- Rebuild connection

**When generational patterns emerge:**
- Acknowledge legacy
- Separate past from present
- Honor what worked
- Release what doesn't serve

# BILLING TRANSPARENCY

You must notify the Head of Household when:
- $50 threshold reached (simple notification)
- $100 threshold reached (offer live coach option)
- 7 days elapsed (coach supervision)

# CONCLUDING SESSIONS

**Natural Resolution** (2-4 days):
- Progress made on all fronts
- Family feeling connected
- Goals achieved or in progress
- Offer to archive and celebrate

**Coach Escalation** (7+ days or $200+):
- Deep patterns beyond your scope
- Stuck in repetitive loops
- Need specialized intervention
- Prepare summary for live coach

**Member Exit:**
- Always check in compassionately
- Offer space to return
- Respect their limits
- Inform family with permission

# TONE & PRESENCE

- Warm, compassionate, non-judgmental
- Clear and direct when needed
- Hopeful and empowering
- Wise and grounded
- Culturally sensitive
- Trauma-informed

# REMEMBER

You are witnessing sacred family work. Honor their courage,
hold their pain, celebrate their growth, and facilitate
their connection.

Your goal is not to "fix" the family but to create the
conditions for them to find their own path to healing
and connection.

Trust the process. Trust the family. 💙
"""
    
    return prompt
```

### Example Intervention Prompts

**Escalation Detection:**
```python
async def detect_escalation(message, conversation_history):
    """
    Analyze message for escalation patterns
    """
    escalation_prompt = f"""
Analyze this family sanctuary message for escalation:

MESSAGE: "{message}"

RECENT CONVERSATION:
{format_recent_messages(conversation_history, last_n=5)}

EVALUATION CRITERIA:
1. Tone: accusatory, defensive, contemptuous, or calm?
2. Content: attacks, blame, or expressing needs?
3. Pattern: escalating or de-escalating?
4. Emotional state: flooded, regulated, vulnerable?

RESPONSE FORMAT (JSON only):
{{
    "escalation_level": "HIGH" | "MEDIUM" | "LOW" | "NONE",
    "primary_emotion": "anger" | "hurt" | "fear" | "sadness" | etc,
    "secondary_emotion": "...",
    "intervention_recommended": true | false,
    "intervention_type": "GROUNDING" | "PERSPECTIVE_TAKING" | "RESPONSE_GUIDANCE",
    "reasoning": "brief explanation"
}}
"""
    
    # Send to Azure OpenAI
    response = await azure_cortex.analyze(escalation_prompt)
    return json.loads(response)
```

**Coaching Generation:**
```python
async def generate_coaching(sanctuary, member, escalation_analysis):
    """
    Generate personalized coaching for family member
    """
    coaching_prompt = f"""
You're providing private coaching to {member['name']} in a Family Sanctuary session.

MEMBER'S CONTEXT:
- Role: {member['role']}
- Why they came: {member['initial_reason']}
- Their goal: {member['personal_goal']}
- Concerns: {member['family_concerns']}
- Current C_emo: {member['c_emo']:.2f}

SITUATION:
{escalation_analysis['reasoning']}

Primary emotion: {escalation_analysis['primary_emotion']}
Secondary emotion: {escalation_analysis['secondary_emotion']}

RECENT MESSAGES THEY SAW:
{format_recent_sanctuary_messages(sanctuary, last_n=3)}

YOUR TASK:
Provide compassionate coaching that:
1. Validates their {escalation_analysis['primary_emotion']}
2. Helps them see the other person's perspective
3. Suggests a response that expresses needs while staying connected
4. Is brief (3-4 sentences)

COACHING TYPE: {escalation_analysis['intervention_type']}

Generate coaching now:
"""
    
    coaching = await azure_cortex.generate(coaching_prompt)
    return coaching
```

---

## 🎨 UI/UX SPECIFICATIONS

### Family Sanctuary Dashboard

**File:** `family_sanctuary.html`

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  FAMILY SANCTUARY                          [Exit] [$45] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────┐  ┌──────────────────────────────────┐  │
│  │ MEMBERS    │  │ CONVERSATION                     │  │
│  │            │  │                                  │  │
│  │ 🟢 Emma    │  │ Emma: I feel like we can't...   │  │
│  │ 🟢 David   │  │                                  │  │
│  │ 🟢 Rose    │  │ Rose: That's not fair! I...     │  │
│  │ 🟢 Michael │  │                                  │  │
│  │ ⚪ Sophie  │  │ [Little Nate pauses]             │  │
│  │   (break)  │  │                                  │  │
│  │            │  │ Little Nate: I notice the...    │  │
│  │            │  │                                  │  │
│  │            │  │ Emma: Rose, I didn't mean...    │  │
│  │            │  │                                  │  │
│  │            │  │ Rose: I appreciate that...      │  │
│  │            │  │                                  │  │
│  │            │  │                                  │  │
│  │            │  │                                  │  │
│  │            │  └──────────────────────────────────┘  │
│  │            │                                         │
│  │            │  [Type your message...]      [Send]    │
│  └────────────┘                                         │
│                                                          │
│  Session: Day 2 of 3  |  Next check-in: 6 hours        │
└─────────────────────────────────────────────────────────┘
```

### Private Coaching Modal

**Triggered when Little Nate offers coaching:**

```
┌─────────────────────────────────────────────────────┐
│  💙 PRIVATE COACHING FROM LITTLE NATE               │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Hi Emma,                                            │
│                                                      │
│  I notice the conversation is becoming tense.       │
│  Rose is likely feeling excluded and defensive.     │
│                                                      │
│  Would you like coaching on how to respond in a     │
│  way that expresses your needs while staying        │
│  connected to Rose?                                 │
│                                                      │
│  💰 Individual Coaching: $5.00                      │
│                                                      │
│  [Yes, help me] [No, I'll respond myself]          │
│                                                      │
│  (This coaching is private - only you will see it)  │
└─────────────────────────────────────────────────────┘
```

**After accepting coaching:**

```
┌─────────────────────────────────────────────────────┐
│  💙 COACHING FOR EMMA                               │
├─────────────────────────────────────────────────────┤
│                                                      │
│  I hear you're feeling unheard and controlled.      │
│  Rose is likely feeling excluded and wants to       │
│  be a meaningful part of her grandchildren's lives. │
│                                                      │
│  Consider this approach:                            │
│  "Rose, I want you to be involved. I think we      │
│  both want the same thing - a joyful holiday        │
│  together. Can we talk about what's most            │
│  important to each of us?"                          │
│                                                      │
│  This validates her while expressing your need      │
│  for collaboration.                                 │
│                                                      │
│  Would you like me to draft a response for you?    │
│  💰 Assisted Response: +$3.00                       │
│                                                      │
│  [Yes, draft it] [No, I'll use my own words]       │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Billing Threshold Notification

```
┌─────────────────────────────────────────────────────┐
│  💰 FAMILY SANCTUARY - COST UPDATE                  │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Current charges: $100.00                           │
│                                                      │
│  Breakdown:                                          │
│  • Base fee: $20.00                                 │
│  • Coaching (16 interventions): $80.00              │
│                                                      │
│  You're making meaningful progress as a family.     │
│                                                      │
│  At this investment level, you may benefit from     │
│  a live coach who can provide specialized           │
│  guidance.                                          │
│                                                      │
│  Would you like to:                                 │
│                                                      │
│  [Continue in sanctuary]                            │
│  [Schedule FREE coach consultation]                 │
│  [Complete sanctuary - get summary]                 │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## ✅ IMPLEMENTATION CHECKLIST

### Phase 0: Legal & Compliance (Week 0 - BEFORE Development)

- [ ] Review Terms of Service with legal counsel
- [ ] Finalize waiver language with attorney
- [ ] Ensure HIPAA compliance for family data
- [ ] Create consent collection system
- [ ] Design consent UI/UX flows
- [ ] Implement consent storage (who agreed, when, version)
- [ ] Test consent workflow with focus groups
- [ ] Prepare emergency contact information display
- [ ] Create dispute resolution process documentation

### Phase 1: Database & Architecture (Week 1)

- [ ] Create `family_sanctuaries.json` schema
- [ ] Create `sanctuary_engine.py` file
- [ ] Implement `FamilySanctuarySession` class
- [ ] Implement `TherapeuticModality` helper class
- [ ] Implement `BillingManager` for sanctuary
- [ ] Add PostgreSQL schema (for future migration)
- [ ] Set up Azure Blob container: `family-sanctuary-archives`

### Phase 2: Backend Handlers (Week 2)

- [ ] `sanctuary_create` handler
- [ ] `sanctuary_join` handler
- [ ] `sanctuary_onboarding_complete` handler
- [ ] `sanctuary_message` handler
- [ ] `sanctuary_coaching_accept` handler
- [ ] `sanctuary_coaching_decline` handler
- [ ] `sanctuary_exit` handler
- [ ] `sanctuary_exit_confirm` handler
- [ ] `sanctuary_extend` handler
- [ ] `sanctuary_complete` handler
- [ ] `sanctuary_request_coach` handler

### Phase 3: Little Nate AI Integration (Week 2-3)

- [ ] Build sanctuary system prompt template
- [ ] Implement escalation detection algorithm
- [ ] Implement coaching generation
- [ ] Implement assisted response generation
- [ ] Integrate with existing AzureCortex class
- [ ] Test therapeutic modality selection
- [ ] Implement C_emo family tracking

### Phase 4: Billing Integration (Week 3)

- [ ] Base fee ($20) Stripe integration
- [ ] Coaching charge ($5) per intervention
- [ ] Assisted response charge ($3) add-on
- [ ] Threshold notifications ($50, $100)
- [ ] Invoice generation
- [ ] Refund system
- [ ] Test with Stripe test mode

### Phase 5: Frontend Development (Week 4)

- [ ] Create `family_sanctuary.html`
- [ ] Multi-member chat interface
- [ ] Active members sidebar
- [ ] Private coaching modal
- [ ] Billing tracker display
- [ ] Exit/pause controls
- [ ] Onboarding flow UI
- [ ] Mobile responsive design

### Phase 6: Azure Blob Integration (Week 4)

- [ ] Set up Azure Storage account
- [ ] Create blob container with proper permissions
- [ ] Implement upload function for transcripts
- [ ] Implement upload for coach summaries
- [ ] Implement retrieval/download for family
- [ ] Test archive access controls

### Phase 7: Coach Integration (Week 5)

- [ ] Coach summary generation
- [ ] Coach notification system
- [ ] Coach dashboard view (The Eye extension)
- [ ] Escalation workflow
- [ ] Post-session continuation flow
- [ ] Test handoff process

### Phase 8: Testing & QA (Week 6)

- [ ] Unit tests for sanctuary_engine
- [ ] Integration tests for all handlers
- [ ] End-to-end family session simulation
- [ ] Billing accuracy verification
- [ ] Escalation detection accuracy
- [ ] Minor safety protocols
- [ ] Load testing (multiple concurrent sanctuaries)
- [ ] Security audit (PII protection, access control)

### Phase 9: Documentation & Training (Week 7)

- [ ] User guide for families
- [ ] Coach training materials
- [ ] Admin documentation
- [ ] API documentation
- [ ] Troubleshooting guide
- [ ] Video tutorials

### Phase 10: Deployment (Week 8)

- [ ] Staging environment testing
- [ ] Production deployment
- [ ] Monitoring dashboards
- [ ] Alert systems
- [ ] Backup procedures
- [ ] Rollback plan
- [ ] Launch communications

---

## 🚀 TECHNICAL REQUIREMENTS SUMMARY

### New Files to Create

1. **Backend:**
   - `sanctuary_engine.py` (~800 lines)
   - `therapeutic_modalities.py` (~400 lines)
   - `sanctuary_billing.py` (~300 lines)

2. **Frontend:**
   - `family_sanctuary.html` (~500 lines)
   - `family_sanctuary.css` (~300 lines)
   - `family_sanctuary.js` (~600 lines)

3. **Database:**
   - `family_sanctuaries.json` (schema)
   - PostgreSQL migration scripts

4. **Documentation:**
   - User guide
   - Coach guide
   - Admin guide

### Modified Files

1. **bridge_server.py:**
   - Add 11 new WebSocket handlers
   - Import sanctuary_engine
   - ~400 lines added

2. **user_registry.json:**
   - No schema changes needed
   - Uses existing family_id field

3. **billing.json:**
   - Add sanctuary_charges section
   - Track per-sanctuary billing

4. **The Eye Dashboard:**
   - Add Family Sanctuary analytics tab
   - Show active sanctuaries
   - Display metrics

### External Dependencies

1. **Azure Blob Storage:**
   - Python SDK: `azure-storage-blob==12.19.0`
   - Container: `family-sanctuary-archives`
   - Access: Private with SAS tokens

2. **Stripe:**
   - Already integrated
   - New payment intent types for sanctuary

3. **Azure OpenAI:**
   - Increased usage expected
   - Budget monitoring recommended

---

## 📊 SUCCESS METRICS

### Business Metrics

- Number of sanctuaries created per month
- Average sanctuary duration
- Average revenue per sanctuary
- Coach escalation rate
- Family satisfaction scores
- Repeat usage rate

### Clinical Metrics

- Family C_emo improvement (avg Δ)
- Breakthrough moment frequency
- De-escalation success rate
- Resolution achievement rate
- Member engagement levels
- Coach intervention quality

### Technical Metrics

- Escalation detection accuracy
- Response time (<2s per message)
- System uptime (>99.9%)
- Azure Blob reliability
- Billing accuracy (100%)

---

## 🎯 LAUNCH TIMELINE

**Week 1-2:** Database & Backend (sanctuary_engine.py)  
**Week 3-4:** AI Integration & Billing  
**Week 5-6:** Frontend & Coach Tools  
**Week 7-8:** Testing & Documentation  
**Week 9:** Soft launch (beta families)  
**Week 10:** Full production launch

**Total Development Time:** 10 weeks  
**Team Size:** 1-2 developers + 1 coach advisor  
**Budget:** ~$30K development + $5K Azure/Stripe fees

---

## ✅ FINAL SUMMARY

Family Sanctuary is a groundbreaking feature that brings **AI-facilitated family therapy** to the Clinical Sovereignty Lab platform.

**Key Innovations:**
- Multi-member therapeutic group sessions
- Real-time AI intervention at critical moments
- Pay-per-intervention billing model
- 24-hour asynchronous format
- Coach escalation pathway
- Azure Blob archival for learning

**Expected Impact:**
- New revenue stream ($100-200 per sanctuary avg)
- Increased TOP_TIER value proposition
- Family-level engagement (not just individual)
- Coach collaboration opportunities
- Therapeutic effectiveness research data

**Status:** 🟢 READY FOR DEVELOPMENT

---

**Document Version:** 1.0  
**Created:** January 26, 2026 4:00 AM  
**Status:** 📋 COMPLETE SPECIFICATION  
**Ready for:** Development kickoff

**Next Steps:**
1. Review with clinical team
2. Finalize therapeutic approach
3. Begin Phase 1 development
4. Set up Azure Blob container
5. Create sanctuary_engine.py

🎉 Family Sanctuary - Healing families through AI-facilitated connection! 💙
