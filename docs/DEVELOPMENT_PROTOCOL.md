# DEVELOPMENT_PROTOCOL.md
## MANDATORY: Read Before Any Code Changes

**Last Updated:** January 27, 2026  
**Status:** ENFORCED  
**Location:** Project Root

---

## 🚨 STOP - READ THIS FIRST

Before writing, modifying, or suggesting ANY code in this project, you MUST:

1. **Review the relevant specification documents**
2. **Verify your code aligns with existing architecture**
3. **Check data flow patterns**

---

## 📋 REQUIRED READING BY FEATURE

### Family Sanctuary Development
```
MUST READ BEFORE CODING:
├── /docs/FAMILY_SANCTUARY_SPEC.md      # Full feature specification
├── /docs/DATA_SOURCE_MAPPING_V2.md     # Data architecture & billing flow
└── /docs/DEVELOPMENT_PROTOCOL.md       # This file
```

### Night School Development
```
MUST READ BEFORE CODING:
├── /docs/NIGHT_SCHOOL_SPEC.md          # Training system specification
├── /docs/DATA_SOURCE_MAPPING_V2.md     # Data architecture
└── /docs/DEVELOPMENT_PROTOCOL.md       # This file
```

### Billing/Payment Changes
```
MUST READ BEFORE CODING:
├── /docs/DATA_SOURCE_MAPPING_V2.md     # Billing flow (Tree 4)
├── /docs/FAMILY_SANCTUARY_SPEC.md      # Sanctuary billing section
└── /docs/DEVELOPMENT_PROTOCOL.md       # This file
```

### Any Backend Changes
```
MUST READ BEFORE CODING:
├── /docs/DATA_SOURCE_MAPPING_V2.md     # Full data architecture
└── /docs/DEVELOPMENT_PROTOCOL.md       # This file
```

---

## ✅ PRE-CODING CHECKLIST

Before writing any code, confirm:

- [ ] I have read the relevant SPEC.md file(s)
- [ ] I have reviewed DATA_SOURCE_MAPPING_V2.md for data flow
- [ ] I understand which existing classes to use:
  - [ ] `BillingSystem` for payments (NOT direct Stripe)
  - [ ] `AnalyticsEngine` for event tracking
  - [ ] `MetricsEngine` for client/coach metrics
  - [ ] `SessionTracker` for live sessions
- [ ] I know the correct data file locations:
  - [ ] `user_registry.json` for user data
  - [ ] `billing.json` for billing records
  - [ ] `analytics.json` for platform analytics
  - [ ] `Vaults/Clients/{id}/` for client-specific data
  - [ ] `family_sanctuaries.json` for sanctuary sessions

---

## 🏗️ EXISTING SYSTEM CLASSES

**Use these - do NOT recreate:**

| Class | Purpose | File |
|-------|---------|------|
| `BillingSystem` | All payment/billing operations | bridge_server.py:869 |
| `AnalyticsEngine` | Event tracking & dashboard stats | bridge_server.py:1155 |
| `MetricsEngine` | Client/Coach metrics in Vaults | bridge_server.py:486 |
| `SessionTracker` | Live session management | bridge_server.py:743 |
| `MemorySystem` | Conversation memory | bridge_server.py:364 |
| `NightSchool` | Training engine | bridge_server.py:1011 |
| `AzureCortex` | Azure OpenAI integration | bridge_server.py:1283 |

---

## 📁 DATA FILE LOCATIONS

```
backend/app/websocket/data/
├── user_registry.json          # All users, profiles, subscriptions
├── billing.json                # Billing records, customers
├── transactions.json           # Transaction history
├── analytics.json              # Platform analytics
├── family_sanctuaries.json     # Sanctuary sessions
│
└── Vaults/
    ├── Clients/{hardware_id}/
    │   └── metrics.json        # Per-client Nevedal metrics
    ├── Coaches/{hardware_id}/
    │   └── metrics.json        # Per-coach metrics
    └── Admin/
        ├── wisdom_database.json
        ├── COACH_NOTES_INBOX/
        ├── COACH_NOTES/
        └── ADMIN_CURRICULUM/
```

---

## 🔄 INTEGRATION PATTERNS

### When Adding a New Feature:

1. **Check if similar exists** - Review bridge_server.py handlers
2. **Use existing classes** - Don't create new billing/analytics
3. **Follow data patterns** - Store in correct locations
4. **Record analytics** - Call `analytics_engine.record_event()`
5. **Update user registry** - For subscription/profile changes

### When Modifying Billing:

```python
# CORRECT - Use BillingSystem
billing_system.record_transaction(user_id, amount, description, type)

# WRONG - Direct Stripe
stripe.Charge.create(...)  # DON'T DO THIS
```

### When Recording Events:

```python
# CORRECT - Use AnalyticsEngine
analytics_engine.record_event("event_type", user_id, {"data": "here"})

# WRONG - Direct file write
with open("analytics.json", "w") as f:  # DON'T DO THIS
```

---

## 🚫 COMMON MISTAKES TO AVOID

1. **Direct Stripe calls** - Use `BillingSystem` instead
2. **Skipping analytics** - Always record significant events
3. **Wrong data locations** - Check DATA_SOURCE_MAPPING_V2.md
4. **Recreating classes** - Use existing system classes
5. **Ignoring specs** - Read the .md files FIRST

---

## 📝 CODE REVIEW QUESTIONS

Before submitting code, ask:

1. Does this follow the SPEC.md requirements?
2. Does this use the correct existing classes?
3. Does this store data in the right locations?
4. Does this record appropriate analytics events?
5. Is billing handled through BillingSystem?

---

## 🔗 DOCUMENT LOCATIONS

Keep these files updated and in sync:

| Document | Purpose | Update When |
|----------|---------|-------------|
| `FAMILY_SANCTUARY_SPEC.md` | Sanctuary feature spec | Feature changes |
| `DATA_SOURCE_MAPPING_V2.md` | Data architecture | New data flows |
| `DEVELOPMENT_PROTOCOL.md` | This file | New patterns |

---

## ⚠️ ENFORCEMENT

**AI Assistants:** Before generating ANY code for this project:
1. Request to see relevant .md files if not provided
2. Verify alignment with specifications
3. Use existing system classes
4. Follow established data patterns

**Developers:** Reference this document in code reviews.

---

**Document Version:** 1.0  
**Created:** January 27, 2026  
**Maintainer:** Nathan N.
