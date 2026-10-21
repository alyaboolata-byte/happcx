#!/usr/bin/env python3
"""IndexNow: crawl only allowlisted HTTPS hosts and notify after publication."""
import argparse, concurrent.futures as cf, hashlib, json, os, pathlib, re, time
import urllib.request as R, urllib.error as E, urllib.parse as U, urllib.robotparser as RP
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

UA='IndexNowNotifier/1.0'
class NoRedirect(R.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
OPENER=R.build_opener(NoRedirect)
class Head(HTMLParser):
 def __init__(self): super().__init__(); self.canon=[]; self.robots=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='link' and 'canonical' in a.get('rel','').lower().split(): self.canon.append(a.get('href',''))
  if tag=='meta' and a.get('name','').lower() in ('robots','bingbot'): self.robots.append(a.get('content',''))
def valid(url,site):
 try:
  p=U.urlsplit(url)
  return p.scheme=='https' and p.netloc==site['host'] and not p.fragment and not p.username and (p.path or '/').startswith(site.get('scope','/'))
 except ValueError: return False
def get(url,site):
 if not valid(url,site): raise ValueError('URL outside approved host or scope')
 try:
  with OPENER.open(R.Request(url,headers={'User-Agent':UA,'Accept-Encoding':'identity'}),timeout=25) as r:
   b=r.read(10_000_001)
   if len(b)>10_000_000: raise ValueError('Response too large')
   return r.status,dict(r.headers.items()),b
 except E.HTTPError as e: return e.code,dict(e.headers.items()),e.read(4096)
def header(h,key): return ','.join(str(v) for k,v in h.items() if k.lower()==key)
def robots(site):
 url='https://'+site['host']+'/robots.txt'
 # GitHub Pages subdirectory sites still use the host-level robots file.
 root={**site,'scope':'/'}
 status,h,b=get(url,root)
 if status==404: b=b''
 elif status!=200: raise ValueError('robots.txt HTTP '+str(status))
 if status==200 and 'html' in header(h,'content-type').lower(): raise ValueError('robots.txt contains HTML')
 p=RP.RobotFileParser(); p.parse(b.decode('utf-8','replace').splitlines())
 return p,status
def sitemap(site):
 pending=[site.get('sitemap','https://'+site['host']+'/sitemap.xml')]; seen=set(); urls=[]; statuses=[]
 while pending:
  url=pending.pop()
  if url in seen: continue
  if len(seen)>=100: raise ValueError('Sitemap index limit exceeded')
  seen.add(url); s,h,b=get(url,site); statuses.append({'url':url,'status':s})
  if s==404 and len(seen)==1: return site.get('fallbackUrls',[]),statuses
  if s!=200: raise ValueError('Sitemap HTTP '+str(s)+': '+url)
  root=ET.fromstring(b); kind=root.tag.split('}')[-1]
  if kind not in ('urlset','sitemapindex'): raise ValueError('Invalid sitemap document')
  for child in root:
   loc=next((x.text.strip() for x in child if x.tag.split('}')[-1]=='loc' and x.text),'')
   if not valid(loc,site): raise ValueError('Sitemap includes unapproved URL: '+loc)
   (pending if kind=='sitemapindex' else urls).append(loc)
  if len(urls)>100000: raise ValueError('URL limit exceeded')
 return list(dict.fromkeys(urls)),statuses
def check_page(url,site,rp):
 row={'url':url}
 try:
  if not all(rp.can_fetch(bot,url) for bot in ('bingbot','IndexNow','*')): return {**row,'excluded':'robots disallow'}
  s,h,b=get(url,site); row['status']=s
  if s!=200: return {**row,'excluded':'HTTP '+str(s)}
  if 'text/html' not in header(h,'content-type').lower(): return {**row,'excluded':'not HTML'}
  head=Head(); head.feed(b.decode('utf-8','replace'))
  directives=','.join(head.robots)+','+header(h,'x-robots-tag')
  if re.search(r'\b(noindex|none)\b',directives,re.I): return {**row,'excluded':'noindex'}
  if len(set(head.canon))>1: return {**row,'excluded':'conflicting canonicals'}
  canonical=U.urljoin(url,head.canon[0]) if head.canon else url
  # Normalize an empty origin path to /, without changing case or path semantics.
  def norm(v):
   p=U.urlsplit(v); return U.urlunsplit((p.scheme,p.netloc,p.path or '/',p.query,''))
  if not valid(canonical,site) or norm(canonical)!=norm(url): return {**row,'excluded':'noncanonical','canonical':canonical}
  row.update(hash=hashlib.sha256(b).hexdigest(),canonical=canonical,canonicalSource='link' if head.canon else 'implicit self')
 except Exception as e: row['excluded']='fetch error: '+str(e)
 return row
def post(site,urls):
 payload=json.dumps({'host':site['host'],'key':site['key'],'keyLocation':site['keyLocation'],'urlList':urls}).encode()
 req=R.Request('https://www.bing.com/indexnow',data=payload,headers={'Content-Type':'application/json; charset=utf-8','User-Agent':UA},method='POST')
 for attempt in range(3):
  try:
   with OPENER.open(req,timeout=30) as r: status,body=r.status,r.read(4096).decode('utf-8','replace')
  except E.HTTPError as e:
   status,body=e.code,e.read(4096).decode('utf-8','replace')
   if status==429: break # honour rate limits; retry on a later successful deployment
  except E.URLError as e:
   status,body=0,str(e)
  if status not in (0,500,502,503,504): break
  if attempt<2: time.sleep(2**attempt)
 return {'status':status,'body':body,'count':len(urls)}
def run(site,state,submit=False,full=False,require_sha=None):
 report={'host':site['host'],'keyLocation':site['keyLocation'],'submitted':0,'api':[]}
 previous=state.get(site['host'],{})
 try:
  if require_sha:
   marker=site['markerUrl']; s,h,b=get(marker,site)
   data=json.loads(b) if s==200 else {}
   if data.get('sha')!=require_sha or data.get('projectId')!=site['projectId']: raise ValueError('Production revision marker does not match the successful deployment')
  rp,rs=robots(site); report['robotsStatus']=rs
  candidates,sm=sitemap(site); report['sitemaps']=sm; report['candidates']=len(candidates)
  with cf.ThreadPoolExecutor(max_workers=5) as ex: pages=list(ex.map(lambda x:check_page(x,site,rp),candidates))
  report['pages']=pages; accepted=[p for p in pages if 'hash' in p]
  report['eligible']=len(accepted); report['excluded']=len(pages)-len(accepted)
  changed=[p['url'] for p in accepted if full or previous.get(p['url'])!=p['hash']]
  report['changed']=len(changed)
  s,h,b=get(site['keyLocation'],site)
  report['keyStatus']=s
  if s!=200 or b.decode('utf-8','replace').strip()!=site['key'] or 'html' in header(h,'content-type').lower(): raise ValueError('Key file missing or content mismatch (HTTP '+str(s)+')')
  if not all(rp.can_fetch(bot,site['keyLocation']) for bot in ('bingbot','IndexNow','*')): raise ValueError('Key file blocked by robots.txt')
  current={p['url']:p['hash'] for p in accepted}
  if submit:
   for start in range(0,len(changed),10000):
    batch=changed[start:start+10000]; result=post(site,batch); report['api'].append(result)
    if result['status'] not in (200,202): raise ValueError('Bing rejected submission: HTTP '+str(result['status']))
    report['submitted']+=len(batch)
   if any(p.get('excluded','').startswith('fetch error') or p.get('status',0)>=500 or p.get('status')==429 for p in pages):
    raise ValueError('Some pages could not be checked; state retained for retry')
   state[site['host']]=current
  report['result']='submitted' if submit else 'checked'
 except Exception as e: report['result']='error';report['error']=str(e)
 return report
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',default='.indexnow/sites.json');ap.add_argument('--state',default='.indexnow/state.json');ap.add_argument('--report',default='.indexnow/report.json');ap.add_argument('--submit',action='store_true');ap.add_argument('--full',action='store_true');ap.add_argument('--require-sha');args=ap.parse_args()
 sites=json.loads(pathlib.Path(args.config).read_text())['sites']; statepath=pathlib.Path(args.state)
 state=json.loads(statepath.read_text()) if statepath.exists() else {}
 def task(site):
  r=run(site,state,args.submit,args.full,args.require_sha)
  print(json.dumps({k:v for k,v in r.items() if k not in ('pages','sitemaps','keyLocation')},ensure_ascii=False),flush=True)
  return r
 with cf.ThreadPoolExecutor(max_workers=3) as ex: reports=list(ex.map(task,sites))
 pathlib.Path(args.report).parent.mkdir(parents=True,exist_ok=True);pathlib.Path(args.report).write_text(json.dumps(reports,ensure_ascii=False,indent=2))
 if args.submit: statepath.parent.mkdir(parents=True,exist_ok=True);statepath.write_text(json.dumps(state,ensure_ascii=False,indent=2))
 if any(r['result']=='error' for r in reports): raise SystemExit(1)
if __name__=='__main__': main()
