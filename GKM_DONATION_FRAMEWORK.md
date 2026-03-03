# Greatest in the Kingdom Ministry — Donation & Tax Framework

## Prepared for: GKM Board of Directors and Accounting Professionals

---

## Part I: Organization Overview

### Greatest in the Kingdom Ministry (GKM)

| Field | Value |
|---|---|
| Legal Name | Greatest in the Kingdom Ministry |
| Tax-Exempt Status | 501(c)(3) |
| EIN (Tax ID) | 84-3879515 |
| Registered Address | Stafford, TX 77477 |
| Contact Email | support@sovereignsanctuary.net |
| Fiscal Year | Calendar year (January 1 – December 31) |

### Sovereign Sanctuary (For-Profit Entity)

| Field | Value |
|---|---|
| Legal Name | Sovereign Sanctuary |
| Entity Type | For-profit technology company |
| Product | AI-powered therapy and coaching platform ("Little Nate") |
| Revenue Streams | Subscription tiers, token pack purchases, coaching services |
| Relationship to GKM | GKM receives 100% of token sharing fees as charitable donations |

### Relationship Between Entities

GKM and Sovereign Sanctuary are **legally separate entities**. GKM is a 501(c)(3) nonprofit ministry. Sovereign Sanctuary is a for-profit technology company that operates the Little Nate AI therapy platform. The two entities intersect through a single mechanism: **token sharing fees**. When Sovereign Sanctuary users share digital tokens with each other through the platform, a processing fee is collected. 100% of that fee is donated to GKM. No goods or services are provided by GKM in exchange for these donations.

---

## Part II: How Token Sharing Works

### What Are Tokens?

Tokens are the internal digital currency of the Sovereign Sanctuary platform. Users consume tokens when they interact with AI therapy features:

| Feature | Token Cost | Source Tag |
|---|---|---|
| AI Chat (Little Nate) | ~10 tokens per word | `ai_chat` |
| Sanctuary AI Therapy Response | ~10 tokens per word | `sanctuary_ai` |
| Group Coaching Suggestions | ~10 tokens per word | `group_coaching` |
| Private Coaching Responses | ~10 tokens per word | `private_coaching` |

Users receive tokens through their subscription tier or by purchasing token packs:

| Pack Name | Tokens Included | Purchase Price |
|---|---|---|
| Light | 15,000 | $3.00 |
| Standard | 50,000 | $7.00 |
| Power | 150,000 | $20.00 |
| Ultimate | 1,000,000 | $125.00 |

### Token Sharing (The Donation Trigger)

Users can gift tokens to other users through the platform's BLE (Bluetooth Low Energy) or NFC (Near-Field Communication) peer-to-peer mesh. This is a voluntary act of generosity between users.

**When a user shares tokens, a processing fee is charged:**

| Parameter | Value |
|---|---|
| Fee Rate | $5.00 per 10,000 tokens shared |
| Fee Rounding | Rounded up to the nearest 10,000-token increment |
| Minimum Share | 1,000 tokens |
| Maximum Share per Transaction | 100,000 tokens |
| Payment Method | Stripe (credit/debit card) |
| Fee Recipient | 100% donated to GKM |

**Fee Calculation Examples:**

| Tokens Shared | Fee Chunks (ceil) | Fee Charged | Donated to GKM |
|---|---|---|---|
| 5,000 | 1 | $5.00 | $5.00 |
| 10,000 | 1 | $5.00 | $5.00 |
| 15,000 | 2 | $10.00 | $10.00 |
| 50,000 | 5 | $25.00 | $25.00 |
| 100,000 | 10 | $50.00 | $50.00 |

### Generosity Reward: Free Month

As an incentive for generosity, users who share a cumulative total of 100,000 tokens receive one free month of platform usage from Sovereign Sanctuary. This reward is funded by Sovereign Sanctuary (the for-profit entity), not GKM. Additional free months are awarded at each subsequent 100,000-token milestone.

---

## Part III: Donation Lifecycle

### Step-by-Step Flow

```
1. User A ("Sharer") discovers User B ("Receiver") via BLE/NFC
2. User A initiates a token share (e.g., 20,000 tokens)
3. System calculates fee: ceil(20,000 / 10,000) × $5.00 = $10.00
4. Stripe charges User A's card for $10.00
5. Tokens are transferred: User A balance decreases, User B balance increases
6. $10.00 fee is recorded as a donation to GKM in the gkm_donations ledger
7. Cumulative donation total is updated for User A's tax year
8. If cumulative total reaches $250+, User A becomes eligible for a tax receipt
9. At year-end (January 2nd), the system auto-generates receipts for all eligible donors
```

