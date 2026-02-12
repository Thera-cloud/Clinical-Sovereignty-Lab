# Little Nate — Analytics Events & Crisis Protocol
## Version 1.0 | January 21, 2026

---

## PART 1: ANALYTICS EVENTS SCHEMA

Track these events for business intelligence, user behavior analysis, and product improvement.

### Event Structure

```json
{
  "event_id": "uuid",
  "event_name": "string",
  "timestamp": "ISO8601",
  "user_id": "uuid (nullable for anonymous)",
  "session_id": "uuid (nullable)",
  "properties": {},
  "context": {
    "platform": "ios | android | web",
    "app_version": "string",
    "device_type": "string",
    "os_version": "string"
  }
}
```

---

### Core Events

#### Authentication & Onboarding

| Event | Properties | Trigger |
|-------|------------|---------|
| `signup_started` | `{ source, referrer }` | User opens signup |
| `signup_consent_agreed` | `{ consent_version }` | User accepts covenant |
| `signup_completed` | `{ role, modality }` | Account created |
| `login_success` | `{ method: password|biometric }` | Successful login |
| `login_failed` | `{ reason }` | Failed login |
| `logout` | `{ voluntary: bool }` | User logs out |

#### Trial & Conversion

| Event | Properties | Trigger |
|-------|------------|---------|
| `trial_started` | `{ trial_days }` | Trial begins |
| `trial_day_n` | `{ day: 1-7, sessions_count }` | Each day of trial |
| `trial_upgrade_prompt_shown` | `{ days_remaining, location }` | Upgrade modal shown |
| `trial_upgrade_clicked` | `{ tier_selected }` | User clicks upgrade |
| `trial_expired` | `{ sessions_total, coherence_final }` | Trial ends |
| `trial_converted` | `{ tier, time_to_convert_hours }` | User subscribes |

#### Subscription & Billing

| Event | Properties | Trigger |
|-------|------------|---------|
| `subscription_started` | `{ tier, price, trial: bool }` | New subscription |
| `subscription_upgraded` | `{ from_tier, to_tier }` | Tier upgrade |
| `subscription_downgraded` | `{ from_tier, to_tier }` | Tier downgrade |
| `subscription_cancelled` | `{ reason, tenure_days }` | Cancellation |
| `subscription_reactivated` | `{ days_inactive }` | Resubscribe |
| `payment_succeeded` | `{ amount, type }` | Payment processed |
| `payment_failed` | `{ reason, retry_count }` | Payment failure |

#### Family

| Event | Properties | Trigger |
|-------|------------|---------|
| `family_member_invited` | `{ relationship }` | Invitation sent |
| `family_member_accepted` | `{ inviter_id }` | Invitation accepted |
| `family_member_removed` | `{ relationship, tenure_days }` | Member removed |

#### Coaching

| Event | Properties | Trigger |
|-------|------------|---------|
| `coaching_pack_purchased` | `{ pack_type, price }` | Pack bought |
| `coaching_session_booked` | `{ coach_id, days_until }` | Session scheduled |
| `coaching_session_started` | `{ session_id }` | Session begins |
| `coaching_session_completed` | `{ duration_minutes, rating }` | Session ends |
| `coaching_session_cancelled` | `{ hours_before, reason }` | Cancellation |
| `coaching_session_no_show` | `{ who: client|coach }` | No-show |

#### Session & Engagement

| Event | Properties | Trigger |
|-------|------------|---------|
| `session_started` | `{ type: ai|coach, modality }` | Conversation begins |
| `session_message_sent` | `{ message_length, is_voice }` | User sends message |
| `session_ended` | `{ duration_seconds, messages_count }` | Conversation ends |
| `voice_mode_activated` | `{}` | Voice mode turned on |
| `voice_mode_error` | `{ error_type }` | Voice mode fails |

#### Nevedal

| Event | Properties | Trigger |
|-------|------------|---------|
| `nevedal_reading_recorded` | `{ c_emo, p_ent, cee_window }` | Biometric captured |
| `cee_window_detected` | `{ duration_seconds, c_emo_peak }` | CEE achieved |
| `coherence_milestone` | `{ milestone: 0.5|0.7|0.9, first_time }` | Threshold crossed |

#### Errors & Issues

| Event | Properties | Trigger |
|-------|------------|---------|
| `error_occurred` | `{ error_code, message, stack }` | App error |
| `connection_lost` | `{ duration_ms }` | WebSocket dropped |
| `connection_restored` | `{ downtime_ms }` | Reconnected |
| `crash_detected` | `{ screen, last_action }` | App crash |

