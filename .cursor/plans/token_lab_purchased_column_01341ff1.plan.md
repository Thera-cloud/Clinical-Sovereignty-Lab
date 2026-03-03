---
name: Token Lab Purchased Column
overview: Add a "Purchased" column to the Token Lab All Balances table showing the cumulative quantity of extra tokens each user has bought via Stripe token packs, placed next to the existing Balance column.
todos:
  - id: backend-purchased-query
    content: Add LEFT JOIN on token_transactions to /balances endpoint to include tokens_purchased per user
    status: completed
  - id: frontend-columns
    content: Add Usage (Month) and Purchased columns to All Balances table header and body in token_lab.html
    status: completed
  - id: deploy-verify
    content: Deploy token_lab_api.py and token_lab.html, verify columns render correctly
    status: pending
isProject: false
---

# Token Lab -- Add "Purchased" Column to All Balances

## Current State

The All Balances table in [dashboard/token_lab.html](dashboard/token_lab.html) has these columns:

| Checkbox | Username | Name | Role | Tier | Balance | Family | Actions |

The [backend/app/routers/token_lab_api.py](backend/app/routers/token_lab_api.py) `/balances` endpoint (line 116) queries `users` only -- no join to `token_transactions`.

Token pack purchases are already logged in `token_transactions` with `action = 'purchase'` and `source = 'token_pack'` by the Stripe webhook handler in [backend/app/services/stripe_integration.py](backend/app/services/stripe_integration.py).

## Target State

| Checkbox | Username | Name | Role | Tier | Balance | Usage (Month) | Purchased | Family | Actions |

- **Usage (Month)**: already returned by the API as `usage_month` from `profile_data->>'token_usage_month'` but not displayed -- surface it
- **Purchased**: cumulative total of all token pack purchases for that user

## Backend Change -- `token_lab_api.py`

Modify the `/balances` endpoint SQL query to LEFT JOIN a purchase summary:

```sql
SELECT
    u.username,
    u.role,
    COALESCE(u.token_balance, 0) as token_balance,
    u.subscription_status,
    u.profile_data->>'name' as name,
    u.profile_data->>'tier' as tier,
    u.profile_data->>'family_id' as family_id,
    u.profile_data->>'company_id' as company_id,
    u.profile_data->>'token_usage_today' as usage_today,
    u.profile_data->>'token_usage_month' as usage_month,
    u.family_id as family_uuid,
    COALESCE(p.total_purchased, 0) as tokens_purchased
FROM users u
LEFT JOIN (
    SELECT username, SUM(amount) as total_purchased
    FROM token_transactions
    WHERE action = 'purchase' AND source = 'token_pack'
    GROUP BY username
) p ON p.username = u.username
ORDER BY u.token_balance DESC NULLS LAST, u.role, u.username
```

This adds `tokens_purchased` to each row without changing existing fields.

### File

- `backend/app/routers/token_lab_api.py` -- modify the SELECT in the `/balances` endpoint (~line 116-132)

## Frontend Change -- `token_lab.html`

### Table Header

Add two columns after "Balance":

```html
<th>Usage (Mo)</th>
<th>Purchased</th>
```

### Table Body

In the `tlFilterBalances()` rendering function (~line 455-480), add cells for each user:

```javascript
'<td>' + (parseInt(u.usage_month) || 0).toLocaleString() + '</td>' +
'<td>' + (parseInt(u.tokens_purchased) || 0).toLocaleString() + '</td>' +
```

The "Purchased" cell shows `0` for users who have never bought extra tokens and the cumulative total for those who have.

### File

- `dashboard/token_lab.html` -- add 2 column headers and 2 cell renderers

## No Migration Needed

The data already exists in `token_transactions`. This is a read-only query change.

## Deployment

1. Deploy `token_lab_api.py` via `scp`, restart `nate_backend`
2. Deploy `token_lab.html` to all 3 server directories (per `deployment-safety.mdc`)
3. Verify the new columns appear in the Token Lab All Balances table

