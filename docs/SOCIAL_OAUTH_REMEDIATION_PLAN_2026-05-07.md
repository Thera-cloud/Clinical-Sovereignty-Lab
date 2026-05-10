# Social OAuth remediation — Path C (minimum scopes now, elevated access documented)

**Date:** 2026-05-07  
**Basis:** `docs/SOCIAL_OAUTH_SCOPE_AUDIT_2026-05-07.md` (STATE **B** and tightly related **A/B** platforms).  
**Path C:** Ship **minimum scopes that match what the operator’s apps already have** (or can get without new products), and **document** separate portal tracks to regain full capability.

**Legend — operator action:**  
- **Fix code now** — low loss, unblocks OAuth quickly.  
- **Portal first** — code cuts would break core SkyEye behavior; waiting for approval is correct.  
- **Both** — narrow code + parallel portal application.

---

## 1. `linkedin` — `LinkedInAdapter` (posting app)

### 1.1 Code fix (drop unapproved scopes)

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/linkedin.py` — **line 312** (`params["scope"]`) |
| **Current** | `openid profile email w_member_social r_member_social` |
| **Recommended (minimum)** | `openid profile email w_member_social` |
| **Lost if dropped** | **`r_member_social`:** reading member/social graph and **Community Management–class** reads on the **posting** token. Per architecture, those flows should use **`linkedin_community`** + community token anyway — **not** the posting app. |

### 1.2 Provider portal (elevated / alignment)

| Field | Value |
|--------|--------|
| **Provider** | LinkedIn Developers |
| **Apply for** | On **posting** app: **Sign In with LinkedIn / OpenID**, **Share on LinkedIn** (`w_member_social`). Ensure redirect URI matches callback. |
| **Review time** | **~0–3 business days** if products already enabled; **longer** if new app or compliance review. (Indicative only.) |
| **Restored after approval** | Stable posting + identity; **not** `r_member_social` on this app — that stays on the **second** app per `.cursor/rules/linkedin-dual-credential-architecture.mdc`. |

### 1.3 Re-expansion

| Item | Detail |
|------|--------|
| **When approved** | Do **not** add `r_member_social` back to `LinkedInAdapter`. Instead complete **`linkedin_community`** OAuth. |
| **Code** | If Community app is approved and comments/reactions need `r_member_social`, add it to **`LinkedInCommunityAdapter`** `get_oauth_url` (currently **line 1097** lacks `r_member_social` — may be needed after CM API is live). |
| **Tests** | Add a **unit or contract test** that asserts `LinkedInAdapter` scope string **excludes** `r_member_social`; optional snapshot test for `LinkedInCommunityAdapter` once finalized. |

### 1.4 Operator recommendation

**Both** — **fix code immediately** (drop `r_member_social` on posting adapter) **and** keep **linkedin_community** portal work in parallel.

---

## 2. `linkedin_community` — `LinkedInCommunityAdapter`

### 2.1 Code fix (minimum scopes “now”)

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/linkedin.py` — **line 1097** |
| **Current** | `openid profile email w_member_social` |
| **Recommended (minimum for “authorize succeeds\"\")** | **No further reduction** without losing CM features: OpenID + `w_member_social` is already the **narrow** community-app string in code. Removing `w_member_social` breaks write-side CM actions. |
| **Lost if over-trimmed** | Dropping `w_member_social` loses posting/management actions that depend on that product. |

**Path C nuance:** If OAuth still fails, the blocker is almost certainly **missing Community Management API on that app**, not an overbroad scope string.

### 2.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | LinkedIn Developers (second app) |
| **Apply for** | **Community Management API** product; redirect `https://api.sovereignsanctuary.net/api/skyeye/platforms/linkedin_community/callback` (per rule). |
| **Review time** | **Often weeks** (depends on LinkedIn; indicative). |
| **Restored** | OAuth completes; session engine / observer can use community token for **`_social_actions_token`** paths. |

### 2.3 Re-expansion

| Item | Detail |
|------|--------|
| **After CM approval** | Evaluate adding **`r_member_social`** to **line 1097** if read-side social/comment APIs require it (align with LinkedIn docs + rule intent). |
| **Tests** | Assert community scope string matches allowlist; regression test if `r_member_social` is added later. |

### 2.4 Operator recommendation

**Portal first** (primary). **Code** only after docs confirm **`r_member_social`** is required for your CM flows — then **small additive change** at line 1097.

---

## 3. `instagram` — `InstagramAdapter`

### 3.1 Code fix

| Field | Value |
|--------|--------|
| **File:line** | **No `scope` in URL** — permissions are driven by **`config_id`** and Meta app configuration: `instagram.py` **lines 162–169**. |
| **Current** | Implicit permissions via Facebook Login for Business use case. |
| **Recommended (minimum)** | **Portal:** trim the Meta **use case / permissions** to the smallest set that still allows **content publish + comments** you actually use (per `.cursor/rules/meta-instagram-oauth-checklist.mdc`: e.g. `instagram_business_basic`, `instagram_business_content_publish`, …). |
| **Lost** | Removing **manage_comments** / **insights** in portal disables those API calls in SkyEye. |

### 3.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | Meta Developer (Facebook Login for Business) |
| **Apply for** | App **Published**; correct **config_id**; **Advanced Access** / App Review for needed `instagram_business_*` + `business_management`. |
| **Review time** | **~Days–weeks** (Meta queue). |
| **Restored** | Full IG marketing + comments + insights per approved permissions. |

### 3.3 Re-expansion

| Item | Detail |
|------|--------|
| **After approval** | Re-enable trimmed permissions in Meta dashboard; **no code change** unless `config_id` or API version must change. |
| **Tests** | Integration or smoke test: OAuth returns token; optional checklist test that `META_API_VERSION` matches rule (`v21.0`). |

### 3.4 Operator recommendation

**Portal first.** **Code** only if `config_id` / API version drift from checklist.

---

## 4. `facebook` — `FacebookAdapter`

### 4.1 Code fix (optional tiered minimization)

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/facebook.py` — **line 149** |
| **Current** | `pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,pages_manage_metadata` |
| **Recommended (minimum viable posting)** | `pages_show_list,pages_manage_posts` — **only if** you do **not** need engagement APIs, comment moderation, or metadata management via Graph. |
| **Lost** | **`pages_read_engagement`:** analytics/engagement reads. **`pages_manage_engagement`:** moderating/responding at Page engagement layer. **`pages_manage_metadata`:** Page setting/metadata updates. |

### 4.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | Meta |
| **Apply for** | **pages_manage_posts** (+ any kept scopes) via App Review; Page roles for the authenticating user. |
| **Review time** | **Days–weeks.** |
| **Restored** | Full Page publishing + engagement + analytics alignment. |

### 4.3 Re-expansion

| Item | Detail |
|------|--------|
| **After approval** | Add back dropped `pages_*` scopes **one group at a time** at line 149 as features are enabled. |
| **Tests** | Comment or constant documenting **required scopes per feature**; optional grep test that scope string includes mandatory subsets for enabled features. |

### 4.4 Operator recommendation

**Both** — **apply for permissions** for the scopes you need long-term; **optionally** **fix code** to a **smaller** set **only after** confirming SkyEye code paths don’t call removed permissions (audit `facebook.py` + session engine).

---

## 5. `youtube` — `YouTubeAdapter`

### 5.1 Code fix (possible split)

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/youtube.py` — **line 170** |
| **Current** | `https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl` |
| **Recommended (minimum trial)** | `https://www.googleapis.com/auth/youtube` only — **if** all used Data API v3 paths work without `force-ssl`. |
| **Lost** | **`youtube.force-ssl`:** operations Google classifies as account-sensitive / certain write paths; dropping may break uploads, comments, or captions depending on API usage. **Verify against live calls before committing.** |

### 5.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | Google Cloud Console |
| **Apply for** | YouTube Data API v3 enabled; OAuth consent; **sensitive scope verification** if user base is external. |
| **Review time** | **Days–weeks** if verification required. |
| **Restored** | Full channel management + posting after scopes + verification align. |

### 5.3 Re-expansion

| Item | Detail |
|------|--------|
| **After confirmation** | Restore `youtube.force-ssl` on line 170 when needed. |
| **Tests** | Document required scopes per method group; optional test that scope env or constant matches doc. |

### 5.4 Operator recommendation

**Both** — **try** minimal `youtube` scope in a **branch** and run **one** real upload/comment path; if anything fails, **portal + keep force-ssl** without code removal.

---

## 6. `tiktok` — `TikTokAdapter`

### 6.1 Code fix

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/tiktok.py` — **line 156** |
| **Current** | `user.info.basic,video.publish,video.list,comment.list,comment.list.manage` |
| **Recommended (minimum for SkyEye posting)** | **Cannot** drop `video.publish` without losing autonomous posting. **Optional trim:** `comment.list.manage` first if you only need read-only comment polling — **verify** `notification_observer` / session engine don’t reply via TikTok. |
| **Lost if comment manage removed** | Comment moderation / reply flows that require manage scope. |

### 6.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | TikTok for Developers |
| **Apply for** | **Content Posting API** (and comment scopes as needed); sandbox → production. |
| **Review time** | **Highly variable** (indicative: **weeks**). |
| **Restored** | Authorized URL succeeds; posting + comments per approved products. |

### 6.3 Re-expansion

| Item | Detail |
|------|--------|
| **After approval** | Re-add any temporarily removed comment scopes at line 156. |
| **Tests** | Golden-string test for scope set + feature flag mapping (“posting-only” vs “full”). |

### 6.4 Operator recommendation

**Portal first** for **`video.publish`**. **Both** only if you intentionally **pause** comment management via a **narrower** scope while posting stays approved.

---

## 7. `x` — `XTwitterAdapter`

### 7.1 Code fix

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/x_twitter.py` — **line 213** |
| **Current** | `tweet.read tweet.write users.read offline.access` |
| **Recommended (minimum for SkyEye)** | **No reduction** for autonomous marketing: **`tweet.write`** is essential; **`offline.access`** needed for refresh tokens. **`tweet.read` / `users.read`** support posting + identity. |
| **Lost if trimmed** | Any removal breaks SkyEye’s designed posting or token refresh behavior. |

### 7.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | X Developer Portal |
| **Apply for** | Project **Elevated** / appropriate access for **read + write** + **offline** per X policy. |
| **Review time** | **Hours–days** in many cases; can extend. |
| **Restored** | OAuth proceeds; posting and renewals work. |

### 7.3 Re-expansion

| Item | Detail |
|------|--------|
| **After approval** | N/A — keep full scope set. |
| **Tests** | Regression test: scope string unchanged without deliberate product decision. |

### 7.4 Operator recommendation

**Portal first** — **do not** drop scopes for Path C on X without changing product requirements.

---

## 8. `pinterest` — `PinterestAdapter` (A/B in audit; included for Path C consistency)

### 8.1 Code fix (optional)

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/pinterest.py` — **line 151** |
| **Current** | `boards:read,boards:write,pins:read,pins:write,user_accounts:read` |
| **Recommended (read-only monitoring)** | e.g. `boards:read,pins:read,user_accounts:read` — **only if** SkyEye must connect before write approval. |
| **Lost** | Creating/updating pins or boards via API. |

### 8.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | Pinterest Developers |
| **Apply for** | Standard API access / any required **elevated** scopes for write. |
| **Review time** | **Days–weeks** (indicative). |
| **Restored** | Full read/write marketing automation. |

### 8.3 Re-expansion

Restore write scopes on line 151 after approval.

### 8.4 Operator recommendation

**Fix code now** only for a **deliberate read-only** mode; otherwise **portal first** to keep write paths.

---

## 9. `reddit` — `RedditAdapter`

### 9.1 Code fix

| Field | Value |
|--------|--------|
| **File:line** | `backend/app/services/platforms/reddit.py` — **line 200** |
| **Current** | `identity,submit,read,privatemessages,modflair,modposts,edit,flair,history,mysubreddits` |
| **Recommended (minimum for post + read + reply)** | `identity,read,submit,edit,flair,history` — **drop** `privatemessages,modflair,modposts,mysubreddits` **if** you do **not** use mod tools or DM flows via this integration. |
| **Lost** | **Mod** features (`moderate_content`-style paths), **private messages**, **mysubreddits** convenience. Re-add **modposts** if moderator removal APIs are required. |

### 9.2 Provider portal

| Field | Value |
|--------|--------|
| **Provider** | Reddit (old Reddit prefs / dev portal) |
| **Apply for** | App type that allows **submit** + **read**; if mod scopes return, **approved** mod use case. |
| **Review time** | **Instant to days** depending on scope class. |
| **Restored** | Full moderation + messaging. |

### 9.3 Re-expansion

Re-add removed scopes at line 200 when product needs them; run smoke tests on `post_content` / `reply_to_comment` / `moderate_content`.

### 9.4 Operator recommendation

**Both** — **fix code** to a **documented minimal** set after tracing which methods SkyEye actually uses; **portal** if Reddit rejects reduced set for app type.

---

## Summary table — operator decision

| Platform | Primary Path C action |
|----------|------------------------|
| linkedin | **Both** — drop `r_member_social` at line 312; CM via separate app |
| linkedin_community | **Portal first**; optional add `r_member_social` at 1097 after CM live |
| instagram | **Portal first** (permissions on use case) |
| facebook | **Both** — optional scope trim at 149 + portal for reviews |
| youtube | **Both** — trial drop `force-ssl` only with API verification |
| tiktok | **Portal first**; optional trim comment manage |
| x | **Portal first** — keep line 213 |
| pinterest | **Portal first** unless read-only mode |
| reddit | **Both** — trim mod/PM scopes at 200 if unused |

---

## Cross-cutting: prevent scope regression

1. **Single source of truth** — e.g. module-level constants `LINKEDIN_POSTING_SCOPES`, `REDDIT_MINIMAL_SCOPES`, with comments pointing to this doc.  
2. **Tests** — snapshot or equality tests on scope strings; fail CI if changed without updating `docs/SOCIAL_OAUTH_SCOPE_AUDIT_*.md` / this plan.  
3. **.cursor/rules** — update `linkedin-dual-credential-architecture.mdc` if line 1097 gains `r_member_social` after approval.

---

*Plan only — no code changes in this commit.*