---

### Key Metrics to Derive

| Metric | Calculation |
|--------|-------------|
| **Conversion Rate** | `trial_converted / trial_started` |
| **Churn Rate** | `subscription_cancelled / active_subscriptions` |
| **ARPU** | `total_revenue / active_users` |
| **Session Frequency** | `session_started / unique_users / days` |
| **Avg Session Duration** | `sum(session_ended.duration) / count` |
| **CEE Rate** | `cee_window_detected / session_ended` |
| **Coaching Utilization** | `coaching_session_completed / pack_sessions_total` |
| **Family Expansion Rate** | `family_member_accepted / subscription_started(TOP_TIER)` |
| **NPS Proxy** | Derived from session ratings and tenure |

---

### Database Table

```sql
CREATE TABLE analytics_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_name VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_id UUID REFERENCES users(id),
    session_id UUID,
    properties JSONB DEFAULT '{}',
    context JSONB DEFAULT '{}',
    
    -- Partitioning by month for performance
    created_month DATE GENERATED ALWAYS AS (DATE_TRUNC('month', timestamp)) STORED
) PARTITION BY RANGE (created_month);

-- Create monthly partitions
CREATE TABLE analytics_events_2026_01 PARTITION OF analytics_events
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
    
-- Indexes
CREATE INDEX idx_events_name ON analytics_events(event_name);
CREATE INDEX idx_events_user ON analytics_events(user_id);
CREATE INDEX idx_events_timestamp ON analytics_events(timestamp);
CREATE INDEX idx_events_properties ON analytics_events USING GIN(properties);
```

---

## PART 2: CRISIS ESCALATION PROTOCOL

### Crisis Severity Levels

| Level | Name | Trigger | Response Time |
|-------|------|---------|---------------|
| **P0** | CRITICAL | Active self-harm language, suicide ideation | Immediate (<5 min) |
| **P1** | HIGH | Crisis keywords, severe distress, harm to others | <30 min |
| **P2** | ELEVATED | Concerning patterns, extended silence, declining coherence | <4 hours |
| **P3** | MONITORING | Mild concerns, new user with risk factors | Daily review |

---

### Detection Triggers

#### P0 — CRITICAL (Immediate)

Keywords/phrases:
- "I want to die"
- "kill myself"
- "end it all"
- "no reason to live"
- "goodbye forever"
- "better off without me"
- Explicit suicide plans (method, time, place)

Patterns:
- Nate detects imminent self-harm intent
- User explicitly states they are in danger
- Third-party report of active crisis

#### P1 — HIGH (<30 min)

Keywords/phrases:
- "I can't go on"
- "what's the point"
- "nobody cares"
- "I'm a burden"
- References to self-harm without immediacy
- Mentions of harming others

Patterns:
- Severe emotional distress (C_emo < 0.2 sustained)
- Nate AI escalation flag
- Repeated crisis-adjacent language

#### P2 — ELEVATED (<4 hours)

Patterns:
- No activity for 3+ days (Deadman Switch)
- C_emo declining trend over 7+ days
- Session abrupt endings pattern
- User mentions "giving up" on therapy
- Conflict with family members

#### P3 — MONITORING (Daily)

Patterns:
- New user with depression/anxiety modality
- Minor with unstable home situation
- History of crisis in notes
- Coherence volatility

---

### Escalation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CRISIS DETECTION                                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  1. NATE AI RESPONSE (Immediate)                                         │
│     • Acknowledge distress                                               │
│     • Provide 988 Suicide & Crisis Lifeline                             │
│     • Offer to stay present                                              │
│     • Never abandon conversation                                         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. SYSTEM ALERT (Automatic)                                             │
│     • Add to Crisis Watchlist                                            │
│     • Log in audit trail                                                 │
│     • Send internal alert to duty admin                                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
         ┌──────────┐    ┌──────────┐    ┌──────────┐
         │    P0    │    │    P1    │    │   P2/P3  │
         │ CRITICAL │    │   HIGH   │    │ ELEVATED │
         └────┬─────┘    └────┬─────┘    └────┬─────┘
              │               │               │
              ▼               ▼               ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ IMMEDIATE:      │  │ WITHIN 30 MIN:  │  │ WITHIN 4 HRS:   │