### What the Donor Receives

- **Immediate**: Confirmation of token transfer, fee amount, and cumulative donation total
- **In-App**: A personalized thank-you message from Little Nate (the AI companion)
- **Annual**: IRS-compliant donation receipt if cumulative donations reach $250+ in a calendar year

### What GKM Provides in Exchange

**Nothing.** No goods or services are provided to the donor in exchange for the donation. The token transfer itself occurs between two platform users — GKM is not a party to that transaction. The fee is a voluntary charitable contribution that enables the platform to facilitate peer-to-peer generosity.

This is critical for 501(c)(3) compliance: the donation receipt explicitly states **"No goods or services were provided in exchange for this contribution."**

---

## Part IV: CPA Tax Guide

### A. For Individual Donors (Platform Users Who Share Tokens)

#### Are token sharing fees tax-deductible?

**Yes.** The fee charged when sharing tokens is a charitable contribution to Greatest in the Kingdom Ministry, a 501(c)(3) organization (EIN: 84-3879515). Donors may deduct these contributions on Schedule A (Form 1040) if they itemize deductions, subject to standard IRS rules for charitable giving.

#### Documentation requirements

| Annual Total | IRS Requirement | What the System Provides |
|---|---|---|
| Under $250 | Bank/credit card statement sufficient | Stripe receipt for each transaction |
| $250 or more | Written acknowledgment from the charity | GKM annual donation receipt (auto-generated) |
| $500 or more | Form 8283 (Section A) if non-cash | N/A — all donations are cash via Stripe |

#### What the GKM donation receipt includes

Each annual receipt contains:

1. Organization name: Greatest in the Kingdom Ministry
2. EIN: 84-3879515
3. Organization address: Stafford, TX 77477
4. Donor name (as registered on the platform)
5. Tax year covered
6. Total donation amount for the year
7. Itemized list of individual donations with dates and amounts
8. Statement: **"No goods or services were provided in exchange for this contribution"**
9. Contact: support@sovereignsanctuary.net

#### Receipt threshold and timing

- Receipts are generated for donors whose cumulative annual donations total **$250.00 or more**
- Automatic generation occurs on **January 2nd** of each year for the prior tax year
- Administrators can also generate receipts on-demand via the GKM dashboard
- Receipts are idempotent — regenerating updates the existing record rather than creating duplicates

#### Deduction limits

Standard IRS charitable deduction rules apply:

- Cash donations to 501(c)(3) organizations: generally deductible up to **60% of AGI**
- Excess may be carried forward up to 5 years
- Subject to overall limitations under IRC §170

#### Important: The free month reward

The free month of platform usage awarded at 100,000 cumulative tokens shared is provided by **Sovereign Sanctuary** (the for-profit entity), not GKM. This reward does not reduce or affect the charitable deduction for the donation fees. The donor should consult their tax advisor regarding whether the fair market value of the free month constitutes taxable income.

### B. For GKM (Nonprofit Entity — 501(c)(3))

#### Revenue recognition

All token sharing fees flow to GKM as **contribution revenue** (ASC 958-605). These are unconditional contributions — no performance obligation or exchange transaction exists.

| Account | Debit | Credit |
|---|---|---|
| Cash (Stripe settlement) | $X.XX | |
| Contribution Revenue — Token Shares | | $X.XX |

#### Key accounting considerations

1. **Revenue classification**: All share fees are classified as **contributions without donor restrictions** unless the donor imposes specific conditions (currently no mechanism for restricted donations exists).

2. **Stripe processing fees**: Stripe charges processing fees (~2.9% + $0.30 per transaction) on the PaymentIntent. The net amount received by GKM is the gross fee minus Stripe's cut. GKM should record:
   - Gross contribution revenue at the full fee amount
   - Stripe processing fees as a fundraising expense

3. **Cumulative tracking**: The system maintains a running `cumulative_total_cents` per donor per tax year. This total is **monotonically increasing** — it never decreases within a tax year. Refunds or adjustments, if ever needed, would create a separate offsetting entry.

4. **Receipt obligations**: IRS requires written acknowledgment for single contributions of $250+ (IRC §170(f)(8)). The system's threshold is based on cumulative annual total ($250+), which exceeds this requirement by also covering donors whose individual gifts are under $250 but aggregate above it.

5. **Form 990 reporting**: All contributions should appear on Form 990, Part VIII, Line 1 (Contributions, gifts, grants). The system's annual summary endpoint (`/api/gkm/annual-summary`) provides per-year totals suitable for 990 preparation.

