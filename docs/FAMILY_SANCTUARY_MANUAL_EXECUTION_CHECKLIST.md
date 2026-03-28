# Family Sanctuary Manual Execution Checklist

This checklist complements `backend/tests/test_family_sanctuary_lifecycle_plan.py`.
Automated tests cover source/contracts and non-mutating DB checks; this checklist covers UX and provider flows (Stripe/Twilio) that require human validation.

## Preconditions

- Stripe test/live mode selected intentionally
- Twilio voice route active for shared family number
- Admin access to Sovereign Command
- At least 1 test family and 2 member accounts available
- Quantum flags state recorded before run:
  - `ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR`
  - `ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION`
  - `ENABLE_TIME_CRYSTAL_FORGE`

## Manual Phases

### Phase 1: Family Creation / Invitation / Merge

- Create family from app flow
- Invite 2 members: one accepts, one declines
- In Sovereign Command, run merge of solo user into family
- Verify merged user keeps:
  - conversation history
  - crystals
  - billing transition from individual to family

### Phase 2: Individual Sessions Inside Family

- Start private 1:1 as member A
- Confirm member B cannot view transcript
- Confirm LN references member A history only
- Confirm coaching remains scoped to member A

### Phase 3: Group Dynamics + Intervention

- Start family group chat
- Simulate escalation between two members
- Validate LN de-escalation response
- Validate LN private intervention to one member is not visible in group thread

### Phase 4: Voice Call Family Context

- Member calls shared number
- Validate caller identity and family context load
- Validate no leak of other members private content
- Validate call metering recorded per user while consuming shared family entitlement

### Phase 5: Billing / Entitlements (Stripe)

- Validate per-seat billing at baseline
- Add member and confirm proration/update
- Remove member and confirm proration/update
- Exhaust voice pool and validate overage/upgrade UX

### Phase 6: Coach Integration

- Assign coach to family
- Validate coach can see family overview and group session summaries
- Validate private 1:1 visibility obeys consent boundaries
- Validate coach note -> LN handoff behavior appears naturally

### Phase 7: Privacy Boundaries (Deployment Blocker)

- Member A discloses private topic in 1:1
- Member B asks LN about A's private topic
- Validate LN does not reveal, confirm, or deny private disclosure
- Validate admin cannot open member private 1:1 transcript
- Remove member and validate data isolation behavior

### Phase 8: Quantum Crystal Behavior (flags ON)

- Enable `ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR=true`
- Validate recall logs created per requesting user
- Validate co-activation formed from that user's recalled hits only
- Validate no cross-member crystal recall contamination

### Phase 9: Exit / Dissolution / Export

- Member voluntary exit flow
- Full family dissolution flow
- Data export for member account
- Validate personal data preserved, group contributions retained in group history policy

## Evidence to capture per phase

- Screenshot(s)
- API response snippet (where relevant)
- SQL verification query + row count
- Pass/Fail
- If fail: repro steps and severity (`privacy`, `billing`, `functional`, `cosmetic`)

## Severity policy

- Any Phase 7 privacy failure: **BLOCK DEPLOYMENT**
- Billing defects: fix before production rollout
- Functional defects: fix before flags ON
- Cosmetic issues: track separately if no safety impact

