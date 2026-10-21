"""Wait until Vercel serves this exact production Git revision."""
import json,os,pathlib,re,time
from notifier import get
config=json.loads(pathlib.Path('.indexnow/sites.json').read_text());site=config['sites'][0]
sha=os.environ['GITHUB_SHA']
if not re.fullmatch(r'[a-f0-9]{40}',sha): raise SystemExit('Invalid Git revision')
ready=False
for attempt in range(120):
 try:
  status,headers,body=get(site['markerUrl'],site)
  marker=json.loads(body) if status==200 else {}
  if marker.get('sha')==sha and marker.get('projectId')==site['projectId']: ready=True;break
 except Exception: pass
 if attempt%6==0: print('Waiting for the matching production deployment...',flush=True)
 if attempt<119: time.sleep(10)
if not ready: raise SystemExit('The production revision was not published within 20 minutes; no URLs submitted')
with open(os.environ['GITHUB_OUTPUT'],'a') as f: f.write('ready=true\nsha='+sha+'\n')
print('Published production revision verified')