6. **Scholarship fund distributions**: If GKM allocates funds for scholarships (subsidized platform access for qualifying individuals), these are **program service expenses** on Form 990, Part IX.

#### Annual filing checklist for GKM

| Filing | Deadline | Data Source |
|---|---|---|
| Form 990 or 990-EZ | May 15 (or extension) | GKM annual summary + Stripe settlement reports |
| State charitable registration renewals | Varies by state | Organization records |
| Donor acknowledgment letters ($250+) | By Jan 31 of following year | Auto-generated by system on Jan 2nd |
| 1099-NEC (if applicable to contractors) | Jan 31 | N/A unless GKM pays contractors |

### C. For Sovereign Sanctuary (For-Profit Entity)

#### Token pack revenue

Token pack purchases ($3–$125) are **product revenue** for Sovereign Sanctuary. Tokens are a digital good consumed on the platform.

| Account | Debit | Credit |
|---|---|---|
| Cash (Stripe settlement) | $X.XX | |
| Token Pack Revenue | | $X.XX |

#### Token sharing fee — pass-through treatment

Sovereign Sanctuary collects the sharing fee via Stripe but immediately donates 100% to GKM. This creates two entries:

| Account | Debit | Credit |
|---|---|---|
| Cash (Stripe — sharing fee collected) | $X.XX | |
| Charitable Contribution Expense | $X.XX | |
| Cash (remitted to GKM) | | $X.XX |
| Payable to GKM | | $X.XX |

Alternatively, if Sovereign Sanctuary acts purely as a **collection agent** for GKM (recommended structure), the fee never touches Sovereign Sanctuary's P&L:

| Account | Debit | Credit |
|---|---|---|
| Cash (Stripe — sharing fee collected) | $X.XX | |
| Due to GKM (liability) | | $X.XX |

**Recommendation**: Treat Sovereign Sanctuary as a collection agent to avoid recognizing revenue and a corresponding charitable deduction. This simplifies Sovereign Sanctuary's tax return and avoids charitable deduction limitations. The board should confirm this treatment with legal counsel.

#### Free month reward — cost to Sovereign Sanctuary

The free month awarded to generous sharers is a **marketing/customer loyalty expense** for Sovereign Sanctuary:

| Account | Debit | Credit |
|---|---|---|
| Marketing Expense — Loyalty Rewards | $49.00* | |
| Deferred Revenue (or Revenue Contra) | | $49.00* |

*Based on the Inner Chamber tier price ($49/month). The actual cost to Sovereign Sanctuary is the marginal cost of service (AI compute, infrastructure) rather than the list price.

#### Sovereign Sanctuary's charitable deduction

If Sovereign Sanctuary treats the fees as pass-through revenue (recognizing it and then donating it), the corporate charitable deduction is limited to **10% of taxable income** (IRC §170(b)(2)). This is another reason to prefer the collection agent treatment.

---

## Part V: Data Systems & Audit Trail

### Database Tables

The system maintains a complete, immutable audit trail across four database tables:

#### 1. `token_shares` — Transaction Record

Every peer-to-peer token transfer is recorded with:

| Column | Description |
|---|---|
| `id` | Unique transaction UUID |
| `sharer_username` | Who sent the tokens |
| `receiver_username` | Who received the tokens |
| `tokens_shared` | Number of tokens transferred |
| `share_fee_cents` | Fee charged (in cents) |
| `stripe_payment_id` | Stripe PaymentIntent ID for the fee |
| `donation_eligible` | Whether the fee qualifies as a GKM donation (default: TRUE) |
| `created_at` | Timestamp of the transaction |

#### 2. `gkm_donations` — Donation Ledger

Each share fee is individually recorded as a donation entry:

| Column | Description |
|---|---|
| `id` | Unique donation UUID |
| `username` | Donor's platform username |
| `donation_amount_cents` | This donation amount (in cents) |
| `source` | Origin of donation (currently always `token_share`) |
| `cumulative_total_cents` | Running total for this donor in this tax year |
| `receipt_sent` | Whether a receipt has been issued for this donation |
| `receipt_sent_at` | When the receipt was sent |
| `tax_year` | Calendar year this donation applies to |
| `stripe_payment_id` | Corresponding Stripe PaymentIntent ID |
| `created_at` | Timestamp |

#### 3. `gkm_annual_receipts` — Year-End Receipt Tracking

One row per donor per tax year, created when receipts are generated:

