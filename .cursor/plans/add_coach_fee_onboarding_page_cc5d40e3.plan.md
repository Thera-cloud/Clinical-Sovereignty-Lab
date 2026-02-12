---
name: Add coach fee onboarding page
overview: Add a new onboarding tutorial page for coaches explaining how they'll be charged platform fees, the 30% (min $30) fee structure, 1099 contractor status, and payment modes.
todos:
  - id: add-fees-step
    content: Add 'Your Fees & Earnings' step to _coachSteps and build _buildFeesCard() widget with fee breakdown, payment modes, and 1099 info
    status: completed
  - id: rebuild-deploy-fees
    content: Rebuild Flutter web (skip index.html) + deploy web build
    status: completed
isProject: false
---

# Add Coach Fee Onboarding Page

## Change

Add a new step to the `_coachSteps` list in [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) (line ~172), inserted **after** "Client Pricing Overview" and **before** the closing bracket of the list (making it the new final step).

### New Step Data (line ~178)

```dart
{
  "title": "Your Fees & Earnings",
  "icon": "fees",
  "speech": "Let's talk business. When a client books with you, the platform takes a 30 percent fee with a 30 dollar minimum per session. You set your own rate, and you'll see the breakdown in your Financials tab. You're a 1099 independent contractor, so we collect a W-9 at signup and issue a 1099 at year-end if you earn over 600 dollars.",
  "description": "",
  "expression": "attentive",
},
```

### New Card Widget

Add a `_buildFeesCard()` method (next to `_buildPricingCard()`, around line ~606) that renders:

- **"How You Get Paid"** header
- **Platform Fee** card: "30% of your session fee (minimum $30 per session)"
- **Example breakdown**: "You charge $150/hr -> Platform fee: $45 -> You keep: $105"
- **Payment Modes** card: Two options explained -- "Coach Handles" (you collect from client, platform invoices you) vs "Platform Handles" (platform collects, pays you net)
- **1099 Status** card: "You're an independent contractor. W-9 collected at registration. 1099-NEC issued if earnings exceed $600/year."
- **Financials Tab** note: "Track all earnings, fees, and tax documents in your FINANCIALS tab."

### PageView Routing

In the `build()` method (~line 439), add a condition so `step["icon"] == "fees"` renders `_buildFeesCard()` instead of `_buildFeatureCard(step)`:

```dart
if (step["icon"] == "pricing") {
  return _buildPricingCard();
}
if (step["icon"] == "fees") {
  return _buildFeesCard();
}
return _buildFeatureCard(step);
```

## Files to Modify

- [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) only

## Deployment

- Flutter rebuild + rsync (skip index.html)
- No backend changes needed

