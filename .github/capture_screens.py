#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions 截图脚本：对 targets（[["iid","url"],...]）逐条截图到 data/screens/{iid}.png。
用于国内服务器不可达的境外源（dpcla.org、gofundme.com 等）。
未传 targets 时自动取 data/intel_feed.json 中 lead_tag 条目前 15 条（跳过已截图），
并将成功截图清单写 data/screens_manifest.json 供服务器同步拉取。"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "screens")
MANIFEST = os.path.join(ROOT, "data", "screens_manifest.json")
os.makedirs(OUT, exist_ok=True)

raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    targets = json.loads(raw) if raw.strip() else []
except Exception:
    print("bad targets", file=sys.stderr)
    sys.exit(1)

if not targets:
    # 自动从 feed 读 lead 条目（最多 15 条，跳过已有截图）
    try:
        feed = json.load(open(os.path.join(ROOT, "data", "intel_feed.json"), encoding="utf-8"))
    except Exception:
        feed = []
    picked = [x for x in feed if x.get("lead_tag")]
    for x in picked[:15]:
        iid = x["id"]
        if os.path.isfile(os.path.join(OUT, iid + ".png")) and \
                os.path.getsize(os.path.join(OUT, iid + ".png")) > 5000:
            continue
        targets.append([iid, x.get("url", "")])
    if targets:
        print("auto targets from feed:", len(targets))

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

ok = fail = 0
captured = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
                                args=["--no-sandbox", "--disable-dev-shm-usage"])
    for iid, url in targets:
        fp = os.path.join(OUT, iid + ".png")
        if os.path.isfile(fp) and os.path.getsize(fp) > 5000:
            print("skip existing", iid); continue
        page = browser.new_page(user_agent=UA, viewport={"width": 1280, "height": 1400})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            # 首屏截图（不整页）：图小稳定，够作来源证据；整页大图易超 contents API 1MB 限制
            page.screenshot(path=fp, full_page=False)
            if os.path.getsize(fp) > 5000:
                print("captured", iid, os.path.getsize(fp)); ok += 1
                captured.append([iid, url])
            else:
                print("empty", iid); fail += 1
        except Exception as ex:
            print("ERR", iid, str(ex)[:120]); fail += 1
        finally:
            page.close()
        time.sleep(1)
    browser.close()
# 合并清单（保留历史条目，避免服务器重复拉取逻辑出错）
old_manifest = []
if os.path.isfile(MANIFEST):
    try:
        old_manifest = json.load(open(MANIFEST, encoding="utf-8"))
    except Exception:
        old_manifest = []
seen = {c[0] for c in old_manifest}
for c in captured:
    if c[0] not in seen:
        old_manifest.append(c)
json.dump(old_manifest, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False)
print("done. ok:", ok, "fail:", fail)
sys.exit(0 if ok else 1)