| Column | Description |
|---|---|
| `username` | Donor's platform username |
| `tax_year` | Calendar year |
| `total_donations_cents` | Sum of all donations for the year |
| `sent_at` | When the receipt was delivered |
| Unique constraint | `(username, tax_year)` — prevents duplicate receipts |

#### 4. `gkm_discounts` — Promotional Discount Tracking

Records any discounts or promotional credits issued through GKM:

| Column | Description |
|---|---|
| `username` | Recipient |
| `discount_type` | Category of discount |
| `amount_cents` | Value of discount |
| `description` | Free-text explanation |
| `applied_at` | Timestamp |

### Cross-Reference with Stripe

Every donation has a `stripe_payment_id` that maps directly to a Stripe PaymentIntent. This provides a three-way reconciliation:

```
GKM Donation Ledger (gkm_donations.stripe_payment_id)
        ↕
Stripe Dashboard (PaymentIntent ID)
        ↕
Token Share Record (token_shares.stripe_payment_id)
```

A CPA can verify any donation by:

1. Pulling the donation from `gkm_donations`
2. Matching the `stripe_payment_id` to the Stripe dashboard
3. Confirming the corresponding `token_shares` entry shows the same fee amount

### Automated Reports Available

| Report | Access | Frequency |
|---|---|---|
| Annual Donation Summary (per donor) | `/api/gkm/annual-summary?year=YYYY` | On-demand |
| All Donations (with date range) | `/api/gkm/donations?year=YYYY` | On-demand |
| Per-User Donation History | `/api/gkm/donations/{username}` | On-demand |
| Token Sharing Activity | `/api/gkm/sharing-activity?days=N` | On-demand |
| Batch Receipt Generation | `/api/gkm/annual-receipts/generate` | Auto: Jan 2nd |

All reports are accessible through the GKM tab in the Sovereign Command admin dashboard (admin-only access).

---

## Part VI: Compliance Summary

### For the Board

| Requirement | Status |
|---|---|
| 501(c)(3) determination letter | Active (EIN: 84-3879515) |
| No goods/services exchanged for donations | Confirmed — receipt language includes this statement |
| Donor acknowledgment for gifts $250+ | Automated — system generates receipts annually |
| Immutable donation ledger | Database enforced — cumulative totals are monotonically increasing |
| Stripe payment trail for every donation | Every donation has a `stripe_payment_id` |
| Separation from for-profit entity | GKM receives funds; Sovereign Sanctuary operates the platform |
| Annual receipt automation | Runs January 2nd for prior tax year |
| Idempotent receipt generation | UNIQUE constraint on (username, tax_year) prevents duplicates |

### For the CPA

| Item | Where to Find It |
|---|---|
| Gross donation revenue for the year | `GET /api/gkm/annual-summary?year=YYYY` |
| Individual donor records | `GET /api/gkm/donations/{username}` |
| Stripe settlement reconciliation | Match `stripe_payment_id` in donation records to Stripe dashboard |
| Receipt status (sent/unsent) | `receipt_sent` and `receipt_sent_at` columns in `gkm_donations` |
| Number of qualifying donors ($250+) | Annual summary shows `receipt_eligible` flag per donor |
| Discount/scholarship activity | `GET /api/gkm/discounts` and `GET /api/gkm/scholarships` |

---

## Part VII: Board Governance Recommendations

1. **Annual audit**: Reconcile total `gkm_donations` amounts against Stripe settlement reports at year-end.

2. **Stripe fee allocation**: Decide whether Stripe processing fees (~2.9% + $0.30) are absorbed by GKM as fundraising expenses or passed through to Sovereign Sanctuary as a platform cost. Document this decision in board minutes.

3. **Collection agent agreement**: Execute a written agreement between GKM and Sovereign Sanctuary formalizing that Sovereign Sanctuary collects token sharing fees as an agent of GKM. This clarifies the pass-through treatment for both entities' tax returns.

4. **Scholarship fund governance**: If GKM funds scholarships (subsidized platform access), establish written criteria for eligibility and document the approval process for each allocation.

5. **Receipt threshold review**: The current $250 threshold mirrors the IRS requirement for written acknowledgment. The board may choose to issue receipts for all donors regardless of amount as a best practice.

6. **Quarterly financial review**: Use the GKM dashboard's sharing activity and donation summary reports for quarterly board review of donation inflows, donor count trends, and scholarship distributions.

---

*Document version: February 2026*
*Generated from system configuration and codebase at Sovereign Sanctuary platform v1.0*
*This document is for informational purposes and does not constitute legal or tax advice. Consult qualified legal and tax professionals for entity-specific guidance.*
