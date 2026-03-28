# R2 Custom Domain + Smart Tiered Cache Setup

## Goal

Put a custom domain (`cdn.sovereignsanctuary.net`) in front of R2 buckets so
that avatars, session charts, PDFs, classroom videos, and exports are served
through Cloudflare's CDN with Smart Tiered Cache — reducing R2 Class A/B
operation costs and egress to near-zero for repeated reads at infinite scale.

## Architecture

```
Client → cdn.sovereignsanctuary.net (Cloudflare CDN + Smart Tiered Cache)
           ↓ cache MISS only
         R2 bucket (nate-vault)
           ↓
         origin response → cached at edge (up to 30 days)
```

Repeated reads never hit R2 — Cloudflare serves from edge cache. Smart Tiered
Cache adds an upper-tier datacenter layer that further reduces R2 origin pulls.

## Step 1: Connect Custom Domain to R2 Bucket

1. Go to **Cloudflare Dashboard** → **R2 Object Storage** → **nate-vault**
2. Click **Settings** tab
3. Under **Public Access** → **Custom Domains** → click **Connect Domain**
4. Enter: `cdn.sovereignsanctuary.net`
5. Cloudflare auto-creates a CNAME DNS record pointing to the R2 bucket
6. Status will show **Initializing** → wait ~60s → refresh → **Active**
7. If stuck on Initializing, verify DNS propagation and retry

## Step 2: Enable Smart Tiered Cache

1. Go to **Cloudflare Dashboard** → **sovereignsanctuary.net** zone
2. Navigate to **Caching** → **Configuration** → **Tiered Cache**
3. Select **Smart Tiered Cache** (automatic)
   - This picks the optimal upper-tier datacenter nearest to your R2 data
   - Free with Pro/Business plans, included with Workers Paid
4. Save changes

## Step 3: Verify Cache Rules

After custom domain is Active:

```bash
# Verify an object is served through CDN
curl -sI https://cdn.sovereignsanctuary.net/test-object.png

# Expected headers:
# cf-cache-status: HIT (after first request)
# cf-r2-bucket: nate-vault
# cache-control: public, max-age=2592000
```

## Step 4: Configure Cache Rules (Cloudflare Dashboard)

Go to **Rules** → **Cache Rules** and create:

### Rule: R2 CDN Long Cache
- **When**: Hostname equals `cdn.sovereignsanctuary.net`
- **Then**:
  - Cache eligibility: **Eligible for cache**
  - Edge TTL: **Override** → 30 days (2592000s)
  - Browser TTL: **Override** → 7 days (604800s)
  - Respect Strong ETags: On

This ensures:
- First request: Class B read from R2 (cache MISS)
- All subsequent requests: served from edge (FREE, no R2 ops)
- Smart Tiered Cache: even cache MISSes at edge may be HITs at upper tier

## Step 5: Update Backend to Use CDN URLs

The backend generates URLs for stored R2 objects. Update these to point to
the CDN domain instead of hitting the API directly:

```python
CDN_BASE = "https://cdn.sovereignsanctuary.net"

def get_cdn_url(r2_key: str) -> str:
    return f"{CDN_BASE}/{r2_key}"
```

Content types served via CDN:
- Avatars: `avatars/{user_id}.{ext}`
- Session charts: `sessions/{session_id}/chart.png`
- DOJO assessment PDFs: `dojo/assessments/{id}.pdf`
- PM exports: `exports/{filename}`
- Classroom videos: `classroom/{session_id}/{filename}`
- Coach folder files: `coach-folders/{coach_id}/{filename}`

## Cost Impact at Scale

| Users | Without CDN (R2 direct) | With CDN + Tiered Cache |
|-------|------------------------|------------------------|
| 1,000 | ~$2/mo | ~$0.10/mo |
| 10,000 | ~$20/mo | ~$0.50/mo |
| 100,000 | ~$200/mo | ~$2/mo |
| 1,000,000 | ~$2,000/mo | ~$5/mo |

The cache hit ratio approaches 99%+ for static assets (avatars, PDFs).
R2 Class A ($4.50/M) and Class B ($0.36/M) operations drop to near-zero
because the CDN absorbs all repeated reads.

## DNS Record (Auto-Created)

| Type | Name | Target | Proxy |
|------|------|--------|-------|
| CNAME | cdn | `<bucket>.r2.cloudflarestorage.com` | Yes (orange cloud) |

The proxy MUST be enabled (orange cloud) for caching to work.
