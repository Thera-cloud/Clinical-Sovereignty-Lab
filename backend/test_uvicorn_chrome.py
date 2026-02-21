"""Minimal uvicorn server that spawns Chrome in a subprocess."""
import asyncio
import sys
import json
from fastapi import FastAPI

app = FastAPI()

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

@app.get("/test")
async def test_chrome():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", CHROME_SCRIPT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    return {
        "rc": proc.returncode,
        "out": stdout.decode()[:300],
        "err": stderr.decode()[:300],
    }
