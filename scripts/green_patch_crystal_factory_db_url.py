#!/usr/bin/env python3
"""Run on GREEN only. Sets Hetzner /opt/crystal-factory/.env PRODUCTION_DB_URL to PgBouncer on wg0."""
from pathlib import Path
from urllib.parse import quote
import subprocess
import sys


def main() -> int:
    green_env = Path("/opt/clinical-sovereignty-lab/.env")
    if not green_env.is_file():
        print("Missing GREEN .env", file=sys.stderr)
        return 1
    text = green_env.read_text()
    pw = None
    for line in text.splitlines():
        if line.startswith("POSTGRES_PASSWORD="):
            pw = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not pw:
        print("POSTGRES_PASSWORD not found", file=sys.stderr)
        return 1
    url = "postgresql://nate_admin:{}@10.13.13.2:6432/little_nate".format(quote(pw, safe=""))
    remote_py = """from pathlib import Path
url = %r
p = Path("/opt/crystal-factory/.env")
assert p.is_file(), "missing .env"
lines = [ln for ln in p.read_text().splitlines() if not ln.startswith("PRODUCTION_DB_URL=")]
lines.append("PRODUCTION_DB_URL=" + url)
p.write_text("\\n".join(lines) + "\\n")
print("ok")
""" % (
        url,
    )
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "root@10.13.13.5", "python3", "-"],
        input=remote_py,
        capture_output=True,
        text=True,
    )
    print(r.stdout, end="")
    print(r.stderr, file=sys.stderr, end="")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
