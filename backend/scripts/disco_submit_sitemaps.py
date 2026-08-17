#!/usr/bin/env python3
"""T1.12 — submit brand sitemap to GSC + IndexNow/Bing. Fails closed without keys."""

from __future__ import annotations

import os
import sys
import urllib.request

SITEMAP = "https://www.sovereignsanctuary.net/sitemap.xml"


def main() -> int:
    gsc = (os.getenv("GOOGLE_SEARCH_CONSOLE_KEY") or "").strip()
    indexnow = (os.getenv("INDEXNOW_KEY") or "").strip()
    if not gsc and not indexnow:
        print("T1.12 blocked: GOOGLE_SEARCH_CONSOLE_KEY and INDEXNOW_KEY unset")
        print(f"Manual: submit {SITEMAP} in GSC + Bing Webmaster")
        return 2
    if indexnow:
        body = (
            '{"host":"www.sovereignsanctuary.net","key":"%s",'
            '"keyLocation":"https://www.sovereignsanctuary.net/%s.txt",'
            '"urlList":["%s"]}' % (indexnow, indexnow, SITEMAP)
        ).encode()
        req = urllib.request.Request(
            "https://api.indexnow.org/indexnow",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("indexnow", resp.status)
    if gsc:
        print("gsc key present — poll not wired (diagnostics keyed_not_polled_v1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
