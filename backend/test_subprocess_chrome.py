"""Test if Chrome works when launched from a subprocess spawned by an async process."""
import asyncio
import sys
import json

CHROME_SCRIPT = '''
from playwright.sync_api import sync_playwright
import json
p = sync_playwright().start()
b = p.chromium.launch(args=["--no-sandbox"])
pg = b.new_page()
pg.goto("https://example.com")
print(json.dumps({"title": pg.title(), "url": pg.url}))
b.close()
p.stop()
'''

async def test():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", CHROME_SCRIPT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    print(f"Return code: {proc.returncode}")
    print(f"Stdout: {stdout.decode()[:300]}")
    if stderr:
        print(f"Stderr: {stderr.decode()[:300]}")

asyncio.run(test())
