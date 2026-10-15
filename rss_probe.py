# -*- coding: utf-8 -*-
"""GNEWS 原文URL解析多策略诊断（独立 rss-probe workflow）。跑在海外节点，
完整跟随重定向 + protobuf 离线解码 + description 提取，结果写 data/rss_probe.json 并 git 提交。"""
import urllib.request, urllib.parse, ssl, json, re, os, base64, datetime, subprocess, time
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
def gnews(site):
    q=urllib.parse.quote("site:%s (china OR chinese)"%site)
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"%q
SRC={"路透":gnews("reuters.com"),"AP":gnews("apnews.com"),"彭博":gnews("bloomberg.com"),
     "日经":gnews("asia.nikkei.com"),"WSJ":gnews("wsj.com")}
def get(url,timeout=20):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/rss+xml,application/xml,*/*"})
    with urllib.request.urlopen(req,timeout=timeout,context=CTX) as r:
        return r.status, r.read(2000000).decode("utf-8","ignore")
def dom(u):
    m=re.match(r'https?://([^/]+)',u or ""); return m.group(1) if m else ""
def follow_chain(link):
    chain=[]; external=[]; final=""; err=""
    class H(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,hdrs,newurl):
            chain.append(newurl)
            return urllib.request.HTTPRedirectHandler.redirect_request(self,req,fp,code,msg,hdrs,newurl)
    try:
        op=urllib.request.build_opener(H)
        r=op.open(urllib.request.Request(link,headers={"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"}),timeout=15,context=CTX)
        final=r.geturl(); body=r.read(80000).decode("utf-8","ignore"); r.close()
        urls=re.findall(r'https?://[A-Za-z0-9./_\-?=&%#:;]+',body)
        external=[x for x in urls if not any(k in dom(x) for k in ("google","gstatic","googleapis"))][:3]
    except Exception as e:
        err=repr(e)[:100]
    return chain[:5],final[:120],external,err
def pb_decode(link):
    out={"raw_head":"","urls":[],"err":""}
    try:
        aid=link.split("articles/")[1].split("?")[0]
        raw=base64.urlsafe_b64decode(aid+"="*(-len(aid)%4))
        out["raw_head"]=raw[:32].hex()
        # 在解码字节里找可打印 URL
        hits=re.findall(rb'[A-Za-z0-9+/=]{24,}',raw)
        for h in hits:
            try:
                inner=base64.urlsafe_b64decode(h+b"="*(-len(h)%4))
                for u in re.findall(rb'https?://[\x20-\x7e]{8,}',inner):
                    out["urls"].append(u.decode("latin1","ignore")[:120])
            except Exception: pass
        out["urls"]=out["urls"][:3]
    except Exception as e:
        out["err"]=repr(e)[:80]
    return out
res={"diag_at":datetime.datetime.utcnow().isoformat()+"Z","results":{}}
for name,url in SRC.items():
    rec={"feed":url}
    try:
        st,body=get(url); rec["status"]=st
        items=re.findall(r"<item[\s\S]*?</item>",body)
        rec["items"]=len(items)
        samp=[]
        for blk in items[:2]:
            t=re.search(r"<title>(.*?)</title>",blk); l=re.search(r"<link>(.*?)</link>",blk)
            d=re.search(r"<pubDate>(.*?)</pubDate>",blk)
            link=l.group(1).strip() if l else ""
            chain,final,external,err=follow_chain(link)
            pb=pb_decode(link)
            samp.append({"title":(t.group(1)[:50] if t else ""),"date":(d.group(1)[:25] if d else ""),
                         "chain":[c[:70] for c in chain],"final":final,"external":external,
                         "follow_err":err,"pb":pb})
        rec["samples"]=samp
    except Exception as e:
        rec["err"]=repr(e)[:120]
    res["results"][name]=rec
    print(name,rec.get("items"),"done",flush=True)
os.makedirs("data",exist_ok=True)
json.dump(res,open("data/rss_probe.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
# git 提交（checkout action 已配置 GITHUB_TOKEN credential）
def sh(cmd):
    return subprocess.run(cmd,shell=True,capture_output=True,text=True)
sh('git config user.name "github-actions[bot]"')
sh('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"')
sh("git add data/rss_probe.json")
if sh("git diff --staged --quiet").returncode!=0:
    sh('git commit -m "data: gnews multi-strategy decode diagnosis"')
    for i in range(3):
        r=sh("git pull --rebase origin main && git push")
        if r.returncode==0: print("PUSHED"); break
        print("retry",i,r.stderr[:100]); time.sleep(6)
else: print("no change")
