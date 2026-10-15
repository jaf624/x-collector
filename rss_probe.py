# -*- coding: utf-8 -*-
"""权威源 RSS 通道探活（GitHub Actions 海外节点跑），结果写 data/rss_probe.json。
只记录真实可达状态与条目数，不编造 feed_url。"""
import urllib.request, ssl, json, datetime, re, urllib.parse
CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
def gnews(site, kw="china OR chinese"):
    q=urllib.parse.quote("site:%s (%s)" % (site, kw))
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % q
CANDS={
 "GNEWS-路透": gnews("reuters.com"),
 "GNEWS-AP": gnews("apnews.com"),
 "GNEWS-AFP": gnews("france24.com"),
 "GNEWS-彭博": gnews("bloomberg.com"),
 "GNEWS-日经": gnews("asia.nikkei.com"),
 "GNEWS-金融时报": gnews("ft.com"),
 "GNEWS-华尔街日报": gnews("wsj.com"),
 "GNEWS-纽约时报": gnews("nytimes.com"),
 "GNEWS-经济学人": gnews("economist.com"),
 "GNEWS-路透-China": "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % urllib.parse.quote("reuters.com china technology OR rare earth OR tariff OR military"),
 "AP直接feed": "https://apnews.com/feed",
 "共同社英文": "https://english.kyodonews.net/rss/news.xml",
 "共同社中文": "https://chinese.kyodonews.net/rss/all.xml",
 "日经中文": "https://cn.nikkei.com/rss/rss.xml",
 "BBC中文": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
 "美国国务院": "https://www.state.gov/feed/",
 "美国国防部": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?max=20&ContentType=1",
 "商务部新闻": "https://www.commerce.gov/news/press-releases/rss.xml",
 "USTR新闻": "https://ustr.gov/feeds/press-releases.xml",
 "能源部FE": "https://www.energy.gov/fe/newsroom/rss.xml",
 "NATO": "https://www.nato.int/webservices/rss/news.xml",
 "欧盟presscorner": "https://ec.europa.eu/commission/presscorner/api/rss?language=en",
 "日本外务省": "https://www.mofa.go.jp/rss/english.xml",
 "日本经产省": "https://www.meti.go.jp/rss/whatsnew_e.xml",
 "USNI": "https://news.usni.org/feed",
 "DefenseNews": "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/?outputType=xml",
 "Mining": "https://www.mining.com/feed/",
 "OilPrice": "https://oilprice.com/rss/main",
 "IMF": "https://www.imf.org/en/News/RSS?language=eng",
 "USGS": "https://www.usgs.gov/news/rss.xml",
 "IEA": "https://www.iea.org/news.xml",
 "WTO": "https://www.wto.org/library/rss/latestnews_e.xml",
}
out=[]
for name,u in CANDS.items():
    rec={"name":name,"url":u}
    try:
        req=urllib.request.Request(u,headers={"User-Agent":UA,"Accept":"application/rss+xml,application/xml,atom+xml,*/*"})
        with urllib.request.urlopen(req,timeout=25,context=CTX) as r:
            body=r.read(200000).decode("utf-8","ignore")
            items=len(re.findall(r"<item[ >]",body))+len(re.findall(r"<entry[ >]",body))
            rec.update(status=r.status, items=items, is_feed=items>0,
                       sample=re.sub(r"\s+"," ",(re.search(r"<item[\s\S]*?<title>(.*?)</title>",body) or re.search(r"<entry[\s\S]*?<title[^>]*>(.*?)</title>",body) or [None,""])[1])[:120] if items else "")
    except urllib.error.HTTPError as e:
        rec.update(status=e.code, items=0, is_feed=False)
    except Exception as e:
        rec.update(status=-1, items=0, is_feed=False, err=str(e)[:80])
    out.append(rec)
import os
os.makedirs("data",exist_ok=True)
json.dump({"probed_at":datetime.datetime.utcnow().isoformat()+"Z","results":out},
          open("data/rss_probe.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
ok=[r["name"] for r in out if r["is_feed"]]
print("FEED_OK %d/%d: %s" % (len(ok),len(out),", ".join(ok)))
