# Social scope usage trace — Facebook, YouTube, Reddit

**Date:** 2026-05-07  
**Mode:** Read-only trace of `backend/app/services/platforms/{facebook,youtube,reddit}.py` plus SkyEye consumers.

Provider scope ↔ permission mapping below uses Meta / Google / Reddit public documentation as of the trace date; where docs do not spell out a 1:1 line, scopes are marked **UNCERTAIN**.

---

## Facebook (`FacebookAdapter`)

### Current OAuth scope string (`get_oauth_url`)

`pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,pages_manage_metadata`

### Adapter methods (defined in `facebook.py`)

| Area | Methods |
|------|---------|
| Auth | `authenticate`, `refresh_token`, `get_oauth_url`, `handle_oauth_callback` |
| Content | `post_content` |
| Read/monitor | `get_comments`, `get_mentions`, `get_feed`, `get_own_posts` |
| Engagement | `reply_to_comment` |
| Moderation | `delete_comment`, `hide_comment` |
| Discovery/analytics | `get_follower_count`, `get_post_reactions`, `get_analytics` |
| Trending | *(inherits base `get_trending` → always `[]`)* |

### Called Graph endpoints (scope drivers)

- `GET /me`, `GET /oauth/access_token` (exchange), `GET /me/accounts` (OAuth callback)
- `POST /{page-id}/photos`, `POST /{page-id}/feed`
- `GET /{post-id}/comments`, `GET /{page-id}/tagged`, `GET /{page-id}/posts`
- `POST /{comment-id}/comments` (replies), `DELETE /{comment-id}`, `POST /{comment-id}` (hide)
- `GET /{page-or-me}` (followers/fan), `GET /{post-id}/reactions`

### Scope cross-reference (per Meta Pages permissions docs)

| Scope | Required by traced methods? | Notes |
|-------|----------------------------|--------|
| `pages_show_list` | **USED** | `/me/accounts` / listing pages the user can manage. |
| `pages_read_engagement` | **USED** | Reading posts, comments, reaction lists, tagged feed, follower/fan fields. |
| `pages_manage_posts` | **USED** | Publishing to page feed/photos. |
| `pages_manage_engagement` | **USED** | Comment replies, delete/hide comments on the Page. |
| `pages_manage_metadata` | **UNUSED** *(for this adapter’s HTTP calls)* | No calls to page settings, webhooks, CTA, or metadata management in `facebook.py`. Safe to drop **only if** no other code path depends on it (none found in this trace). |

### SkyEye consumers (extra methods → scopes)

- **`notification_observer.py`** — `get_follower_count`, `get_own_posts`, `get_post_reactions`, `get_comments` (subset of same scopes as above).
- **`skyeye_session_engine.py`** — `get_feed`, `get_own_posts`, `get_comments`, `get_mentions` (tagged), `get_analytics`, `reply_to_comment`, `post_content`; `get_trending` is base default (no Facebook trending). No methods beyond the adapter’s surface that would **add** new permissions vs the table above.

---

## YouTube (`YouTubeAdapter`)

### Current OAuth scope string (`get_oauth_url`)

`https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl`

### Adapter methods (`youtube.py`)

| Area | Methods |
|------|---------|
| Auth | `authenticate`, `refresh_token`, `get_oauth_url`, `handle_oauth_callback` |
| Content | `post_content` *(returns `NOT_SUPPORTED` — no Data API upload path implemented)* |
| Read/monitor | `get_comments`, `get_mentions` *(stub → `[]`)*, `get_feed`, `get_own_posts` |
| Engagement | `reply_to_comment` |
| Moderation | `delete_comment`, `hide_comment` |
| Discovery/analytics | `get_follower_count`, `get_analytics` |
| Trending | *(base default `[]`)* |

### Called API surfaces (scope drivers)

- `channels.list` (`mine=true`, `part=snippet` / `contentDetails` / `statistics`)
- `playlistItems.list`, `commentThreads.list`, `comments.insert`, `comments.delete`, `comments.setModerationStatus`

### Scope cross-reference (Google OAuth scopes for YouTube Data API v3)

| Scope | Required by traced methods? | Notes |
|-------|----------------------------|--------|
| `https://www.googleapis.com/auth/youtube` | **USED** | Full channel management scope; covers list + comment read/write + moderation in Data API v3. |
| `https://www.googleapis.com/auth/youtube.force-ssl` | **UNCERTAIN** | Documented as SSL-only variant overlapping full manage access; **likely redundant** if `youtube` is already granted. Dropping should be validated with a live token + `comments.insert` / `setModerationStatus`. |

