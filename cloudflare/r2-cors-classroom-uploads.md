# R2 CORS rules — direct browser → R2 multipart upload

The Coach Classroom direct-upload flow has the browser PUT chunks straight
to the R2 bucket using presigned URLs. The R2 bucket MUST advertise CORS
or the browser will block the cross-origin PUT (you'll see a `CORS policy`
error in the console and `net::ERR_FAILED`).

The two non-obvious requirements:

1. **`AllowedMethods` must include `PUT`** — that's the verb the
   presigned-part URLs use.
2. **`ExposeHeaders` must include `ETag`** — without it the browser
   strips the response header before our JS can read it, and the
   `/upload-video/complete` call will fail with
   `ETag header missing from R2 response`.

## Apply via Cloudflare dashboard (preferred)

1. Cloudflare Dashboard → R2 → `nate-vault` → **Settings** tab.
2. Scroll to **CORS Policy** → **Edit**.
3. Paste the contents of [`r2-cors-classroom-uploads.json`](./r2-cors-classroom-uploads.json).
4. Save.

## Apply via wrangler / aws CLI

If you have R2 admin-scoped S3 credentials (the production read/write key
on the backend is bucket-scoped and cannot mutate CORS):

```bash
aws s3api put-bucket-cors \
  --bucket nate-vault \
  --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com" \
  --cors-configuration file://cloudflare/r2-cors-classroom-uploads.json
```

## Diff vs the previous CORS policy

The pre-existing rule allowed only `GET, HEAD` from the same origins.
We extended ONE rule in place rather than appending a second rule — S3
CORS picks the first match, so a misordered second rule for the same
origins would never be reached for GET/HEAD requests.

| Field | Before | After | Why |
|---|---|---|---|
| `AllowedMethods` | `[GET, HEAD]` | `[GET, HEAD, PUT]` | PUT is the verb of every presigned-part URL the browser uploads to |
| `ExposeHeaders` | (absent) | `[ETag]` | The browser hides cross-origin response headers from JS by default; we need ETag to send back to /complete |
| `AllowedOrigins`, `AllowedHeaders`, `MaxAgeSeconds` | (unchanged) | (unchanged) | Existing signed-GET flow keeps working identically |

## Verify

After applying, run from any allowed origin's browser console:

```js
fetch('https://<account>.r2.cloudflarestorage.com/nate-vault/_probe/x', {
  method: 'OPTIONS',
  headers: {'Origin': location.origin, 'Access-Control-Request-Method': 'PUT'}
}).then(r => console.log(r.status, [...r.headers]));
```

You should see `Access-Control-Allow-Methods: GET, HEAD, PUT` and
`Access-Control-Expose-Headers: ETag` in the response.
