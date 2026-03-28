# Secret Store System-Wide Architecture

This document defines the canonical secret model for Little Nate, the dual-CLI pipeline, and edge replication-aware services.

## Active Secret Store

- **Cloudflare Secret Store ID**: `32a36b47eb324b7099e76c09bee80e8c`
- **Primary use**: runtime secrets for Workers and CLI-Cloud control-plane access
- **Rule**: replicated systems (D1/KV/R2/PostgreSQL) may store secret metadata only, never secret values

## Best-Long-Term Runtime Architecture

1. Keep API multi-worker for throughput.
2. Move background agents to a single-runner process/container (1 replica).
3. Use Redis distributed lock for trust-window claim (`SET NX EX`).
4. Use DB idempotency ledger for trust runs (`UNIQUE(window_key, run_type)`).
5. Manual `/trigger` uses same lock key (window-based) as scheduled runs.

## Secret Catalog (copy-ready)

Format requested:
1. Name
2. Permission (`Workers` or `AI Gateway`)
3. Value
4. Comment

### Core Trust / AI / Billing

| Name | Permission | Value | Comment |
|---|---|---|---|
| `SOVEREIGN_AI_AZURE_OPENAI_KEY` | AI Gateway | `<azure_openai_api_key>` | Azure OpenAI key for inference fallback and policy-checked AI Gateway routes. Rotate every 90 days. |
| `SOVEREIGN_AI_HMAC_SIGNING_KEY` | Workers | `<32+ byte random base64url>` | HMAC signing key for internal Worker-to-origin request signatures. Used by summon and trust-sensitive internal calls. |
| `SOVEREIGN_AUDIT_CLIENT_SYNTHETIC_TOKEN` | Workers | `<strong random token>` | Synthetic client auth token for nightly audit pathways only. Never valid for human sessions. Rotate monthly. |
| `SOVEREIGN_BILLING_STRIPE_SECRET_LIVE` | Workers | `<stripe_live_secret_key>` | Production Stripe secret for real billing flows. Scope only to billing/webhook workers. Rotate quarterly. |
| `SOVEREIGN_BILLING_STRIPE_SECRET_TEST` | Workers | `<stripe_test_secret_key>` | Stripe test key for synthetic audit and non-production verification paths. |
| `SOVEREIGN_EMAIL_SENDGRID_API_KEY` | Workers | `<sendgrid_api_key>` | SendGrid key for trust reports and platform notifications. Least-privilege scopes only. |
| `SOVEREIGN_SMS_TWILIO_AUTH_TOKEN` | Workers | `<twilio_auth_token>` | Twilio auth token for SMS notification dispatch. Use Verify APIs for OTP flows. |

### Data Plane (Private Network)

| Name | Permission | Value | Comment |
|---|---|---|---|
| `SOVEREIGN_DB_POSTGRES_CONNECTION_STRING` | Workers | `postgresql://<user>:<pass>@<private_host>:5432/<db>` | Private Postgres DSN for controlled workers; no public exposure. |
| `SOVEREIGN_CACHE_REDIS_CONNECTION_STRING` | Workers | `redis://:<password>@<private_host>:6379` | Redis DSN for distributed locks, state gates, and orchestration idempotency. |
| `SOVEREIGN_STORAGE_R2_ACCESS_KEY_ID` | Workers | `<r2_access_key_id>` | R2 API access key id for worker-side object operations. |
| `SOVEREIGN_STORAGE_R2_SECRET_ACCESS_KEY` | Workers | `<r2_secret_access_key>` | R2 API secret access key. Rotate with dual-key overlap window. |
| `SOVEREIGN_STORAGE_AZURE_BLOB_SAS_TOKEN` | Workers | `<azure_blob_sas_token>` | SAS token for scoped blob write/read where Azure fallback is required. Auto-expiry required. |

### Webhook / Edge Integrity

| Name | Permission | Value | Comment |
|---|---|---|---|
| `SOVEREIGN_WEBHOOK_STRIPE_SECRET` | Workers | `<stripe_webhook_signing_secret>` | Stripe webhook signature validation secret; used in webhook gateway only. |
| `SOVEREIGN_WEBHOOK_ZOOM_SECRET` | Workers | `<zoom_webhook_secret>` | Zoom webhook secret for signature verification. |
| `SOVEREIGN_COHERENCE_HMAC_SECRET` | Workers | `<coherence_hmac_secret>` | HMAC secret for voice/coherence publish path anti-spoofing. |

### CLI-Cloud / CLI-Mac Interop

| Name | Permission | Value | Comment |
|---|---|---|---|
| `SOVEREIGN_INFRA_CLOUDFLARE_API_TOKEN` | Workers | `<scoped_cf_api_token>` | Scoped token for CLI-Cloud automation (deploy/read/write only required resources). |
| `SOVEREIGN_TUNNEL_WIREGUARD_CLOUD_PRIVATE_KEY` | Workers | `<wireguard_private_key_cloud_side>` | WireGuard private key for CLI-Cloud tunnel endpoint; rotate with coordinated key rollover. |
| `SOVEREIGN_CLI_INTEROP_SIGNING_KEY` | Workers | `<32+ byte random base64url>` | Signing key for CLI-to-CLI command attestations and anti-replay envelopes. |
| `SOVEREIGN_CLI_INTEROP_ENCRYPTION_KEY` | Workers | `<x25519/age_or_equivalent_private_material>` | Envelope encryption key for CLI command payload exchange metadata where needed. |

## Replication-Safe Secret Practices

- D1/KV/R2/PostgreSQL may store:
  - secret name
  - secret version
  - owner service
  - rotation policy and dates
  - last validation status
- D1/KV/R2/PostgreSQL must never store:
  - secret plaintext values
  - private key material
  - raw bearer tokens

## Optional Store Segmentation (when scaling beyond one store)

Use separate stores for blast-radius control:

1. `SOVEREIGN-CORE-RUNTIME`
2. `SOVEREIGN-BILLING`
3. `SOVEREIGN-WEBHOOKS`
4. `SOVEREIGN-CLI-CONTROL`
5. `SOVEREIGN-DATA-PLANE`
6. `SOVEREIGN-AI-GATEWAY`

Start with one store (`32a36b47eb324b7099e76c09bee80e8c`) and split once operational maturity requires stricter admin boundaries.

