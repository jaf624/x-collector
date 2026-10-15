# -*- coding: utf-8 -*-
"""GNEWS 采集0根因诊断：在海外 Actions 跑，测 feed获取→parse→日期→302原文解析，
用 GITHUB_TOKEN 经 Contents API 直接提交 data/gnews_diag.json（不依赖 workflow git push）。"""
import urllib.request, urllib.parse, urllib.error, ssl, json, re, os, base64, datetime, time
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
def gnews(site):
    q=urllib.parse.quote("site:%s (china OR chinese)"%site)
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"%q
SRC={
 "路透":gnews("reuters.com"),"AP":gnews("apnews.com"),"AFP":gnews("france24.com"),
 "彭博":gnews("bloomberg.com"),"日经":gnews("asia.nikkei.com"),"FT":gnews("ft.com"),
 "WSJ":gnews("wsj.com"),"NYT":gnews("nytimes.com"),"经济学人":gnews("economist.com"),
}
class _GNR(urllib.request.HTTPRedirectHandler):
    def __init__(self): self.loc=None
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        self.loc=newurl; return None
def resolve(u,timeout=12):
    if not u or "news.google.com" not in u: return u,"skip"
    try:
        h=_GNR(); op=urllib.request.build_opener(h)
        req=urllib.request.Request(u,headers={"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"})
        try:
            r=op.open(req,timeout=timeout); final=r.geturl(); body=r.read(200000).decode("utf-8","ignore"); r.close()
            if "news.google.com" not in final: return final,"302-final"
        except urllib.error.HTTPError as e:
            if h.loc and "news.google.com" not in h.loc: return h.loc,"loc"
            body=e.read(200000).decode("utf-8","ignore") if hasattr(e,"read") else ""
        for m in re.findall(r'https?://[^\s"\'<>\\]+',body or ""):
            mm=re.match(r'https?://([^/]+)',m)
            if mm and not any(x in mm.group(1) for x in ("google.","gstatic","googlenews")):
                return m.rstrip("\\"),"html-extract"
        return u,"unresolved"
    except Exception as e:
        return u,"err:"+repr(e)[:50]
def parse_items(body):
    out=[]
    for m in re.finditer(r"<item[\s\S]*?</item>",body):
        blk=m.group(0)
        t=re.search(r"<title>(.*?)</title>",blk); l=re.search(r"<link>(.*?)</link>",blk)
        d=re.search(r"<pubDate>(.*?)</pubDate>",blk)
        out.append({"title":(t.group(1) if t else "")[:70],"link":(l.group(1) if l else "").strip(),
                    "date":(d.group(1) if d else "")[:40]})
    return out
res={"diag_at":datetime.datetime.utcnow().isoformat()+"Z","sources":{}}
for name,u in SRC.items():
    rec={"feed_url":u}
    try:
        req=urllib.request.Request(u,headers={"User-Agent":UA,"Accept":"application/rss+xml,application/xml,*/*"})
        with urllib.request.urlopen(req,timeout=20,context=CTX) as r:
            body=r.read(2000000).decode("utf-8","ignore")
        items=parse_items(body)
        rec["feed_status"]=r.status; rec["parsed"]=len(items)
        diag=[]
        for it in items[:3]:
            real,how=resolve(it["link"])
            diag.append({"title":it["title"],"date":it["date"],"real":real[:100],"how":how})
        rec["samples"]=diag
    except Exception as e:
        rec["err"]=repr(e)[:150]
    res["sources"][name]=rec
    print(name,rec.get("parsed"),[s["how"] for s in rec.get("samples",[])],flush=True)
# 提交
payload=json.dumps(res,ensure_ascii=False,indent=1)
tok=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
repo=os.environ.get("GITHUB_REPOSITORY","jaf624/x-collector")
if tok:
    H={"User-Agent":"diag","Authorization":"Bearer "+tok,"Accept":"application/vnd.github+json"}
    def api(method,path,body=None):
        data=json.dumps(body).encode() if body is not None else None
        r=urllib.request.Request("https://api.github.com/repos/%s/%s"%(repo,path),data=data,method=method,headers=H)
        try:
            with urllib.request.urlopen(r,timeout=60) as x:
                raw=x.read(); return x.status,(json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e: return e.code,e.read().decode()[:150]
    st,cur=api("GET","contents/data/gnews_diag.json")
    b={"message":"data: gnews collection zero-result diagnosis","content":base64.b64encode(payload.encode()).decode(),"branch":"main"}
    if st==200 and isinstance(cur,dict): b["sha"]=cur["sha"]
    st,r2=api("PUT","contents/data/gnews_diag.json",b)
    print("COMMIT",st,r2.get("commit",{}).get("sha","")[:8] if isinstance(r2,dict) else r2)
else:
    print("NO GITHUB_TOKEN")