`youtube.readonly` would **not** cover `comments.insert`, `comments.delete`, or `setModerationStatus`; the app is correctly **not** requesting readonly given session engagement.

### SkyEye consumers

- **`notification_observer.py`** — `get_follower_count`, `get_own_posts`, `get_comments`.
- **`livestream_chat.py`** (`YouTubeChatPoller`) — `authenticate`, `get_comments("live", …)` — same OAuth scopes as `commentThreads.list` (still “manage” class, not readonly). *Implementation note:* `"live"` is passed as `videoId`; behavior is API-dependent and may return empty/403 without a real video id — scope need is unchanged.
- **`skyeye_session_engine.py`** — `get_feed`, `get_own_posts`, `get_comments`, `get_analytics`, `reply_to_comment`, `post_content` (currently no-op success path); `get_mentions` / `get_trending` are empty on YouTube.

---

## Reddit (`RedditAdapter`)

### Current OAuth scope string (`get_oauth_url`)

`identity,submit,read,privatemessages,modflair,modposts,edit,flair,history,mysubreddits`

### Adapter methods (`reddit.py`)

| Area | Methods |
|------|---------|
| Auth | `authenticate`, `_script_auth`, `refresh_token`, `get_oauth_url`, `handle_oauth_callback` |
| Content | `post_content` (`/api/submit`, optional `flair_id`) |
| Read/monitor | `get_comments`, `get_mentions`, `get_feed`, `get_own_posts`, `get_trending` |
| Engagement | `reply_to_comment` |
| Moderation | `delete_comment`, `block_user` |
| Analytics | `get_analytics` |

### Called OAuth endpoints (scope drivers)

- `GET /api/v1/me`
- `GET /comments/{id}`, `GET /message/mentions`, `GET /user/{name}/submitted`, `GET /r/popular/hot`
- `POST /api/submit`, `POST /api/comment`, `POST /api/del`, `POST /api/block_user`

### Scope cross-reference (Reddit OAuth2 scope list)

| Scope | Required by traced methods / consumers? | Notes |
|-------|----------------------------------------|--------|
| `identity` | **USED** | `/api/v1/me` in auth, callback, analytics. |
| `read` | **USED** | Thread listings, user submitted, popular, comment trees. |
| `submit` | **USED** | `/api/submit` and `/api/comment`. |
| `privatemessages` | **USED** | `/message/mentions` in `get_mentions` (session observe + engage). |
| `edit` | **UNCERTAIN** | `/api/del` on own content may succeed with `submit` alone; verify before removing. |
| `flair` | **UNCERTAIN** | Only if `post_content(..., flair_id=...)` is used in production; not grepped elsewhere in `backend/`. |
| `modflair` | **UNUSED** | No mod-flair endpoints in adapter. |
| `modposts` | **UNUSED** | No mod-sticky/distinguish flows in adapter. |
| `history` | **UNUSED** | No voting/recent-history endpoints traced. |
| `mysubreddits` | **UNUSED** | No `/subreddits/mine` or moderated-list calls traced. |

`block_user` → **UNCERTAIN** minimal scope (not clearly mapped to a single scope in this trace); treat as “keep until Reddit doc confirmed or integration tested.”

### SkyEye consumers

- **`notification_observer.py`** — **does not** poll `reddit` in the traced branch list (only facebook/youtube called out for dedicated `_poll_*`). Adapter methods may still run via sessions.
- **`skyeye_session_engine.py`** — Uses `get_feed`, `get_trending`, `get_own_posts`, `get_comments`, `get_mentions`, `get_analytics`, `reply_to_comment`, `post_content` when Reddit is in the session platform set — aligns with **identity, read, submit, privatemessages** at minimum.

---

## Summary table

| Platform | USED (confident) | UNUSED / safe to drop (pending confirm) | UNCERTAIN |
|----------|------------------|----------------------------------------|-----------|
| **Facebook** | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement` | `pages_manage_metadata` *(no adapter calls)* | — |
| **YouTube** | `youtube` (full manage) | — | `youtube.force-ssl` *(likely redundant with `youtube`)* |
| **Reddit** | `identity`, `read`, `submit`, `privatemessages` | `modflair`, `modposts`, `history`, `mysubreddits` | `edit`, `flair`, `block_user` pairing |

---

*End of trace.*
