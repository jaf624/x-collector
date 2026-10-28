import json, urllib.request, ssl, sys
import intel_collect as ic
srcs=[s for s in json.load(open('targets/institute_sources.json')) if s.get('host')=='news.google.com/bleeping'][0]
st,body=ic.feed_get(srcs['feed_url'])
print('feed_get HTTP',st,'len',len(body or ''))
items,ft=ic.parse_rss_items(body,srcs['feed_url'])
print('parsed items',len(items))
for it in items[:6]:
    real=ic.resolve_gnews_url(it['link'])
    blob=it['title']+' '+it['text'][:1500]
    print('---')
    print(' title:',it['title'][:60])
    print(' real:',real[:80])
    print(' hardnews:',ic.is_hardnews_url(real),'topic:',bool(ic.re.compile(ic.TOPIC_RE).search(blob)),'china:',bool(ic._china_ok(ic.host_of(real),it['title'],it['text'][:800],it['text'][:1500])),'soft:',ic.soft_news(it['title']),'textlen:',len(it['text']))
