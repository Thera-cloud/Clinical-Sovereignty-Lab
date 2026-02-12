# Little Nate — Full Stack Implementation Checklist
## Complete Integration Guide for Production Deployment

**Version:** 4.0  
**Date:** January 21, 2026  
**Status:** Planning Phase — Ready for Development

---

## 📊 CURRENT STATE ASSESSMENT

### ✅ COMPLETED (Existing Assets)

| Asset | Location | Lines/Size | Status |
|-------|----------|------------|--------|
| **Client Mobile App (Flutter)** | `main_hybrid.dart` | 1,748 lines | Working - Lobby, Login, Signup, Chat, Consent |
| **Coach Portal UI (Flutter)** | `coach_portal_v2_complete.dart` | 1,815 lines | Complete - Tabs, Calendar, Sessions, Ask Nate |
| **Bridge Server (Python)** | `bridge_server_hybrid.py` | 506 lines | Working - Auth, WebSocket, Azure Realtime |
| **Coach Portal Handlers** | `bridge_handlers_v2.py` | 810 lines | Complete - Coach API handlers |
| **Nevedal Engine** | `nevedal_engine.py` | 850 lines | Complete - Full formula, CEE detection |
| **Nevedal Flutter Client** | `nevedal_flutter.dart` | 550 lines | Complete - Biometrics, state display |
| **Nevedal WebSocket Handlers** | `nevedal_handlers.py` | 200 lines | Complete - Real-time streaming |
| **Night School Director** | `night_school_director.py` | 950 lines | Complete - PII, Dojo, versioning |
| **Night School Handlers** | `night_school_handlers.py` | 280 lines | Complete - WebSocket handlers |
| **Night School REST API** | `night_school_api.py` | 350 lines | Complete - REST endpoints |
| **REST API Server** | `api_server.py` | 750 lines | Complete - FastAPI, auth, endpoints |
| **Database Schema** | `database_schema.sql` | 450 lines | Complete - PostgreSQL schema |
| **Migration Script** | `migrate_to_postgres.py` | 350 lines | Complete - JSON to PostgreSQL |
| **Admin Console (React)** | `SovereignCommand.jsx` | 1,100 lines | Complete - All 7 screens |
| **Admin Console HTML** | `sc_01` - `sc_07` | 250KB total | Reference designs |
| **Integration Tests** | `test_integration.py` | 650 lines | Complete - 40+ tests |
| **Docker Config** | `docker-compose.yml` + Dockerfiles | 400 lines | Complete - Full deployment |
| **Documentation** | Multiple .md files | 2,000+ lines | Architecture guides |

### ❌ NOT YET IMPLEMENTED

| Component | Priority | Effort |
|-----------|----------|--------|
| **E-Commerce / Billing System** | **HIGH** | **3 weeks** |
| Stripe Integration | HIGH | 1 week |
| Subscription Management | HIGH | 1 week |
| Family Linking Billing | HIGH | 0.5 weeks |
| Live Coaching Booking/Payment | HIGH | 0.5 weeks |
| MVVM Refactoring (Cursor) | MEDIUM | 2 weeks |
| Push Notification Service | LOW | 1 week |

---

## 🏗️ ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LITTLE NATE PLATFORM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   Client     │   │    Coach     │   │    Admin     │   │   Research   │ │
│  │  Mobile App  │   │   Portal     │   │   Console    │   │     Lab      │ │
│  │  (Flutter)   │   │  (Flutter)   │   │   (React)    │   │   (React)    │ │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘ │
│         │                  │                  │                  │          │
│         └──────────────────┴──────────────────┴──────────────────┘          │
│                                    │                                         │
│                            ┌───────▼───────┐                                │
│                            │  API Gateway  │                                │
│                            │   (FastAPI)   │                                │
│                            └───────┬───────┘                                │
│                                    │                                         │
│    ┌───────────────────────────────┼───────────────────────────────┐        │
│    │                               │                               │        │
│  ┌─▼──────────┐  ┌────────────────▼────────────────┐  ┌───────────▼──┐     │
│  │  Bridge    │  │         Services Layer          │  │   Stripe     │     │
│  │  Server    │  │  Auth│Session│Nevedal│Coach│... │  │   Webhooks   │     │
│  │ (WebSocket)│  └────────────────┬────────────────┘  └──────────────┘     │
│  └─────┬──────┘                   │                                         │
│        │                          │                                         │
│        └──────────────────────────┼─────────────────────────────────┐       │
│                                   │                                 │       │
│                           ┌───────▼───────┐                 ┌───────▼─────┐ │
│                           │  PostgreSQL   │                 │    Redis    │ │
│                           │   Database    │                 │   (Cache)   │ │
│                           └───────────────┘                 └─────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 MASTER IMPLEMENTATION CHECKLIST

