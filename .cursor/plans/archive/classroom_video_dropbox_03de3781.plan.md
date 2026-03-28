---
name: Classroom Video Dropbox
overview: Fix the non-functional Classroom video upload by correcting 3 bugs (wrong URL path, missing auth header, web file.path crash), replace the upload button with a visual drop-zone UI, and add backend security hardening.
todos:
  - id: fix-route
    content: Fix endpoint route path in sessions.py (remove duplicate /api/ prefix) and update Flutter client URL to match
    status: completed
  - id: add-auth
    content: Add Authorization header to the multipart upload request in _pickAndUploadVideo()
    status: completed
  - id: dropbox-ui
    content: Replace upload button with a dashed-border drop-zone container (icon, label, format hints, inline progress)
    status: completed
  - id: backend-security
    content: Add filename sanitization, magic-byte validation, and chunked streaming to upload_classroom_video()
    status: completed
  - id: build-deploy
    content: Flutter build + rsync to both server dirs, scp sessions.py to server, restart backend
    status: completed
isProject: false
---

# Classroom Video Upload: Dropbox UI + Security Fix

## Current Problems (3 bugs preventing upload)

1. **Wrong URL path** — The Flutter client sends to `/api/classroom/upload-video`, but the endpoint lives inside the sessions router (`prefix="/api/sessions"`), making the actual path `/api/sessions/api/classroom/upload-video`. The upload silently gets a 404.
2. **Missing Authorization header** — The multipart request in `_pickAndUploadVideo()` never sets `Authorization: Bearer <token>`. The sessions router requires auth on every endpoint via `dependencies=[Depends(_require_auth)]`, so even if the URL matched, it would return 401.
3. **Web `file.path` crash** — Already fixed in the prior deployment, but the fix is deployed.

## Plan

### 1. Fix the backend route path

In [backend/app/routers/sessions.py](backend/app/routers/sessions.py), the endpoint decorator is `@router.post("/api/classroom/upload-video")`. Since the router has `prefix="/api/sessions"`, the full path becomes `/api/sessions/api/classroom/upload-video`. Fix by changing the decorator to just `/classroom/upload-video` so the full URL is `/api/sessions/classroom/upload-video`. Then update the Flutter client URL to match.

Alternatively, move the classroom upload to its own un-prefixed route, but keeping it in the sessions router (which already has auth) is cleaner.

### 2. Add Authorization header to the upload request

In [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) `_pickAndUploadVideo()` (~line 11320), add:

```dart
request.headers['Authorization'] = 'Bearer ${widget.currentUserProfile?['token'] ?? ''}';
```

### 3. Replace the upload button with a drop-zone UI

Replace the current `ElevatedButton.icon` with a dashed-border container styled as a "dropbox" area:

- Dashed gold border container with rounded corners
- Cloud upload icon centered
- "Tap to upload a session video" label
- Accepted formats note: "MP4, MOV, WEBM -- max 500MB"
- Progress bar and success state rendered inside the zone
- No new packages needed -- use `CustomPaint` with a dashed-rect painter for the border

### 4. Backend security hardening

In [backend/app/routers/sessions.py](backend/app/routers/sessions.py) `upload_classroom_video()`:

- **Filename sanitization** — Strip path separators and null bytes from `file.filename` before using it in the response or JSON record (the file on disk already uses a generated `video_id`, so the path is safe, but the filename stored in JSON should be sanitized)
- **Magic-byte validation** — Check the first 8-12 bytes of content against known video file signatures (MP4 `ftyp`, MOV `moov`/`ftyp`, WebM `\x1A\x45\xDF\xA3`) to prevent disguised uploads. This prevents someone from uploading a `.php` or `.exe` renamed to `.mp4`
- **Chunked read** — Replace `await file.read()` (loads entire file into memory) with chunked streaming to a temp file, enforcing the 500MB limit during the stream rather than after

The JSON file (`classroom_sessions.json`) is append-only metadata -- no SQL is involved, so there is no SQL injection risk. The security focus is on preventing malicious file content from reaching disk.

### 5. Build + deploy

- `flutter build web --release`
- `rsync` to both server directories
- `scp` the updated `sessions.py` to server, restart backend

