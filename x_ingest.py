#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X 内容国内入库器：拉取海外采集器产出的 x_feed.json（raw.githubusercontent 国内可达），
经清洗/评分/理论标注/图片本地化后写入 prompts 表，网站即可展示。
- 幂等：以 x:ID 生成 content_hash，重复自动跳过
- --dry-run 只解析不写库；--file 用本地json测试
"""
import os, re, json, ssl, sys, hashlib, urllib.request, datetime, sqlite3, time

BASE='/opt/prompthub'
DB=os.path.join(BASE,'data/prompts.db')
ING=os.path.join(BASE,'ingest'); os.makedirs(ING,exist_ok=True)
IMG_DIR=os.path.join(BASE,'static/media/x'); os.makedirs(IMG_DIR,exist_ok=True)
URL_FILE=os.path.join(ING,'x_feed_urls.txt')
LOG=os.path.join(BASE,'logs/x_ingest.log'); os.makedirs(os.path.dirname(LOG),exist_ok=True)
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
H={'User-Agent':'Mozilla/5.0'}

def log(m):
    line=f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line)
    with open(LOG,'a') as f: f.write(line+'\n')

def http(url,timeout=30,binary=False):
    req=urllib.request.Request(url,headers=H)
    with urllib.request.urlopen(req,timeout=timeout,context=CTX) as r:
        return r.read() if binary else r.read().decode('utf-8','ignore')

# ---------- 洗练 ----------
def clean_text(t):
    if not t: return ''
    t=re.sub(r'https?://t\.co/\S+','',t)          # 去短链
    t=re.sub(r'^RT\s*@[\w]+:\s*','',t)             # 去RT头
    t=re.sub(r'#([^#\s]+)#',r'\1',t)              # 去话题井号保留词
    t=t.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>')
    t=re.sub(r'[ \t]+',' ',t).strip()
    return t

def has_cn(s): return len(re.findall(r'[\u4e00-\u9fff]',s))

THEORY_MAP=[
 (('构图','视角','景别','前景','景深','三分','对称','光影','光线','布光','色调'),'摄影构图与光影理论'),
 (('角色','人设','人物','表情','姿态','服装','五官','气质'),'角色设定与人物刻画法'),
 (('风格','质感','画风','插画','写实','赛博','国风','油画','3d','bjd'),'风格化与材质表现理论'),
 (('--ar','--v','--q','seed','steps','cfg','采样','分辨率','参数','4k','8k'),'参数精确化与采样控制'),
 (('步骤','首先','然后','接着','第一步','1.','流程'),'链式思维(CoT)分步引导'),
 (('不要','避免','负面','negative','剔除','模糊','水印'),'负向约束与质量边界控制'),
 (('镜头','运镜','推拉摇移','特写','全景','转场','时长'),'影视镜头语言与运镜设计'),
 (('场景','环境','背景','空间','氛围','天气','时间'),'场景氛围与环境叙事法'),
]
def tag_theory(t):
    low=t.lower(); hit=[]
    for kws,name in THEORY_MAP:
        if any(k.lower() in low for k in kws) and name not in hit: hit.append(name)
    return '；'.join(hit[:4])

def score(t):
    n=len(t); s=72
    if n>=120: s+=4
    if n>=260: s+=5
    if n>=500: s+=4
    if re.search(r'[，。；、：]',t): s+=3
    if re.search(r'\d|--|#|\*|-',t): s+=2
    if tag_theory(t): s+=4
    if has_cn(t)>=40: s+=2
    return round(min(93.0,float(s)),2)

def make_title(t):
    head=re.split(r'[\n。！!？?]',t)[0][:22].strip()
    return head if len(head)>=6 else (t[:22].strip() or 'X精选AI提示词')

def localize_photos(photos,xid):
    paths=[]; meta=[]
    for i,p in enumerate(photos or []):
        u=p.get('url') if isinstance(p,dict) else str(p)
        if not u: continue
        fn=f"{xid}_{i}.jpg"; lp=os.path.join(IMG_DIR,fn); web=f"/static/media/x/{fn}"
        if not os.path.exists(lp):
            try: open(lp,'wb').write(http(u,40,True))
            except Exception: continue
        if os.path.exists(lp) and os.path.getsize(lp)>1500:
            paths.append(web); meta.append(p)
    return paths,meta

def build_record(r):
    xid=str(r.get('x_id') or '').strip()
    text=clean_text(r.get('text_raw',''))
    if not xid or len(text)<25: return None
    imgs,meta=localize_photos(r.get('photos'),xid)
    images_json=json.dumps(meta,ensure_ascii=False) if meta else '[]'
    theory=tag_theory(text)
    lang='zh' if has_cn(text)>=8 else 'en'
    return dict(
        xid=xid,title=make_title(text),content=text,
        source_url=r.get('url',''),author=r.get('screen_name',''),
        quality=score(text),image=(imgs[0] if imgs else ''),images=images_json,
        video=r.get('video',''),lang=lang,theory=theory,
        media_count=len(imgs),fav=int(r.get('fav') or 0),rt=int(r.get('retweet') or 0),
        cid='X精选',
    )

def load_feed(args):
    for a in args:
        if a=='--file': continue
    # --file path
    if '--file' in sys.argv:
        p=sys.argv[sys.argv.index('--file')+1]
        return json.loads(open(p,encoding='utf-8').read())
    urls=[l.strip() for l in open(URL_FILE).read().splitlines() if l.strip() and not l.startswith('#')] if os.path.exists(URL_FILE) else []
    feed=[]
    for u in urls:
        try: feed+=json.loads(http(u)); log(f'拉取成功 {u}')
        except Exception as e: log(f'拉取失败 {u} -> {e}')
    return feed

def main():
    dry='--dry-run' in sys.argv
    feed=load_feed(sys.argv[1:])
    log(f'feed条数 {len(feed)} dry={dry}')
    conn=sqlite3.connect(DB); c=conn.cursor(); ins=skip=err=0
    for r in feed:
        try:
            b=build_record(r)
            if not b: skip+=1; continue
            ch=hashlib.md5(('x:'+b['xid']).encode()).hexdigest()
            exist=c.execute('SELECT id FROM prompts WHERE content_hash=? OR source_url=?',(ch,b['source_url'])).fetchone()
            if exist: skip+=1; continue
            if dry:
                ins+=1; print('[dry]',b['xid'],b['author'],b['quality'],'图%d'%b['media_count'],b['title']); continue
            now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cols=("title,content,source,source_url,tags,language,quality_score,is_ai_processed,"
                  "content_hash,views,likes,author,category,created_at,updated_at,image_url,video_url,"
                  "platform,images,status,is_recommended,heat_score,source_type,media_type,media_count,"
                  "theory_applied,prompt_precision,originality_level")
            qs=",".join(["?"]*28)
            vals=(b['title'],b['content'],'X平台@'+b['author'],b['source_url'],'X精选,AI提示词',b['lang'],
                  b['quality'],1,ch,b['fav'],b['rt']+b['fav'],b['author'],'ai_prompt',now,now,
                  b['image'],b['video'],b['cid'],b['images'],'online',1,float(b['rt']+b['fav']),
                  'republished','image' if b['media_count'] else 'text',b['media_count'],
                  b['theory'],'结构化精准','high')
            c.execute(f"INSERT INTO prompts({cols}) VALUES({qs})", vals)
            ins+=1
        except Exception as e: err+=1; log('入库异常 '+str(e)[:120])
    if not dry: conn.commit()
    conn.close(); log(f'完成：新增{ins} 跳过{skip} 异常{err}')

if __name__=='__main__': main()