### PHASE 0: Infrastructure Setup ✅ COMPLETE
**Goal:** Production-ready infrastructure

- [x] PostgreSQL database schema
- [x] FastAPI project structure
- [x] JWT authentication
- [x] Pydantic models
- [x] Docker containerization
- [x] Environment variable management

---

### PHASE 1: Core Backend ✅ COMPLETE
**Goal:** Replace JSON file storage with proper database + REST API

- [x] User Management API
- [x] Family Management API
- [x] Session Management API
- [x] Audit Log System

---

### PHASE 2: Coach Portal Backend ✅ COMPLETE
**Goal:** Full backend support for coach portal

- [x] Coach-Specific Endpoints
- [x] Pre-Session Brief API
- [x] Post-Session Analysis API
- [x] Ask Nate (Coach) API

---

### PHASE 3: Admin Console Backend ✅ COMPLETE
**Goal:** Full backend support for admin screens

- [x] Dashboard API
- [x] User Management API
- [x] Night School API
- [x] The Eye API
- [x] Nate Features API

---

### PHASE 4: Nevedal Research Lab ✅ COMPLETE
**Goal:** Full implementation with real biometric computation

- [x] Nevedal Formula Implementation
- [x] Voice Biometric Extraction
- [x] CEE Window Detection
- [x] Real-time WebSocket Streaming
- [x] State History Tracking

---

### PHASE 5: Admin Web Console ✅ COMPLETE
**Goal:** Convert mockups to production web app

- [x] React SPA with all 7 screens
- [x] Design system implementation
- [x] Dashboard (sc_01)
- [x] User Management (sc_02)
- [x] Night School (sc_03)
- [x] The Eye (sc_04)
- [x] Audit Log (sc_05)
- [x] Nate Features (sc_06)
- [x] Nevedal Lab (sc_07)

---

### PHASE 6: Night School Director ✅ COMPLETE
**Goal:** PII detection, versioning, adversarial testing

- [x] PII Detection & Redaction
- [x] Wisdom Entry Management
- [x] Coach Notes Audit Queue
- [x] Version Control with Snapshots
- [x] The Dojo (Adversarial Testing)
- [x] All 6 Persona Prompts

---

### PHASE 7: E-Commerce & Billing System 🚧 NEXT
**Goal:** Complete monetization infrastructure

#### 7.1 Pricing Structure Implementation
```
BASE TIERS:
├── THRESHOLD (Trial)           Free         7 days
├── INNER CHAMBER (Standard)    $49/mo       AI companion
└── SOVEREIGN CIRCLE (Top Tier) $149/mo      Full platform

FAMILY LINKING (Sovereign Circle only):
├── Spouse                      Included
├── First Dependent             Included
└── Each Additional Member      +$75/mo

LIVE COACHING (Sovereign Circle only):
├── Single Session (45 min)     $175
├── 4-Session Pack              $600         (15% off)
└── 8-Session Pack              $1,120       (20% off)
```

#### 7.2 Database Schema Updates
- [ ] Add `subscriptions` table
- [ ] Add `subscription_items` table (family members)
- [ ] Add `session_packs` table
- [ ] Add `coaching_sessions` table
- [ ] Add `payment_history` table
- [ ] Add `family_role` column to users
- [ ] Add `linked_at`, `linked_by` columns to users

#### 7.3 Stripe Integration
- [ ] Set up Stripe account & API keys
- [ ] Create Stripe Products:
  - [ ] `prod_inner_chamber` — $49/mo
  - [ ] `prod_sovereign_circle` — $149/mo
  - [ ] `prod_family_member` — $75/mo
  - [ ] `prod_coaching_single` — $175
  - [ ] `prod_coaching_4pack` — $600
  - [ ] `prod_coaching_8pack` — $1,120
- [ ] Configure Stripe webhook endpoint
- [ ] Implement webhook handlers:
  - [ ] `checkout.session.completed`
  - [ ] `invoice.paid`
  - [ ] `invoice.payment_failed`
  - [ ] `customer.subscription.updated`
  - [ ] `customer.subscription.deleted`

