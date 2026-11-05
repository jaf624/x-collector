# -*- coding: utf-8 -*-
"""在 GitHub Actions（境外出口）里把 Google News 跳转链接解析成原站地址，并直接抓正文。

背景：国内服务器对 news.google.com / reuters / jina 全部不可达，采集到的 50% 线索
是 news.google.com/rss/articles/... 跳转链接，本机既打不开也抓不到正文，导致研判
永远凑不满 700 字。GitHub runner 在境外，可以跟随 302 拿到原站地址，并直连抓正文。

不依赖 Jina key：先 requests 跟随重定向，再直连取 HTML，用 trafilatura（若可用）
或正则抽段。
"""
import json, os, re, time

PATH = "data/intel_feed.json"
CAP = int(os.environ.get("RESOLVE_MAX", "60"))
MIN_BODY = 700

SKIP = ("baike.baidu.com", "zhihu.com", "wikipedia.org", "douban.com", "bilibili.com")


def clean_html(h):
    h = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", h)
    ps = re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)
    txt = " ".join(re.sub(r"(?s)<[^>]+>", "", x) for x in ps)
    txt = re.sub(r"&nbsp;|&#160;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def cn_len(s):
    return len(re.findall(r"[\u4e00-\u9fa5]", s or ""))


def fetch_body(url):
    """返回 (final_url, body)。trafilatura 优先，正则兜底。"""
    import requests
    r = requests.get(url, timeout=25, allow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    final = r.url
    body = ""
    try:
        import trafilatura
        body = trafilatura.extract(r.text) or ""
    except Exception:
        pass
    if len(body) < MIN_BODY:
        alt = clean_html(r.text)
        if len(alt) > len(body):
            body = alt
    return final, body


def main():
    if not os.path.exists(PATH):
        print("无 feed"); return
    feed = json.load(open(PATH, encoding="utf-8"))
    items = feed if isinstance(feed, list) else (feed.get("items") or [])
    cand = [x for x in items
            if ("news.google.com" in (x.get("url") or "")
                or len((x.get("content") or "").strip()) < MIN_BODY)
            and (x.get("url") or "").startswith("http")
            and not any(d in (x.get("url") or "") for d in SKIP)
            and x.get("body_from") != "gh"]
    cand.sort(key=lambda x: x.get("published") or "", reverse=True)
    print("待解析/补正文候选:", len(cand), flush=True)

    ok = 0
    for x in cand:
        if ok >= CAP:
            break
        try:
            final, body = fetch_body(x["url"])
            if "news.google.com" in x["url"]:
                x["gnews_url"] = x["url"]
                x["url"] = final
            if len(body) >= MIN_BODY:
                x["content"] = body[:4000]
                x["summary"] = body[:240]
                x["body_from"] = "gh"
                ok += 1
                print("  · ok", len(body), (x.get("title") or "")[:30], flush=True)
            else:
                print("  · short", len(body), (x.get("title") or "")[:30], flush=True)
        except Exception as e:
            print("  · err", (x.get("title") or "")[:30], repr(e)[:60], flush=True)
        time.sleep(0.6)

    json.dump(feed, open(PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print("完成，补全文", ok, "条", flush=True)


if __name__ == "__main__":
    main()
