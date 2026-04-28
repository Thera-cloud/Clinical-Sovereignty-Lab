#!/bin/sh
# Ensure bind-mounted /app/data is owned by the runtime user, then ensure the
# classroom R2 upload manifest is present and writable (uid 1000, nate).
# Prevents PermissionError on POST /api/classroom/upload-video/* when a host
# file is created as root or permissions drift after volume changes.
chown -R nate:nate /app/data /app/logs 2>/dev/null || true

F=/app/data/classroom_sessions.json
mkdir -p /app/data 2>/dev/null || true
if [ ! -f "$F" ]; then
  printf '%s' '[]' > "$F" 2>/dev/null || true
fi
# Re-assert owner on the manifest (covers root-created new file, failed -R, or mount quirks)
[ -f "$F" ] && chown nate:nate "$F" 2>/dev/null || true
if [ -f "$F" ] && ! gosu nate sh -c "test -w \"$F\"" 2>/dev/null; then
  chmod u+rw "$F" 2>/dev/null || true
fi

exec gosu nate "$@"
