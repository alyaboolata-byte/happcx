import json,os,pathlib,re,time
from notifier import get
event=json.loads(pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text())
config=json.loads(pathlib.Path('.indexnow/sites.json').read_text());site=config['sites'][0]
name=os.getenv('GITHUB_EVENT_NAME')
sha=None
if name=='status' and event.get('state')=='success' and event.get('context','').startswith('Vercel'):
 target=event.get('target_url') or ''
 if target.startswith('https://vercel.com/li88s-projects/'+config['project']+'/'): sha=event.get('sha')
elif name=='deployment_status':
 dep=event.get('deployment',{});status=event.get('deployment_status',{})
 if status.get('state')=='success' and (dep.get('production_environment') is True or dep.get('environment','').lower()=='production'):
  sha=dep.get('sha')
elif name=='workflow_dispatch': sha=os.getenv('GITHUB_SHA')
ready=False
if sha and re.fullmatch(r'[a-f0-9]{40}',sha):
 for attempt in range(6):
  try:
   s,h,b=get(site['markerUrl'],site);marker=json.loads(b) if s==200 else {}
   if marker.get('sha')==sha and marker.get('projectId')==site['projectId']: ready=True;break
  except Exception: pass
  if attempt<5: time.sleep(10)
with open(os.environ['GITHUB_OUTPUT'],'a') as f: f.write('ready='+str(ready).lower()+'\nsha='+str(sha or '')+'\n')
print('Published production revision verified' if ready else 'Skipped: event does not identify the currently published production revision')
