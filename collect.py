#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X(Twitter) 海外采集器 —— 设计为在 GitHub Actions 海外 runner 上定时运行。
两条采集腿：
  1) 免登录 syndication 公开接口：按"具体推文ID"取正文/图/视频（用户投喂链接走这条，无需Cookie）
  2) 可选 twikit 登录态：配置 GitHub Secret(X_AUTH_TOKEN / X_CT0) 后，
     可自动抓"指定账号时间线 + 关键词搜索"，实现主动发现，不依赖人工投喂。
输出 data/x_feed.json（累积去重），由国内服务器定时拉取后洗练入库。
"""
import os, re, json, math, time, ssl, urllib.request, urllib.error, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
OUT_DIR = ROOT / "data"; OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "x_feed.json"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# ---------- syndication 免登录 ----------
def _int_base(n, r):
    if n == 0: return "0"
    s=""
    while n: s = DIGITS[n % r] + s; n //= r
    return s

def _js_tostring(x, r=36):
    ip=int(x); fp=x-ip; s=_int_base(ip,r)
    if fp>0:
        s+="."
        for _ in range(16):
            fp*=r; d=int(fp); s+=DIGITS[d]; fp-=d
            if fp==0: break
    return s

def synd_token(tid):  # 复刻 react-tweet 的 token 算法，无需登录
    return _js_tostring((int(tid)/1e15)*math.pi, 36).replace("0","").replace(".","")

def http_get(url, headers=None, timeout=25):
    req=urllib.request.Request(url, headers=headers or {"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()

def fetch_by_id(tid, retry=2):
    url=f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&lang=zh-cn&token={synd_token(tid)}"
    for k in range(retry+1):
        try:
            d=json.loads(http_get(url).decode("utf-8","ignore"))
            return normalize(d)
        except urllib.error.HTTPError as e:
            if e.code in (404,): return None
            time.sleep(2*(k+1))
        except Exception:
            time.sleep(2*(k+1))
    return None

def normalize(d):
    u=d.get("user") or {}
    photos=[{"url":p.get("url"),"w":p.get("width"),"h":p.get("height")} for p in (d.get("photos") or [])]
    video=""
    for m in (d.get("mediaDetails") or []):
        if m.get("type")=="video":
            vs=[v for v in (m.get("video_info",{}).get("variants") or []) if v.get("content_type")=="video/mp4"]
            if vs: video=sorted(vs,key=lambda x:x.get("bitrate",0))[-1].get("url","")
    tid=str(d.get("id") or d.get("id_str") or "")
    return {
        "x_id":tid,
        "screen_name":u.get("screen_name",""),
        "author":u.get("name",""),
        "verified":u.get("verified",False),
        "created_at":d.get("created_at",""),
        "text_raw":d.get("text") or "",
        "lang":d.get("lang",""),
        "photos":photos,
        "video":video,
        "url":f"https://x.com/{u.get('screen_name','i')}/status/{tid}",
        "fav":d.get("favorite_count",0),
        "retweet":d.get("retweet_count",0),
        "reply":d.get("conversation_count",0),
        "is_quote":bool(d.get("isQuoted")),
        "fetched_at":datetime.datetime.utcnow().isoformat()+"Z",
    }

# ---------- 可选 twikit 登录态（主动发现） ----------
def fetch_with_twikit(accounts, keywords, per_user=15):
    out=[]
    try:
        from twikit import Client
    except Exception:
        print("[twikit] 未安装，跳过登录态采集（pip install twikit 后可用）"); return out
    at=os.environ.get("X_AUTH_TOKEN",""); ct0=os.environ.get("X_CT0","")
    if not at or not ct0:
        print("[twikit] 未配置 X_AUTH_TOKEN/X_CT0 secret，跳过主动发现，仅用免登录ID"); return out
    try:
        c=Client("en-US")
        c.set_cookies({"auth_token":at,"ct0":ct0})
        for name in accounts:
            try:
                user=c.get_user_by_screen_name(name)
                for t in (user.get_tweets("Tweets",count=per_user) or []):
                    out.append(_twikit_to_rec(t,name))
                time.sleep(2)
            except Exception as e: print(f"[twikit] 账号 {name} 失败: {e}")
        for kw in keywords:
            try:
                for t in (c.search_tweets(kw,"Latest",count=per_user) or []):
                    out.append(_twikit_to_rec(t,"search:"+kw))
                time.sleep(2)
            except Exception as e: print(f"[twikit] 搜索 {kw} 失败: {e}")
    except Exception as e:
        print("[twikit] 登录态采集异常:",e)
    return out

def _twikit_to_rec(t, via):
    attrs=lambda *a: None
    media=[]
    try:
        for m in (t.media or []):
            if m.get("type")=="photo": media.append({"url":m.get("media_url_https"),"w":m.get("original_info",{}).get("width"),"h":m.get("original_info",{}).get("height")})
    except Exception: pass
    video=""
    try:
        for m in (t.media or []):
            if m.get("type")=="video":
                vs=m.get("video_info",{}).get("variants",[])
                mp4=[v for v in vs if v.get("content_type")=="video/mp4"]
                if mp4: video=sorted(mp4,key=lambda x:x.get("bitrate",0))[-1]["url"]
    except Exception: pass
    u=getattr(t,"user",None)
    tid=str(getattr(t,"id",""))
    return {
        "x_id":tid,
        "screen_name":getattr(u,"screen_name","") if u else via,
        "author":getattr(u,"name","") if u else "",
        "verified":bool(getattr(u,"verified",False)) if u else False,
        "created_at":str(getattr(t,"created_at","")),
        "text_raw":getattr(t,"text","") or "",
        "lang":getattr(t,"lang",""),
        "photos":media,"video":video,
        "url":f"https://x.com/{getattr(u,'screen_name','i') if u else 'i'}/status/{tid}",
        "fav":getattr(t,"favorite_count",0),"retweet":getattr(t,"retweet_count",0),"reply":getattr(t,"reply_count",0),
        "is_quote":bool(getattr(t,"is_quote_status",False)),
        "fetched_at":datetime.datetime.utcnow().isoformat()+"Z",
    }

def read_lines(p):
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] if p.exists() else []

# 海外节点把X图片下载进仓库 data/images，URL换成 raw 地址，保证国内服务器/用户浏览器可访问
RAW_BASE = f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY','')}/main" if os.environ.get("GITHUB_REPOSITORY") else ""
IMG_DIR = OUT_DIR / "images"; IMG_DIR.mkdir(parents=True, exist_ok=True)

def localize_media(recs, max_bytes=8_000_000):
    if not RAW_BASE:  # 本地无仓库上下文时保留原URL
        return
    for r in recs:
        for i, p in enumerate(r.get("photos") or []):
            u = p.get("url", "")
            if not u or "raw.githubusercontent" in u: continue
            fn = f"{r['x_id']}_{i}.jpg"; fp = IMG_DIR / fn
            try:
                if not fp.exists():
                    b = http_get(u, {"User-Agent": UA}, 40)
                    if len(b) < 1500 or len(b) > max_bytes: continue
                    fp.write_bytes(b)
                p["url"] = f"{RAW_BASE}/data/images/{fn}"   # 国内可达
            except Exception as e:
                print("[img]", r["x_id"], "fail", str(e)[:80])

def main():
    ids=read_lines(ROOT/"targets"/"ids.txt")
    accounts=read_lines(ROOT/"targets"/"accounts.txt")
    keywords=read_lines(ROOT/"targets"/"keywords.txt")
    recs=[]
    # 1) 免登录ID（用户投喂）
    for tid in ids:
        tid=re.search(r"(\d{10,})",tid)
        if not tid: continue
        r=fetch_by_id(tid.group(1))
        if r: recs.append(r); print("[id] ok",r["x_id"],r["screen_name"])
        else:  print("[id] miss",tid.group(1))
        time.sleep(1)
    # 2) 登录态主动发现
    recs += fetch_with_twikit(accounts, keywords)
    # 3) 图片落地到仓库，保证国内可达
    localize_media(recs)
    # 累积去重
    old={}
    if OUT.exists():
        try: old={x["x_id"]:x for x in json.loads(OUT.read_text(encoding="utf-8"))}
        except Exception: old={}
    for r in recs:
        if r.get("x_id"): old[r["x_id"]]=r
    feed=sorted(old.values(), key=lambda x:x.get("fetched_at",""), reverse=True)
    OUT.write_text(json.dumps(feed,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"完成：本次 {len(recs)} 条，累积 {len(feed)} 条 -> {OUT}")

if __name__=="__main__":
    main()