#### 7.4 Subscription Management API
- [ ] `POST /api/billing/checkout` — Create Stripe checkout session
- [ ] `GET /api/billing/subscription` — Get current subscription
- [ ] `POST /api/billing/subscription/upgrade` — Upgrade tier
- [ ] `POST /api/billing/subscription/downgrade` — Downgrade tier
- [ ] `POST /api/billing/subscription/cancel` — Cancel subscription
- [ ] `POST /api/billing/subscription/pause` — Pause subscription
- [ ] `GET /api/billing/invoices` — Get invoice history
- [ ] `GET /api/billing/payment-methods` — List payment methods
- [ ] `POST /api/billing/payment-methods` — Add payment method
- [ ] `DELETE /api/billing/payment-methods/{id}` — Remove payment method

#### 7.5 Family Linking API
- [ ] `POST /api/family/invite` — Send family invitation
- [ ] `POST /api/family/accept` — Accept invitation
- [ ] `DELETE /api/family/members/{id}` — Remove family member
- [ ] `GET /api/family/billing` — Get family billing summary
- [ ] Implement proration logic for mid-cycle additions
- [ ] Implement spouse/dependent detection
- [ ] Auto-upgrade linked members to STANDARD access

#### 7.6 Live Coaching Booking API
- [ ] `GET /api/coaching/availability` — Get coach availability
- [ ] `POST /api/coaching/book` — Book session (pay or use pack)
- [ ] `POST /api/coaching/cancel/{id}` — Cancel booking (refund logic)
- [ ] `GET /api/coaching/sessions` — List user's coaching sessions
- [ ] `GET /api/coaching/packs` — Get user's session packs
- [ ] `POST /api/coaching/packs/purchase` — Buy session pack
- [ ] Implement pack expiration logic

#### 7.7 Trial Management
- [ ] Implement 7-day trial logic
- [ ] Trial expiration cron job
- [ ] Grace period (3 days) implementation
- [ ] Trial-to-paid conversion tracking

#### 7.8 Client-Side Billing UI (Flutter)
- [ ] Membership selection screen
- [ ] Feature comparison view
- [ ] Family management screen
- [ ] Live coaching booking flow
- [ ] Session pack purchase screen
- [ ] Subscription management in settings
- [ ] Payment method management
- [ ] Invoice history view
- [ ] Upgrade/downgrade flows
- [ ] Trial expiration prompts
- [ ] Coherence milestone rewards

#### 7.9 Admin Billing Management
- [ ] Revenue dashboard
- [ ] Subscription analytics
- [ ] Failed payment alerts
- [ ] Manual subscription adjustments
- [ ] Refund processing
- [ ] Coupon/discount management

---

### PHASE 8: MVVM Integration (Cursor) 🔜 AFTER E-COMMERCE
**Goal:** Consolidate all code with proper architecture

#### 8.1 Server Consolidation
- [ ] Create unified folder structure
- [ ] Migrate to service-based architecture
- [ ] Implement message routing
- [ ] Consolidate handlers into services
- [ ] Single WebSocket gateway

#### 8.2 Client Consolidation
- [ ] Create MVVM folder structure
- [ ] Implement Riverpod providers
- [ ] Create repositories
- [ ] Create ViewModels
- [ ] Refactor screens to use ViewModels
- [ ] Single WebSocket client

#### 8.3 Testing & Validation
- [ ] Unit tests for all ViewModels
- [ ] Integration tests for repositories
- [ ] End-to-end flow testing
- [ ] Performance optimization

---

### PHASE 9: Integration & Testing
**Goal:** Full system integration and quality assurance

#### 9.1 Integration Testing
- [ ] Client app ↔ Bridge server
- [ ] Coach portal ↔ REST API
- [ ] Admin console ↔ REST API
- [ ] E-commerce ↔ Stripe
- [ ] Real-time WebSocket stability
- [ ] Azure OpenAI integration
- [ ] Biometric pipeline end-to-end

#### 9.2 Security Audit
- [ ] JWT token security review
- [ ] Payment data handling (PCI compliance)
- [ ] SQL injection prevention
- [ ] XSS prevention
- [ ] CSRF protection
- [ ] Rate limiting verification
- [ ] Audit log completeness
- [ ] HIPAA compliance check
- [ ] Data encryption at rest