│                 │  │                 │  │                 │
│ • Page on-call  │  │ • Alert duty    │  │ • Email assigned│
│   admin         │  │   coach         │  │   coach         │
│ • Alert any     │  │ • Review        │  │ • Schedule      │
│   assigned      │  │   session       │  │   check-in      │
│   coach         │  │ • Consider      │  │ • Monitor for   │
│ • If guardian:  │  │   outreach      │  │   escalation    │
│   notify        │  │                 │  │                 │
│ • Consider 911  │  │                 │  │                 │
│   if location   │  │                 │  │                 │
│   known         │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

### Crisis Response Message Templates (Nate AI)

#### P0 Response:
```
I hear you, and I'm concerned about what you're sharing with me. 
Your life matters, and I want you to get the support you need right now.

Please reach out to the 988 Suicide & Crisis Lifeline by calling or texting 988. 
They have trained counselors available 24/7.

I'm here with you. I'm not going anywhere. 
Would you like to talk about what's happening?
```

#### P1 Response:
```
What you're feeling sounds incredibly heavy, and I'm grateful you're 
sharing this with me. You don't have to carry this alone.

If you're in crisis, the 988 Lifeline is available anytime: call or text 988.

I'd like to understand more about what's going on. Can you tell me 
what's been happening?
```

---

### Guardian Notification Protocol

For minors (users under 18 with a linked guardian):

| Crisis Level | Guardian Notification |
|--------------|----------------------|
| P0 CRITICAL | Immediate call + text + email |
| P1 HIGH | Text + email within 30 min |
| P2 ELEVATED | Email within 24 hours |
| P3 MONITORING | No automatic notification |

**Guardian Notification Message (P0):**
```
URGENT: [Child Name] may be in crisis.

During their session with Little Nate, concerning language was detected 
that suggests they may be thinking about self-harm.

We have provided them with crisis resources (988 Lifeline) and are 
monitoring the situation.

Please check on [Child Name] as soon as possible.

If you believe they are in immediate danger, call 911.

Resources:
• 988 Suicide & Crisis Lifeline
• Crisis Text Line: Text HOME to 741741

— Sovereign Sanctuary Safety Team
```

---

### Internal Alert System

```python
# Crisis alert destinations
ALERT_CHANNELS = {
    "P0": {
        "pagerduty": True,
        "slack": "#crisis-p0",
        "sms": ["on_call_admin"],
        "email": ["crisis@littlenate.ai", "on_call_admin"]
    },
    "P1": {
        "pagerduty": False,
        "slack": "#crisis-alerts",
        "sms": [],
        "email": ["crisis@littlenate.ai"]
    },
    "P2": {
        "pagerduty": False,
        "slack": "#crisis-monitoring",
        "sms": [],
        "email": []
    },
    "P3": {
        "pagerduty": False,
        "slack": None,
        "sms": [],
        "email": []
    }
}
```

---

### Documentation Requirements

Every crisis event must be documented:

```sql
CREATE TABLE crisis_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    watchlist_id UUID REFERENCES crisis_watchlist(id),
    user_id UUID NOT NULL REFERENCES users(id),
    severity VARCHAR(10) NOT NULL,  -- P0, P1, P2, P3
    trigger_type VARCHAR(50) NOT NULL,  -- KEYWORD, PATTERN, MANUAL, DEADMAN
    trigger_content TEXT,  -- The specific trigger (redacted if needed)
    nate_response TEXT,  -- What Nate said
    actions_taken JSONB,  -- Array of actions
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES users(id),
    resolution_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

### Escalation Checklist (Admin Use)

#### P0 Response Checklist:
- [ ] Reviewed flagged conversation
- [ ] Confirmed user is still engaged (or attempted outreach)
- [ ] Verified 988/crisis resources were provided
- [ ] Checked if minor → notified guardian
- [ ] Documented in crisis_events
- [ ] Assigned to coach for follow-up
- [ ] Set 24-hour check-in reminder
- [ ] If no response + location known → consider wellness check

#### Resolution Criteria:
- User explicitly states they are safe
- User engages with crisis resource
- Guardian confirms user is safe
- 48 hours of stable engagement post-crisis
- Coach assessment confirms stability

---

### Legal & Compliance Notes

1. **Duty to Warn**: If user expresses intent to harm specific individuals, 
   escalate to legal counsel immediately.

2. **Mandated Reporting**: If minor abuse is suspected, follow state 
   mandated reporting requirements.

3. **Documentation**: All crisis interactions must be preserved for 
   minimum 7 years.

4. **Privacy**: Crisis data is subject to stricter access controls than 
   standard user data.

5. **Training**: All staff with crisis access must complete annual 
   crisis response training.

---

*Document Version: 1.0*
*Last Updated: January 21, 2026*
*Review Schedule: Quarterly*
