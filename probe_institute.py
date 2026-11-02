#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量探测 institute_sources.json 里所有源的健康度。
跑在 GitHub Actions 境外 runner 上，并发探测，结果写回源文件。
挂的源标记为 inactive，活的保持 active。"""
import urllib.request, ssl, json, os, sys, time, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "targets", "institute_sources.json")
REPORT = os.path.join(ROOT, "data", "institute_probe_report.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

TIMEOUT = int(os.environ.get("PROBE_TIMEOUT", "15"))
WORKERS = int(os.environ.get("PROBE_WORKERS", "20"))

def probe_one(s):
    """探测单个源，返回 (host, status, items, error)"""
    feed_url = s.get("feed_url", "")
    host = s.get("host", "")
    if not feed_url:
        return host, -1, 0, "no feed_url"
    
    try:
        req = urllib.request.Request(feed_url, headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/xml, text/xml, */*"
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
            status = r.status
            body = r.read(500000).decode("utf-8", "ignore")
        
        # 尝试解析RSS条数
        items = 0
        try:
            root = ET.fromstring(body)
            # RSS 2.0: channel/item
            for ch in root:
                tag = ch.tag.lower()
                if tag in ("channel", "feed"):
                    items = len([c for c in ch if c.tag.lower() in ("item", "entry")])
                    break
        except Exception:
            items = -1  # 解析失败但HTTP 200
        
        return host, status, items, ""
    except urllib.error.HTTPError as e:
        return host, e.code, 0, f"HTTP {e.code}"
    except Exception as e:
        err = str(e)[:80]
        return host, -1, 0, err

def main():
    sources = json.load(open(SRC, encoding="utf-8"))
    print(f"开始探测 {len(sources)} 个源...", flush=True)
    
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(probe_one, s): s for s in sources}
        done = 0
        for fu in as_completed(futures):
            host, status, items, err = fu.result()
            results[host] = {"status": status, "items": items, "error": err}
            done += 1
            if done % 50 == 0:
                print(f"  已探测 {done}/{len(sources)}...", flush=True)
    
    # 统计
    ok = sum(1 for v in results.values() if v["status"] == 200 and v["items"] != 0)
    http200 = sum(1 for v in results.values() if v["status"] == 200)
    fail_403 = sum(1 for v in results.values() if v["status"] == 403)
    fail_404 = sum(1 for v in results.values() if v["status"] == 404)
    fail_timeout = sum(1 for v in results.values() if v["status"] == -1)
    
    print(f"\n探测完成：", flush=True)
    print(f"  成功（200+有内容）: {ok}个", flush=True)
    print(f"  HTTP 200但解析0条: {http200 - ok}个", flush=True)
    print(f"  403 Forbidden: {fail_403}个", flush=True)
    print(f"  404 Not Found: {fail_404}个", flush=True)
    print(f"  超时/连接失败: {fail_timeout}个", flush=True)
    
    # 更新源状态：挂的标为inactive
    changed = 0
    for s in sources:
        host = s.get("host", "")
        r = results.get(host, {})
        status = r.get("status", -1)
        items = r.get("items", 0)
        
        # 判断是否健康：200 且 items != 0
        is_healthy = (status == 200 and items != 0)
        
        old_status = s.get("status", "active")
        if not is_healthy and old_status == "active":
            s["status"] = "inactive"
            s["probe_error"] = r.get("error", "")
            changed += 1
        elif is_healthy and old_status == "inactive":
            s["status"] = "active"
            s.pop("probe_error", None)
            changed += 1
        
        # 记录最近探测结果
        s["last_probe"] = datetime.datetime.utcnow().isoformat()
        s["last_probe_status"] = status
        s["last_probe_items"] = items
    
    print(f"\n更新了 {changed} 个源的状态（active<->inactive）", flush=True)
    
    # 写回
    json.dump(sources, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    
    # 写报告
    report = {
        "probed_at": datetime.datetime.utcnow().isoformat(),
        "total": len(sources),
        "ok": ok,
        "http200": http200,
        "fail_403": fail_403,
        "fail_404": fail_404,
        "fail_timeout": fail_timeout,
        "changed": changed,
        "results": results
    }
    json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"报告已写入 {REPORT}", flush=True)

if __name__ == "__main__":
    main()