#### 9.3 Performance Testing
- [ ] Load testing (100+ concurrent users)
- [ ] WebSocket connection limits
- [ ] Database query optimization
- [ ] API response time benchmarks
- [ ] Memory leak detection

---

### PHASE 10: Deployment & Launch
**Goal:** Production deployment

#### 10.1 Infrastructure
- [ ] Production server provisioning
- [ ] SSL certificate setup
- [ ] CDN configuration
- [ ] Database replication
- [ ] Backup automation
- [ ] Monitoring setup (Prometheus/Grafana)
- [ ] Alerting configuration
- [ ] Stripe production keys

#### 10.2 Documentation
- [ ] API documentation (Swagger/OpenAPI)
- [ ] Admin user manual
- [ ] Coach user manual
- [ ] Client user guide
- [ ] Billing/subscription FAQ
- [ ] Developer documentation
- [ ] Incident response procedures

#### 10.3 Launch
- [ ] Soft launch (beta users)
- [ ] Payment flow testing with real cards
- [ ] Performance monitoring
- [ ] Bug fixes
- [ ] Full launch
- [ ] Post-launch monitoring

---

## 🗄️ UPDATED DATABASE SCHEMA

### New E-Commerce Tables

```sql
-- Subscriptions (Stripe-synced)
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    stripe_subscription_id VARCHAR(255) UNIQUE,
    stripe_customer_id VARCHAR(255),
    tier VARCHAR(30) NOT NULL,  -- 'TRIAL', 'STANDARD', 'TOP_TIER'
    status VARCHAR(30) NOT NULL, -- 'ACTIVE', 'PAUSED', 'CANCELLED', 'PAST_DUE'
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Family members billing
CREATE TABLE subscription_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id),
    user_id UUID NOT NULL REFERENCES users(id),
    stripe_subscription_item_id VARCHAR(255),
    family_role VARCHAR(30) NOT NULL, -- 'PRIMARY', 'SPOUSE', 'DEPENDENT', 'ADDITIONAL'
    price_cents INT NOT NULL, -- 0 for spouse/first dependent, 7500 for additional
    added_at TIMESTAMPTZ DEFAULT NOW()
);

-- Session packs purchased
CREATE TABLE session_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) NOT NULL,
    pack_type VARCHAR(20) NOT NULL,  -- 'SINGLE', 'PACK_4', 'PACK_8'
    sessions_total INT NOT NULL,
    sessions_remaining INT NOT NULL,
    price_cents INT NOT NULL,
    stripe_payment_id VARCHAR(255),
    purchased_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Individual coaching sessions booked
CREATE TABLE coaching_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES users(id) NOT NULL,
    coach_id UUID REFERENCES users(id) NOT NULL,
    pack_id UUID REFERENCES session_packs(id),  -- NULL if single purchase
    scheduled_at TIMESTAMPTZ NOT NULL,
    duration_minutes INT DEFAULT 45,
    status VARCHAR(20) DEFAULT 'SCHEDULED',  -- SCHEDULED, COMPLETED, CANCELLED, NO_SHOW
    price_cents INT,  -- NULL if from pack
    stripe_payment_id VARCHAR(255),  -- For single session purchases
    nate_briefing_sent BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Payment history
CREATE TABLE payment_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) NOT NULL,
    stripe_payment_intent_id VARCHAR(255),
    stripe_invoice_id VARCHAR(255),
    amount_cents INT NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    description TEXT,
    status VARCHAR(20) NOT NULL, -- 'SUCCEEDED', 'FAILED', 'REFUNDED'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Coupons/discounts
CREATE TABLE coupons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) UNIQUE NOT NULL,
    stripe_coupon_id VARCHAR(255),
    discount_type VARCHAR(20) NOT NULL, -- 'PERCENT', 'FIXED'
    discount_value INT NOT NULL, -- Percentage or cents
    applies_to VARCHAR(30), -- 'STANDARD', 'TOP_TIER', 'COACHING', 'ALL'
    max_uses INT,
    current_uses INT DEFAULT 0,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User modifications for family linking
ALTER TABLE users ADD COLUMN family_role VARCHAR(30);  -- 'PRIMARY', 'SPOUSE', 'DEPENDENT', 'ADDITIONAL'
ALTER TABLE users ADD COLUMN linked_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN linked_by UUID REFERENCES users(id);
ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(255);
```

