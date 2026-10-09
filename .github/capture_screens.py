#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions 截图脚本：对 targets（[["iid","url"],...]）逐条截图到 data/screens/{iid}.png。
用于国内服务器不可达的境外源（dpcla.org 等）。"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "screens")
os.makedirs(OUT, exist_ok=True)

try:
    targets = json.loads(sys.argv[1])
except Exception:
    print("bad targets", file=sys.stderr)
    sys.exit(1)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

ok = fail = 0
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
                                args=["--no-sandbox", "--disable-dev-shm-usage"])
    for iid, url in targets:
        fp = os.path.join(OUT, iid + ".png")
        if os.path.isfile(fp) and os.path.getsize(fp) > 5000:
            print("skip existing", iid); continue
        page = browser.new_page(user_agent=UA, viewport={"width": 1280, "height": 1600})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            page.screenshot(path=fp, full_page=True)
            if os.path.getsize(fp) > 5000:
                print("captured", iid, os.path.getsize(fp)); ok += 1
            else:
                print("empty", iid); fail += 1
        except Exception as ex:
            print("ERR", iid, str(ex)[:120]); fail += 1
        finally:
            page.close()
        time.sleep(1)
    browser.close()
print("done. ok:", ok, "fail:", fail)
sys.exit(0 if ok else 1)
