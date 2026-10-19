
import urllib.request, urllib.parse, ssl, json, re, os, datetime, subprocess, time
from concurrent.futures import ThreadPoolExecutor
CTX=ssl.create_default_context();CTX.check_hostname=False;CTX.verify_mode=ssl.CERT_NONE
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
def gnews(d):
    q=urllib.parse.quote("site:%s (china OR chinese OR taiwan OR taipei OR beijing OR \"south china sea\" OR \"rare earth\" OR \"critical mineral\" OR \"indo-pacific\" OR \"export control\" OR semiconductor)"%d)
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"%q
G=["usni.org","thedrive.com","stripes.com","maritime-executive.com","c4isrnet.com","naval-technology.com","miningweekly.com","spglobal.com","fastmarkets.com","kitco.com","argusmedia.com","semianalysis.com","theregister.com","piie.com","cnbc.com","csis.org","usgs.gov","eia.gov","bis.gov","ustr.gov","nato.int","uscc.gov","commerce.gov"]
DIRECT=[("state.gov_RSS","https://www.state.gov/feed/"),("treasury_RSS","https://home.treasury.gov/rss.xml"),("ustr_RSS","https://ustr.gov/rss.xml"),("whitehouse_RSS","https://www.whitehouse.gov/news/rss"),("navalnews_RSS","https://www.navalnews.com/feed/"),("mining_RSS","https://www.mining.com/feed/"),("oilprice_RSS","https://oilprice.com/rss/main"),("defensenews_RSS","https://www.defensenews.com/arc/outboundfeeds/rss/")]
CN=re.compile(r"china|chinese|taiwan|taipei|beijing|hong kong|xinjiang|rare earth|critical mineral|south china sea|indo-pacific|export control|semiconductor|lithium|graphite|nato|quad|mineral|tariff",re.I)
def probe(item):
    name,url=item
    try:
        req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/rss+xml,application/xml,*/*"})
        b=urllib.request.urlopen(req,timeout=22,context=CTX).read(1500000).decode("utf-8","ignore")
        items=re.findall(r"<item[\s\S]*?</item>",b)
        titles=re.findall(r"<item[\s\S]*?<title>(.*?)</title>",b)
        cn=[t for t in titles if CN.search(t)]
        dates=re.findall(r"<pubDate>(.*?)</pubDate>",b)
        return {"name":name,"items":len(items),"china":len(cn),"latest":dates[0][:22] if dates else "","sample":cn[:2]}
    except Exception as e:
        return {"name":name,"items":0,"china":0,"err":repr(e)[:80]}
tasks=[(d,gnews(d)) for d in G]+DIRECT
with ThreadPoolExecutor(max_workers=8) as ex:
    res=list(ex.map(probe,tasks))
out={"diag_at":datetime.datetime.utcnow().isoformat()+"Z","results":res}
os.makedirs("data",exist_ok=True)
json.dump(out,open("data/rss_probe.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for r in sorted(res,key=lambda x:-x.get("china",0)):
    print(r["name"],r.get("items"),r.get("china"),r.get("latest",""),r.get("err",""))
def sh(cc):return subprocess.run(cc,shell=True,capture_output=True,text=True)
sh('git config user.name "github-actions[bot]"');sh('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"')
sh("git add data/rss_probe.json")
if sh("git diff --staged --quiet").returncode!=0:
    sh('git commit -m "data: hardnews probe"')
    for i in range(3):
        if sh("git pull --rebase origin main && git push").returncode==0:print("PUSHED");break
        time.sleep(6)
else:print("no change")