---

## 💰 PRICING REFERENCE

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SANCTUARY PRICING                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  BASE TIERS                                                              │
│  ───────────────────────────────────────────────────────────            │
│  THRESHOLD (Trial)              Free         7 days                     │
│  INNER CHAMBER (Standard)       $49/mo       AI companion               │
│  SOVEREIGN CIRCLE (Top Tier)    $149/mo      Full platform              │
│                                                                          │
│  FAMILY LINKING (Sovereign Circle only)                                  │
│  ───────────────────────────────────────────────────────────            │
│  Spouse                         Included     STANDARD-level access      │
│  First Dependent                Included     STANDARD-level access      │
│  Each Additional Member         +$75/mo      STANDARD-level access      │
│                                                                          │
│  LIVE COACHING (Sovereign Circle only)                                   │
│  ───────────────────────────────────────────────────────────            │
│  Single Session (45 min)        $175         Book anytime               │
│  4-Session Pack                 $600         Save 15% (3 month expiry)  │
│  8-Session Pack                 $1,120       Save 20% (6 month expiry)  │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│  EXAMPLE CONFIGURATIONS                                                  │
│  ───────────────────────────────────────────────────────────            │
│                                                                          │
│  Individual (Standard)                                    $49/mo        │
│  Individual (Sovereign Circle)                            $149/mo       │
│  Couple                                                   $149/mo       │
│  Family of 3 (spouse + 1 child)                           $149/mo       │
│  Family of 4 (spouse + 2 children)                        $224/mo       │
│  Family of 5                                              $299/mo       │
│  Family of 6                                              $374/mo       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔢 UPDATED EFFORT ESTIMATES

| Phase | Duration | Status |
|-------|----------|--------|
| Phase 0: Infrastructure | 1 week | ✅ COMPLETE |
| Phase 1: Core Backend | 2 weeks | ✅ COMPLETE |
| Phase 2: Coach Backend | 1 week | ✅ COMPLETE |
| Phase 3: Admin Backend | 2 weeks | ✅ COMPLETE |
| Phase 4: Nevedal Lab | 2 weeks | ✅ COMPLETE |
| Phase 5: Admin Console | 2 weeks | ✅ COMPLETE |
| Phase 6: Night School | 2 weeks | ✅ COMPLETE |
| **Phase 7: E-Commerce** | **3 weeks** | 🚧 **NEXT** |
| Phase 8: MVVM Integration | 2 weeks | 🔜 PENDING |
| Phase 9: Integration/Testing | 2 weeks | 🔜 PENDING |
| Phase 10: Deployment | 1 week | 🔜 PENDING |
| **TOTAL** | **20 weeks** | **60% Complete** |

---

## 📞 CONTEXT FOR CURSOR SESSIONS

**Copy this to start Cursor integration:**

```
I'm building Little Nate, an AI therapy platform.

COMPLETED COMPONENTS:
- Flutter mobile app (main_hybrid.dart, 1,748 lines)
- Coach portal (coach_portal_v2_complete.dart, 1,815 lines)
- Bridge server (bridge_server_hybrid.py + handlers, ~1,600 lines)
- Nevedal engine (nevedal_engine.py, 850 lines)
- Night School (night_school_director.py, 950 lines)
- Admin console (SovereignCommand.jsx, 1,100 lines)
- REST API (api_server.py, 750 lines)
- Database schema (database_schema.sql, 450 lines)
- E-Commerce UI & backend (to be built)

ARCHITECTURE NEEDED:
- MVVM with Riverpod (Flutter)
- Service-based message routing (Python)
- Single WebSocket connection pattern
- Stripe integration for billing

KEY FILES TO REFERENCE:
- MVVM_INTEGRATION_GUIDE.md
- CURSOR_PROJECT_STRUCTURE.md
- CODE_PRESERVATION_AUDIT.md
- FULL_STACK_CHECKLIST_V4.md (this file)

PRICING MODEL:
- Trial: Free (7 days)
- Standard: $49/mo
- Top Tier: $149/mo
- Family: Spouse + 1 dependent free, then +$75/mo each
- Live Coaching: $175/session (packs: 4/$600, 8/$1,120)
```

---

*Document generated January 21, 2026*  
*Little Nate Platform — Full Stack Implementation Guide v4.0*
