#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性自测：在 GitHub Actions 美国节点验证 Telegram 公开频道网页预览(t.me/s/<name>)能否免登录抓取。

合规边界（自测严格遵守）：
  - 只访问 Telegram 官方公开公告频道(中性) t.me/s/telegram，不登录、不加入、不使用任何账号/API；
  - 只解析公开 HTML 中的文本与元数据，绝不下载图片/视频/文件，媒体仅计数标记；
  - 不触碰任何非公开群组/频道。
"""
import os, re, json, ssl, time, html, datetime, urllib.request, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CH = "telegram"  # Telegram 官方公开公告频道，中性


def get(url, headers=None, timeout=60):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "ignore"), round(time.time() - t0, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300], round(time.time() - t0, 1)
    except Exception as e:
        return None, "EXC " + repr(e)[:200], round(time.time() - t0, 1)


def strip(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(t or ""))).strip()


result = {"channel": CH, "purpose": "public-web-preview connectivity, no login, no media download",
          "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"}

# 1) 直连公开网页预览（境外 runner 首选，零 token）
url = f"https://t.me/s/{CH}"
st, body, sec = get(url)
posts = re.findall(r'data-post="' + re.escape(CH) + r'/(\d+)"', body)
dates = re.findall(r'datetime="(20\d\d-\d\d-\d\dT[^"]+)"', body)
texts = re.findall(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', body, re.S)
media = {"photo_wrap": len(re.findall(r"tgme_widget_message_photo_wrap", body)),
         "video": len(re.findall(r"tgme_widget_message_(?:media_video|round_video)", body)),
         "document": len(re.findall(r"tgme_widget_message_document", body))}
result["direct"] = {"http": st, "seconds": sec, "html_len": len(body),
                    "posts": len(posts), "datetimes": len(dates), "text_blocks": len(texts),
                    "media_marks": media, "first_post_ids": posts[:3],
                    "sample": [strip(t)[:160] for t in texts[:2]]}

# 2) Jina 境外代抓兜底（直连受限时）
if KEY:
    st2, b2, sec2 = get("https://r.jina.ai/" + url,
                        headers={"Authorization": f"Bearer {KEY}", "Accept": "text/plain"})
    links = re.findall(r"t\.me/" + re.escape(CH) + r"/(\d+)", b2)
    result["jina"] = {"http": st2, "seconds": sec2, "len": len(b2),
                      "perm_links": len(set(links)), "head": b2[:200]}
else:
    result["jina"] = {"skip": "no JINA_KEY"}

os.makedirs("data", exist_ok=True)
json.dump(result, open("data/telegram_selftest.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(json.dumps(result, ensure_ascii=False, indent=1))
print("TG_SELFTEST_DONE")
