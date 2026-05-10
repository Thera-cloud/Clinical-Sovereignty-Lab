# Social OAuth scope vs. product alignment — SkyEye adapters

**Date:** 2026-05-07  
**Scope:** Read-only audit of `backend/app/services/platforms/*.py` (+ registry + rules).  
**Note:** `threads.py` does **not** exist; registry lists 9 platform keys in `_ADAPTER_MAP` (`__init__.py`).

---

## Section A — Per-platform audit table

| Platform | File | `get_oauth_url()` — scope string (verbatim) | Auth endpoint | Product requirement (from code / rules / template) | State | Risk |
|----------|------|-----------------------------------------------|---------------|-----------------------------------------------------|-------|------|
| **x** | `x_twitter.py` | `tweet.read tweet.write users.read offline.access` | `https://x.com/i/oauth2/authorize` | X Developer Portal project; write + offline typically need **approved/use-case** access, not anonymous dev defaults. Code comment: X API v2 + OAuth 2.0 PKCE. | **B** | High if project is basic/unapproved |
| **linkedin** | `linkedin.py` (`LinkedInAdapter`) | `openid profile email w_member_social r_member_social` | `https://www.linkedin.com/oauth/v2/authorization` | **Open ID** product; **Share on LinkedIn** (`w_member_social`); **`r_member_social`** = **Community Management API** (separate app per `.cursor/rules/linkedin-dual-credential-architecture.mdc`). | **B** | **High** — mixed posting + community read on one app |
| **linkedin_community** | `linkedin.py` (`LinkedInCommunityAdapter`) | `openid profile email w_member_social` | same | Second app “Sovereign Sanctuary Engine 1.0”; Community Management API approval. Rule documents client id example + redirect `.../linkedin_community/callback`. | **B** | High until product approved |
| **instagram** | `instagram.py` | *(no `scope` query param)* — `config_id=1458216979214040`, `override_default_response_type=true` | `https://www.facebook.com/v21.0/dialog/oauth` | **Facebook Login for Business** use case; `.cursor/rules/meta-instagram-oauth-checklist.mdc` lists required permissions: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_comments`, `instagram_business_manage_insights`, `business_management`. `.env.template`: `INSTAGRAM_APP_ID`, etc. | **B** | High if use case / App Review / publish incomplete |
| **facebook** | `facebook.py` | `pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,pages_manage_metadata` | `https://www.facebook.com/v19.0/dialog/oauth` | Meta **Pages** permissions; production use usually requires **app review** / business assets. Shares credential vars with Meta ecosystem. | **B** | High without reviewed app + Page roles |
| **youtube** | `youtube.py` | `https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl` | `https://accounts.google.com/o/oauth2/v2/auth` | Google Cloud OAuth client + **YouTube Data API v3** enabled; module doc. Sensitive scopes may need **verification** for broad user base. | **B** | Medium–high (verification / consent) |
| **tiktok** | `tiktok.py` | `user.info.basic,video.publish,video.list,comment.list,comment.list.manage` | `https://www.tiktok.com/v2/auth/authorize/` | **Content Posting API** class product; `.env.template` `TIKTOK_CLIENT_KEY/SECRET`. Not a “single checkbox” default app. | **B** | High if sandbox approval missing |
| **pinterest** | `pinterest.py` | `boards:read,boards:write,pins:read,pins:write,user_accounts:read` | `https://www.pinterest.com/oauth/` | Pinterest API v5 app; standard marketing integration — still **app registration** and token exchange. No dedicated rule file found. | **A/B** | Medium (org approval / Standard access varies) |
| **reddit** | `reddit.py` | `identity,submit,read,privatemessages,modflair,modposts,edit,flair,history,mysubreddits` | `https://www.reddit.com/api/v1/authorize` | Reddit app type + many **mod*** scopes imply **elevated** use; not default “installed app read-only”. | **B** | High — scope breadth |

**State key:** **A** = typical default developer setup; **B** = elevated product/review; **C** = unclear from repo.

---

## Section B — High-risk findings (STATE B)

| Platform | Likely culprit scope(s) / mechanism | Alignment fix |
|----------|--------------------------------------|---------------|
| **linkedin** | `r_member_social` on **posting** app | **Code:** drop `r_member_social` from `LinkedInAdapter`; use `linkedin_community` OAuth for CM scopes. **Portal:** ensure OpenID + Share products on posting app. |
| **linkedin_community** | Entire flow gated on **Community Management** product | **Portal:** approve CM API on second app; correct redirect `linkedin_community/callback`. |
| **instagram** | Permissions live in **Login for Business** config, not URL | **Portal:** verify use case includes rule’s five `instagram_business_*` + `business_management`. **Code:** mismatch if `config_id` doesn’t match dashboard. |
| **facebook** | `pages_manage_*`, `pages_read_engagement` | **Portal:** app review + admin granted Page tasks. **Code:** optional scope minimization if some features unused. |
| **x** | `tweet.write`, `offline.access` | **Portal:** project access tier. **Code:** cannot post without write scope — no drop without feature loss. |
| **youtube** | `youtube.force-ssl` | **Portal:** GCP consent screen + API enablement. |
| **tiktok** | `video.publish`, `comment.list.manage` | **Portal:** Content Posting product / sandbox. |
| **reddit** | `modposts`, `modflair`, `privatemessages`, etc. | **Code:** trim to minimal scopes for SkyEye use (if read-only not needed). **Portal:** app type must allow requested scopes. |

---

## Section C — Recommended fix scope

- **Batch (single PR theme):** “Scope minimization + dual-app discipline” — **LinkedIn** is the clearest **code** fix; **Reddit** is second if prod only needs submit/read.
- **Sequential / operator:** **Meta (Instagram/Facebook)**, **TikTok**, **Google**, **X**, **Pinterest** are mostly **developer-portal** alignment (products, review, redirect URIs, API enablement); code changes alone cannot fix missing products.
- **Class of failure (like LinkedIn):** Any adapter that bundles **disjoint provider products** in one `scope` string (or one Meta use case) can fail at **authorize** before callback — same symptom class.

---

## Section D — Reference cross-check (rules / docs vs code)

| Reference | Says | Code reality | Violation? |
|-----------|------|--------------|------------|
| `.cursor/rules/linkedin-dual-credential-architecture.mdc` | Posting app scopes: `w_member_social`; community app: `w_member_social`, `r_member_social` (two apps) | `LinkedInAdapter` requests **`r_member_social`** alongside posting scopes on **one** client | **Yes** — scope model violated |
| `.cursor/rules/meta-instagram-oauth-checklist.mdc` | Lists five `instagram_business_*` + `business_management`; `config_id` required | `get_oauth_url` has `config_id`; **no explicit `scope` param** (permissions from Meta configuration) | **Partial** — operator must match checklist in dashboard; not literal string in code |
| `.cursor/rules/social-engagement-architecture.mdc` | Per-platform adapter methods | Aligns with adapters existing | No scope detail |
| `.env.template` | `PUBLIC_BASE_URL`, platform client vars | Hints credentials only, not scope | N/A |
| `docs/` | No comprehensive OAuth scope matrix found beyond scattered mentions | — | Gaps |

---

**Registry note:** Supported keys: `tiktok`, `instagram`, `youtube`, `reddit`, `linkedin`, `linkedin_community`, `facebook`, `pinterest`, `x` (`__init__.py`).
